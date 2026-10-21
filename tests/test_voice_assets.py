import io
import json
import tempfile
import unittest
import wave
from pathlib import Path

from web_server import _create_voice_profile


def wav_bytes(sample_rate=24000, frames=2400):
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(b"\0\0" * frames)
    return output.getvalue()


class VoiceAssetTests(unittest.TestCase):
    def test_create_voice_profile_saves_audio_transcript_and_default_selection(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            result = _create_voice_profile("new-voice", [
                ("voice/greeting.wav", wav_bytes()),
                ("voice/greeting.txt", b"Good morning."),
                ("voice/farewell.wav", wav_bytes(frames=3600)),
            ], Path(temporary_dir))

            profile_dir = Path(temporary_dir) / "new-voice"
            selection = json.loads((profile_dir / "selection.json").read_text(encoding="utf-8"))
            self.assertEqual(result["id"], "new-voice")
            self.assertEqual(set(selection["files"]), {"greeting.wav", "farewell.wav"})
            self.assertEqual((profile_dir / "greeting.txt").read_text(encoding="utf-8"), "Good morning.")

    def test_create_voice_profile_rejects_invalid_folder_and_mixed_sample_rates(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            with self.assertRaisesRegex(ValueError, "根目录名为 voice"):
                _create_voice_profile("new-voice", [("audio/greeting.wav", wav_bytes())], Path(temporary_dir))
            with self.assertRaisesRegex(ValueError, "采样率必须一致"):
                _create_voice_profile("new-voice", [
                    ("voice/one.wav", wav_bytes()),
                    ("voice/two.wav", wav_bytes(sample_rate=16000)),
                ], Path(temporary_dir))


if __name__ == "__main__":
    unittest.main()
