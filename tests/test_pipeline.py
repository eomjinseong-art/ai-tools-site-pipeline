import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import promo_pipeline
from content_queue import CONSUMED_PATH
from full_orchestrator import wrap_text_for_image
from PIL import Image, ImageDraw, ImageFont
ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / "fixtures" / "sample_video.json"
QUIET_GITHUB = {"GITHUB_ACTIONS": "", "GITHUB_TOKEN": "", "GH_TOKEN": ""}


class PipelineTests(unittest.TestCase):
    def test_dry_run_uses_queue_and_does_not_consume(self):
        before = CONSUMED_PATH.read_text(encoding="utf-8")
        with TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, QUIET_GITHUB, clear=False):
                rc = promo_pipeline.main(["--input", str(FIXTURE), "--outdir", tmp, "--dry-run"])
            self.assertEqual(rc, 0)
            out = Path(tmp)
            cards = json.loads((out / "cards.json").read_text(encoding="utf-8"))
            meta = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
            status = json.loads((out / "queue_status.json").read_text(encoding="utf-8"))
            self.assertTrue(meta["dry_run"])
            self.assertEqual(meta["script_source"], "queue")
            self.assertEqual(meta["script_id"], "chatgpt-handoff")
            self.assertIn("챗GPT", cards["card1_hook"])
            self.assertIn("days_left", status)
            self.assertFalse((out / "final.mp4").exists())
            self.assertFalse((out / "upload.json").exists())
        self.assertEqual(CONSUMED_PATH.read_text(encoding="utf-8"), before)

    def test_skip_rewrite_uses_template(self):
        with TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, QUIET_GITHUB, clear=False):
                rc = promo_pipeline.main(
                    ["--input", str(FIXTURE), "--outdir", tmp, "--dry-run", "--skip-rewrite"]
                )
            self.assertEqual(rc, 0)
            meta = json.loads((Path(tmp) / "metadata.json").read_text(encoding="utf-8"))
            cards = json.loads((Path(tmp) / "cards.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["script_source"], "template")
        self.assertIsNone(meta["script_id"])
        blob = " ".join(cards.values())
        self.assertIn("챗GPT", blob)
        self.assertNotIn("http", blob)

    def test_default_run_refuses_before_render_or_upload(self):
        before = CONSUMED_PATH.read_text(encoding="utf-8")
        with TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {**QUIET_GITHUB, "YT_PRIVACY_STATUS": "public"}, clear=False):
                with mock.patch("promo_pipeline.render_final") as render:
                    with mock.patch("promo_pipeline.pick_video") as pick:
                        rc = promo_pipeline.main(["--input", str(FIXTURE), "--outdir", tmp])
            self.assertEqual(rc, 2)
            render.assert_not_called()
            pick.assert_not_called()
            out = Path(tmp)
            self.assertFalse((out / "final.mp4").exists())
            self.assertFalse((out / "upload.json").exists())
            retired = json.loads((out / "retired.json").read_text(encoding="utf-8"))
            self.assertTrue(retired["retired"])
            self.assertIn("나두 AI 요약", retired["reason"])
        self.assertEqual(CONSUMED_PATH.read_text(encoding="utf-8"), before)

    def test_korean_wrap_splits_without_spaces(self):
        img = Image.new("RGB", (200, 200), "white")
        draw = ImageDraw.Draw(img)
        font = ImageFont.load_default()
        lines = wrap_text_for_image("가나다라마바사아자차카타파하", font, max_width=20, draw=draw)
        self.assertGreater(len(lines), 1)

    def test_workflow_has_no_paid_ai_secrets(self):
        workflow = (ROOT / ".github" / "workflows" / "promo_upload.yml").read_text(encoding="utf-8")
        self.assertIn("name: Promo Shorts - Daily Publish", workflow)
        self.assertNotIn("schedule:", workflow)
        self.assertNotIn("cron:", workflow)
        self.assertNotIn("promo_pipeline.py", workflow)
        self.assertNotIn("rewrite_driver.py", workflow)
        self.assertNotIn("OPENAI_API_KEY", workflow)
        self.assertNotIn("ELEVENLABS_API_KEY", workflow)
        self.assertNotIn("ELEVEN_VOICE_ID", workflow)
        self.assertNotIn("YT_", workflow)
        self.assertNotIn("openai", workflow.lower())
        self.assertNotIn("eleven", workflow.lower())
        self.assertNotIn("issues: write", workflow)
        self.assertNotIn("git push", workflow)
        self.assertIn("exit 1", workflow)
        self.assertFalse((ROOT / "elevenlabs_tts.py").exists())
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("pull_request:", ci)
        self.assertNotIn("schedule:", ci)
        self.assertIn("python -m unittest discover -s tests -v", ci)
        self.assertNotIn("promo_pipeline.py", ci)

    def test_sources_omit_personal_names_and_paid_sdks(self):
        forbidden_names = ("진" + "성", "로" + "빈", "엄" + "진" + "성")
        forbidden_sdks = ("openai", "elevenlabs", "eleven_api", "eleven_voice")
        roots = [ROOT]
        checked = 0
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            if ".git" in path.parts or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            if path.suffix.lower() not in {".py", ".yml", ".yaml", ".md", ".txt", ".json", ".sql", ".ps1"}:
                continue
            text = path.read_text(encoding="utf-8")
            checked += 1
            for name in forbidden_names:
                self.assertNotIn(name, text, f"{name} in {path}")
            if "tests" in path.parts:
                continue
            if path.suffix.lower() in {".py", ".yml", ".yaml", ".txt"}:
                lowered = text.lower()
                for sdk in forbidden_sdks:
                    self.assertNotIn(sdk, lowered, f"{sdk} in {path}")
        self.assertGreater(checked, 10)
        del roots


if __name__ == "__main__":
    unittest.main()
