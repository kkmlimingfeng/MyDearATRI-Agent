import os
import unittest
from unittest.mock import patch

from modules.tts.qwen_gguf import DEFAULT_TTS_URL, QwenGGUFTTS


class TTSPortTests(unittest.TestCase):
    def test_default_endpoint_uses_port_8767(self):
        with patch.dict(os.environ, {}, clear=True):
            service = QwenGGUFTTS()

        self.assertEqual(service.url, DEFAULT_TTS_URL)
        self.assertEqual(service._local_port, 8767)
        self.assertTrue(service._can_start_local)

    def test_custom_loopback_endpoint_uses_configured_port(self):
        with patch.dict(os.environ, {"ATRI_TTS_URL": "http://127.0.0.1:9876"}):
            service = QwenGGUFTTS()

        self.assertEqual(service._local_port, 9876)
        self.assertTrue(service._can_start_local)

    def test_remote_endpoint_is_not_started_as_a_local_server(self):
        with patch.dict(os.environ, {"ATRI_TTS_URL": "http://tts-host:8767"}):
            service = QwenGGUFTTS()

        self.assertFalse(service._can_start_local)


if __name__ == "__main__":
    unittest.main()
