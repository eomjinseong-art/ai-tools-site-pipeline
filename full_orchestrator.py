# full_orchestrator.py
"""
Full orchestrator: rewrite -> card images -> elevenlabs TTS -> per-card clips -> concat -> final.mp4
Usage:
  python full_orchestrator.py --outdir out --input metadata.json
If metadata.json is omitted, the script will call rewrite_for_shorts.rewrite_summary_for_shorts()
to produce cards (needs rewrite_for_shorts.py available).
Requires: ffmpeg, ffprobe on PATH. Python deps: pillow, requests.
"""

import os
import sys
import json
import math
import textwrap
import shutil
import subprocess
import argparse
import logging
from typing import List, Dict, Optional
from PIL import Image, ImageDraw, ImageFont

# Try to import user-provided modules (they were created earlier in the project)
try:
    import rewrite_for_shorts
except Exception as e:
    rewrite_for_shorts = None
    logging.warning("rewrite_for_shorts not importable: %s", e)

try:
    import elevenlabs_tts
except Exception as e:
    elevenlabs_tts = None
    logging.warning("elevenlabs_tts not importable: %s", e)


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


# ---------- helpers ----------

def check_command(name: str):
    if shutil.which(name) is None:
        raise RuntimeError(f"Required command '{name}' not found in PATH. Install ffmpeg/ffprobe.")


def run(cmd: List[str], check=True):
    logging.debug("RUN: %s", " ".join(cmd))
    subprocess.run(cmd, check=check)


