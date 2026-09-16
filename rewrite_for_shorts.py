"""
rewrite_for_shorts.py — 쇼츠 카드뉴스용 리라이팅 (OpenAI)

사용법:
  from rewrite_for_shorts import rewrite_summary_for_shorts, cards_as_list
  cards = rewrite_summary_for_shorts(hook, summary_points, takeaway)

환경변수:
  OPENAI_API_KEY   (필수 — 키가 없고 입력 카드도 쓸 수 없으면 실패)
  OPENAI_MODEL     (선택, 기본 gpt-4.1-mini)
  REWRITE_MODEL    (선택, OPENAI_MODEL보다 우선. claude-* 값은 무시)

폴백: OpenAI 호출이 실패한 뒤에만, 그리고 원본 hook/summary_points/takeaway가
이미 카드로 쓸 수 있을 때만 규칙 기반 축약을 사용한다.
하드코딩된 Canva 샘플을 프로덕션에서 쓰지 않는다.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Dict, List, Optional

CARD_KEYS = ["card1_hook", "card2", "card3", "card4", "card5_takeaway"]

DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0
MIN_CHARS = 10
MAX_CHARS = 35  # 카드당 권장 길이(한글)
VALIDATE_MAX_CHARS = MAX_CHARS + 20  # 검증 여유

DISALLOWED_PATTERNS = [r"[#@\u200b]", r"https?://"]

PROMPT_TEMPLATE = r"""
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
"""


class RewriteError(Exception):
    pass


def resolve_rewrite_model(explicit: Optional[str] = None) -> str:
    if explicit:
        return explicit
    raw = (os.environ.get("REWRITE_MODEL") or os.environ.get("OPENAI_MODEL") or "").strip()
    if not raw or raw.lower().startswith("claude"):
        return DEFAULT_OPENAI_MODEL
    return raw


def cards_as_list(data: Dict[str, str]) -> List[str]:
    return [str(data[k]).strip() for k in CARD_KEYS]


def clean_model_text(text: str) -> str:
    """모델 반환에서 JSON 객체만 추출."""
    if not text:
        return ""

    text = re.sub(r"^```json\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"```\s*$", "", text)

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1].strip()

    match = re.search(r"(\{.*\})", text, flags=re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def normalize_card_text(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s


def validate_card_text(s: str) -> bool:
    if not s:
        return False
    if len(s) < MIN_CHARS or len(s) > VALIDATE_MAX_CHARS:
        return False
    for p in DISALLOWED_PATTERNS:
        if re.search(p, s):
            return False
    return True


def parse_cards_json(raw_text: str) -> Dict[str, str]:
    cleaned = clean_model_text(raw_text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RewriteError(f"카드 JSON 파싱 실패: {exc}") from exc

    if not isinstance(data, dict):
        raise RewriteError("카드 JSON이 객체가 아닙니다.")
    if not all(k in data for k in CARD_KEYS):
        raise RewriteError(f"모델 응답에 예상 키가 없습니다: {list(data.keys())}")

    out: Dict[str, str] = {}
    for k in CARD_KEYS:
        v = normalize_card_text(str(data[k]))
        if not validate_card_text(v):
            raise RewriteError(f"카드 텍스트가 유효하지 않습니다: {k} -> '{v[:40]}' (len={len(v)})")
        out[k] = v
    return out


def _trim_to_len(s: str, max_len: int) -> str:
    s = normalize_card_text(s)
    s = re.sub(r"[。.!?]+$", "", s)
    if len(s) <= max_len:
        return s
    cut = s[:max_len].rfind(" ")
    if cut > max_len // 2:
        s = s[:cut]
    else:
        s = s[:max_len]
    return s.rstrip(" ,;:") + "…"


def simple_rewrite_fallback(hook: str, summary_points: List[str], takeaway: str) -> Dict[str, str]:
    """원본을 길이만 맞춰 카드화. 샘플 문구를 넣지 않는다."""
    if len(summary_points) < 3:
        raise RewriteError("summary_points는 최소 3개 필요합니다.")
    return {
        "card1_hook": _trim_to_len(hook, 30),
        "card2": _trim_to_len(summary_points[0], 28),
        "card3": _trim_to_len(summary_points[1], 28),
        "card4": _trim_to_len(summary_points[2], 28),
        "card5_takeaway": _trim_to_len(takeaway, 34),
    }


def source_has_usable_cards(hook: str, summary_points: List[str], takeaway: str) -> bool:
    try:
        cards = simple_rewrite_fallback(hook, summary_points, takeaway)
        return all(validate_card_text(cards[k]) for k in CARD_KEYS)
    except Exception:
        return False


def _openai_complete(prompt: str, model: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RewriteError("OPENAI_API_KEY가 설정되어 있지 않습니다.")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RewriteError("openai 패키지가 필요합니다. pip install openai") from exc

    client = OpenAI(api_key=api_key)
    kwargs = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 800,
        "temperature": 0.6,
    }
    try:
        resp = client.chat.completions.create(response_format={"type": "json_object"}, **kwargs)
    except Exception:
        resp = client.chat.completions.create(**kwargs)

    content = resp.choices[0].message.content if resp.choices else ""
    if not content:
        raise RewriteError("OpenAI 응답이 비어 있습니다.")
    return content


def rewrite_summary_for_shorts(
    hook: str,
    summary_points: List[str],
    takeaway: str,
    model: Optional[str] = None,
    max_retries: int = MAX_RETRIES,
) -> Dict[str, str]:
    """
    OpenAI로 5장 카드를 만든다.
    OpenAI가 실패하고 원본이 이미 카드로 쓸 수 있으면 축약 폴백만 사용한다.
    """
    points = [str(p).strip() for p in (summary_points or []) if str(p).strip()]
    if len(points) < 3:
        raise RewriteError("summary_points는 최소 3개 필요합니다.")

    prompt = PROMPT_TEMPLATE.format(
        min_chars=MIN_CHARS,
        max_chars=MAX_CHARS,
        hook=hook,
        p1=points[0],
        p2=points[1],
        p3=points[2],
        takeaway=takeaway,
    )
    chosen = resolve_rewrite_model(model)
    last_exc: Optional[Exception] = None

    if not os.environ.get("OPENAI_API_KEY"):
        last_exc = RewriteError("OPENAI_API_KEY가 설정되어 있지 않습니다.")
        if source_has_usable_cards(hook, points, takeaway):
            print(f"[rewrite] OpenAI 키 없음, 원본 카드 폴백 사용")
            return simple_rewrite_fallback(hook, points, takeaway)
        raise last_exc

    for attempt in range(1, max_retries + 1):
        try:
            raw = _openai_complete(prompt, chosen)
            return parse_cards_json(raw)
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                time.sleep(RETRY_BACKOFF**attempt)

    if source_has_usable_cards(hook, points, takeaway):
        print(f"[rewrite] OpenAI 실패, 원본 카드 폴백 사용 (last_exc={last_exc})")
        return simple_rewrite_fallback(hook, points, takeaway)

    raise RewriteError(
        "OpenAI 리라이팅에 실패했고 원본 hook/summary_points/takeaway도 "
        f"카드로 쓸 수 없습니다: {last_exc}"
    )


if __name__ == "__main__":
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
