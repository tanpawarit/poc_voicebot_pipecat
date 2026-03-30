"""OpenAI TTS service wrapper with process-local memory caching."""

from __future__ import annotations

import asyncio
import logging
from typing import Iterable, Sequence
from uuid import uuid4

from pipecat.frames.frames import CancelFrame, EndFrame, ErrorFrame, StartFrame, TTSAudioRawFrame
from pipecat.services.openai.tts import OpenAITTSService

from common.thai_phonetics import preprocess_for_tts
from common.tts_cache import TTSMemoryCache, build_tts_cache_key

logger = logging.getLogger(__name__)


class CachedOpenAITTSService(OpenAITTSService):
    """OpenAI TTS service with exact-text PCM caching and prewarm support."""

    def __init__(
        self,
        *,
        cache: TTSMemoryCache | None,
        cache_enabled: bool = True,
        excluded_texts: Iterable[str] | None = None,
        prewarm_texts: Sequence[str] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._cache = cache
        self._cache_enabled = cache_enabled and cache is not None
        self._excluded_texts = {text for text in (excluded_texts or ()) if text}
        self._prewarm_texts = tuple(dict.fromkeys(text for text in (prewarm_texts or ()) if text))
        self._prewarm_task: asyncio.Task[None] | None = None

    async def start(self, frame: StartFrame):
        await super().start(frame)
        if self._cache_enabled and self._prewarm_texts and self._prewarm_task is None:
            self._prewarm_task = asyncio.create_task(self.prewarm_texts(self._prewarm_texts))

    async def stop(self, frame: EndFrame):
        await self._cancel_prewarm_task()
        await super().stop(frame)

    async def cancel(self, frame: CancelFrame):
        await self._cancel_prewarm_task()
        await super().cancel(frame)

    async def run_tts(self, text: str, context_id: str):
        text = preprocess_for_tts(text)
        if not self._should_cache_text(text):
            async for frame in super().run_tts(text, context_id):
                yield frame
            return

        cache_key = self._cache_key_for(text)
        cached = await self._cache.get(cache_key)
        if cached is not None:
            logger.debug("TTS cache hit for rendered prompt")
            yield TTSAudioRawFrame(
                audio=cached.audio,
                sample_rate=cached.sample_rate,
                num_channels=cached.num_channels,
                context_id=context_id,
            )
            return

        logger.debug("TTS cache miss for rendered prompt")
        audio_chunks: list[bytes] = []
        sample_rate = self.sample_rate
        num_channels = 1
        has_error = False

        async for frame in super().run_tts(text, context_id):
            if isinstance(frame, TTSAudioRawFrame):
                audio_chunks.append(frame.audio)
                sample_rate = frame.sample_rate or self._effective_sample_rate()
                num_channels = frame.num_channels
            elif isinstance(frame, ErrorFrame):
                has_error = True
            yield frame

        if audio_chunks and not has_error:
            await self._cache.set(
                cache_key,
                audio=b"".join(audio_chunks),
                sample_rate=sample_rate,
                num_channels=num_channels,
            )

    async def prewarm_texts(self, texts: Sequence[str]) -> None:
        if not self._cache_enabled:
            return

        seen: set[str] = set()
        for text in texts:
            if not text or text in seen or not self._should_cache_text(text):
                continue
            seen.add(text)

            cache_key = self._cache_key_for(text)
            if await self._cache.has(cache_key):
                continue

            try:
                await self._populate_cache(text, cache_key)
            except Exception:
                logger.exception("TTS prewarm failed for prompt")

    def _should_cache_text(self, text: str) -> bool:
        return self._cache_enabled and text not in self._excluded_texts

    def _cache_key_for(self, text: str) -> str:
        return build_tts_cache_key(
            model=getattr(self._settings, "model", None),
            voice=getattr(self._settings, "voice", None),
            speed=getattr(self._settings, "speed", None),
            instructions=getattr(self._settings, "instructions", None),
            sample_rate=self._effective_sample_rate(),
            text=text,
        )

    async def _populate_cache(self, text: str, cache_key: str) -> None:
        audio_chunks: list[bytes] = []
        sample_rate = self._effective_sample_rate()
        num_channels = 1

        async for frame in super().run_tts(text, f"prewarm-{uuid4()}"):
            if isinstance(frame, ErrorFrame):
                logger.warning("Skipping TTS cache store after upstream error during prewarm")
                return
            if isinstance(frame, TTSAudioRawFrame):
                audio_chunks.append(frame.audio)
                sample_rate = frame.sample_rate or self._effective_sample_rate()
                num_channels = frame.num_channels

        if audio_chunks:
            await self._cache.set(
                cache_key,
                audio=b"".join(audio_chunks),
                sample_rate=sample_rate,
                num_channels=num_channels,
            )

    def _effective_sample_rate(self) -> int:
        return self.sample_rate or getattr(self, "_init_sample_rate", 0) or self.OPENAI_SAMPLE_RATE

    async def _cancel_prewarm_task(self) -> None:
        if self._prewarm_task is None:
            return

        self._prewarm_task.cancel()
        try:
            await self._prewarm_task
        except asyncio.CancelledError:
            pass
        finally:
            self._prewarm_task = None
