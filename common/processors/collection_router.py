"""Deterministic router from user transcript to a scripted collection response."""

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

from common.flows.collection import CollectionFlowDefinition, CollectionIntent

logger = logging.getLogger(__name__)


class IntentClassifier(Protocol):
    async def classify(
        self,
        transcript: str,
        state: Mapping[str, object] | None = None,
    ) -> CollectionIntent: ...


class CollectionRouterProcessor(FrameProcessor):
    """Speak the opening, classify one final transcript, then speak a scripted reply."""

    def __init__(
        self,
        *,
        flow_definition: CollectionFlowDefinition,
        classifier: IntentClassifier,
        state: Mapping[str, object] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._flow_definition = flow_definition
        self._classifier = classifier
        self._state = dict(state or {})
        self._opening_sent = False
        self._handled_transcript = False

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
                await self.push_frame(
                    TTSSpeakFrame(self._flow_definition.opening, append_to_context=False)
                )
            return

        if isinstance(frame, InterimTranscriptionFrame):
            return

        if isinstance(frame, ErrorFrame) and not self._handled_transcript:
            self._handled_transcript = True
            logger.warning("Falling back after STT error: %s", frame.error)
            await self._push_fallback_and_end(reason="stt_error")
            return

        if isinstance(frame, TranscriptionFrame):
            if self._handled_transcript:
                logger.debug("Ignoring transcript after routing has already completed")
                return

            self._handled_transcript = True
            transcript = frame.text.strip()
            if not transcript:
                logger.warning("Falling back after empty transcript")
                await self._push_fallback_and_end(reason="empty_transcript")
                return

            try:
                intent = await self._classifier.classify(transcript, self._state)
            except Exception:
                logger.exception("Intent classification failed for transcript: %s", transcript)
                await self._push_fallback_and_end(
                    reason="classifier_error",
                    transcript=transcript,
                )
                return

            response_text = self._flow_definition.response_for(intent)
            logger.info(
                "Routing collection transcript to scripted response",
                extra={"event": "collection_route", "intent": intent.value, "transcript": transcript},
            )
            await self.push_frame(TTSSpeakFrame(response_text, append_to_context=False))
            await self.push_frame(EndFrame())
            return

        await self.push_frame(frame, direction)

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
        await self.push_frame(TTSSpeakFrame(self._flow_definition.fallback, append_to_context=False))
        await self.push_frame(EndFrame())
