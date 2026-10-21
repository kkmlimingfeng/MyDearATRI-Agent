import io
import json
import os
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import modules.tts.qwen_gguf as qwen_gguf
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

    def test_voice_profiles_are_discovered_and_use_transcript_sidecars(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            voice_dir = Path(temporary_dir)
            atri_dir = voice_dir / "atri"
            custom_dir = voice_dir / "new-voice"
            atri_dir.mkdir()
            custom_dir.mkdir()

            def write_wav(path):
                with wave.open(str(path), "wb") as audio:
                    audio.setnchannels(1)
                    audio.setsampwidth(2)
                    audio.setframerate(24000)
                    audio.writeframes(b"\0\0" * 2400)

            for filename in qwen_gguf.PRESET_FILES:
                write_wav(atri_dir / filename)
            sample = custom_dir / "greeting.wav"
            write_wav(sample)
            sample.with_suffix(".txt").write_text("Good morning.", encoding="utf-8")

            with patch.object(qwen_gguf, "VOICE_DATA_DIR", voice_dir), patch.object(qwen_gguf, "REFERENCE_DIR", atri_dir):
                service = QwenGGUFTTS()
                references = service.references()
                custom = next(item for item in references if item["id"] == "new-voice/greeting.wav")
                payload, _ = service._reference_audio(custom["id"])

                self.assertEqual(references[0]["id"], "atri")
                self.assertEqual(custom["ref_text"], "Good morning.")
                self.assertEqual(service._reference_transcript(custom["id"]), "Good morning.")
                with wave.open(io.BytesIO(payload), "rb") as audio:
                    self.assertEqual(audio.getframerate(), 24000)

                with self.assertRaises(ValueError):
                    service._reference_audio("../atri/greeting.wav")

    def test_profile_selection_is_persisted_and_used_as_combined_reference(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            voice_dir = Path(temporary_dir)
            profile_dir = voice_dir / "sample-voice"
            profile_dir.mkdir()

            def write_wav(path, frames):
                with wave.open(str(path), "wb") as audio:
                    audio.setnchannels(1)
                    audio.setsampwidth(2)
                    audio.setframerate(24000)
                    audio.writeframes(b"\0\0" * frames)

            write_wav(profile_dir / "first.wav", 2400)
            write_wav(profile_dir / "second.wav", 4800)
            (profile_dir / "first.txt").write_text("first line", encoding="utf-8")
            (profile_dir / "second.txt").write_text("second line", encoding="utf-8")

            with patch.object(qwen_gguf, "VOICE_DATA_DIR", voice_dir), patch.object(qwen_gguf, "REFERENCE_DIR", voice_dir / "atri"):
                service = QwenGGUFTTS()
                service.set_voice_selection("sample-voice", ["second.wav"])
                payload, _ = service._reference_audio("sample-voice")
                selection = json.loads((profile_dir / "selection.json").read_text(encoding="utf-8"))
                profile = next(item for item in service.voice_profiles() if item["id"] == "sample-voice")

                self.assertEqual(selection["files"], ["second.wav"])
                self.assertEqual(service._reference_transcript("sample-voice"), "second line")
                self.assertEqual([clip["name"] for clip in profile["clips"] if clip["selected"]], ["second.wav"])
                with wave.open(io.BytesIO(payload), "rb") as audio:
                    self.assertEqual(audio.getnframes(), 4800)


if __name__ == "__main__":
    unittest.main()
