"""
rewrite_for_shorts.py — 쇼츠 카드 문구.

프로덕션은 유료 LLM을 호출하지 않는다.
대본은 content_queue 의 사전 작성 대기열에서 고르고,
해당 도구 대본이 없으면 카드 필드만으로 결정적 템플릿을 만든다.

  from rewrite_for_shorts import rewrite_summary_for_shorts, cards_as_list
"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional

CARD_KEYS = ["card1_hook", "card2", "card3", "card4", "card5_takeaway"]

MIN_CHARS = 10
MAX_CHARS = 35  # 카드당 권장 길이(한글)
VALIDATE_MAX_CHARS = MAX_CHARS + 20  # 검증 여유

DISALLOWED_PATTERNS = [r"[#@\u200b]", r"https?://"]

# 입력이 비었을 때도 매일 업로드가 끝나도록 고정해 둔 문장.
EMERGENCY_CARD = "핵심만 짧게 정리해서 보여 드립니다"


class RewriteError(Exception):
    pass


def cards_as_list(data: Dict[str, str]) -> List[str]:
    return [str(data[k]).strip() for k in CARD_KEYS]


def clean_model_text(text: str) -> str:
    """대기열/외부 JSON에서 객체만 추출. 유료 모델 응답용이 아니다."""
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


def sanitize_card_text(s: str) -> str:
    s = normalize_card_text(s)
    s = re.sub(r"https?://\S+", "", s, flags=re.IGNORECASE)
    s = s.replace("#", "").replace("@", "").replace("\u200b", "")
    return normalize_card_text(s)


def validate_card_text(s: str) -> bool:
    if not s:
        return False
    if len(s) < MIN_CHARS or len(s) > VALIDATE_MAX_CHARS:
        return False
    for pattern in DISALLOWED_PATTERNS:
        if re.search(pattern, s):
            return False
    return True


def cards_are_valid(data: object) -> bool:
    if not isinstance(data, dict):
        return False
    if any(key not in data for key in CARD_KEYS):
        return False
    for key in CARD_KEYS:
        if not validate_card_text(normalize_card_text(str(data[key]))):
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
    if not all(key in data for key in CARD_KEYS):
        raise RewriteError(f"응답에 예상 키가 없습니다: {list(data.keys())}")

    out: Dict[str, str] = {}
    for key in CARD_KEYS:
        value = normalize_card_text(str(data[key]))
        if not validate_card_text(value):
            raise RewriteError(f"카드 텍스트가 유효하지 않습니다: {key} -> '{value[:40]}' (len={len(value)})")
        out[key] = value
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


def fit_card_text(text: str, fallback: str) -> str:
    """한 카드를 길이/금지문자 규칙 안으로 넣는다. 실패하면 fallback."""
    fallback_text = sanitize_card_text(fallback)
    if len(fallback_text) > MAX_CHARS:
        fallback_text = sanitize_card_text(_trim_to_len(fallback_text, MAX_CHARS))
    if not validate_card_text(fallback_text):
        fallback_text = EMERGENCY_CARD

    candidate = sanitize_card_text(text)
    if len(candidate) < MIN_CHARS:
        candidate = sanitize_card_text(f"{candidate} {fallback_text}")
    if len(candidate) > MAX_CHARS:
        candidate = sanitize_card_text(_trim_to_len(candidate, MAX_CHARS))
    if not validate_card_text(candidate):
        return fallback_text
    return candidate


def rewrite_summary_for_shorts(
    hook: str,
    summary_points: List[str],
    takeaway: str,
    *,
    title: str = "",
    tool_name: str = "",
    name: str = "",
    one_line: str = "",
    description: str = "",
    features: Optional[List[str]] = None,
    link: str = "",
    youtube_id: str = "",
    tool_id: str = "",
    queue_path: Optional[str] = None,
    consumed_paths: Optional[List[str]] = None,
    force_template: bool = False,
) -> Dict[str, str]:
    """
    도구에 맞는 사전 대본 5장을 반환한다.
    대기열에 없으면 이름/한 줄 설명/핵심 기능/링크 CTA 템플릿을 쓴다.
    """
    from content_queue import resolve_shorts_script

    payload = {
        "hook": hook,
        "summary_points": list(summary_points or []),
        "takeaway": takeaway,
        "title": title,
        "tool_name": tool_name,
        "name": name,
        "one_line": one_line,
        "description": description,
        "key_features": features,
        "link": link,
        "youtube_id": youtube_id,
        "id": tool_id,
    }
    resolved = resolve_shorts_script(
        payload,
        queue_file=queue_path,
        consumed_paths=consumed_paths,
        force_template=force_template,
    )
    return resolved.cards


if __name__ == "__main__":
    sample = rewrite_summary_for_shorts(
        hook="예시 도구로 반복 작업을 줄이는 방법",
        summary_points=[
            "초안은 목적만 적고 먼저 맡기세요",
            "결과 형식은 템플릿으로 고정하세요",
            "마지막 문장은 사람이 확인하세요",
        ],
        takeaway="링크에서 예시 도구를 바로 열어 보세요",
        tool_name="예시도구",
        one_line="예시 도구는 초안과 정리를 대신합니다",
        link="https://example.com/tool",
        force_template=True,
    )
    print(json.dumps(sample, ensure_ascii=False, indent=2))
