import unittest
from unittest.mock import patch

import common.config as config_module
from common.config import Settings


class SettingsTests(unittest.TestCase):
    def test_validate_rejects_missing_gemini_api_key(self):
        with self.assertRaises(RuntimeError):
            Settings(gemini_api_key="").validate()

    def test_validate_accepts_default_gemini_runtime_settings(self):
        Settings(gemini_api_key="key").validate()

    def test_gemini_model_defaults_are_set(self):
        with patch.dict(config_module.os.environ, {}, clear=True):
            settings = Settings(gemini_api_key="key")

        self.assertEqual(
            settings.gemini_live_model,
            "gemini-3.1-flash-live-preview",
        )
        self.assertEqual(settings.gemini_live_voice, "Aoede")

    def test_google_api_key_is_accepted_as_fallback(self):
        with patch.dict(config_module.os.environ, {"GOOGLE_API_KEY": "google-key"}, clear=True):
            settings = Settings()

        self.assertEqual(settings.gemini_api_key, "google-key")


if __name__ == "__main__":
    unittest.main()
