import logging
from typing import Optional

from google.genai.types import (
    AudioTranscriptionConfig,
    AutomaticActivityDetection,
    ContextWindowCompressionConfig,
    GenerationConfig,
    LiveConnectConfig,
    MediaResolution,
    Modality,
    RealtimeInputConfig,
    SessionResumptionConfig,
    SlidingWindow,
    SpeechConfig,
    VoiceConfig,
)
from pipecat.frames.frames import (
    ClientConnectedFrame,
    EndFrame,
    Frame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    StartFrame,
)
from pipecat.observers.turn_tracking_observer import TurnTrackingObserver
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection

from common.config import settings
from common.flows import (
    get_gemini_live_initial_messages,
    get_gemini_live_system_instruction,
)
from common.transport import create_transport

logger = logging.getLogger(__name__)


class LanguagePinnedGeminiLiveLLMService(GeminiLiveLLMService):
    """Gemini Live service with explicit transcription language hints."""

    def _build_audio_transcription_config(self) -> AudioTranscriptionConfig:
        language = str(self._settings.language).strip() if self._settings.language else ""
        if not language:
            return AudioTranscriptionConfig()
        return AudioTranscriptionConfig(languageCodes=[language])

    async def _connect(self, session_resumption_handle: Optional[str] = None):
        """Establish client connection to Gemini Live API with pinned STT language."""
        if self._session:
            return

        if session_resumption_handle:
            logger.info(
                "Connecting to Gemini service with session_resumption_handle: %s",
                session_resumption_handle,
            )
        else:
            logger.info("Connecting to Gemini service")
        try:
            transcription_config = self._build_audio_transcription_config()
            config = LiveConnectConfig(
                generation_config=GenerationConfig(
                    frequency_penalty=self._settings.frequency_penalty,
                    max_output_tokens=self._settings.max_tokens,
                    presence_penalty=self._settings.presence_penalty,
                    temperature=self._settings.temperature,
                    top_k=self._settings.top_k,
                    top_p=self._settings.top_p,
                    response_modalities=[Modality(self._settings.modalities.value)],
                    speech_config=SpeechConfig(
                        voiceConfig=VoiceConfig(
                            prebuiltVoiceConfig={"voiceName": self._settings.voice}
                        ),
                        languageCode=str(self._settings.language),
                    ),
                    media_resolution=MediaResolution(self._settings.media_resolution.value),
                ),
                input_audio_transcription=transcription_config,
                output_audio_transcription=transcription_config,
                session_resumption=SessionResumptionConfig(handle=session_resumption_handle),
            )

            history_config = self._get_history_config()
            if history_config:
                config.history_config = history_config

            cwc = self._settings.context_window_compression or {}
            if cwc.get("enabled", False):
                compression_config = ContextWindowCompressionConfig()
                compression_config.sliding_window = SlidingWindow()

                trigger_tokens = cwc.get("trigger_tokens")
                if trigger_tokens is not None:
                    compression_config.trigger_tokens = trigger_tokens

                config.context_window_compression = compression_config

            if self._settings.thinking:
                config.thinking_config = self._settings.thinking

            if self._settings.enable_affective_dialog:
                config.enable_affective_dialog = self._settings.enable_affective_dialog

            if self._settings.proactivity:
                config.proactivity = self._settings.proactivity

            if self._settings.vad:
                vad_config = AutomaticActivityDetection()
                vad_params = self._settings.vad
                has_vad_settings = False

                if vad_params.disabled is not None:
                    vad_config.disabled = vad_params.disabled
                    has_vad_settings = True

                if vad_params.start_sensitivity:
                    vad_config.start_of_speech_sensitivity = vad_params.start_sensitivity
                    has_vad_settings = True

                if vad_params.end_sensitivity:
                    vad_config.end_of_speech_sensitivity = vad_params.end_sensitivity
                    has_vad_settings = True

                if vad_params.prefix_padding_ms is not None:
                    vad_config.prefix_padding_ms = vad_params.prefix_padding_ms
                    has_vad_settings = True

                if vad_params.silence_duration_ms is not None:
                    vad_config.silence_duration_ms = vad_params.silence_duration_ms
                    has_vad_settings = True

                if has_vad_settings:
                    config.realtime_input_config = RealtimeInputConfig(
                        automatic_activity_detection=vad_config
                    )

            adapter = self.get_llm_adapter()
            system_instruction = None
            tools = None
            if self._context:
                params = adapter.get_llm_invocation_params(
                    self._context, system_instruction=self._system_instruction_from_init
                )
                system_instruction = params["system_instruction"]
                tools = params["tools"]
            else:
                system_instruction = self._system_instruction_from_init
            if not tools:
                tools = adapter.from_standard_tools(self._tools_from_init)
            if system_instruction:
                config.system_instruction = system_instruction
            if tools:
                config.tools = tools

            self._connection_task = self.create_task(self._connection_task_handler(config=config))
        except Exception as e:
            await self.push_error(error_msg=f"Initialization error: {e}", exception=e)


