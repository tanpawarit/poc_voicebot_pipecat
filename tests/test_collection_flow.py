import unittest

from common.flows.collection import (
    CollectionIntent,
    build_collection_gemini_initial_messages,
    build_collection_flow,
    build_collection_gemini_system_instruction,
)


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
        self.assertIn("ทะเบียน กข 1234", flow.verify)
        self.assertEqual(flow.response_for(CollectionIntent.TARGET), flow.verify)
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
        self.assertIn(flow.verify, instruction)
        self.assertIn(flow.response_for(CollectionIntent.BUSY), instruction)
        self.assertIn(flow.fallback, instruction)

    def test_gemini_initial_messages_seed_the_exact_opening(self):
        state = {
            "customer_name": "สมชาย ใจดี",
            "first_name": "สมชาย",
            "lic_no": "กข 1234",
            "province": "กรุงเทพมหานคร",
        }
        flow = build_collection_flow(state)

        messages = build_collection_gemini_initial_messages(state)

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["role"], "user")
        self.assertIn(flow.opening, messages[0]["content"])


if __name__ == "__main__":
    unittest.main()
