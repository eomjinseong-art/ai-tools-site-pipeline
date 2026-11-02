"""
LOCAL DEBUG ONLY — not the GitHub Actions entrypoint.

Production daily job:
  python promo_pipeline.py

This driver only resolves a script + TTS. It does not render final.mp4 or upload.
SAMPLE_INPUT is a leftover example and is NOT the production path.
Prefer:
  python rewrite_driver.py --input source.json

TTS uses edge-tts (ko-KR-SunHiNeural) and falls back to gTTS. No API key.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rewrite_for_shorts import rewrite_summary_for_shorts
from tts import TtsError, synthesize_speech

# Deprecated leftover. Do not use this as the Actions source of truth.
SAMPLE_INPUT = {
    "hook": "캔바로 3분 만에 유튜브 썸네일 만드는 법",
    "summary_points": [
        "템플릿에서 원하는 스타일 검색해서 선택하기",
        "텍스트와 이미지를 드래그해서 배치하기",
        "브랜드 색상을 저장해두면 다음에 재사용 가능",
    ],
    "takeaway": "디자인 몰라도 템플릿만 잘 고르면 누구나 만들 수 있다",
    "tool_name": "Canva",
    "link": "https://www.canva.com",
}


def parse_args():
    p = argparse.ArgumentParser(description="Local script+TTS debug driver (not production)")
    p.add_argument("--input", "-i", help="JSON with hook/summary_points/takeaway")
    p.add_argument("--outdir", "-o", default="out")
    p.add_argument("--skip-tts", action="store_true", help="Write cards only")
    return p.parse_args()


def main():
    args = parse_args()
    out_dir = Path(args.outdir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.input:
        payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    else:
        print(
            "[driver] WARNING: SAMPLE_INPUT 을 사용합니다. "
            "프로덕션은 promo_pipeline.py + collector DB를 쓰세요. "
            "로컬 디버그라면 --input JSON을 넘기세요."
        )
        payload = SAMPLE_INPUT

    print("[driver] 대본 선택 중 (대기열 또는 템플릿)...")
    cards = rewrite_summary_for_shorts(
        payload.get("hook") or "",
        payload.get("summary_points") or [],
        payload.get("takeaway") or "",
        title=payload.get("title") or "",
        tool_name=payload.get("tool_name") or payload.get("name") or "",
        one_line=payload.get("one_line") or payload.get("description") or "",
        features=payload.get("key_features") or payload.get("features"),
        link=payload.get("link") or payload.get("url") or "",
        youtube_id=payload.get("youtube_id") or "",
        tool_id=str(payload.get("id") or ""),
    )
    print("[driver] 대본:")
    print(json.dumps(cards, ensure_ascii=False, indent=2))
    (out_dir / "cards.json").write_text(json.dumps(cards, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.skip_tts:
        print("[driver] TTS skipped (--skip-tts).")
        return

    for key, text in cards.items():
        out_path = out_dir / f"{key}.mp3"
        print(f"[driver] TTS 생성: {key} -> {out_path}")
        try:
            engine = synthesize_speech(text, str(out_path))
        except TtsError as exc:
            raise SystemExit(f"[driver] TTS 실패: {key}: {exc}") from exc
        print(f"[driver] 생성 완료 ({engine}): {out_path}")

    print("[driver] 완료. 렌더/업로드는 promo_pipeline.py를 사용하세요.")


if __name__ == "__main__":
    main()
