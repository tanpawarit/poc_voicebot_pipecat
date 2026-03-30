import unittest
from unittest.mock import patch

from pipecat.frames.frames import TTSAudioRawFrame
from pipecat.services.openai.tts import OpenAITTSService

from common.cached_openai_tts import CachedOpenAITTSService
from common.tts_cache import TTSMemoryCache, build_tts_cache_key


class TTSCacheKeyTests(unittest.TestCase):
    def test_build_cache_key_changes_when_request_shape_changes(self):
        key_a = build_tts_cache_key(
            model="gpt-4o-mini-tts",
            voice="sage",
            speed=0.94,
            instructions="natural thai",
            sample_rate=24000,
            text="สวัสดีค่ะ",
        )
        key_b = build_tts_cache_key(
            model="gpt-4o-mini-tts",
            voice="sage",
            speed=0.94,
            instructions="natural thai",
            sample_rate=24000,
            text="สวัสดีครับ",
        )
        key_c = build_tts_cache_key(
            model="gpt-4o-mini-tts",
            voice="coral",
            speed=0.94,
            instructions="natural thai",
            sample_rate=24000,
            text="สวัสดีค่ะ",
        )

        self.assertNotEqual(key_a, key_b)
        self.assertNotEqual(key_a, key_c)


class TTSMemoryCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_lru_eviction_respects_entry_limit(self):
        cache = TTSMemoryCache(max_entries=2, max_bytes=1024)

        await cache.set("a", audio=b"\x00\x01", sample_rate=24000, num_channels=1)
        await cache.set("b", audio=b"\x02\x03", sample_rate=24000, num_channels=1)
        await cache.get("a")
        await cache.set("c", audio=b"\x04\x05", sample_rate=24000, num_channels=1)

        self.assertTrue(await cache.has("a"))
        self.assertFalse(await cache.has("b"))
        self.assertTrue(await cache.has("c"))

    async def test_lru_eviction_respects_byte_budget(self):
        cache = TTSMemoryCache(max_entries=8, max_bytes=5)

        await cache.set("a", audio=b"\x00\x01", sample_rate=24000, num_channels=1)
        await cache.set("b", audio=b"\x02\x03", sample_rate=24000, num_channels=1)
        await cache.get("a")
        await cache.set("c", audio=b"\x04\x05", sample_rate=24000, num_channels=1)

        self.assertTrue(await cache.has("a"))
        self.assertFalse(await cache.has("b"))
        self.assertTrue(await cache.has("c"))


class CachedOpenAITTSServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cache = TTSMemoryCache(max_entries=16, max_bytes=1024 * 1024)

    def _make_service(self, *, excluded_texts=None, cache_enabled=True):
        return CachedOpenAITTSService(
            api_key="key",
            cache=self.cache,
            cache_enabled=cache_enabled,
            excluded_texts=excluded_texts,
            sample_rate=24000,
            settings=CachedOpenAITTSService.Settings(
                model="gpt-4o-mini-tts",
                voice="sage",
                instructions="natural thai",
                speed=0.94,
            ),
        )

    async def _collect_frames(self, service: CachedOpenAITTSService, text: str):
        frames = []
        async for frame in service.run_tts(text, "ctx"):
            frames.append(frame)
        return frames

    async def test_cache_miss_then_hit_reuses_cached_audio(self):
        calls = {"count": 0}

        async def fake_run_tts(self, text: str, context_id: str):
            calls["count"] += 1
            yield TTSAudioRawFrame(
                audio=f"audio:{text}".encode("utf-8"),
                sample_rate=24000,
                num_channels=1,
                context_id=context_id,
            )

        service = self._make_service()
        with patch.object(OpenAITTSService, "run_tts", new=fake_run_tts):
            first_frames = await self._collect_frames(service, "สวัสดีค่ะ")
            second_frames = await self._collect_frames(service, "สวัสดีค่ะ")

        self.assertEqual(calls["count"], 1)
        self.assertEqual(first_frames[0].audio, second_frames[0].audio)
        self.assertTrue(await self.cache.has(service._cache_key_for("สวัสดีค่ะ")))

    async def test_excluded_text_bypasses_cache(self):
        calls = {"count": 0}

        async def fake_run_tts(self, text: str, context_id: str):
            calls["count"] += 1
            yield TTSAudioRawFrame(
                audio=b"\x00\x01",
                sample_rate=24000,
                num_channels=1,
                context_id=context_id,
            )

        service = self._make_service(excluded_texts={"skip me"})
        with patch.object(OpenAITTSService, "run_tts", new=fake_run_tts):
            await self._collect_frames(service, "skip me")
            await self._collect_frames(service, "skip me")

        self.assertEqual(calls["count"], 2)
        self.assertFalse(await self.cache.has(service._cache_key_for("skip me")))

    async def test_prewarm_skips_existing_entries(self):
        calls = {"count": 0}

        async def fake_run_tts(self, text: str, context_id: str):
            calls["count"] += 1
            yield TTSAudioRawFrame(
                audio=f"audio:{text}".encode("utf-8"),
                sample_rate=24000,
                num_channels=1,
                context_id=context_id,
            )

        service = self._make_service()
        with patch.object(OpenAITTSService, "run_tts", new=fake_run_tts):
            await service.prewarm_texts(["warm me", "warm me"])
            await service.prewarm_texts(["warm me"])

        self.assertEqual(calls["count"], 1)
        self.assertTrue(await self.cache.has(service._cache_key_for("warm me")))

    async def test_prewarm_error_does_not_fail_remaining_prompts(self):
        calls = {"count": 0}

        async def fake_run_tts(self, text: str, context_id: str):
            calls["count"] += 1
            if text == "bad":
                raise RuntimeError("boom")
            yield TTSAudioRawFrame(
                audio=f"audio:{text}".encode("utf-8"),
                sample_rate=24000,
                num_channels=1,
                context_id=context_id,
            )

        service = self._make_service()
        with patch.object(OpenAITTSService, "run_tts", new=fake_run_tts):
            await service.prewarm_texts(["bad", "good"])

        self.assertEqual(calls["count"], 2)
        self.assertTrue(await self.cache.has(service._cache_key_for("good")))

    async def test_prewarm_uses_effective_sample_rate_before_service_start(self):
        async def fake_run_tts(self, text: str, context_id: str):
            yield TTSAudioRawFrame(
                audio=f"audio:{text}".encode("utf-8"),
                sample_rate=0,
                num_channels=1,
                context_id=context_id,
            )

        service = self._make_service()
        with patch.object(OpenAITTSService, "run_tts", new=fake_run_tts):
            await service.prewarm_texts(["warm me"])

        entry = await self.cache.get(service._cache_key_for("warm me"))
        self.assertIsNotNone(entry)
        self.assertEqual(entry.sample_rate, 24000)


if __name__ == "__main__":
    unittest.main()
