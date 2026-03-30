import asyncio
import sys
import types
import unittest

try:
    from pipecat.frames.frames import EndFrame, StartFrame, TTSSpeakFrame, TranscriptionFrame
    from pipecat.processors.frame_processor import FrameDirection
except ModuleNotFoundError:
    pipecat_module = types.ModuleType("pipecat")
    frames_package = types.ModuleType("pipecat.frames")
    frames_module = types.ModuleType("pipecat.frames.frames")
    processors_package = types.ModuleType("pipecat.processors")
    processor_module = types.ModuleType("pipecat.processors.frame_processor")

    class Frame:
        pass

    class StartFrame(Frame):
        pass

    class EndFrame(Frame):
        pass

    class TTSSpeakFrame(Frame):
        def __init__(self, text: str, append_to_context: bool = False):
            self.text = text
            self.append_to_context = append_to_context

    class TranscriptionFrame(Frame):
        def __init__(self, text: str, user_id: str, timestamp: str):
            self.text = text
            self.user_id = user_id
            self.timestamp = timestamp

    class InterimTranscriptionFrame(Frame):
        def __init__(self, text: str = ""):
            self.text = text

    class ErrorFrame(Frame):
        def __init__(self, error: str):
            self.error = error

    class FrameDirection:
        DOWNSTREAM = "downstream"
        UPSTREAM = "upstream"

    class FrameProcessor:
        def __init__(self, **kwargs):
            self._task_manager = None

        async def process_frame(self, frame, direction):
            return None

        async def push_frame(self, frame, direction=FrameDirection.DOWNSTREAM):
            return None

        async def cleanup(self):
            return None

    frames_module.Frame = Frame
    frames_module.StartFrame = StartFrame
    frames_module.EndFrame = EndFrame
    frames_module.TTSSpeakFrame = TTSSpeakFrame
    frames_module.TranscriptionFrame = TranscriptionFrame
    frames_module.InterimTranscriptionFrame = InterimTranscriptionFrame
    frames_module.ErrorFrame = ErrorFrame
    processor_module.FrameDirection = FrameDirection
    processor_module.FrameProcessor = FrameProcessor

    sys.modules["pipecat"] = pipecat_module
    sys.modules["pipecat.frames"] = frames_package
    sys.modules["pipecat.frames.frames"] = frames_module
    sys.modules["pipecat.processors"] = processors_package
    sys.modules["pipecat.processors.frame_processor"] = processor_module

    from pipecat.frames.frames import EndFrame, StartFrame, TTSSpeakFrame, TranscriptionFrame
    from pipecat.processors.frame_processor import FrameDirection

from common.flows.collection import (
    BusyIntent,
    CollectionStage,
    Convince2Intent,
    ConvinceIntent,
    FAQIntent,
    OpeningIntent,
    PaymentInquiryIntent,
    VerifyIntent,
    build_collection_flow,
)
from common.processors.collection_router import CollectionRouterProcessor


class FakeClassifier:
    def __init__(
        self,
        *,
        stage_intents: dict[CollectionStage, list[object]] | None = None,
        faq_intents: list[FAQIntent] | None = None,
        exc: Exception | None = None,
        faq_exc: Exception | None = None,
    ):
        self._stage_intents = {stage: list(intents) for stage, intents in (stage_intents or {}).items()}
        self._faq_intents = list(faq_intents or [])
        self._exc = exc
        self._faq_exc = faq_exc
        self.calls: list[tuple[str, str, dict | None]] = []

    async def classify_stage(
        self,
        stage: CollectionStage,
        transcript: str,
        state: dict | None = None,
    ):
        self.calls.append((transcript, stage.value, state))
        if self._exc is not None:
            raise self._exc
        assert self._stage_intents.get(stage)
        return self._stage_intents[stage].pop(0)

    async def classify_faq(
        self,
        transcript: str,
        state: dict | None = None,
    ) -> FAQIntent:
        self.calls.append((transcript, "faq", state))
        if self._faq_exc is not None:
            raise self._faq_exc
        assert self._faq_intents
        return self._faq_intents.pop(0)


