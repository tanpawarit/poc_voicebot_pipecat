import logging

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
from common.flows import get_gemini_live_system_instruction
from common.transport import create_transport

logger = logging.getLogger(__name__)


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
    bootstrap = GeminiContextBootstrapProcessor(context=LLMContext())
    llm = GeminiLiveLLMService(
        api_key=settings.gemini_api_key,
        system_instruction=system_instruction,
        settings=GeminiLiveLLMService.Settings(
            model=settings.gemini_live_model,
            voice=settings.gemini_live_voice,
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
