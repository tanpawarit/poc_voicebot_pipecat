import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from common.flows.collection import CollectionIntent, CollectionStage, VerifyIntent
from common.openai_intent_classifier import (
    OpenAIIntentClassifier,
    OpenAIVerifyIntentClassifier,
)


class OpenAIIntentClassifierTests(unittest.IsolatedAsyncioTestCase):
    async def test_classify_stage_opening_uses_opening_specific_prompt(self):
        classifier = OpenAIIntentClassifier(api_key="test-key", model="test-model")
        classifier._client = SimpleNamespace(
            responses=SimpleNamespace(
                parse=AsyncMock(
                    return_value=SimpleNamespace(
                        output_parsed=SimpleNamespace(route=CollectionIntent.TARGET)
                    )
                )
            )
        )

        intent = await classifier.classify_stage(
            CollectionStage.OPENING,
            "ค่ะ พูดอยู่ค่ะ",
            {"customer_name": "สมชาย ใจดี"},
        )

        self.assertEqual(intent, CollectionIntent.TARGET)
        kwargs = classifier._client.responses.parse.await_args.kwargs
        self.assertIn("opening greeting", kwargs["instructions"])
        self.assertIn("customer_name: สมชาย ใจดี", kwargs["input"])
        self.assertIn("user_reply: ค่ะ พูดอยู่ค่ะ", kwargs["input"])

    async def test_classify_stage_verify_uses_verify_specific_prompt(self):
        classifier = OpenAIIntentClassifier(api_key="test-key", model="test-model")
        classifier._client = SimpleNamespace(
            responses=SimpleNamespace(
                parse=AsyncMock(
                    return_value=SimpleNamespace(
                        output_parsed=SimpleNamespace(route=VerifyIntent.CONFIRMED)
                    )
                )
            )
        )

        intent = await classifier.classify_stage(
            CollectionStage.VERIFY,
            "ใช่ครับ รถผมเอง",
            {
                "first_name": "สมชาย",
                "lic_no": "กข 1234",
                "province": "กรุงเทพมหานคร",
            },
        )

        self.assertEqual(intent, VerifyIntent.CONFIRMED)
        kwargs = classifier._client.responses.parse.await_args.kwargs
        self.assertIn("verify question", kwargs["instructions"])
        self.assertIn("first_name: สมชาย", kwargs["input"])
        self.assertIn("lic_no: กข 1234", kwargs["input"])
        self.assertIn("province: กรุงเทพมหานคร", kwargs["input"])
        self.assertIn("user_reply: ใช่ครับ รถผมเอง", kwargs["input"])

    async def test_legacy_opening_classify_alias_routes_to_opening_stage(self):
        classifier = OpenAIIntentClassifier(api_key="test-key", model="test-model")
        classifier.classify_stage = AsyncMock(return_value=CollectionIntent.FAQ)

        intent = await classifier.classify("โทรมาเรื่องอะไรคะ", {"customer_name": "สมชาย"})

        self.assertEqual(intent, CollectionIntent.FAQ)
        classifier.classify_stage.assert_awaited_once_with(
            CollectionStage.OPENING,
            "โทรมาเรื่องอะไรคะ",
            {"customer_name": "สมชาย"},
        )

    async def test_legacy_verify_classifier_alias_routes_to_verify_stage(self):
        classifier = OpenAIVerifyIntentClassifier(api_key="test-key", model="test-model")
        classifier.classify_stage = AsyncMock(return_value=VerifyIntent.FAQ)

        intent = await classifier.classify("โทรมาเรื่องอะไรคะ", {"first_name": "สมชาย"})

        self.assertEqual(intent, VerifyIntent.FAQ)
        classifier.classify_stage.assert_awaited_once_with(
            CollectionStage.VERIFY,
            "โทรมาเรื่องอะไรคะ",
            {"first_name": "สมชาย"},
        )


if __name__ == "__main__":
    unittest.main()
