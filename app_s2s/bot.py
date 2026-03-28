import logging

from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.observers.turn_tracking_observer import TurnTrackingObserver
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.services.google.gemini_live import GeminiLiveLLMService
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.turns.user_start import MinWordsUserTurnStartStrategy
from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies

from pipecat_flows import FlowManager

from common.config import settings
from common.flows import get_flow
from common.transport import create_transport

logger = logging.getLogger(__name__)


async def run_bot(connection: SmallWebRTCConnection) -> None:
    transport = create_transport(connection)

    flow_system_instruction = None
    flow_global_functions = []
    if settings.flow_name == "collection":
        from common.flows.collection import ROLE_CONTENT, get_global_functions

        flow_system_instruction = ROLE_CONTENT
        flow_global_functions = get_global_functions()

    llm = GeminiLiveLLMService(
        api_key=settings.google_api_key,
        settings=GeminiLiveLLMService.Settings(
            voice="Kore",
            language="th-TH",
            system_instruction=flow_system_instruction,
            temperature=0.0,
            top_p=0.1,
            top_k=1,
            max_tokens=512,
        ),
        inference_on_context_initialization=True,
    )

    context = LLMContext()
    context_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            user_turn_strategies=UserTurnStrategies(
                start=[MinWordsUserTurnStartStrategy(min_words=2)],
                stop=[
                    TurnAnalyzerUserTurnStopStrategy(
                        turn_analyzer=LocalSmartTurnAnalyzerV3()
                    )
                ],
            ),
            vad_analyzer=SileroVADAnalyzer(
                params=VADParams(stop_secs=0.3)
            ),
        ),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            context_aggregator.user(),
            llm,
            context_aggregator.assistant(),
            transport.output(),
        ]
    )

    turn_observer = TurnTrackingObserver(turn_end_timeout_secs=1.0)

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
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        observers=[turn_observer],
    )

    flow_manager = FlowManager(
        task=task,
        llm=llm,
        context_aggregator=context_aggregator,
        global_functions=flow_global_functions,
    )

    # ── Inject CRM context into state ──────────────────────────────────────
    # Must happen BEFORE get_flow() so the opening node prompt is formatted
    # with real customer data. In production: replace with a CRM API call.
    if settings.flow_name == "collection":
        from common.flows.mock_crm import MOCK_CUSTOMER
        flow_manager.state.update(MOCK_CUSTOMER)
        logger.info(
            "Injected mock CRM data for collection flow",
            extra={"event": "crm_inject", "customer": MOCK_CUSTOMER.get("customer_name")},
        )
    # ───────────────────────────────────────────────────────────────────────

    initial_node = get_flow(settings.flow_name, state=flow_manager.state)


    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport_instance: SmallWebRTCConnection) -> None:
        logger.info("Client disconnected", extra={"event": "client_disconnected"})
        await task.cancel()

    runner = PipelineRunner()
    try:
        logger.info("Starting S2S bot, initializing flow", extra={"event": "bot_start"})
        await flow_manager.initialize(initial_node=initial_node)
        await runner.run(task)
    except Exception:
        logger.exception("Bot pipeline error")
    finally:
        logger.info("Bot session ended", extra={"event": "bot_end"})
