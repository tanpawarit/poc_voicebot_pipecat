import unittest
from unittest.mock import patch

import common.config as config_module
from common.config import Settings


class SettingsTests(unittest.TestCase):
    def test_validate_rejects_missing_openai_api_key(self):
        with self.assertRaises(RuntimeError):
            Settings(openai_api_key="", vad_stop_secs=0.2, turn_end_timeout_secs=2.0).validate()

    def test_validate_rejects_invalid_turn_tuning(self):
        with self.assertRaises(RuntimeError):
            Settings(openai_api_key="key", vad_stop_secs=0).validate()

        with self.assertRaises(RuntimeError):
            Settings(openai_api_key="key", turn_end_timeout_secs=0).validate()

        with self.assertRaises(RuntimeError):
            Settings(openai_api_key="key", openai_tts_speed=0).validate()

        with self.assertRaises(RuntimeError):
            Settings(openai_api_key="key", tts_cache_max_entries=0).validate()

        with self.assertRaises(RuntimeError):
            Settings(openai_api_key="key", tts_cache_max_bytes=0).validate()

        with self.assertRaises(RuntimeError):
            Settings(openai_api_key="key", transcript_debounce_secs=-0.1).validate()

    def test_validate_accepts_default_openai_runtime_settings(self):
        Settings(
            openai_api_key="key",
            vad_stop_secs=0.2,
            turn_end_timeout_secs=2.0,
        ).validate()

    def test_openai_model_defaults_are_set(self):
        with patch.dict(config_module.os.environ, {}, clear=True):
            settings = Settings(openai_api_key="key")

        self.assertEqual(settings.openai_stt_model, "gpt-4o-transcribe")
        self.assertIn("Transcribe Thai debt-collection phone calls", settings.openai_stt_prompt)
        self.assertEqual(settings.openai_intent_model, "gpt-4o-mini")
        self.assertEqual(settings.openai_tts_model, "gpt-4o-mini-tts")
        self.assertEqual(settings.openai_tts_voice, "coral")
        self.assertEqual(settings.openai_tts_speed, 1.2)
        self.assertIn("natural Thai", settings.openai_tts_instructions)
        self.assertTrue(settings.tts_cache_enabled)
        self.assertEqual(settings.tts_cache_max_entries, 128)
        self.assertEqual(settings.tts_cache_max_bytes, 67108864)
        self.assertTrue(settings.tts_cache_prewarm_enabled)
        self.assertEqual(settings.transcript_debounce_secs, 1.0)
        self.assertEqual(settings.vad_stop_secs, 0.4)


if __name__ == "__main__":
    unittest.main()
