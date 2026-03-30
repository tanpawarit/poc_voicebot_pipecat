"""In-memory cache primitives for rendered TTS audio."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TTSCacheEntry:
    """Cached PCM audio for a single rendered TTS utterance."""

    audio: bytes
    sample_rate: int
    num_channels: int
    size_bytes: int
    last_accessed: float


def _normalize_key_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def build_tts_cache_key(
    *,
    model: str | None,
    voice: str | None,
    speed: object,
    instructions: object,
    sample_rate: int,
    text: str,
) -> str:
    """Build a stable cache key for a rendered TTS request."""
    payload = {
        "model": _normalize_key_value(model),
        "voice": _normalize_key_value(voice),
        "speed": _normalize_key_value(speed),
        "instructions": _normalize_key_value(instructions),
        "sample_rate": sample_rate,
        "text": text,
    }
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


class TTSMemoryCache:
    """Process-local LRU cache for rendered PCM audio."""

    def __init__(self, *, max_entries: int, max_bytes: int) -> None:
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._lock = asyncio.Lock()
        self._entries: OrderedDict[str, TTSCacheEntry] = OrderedDict()
        self._current_bytes = 0

    @property
    def max_entries(self) -> int:
        return self._max_entries

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    async def get(self, key: str) -> TTSCacheEntry | None:
        """Return a cached entry and refresh its LRU position."""
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None

            refreshed = TTSCacheEntry(
                audio=entry.audio,
                sample_rate=entry.sample_rate,
                num_channels=entry.num_channels,
                size_bytes=entry.size_bytes,
                last_accessed=time.time(),
            )
            self._entries[key] = refreshed
            self._entries.move_to_end(key)
            return refreshed

    async def has(self, key: str) -> bool:
        async with self._lock:
            return key in self._entries

    async def set(
        self,
        key: str,
        *,
        audio: bytes,
        sample_rate: int,
        num_channels: int,
    ) -> bool:
        """Store audio if it fits within the configured memory budget."""
        size_bytes = len(audio)
        if size_bytes == 0 or size_bytes > self._max_bytes:
            return False

        async with self._lock:
            existing = self._entries.pop(key, None)
            if existing is not None:
                self._current_bytes -= existing.size_bytes

            entry = TTSCacheEntry(
                audio=audio,
                sample_rate=sample_rate,
                num_channels=num_channels,
                size_bytes=size_bytes,
                last_accessed=time.time(),
            )
            self._entries[key] = entry
            self._entries.move_to_end(key)
            self._current_bytes += size_bytes
            self._evict_locked()
            return key in self._entries

    async def clear(self) -> None:
        async with self._lock:
            self._entries.clear()
            self._current_bytes = 0

    def _evict_locked(self) -> None:
        while self._entries and (
            len(self._entries) > self._max_entries or self._current_bytes > self._max_bytes
        ):
            _, entry = self._entries.popitem(last=False)
            self._current_bytes -= entry.size_bytes


_shared_cache: TTSMemoryCache | None = None
_shared_cache_config: tuple[int, int] | None = None


def get_shared_tts_cache(*, max_entries: int, max_bytes: int) -> TTSMemoryCache:
    """Return a process-wide cache singleton for the requested limits."""
    global _shared_cache, _shared_cache_config

    config = (max_entries, max_bytes)
    if _shared_cache is None or _shared_cache_config != config:
        _shared_cache = TTSMemoryCache(max_entries=max_entries, max_bytes=max_bytes)
        _shared_cache_config = config
    return _shared_cache


def reset_shared_tts_cache() -> None:
    """Reset the process-wide cache. Intended for tests."""
    global _shared_cache, _shared_cache_config
    _shared_cache = None
    _shared_cache_config = None
