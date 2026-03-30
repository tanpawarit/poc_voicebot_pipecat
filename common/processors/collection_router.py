"""LLM-orchestrated multi-step router for the scripted collection flow."""

import asyncio
import logging
from contextlib import suppress
from enum import StrEnum
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

from common.flows.collection import CollectionFlowDefinition, CollectionStage, FAQIntent, StageIntent

logger = logging.getLogger(__name__)


class IntentClassifier(Protocol):
    async def classify_stage(
        self,
        stage: CollectionStage,
        transcript: str,
        state: Mapping[str, object] | None = None,
    ) -> StageIntent: ...

    async def classify_faq(
        self,
        transcript: str,
        state: Mapping[str, object] | None = None,
    ) -> FAQIntent: ...


class CollectionRouterProcessor(FrameProcessor):
    """Drive the scripted collection flow while letting OpenAI choose the transition."""

    def __init__(
        self,
        *,
        flow_definition: CollectionFlowDefinition,
        classifier: IntentClassifier,
        state: Mapping[str, object] | None = None,
        start_stage: CollectionStage | None = None,
        max_retries_per_stage: int = 1,
        transcript_debounce_secs: float = 0.0,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._flow_definition = flow_definition
        self._classifier = classifier
        self._state = dict(state or {})
        self._max_retries_per_stage = max_retries_per_stage
        self._transcript_debounce_secs = transcript_debounce_secs
        self._initial_prompt_sent = False
        self._conversation_completed = False
        self._current_stage = start_stage or flow_definition.default_stage
        self._stage_retry_counts = {stage: 0 for stage in flow_definition.stages}
        self._pending_transcript_stage: CollectionStage | None = None
        self._pending_transcript_parts: list[str] = []
        self._debounce_task: asyncio.Task[None] | None = None
        self._debounce_lock = asyncio.Lock()

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        # Unit tests may invoke the processor directly without a PipelineTask-backed setup.
        if not (isinstance(frame, StartFrame) and self._task_manager is None):
            await super().process_frame(frame, direction)

        if direction != FrameDirection.DOWNSTREAM:
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, StartFrame):
            await self.push_frame(frame, direction)
            if not self._initial_prompt_sent:
                self._initial_prompt_sent = True
                logger.info("Sending initial collection script for stage %s", self._current_stage.value)
                await self._speak_prompt(self._current_stage)
            return

        if self._conversation_completed:
            logger.debug("Ignoring frame after collection routing has completed: %s", type(frame))
            return

        if isinstance(frame, InterimTranscriptionFrame):
            return

        if isinstance(frame, ErrorFrame):
            await self._clear_pending_transcript()
            logger.warning("Falling back after STT error: %s", frame.error)
            await self._push_fallback_and_end(reason="stt_error")
            return

        if isinstance(frame, TranscriptionFrame):
            transcript = frame.text.strip()
            if not transcript:
                await self._clear_pending_transcript()
                await self._handle_empty_transcript()
                return
            await self._handle_transcription(transcript)
            return

        await self.push_frame(frame, direction)

    async def cleanup(self):
        await self._clear_pending_transcript()
        await super().cleanup()

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

    async def _handle_transcription(self, transcript: str) -> None:
        if self._transcript_debounce_secs <= 0:
            logger.info(
                "Classifying transcript immediately at %s: %s",
                self._current_stage.value,
                transcript,
                extra={
                    "event": "collection_transcript_immediate",
                    "stage": self._current_stage.value,
                    "transcript": transcript,
                },
            )
            await self._route_transcript(transcript)
            return

        async with self._debounce_lock:
            if (
                self._pending_transcript_stage is not None
                and self._pending_transcript_stage != self._current_stage
            ):
                self._pending_transcript_parts.clear()

            self._pending_transcript_stage = self._current_stage
            self._pending_transcript_parts.append(transcript)

            logger.info(
                "Buffered transcript chunk at %s: %s",
                self._current_stage.value,
                transcript,
                extra={
                    "event": "collection_transcript_buffered",
                    "stage": self._current_stage.value,
                    "transcript": transcript,
                },
            )

            if self._debounce_task is not None:
                self._debounce_task.cancel()

            self._debounce_task = asyncio.create_task(
                self._flush_pending_transcript_after_delay(self._current_stage)
            )

    async def _flush_pending_transcript_after_delay(self, stage: CollectionStage) -> None:
        try:
            await asyncio.sleep(self._transcript_debounce_secs)
            transcript = await self._take_pending_transcript(stage)
            if transcript:
                logger.info(
                    "Classifying debounced transcript at %s: %s",
                    stage.value,
                    transcript,
                    extra={
                        "event": "collection_transcript_classify",
                        "stage": stage.value,
                        "transcript": transcript,
                    },
                )
                await self._route_transcript(transcript)
        except asyncio.CancelledError:
            raise

    async def _take_pending_transcript(self, stage: CollectionStage) -> str:
        async with self._debounce_lock:
            if self._pending_transcript_stage != stage or not self._pending_transcript_parts:
                return ""

            if self._current_stage != stage or self._conversation_completed:
                self._pending_transcript_stage = None
                self._pending_transcript_parts.clear()
                self._debounce_task = None
                return ""

            transcript = " ".join(self._pending_transcript_parts)
            self._pending_transcript_stage = None
            self._pending_transcript_parts.clear()
            self._debounce_task = None
            return transcript

    async def _clear_pending_transcript(self) -> None:
        task: asyncio.Task[None] | None = None
        async with self._debounce_lock:
            if self._debounce_task is not None:
                task = self._debounce_task
                self._debounce_task = None
            self._pending_transcript_stage = None
            self._pending_transcript_parts.clear()

        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def _route_transcript(self, transcript: str) -> None:
        try:
            intent = await self._classifier.classify_stage(
                self._current_stage,
                transcript,
                self._state,
            )
        except Exception:
            logger.exception(
                "Stage intent classification failed for stage %s and transcript: %s",
                self._current_stage.value,
                transcript,
            )
            await self._push_fallback_and_end(
                reason=f"{self._current_stage.value}_classifier_error",
                transcript=transcript,
            )
            return

        logger.info(
            "Collection intent resolved to %s for transcript: %s",
            intent.value,
            transcript,
            extra={
                "event": "collection_route",
                "stage": self._current_stage.value,
                "intent": intent.value,
                "transcript": transcript,
            },
        )

        if self._intent_is(intent, "unknown"):
            await self._push_fallback_and_end(
                reason=f"{self._current_stage.value}_unknown",
                transcript=transcript,
            )
            return

        if self._intent_is(intent, "faq"):
            await self._handle_faq_transcript(transcript)
            return

        route = self._flow_definition.route_for(self._current_stage, intent)
        if route.next_stage is not None:
            self._current_stage = route.next_stage
            self._stage_retry_counts[self._current_stage] = 0
            await self._speak_prompt(self._current_stage)
            return

        if route.response:
            await self._push_response_and_end(route.response)
            return

        await self._push_fallback_and_end(
            reason=f"{self._current_stage.value}_missing_route",
            transcript=transcript,
        )

    async def _handle_faq_transcript(self, transcript: str) -> None:
        try:
            intent = await self._classifier.classify_faq(transcript, self._state)
        except Exception:
            logger.exception("FAQ intent classification failed for transcript: %s", transcript)
            await self._push_fallback_and_end(reason="faq_classifier_error", transcript=transcript)
            return

        logger.info(
            "FAQ intent resolved to %s for transcript: %s",
            intent.value,
            transcript,
            extra={
                "event": "collection_faq_route",
                "stage": self._current_stage.value,
                "intent": intent.value,
                "transcript": transcript,
            },
        )

        if self._intent_is(intent, "unknown"):
            await self._push_fallback_and_end(reason="faq_unknown", transcript=transcript)
            return

        await self._push_response_and_end(self._flow_definition.faq_response_for(intent))

    def _intent_is(self, intent: StrEnum, value: str) -> bool:
        return intent.value == value

    async def _speak_prompt(self, stage: CollectionStage, *, retry: bool = False) -> None:
        await self.push_frame(
            TTSSpeakFrame(self._flow_definition.prompt_for(stage, retry=retry), append_to_context=False)
        )

    async def _push_response_and_end(self, text: str) -> None:
        await self._clear_pending_transcript()
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
