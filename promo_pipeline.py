"""
Script check for the retired Shorts publisher.

Black-card generation and YouTube upload are refused. `--dry-run` still
resolves a script to JSON and does not render or upload. Any other invocation
exits 2 before the collector, TTS, render, or upload.

The beige/pastel 9-card carousel is a separate pipeline and is not this file.
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
    resolve_shorts_script,
)
from github_issues import sync_queue_issue
from legacy_shorts_retirement import RETIREMENT_EXIT_CODE, RETIREMENT_REASON, refuse_legacy_black_card_shorts
from supabase_source import CollectorVideo, SupabaseSource, row_to_video

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
    p = argparse.ArgumentParser(description="Retired black-card Shorts publisher. Only --dry-run resolves a script.")
    p.add_argument("--outdir", "-o", default="out", help="Output directory")
    p.add_argument("--input", "-i", help="Optional local JSON instead of Supabase (dry-run only)")
    p.add_argument("--font", help="Ignored. Black-card rendering is retired.")
    p.add_argument("--dry-run", action="store_true", help="Resolve a script to JSON; no TTS, render, or upload")
    p.add_argument("--skip-upload", action="store_true", help="Retired. Generation is refused together with upload.")
    p.add_argument("--skip-rewrite", action="store_true", help="Dry-run only: use the deterministic template")
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
    del outdir, video, cards, font
    refuse_legacy_black_card_shorts("Black-card Shorts render")
    return {}


def refuse_publication(outdir: Path) -> int:
    """Stop before collector reads, render, upload, or script-id consumption."""
    logging.error("%s", RETIREMENT_REASON)
    print(RETIREMENT_REASON, file=sys.stderr)
    try:
        write_json(
            outdir / "retired.json",
            {
                "retired": True,
                "exit_code": RETIREMENT_EXIT_CODE,
                "reason": RETIREMENT_REASON,
            },
        )
    except OSError:
        logging.exception("could not write retired.json")
    return RETIREMENT_EXIT_CODE


def main(argv: Optional[list] = None) -> int:
    args = parse_args(argv)
    if os.environ.get("PROMO_DRY_RUN", "").strip() in {"1", "true", "yes"}:
        args.dry_run = True

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    if not args.dry_run:
        return refuse_publication(outdir)

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

    return refuse_publication(outdir)


if __name__ == "__main__":
    sys.exit(main())
