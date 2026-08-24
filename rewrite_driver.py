"""
rewrite_driver.py - 간단한 실행 드라이버
- rewrite_for_shorts.rewrite_summary_for_shorts 사용
- elevenlabs_tts.synthesize_to_wav 로 카드별 wav 생성
- out/ 폴더에 결과 저장

실행 예:
  (PowerShell)
  $env:ANTHROPIC_API_KEY = '...'
  $env:ELEVENLABS_API_KEY = '...'
  $env:ELEVEN_VOICE_ID = '...'
  python rewrite_driver.py

주의: 실제 워크플로에서는 이 스크립트를 orchestrator 또는 Actions에서 호출하도록 연결하세요.
"""

import os
import json
from pathlib import Path
from rewrite_for_shorts import rewrite_summary_for_shorts
from elevenlabs_tts import synthesize_to_wav

OUT_DIR = Path("out")
OUT_DIR.mkdir(parents=True, exist_ok=True)

SAMPLE_INPUT = {
    "hook": "캔바로 3분 만에 유튜브 썸네일 만드는 법",
    "summary_points": [
        "템플릿에서 원하는 스타일 검색해서 선택하기",
        "텍스트와 이미지를 드래그해서 배치하기",
        "브랜드 색상을 저장해두면 다음에 재사용 가능",
    ],
    "takeaway": "디자인 몰라도 템플릿만 잘 고르면 누구나 만들 수 있다",
}


def main():
    print("[driver] 리라이팅 요청 중...")
    cards = rewrite_summary_for_shorts(
        SAMPLE_INPUT['hook'], SAMPLE_INPUT['summary_points'], SAMPLE_INPUT['takeaway']
    )
    print('[driver] 리라이팅 결과:')
    print(json.dumps(cards, ensure_ascii=False, indent=2))

    # 각 카드 텍스트를 합쳐서 TTS 생성(또는 카드별 파일 생성)
    # 파일 이름은 card1.wav ... card5.wav
    voice_id = os.environ.get('ELEVEN_VOICE_ID')
    if not voice_id:
        raise RuntimeError('ELEVEN_VOICE_ID가 설정되어 있지 않습니다. GitHub Secrets에 추가하세요.')

    api_key = os.environ.get('ELEVENLABS_API_KEY')
    if not api_key:
        raise RuntimeError('ELEVENLABS_API_KEY가 설정되어 있지 않습니다.')

    for k, text in cards.items():
        safe_name = k.replace(' ', '_')
        out_path = OUT_DIR / f"{safe_name}.wav"
        print(f"[driver] TTS 생성: {k} -> {out_path}")
        ok = synthesize_to_wav(text, voice_id=voice_id, out_path=str(out_path), api_key=api_key)
        if not ok:
            print(f"[driver] ElevenLabs TTS 실패: {k}")
        else:
            print(f"[driver] 생성 완료: {out_path}")

    print('[driver] 완료. out/ 폴더를 확인하세요.')


if __name__ == '__main__':
    main()
