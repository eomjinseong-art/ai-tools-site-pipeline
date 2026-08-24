"""
elevenlabs_tts.py - 간단한 ElevenLabs TTS 래퍼 (WAV 저장)
사용법:
  from elevenlabs_tts import synthesize_to_wav
  wav_path = synthesize_to_wav(text, voice_id=os.environ['ELEVEN_VOICE_ID'])

필요한 환경변수:
  ELEVENLABS_API_KEY (또는 전달 인자)
"""

import os
import requests

ELEVEN_API_URL_TEMPLATE = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"


def synthesize_to_wav(text: str, voice_id: str, out_path: str, api_key: str = None) -> bool:
    """ElevenLabs에 텍스트를 보내고 WAV를 파일로 저장.
    - 반환: 성공 여부(True/False)
    - 주의: ElevenLabs 요금/정책을 확인하세요.
    """
    api_key = api_key or os.environ.get('ELEVENLABS_API_KEY')
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY 환경변수가 없습니다.")
    if not voice_id:
        raise RuntimeError("voice_id가 필요합니다.")

    url = ELEVEN_API_URL_TEMPLATE.format(voice_id=voice_id)
    headers = {
        'Accept': 'audio/wav',
        'Content-Type': 'application/json',
        'xi-api-key': api_key,
    }
    body = {
        "text": text,
        # 추가 옵션 예: "voice_settings": {"stability":0.5, "similarity_boost":0.75}
    }

    resp = requests.post(url, headers=headers, json=body, stream=True, timeout=60)
    if resp.status_code not in (200, 201):
        print(f"ElevenLabs TTS 실패: {resp.status_code} {resp.text[:300]}")
        return False

    # 응답 바이트를 파일로 저장
    with open(out_path, 'wb') as f:
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
    return True


if __name__ == '__main__':
    # 간단한 로컬 테스트
    txt = "안녕하세요. 테스트 음성입니다."
    vid = os.environ.get('ELEVEN_VOICE_ID', '')
    ok = synthesize_to_wav(txt, voice_id=vid, out_path='test_eleven.wav')
    print('ok=', ok)
