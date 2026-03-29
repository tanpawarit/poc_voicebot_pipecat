import unittest

from pipecat.frames.frames import EndFrame, StartFrame, TTSSpeakFrame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection

from common.flows.collection import (
    CollectionIntent,
    CollectionStage,
    VerifyIntent,
    build_collection_flow,
)
from common.processors.collection_router import CollectionRouterProcessor


class FakeClassifier:
    def __init__(
        self,
        *,
        opening_intents: list[CollectionIntent] | None = None,
        verify_intents: list[VerifyIntent] | None = None,
        exc: Exception | None = None,
    ):
        self._opening_intents = list(opening_intents or [])
        self._verify_intents = list(verify_intents or [])
        self._exc = exc
        self.calls: list[tuple[str, str, dict | None]] = []

    async def classify_opening(
        self,
        transcript: str,
        state: dict | None = None,
    ) -> CollectionIntent:
        self.calls.append((transcript, CollectionStage.OPENING.value, state))
        if self._exc is not None:
            raise self._exc
        assert self._opening_intents
        return self._opening_intents.pop(0)

    async def classify_verify(
        self,
        transcript: str,
        state: dict | None = None,
    ) -> VerifyIntent:
        self.calls.append((transcript, CollectionStage.VERIFY.value, state))
        if self._exc is not None:
            raise self._exc
        assert self._verify_intents
        return self._verify_intents.pop(0)


class CollectionFlowTests(unittest.TestCase):
    def test_flow_definition_formats_opening_verify_and_overdue_from_state(self):
        flow = build_collection_flow(
            {
                "customer_name": "สมชาย ใจดี",
                "first_name": "สมชาย",
                "lic_no": "กข 1234",
                "province": "กรุงเทพมหานคร",
            }
        )

        self.assertIn("สมชาย ใจดี", flow.prompt_for(CollectionStage.OPENING))
        self.assertIn("ทะเบียน กข 1234", flow.prompt_for(CollectionStage.VERIFY))
        self.assertIn(
            "ทะเบียน กข 1234",
            flow.verify_response_for(VerifyIntent.CONFIRMED),
        )
        self.assertIn("ติดต่อกลับอีกครั้ง", flow.fallback)


class CollectionRouterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.state = {
            "customer_name": "สมชาย ใจดี",
            "first_name": "สมชาย",
            "lic_no": "กข 1234",
            "province": "กรุงเทพมหานคร",
        }
        self.flow = build_collection_flow(self.state)

    async def _make_router(self, classifier: FakeClassifier):
        router = CollectionRouterProcessor(
            flow_definition=self.flow,
            classifier=classifier,
            state=self.state,
        )
        pushed: list[tuple[object, FrameDirection]] = []

        async def capture(frame, direction=FrameDirection.DOWNSTREAM):
            pushed.append((frame, direction))

        router.push_frame = capture
        return router, pushed

    async def test_start_frame_emits_opening_script(self):
        router, pushed = await self._make_router(FakeClassifier())

        await router.process_frame(StartFrame(), FrameDirection.DOWNSTREAM)

        self.assertIsInstance(pushed[0][0], StartFrame)
        self.assertIsInstance(pushed[1][0], TTSSpeakFrame)
        self.assertEqual(pushed[1][0].text, self.flow.prompt_for(CollectionStage.OPENING))

    async def test_target_transcript_routes_to_verify_prompt_without_ending(self):
        classifier = FakeClassifier(opening_intents=[CollectionIntent.TARGET])
        router, pushed = await self._make_router(classifier)
        await router.process_frame(StartFrame(), FrameDirection.DOWNSTREAM)
        pushed.clear()

        await router.process_frame(
            TranscriptionFrame("ครับ พูดอยู่", "user", "2026-03-29T00:00:00Z"),
            FrameDirection.DOWNSTREAM,
        )

        self.assertEqual(classifier.calls[0][0], "ครับ พูดอยู่")
        self.assertEqual(classifier.calls[0][1], CollectionStage.OPENING.value)
        self.assertEqual(len(pushed), 1)
        self.assertIsInstance(pushed[0][0], TTSSpeakFrame)
        self.assertEqual(pushed[0][0].text, self.flow.prompt_for(CollectionStage.VERIFY))

    async def test_verify_confirmed_routes_to_overdue_script_then_end(self):
        classifier = FakeClassifier(
            opening_intents=[CollectionIntent.TARGET],
            verify_intents=[VerifyIntent.CONFIRMED],
        )
        router, pushed = await self._make_router(classifier)
        await router.process_frame(StartFrame(), FrameDirection.DOWNSTREAM)

        await router.process_frame(
            TranscriptionFrame("ครับ พูดอยู่", "user", "2026-03-29T00:00:00Z"),
            FrameDirection.DOWNSTREAM,
        )
        pushed.clear()

        await router.process_frame(
            TranscriptionFrame("ใช่ครับ รถผมเอง", "user", "2026-03-29T00:00:02Z"),
            FrameDirection.DOWNSTREAM,
        )

        self.assertEqual(classifier.calls[1][0], "ใช่ครับ รถผมเอง")
        self.assertEqual(classifier.calls[1][1], CollectionStage.VERIFY.value)
        self.assertIsInstance(pushed[0][0], TTSSpeakFrame)
        self.assertEqual(
            pushed[0][0].text,
            self.flow.verify_response_for(VerifyIntent.CONFIRMED),
        )
        self.assertIsInstance(pushed[1][0], EndFrame)

    async def test_busy_transcript_routes_to_callback_close_then_end(self):
        router, pushed = await self._make_router(
            FakeClassifier(opening_intents=[CollectionIntent.BUSY])
        )
        await router.process_frame(StartFrame(), FrameDirection.DOWNSTREAM)
        pushed.clear()

        await router.process_frame(
            TranscriptionFrame("ตอนนี้ไม่ว่างครับ", "user", "2026-03-29T00:00:00Z"),
            FrameDirection.DOWNSTREAM,
        )

        self.assertIsInstance(pushed[0][0], TTSSpeakFrame)
        self.assertEqual(
            pushed[0][0].text,
            self.flow.opening_response_for(CollectionIntent.BUSY),
        )
        self.assertIsInstance(pushed[1][0], EndFrame)

    async def test_empty_opening_transcript_retries_once_then_falls_back(self):
        router, pushed = await self._make_router(FakeClassifier())
        await router.process_frame(StartFrame(), FrameDirection.DOWNSTREAM)
        pushed.clear()

        await router.process_frame(
            TranscriptionFrame("   ", "user", "2026-03-29T00:00:00Z"),
            FrameDirection.DOWNSTREAM,
        )

        self.assertEqual(len(pushed), 1)
        self.assertIsInstance(pushed[0][0], TTSSpeakFrame)
        self.assertEqual(
            pushed[0][0].text,
            self.flow.prompt_for(CollectionStage.OPENING, retry=True),
        )
        pushed.clear()

        await router.process_frame(
            TranscriptionFrame("   ", "user", "2026-03-29T00:00:01Z"),
            FrameDirection.DOWNSTREAM,
        )

        self.assertIsInstance(pushed[0][0], TTSSpeakFrame)
        self.assertEqual(pushed[0][0].text, self.flow.fallback)
        self.assertIsInstance(pushed[1][0], EndFrame)

    async def test_empty_verify_transcript_retries_once_then_falls_back(self):
        router, pushed = await self._make_router(
            FakeClassifier(opening_intents=[CollectionIntent.TARGET])
        )
        await router.process_frame(StartFrame(), FrameDirection.DOWNSTREAM)

        await router.process_frame(
            TranscriptionFrame("ครับ พูดอยู่", "user", "2026-03-29T00:00:00Z"),
            FrameDirection.DOWNSTREAM,
        )
        pushed.clear()

        await router.process_frame(
            TranscriptionFrame("   ", "user", "2026-03-29T00:00:01Z"),
            FrameDirection.DOWNSTREAM,
        )

        self.assertEqual(len(pushed), 1)
        self.assertIsInstance(pushed[0][0], TTSSpeakFrame)
        self.assertEqual(
            pushed[0][0].text,
            self.flow.prompt_for(CollectionStage.VERIFY, retry=True),
        )
        pushed.clear()

        await router.process_frame(
            TranscriptionFrame("   ", "user", "2026-03-29T00:00:02Z"),
            FrameDirection.DOWNSTREAM,
        )

        self.assertIsInstance(pushed[0][0], TTSSpeakFrame)
        self.assertEqual(pushed[0][0].text, self.flow.fallback)
        self.assertIsInstance(pushed[1][0], EndFrame)

    async def test_classifier_failure_uses_fallback_then_end(self):
        router, pushed = await self._make_router(
            FakeClassifier(exc=RuntimeError("classification failed"))
        )
        await router.process_frame(StartFrame(), FrameDirection.DOWNSTREAM)
        pushed.clear()

        await router.process_frame(
            TranscriptionFrame("ฝากข้อความไว้ได้เลย", "user", "2026-03-29T00:00:00Z"),
            FrameDirection.DOWNSTREAM,
        )

        self.assertIsInstance(pushed[0][0], TTSSpeakFrame)
        self.assertEqual(pushed[0][0].text, self.flow.fallback)
        self.assertIsInstance(pushed[1][0], EndFrame)


if __name__ == "__main__":
    unittest.main()
