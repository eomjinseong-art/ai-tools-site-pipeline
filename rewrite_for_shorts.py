"""
rewrite_for_shorts.py  - 안전한 Lv.1 리라이팅 모듈 (개선판)
- Anthropics(claude) 기반으로 단순 리라이팅 수행
- 재시도/타임아웃/JSON 파싱 보강, 길이 검증 포함

사용법 예시:
  from rewrite_for_shorts import rewrite_summary_for_shorts
  cards = rewrite_summary_for_shorts(hook, summary_points, takeaway)

필요한 환경변수:
  ANTHROPIC_API_KEY

주의: 이 파일은 "리라이팅"만 담당합니다. 카드 렌더/tts/비디오 합성은 별도 파이프라인에서 처리하세요.
"""

import os
import time
import re
import json
from typing import List, Dict, Optional

# Anthropics는 사용 환경에 맞게 설치/불러오기
# pip install anthropic
try:
    import anthropic
except Exception:
    anthropic = None

REWRITE_MODEL = os.environ.get("REWRITE_MODEL", "claude-haiku-4-5-20251001")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

# 동작 파라미터
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0  # 지수 백오프 계수
MIN_CHARS = 10
MAX_CHARS = 35  # 카드당 최대 권장 길이(한글 기준 권장값)

# 금지 문자/패턴 (간단 검증)
DISALLOWED_PATTERNS = [r"[#@\u200b]", r"https?://"]  # 해시태그/링크/제로폭문자 등

PROMPT_TEMPLATE = r'''
다음은 유튜브 영상 하나를 AI가 요약한 내용입니다.
의미와 핵심 정보는 그대로 유지하되, 원문과 문장 구조·단어 선택이
겹치지 않도록 표현을 완전히 바꿔서 쇼츠 카드뉴스용 문구로 재작성해주세요.

[제약]
- 원문 문장을 그대로 가져오지 말 것 (단어 순서만 바꾸는 것도 금지)
- 각 카드는 한 화면에 들어갈 분량으로 짧게 (권장 {min_chars}~{max_chars}자)
- 정보 전달형 존댓말 톤 유지
- 총 5장 구성: 훅(1장) → 핵심 포인트 3개(3장) → 마무리 요약(1장)
- 이모지, 해시태그, URL, 불필요한 구두점 넣지 말 것

아래 JSON 형식으로만 응답하세요. 다른 설명 없이 JSON만 출력합니다.
{{"card1_hook": "...", "card2": "...", "card3": "...", "card4": "...", "card5_takeaway": "..."}}

[원본 hook]
{hook}

[원본 summary_points 상위 3개]
1. {p1}
2. {p2}
3. {p3}

[원본 takeaway]
{takeaway}
'''


def _clean_model_text(text: str) -> str:
    """모델 반환에서 JSON 블록만 안전하게 추출하려고 시도.
    - 코드블록 ```json ``` 제거
    - 가장 큰 중괄호 블록을 찾아 반환
    """
    if not text:
        return ""

    # 제거: ```json ... ``` 및 ``` ... ```
    text = re.sub(r"^```json\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"```\s*$", "", text)

    # 가장 바깥 중괄호 블록 추출
    match = re.search(r"(\{.*\})", text, flags=re.DOTALL)
    if match:
        return match.group(1).strip()

    # 그냥 전체 반환 (fallback)
    return text.strip()


def _validate_card_text(s: str) -> bool:
    if not s: return False
    # 길이(문자기준)
    l = len(s)
    if l < MIN_CHARS or l > (MAX_CHARS + 20):  # 여유 허용
        return False
    # 금지 패턴 존재 검사
    for p in DISALLOWED_PATTERNS:
        if re.search(p, s):
            return False
    return True


class RewriteError(Exception):
    pass


def rewrite_summary_for_shorts(hook: str, summary_points: List[str], takeaway: str,
                               model: Optional[str] = None,
                               max_retries: int = MAX_RETRIES) -> Dict[str, str]:
    """리라이팅 요청을 보내고 JSON 결과(5장 카드)를 돌려줌.
    - 실패시 RewriteError 발생
    - 반환값은 card1...card5_takeaway 키를 포함해야 함
    """
    if anthropic is None:
        raise RewriteError("anthropic SDK가 설치되어 있지 않습니다. `pip install anthropic` 해주세요.`")

    if not ANTHROPIC_API_KEY:
        raise RewriteError("환경변수 ANTHROPIC_API_KEY가 설정되어 있지 않습니다.")

    if len(summary_points) < 3:
        raise RewriteError("summary_points는 최소 3개 필요합니다.")

    model = model or REWRITE_MODEL

    prompt = PROMPT_TEMPLATE.format(
        min_chars=MIN_CHARS,
        max_chars=MAX_CHARS,
        hook=hook,
        p1=summary_points[0],
        p2=summary_points[1],
        p3=summary_points[2],
        takeaway=takeaway,
    )

    client = anthropic.Client(api_key=ANTHROPIC_API_KEY)

    attempt = 0
    last_exc = None
    while attempt < max_retries:
        try:
            attempt += 1
            # Note: some anthropic SDK versions don't accept 'temperature' in messages.create()
            # Keep the request minimal to maximize compatibility.
            resp = client.messages.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
            )

            raw = getattr(resp, 'content', None)
            if raw and isinstance(raw, list) and len(raw) > 0:
                raw_text = raw[0].text
            else:
                raw_text = str(resp)

            cleaned = _clean_model_text(raw_text)

            # JSON 로드
            try:
                data = json.loads(cleaned)
            except Exception:
                # 마지막 중괄호 블록 재시도: 이미 cleaned에서 실패했다면 regex로 더 강하게 추출
                m = re.search(r"(\{(?:[^{}]|(?R))*\})", raw_text, flags=re.DOTALL)
                if m:
                    try:
                        data = json.loads(m.group(1))
                    except Exception:
                        raise
                else:
                    raise

            # 필수 키 검증
            expected_keys = ["card1_hook", "card2", "card3", "card4", "card5_takeaway"]
            if not all(k in data for k in expected_keys):
                raise RewriteError(f"모델 응답에 예상 키가 없습니다: {list(data.keys())}")

            # 각 카드 검증 및 길이 조정/후처리
            for k in expected_keys:
                v = data[k].strip()
                # 줄바꿈 제거
                v = re.sub(r"\s+", " ", v)
                data[k] = v
                if not _validate_card_text(v):
                    raise RewriteError(f"카드 텍스트가 유효하지 않습니다: {k} -> '{v[:40]}' (len={len(v)})")

            return data

        except RewriteError:
            # 검증 오류는 재시도할 필요 없음
            raise
        except Exception as e:
            last_exc = e
            wait = RETRY_BACKOFF ** attempt
            time.sleep(wait)
            continue

    raise RewriteError(f"리라이팅 실패: 마지막 예외: {last_exc}")


if __name__ == '__main__':
    # 간단 로컬 테스트
    sample = rewrite_summary_for_shorts(
        hook="캔바로 3분 만에 유튜브 썸네일 만드는 법",
        summary_points=[
            "템플릿에서 원하는 스타일 검색해서 선택하기",
            "텍스트와 이미지를 드래그해서 배치하기",
            "브랜드 색상을 저장해두면 다음에 재사용 가능",
        ],
        takeaway="디자인 몰라도 템플릿만 잘 고르면 누구나 만들 수 있다",
    )
    print(json.dumps(sample, ensure_ascii=False, indent=2))
