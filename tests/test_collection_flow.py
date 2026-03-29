import unittest

from pipecat.frames.frames import EndFrame, StartFrame, TTSSpeakFrame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection

from common.flows.collection import (
    CollectionIntent,
    build_collection_flow,
    build_collection_gemini_system_instruction,
)
from common.processors.collection_router import CollectionRouterProcessor


class FakeClassifier:
    def __init__(self, *, intent: CollectionIntent | None = None, exc: Exception | None = None):
        self.intent = intent
        self.exc = exc
        self.calls: list[tuple[str, dict | None]] = []

    async def classify(self, transcript: str, state: dict | None = None) -> CollectionIntent:
        self.calls.append((transcript, state))
        if self.exc is not None:
            raise self.exc
        assert self.intent is not None
        return self.intent


class CollectionFlowTests(unittest.TestCase):
    def test_flow_definition_formats_opening_and_target_from_state(self):
        flow = build_collection_flow(
            {
                "customer_name": "สมชาย ใจดี",
                "first_name": "สมชาย",
                "lic_no": "กข 1234",
                "province": "กรุงเทพมหานคร",
            }
        )

        self.assertIn("สมชาย ใจดี", flow.opening)
        self.assertIn("ทะเบียน กข 1234", flow.response_for(CollectionIntent.TARGET))
        self.assertEqual(
            flow.response_for(CollectionIntent.BUSY),
            flow.fallback,
        )

    def test_gemini_instruction_embeds_the_scripted_responses(self):
        state = {
            "customer_name": "สมชาย ใจดี",
            "first_name": "สมชาย",
            "lic_no": "กข 1234",
            "province": "กรุงเทพมหานคร",
        }
        flow = build_collection_flow(state)

        instruction = build_collection_gemini_system_instruction(state)

        self.assertIn(flow.opening, instruction)
        self.assertIn(flow.response_for(CollectionIntent.TARGET), instruction)
        self.assertIn(flow.response_for(CollectionIntent.BUSY), instruction)
        self.assertIn(flow.fallback, instruction)


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
        router, pushed = await self._make_router(FakeClassifier(intent=CollectionIntent.TARGET))

        await router.process_frame(StartFrame(), FrameDirection.DOWNSTREAM)

        self.assertIsInstance(pushed[0][0], StartFrame)
        self.assertIsInstance(pushed[1][0], TTSSpeakFrame)
        self.assertEqual(pushed[1][0].text, self.flow.opening)

    async def test_target_transcript_routes_to_verify_script_then_end(self):
        classifier = FakeClassifier(intent=CollectionIntent.TARGET)
        router, pushed = await self._make_router(classifier)
        await router.process_frame(StartFrame(), FrameDirection.DOWNSTREAM)
        pushed.clear()

        await router.process_frame(
            TranscriptionFrame("ครับ พูดอยู่", "user", "2026-03-29T00:00:00Z"),
            FrameDirection.DOWNSTREAM,
        )

        self.assertEqual(classifier.calls[0][0], "ครับ พูดอยู่")
        self.assertIsInstance(pushed[0][0], TTSSpeakFrame)
        self.assertIn("เป็นเจ้าของรถทะเบียน", pushed[0][0].text)
        self.assertIsInstance(pushed[1][0], EndFrame)

    async def test_busy_transcript_routes_to_callback_close_then_end(self):
        router, pushed = await self._make_router(FakeClassifier(intent=CollectionIntent.BUSY))
        await router.process_frame(StartFrame(), FrameDirection.DOWNSTREAM)
        pushed.clear()

        await router.process_frame(
            TranscriptionFrame("ตอนนี้ไม่ว่างครับ", "user", "2026-03-29T00:00:00Z"),
            FrameDirection.DOWNSTREAM,
        )

        self.assertIsInstance(pushed[0][0], TTSSpeakFrame)
        self.assertEqual(pushed[0][0].text, self.flow.response_for(CollectionIntent.BUSY))
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

    async def test_empty_transcript_uses_fallback_then_end(self):
        router, pushed = await self._make_router(FakeClassifier(intent=CollectionIntent.TARGET))
        await router.process_frame(StartFrame(), FrameDirection.DOWNSTREAM)
        pushed.clear()

        await router.process_frame(
            TranscriptionFrame("   ", "user", "2026-03-29T00:00:00Z"),
            FrameDirection.DOWNSTREAM,
        )

        self.assertIsInstance(pushed[0][0], TTSSpeakFrame)
        self.assertEqual(pushed[0][0].text, self.flow.fallback)
        self.assertIsInstance(pushed[1][0], EndFrame)


if __name__ == "__main__":
    unittest.main()