class CollectionFlowTests(unittest.TestCase):
    def test_flow_definition_formats_stage_prompts_and_terminal_responses_from_state(self):
        flow = build_collection_flow(
            {
                "customer_name": "สมชาย ใจดี",
                "first_name": "สมชาย",
                "lic_no": "กข 1234",
                "province": "กรุงเทพมหานคร",
                "total_of_overdue_amt": "8,500",
                "due_dte": "5 มีนาคม 2568",
            }
        )

        self.assertIn("สมชาย ใจดี", flow.prompt_for(CollectionStage.OPENING))
        self.assertIn("ทะเบียน กข 1234", flow.prompt_for(CollectionStage.VERIFY))
        self.assertIn("8,500", flow.prompt_for(CollectionStage.CONVINCE))
        self.assertIn("พรุ่งนี้", flow.prompt_for(CollectionStage.CONVINCE2))
        self.assertIn("8,500", flow.faq_response_for(FAQIntent.PAYMENT_AMOUNT))
        self.assertIn("ติดต่อกลับอีกครั้ง", flow.fallback)

    def test_flow_definition_prewarm_texts_excludes_opening_and_dedupes(self):
        flow = build_collection_flow(
            {
                "customer_name": "สมชาย ใจดี",
                "first_name": "สมชาย",
                "lic_no": "กข 1234",
                "province": "กรุงเทพมหานคร",
                "total_of_overdue_amt": "8,500",
                "due_dte": "5 มีนาคม 2568",
            }
        )

        prewarm = flow.prewarm_texts()

        self.assertIn(flow.prompt_for(CollectionStage.VERIFY), prewarm)
        self.assertIn(flow.prompt_for(CollectionStage.PAYMENT_INQUIRY), prewarm)
        self.assertIn(flow.fallback, prewarm)
        self.assertNotIn(flow.prompt_for(CollectionStage.OPENING), prewarm)
        self.assertNotIn(flow.prompt_for(CollectionStage.OPENING, retry=True), prewarm)
        self.assertEqual(len(prewarm), len(set(prewarm)))

    def test_flow_definition_can_start_from_checkpoint_state(self):
        flow = build_collection_flow({"checkpoint": "overdue"})

        self.assertEqual(flow.default_stage, CollectionStage.PAYMENT_INQUIRY)


class CollectionRouterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.state = {
            "customer_name": "สมชาย ใจดี",
            "first_name": "สมชาย",
            "lic_no": "กข 1234",
            "province": "กรุงเทพมหานคร",
            "due_date": "5 มีนาคม 2568",
            "due_amount": "8,500",
        }
        self.flow = build_collection_flow(self.state)

    async def _make_router(self, classifier: FakeClassifier):
        router = CollectionRouterProcessor(
            flow_definition=self.flow,
            classifier=classifier,
            state=self.state,
            transcript_debounce_secs=0.0,
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

    async def test_opening_target_routes_to_verify_prompt_without_ending(self):
        classifier = FakeClassifier(
            stage_intents={CollectionStage.OPENING: [OpeningIntent.TARGET]}
        )
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

    async def test_opening_busy_routes_to_busy_prompt(self):
        classifier = FakeClassifier(
            stage_intents={CollectionStage.OPENING: [OpeningIntent.BUSY]}
        )
        router, pushed = await self._make_router(classifier)
        await router.process_frame(StartFrame(), FrameDirection.DOWNSTREAM)
        pushed.clear()

        await router.process_frame(
            TranscriptionFrame("ตอนนี้ไม่ว่างครับ", "user", "2026-03-29T00:00:00Z"),
            FrameDirection.DOWNSTREAM,
        )

        self.assertIsInstance(pushed[0][0], TTSSpeakFrame)
        self.assertEqual(pushed[0][0].text, self.flow.prompt_for(CollectionStage.BUSY))

    async def test_busy_in_time_routes_to_callback_close_then_end(self):
        classifier = FakeClassifier(
            stage_intents={
                CollectionStage.OPENING: [OpeningIntent.BUSY],
                CollectionStage.BUSY: [BusyIntent.IN_TIME],
            }
        )
        router, pushed = await self._make_router(classifier)
        await router.process_frame(StartFrame(), FrameDirection.DOWNSTREAM)
        await router.process_frame(
            TranscriptionFrame("ไม่ว่างครับ", "user", "2026-03-29T00:00:00Z"),
            FrameDirection.DOWNSTREAM,
        )
        pushed.clear()

        await router.process_frame(
            TranscriptionFrame("โทรมาพรุ่งนี้บ่ายสองครับ", "user", "2026-03-29T00:00:01Z"),
            FrameDirection.DOWNSTREAM,
        )

        self.assertIsInstance(pushed[0][0], TTSSpeakFrame)
        self.assertIn("ติดต่อใหม่ตามวันที่ลูกค้าแจ้ง", pushed[0][0].text)
        self.assertIsInstance(pushed[1][0], EndFrame)

    async def test_debounce_combines_transcripts_before_classification(self):
        classifier = FakeClassifier(
            stage_intents={CollectionStage.OPENING: [OpeningIntent.FAQ]},
            faq_intents=[FAQIntent.WHO_CALL],
        )
        router = CollectionRouterProcessor(
            flow_definition=self.flow,
            classifier=classifier,
            state=self.state,
            transcript_debounce_secs=0.02,
        )
        pushed: list[tuple[object, FrameDirection]] = []

        async def capture(frame, direction=FrameDirection.DOWNSTREAM):
            pushed.append((frame, direction))

        router.push_frame = capture

        await router.process_frame(StartFrame(), FrameDirection.DOWNSTREAM)
        pushed.clear()

        await router.process_frame(
            TranscriptionFrame("ยังไงครับ?", "user", "2026-03-29T00:00:00Z"),
            FrameDirection.DOWNSTREAM,
        )
        await asyncio.sleep(0.01)
        await router.process_frame(
            TranscriptionFrame("โทรมาเรื่องอะไร", "user", "2026-03-29T00:00:01Z"),
            FrameDirection.DOWNSTREAM,
        )

        self.assertEqual(classifier.calls, [])

        await asyncio.sleep(0.05)

        self.assertEqual(classifier.calls[0][0], "ยังไงครับ? โทรมาเรื่องอะไร")
        self.assertIsInstance(pushed[0][0], TTSSpeakFrame)
        self.assertEqual(
            pushed[0][0].text,
            self.flow.faq_response_for(FAQIntent.WHO_CALL),
        )
        self.assertIsInstance(pushed[1][0], EndFrame)

    async def test_verify_confirmed_routes_to_payment_inquiry_prompt(self):
        classifier = FakeClassifier(
            stage_intents={
                CollectionStage.OPENING: [OpeningIntent.TARGET],
                CollectionStage.VERIFY: [VerifyIntent.CONFIRMED],
            }
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
            self.flow.prompt_for(CollectionStage.PAYMENT_INQUIRY),
        )

    async def test_payment_inquiry_ptp_routes_to_close_then_end(self):
        classifier = FakeClassifier(
            stage_intents={
                CollectionStage.OPENING: [OpeningIntent.TARGET],
                CollectionStage.VERIFY: [VerifyIntent.CONFIRMED],
                CollectionStage.PAYMENT_INQUIRY: [PaymentInquiryIntent.PTP],
            }
        )
        router, pushed = await self._make_router(classifier)
        await router.process_frame(StartFrame(), FrameDirection.DOWNSTREAM)
        await router.process_frame(
            TranscriptionFrame("ครับ", "user", "2026-03-29T00:00:00Z"),
            FrameDirection.DOWNSTREAM,
        )
        await router.process_frame(
            TranscriptionFrame("ใช่ครับ", "user", "2026-03-29T00:00:01Z"),
            FrameDirection.DOWNSTREAM,
        )
        pushed.clear()

        await router.process_frame(
            TranscriptionFrame("วันนี้จะจ่ายครับ", "user", "2026-03-29T00:00:02Z"),
            FrameDirection.DOWNSTREAM,
        )

        self.assertIsInstance(pushed[0][0], TTSSpeakFrame)
        self.assertIn("02 078 8899", pushed[0][0].text)
        self.assertIsInstance(pushed[1][0], EndFrame)

    async def test_payment_inquiry_convince_routes_to_convince_prompt(self):
        classifier = FakeClassifier(
            stage_intents={
                CollectionStage.OPENING: [OpeningIntent.TARGET],
                CollectionStage.VERIFY: [VerifyIntent.CONFIRMED],
                CollectionStage.PAYMENT_INQUIRY: [PaymentInquiryIntent.CONVINCE],
            }
        )
        router, pushed = await self._make_router(classifier)
        await router.process_frame(StartFrame(), FrameDirection.DOWNSTREAM)
        await router.process_frame(
            TranscriptionFrame("ครับ", "user", "2026-03-29T00:00:00Z"),
            FrameDirection.DOWNSTREAM,
        )
        await router.process_frame(
            TranscriptionFrame("ใช่ครับ", "user", "2026-03-29T00:00:01Z"),
            FrameDirection.DOWNSTREAM,
        )
        pushed.clear()

        await router.process_frame(
            TranscriptionFrame("ยังไม่มีเงินครับ", "user", "2026-03-29T00:00:02Z"),
            FrameDirection.DOWNSTREAM,
        )

        self.assertIsInstance(pushed[0][0], TTSSpeakFrame)
        self.assertEqual(pushed[0][0].text, self.flow.prompt_for(CollectionStage.CONVINCE))

    async def test_convince_then_convince2_then_refuse_closes_call(self):
        classifier = FakeClassifier(
            stage_intents={
                CollectionStage.OPENING: [OpeningIntent.TARGET],
                CollectionStage.VERIFY: [VerifyIntent.CONFIRMED],
                CollectionStage.PAYMENT_INQUIRY: [PaymentInquiryIntent.CONVINCE],
                CollectionStage.CONVINCE: [ConvinceIntent.CONVINCE2],
                CollectionStage.CONVINCE2: [Convince2Intent.REFUSE],
            }
        )
        router, pushed = await self._make_router(classifier)
        await router.process_frame(StartFrame(), FrameDirection.DOWNSTREAM)
        await router.process_frame(
            TranscriptionFrame("ครับ", "user", "2026-03-29T00:00:00Z"),
            FrameDirection.DOWNSTREAM,
        )
        await router.process_frame(
            TranscriptionFrame("ใช่ครับ", "user", "2026-03-29T00:00:01Z"),
            FrameDirection.DOWNSTREAM,
        )
        await router.process_frame(
            TranscriptionFrame("ยังไม่มีเงินครับ", "user", "2026-03-29T00:00:02Z"),
            FrameDirection.DOWNSTREAM,
        )
        pushed.clear()

        await router.process_frame(
            TranscriptionFrame("วันนี้ยังไม่ไหว", "user", "2026-03-29T00:00:03Z"),
            FrameDirection.DOWNSTREAM,
        )

        self.assertEqual(pushed[0][0].text, self.flow.prompt_for(CollectionStage.CONVINCE2))
        pushed.clear()

        await router.process_frame(
            TranscriptionFrame("พรุ่งนี้ก็ไม่ไหวครับ", "user", "2026-03-29T00:00:04Z"),
            FrameDirection.DOWNSTREAM,
        )

        self.assertIsInstance(pushed[0][0], TTSSpeakFrame)
        self.assertIn("ติดต่อหาลูกค้าอีกครั้ง", pushed[0][0].text)
        self.assertIsInstance(pushed[1][0], EndFrame)

    async def test_faq_transcript_routes_to_specific_faq_response_then_end(self):
        classifier = FakeClassifier(
            stage_intents={CollectionStage.OPENING: [OpeningIntent.FAQ]},
            faq_intents=[FAQIntent.PAYMENT_AMOUNT],
        )
        router, pushed = await self._make_router(classifier)
        await router.process_frame(StartFrame(), FrameDirection.DOWNSTREAM)
        pushed.clear()

        await router.process_frame(
            TranscriptionFrame("ยอดเท่าไหร่ครับ", "user", "2026-03-29T00:00:00Z"),
            FrameDirection.DOWNSTREAM,
        )

        self.assertEqual(classifier.calls[1][1], "faq")
        self.assertIsInstance(pushed[0][0], TTSSpeakFrame)
        self.assertEqual(
            pushed[0][0].text,
            self.flow.faq_response_for(FAQIntent.PAYMENT_AMOUNT),
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
            FakeClassifier(stage_intents={CollectionStage.OPENING: [OpeningIntent.TARGET]})
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
