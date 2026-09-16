"""
Supabase collector DB에서 아직 쇼츠로 올리지 않은 published 영상을 고른다.

환경변수:
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY
  PROMO_STATE_PATH  (선택, 기본 out/promo_shorts_state.json)

컬럼이 아직 없으면 REST가 실패하므로, 로컬 state 파일로 중복 게시를 막는다.
GitHub Actions는 워크스페이스가 매번 초기화되므로 SQL 마이그레이션을 한 번 실행하는 것이 정답이다.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

DEFAULT_STATE_PATH = Path(os.environ.get("PROMO_STATE_PATH", "out/promo_shorts_state.json"))
SELECT_FIELDS = (
    "id,youtube_id,title,hook,summary_points,takeaway,published_at,status,"
    "promo_short_youtube_id,promo_short_uploaded_at"
)
SELECT_FIELDS_LEGACY = "id,youtube_id,title,hook,summary_points,takeaway,published_at,status"


class SupabaseSourceError(Exception):
    pass


class PromoColumnsMissing(SupabaseSourceError):
    pass


@dataclass
class CollectorVideo:
    id: str
    youtube_id: str
    title: str
    hook: str
    summary_points: List[str]
    takeaway: str
    published_at: Optional[str] = None
    status: str = "published"
    promo_short_youtube_id: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_metadata(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "youtube_id": self.youtube_id,
            "title": self.title,
            "short_title": self.hook,
            "hook": self.hook,
            "summary_points": self.summary_points,
            "takeaway": self.takeaway,
            "published_at": self.published_at,
        }


def normalize_summary_points(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("[") and text.endswith("]"):
            try:
                raw = json.loads(text)
            except json.JSONDecodeError:
                raw = [p.strip(" •-\t") for p in text.splitlines() if p.strip()]
        else:
            raw = [p.strip(" •-\t") for p in text.splitlines() if p.strip()]
    if not isinstance(raw, list):
        return []
    return [str(p).strip() for p in raw if str(p).strip()]


def video_is_filled(hook: str, summary_points: List[str], takeaway: str) -> bool:
    return bool(hook and hook.strip() and takeaway and takeaway.strip() and len(summary_points) >= 3)


def row_to_video(row: Dict[str, Any]) -> CollectorVideo:
    return CollectorVideo(
        id=str(row["id"]),
        youtube_id=str(row.get("youtube_id") or ""),
        title=str(row.get("title") or ""),
        hook=str(row.get("hook") or "").strip(),
        summary_points=normalize_summary_points(row.get("summary_points")),
        takeaway=str(row.get("takeaway") or "").strip(),
        published_at=row.get("published_at"),
        status=str(row.get("status") or "published"),
        promo_short_youtube_id=row.get("promo_short_youtube_id"),
        extra=row,
    )


def load_state(path: Optional[Path] = None) -> Dict[str, Any]:
    path = path or DEFAULT_STATE_PATH
    if not path.exists():
        return {"uploaded": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"uploaded": {}}
    if not isinstance(data, dict):
        return {"uploaded": {}}
    data.setdefault("uploaded", {})
    return data


def save_state(state: Dict[str, Any], path: Optional[Path] = None) -> Path:
    path = path or DEFAULT_STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def already_uploaded(video_id: str, state: Optional[Dict[str, Any]] = None) -> bool:
    state = state if state is not None else load_state()
    return str(video_id) in (state.get("uploaded") or {})


def _headers(service_key: str) -> Dict[str, str]:
    return {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _is_unknown_column_error(status_code: int, body: str) -> bool:
    if status_code not in (400, 404):
        return False
    lowered = body.lower()
    return (
        "promo_short_youtube_id" in lowered
        or "promo_short_uploaded_at" in lowered
        or "does not exist" in lowered
        or "could not find" in lowered
        or "schema cache" in lowered
    )


class SupabaseSource:
    def __init__(
        self,
        url: Optional[str] = None,
        service_key: Optional[str] = None,
        http: Any = None,
        state_path: Optional[Path] = None,
    ):
        self.url = (url or os.environ.get("SUPABASE_URL") or "").rstrip("/")
        self.service_key = service_key or os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
        self.http = http or requests
        self.state_path = state_path or DEFAULT_STATE_PATH
        self.promo_columns_available = True

    def require_config(self) -> None:
        if not self.url or not self.service_key:
            raise SupabaseSourceError("SUPABASE_URL과 SUPABASE_SERVICE_ROLE_KEY가 필요합니다.")

    def _get(self, select_fields: str, include_null_filter: bool) -> List[Dict[str, Any]]:
        self.require_config()
        params = {
            "select": select_fields,
            "status": "eq.published",
            "order": "published_at.asc.nullslast",
            "limit": "80",
        }
        if include_null_filter:
            params["promo_short_youtube_id"] = "is.null"
        resp = self.http.get(
            f"{self.url}/rest/v1/videos",
            headers=_headers(self.service_key),
            params=params,
            timeout=30,
        )
        if resp.status_code >= 400:
            if include_null_filter and _is_unknown_column_error(resp.status_code, resp.text):
                raise PromoColumnsMissing(resp.text[:300])
            raise SupabaseSourceError(f"Supabase GET 실패 ({resp.status_code}): {resp.text[:300]}")
        data = resp.json()
        if not isinstance(data, list):
            raise SupabaseSourceError("Supabase 응답이 배열이 아닙니다.")
        return data

    def fetch_candidates(self) -> List[CollectorVideo]:
        try:
            rows = self._get(SELECT_FIELDS, include_null_filter=True)
            self.promo_columns_available = True
        except PromoColumnsMissing:
            print("[supabase] promo_short_* 컬럼이 없습니다. 로컬 state 폴백을 사용합니다. SQL 마이그레이션을 실행하세요.")
            self.promo_columns_available = False
            rows = self._get(SELECT_FIELDS_LEGACY, include_null_filter=False)

        state = load_state(self.state_path)
        videos: List[CollectorVideo] = []
        for row in rows:
            video = row_to_video(row)
            if video.promo_short_youtube_id:
                continue
            if already_uploaded(video.id, state):
                continue
            if not video_is_filled(video.hook, video.summary_points, video.takeaway):
                continue
            videos.append(video)
        return videos

    def pick_next(self) -> Optional[CollectorVideo]:
        candidates = self.fetch_candidates()
        return candidates[0] if candidates else None

    def mark_uploaded(self, video_id: str, youtube_video_id: str, uploaded_at: Optional[str] = None) -> Dict[str, Any]:
        uploaded_at = uploaded_at or datetime.now(timezone.utc).isoformat()
        state = load_state(self.state_path)
        state.setdefault("uploaded", {})
        state["uploaded"][str(video_id)] = {
            "promo_short_youtube_id": youtube_video_id,
            "promo_short_uploaded_at": uploaded_at,
        }
        save_state(state, self.state_path)

        db_updated = False
        db_error: Optional[str] = None
        if self.promo_columns_available:
            try:
                self.require_config()
                resp = self.http.patch(
                    f"{self.url}/rest/v1/videos",
                    headers={**_headers(self.service_key), "Prefer": "return=minimal"},
                    params={"id": f"eq.{video_id}"},
                    json={
                        "promo_short_youtube_id": youtube_video_id,
                        "promo_short_uploaded_at": uploaded_at,
                    },
                    timeout=30,
                )
                if resp.status_code >= 400:
                    if _is_unknown_column_error(resp.status_code, resp.text):
                        self.promo_columns_available = False
                        db_error = "promo columns missing"
                    else:
                        raise SupabaseSourceError(
                            f"Supabase PATCH 실패 ({resp.status_code}): {resp.text[:300]}"
                        )
                else:
                    db_updated = True
            except SupabaseSourceError:
                raise
            except Exception as exc:
                db_error = str(exc)
                raise SupabaseSourceError(f"업로드 추적 컬럼 갱신 실패: {exc}") from exc

        return {
            "video_id": video_id,
            "promo_short_youtube_id": youtube_video_id,
            "promo_short_uploaded_at": uploaded_at,
            "db_updated": db_updated,
            "state_path": str(self.state_path),
            "db_error": db_error,
        }


def pick_next_unpublished_video() -> Optional[CollectorVideo]:
    return SupabaseSource().pick_next()
