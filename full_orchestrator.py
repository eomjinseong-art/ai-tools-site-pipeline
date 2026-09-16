"""
Full orchestrator: rewrite -> card images -> ElevenLabs TTS -> clips -> final.mp4

Usage:
  python full_orchestrator.py --outdir out --input metadata.json

Prefer promo_pipeline.py for the daily job. This module only renders.
Requires: ffmpeg, ffprobe. Python deps: pillow.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from typing import Dict, List, Optional

from PIL import Image, ImageDraw, ImageFont

try:
    import rewrite_for_shorts
except Exception as exc:
    rewrite_for_shorts = None
    logging.warning("rewrite_for_shorts not importable: %s", exc)

try:
    import elevenlabs_tts
except Exception as exc:
    elevenlabs_tts = None
    logging.warning("elevenlabs_tts not importable: %s", exc)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

DEFAULT_FONTS = [
    "assets/NotoSansKR-Bold.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansKR-Bold.ttf",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
]


def check_command(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"Required command '{name}' not found in PATH. Install ffmpeg/ffprobe.")


def run(cmd: List[str], check: bool = True) -> None:
    logging.debug("RUN: %s", " ".join(cmd))
    subprocess.run(cmd, check=check)


def ffprobe_duration(path: str) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        logging.warning("ffprobe failed for %s: %s", path, res.stderr)
        return 0.0
    try:
        return float(res.stdout.strip())
    except ValueError:
        return 0.0


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def load_font(preferred_paths: List[Optional[str]], size: int):
    for p in preferred_paths:
        if not p or not os.path.exists(p):
            continue
        try:
            return ImageFont.truetype(p, size=size)
        except Exception:
            try:
                return ImageFont.truetype(p, size=size, index=0)
            except Exception:
                continue
    logging.warning("Preferred fonts not found; using default PIL font.")
    return ImageFont.load_default()


def wrap_text_for_image(text: str, font, max_width: int, draw: ImageDraw.ImageDraw) -> List[str]:
    text = (text or "").strip()
    if not text:
        return [""]

    def wider_than(s: str) -> bool:
        box = draw.textbbox((0, 0), s, font=font)
        return (box[2] - box[0]) > max_width

    if " " in text:
        words = text.split()
        lines: List[str] = []
        cur = words[0]
        for w in words[1:]:
            test = f"{cur} {w}"
            if wider_than(test):
                lines.append(cur)
                cur = w
            else:
                cur = test
        lines.append(cur)
        if not any(wider_than(line) for line in lines):
            return lines

    lines = []
    cur = ""
    for ch in text:
        test = cur + ch
        if cur and wider_than(test):
            lines.append(cur)
            cur = ch
        else:
            cur = test
    if cur:
        lines.append(cur)
    return lines or [""]


def make_card_image(text: str, outpath: str, width: int = 1080, height: int = 1920, font_path: Optional[str] = None):
    bg_color = (18, 18, 18)
    text_color = (255, 255, 255)
    accent = (255, 90, 90)
    padding = 80

    img = Image.new("RGB", (width, height), color=bg_color)
    draw = ImageDraw.Draw(img)
    font_candidates = [font_path, *DEFAULT_FONTS]
    max_text_width = width - padding * 2

    size = 64
    while True:
        font = load_font(font_candidates, size=size)
        lines = wrap_text_for_image(text, font, max_text_width, draw)
        line_box = draw.textbbox((0, 0), "가", font=font)
        line_h = max(line_box[3] - line_box[1], 1)
        total_h = len(lines) * (line_h + 12)
        if total_h <= height - padding * 2 or size <= 28:
            break
        size = int(size * 0.9)

    y0 = (height - total_h) // 2
    draw.rectangle([padding, padding // 2, width - padding, padding // 2 + 8], fill=accent)

    for i, line in enumerate(lines):
        wbox = draw.textbbox((0, 0), line, font=font)
        w = wbox[2] - wbox[0]
        h = wbox[3] - wbox[1]
        x = (width - w) // 2
        y = y0 + i * (h + 12)
        draw.text((x + 2, y + 2), line, font=font, fill=(0, 0, 0))
        draw.text((x, y), line, font=font, fill=text_color)

    footer_font = load_font(font_candidates, size=36)
    footer_text = "나두 AI 요약"
    fbox = draw.textbbox((0, 0), footer_text, font=footer_font)
    fx = width - padding - (fbox[2] - fbox[0])
    fy = height - int(padding / 1.5) - (fbox[3] - fbox[1])
    draw.text((fx, fy), footer_text, font=footer_font, fill=(200, 200, 200))

    img.save(outpath, quality=95)
    logging.info("Wrote card image: %s", outpath)


def make_clip_from_image_and_audio(image_path: str, audio_path: str, outpath: str, target_w: int = 1080, target_h: int = 1920):
    dur = ffprobe_duration(audio_path)
    if dur <= 0.01:
        logging.warning("Audio duration <= 0 for %s, creating 1s silent clip", audio_path)
        silent = audio_path + ".sil.wav"
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=22050", "-t", "1.0", silent])
        audio_path = silent
        dur = 1.0

    fade_d = min(0.18, dur / 4.0)
    vf = f"scale={target_w}:{target_h},fade=t=in:st=0:d={fade_d},fade=t=out:st={max(0, dur - fade_d)}:d={fade_d}"
    af = f"afade=t=in:st=0:d={min(0.1, fade_d)},afade=t=out:st={max(0, dur - min(0.1, fade_d))}:d={min(0.1, fade_d)}"
    cmd = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-i",
        image_path,
        "-i",
        audio_path,
        "-t",
        f"{dur:.3f}",
        "-filter_complex",
        f"[0:v]{vf}[v];[1:a]{af}[a]",
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-pix_fmt",
        "yuv420p",
        "-shortest",
        outpath,
    ]
    run(cmd)
    logging.info("Created clip %s (dur %.2fs)", outpath, dur)
    return dur


def concat_clips(clip_paths: List[str], outpath: str) -> None:
    concat_file = outpath + ".concat.txt"
    with open(concat_file, "w", encoding="utf-8") as f:
        for p in clip_paths:
            f.write(f"file '{os.path.abspath(p)}'\n")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_file, "-c", "copy", outpath])
    logging.info("Concatenated %d clips into %s", len(clip_paths), outpath)


def make_thumbnail_from_card(card_image_path: str, outpath: str, short_title: Optional[str] = None) -> None:
    im = Image.open(card_image_path).convert("RGB")
    target = (1280, 720)
    im_ratio = im.width / im.height
    t_ratio = target[0] / target[1]
    if im_ratio > t_ratio:
        new_h = im.height
        new_w = int(new_h * t_ratio)
        left = (im.width - new_w) // 2
        im = im.crop((left, 0, left + new_w, new_h))
    else:
        new_w = im.width
        new_h = int(new_w / t_ratio)
        top = (im.height - new_h) // 2
        im = im.crop((0, top, new_w, top + new_h))
    im = im.resize(target, Image.LANCZOS)
    draw = ImageDraw.Draw(im)
    if short_title:
        font = load_font(DEFAULT_FONTS, size=48)
        tb = draw.textbbox((0, 0), short_title, font=font)
        x, y = 40, 40
        draw.rectangle([x - 10, y - 10, x + tb[2] - tb[0] + 20, y + tb[3] - tb[1] + 10], fill=(0, 0, 0))
        draw.text((x, y), short_title, font=font, fill=(255, 255, 255))
    im.save(outpath, quality=90)
    logging.info("Wrote thumbnail: %s", outpath)


def _cards_from_metadata(metadata: Optional[Dict]) -> List[str]:
    if not metadata:
        return []
    raw = metadata.get("cards")
    if isinstance(raw, dict) and rewrite_for_shorts is not None:
        return rewrite_for_shorts.cards_as_list(raw)
    if isinstance(raw, list) and raw:
        out = []
        for item in raw:
            if isinstance(item, dict):
                out.append(str(item.get("text") or item.get("card") or "").strip())
            else:
                out.append(str(item).strip())
        return [c for c in out if c]
    return []


def synthesize_card_audio(text: str, audio_path: str, allow_silent_tts: bool) -> None:
    voice_id = os.environ.get("ELEVEN_VOICE_ID")
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if elevenlabs_tts is None or not voice_id or not api_key:
        if allow_silent_tts:
            run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=22050", "-t", "1.0", audio_path])
            return
        raise RuntimeError("ELEVENLABS_API_KEY와 ELEVEN_VOICE_ID가 필요합니다.")
    ok = elevenlabs_tts.synthesize_to_wav(text, voice_id=voice_id, out_path=audio_path, api_key=api_key)
    if not ok:
        raise RuntimeError(f"ElevenLabs TTS 실패: {audio_path}")


def orchestrate(
    outdir: str,
    metadata: Optional[Dict] = None,
    font_path: Optional[str] = None,
    allow_silent_tts: Optional[bool] = None,
) -> Dict:
    check_command("ffmpeg")
    check_command("ffprobe")
    ensure_dir(outdir)
    temp_dir = os.path.join(outdir, "tmp")
    ensure_dir(temp_dir)

    if allow_silent_tts is None:
        allow_silent_tts = os.environ.get("PROMO_ALLOW_SILENT_TTS", "").strip() in {"1", "true", "yes"}

    cards = _cards_from_metadata(metadata)
    short_title = (metadata or {}).get("short_title") or (metadata or {}).get("title")

    if not cards:
        if rewrite_for_shorts is None:
            raise RuntimeError("No cards provided and rewrite_for_shorts module not available.")
        hook = (metadata.get("hook") if metadata else "") or ""
        summary_points = (metadata.get("summary_points") if metadata else []) or []
        takeaway = (metadata.get("takeaway") if metadata else "") or ""
        logging.info("Calling rewrite_for_shorts.rewrite_summary_for_shorts()")
        cards_struct = rewrite_for_shorts.rewrite_summary_for_shorts(hook, summary_points, takeaway)
        if isinstance(cards_struct, dict):
            cards = rewrite_for_shorts.cards_as_list(cards_struct)
            short_title = short_title or cards_struct.get("card1_hook")
        elif isinstance(cards_struct, list) and cards_struct:
            cards = [str(c.get("text") if isinstance(c, dict) else c) for c in cards_struct]
        else:
            raise RuntimeError("rewrite_for_shorts returned no cards")

    if len(cards) < 1:
        raise RuntimeError("No card texts to render")
    logging.info("Got %d cards", len(cards))

    card_image_paths = []
    clip_paths = []
    durations = []

    for i, text in enumerate(cards, start=1):
        img_path = os.path.join(temp_dir, f"card_{i:02d}.png")
        make_card_image(text, img_path, font_path=font_path)
        card_image_paths.append(img_path)

        audio_path = os.path.join(temp_dir, f"card_{i:02d}.wav")
        logging.info("Synthesizing audio for card %d...", i)
        synthesize_card_audio(text, audio_path, allow_silent_tts=allow_silent_tts)

        clip_path = os.path.join(temp_dir, f"clip_{i:02d}.mp4")
        durations.append(make_clip_from_image_and_audio(img_path, audio_path, clip_path))
        clip_paths.append(clip_path)

    raw_out = os.path.join(outdir, "raw_concat.mp4")
    concat_clips(clip_paths, raw_out)

    final_out = os.path.join(outdir, "final.mp4")
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            raw_out,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            final_out,
        ]
    )

    thumb_path = os.path.join(outdir, "thumbnail.jpg")
    make_thumbnail_from_card(card_image_paths[0], thumb_path, short_title)

    meta = {
        "cards_count": len(cards),
        "cards": cards,
        "durations": durations,
        "final_path": os.path.abspath(final_out),
        "thumbnail": os.path.abspath(thumb_path),
        "title": (metadata or {}).get("title"),
        "source_id": (metadata or {}).get("id"),
        "source_youtube_id": (metadata or {}).get("youtube_id"),
    }
    meta_path = os.path.join(outdir, "metadata.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    logging.info("Pipeline complete. final video: %s", final_out)
    return meta


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--outdir", "-o", default="out", help="Output directory")
    p.add_argument("--input", "-i", help="Optional metadata JSON")
    p.add_argument("--font", help="Optional font file path (TTF/TTC)")
    return p.parse_args()


def main():
    args = parse_args()
    ensure_dir(args.outdir)
    metadata = None
    if args.input:
        with open(args.input, "r", encoding="utf-8") as f:
            metadata = json.load(f)
    try:
        orchestrate(args.outdir, metadata=metadata, font_path=args.font)
    except Exception as exc:
        logging.exception("Pipeline failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
