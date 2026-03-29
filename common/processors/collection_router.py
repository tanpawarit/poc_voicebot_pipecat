"""Deterministic multi-step router for the collection flow."""

import logging
from typing import Mapping, Protocol

from pipecat.frames.frames import (
    EndFrame,
    ErrorFrame,
    Frame,
    InterimTranscriptionFrame,
    StartFrame,
    TTSSpeakFrame,
    TranscriptionFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from common.flows.collection import (
    CollectionFlowDefinition,
    CollectionIntent,
    CollectionStage,
    VerifyIntent,
)

logger = logging.getLogger(__name__)


class IntentClassifier(Protocol):
    async def classify_opening(
        self,
        transcript: str,
        state: Mapping[str, object] | None = None,
    ) -> CollectionIntent: ...

    async def classify_verify(
        self,
        transcript: str,
        state: Mapping[str, object] | None = None,
    ) -> VerifyIntent: ...


class CollectionRouterProcessor(FrameProcessor):
    """Drive the opening -> verify collection checkpoints using scripted prompts."""

    def __init__(
        self,
        *,
        flow_definition: CollectionFlowDefinition,
        classifier: IntentClassifier,
        state: Mapping[str, object] | None = None,
        max_retries_per_stage: int = 1,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._flow_definition = flow_definition
        self._classifier = classifier
        self._state = dict(state or {})
        self._max_retries_per_stage = max_retries_per_stage
        self._opening_sent = False
        self._conversation_completed = False
        self._current_stage = CollectionStage.OPENING
        self._stage_retry_counts = {
            CollectionStage.OPENING: 0,
            CollectionStage.VERIFY: 0,
        }

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        # Unit tests may invoke the processor directly without a PipelineTask-backed setup.
        if not (isinstance(frame, StartFrame) and self._task_manager is None):
            await super().process_frame(frame, direction)

        if direction != FrameDirection.DOWNSTREAM:
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, StartFrame):
            await self.push_frame(frame, direction)
            if not self._opening_sent:
                self._opening_sent = True
                logger.info("Sending opening script for collection POC")
                await self._speak_prompt(CollectionStage.OPENING)
            return

        if self._conversation_completed:
            logger.debug("Ignoring frame after collection routing has completed: %s", type(frame))
            return

        if isinstance(frame, InterimTranscriptionFrame):
            return

        if isinstance(frame, ErrorFrame):
            logger.warning("Falling back after STT error: %s", frame.error)
            await self._push_fallback_and_end(reason="stt_error")
            return

        if isinstance(frame, TranscriptionFrame):
            transcript = frame.text.strip()
            if not transcript:
                await self._handle_empty_transcript()
                return

            if self._current_stage == CollectionStage.OPENING:
                await self._handle_opening_transcript(transcript)
                return

            if self._current_stage == CollectionStage.VERIFY:
                await self._handle_verify_transcript(transcript)
                return

        await self.push_frame(frame, direction)

    async def _handle_opening_transcript(self, transcript: str) -> None:
        try:
            intent = await self._classifier.classify_opening(transcript, self._state)
        except Exception:
            logger.exception("Opening intent classification failed for transcript: %s", transcript)
            await self._push_fallback_and_end(
                reason="opening_classifier_error",
                transcript=transcript,
            )
            return

        logger.info(
            "Routing collection transcript at opening checkpoint",
            extra={
                "event": "collection_route",
                "stage": self._current_stage.value,
                "intent": intent.value,
                "transcript": transcript,
            },
        )

        if intent == CollectionIntent.TARGET:
            self._current_stage = CollectionStage.VERIFY
            self._stage_retry_counts[CollectionStage.VERIFY] = 0
            await self._speak_prompt(CollectionStage.VERIFY)
            return

        if intent == CollectionIntent.UNKNOWN:
            await self._push_fallback_and_end(reason="opening_unknown", transcript=transcript)
            return

        await self._push_response_and_end(self._flow_definition.opening_response_for(intent))

    async def _handle_verify_transcript(self, transcript: str) -> None:
        try:
            intent = await self._classifier.classify_verify(transcript, self._state)
        except Exception:
            logger.exception("Verify intent classification failed for transcript: %s", transcript)
            await self._push_fallback_and_end(
                reason="verify_classifier_error",
                transcript=transcript,
            )
            return

        logger.info(
            "Routing collection transcript at verify checkpoint",
            extra={
                "event": "collection_route",
                "stage": self._current_stage.value,
                "intent": intent.value,
                "transcript": transcript,
            },
        )

        if intent == VerifyIntent.UNKNOWN:
            await self._push_fallback_and_end(reason="verify_unknown", transcript=transcript)
            return

        await self._push_response_and_end(self._flow_definition.verify_response_for(intent))

    async def _handle_empty_transcript(self) -> None:
        retry_count = self._stage_retry_counts[self._current_stage]
        if retry_count < self._max_retries_per_stage:
            self._stage_retry_counts[self._current_stage] += 1
            logger.info(
                "Retrying collection prompt after empty transcript",
                extra={
                    "event": "collection_retry",
                    "stage": self._current_stage.value,
                    "retry_count": self._stage_retry_counts[self._current_stage],
                },
            )
            await self._speak_prompt(self._current_stage, retry=True)
            return

        logger.warning(
            "Retry limit exceeded for collection stage",
            extra={
                "event": "collection_retry_exceeded",
                "stage": self._current_stage.value,
                "retry_count": retry_count,
            },
        )
        await self._push_fallback_and_end(reason=f"{self._current_stage.value}_retry_exceeded")

    async def _speak_prompt(self, stage: CollectionStage, *, retry: bool = False) -> None:
        await self.push_frame(
            TTSSpeakFrame(self._flow_definition.prompt_for(stage, retry=retry), append_to_context=False)
        )

    async def _push_response_and_end(self, text: str) -> None:
        self._conversation_completed = True
        await self.push_frame(TTSSpeakFrame(text, append_to_context=False))
        await self.push_frame(EndFrame())

    async def _push_fallback_and_end(
        self,
        *,
        reason: str,
        transcript: str | None = None,
    ) -> None:
        logger.info(
            "Using fallback collection script",
            extra={"event": "collection_fallback", "reason": reason, "transcript": transcript or ""},
        )
        await self._push_response_and_end(self._flow_definition.fallback)
