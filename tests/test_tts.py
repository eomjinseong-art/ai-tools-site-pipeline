import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import tts


class TtsTests(unittest.TestCase):
    def test_edge_retries_with_backoff_then_succeeds(self):
        sleeps = []

        def edge_save(text, voice, path):
            edge_save.calls += 1
            if edge_save.calls < 3:
                raise RuntimeError("temporary outage")
            Path(path).write_bytes(b"a" * 120)

        edge_save.calls = 0

        def gtts_save(text, path):
            raise AssertionError("gTTS should not run after edge-tts succeeds")

        with TemporaryDirectory() as tmp:
            out = str(Path(tmp) / "voice.mp3")
            engine = tts.synthesize_speech(
                "안녕하세요 테스트 음성입니다",
                out,
                voice="ko-KR-InJoonNeural",
                sleep=sleeps.append,
                edge_save=edge_save,
                gtts_save=gtts_save,
            )
            self.assertTrue(Path(out).is_file())
        self.assertEqual(engine, "edge-tts")
        self.assertEqual(edge_save.calls, 3)
        self.assertEqual(sleeps, [1.0, 2.0])

    def test_falls_back_to_gtts_after_edge_failures(self):
        def edge_save(text, voice, path):
            raise RuntimeError("edge down")

        def gtts_save(text, path):
            Path(path).write_bytes(b"b" * 90)

        with TemporaryDirectory() as tmp:
            out = str(Path(tmp) / "voice.mp3")
            engine = tts.synthesize_speech(
                "폴백 음성 테스트 문장입니다",
                out,
                sleep=lambda _delay: None,
                max_attempts=3,
                edge_save=edge_save,
                gtts_save=gtts_save,
            )
        self.assertEqual(engine, "gtts")

    def test_single_attempt_does_not_sleep(self):
        sleeps = []

        def edge_save(text, voice, path):
            raise RuntimeError("nope")

        def gtts_save(text, path):
            Path(path).write_bytes(b"c" * 80)

        tts.synthesize_speech(
            "한 번만 시도하는 문장입니다",
            str(Path(self._tmp()) / "v.mp3"),
            sleep=sleeps.append,
            max_attempts=1,
            edge_save=edge_save,
            gtts_save=gtts_save,
        )
        self.assertEqual(sleeps, [])

    def test_empty_text_raises(self):
        with self.assertRaises(tts.TtsError):
            tts.synthesize_speech("  ", "out.mp3", edge_save=lambda *args: None, gtts_save=lambda *args: None)

    def test_default_voice_and_pinned_requirements(self):
        self.assertEqual(tts.DEFAULT_VOICE, "ko-KR-SunHiNeural")
        self.assertEqual(tts.ALTERNATE_VOICE, "ko-KR-InJoonNeural")
        with mock.patch.dict(os.environ, {"EDGE_TTS_VOICE": "ko-KR-InJoonNeural"}):
            self.assertEqual(tts.resolve_voice(), "ko-KR-InJoonNeural")
        requirements = Path(__file__).resolve().parents[1].joinpath("requirements.txt").read_text(encoding="utf-8")
        self.assertIn(f"edge-tts=={tts.EDGE_TTS_VERSION}", requirements)
        self.assertEqual(tts.EDGE_TTS_VERSION, "7.3.1")
        self.assertIn("gTTS==2.5.4", requirements)
        lowered = requirements.lower()
        self.assertNotIn("openai", lowered)
        self.assertNotIn("eleven", lowered)

    def _tmp(self):
        holder = TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        return holder.name


if __name__ == "__main__":
    unittest.main()
