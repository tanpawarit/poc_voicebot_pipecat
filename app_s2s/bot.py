import logging

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.observers.turn_tracking_observer import TurnTrackingObserver
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.services.openai.stt import OpenAISTTService
from pipecat.services.openai.tts import OpenAITTSService
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transcriptions.language import Language

from common.config import settings
from common.flows import get_flow
from common.openai_intent_classifier import OpenAIIntentClassifier
from common.processors.collection_router import CollectionRouterProcessor
from common.transport import create_transport

logger = logging.getLogger(__name__)


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

    flow_definition = get_flow(settings.flow_name, state=state)
    classifier = OpenAIIntentClassifier(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        model=settings.openai_intent_model,
    )
    vad = VADProcessor(
        vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=settings.vad_stop_secs))
    )
    stt = OpenAISTTService(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        audio_passthrough=False,
        settings=OpenAISTTService.Settings(
            model=settings.openai_stt_model,
            language=Language.TH,
        ),
    )
    router = CollectionRouterProcessor(
        flow_definition=flow_definition,
        classifier=classifier,
        state=state,
    )
    tts = OpenAITTSService(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        sample_rate=24000,
        settings=OpenAITTSService.Settings(
            model=settings.openai_tts_model,
            voice=settings.openai_tts_voice,
            language=Language.TH,
            instructions=settings.openai_tts_instructions,
            speed=settings.openai_tts_speed,
        ),
    )
    pipeline = Pipeline(
        [
            transport.input(),
            vad,
            stt,
            router,
            tts,
            transport.output(),
        ]
    )

    turn_observer = TurnTrackingObserver(
        turn_end_timeout_secs=settings.turn_end_timeout_secs
    )

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
        logger.info("Starting S2S bot with OpenAI deterministic flow", extra={"event": "bot_start"})
        await runner.run(task)
    except Exception:
        logger.exception("Bot pipeline error")
    finally:
        logger.info("Bot session ended", extra={"event": "bot_end"})
