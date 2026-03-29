import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app_s2s.server as server


class DummyConnection:
    def __init__(self):
        self.initialized = None

    async def initialize(self, *, sdp: str, type: str):
        self.initialized = {"sdp": sdp, "type": type}

    def get_answer(self):
        return {"sdp": "answer-sdp", "type": "answer", "pc_id": "pc-123"}


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)
        self.gemini_api_key = server.settings.gemini_api_key
        server.settings.gemini_api_key = "test-key"

    def tearDown(self):
        server.settings.gemini_api_key = self.gemini_api_key

    def test_offer_validation_rejects_missing_sdp(self):
        response = self.client.post("/api/offer", json={"type": "offer"})

        self.assertEqual(response.status_code, 422)

    def test_offer_validation_rejects_wrong_type(self):
        response = self.client.post("/api/offer", json={"sdp": "offer-sdp", "type": "answer"})

        self.assertEqual(response.status_code, 422)

    def test_offer_returns_answer_for_valid_payload(self):
        dummy_connection = DummyConnection()

        async def fake_run_bot(connection):
            self.assertIs(connection, dummy_connection)

        with patch.object(server, "create_connection", return_value=dummy_connection):
            with patch("app_s2s.bot.run_bot", fake_run_bot):
                response = self.client.post(
                    "/api/offer",
                    json={"sdp": "offer-sdp", "type": "offer"},
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"sdp": "answer-sdp", "type": "answer", "pc_id": "pc-123"},
        )
        self.assertEqual(
            dummy_connection.initialized,
            {"sdp": "offer-sdp", "type": "offer"},
        )


if __name__ == "__main__":
    unittest.main()
