"""
사전 작성 쇼츠 대본 대기열.

  content_queue/shorts_scripts.json   대본 (주 1회 보조자가 채움)
  content_queue/consumed_ids.json     이미 사용한 id
  out/content_queue_state.json        런타임 소비 상태 (캐시 백업)

하루 1편이면 days_left = 아직 쓰지 않은 유효 대본 수.
도구에 맞는 대본이 없으면 템플릿으로 만들고, 그 경우 id 를 소비하지 않는다.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from rewrite_for_shorts import (
    CARD_KEYS,
    EMERGENCY_CARD,
    cards_are_valid,
    fit_card_text,
    normalize_card_text,
)

logger = logging.getLogger(__name__)

LOW_WATER_DAYS = 14
DEFAULT_CADENCE_PER_DAY = 1
QUEUE_PATH = Path("content_queue/shorts_scripts.json")
CONSUMED_PATH = Path("content_queue/consumed_ids.json")
RUNTIME_STATE_NAME = "content_queue_state.json"

GENERIC_NAME = "이 AI 툴"
HOOK_FALLBACK = "이 AI 툴 핵심만 먼저 보세요"
ONE_LINE_FALLBACK = "한 줄 설명을 카드로 옮겼습니다"
FEATURE_FALLBACK = "대표 기능을 짧게 정리했습니다"
FEATURE_TWO_FALLBACK = "결과는 직접 한 번 확인하세요"
CTA_FALLBACK = "설명란 링크에서 바로 확인하세요"

_GENERIC_KEYS = {"ai", "툴", "도구", "앱"}


class ContentQueueError(Exception):
    pass


@dataclass
class ToolCard:
    name: str
    one_line: str
    features: List[str]
    link: str
    tool_id: str = ""
    title: str = ""
    hook: str = ""

    def match_blob(self) -> str:
        parts = [self.name, self.title, self.hook, self.one_line, self.tool_id, self.link]
        return " ".join(part for part in parts if part).casefold()


@dataclass
class ResolvedScript:
    cards: Dict[str, str]
    source: str
    script_id: Optional[str]
    link: str
    tool_name: str

    def to_meta(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "script_id": self.script_id,
            "link": self.link,
            "tool_name": self.tool_name,
            "cards": {key: self.cards[key] for key in CARD_KEYS},
        }


def queue_path(explicit: Optional[os.PathLike[str] | str] = None) -> Path:
    if explicit:
        return Path(explicit)
    override = (os.environ.get("CONTENT_QUEUE_PATH") or "").strip()
    return Path(override) if override else QUEUE_PATH


def committed_consumed_path(explicit: Optional[os.PathLike[str] | str] = None) -> Path:
    if explicit:
        return Path(explicit)
    override = (os.environ.get("CONTENT_QUEUE_CONSUMED_PATH") or "").strip()
    return Path(override) if override else CONSUMED_PATH


def runtime_state_path(outdir: Optional[os.PathLike[str] | str]) -> Optional[Path]:
    if not outdir:
        return None
    return Path(outdir) / RUNTIME_STATE_NAME


def consumed_state_paths(
    outdir: Optional[os.PathLike[str] | str] = None,
    extra: Optional[Sequence[os.PathLike[str] | str]] = None,
) -> List[Path]:
    paths: List[Path] = [committed_consumed_path()]
    runtime = runtime_state_path(outdir)
    if runtime is not None:
        paths.append(runtime)
    for item in extra or []:
        paths.append(Path(item))
    unique: List[Path] = []
    seen = set()
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_consumed_ids(paths: Iterable[Path]) -> List[str]:
    found = []
    seen = set()
    for path in paths:
        if not path.exists():
            continue
        try:
            data = _read_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("consumed state unreadable %s: %s", path, exc)
            continue
        raw = []
        if isinstance(data, dict):
            raw = data.get("consumed_ids") or data.get("consumed") or []
        elif isinstance(data, list):
            raw = data
        if not isinstance(raw, list):
            logger.warning("consumed state is not a list: %s", path)
            continue
        for item in raw:
            script_id = str(item).strip()
            if not script_id or script_id in seen:
                continue
            seen.add(script_id)
            found.append(script_id)
    return found


def write_consumed_ids(path: Path, script_ids: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"consumed_ids": sorted({str(item).strip() for item in script_ids if str(item).strip()})}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def mark_script_consumed(script_id: str, paths: Sequence[Path]) -> List[str]:
    script_id = (script_id or "").strip()
    if not script_id:
        raise ContentQueueError("소비할 script id 가 비어 있습니다.")
    current = load_consumed_ids(paths)
    if script_id not in current:
        current.append(script_id)
    for path in paths:
        write_consumed_ids(path, current)
    return current


def _as_str_list(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("[") and text.endswith("]"):
            try:
                raw = json.loads(text)
            except json.JSONDecodeError:
                raw = [line.strip() for line in text.splitlines() if line.strip()]
        else:
            raw = [line.strip(" •-\t") for line in text.splitlines() if line.strip()]
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def tool_card_from_mapping(data: Optional[Dict[str, Any]]) -> ToolCard:
    payload = data or {}
    features = _as_str_list(
        payload.get("key_features")
        if payload.get("key_features") is not None
        else payload.get("features")
        if payload.get("features") is not None
        else payload.get("summary_points")
    )
    link = _first_text(payload.get("link"), payload.get("url"), payload.get("cta_url"), payload.get("cta"))
    youtube_id = _first_text(payload.get("youtube_id"))
    if not link and youtube_id:
        link = f"https://www.youtube.com/watch?v={youtube_id}"
    name = _first_text(payload.get("tool_name"), payload.get("name"), payload.get("title"), payload.get("hook"))
    one_line = _first_text(
        payload.get("one_line"),
        payload.get("description"),
        payload.get("hook"),
        payload.get("takeaway"),
    )
    return ToolCard(
        name=name,
        one_line=one_line,
        features=features,
        link=link,
        tool_id=_first_text(payload.get("tool_id"), payload.get("id")),
        title=_first_text(payload.get("title")),
        hook=_first_text(payload.get("hook")),
    )


def _host(link: str) -> str:
    raw = (link or "").strip()
    raw = re.sub(r"^https?://", "", raw, flags=re.IGNORECASE)
    raw = raw.split("/")[0].split("?")[0].split("#")[0]
    if raw.lower().startswith("www."):
        raw = raw[4:]
    if not raw or " " in raw or len(raw) > 40:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}", raw):
        return ""
    return raw


def _clean_name(name: str) -> str:
    text = normalize_card_text(name)
    text = re.sub(r"https?://\S+", "", text, flags=re.IGNORECASE)
    text = text.replace("#", "").replace("@", "").replace("\u200b", "")
    return normalize_card_text(text)


def link_cta(name: str, link: str) -> str:
    shown = _clean_name(name) or GENERIC_NAME
    host = _host(link)
    if host:
        return f"{host} 링크에서 {shown} 열기"
    return f"설명란 링크에서 {shown} 확인하세요"


def template_cards(card: ToolCard) -> Dict[str, str]:
    """
    이름, 한 줄 설명, 핵심 기능 2개, 링크 CTA 로 5장을 만든다.
    같은 입력이면 항상 같은 문장이다. 네트워크를 쓰지 않는다.
    """
    name = _clean_name(card.name) or GENERIC_NAME
    features = [_clean_name(item) for item in card.features if _clean_name(item)]
    first = features[0] if features else f"{name}의 대표 기능을 확인해 보세요"
    second = features[1] if len(features) > 1 else f"{name} 결과는 직접 한 번 확인하세요"
    cards = {
        "card1_hook": fit_card_text(f"{name} 한 줄로 시작하기", HOOK_FALLBACK),
        "card2": fit_card_text(card.one_line, ONE_LINE_FALLBACK if name == GENERIC_NAME else f"{name} 사용법을 짧게 정리합니다"),
        "card3": fit_card_text(first, FEATURE_FALLBACK),
        "card4": fit_card_text(second, FEATURE_TWO_FALLBACK),
        "card5_takeaway": fit_card_text(link_cta(name, card.link), CTA_FALLBACK),
    }
    if not cards_are_valid(cards):
        logger.warning("template produced invalid cards; using emergency copy")
        cards = {key: EMERGENCY_CARD for key in CARD_KEYS}
    return cards


def load_queue(path: Optional[os.PathLike[str] | str] = None) -> Dict[str, Any]:
    target = queue_path(path)
    warnings: List[str] = []
    if not target.exists():
        warnings.append(f"queue file missing: {target}")
        return {
            "version": 1,
            "cadence_per_day": DEFAULT_CADENCE_PER_DAY,
            "scripts": [],
            "warnings": warnings,
            "path": str(target),
        }
    try:
        data = _read_json(target)
    except (OSError, json.JSONDecodeError) as exc:
        warnings.append(f"queue file unreadable: {exc}")
        return {
            "version": 1,
            "cadence_per_day": DEFAULT_CADENCE_PER_DAY,
            "scripts": [],
            "warnings": warnings,
            "path": str(target),
        }
    if not isinstance(data, dict):
        warnings.append("queue root is not an object")
        data = {}
    scripts_raw = data.get("scripts")
    if not isinstance(scripts_raw, list):
        warnings.append("scripts is not a list")
        scripts_raw = []

    scripts: List[Dict[str, Any]] = []
    seen_ids = set()
    for index, item in enumerate(scripts_raw):
        if not isinstance(item, dict):
            warnings.append(f"scripts[{index}] is not an object")
            continue
        script_id = str(item.get("id") or "").strip()
        if not script_id:
            warnings.append(f"scripts[{index}] missing id")
            continue
        if script_id in seen_ids:
            warnings.append(f"duplicate script id ignored: {script_id}")
            continue
        seen_ids.add(script_id)
        cards = item.get("cards")
        if not cards_are_valid(cards):
            warnings.append(f"invalid cards ignored: {script_id}")
            continue
        normalized_cards = {key: normalize_card_text(str(cards[key])) for key in CARD_KEYS}
        aliases = _as_str_list(item.get("aliases"))
        match_ids = _as_str_list(item.get("match_ids"))
        tool_name = str(item.get("tool_name") or "").strip()
        if not tool_name and not aliases and not match_ids:
            warnings.append(f"unmatchable script ignored: {script_id}")
            continue
        scripts.append(
            {
                "id": script_id,
                "tool_name": tool_name,
                "aliases": aliases,
                "match_ids": match_ids,
                "link": str(item.get("link") or "").strip(),
                "cards": normalized_cards,
            }
        )

    cadence = data.get("cadence_per_day", DEFAULT_CADENCE_PER_DAY)
    if isinstance(cadence, bool) or not isinstance(cadence, int) or cadence < 1:
        warnings.append("cadence_per_day invalid; using 1")
        cadence = DEFAULT_CADENCE_PER_DAY
    for warning in warnings:
        logger.warning("%s", warning)
    return {
        "version": data.get("version") or 1,
        "cadence_per_day": cadence,
        "scripts": scripts,
        "warnings": warnings,
        "path": str(target),
    }


def compute_days_left(unused_count: int, cadence_per_day: int) -> int:
    """days_left = floor(unused_valid_scripts / cadence_per_day)."""
    cadence = cadence_per_day if isinstance(cadence_per_day, int) and cadence_per_day >= 1 else DEFAULT_CADENCE_PER_DAY
    unused = unused_count if isinstance(unused_count, int) and unused_count > 0 else 0
    return unused // cadence


def _match_keys(script: Dict[str, Any]) -> List[str]:
    keys = [str(script.get("tool_name") or "")]
    keys.extend(str(item) for item in script.get("aliases") or [])
    cleaned = []
    for key in keys:
        text = key.strip()
        if len(text) < 2:
            continue
        if text.casefold() in _GENERIC_KEYS:
            continue
        cleaned.append(text)
    return cleaned


def match_score(script: Dict[str, Any], card: ToolCard) -> int:
    best = 0
    tool_id = (card.tool_id or "").strip()
    if tool_id and tool_id in {str(item).strip() for item in script.get("match_ids") or []}:
        best = 10_000 + len(tool_id)
    blob = card.match_blob()
    name_fold = (card.name or "").casefold()
    for key in _match_keys(script):
        folded = key.casefold()
        if folded == name_fold or (tool_id and folded == tool_id.casefold()):
            best = max(best, 5_000 + len(key))
        elif folded in blob:
            best = max(best, len(key))
    return best


def select_script(
    card: ToolCard,
    scripts: Sequence[Dict[str, Any]],
    consumed_ids: Iterable[str],
) -> Optional[Dict[str, Any]]:
    consumed = {str(item) for item in consumed_ids}
    best: Optional[Dict[str, Any]] = None
    best_score = 0
    for script in scripts:
        if script["id"] in consumed:
            continue
        score = match_score(script, card)
        if score > best_score:
            best = script
            best_score = score
    return best


def resolve_shorts_script(
    data: Optional[Dict[str, Any]] = None,
    *,
    queue_file: Optional[os.PathLike[str] | str] = None,
    consumed_paths: Optional[Sequence[os.PathLike[str] | str]] = None,
    outdir: Optional[os.PathLike[str] | str] = None,
    force_template: bool = False,
) -> ResolvedScript:
    """
    도구 카드에 맞는 미사용 대본을 고른다.
    없으면 템플릿. 이 함수는 id 를 소비하지 않는다.
    """
    target = queue_file
    card = tool_card_from_mapping(data)
    paths = [Path(item) for item in consumed_paths] if consumed_paths is not None else consumed_state_paths(outdir)
    consumed = load_consumed_ids(paths)
    chosen = None
    if not force_template:
        queue = load_queue(target)
        chosen = select_script(card, queue["scripts"], consumed)
    if chosen is not None:
        link = chosen["link"] or card.link
        return ResolvedScript(
            cards={key: chosen["cards"][key] for key in CARD_KEYS},
            source="queue",
            script_id=chosen["id"],
            link=link,
            tool_name=chosen["tool_name"] or card.name,
        )
    templated = template_cards(card)
    return ResolvedScript(
        cards=templated,
        source="template",
        script_id=None,
        link=card.link,
        tool_name=card.name or GENERIC_NAME,
    )


def build_queue_report(
    *,
    queue_file: Optional[os.PathLike[str] | str] = None,
    consumed_paths: Optional[Sequence[Path]] = None,
    outdir: Optional[os.PathLike[str] | str] = None,
) -> Dict[str, Any]:
    queue = load_queue(queue_file)
    paths = list(consumed_paths) if consumed_paths is not None else consumed_state_paths(outdir)
    consumed = load_consumed_ids(paths)
    consumed_set = set(consumed)
    unused = [script for script in queue["scripts"] if script["id"] not in consumed_set]
    days = compute_days_left(len(unused), queue["cadence_per_day"])
    return {
        "queue_path": queue["path"],
        "consumed_paths": [str(path) for path in paths],
        "cadence_per_day": queue["cadence_per_day"],
        "low_water_days": LOW_WATER_DAYS,
        "valid_scripts": len(queue["scripts"]),
        "consumed_ids": consumed,
        "unused_scripts": len(unused),
        "unused_ids": [script["id"] for script in unused],
        "days_left": days,
        "low_water": days < LOW_WATER_DAYS,
        "formula": "days_left = floor(unused_valid_scripts / cadence_per_day)",
        "warnings": queue["warnings"],
    }


def low_water_issue_body(report: Dict[str, Any]) -> str:
    unused_ids = report.get("unused_ids") or []
    preview = ", ".join(unused_ids[:40]) or "(없음)"
    extra = ""
    if len(unused_ids) > 40:
        extra = f"\n- 외 {len(unused_ids) - 40}개"
    threshold = report.get("low_water_days", LOW_WATER_DAYS)
    return (
        f"쇼츠 사전 대본이 {threshold}일분보다 적습니다.\n\n"
        f"- days_left: {report.get('days_left')}\n"
        f"- unused_scripts: {report.get('unused_scripts')}\n"
        f"- cadence_per_day: {report.get('cadence_per_day')}\n"
        f"- 기준: days_left = floor(미사용 유효 대본 수 / cadence_per_day) < {threshold}\n"
        f"- 남은 id: {preview}{extra}\n\n"
        "content_queue/shorts_scripts.json 에 대본을 추가해 주세요.\n"
        "레거시 검정 카드 쇼츠 업로드는 중단되었습니다. 템플릿이 있어도 영상을 올리지 않습니다.\n"
        "이 이슈는 잔여 일수가 바뀌면 본문을 갱신합니다.\n"
    )


def queue_recovered_comment(report: Dict[str, Any]) -> str:
    threshold = report.get("low_water_days", LOW_WATER_DAYS)
    return (
        f"사전 대본이 다시 {threshold}일 이상입니다. "
        f"days_left={report.get('days_left')}. 이슈를 닫습니다."
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Show how many pre-written Shorts scripts remain")
    parser.add_argument("command", nargs="?", default="status", choices=["status"])
    parser.add_argument("--queue", help="Override shorts_scripts.json path")
    parser.add_argument("--outdir", help="Include out/content_queue_state.json in the consumed union")
    args = parser.parse_args(list(argv) if argv is not None else None)
    report = build_queue_report(queue_file=args.queue, outdir=args.outdir)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
