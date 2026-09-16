"""
LOCAL DEBUG ONLY — not the GitHub Actions entrypoint.

Production daily job:
  python promo_pipeline.py

This driver only rewrites + TTS. It does not render final.mp4 or upload.
SAMPLE_INPUT is a leftover Canva example and is NOT the production path.
Prefer:
  python rewrite_driver.py --input source.json
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from elevenlabs_tts import synthesize_to_wav
from rewrite_for_shorts import rewrite_summary_for_shorts

# Deprecated leftover. Do not use this as the Actions source of truth.
SAMPLE_INPUT = {
    "hook": "캔바로 3분 만에 유튜브 썸네일 만드는 법",
    "summary_points": [
        "템플릿에서 원하는 스타일 검색해서 선택하기",
        "텍스트와 이미지를 드래그해서 배치하기",
        "브랜드 색상을 저장해두면 다음에 재사용 가능",
    ],
    "takeaway": "디자인 몰라도 템플릿만 잘 고르면 누구나 만들 수 있다",
}


def parse_args():
    p = argparse.ArgumentParser(description="Local rewrite+TTS debug driver (not production)")
    p.add_argument("--input", "-i", help="JSON with hook/summary_points/takeaway")
    p.add_argument("--outdir", "-o", default="out")
    return p.parse_args()


def main():
    args = parse_args()
    out_dir = Path(args.outdir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.input:
        payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    else:
        print(
            "[driver] WARNING: SAMPLE_INPUT(Canva 예제)를 사용합니다. "
            "프로덕션은 promo_pipeline.py + collector DB를 쓰세요. "
            "로컬 디버그라면 --input JSON을 넘기세요."
        )
        payload = SAMPLE_INPUT

    print("[driver] 리라이팅 요청 중...")
    cards = rewrite_summary_for_shorts(payload["hook"], payload["summary_points"], payload["takeaway"])
    print("[driver] 리라이팅 결과:")
    print(json.dumps(cards, ensure_ascii=False, indent=2))
    (out_dir / "cards.json").write_text(json.dumps(cards, ensure_ascii=False, indent=2), encoding="utf-8")

    voice_id = os.environ.get("ELEVEN_VOICE_ID")
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not voice_id or not api_key:
        print("[driver] TTS skipped (ELEVENLABS_API_KEY / ELEVEN_VOICE_ID missing).")
        return

    for key, text in cards.items():
        out_path = out_dir / f"{key}.wav"
        print(f"[driver] TTS 생성: {key} -> {out_path}")
        if not synthesize_to_wav(text, voice_id=voice_id, out_path=str(out_path), api_key=api_key):
            raise SystemExit(f"[driver] ElevenLabs TTS 실패: {key}")
        print(f"[driver] 생성 완료: {out_path}")

    print("[driver] 완료. 렌더/업로드는 promo_pipeline.py를 사용하세요.")


if __name__ == "__main__":
    main()