def ffprobe_duration(path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        logging.warning("ffprobe failed for %s: %s", path, res.stderr)
        return 0.0
    try:
        return float(res.stdout.strip())
    except:
        return 0.0


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


# ---------- image/text layout ----------

def load_font(preferred_paths: List[str], size: int):
    for p in preferred_paths:
        if p and os.path.exists(p):
            try:
                return ImageFont.truetype(p, size=size)
            except Exception:
                continue
    # fallback to a default font (may not support Korean well)
    logging.warning("Preferred fonts not found; using default PIL font.")
    return ImageFont.load_default()


def wrap_text_for_image(text: str, font: ImageFont.FreeTypeFont, max_width: int, draw: ImageDraw.Draw):
    # brute-force wrap using textwrap with attempt to fit
    words = text.split()
    lines = []
    if not words:
        return [""]
    # Try incremental approach
    cur = words[0]
    for w in words[1:]:
        test = cur + " " + w
        wbox = draw.textbbox((0,0), test, font=font)
        if wbox[2] - wbox[0] <= max_width:
            cur = test
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def make_card_image(text: str, outpath: str, width=1080, height=1920,
                    font_path: Optional[str] = None):
    # Background & style config
    bg_color = (18, 18, 18)   # dark background
    text_color = (255, 255, 255)
    accent = (255, 90, 90)
    padding = 80

    img = Image.new("RGB", (width, height), color=bg_color)
    draw = ImageDraw.Draw(img)

    # Load font: try user font path then common fallbacks
    font = load_font([font_path, "assets/NotoSansKR-Bold.ttf", "/usr/share/fonts/truetype/noto/NotoSansKR-Bold.ttf"], size=64)
    # adaptive size: try to fit by shrinking if too wide
    max_text_width = width - padding * 2

    # Prepare wrapped lines with aggressive wrapping for center alignment
    # Use a measuring loop to reduce font size if needed
    size = 64
    while True:
        font = load_font([font_path, "assets/NotoSansKR-Bold.ttf", "/usr/share/fonts/truetype/noto/NotoSansKR-Bold.ttf"], size=size)
        lines = []
        # naive wrap by characters per line estimation
        words = text.split()
        if not words:
            lines = [""]
        else:
            cur = words[0]
            for w in words[1:]:
                test = cur + " " + w
                wbox = draw.textbbox((0, 0), test, font=font)
                if wbox[2]-wbox[0] <= max_text_width:
                    cur = test
                else:
                    lines.append(cur)
                    cur = w
            lines.append(cur)
        # measure total height
        line_h = draw.textbbox((0,0), "가", font=font)[3] - draw.textbbox((0,0), "가", font=font)[1]
        total_h = len(lines) * (line_h + 12)
        if total_h <= height - padding*2 or size <= 28:
            break
        size = int(size * 0.9)

    # Vertical centering
    y0 = (height - total_h) // 2

    # Optional small top accent bar
    bar_h = 8
    draw.rectangle([padding, padding//2, width-padding, padding//2 + bar_h], fill=accent)

    # Draw lines centered
    for i, line in enumerate(lines):
        wbox = draw.textbbox((0,0), line, font=font)
        w = wbox[2] - wbox[0]
        h = wbox[3] - wbox[1]
        x = (width - w) // 2
        y = y0 + i * (h + 12)
        # Drop shadow for readability
        draw.text((x+2, y+2), line, font=font, fill=(0,0,0,200))
        draw.text((x, y), line, font=font, fill=text_color)

    # Small footer CTA area
    # draw channel hint
    footer_font = load_font([font_path], size=36)
    footer_text = "나두 AI 요약"
    fbox = draw.textbbox((0,0), footer_text, font=footer_font)
    fx = width - padding - (fbox[2]-fbox[0])
    fy = height - padding//1.5 - (fbox[3]-fbox[1])
    draw.text((fx, fy), footer_text, font=footer_font, fill=(200,200,200))

    img.save(outpath, quality=95)
    logging.info("Wrote card image: %s", outpath)


# ---------- clip creation ----------

def make_clip_from_image_and_audio(image_path: str, audio_path: str, outpath: str,
                                   target_w=1080, target_h=1920):
    dur = ffprobe_duration(audio_path)
    if dur <= 0.01:
        logging.warning("Audio duration <= 0 for %s, creating 1s silent clip", audio_path)
        # create 1s silent audio
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=22050", "-t", "1.0", audio_path + ".sil.wav"])
        audio_path = audio_path + ".sil.wav"
        dur = 1.0

    fade_d = min(0.18, dur / 4.0)
    # Build ffmpeg filter_complex for video fade and audio afade
    vf = f"scale={target_w}:{target_h},fade=t=in:st=0:d={fade_d},fade=t=out:st={max(0, dur-fade_d)}:d={fade_d}"
    af = f"afade=t=in:st=0:d={min(0.1, fade_d)}," + f"afade=t=out:st={max(0, dur-min(0.1, fade_d))}:d={min(0.1, fade_d)}"

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", image_path,
        "-i", audio_path,
        "-t", f"{dur:.3f}",
        "-filter_complex", f"[0:v]{vf}[v];[1:a]{af}[a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-shortest",
        outpath
    ]
    run(cmd)
    logging.info("Created clip %s (dur %.2fs)", outpath, dur)
    return dur


def concat_clips(clip_paths: List[str], outpath: str):
    concat_file = outpath + ".concat.txt"
    with open(concat_file, "w", encoding="utf-8") as f:
        for p in clip_paths:
            f.write(f"file '{os.path.abspath(p)}'\n")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_file, "-c", "copy", outpath])
    logging.info("Concatenated %d clips into %s", len(clip_paths), outpath)


def make_thumbnail_from_card(card_image_path: str, outpath: str, short_title: Optional[str] = None):
    # Create 1280x720 thumbnail by cropping/letterboxing first card
    im = Image.open(card_image_path).convert("RGB")
    # Resize/crop center to 1280x720
    target = (1280, 720)
    im_ratio = im.width / im.height
    t_ratio = target[0] / target[1]
    if im_ratio > t_ratio:
        # image is wider -> crop width
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
        font = load_font(["assets/NotoSansKR-Bold.ttf", "/usr/share/fonts/truetype/noto/NotoSansKR-Bold.ttf"], size=48)
        tb = draw.textbbox((0,0), short_title, font=font)
        x = 40
        y = 40
        # background rectangle for readability
        draw.rectangle([x-10, y-10, x+tb[2]-tb[0]+20, y+tb[3]-tb[1]+10], fill=(0,0,0,200))
        draw.text((x, y), short_title, font=font, fill=(255,255,255))
    im.save(outpath, quality=90)
    logging.info("Wrote thumbnail: %s", outpath)


# ---------- orchestration ----------

