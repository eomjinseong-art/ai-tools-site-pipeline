import io
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import content_queue
import promo_pipeline
from content_queue import CONSUMED_PATH
from full_orchestrator import make_card_image, orchestrate
from legacy_shorts_retirement import RETIREMENT_REASON, LegacyBlackCardShortsRetired
from supabase_source import video_is_filled
from youtube_upload import build_video_resource, credentials_from_env, upload_shorts


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / "fixtures" / "sample_video.json"


class RetirementGuardTests(unittest.TestCase):
    def test_reason_names_the_watermark_and_blocks_bypass_language(self):
        self.assertIn("나두 AI 요약", RETIREMENT_REASON)
        self.assertIn("beige/pastel", RETIREMENT_REASON)
        self.assertIn("explicit new design permission", RETIREMENT_REASON)
        self.assertIn("No environment variable", RETIREMENT_REASON)

    def test_skip_upload_still_refuses_generation(self):
        before = CONSUMED_PATH.read_text(encoding="utf-8")
        with TemporaryDirectory() as tmp:
            with mock.patch("promo_pipeline.render_final") as render:
                rc = promo_pipeline.main(["--input", str(FIXTURE), "--outdir", tmp, "--skip-upload"])
            self.assertEqual(rc, 2)
            render.assert_not_called()
            self.assertFalse((Path(tmp) / "final.mp4").exists())
            retired = json.loads((Path(tmp) / "retired.json").read_text(encoding="utf-8"))
            self.assertIn("나두 AI 요약", retired["reason"])
        self.assertEqual(CONSUMED_PATH.read_text(encoding="utf-8"), before)

    def test_privacy_and_allow_flags_do_not_publish(self):
        env = {
            "YT_PRIVACY_STATUS": "public",
            "PROMO_ALLOW_UPLOAD": "1",
            "GITHUB_ACTIONS": "true",
            "GITHUB_TOKEN": "not-a-real-token",
        }
        with TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, env, clear=False):
                with mock.patch("youtube_upload.credentials_from_env") as creds:
                    with mock.patch("youtube_upload.build_youtube_client") as client:
                        rc = promo_pipeline.main(["--outdir", tmp, "--input", str(FIXTURE)])
                        with self.assertRaises(LegacyBlackCardShortsRetired):
                            upload_shorts(str(Path(tmp) / "final.mp4"), "제목", "설명")
                        with self.assertRaises(LegacyBlackCardShortsRetired):
                            build_video_resource("제목", "설명")
            self.assertEqual(rc, 2)
            creds.assert_not_called()
            client.assert_not_called()
            self.assertFalse((Path(tmp) / "upload.json").exists())

    def test_direct_render_refuses_before_writing_a_card(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "card.png"
            with self.assertRaises(LegacyBlackCardShortsRetired) as raised:
                make_card_image("나두 AI 요약 테스트 문장입니다", str(out))
            self.assertIn("나두 AI 요약", str(raised.exception))
            self.assertFalse(out.exists())
            with self.assertRaises(LegacyBlackCardShortsRetired):
                orchestrate(tmp, metadata={"cards": ["열 글자가 넘는 카드 문장입니다"]})

    def test_dry_run_still_resolves_a_script_without_video_files(self):
        before = CONSUMED_PATH.read_text(encoding="utf-8")
        quiet = {"GITHUB_ACTIONS": "", "GITHUB_TOKEN": "", "GH_TOKEN": ""}
        with TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, quiet, clear=False):
                rc = promo_pipeline.main(["--input", str(FIXTURE), "--outdir", tmp, "--dry-run"])
            self.assertEqual(rc, 0)
            meta = json.loads((Path(tmp) / "metadata.json").read_text(encoding="utf-8"))
            self.assertTrue(meta["dry_run"])
            self.assertEqual(meta["script_id"], "chatgpt-handoff")
            self.assertFalse((Path(tmp) / "final.mp4").exists())
            self.assertFalse((Path(tmp) / "retired.json").exists())
            self.assertFalse((Path(tmp) / "upload.json").exists())
        self.assertEqual(CONSUMED_PATH.read_text(encoding="utf-8"), before)

    def test_content_queue_status_still_runs(self):
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            rc = content_queue.main(["status"])
        self.assertEqual(rc, 0)
        report = json.loads(buf.getvalue())
        self.assertIn("days_left", report)
        self.assertGreaterEqual(report["valid_scripts"], 1)
        self.assertIn("formula", report)

    def test_collector_row_filter_still_works(self):
        self.assertTrue(video_is_filled("훅 문장입니다", ["하나", "둘", "셋"], "정리합니다"))
        self.assertFalse(video_is_filled("", ["하나", "둘", "셋"], "정리합니다"))
        self.assertFalse(video_is_filled("훅 문장입니다", ["하나"], "정리합니다"))

    def test_credential_parser_does_not_upload(self):
        creds = credentials_from_env(
            {
                "YT_CLIENT_ID": "cid.apps.googleusercontent.com",
                "YT_CLIENT_SECRET": "secret",
                "YT_REFRESH_TOKEN": "refresh-token",
            }
        )
        self.assertEqual(creds.refresh_token, "refresh-token")
        with self.assertRaises(LegacyBlackCardShortsRetired):
            upload_shorts("clip.mp4", "제목", "설명")

    def test_workflow_and_deploy_script_cannot_publish(self):
        workflow = (ROOT / ".github" / "workflows" / "promo_upload.yml").read_text(encoding="utf-8")
        self.assertIn("name: Promo Shorts - Daily Publish", workflow)
        self.assertNotIn("schedule:", workflow)
        self.assertNotIn("cron:", workflow)
        self.assertNotIn("python promo_pipeline.py", workflow)
        self.assertNotIn("full_orchestrator.py", workflow)
        self.assertNotIn("youtube_upload.py", workflow)
        for secret in ("YT_CLIENT_ID", "YT_REFRESH_TOKEN", "SUPABASE_SERVICE_ROLE_KEY"):
            self.assertNotIn(secret, workflow)
        self.assertIn("exit 1", workflow)

        deploy = (ROOT / "deploy_to_repo.ps1").read_text(encoding="utf-8")
        self.assertIn("retired", deploy.lower())
        self.assertNotIn("git push", deploy.lower())
        self.assertNotIn("Copy-Item", deploy)
        self.assertIn("exit 1", deploy)

        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("on:\n  pull_request:", ci)
        self.assertNotIn("promo_pipeline.py", ci)
        self.assertNotIn("schedule:", ci)


if __name__ == "__main__":
    unittest.main()
