import unittest

from pipecat.frames.frames import (
    ClientConnectedFrame,
    EndFrame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    StartFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection

from app_s2s.bot import GeminiContextBootstrapProcessor, EndCallAfterResponsesProcessor


class BotProcessorsTests(unittest.IsolatedAsyncioTestCase):
    async def test_bootstrap_processor_seeds_context_on_client_connected(self):
        processor = GeminiContextBootstrapProcessor(context=LLMContext())
        pushed: list[tuple[object, FrameDirection]] = []

        async def capture(frame, direction=FrameDirection.DOWNSTREAM):
            pushed.append((frame, direction))

        processor.push_frame = capture

        await processor.process_frame(ClientConnectedFrame(), FrameDirection.DOWNSTREAM)

        self.assertIsInstance(pushed[0][0], ClientConnectedFrame)
        self.assertIsInstance(pushed[1][0], LLMContextFrame)

    async def test_bootstrap_processor_does_not_seed_on_start_frame(self):
        processor = GeminiContextBootstrapProcessor(context=LLMContext())
        pushed: list[tuple[object, FrameDirection]] = []

        async def capture(frame, direction=FrameDirection.DOWNSTREAM):
            pushed.append((frame, direction))

        processor.push_frame = capture

        await processor.process_frame(StartFrame(), FrameDirection.DOWNSTREAM)

        self.assertEqual(len(pushed), 1)
        self.assertIsInstance(pushed[0][0], StartFrame)

    async def test_end_call_processor_queues_end_after_second_response(self):
        processor = EndCallAfterResponsesProcessor(response_limit=2)
        pushed: list[tuple[object, FrameDirection]] = []

        async def capture(frame, direction=FrameDirection.DOWNSTREAM):
            pushed.append((frame, direction))

        processor.push_frame = capture

        await processor.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)
        self.assertEqual(len(pushed), 1)
        self.assertIsInstance(pushed[0][0], LLMFullResponseEndFrame)

        await processor.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)

        self.assertIsInstance(pushed[1][0], LLMFullResponseEndFrame)
        self.assertIsInstance(pushed[2][0], EndFrame)


if __name__ == "__main__":
    unittest.main()
