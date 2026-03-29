import unittest

from common.html import get_html_page


class HtmlTests(unittest.TestCase):
    def test_html_includes_explicit_bot_audio_playback_and_cleanup_hooks(self):
        page = get_html_page("Test", "collection")

        self.assertIn('<audio id="bot-audio" autoplay playsinline></audio>', page)
        self.assertIn("await botAudio.play();", page)
        self.assertIn("Bot audio playback started", page)
        self.assertIn("function stopBotAudioMonitor()", page)
        self.assertIn("stopBotAudioMonitor();", page)


if __name__ == "__main__":
    unittest.main()
