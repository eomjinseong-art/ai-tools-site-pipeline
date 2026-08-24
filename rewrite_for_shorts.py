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

    # 가장 바깥 중괄호 블록 추출(가장 첫 '{' 와 마지막 '}' 사용)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start:end+1].strip()

    # fallback: 기존 방식(가장 첫 매칭)
    match = re.search(r"(\{.*\})", text, flags=re.DOTALL)
    if match:
        return match.group(1).strip()

    # 그냥 전체 반환 (fallback)
    return text.strip()


def _validate_card_text(s: str) -> bool:
    if not s:
        return False
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


def _simple_rewrite_fallback(hook: str, summary_points: List[str], takeaway: str) -> Dict[str, str]:
    """
    Anthropic 호출이 불가능할 때 사용하는 간단한 규칙 기반 폴백 리라이팅.
    - 길이 제한 적용(권장 15~30자 범위로 트리밍)
    - 최소한의 표현 변경(불필요 공백 제거, 문장 끝 마침표 제거, 일부 트리밍)
    """
    def normalize(s: str, max_len: int = 28) -> str:
        s = s.strip()
        s = re.sub(r"\s+", " ", s)
        # 문장 끝의 마침표/물음표/느낌표 제거
        s = re.sub(r"[。.!?]+$", "", s)
        if len(s) > max_len:
            # 자연스러운 잘림을 위해 마지막 공백 기준으로 자름
            cut = s[:max_len].rfind(" ")
            if cut > max_len // 2:
                s = s[:cut]
            else:
                s = s[:max_len]
            s = s.rstrip(" ,;:")
            s += "…"
        return s

    card1 = normalize(hook, max_len=30)
    card2 = normalize(summary_points[0], max_len=28)
    card3 = normalize(summary_points[1], max_len=28)
    card4 = normalize(summary_points[2], max_len=28)
    card5 = normalize(takeaway, max_len=34)

    return {
        "card1_hook": card1,
        "card2": card2,
        "card3": card3,
        "card4": card4,
        "card5_takeaway": card5,
    }


def rewrite_summary_for_shorts(hook: str, summary_points: List[str], takeaway: str,
                               model: Optional[str] = None,
                               max_retries: int = MAX_RETRIES) -> Dict[str, str]:
    """
    Anthropic 호출을 시도하되, 결제/서비스 오류 등으로 실패하면 간단한 폴백을 사용.
    """
    if anthropic is None:
        # SDK가 없으면 폴백
        return _simple_rewrite_fallback(hook, summary_points, takeaway)

    if not ANTHROPIC_API_KEY:
        # 키가 없으면 폴백
        return _simple_rewrite_fallback(hook, summary_points, takeaway)

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
            # Anthropic SDK 호환성 고려: 불필요 파라미터 제거
            resp = client.messages.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
            )

            raw = getattr(resp, "content", None)
            if raw and isinstance(raw, list) and len(raw) > 0:
                raw_text = raw[0].text
            else:
                raw_text = str(resp)

            cleaned = _clean_model_text(raw_text)

            # JSON 로드 (안전한 방식)
            try:
                data = json.loads(cleaned)
            except Exception:
                start = raw_text.find("{")
                end = raw_text.rfind("}")
                if start != -1 and end != -1 and end > start:
                    data = json.loads(raw_text[start:end+1])
                else:
                    raise

            # 필수 키 검증
            expected_keys = ["card1_hook", "card2", "card3", "card4", "card5_takeaway"]
            if not all(k in data for k in expected_keys):
                raise RewriteError(f"모델 응답에 예상 키가 없습니다: {list(data.keys())}")

            # 각 카드 검증 및 길이 조정/후처리
            for k in expected_keys:
                v = data[k].strip()
                v = re.sub(r"\s+", " ", v)
                data[k] = v
                if not _validate_card_text(v):
                    raise RewriteError(f"카드 텍스트가 유효하지 않습니다: {k} -> '{v[:40]}' (len={len(v)})")

            return data

        except Exception as e:
            last_exc = e
            msg = str(e).lower()
            # 잔액/결제 관련 에러면 즉시 폴백 사용
            if "credit" in msg or "balance" in msg or "payment" in msg or "insufficient" in msg:
                print("[rewrite] Anthropic 호출 실패(잔액/결제): 폴백 리라이팅 사용")
                return _simple_rewrite_fallback(hook, summary_points, takeaway)

            # 일시적 네트워크/SDK 오류는 재시도
            wait = RETRY_BACKOFF ** attempt
            time.sleep(wait)
            continue

    # 모든 재시도 실패하면 폴백을 사용
    print("[rewrite] 모든 재시도 실패: 폴백 리라이팅 사용 (last_exc=", last_exc, ")")
    return _simple_rewrite_fallback(hook, summary_points, takeaway)


if __name__ == "__main__":
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
