import tempfile
import unittest
from pathlib import Path

from web_server import _click_audio_files


class Live2DClickAudioTests(unittest.TestCase):
    def test_audio_directory_is_rescanned_and_non_audio_files_are_ignored(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            audio_dir = Path(temporary_dir)
            (audio_dir / "first.wav").write_bytes(b"first")
            (audio_dir / "notes.txt").write_text("not audio", encoding="utf-8")

            self.assertEqual([path.name for path in _click_audio_files(audio_dir)], ["first.wav"])

            (audio_dir / "second.mp3").write_bytes(b"second")
            self.assertEqual(
                sorted(path.name for path in _click_audio_files(audio_dir)),
                ["first.wav", "second.mp3"],
            )

    def test_missing_audio_directory_returns_no_files(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            missing_dir = Path(temporary_dir) / "missing"
            self.assertEqual(_click_audio_files(missing_dir), [])


if __name__ == "__main__":
    unittest.main()
