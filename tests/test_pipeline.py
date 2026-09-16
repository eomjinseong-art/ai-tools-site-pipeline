import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import promo_pipeline
from full_orchestrator import wrap_text_for_image
from PIL import ImageDraw, ImageFont, Image


class PipelineTests(unittest.TestCase):
    def test_dry_run_writes_cards_not_upload(self):
        fixture = Path(__file__).parent / "fixtures" / "sample_video.json"
        cards = {
            "card1_hook": "반복 업무를 바로 맡기는 방법",
            "card2": "이메일 초안은 먼저 맡기세요",
            "card3": "표와 요약은 템플릿으로 고정",
            "card4": "결과는 사람이 한 번 검수하세요",
            "card5_takeaway": "템플릿만 있으면 시간을 줄입니다",
        }
        with TemporaryDirectory() as tmp:
            with mock.patch("promo_pipeline.rewrite_summary_for_shorts", return_value=cards):
                rc = promo_pipeline.main(["--input", str(fixture), "--outdir", tmp, "--dry-run"])
            self.assertEqual(rc, 0)
            out = Path(tmp)
            self.assertTrue((out / "cards.json").is_file())
            self.assertTrue((out / "metadata.json").is_file())
            self.assertFalse((out / "final.mp4").exists())
            self.assertFalse((out / "upload.json").exists())
            meta = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
            self.assertTrue(meta["dry_run"])

    def test_korean_wrap_splits_without_spaces(self):
        img = Image.new("RGB", (200, 200), "white")
        draw = ImageDraw.Draw(img)
        font = ImageFont.load_default()
        lines = wrap_text_for_image("가나다라마바사아자차카타파하", font, max_width=20, draw=draw)
        self.assertGreater(len(lines), 1)

    def test_workflow_calls_real_entrypoint(self):
        workflow = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "promo_upload.yml"
        text = workflow.read_text(encoding="utf-8")
        self.assertIn("promo_pipeline.py", text)
        self.assertNotIn("rewrite_driver.py", text)
        self.assertNotIn("rewrite only", text)


if __name__ == "__main__":
    unittest.main()