def orchestrate(outdir: str, metadata: Optional[Dict] = None, font_path: Optional[str] = None):
    check_command("ffmpeg")
    check_command("ffprobe")
    ensure_dir(outdir)
    temp_dir = os.path.join(outdir, "tmp")
    ensure_dir(temp_dir)

    # Obtain cards: a list of strings. If metadata provided and has 'cards', use them.
    cards: List[str] = []
    short_title = None
    if metadata:
        short_title = metadata.get("short_title") or metadata.get("title")
        if "cards" in metadata:
            cards = metadata["cards"]
    if not cards:
        if rewrite_for_shorts is None:
            raise RuntimeError("No cards provided and rewrite_for_shorts module not available.")
        # Validate inputs
        hook = (metadata.get("hook") if metadata else "") or ""
        summary_points = (metadata.get("summary_points") if metadata else []) or []
        takeaway = (metadata.get("takeaway") if metadata else "") or ""
        logging.info("Calling rewrite_for_shorts.rewrite_summary_for_shorts()")
        cards_struct = rewrite_for_shorts.rewrite_summary_for_shorts(hook, summary_points, takeaway)
        # Accept both list of strings or list of dicts with 'text'
        if isinstance(cards_struct, list) and cards_struct:
            for c in cards_struct:
                if isinstance(c, dict):
                    cards.append(c.get("text") or c.get("card") or "")
                    if not short_title and c.get("short_title"):
                        short_title = c.get("short_title")
                else:
                    cards.append(str(c))
        else:
            raise RuntimeError("rewrite_for_shorts returned no cards")

    logging.info("Got %d cards", len(cards))

    # create images and audio
    card_image_paths = []
    card_audio_paths = []
    clip_paths = []
    durations = []

    for i, text in enumerate(cards, start=1):
        img_path = os.path.join(temp_dir, f"card_{i:02d}.png")
        make_card_image(text, img_path, font_path=font_path)
        card_image_paths.append(img_path)

        # audio: use elevenlabs_tts.synthesize_to_wav(text, outpath)
        audio_path = os.path.join(temp_dir, f"card_{i:02d}.wav")
        if elevenlabs_tts is None:
            logging.warning("elevenlabs_tts not available. Creating silent audio instead.")
            # create 1s silence as fallback
            run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=22050", "-t", "1.0", audio_path])
        else:
            logging.info("Synthesizing audio for card %d...", i)
            # elevenlabs_tts.synthesize_to_wav should write the wav file; adapt if function name differs
            if hasattr(elevenlabs_tts, "synthesize_to_wav"):
                elevenlabs_tts.synthesize_to_wav(text, audio_path)
            elif hasattr(elevenlabs_tts, "synthesize_and_save"):
                elevenlabs_tts.synthesize_and_save(text, audio_path)
            else:
                raise RuntimeError("elevenlabs_tts module found but no known synth function (synthesize_to_wav expected).")
        card_audio_paths.append(audio_path)

        # clip creation
        clip_path = os.path.join(temp_dir, f"clip_{i:02d}.mp4")
        dur = make_clip_from_image_and_audio(img_path, audio_path, clip_path)
        durations.append(dur)
        clip_paths.append(clip_path)

    # concat clips
    raw_out = os.path.join(outdir, "raw_concat.mp4")
    concat_clips(clip_paths, raw_out)

    # no bgm requested; final = raw_out (we still re-encode to ensure compatibility)
    final_out = os.path.join(outdir, "final.mp4")
    # re-encode container to ensure wide compatibility (copy video/audio)
    run(["ffmpeg", "-y", "-i", raw_out, "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-b:a", "192k", final_out])

    # create thumbnail
    thumb_path = os.path.join(outdir, "thumbnail.jpg")
    make_thumbnail_from_card(card_image_paths[0], thumb_path, short_title)

    # summary metadata
    meta = {
        "cards_count": len(cards),
        "durations": durations,
        "final_path": os.path.abspath(final_out),
        "thumbnail": os.path.abspath(thumb_path),
    }
    meta_path = os.path.join(outdir, "metadata.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    logging.info("Pipeline complete. final video: %s", final_out)
    logging.info("Metadata written to %s", meta_path)
    return meta


# ---------- CLI ----------

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--outdir", "-o", default="out", help="Output directory")
    p.add_argument("--input", "-i", help="Optional metadata JSON with {title, short_title, hook, summary_points, takeaway, cards}")
    p.add_argument("--font", help="Optional font file path (TTF) for Korean text, e.g. assets/NotoSansKR-Bold.ttf")
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
    except Exception as e:
        logging.exception("Pipeline failed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()