class GeminiContextBootstrapProcessor(FrameProcessor):
    """Seed Gemini after the WebRTC client is ready to receive the opening audio."""

    def __init__(self, *, context: LLMContext, **kwargs) -> None:
        super().__init__(**kwargs)
        self._context = context
        self._seeded = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        if not (isinstance(frame, StartFrame) and self._task_manager is None):
            await super().process_frame(frame, direction)

        await self.push_frame(frame, direction)

        if (
            direction == FrameDirection.DOWNSTREAM
            and isinstance(frame, ClientConnectedFrame)
            and not self._seeded
        ):
            self._seeded = True
            logger.info(
                "Seeding Gemini Live context after client connection",
                extra={"event": "gemini_bootstrap"},
            )
            await self.push_frame(LLMContextFrame(self._context), direction)


class EndCallAfterResponsesProcessor(FrameProcessor):
    """End the call once Gemini has delivered the opening and one scripted reply."""

    def __init__(self, *, response_limit: int = 2, **kwargs) -> None:
        super().__init__(**kwargs)
        self._response_limit = response_limit
        self._response_count = 0
        self._end_queued = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        if not (isinstance(frame, StartFrame) and self._task_manager is None):
            await super().process_frame(frame, direction)

        await self.push_frame(frame, direction)

        if (
            direction == FrameDirection.DOWNSTREAM
            and isinstance(frame, LLMFullResponseEndFrame)
            and not self._end_queued
        ):
            self._response_count += 1
            logger.info(
                "Gemini Live response completed",
                extra={"event": "gemini_response_end", "count": self._response_count},
            )
            if self._response_count >= self._response_limit:
                self._end_queued = True
                logger.info(
                    "Ending Gemini Live session after scripted response",
                    extra={"event": "bot_script_complete", "count": self._response_count},
                )
                await self.push_frame(EndFrame(reason="script_complete"), direction)


async def run_bot(connection: SmallWebRTCConnection) -> None:
    transport = create_transport(connection)
    state: dict[str, object] = {}

    if settings.flow_name == "collection":
        from common.flows.mock_crm import MOCK_CUSTOMER

        state.update(MOCK_CUSTOMER)
        logger.info(
            "Injected mock CRM data for collection flow",
            extra={"event": "crm_inject", "customer": MOCK_CUSTOMER.get("customer_name")},
        )

    system_instruction = get_gemini_live_system_instruction(settings.flow_name, state=state)
    initial_messages = get_gemini_live_initial_messages(settings.flow_name, state=state)
    bootstrap = GeminiContextBootstrapProcessor(context=LLMContext(messages=initial_messages))
    llm = LanguagePinnedGeminiLiveLLMService(
        api_key=settings.gemini_api_key,
        system_instruction=system_instruction,
        settings=LanguagePinnedGeminiLiveLLMService.Settings(
            model=settings.gemini_live_model,
            voice=settings.gemini_live_voice,
            language=settings.gemini_live_language,
        ),
    )
    session_controller = EndCallAfterResponsesProcessor(response_limit=2)

    pipeline = Pipeline(
        [
            transport.input(),
            bootstrap,
            llm,
            session_controller,
            transport.output(),
        ]
    )

    turn_observer = TurnTrackingObserver(turn_end_timeout_secs=2.0)

    @turn_observer.event_handler("on_turn_ended")
    async def on_turn_ended(
        observer: TurnTrackingObserver,
        turn_count: int,
        duration: float,
        was_interrupted: bool,
    ) -> None:
        status = "interrupted" if was_interrupted else "completed"
        logger.info(
            f"Turn {turn_count} {status} after {duration:.2f}s",
            extra={"event": "turn_ended", "turn": turn_count, "duration": duration},
        )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=False,
            audio_in_sample_rate=16000,
            audio_out_sample_rate=24000,
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        observers=[turn_observer],
    )

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport_instance: SmallWebRTCConnection) -> None:
        logger.info("Client disconnected", extra={"event": "client_disconnected"})
        await task.cancel()

    runner = PipelineRunner()
    try:
        logger.info("Starting S2S bot with Gemini Live scripted flow", extra={"event": "bot_start"})
        await runner.run(task)
    except Exception:
        logger.exception("Bot pipeline error")
    finally:
        logger.info("Bot session ended", extra={"event": "bot_end"})
