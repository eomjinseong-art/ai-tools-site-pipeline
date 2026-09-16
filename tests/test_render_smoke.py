import json
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from full_orchestrator import orchestrate


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe required")
class RenderSmokeTests(unittest.TestCase):
    def test_silent_cards_produce_vertical_mp4(self):
        metadata = {
            "title": "스모크 테스트",
            "short_title": "카드 렌더 확인",
            "cards": [
                "반복 업무를 바로 맡기는 방법",
                "이메일 초안은 먼저 맡기세요",
                "표와 요약은 템플릿으로 고정",
                "결과는 사람이 한 번 검수하세요",
                "템플릿만 있으면 시간을 줄입니다",
            ],
        }
        with TemporaryDirectory() as tmp:
            meta = orchestrate(tmp, metadata=metadata, allow_silent_tts=True)
            final_path = Path(meta["final_path"])
            self.assertTrue(final_path.is_file())
            self.assertGreater(final_path.stat().st_size, 1000)
            saved = json.loads((Path(tmp) / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["cards_count"], 5)
