"""
Daily Shorts pipeline entrypoint.

  1. Pick one unpublished-for-shorts video from the collector Supabase DB
  2. Use a pre-written script, or a deterministic template if that tool has none
  3. TTS (edge-tts, then gTTS) + render vertical final.mp4
  4. Upload to YouTube Shorts
  5. Mark the video and the consumed script id

Usage:
  python promo_pipeline.py
  python promo_pipeline.py --dry-run
  python promo_pipeline.py --input fixture.json --skip-upload
  python promo_pipeline.py --skip-upload   # render only

GitHub Actions must call this file, not rewrite_driver.py.
No paid LLM or TTS API key is required.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from content_queue import (
    build_queue_report,
    consumed_state_paths,
    mark_script_consumed,
    resolve_shorts_script,
)
from github_issues import open_youtube_reauth_issue, sync_queue_issue
from rewrite_for_shorts import cards_as_list
from supabase_source import CollectorVideo, SupabaseSource, row_to_video
from youtube_upload import (
    YouTubeAuthExpired,
    YouTubeUploadError,
    build_shorts_description,
    build_shorts_title,
    upload_shorts,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def video_from_input(payload: Dict[str, Any]) -> CollectorVideo:
    if "hook" in payload:
        return row_to_video(
            {
                "id": payload.get("id") or payload.get("youtube_id") or "local-input",
                "youtube_id": payload.get("youtube_id") or "",
                "title": payload.get("title") or payload.get("short_title") or payload.get("hook") or "",
                "hook": payload.get("hook") or "",
                "summary_points": payload.get("summary_points") or [],
                "takeaway": payload.get("takeaway") or "",
                "published_at": payload.get("published_at"),
                "status": payload.get("status") or "published",
            }
        )
    raise SystemExit("입력 JSON에 hook/summary_points/takeaway가 필요합니다.")


def parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Nadoo AI YouTube Shorts daily publisher")
    p.add_argument("--outdir", "-o", default="out", help="Output directory")
    p.add_argument("--input", "-i", help="Optional local JSON instead of Supabase")
    p.add_argument("--font", help="Optional TTF/TTC path for Korean cards")
    p.add_argument("--dry-run", action="store_true", help="Rewrite only; no TTS/render/upload")
    p.add_argument("--skip-upload", action="store_true", help="Render final.mp4 but do not upload")
    p.add_argument("--skip-rewrite", action="store_true", help="Use source texts as cards (debug)")
    return p.parse_args(argv)


def pick_video(args: argparse.Namespace, outdir: Path) -> Optional[CollectorVideo]:
    if args.input:
        payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
        video = video_from_input(payload)
        logging.info("Using local input %s (%s)", args.input, video.title)
        return video

    source = SupabaseSource(state_path=outdir / "promo_shorts_state.json")
    video = source.pick_next()
    if video is None:
        payload = {
            "skipped": True,
            "reason": "no unpublished published videos with hook/summary_points/takeaway",
        }
        write_json(outdir / "skipped.json", payload)
        logging.info("No eligible collector video. Wrote %s", outdir / "skipped.json")
        return None
    write_json(outdir / "source_video.json", video.to_metadata())
    logging.info("Picked collector video %s — %s", video.id, video.title)
    return video


def video_payload(video: CollectorVideo) -> Dict[str, Any]:
    data = video.to_metadata()
    extra = video.extra or {}
    for key in (
        "tool_name",
        "name",
        "one_line",
        "description",
        "key_features",
        "features",
        "link",
        "url",
        "cta_url",
    ):
        if extra.get(key) and not data.get(key):
            data[key] = extra[key]
    return data


def resolve_cards(video: CollectorVideo, outdir: Path, force_template: bool):
    return resolve_shorts_script(
        video_payload(video),
        outdir=outdir,
        force_template=force_template,
    )


def alert_queue_if_needed(outdir: Path) -> Dict[str, Any]:
    """14일분 미만이면 이슈를 열거나 갱신한다. 실패해도 업로드는 계속한다."""
    try:
        report = build_queue_report(outdir=outdir)
        write_json(outdir / "queue_status.json", report)
        logging.info(
            "[queue] days_left=%s unused=%s low_water=%s",
            report.get("days_left"),
            report.get("unused_scripts"),
            report.get("low_water"),
        )
        result = sync_queue_issue(report)
        if not result.get("skipped"):
            logging.info("[queue] GitHub issue action=%s title=%s", result.get("action"), result.get("title"))
        return report
    except Exception:
        logging.exception("[queue] low-water check failed")
        return {}


def render_final(outdir: str, video: CollectorVideo, cards: Dict[str, str], font: Optional[str]) -> Dict[str, Any]:
    from full_orchestrator import orchestrate

    metadata = video.to_metadata()
    metadata["cards"] = cards_as_list(cards)
    metadata["short_title"] = cards.get("card1_hook") or video.hook
    return orchestrate(outdir, metadata=metadata, font_path=font, allow_silent_tts=False)


def main(argv: Optional[list] = None) -> int:
    args = parse_args(argv)
    if os.environ.get("PROMO_DRY_RUN", "").strip() in {"1", "true", "yes"}:
        args.dry_run = True

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    alert_queue_if_needed(outdir)

    video = pick_video(args, outdir)
    if video is None:
        return 0

    try:
        choice = resolve_cards(video, outdir, force_template=args.skip_rewrite)
        cards = choice.cards
    except Exception:
        logging.exception("Script resolve failed; using template")
        try:
            choice = resolve_cards(video, outdir, force_template=True)
            cards = choice.cards
        except Exception:
            logging.exception("Template fallback failed")
            return 1

    write_json(outdir / "cards.json", cards)
    write_json(outdir / "script.json", choice.to_meta())

    if args.dry_run:
        write_json(
            outdir / "metadata.json",
            {
                "dry_run": True,
                "title": video.title,
                "cards": cards,
                "source_id": video.id,
                "script_source": choice.source,
                "script_id": choice.script_id,
            },
        )
        logging.info("Dry-run complete (no render/upload).")
        return 0

    try:
        render_meta = render_final(str(outdir), video, cards, args.font)
    except Exception:
        logging.exception("Render failed")
        return 1

    final_path = Path(render_meta.get("final_path") or (outdir / "final.mp4"))
    if not final_path.is_file():
        logging.error("final.mp4 was not produced")
        return 1

    if args.skip_upload:
        write_json(outdir / "upload.json", {"skipped": True, "reason": "--skip-upload"})
        logging.info("Render complete; upload skipped.")
        return 0

    title = build_shorts_title(video.title, hook=cards.get("card1_hook") or video.hook)
    tool_link = (choice.link or "").strip()
    extra = f"도구 링크: {tool_link}" if tool_link else None
    description = build_shorts_description(
        video.title,
        cards.get("card5_takeaway") or video.takeaway,
        video.youtube_id,
        extra=extra,
    )

    try:
        yt_id = upload_shorts(
            video_path=str(final_path),
            title=title,
            description=description,
            thumbnail_path=render_meta.get("thumbnail"),
        )
    except YouTubeAuthExpired:
        logging.exception("[youtube] invalid_grant")
        issue: Dict[str, Any] = {"error": "invalid_grant"}
        try:
            issue = open_youtube_reauth_issue()
            logging.error("[youtube] opened or updated issue: %s", issue.get("number") or issue)
        except Exception:
            logging.exception("[youtube] failed to open reauth issue")
        write_json(outdir / "youtube_auth_error.json", {"error": "invalid_grant", "issue": issue})
        return 1
    except YouTubeUploadError:
        logging.exception("YouTube upload failed")
        return 1
    except Exception:
        logging.exception("YouTube upload failed")
        return 1

    mark = SupabaseSource(state_path=outdir / "promo_shorts_state.json").mark_uploaded(video.id, yt_id)
    if choice.source == "queue" and choice.script_id:
        try:
            mark_script_consumed(choice.script_id, consumed_state_paths(outdir))
        except Exception:
            logging.exception("[queue] failed to record consumed script id %s", choice.script_id)
    write_json(
        outdir / "upload.json",
        {
            "youtube_id": yt_id,
            "url": f"https://www.youtube.com/shorts/{yt_id}",
            "title": title,
            "source_video_id": video.id,
            "source_youtube_id": video.youtube_id,
            "script_source": choice.source,
            "script_id": choice.script_id,
            "tracking": mark,
        },
    )
    logging.info("Published Shorts %s", yt_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
