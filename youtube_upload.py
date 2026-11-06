"""
YouTube title and description helpers.

`upload_shorts` and `build_video_resource` are retired. They raise before
reading credentials or calling the videos.insert API. There is no public
privacy default and no environment-variable bypass.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from legacy_shorts_retirement import refuse_legacy_black_card_shorts

YOUTUBE_UPLOAD_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]
TOKEN_URI = "https://oauth2.googleapis.com/token"
TITLE_MAX = 100
SHORTS_TAG = "#Shorts"


class YouTubeUploadError(Exception):
    pass


class YouTubeAuthExpired(YouTubeUploadError):
    """OAuth refresh token이 invalid_grant 로 거절된 경우."""


def is_invalid_grant(exc: BaseException) -> bool:
    seen: set[int] = set()
    current: Optional[BaseException] = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if _payload_has_invalid_grant(current):
            return True
        cause = current.__cause__
        context = current.__context__ if not current.__suppress_context__ else None
        current = cause or context
    return False


def _payload_has_invalid_grant(exc: BaseException) -> bool:
    if "invalid_grant" in str(exc).lower():
        return True
    for arg in getattr(exc, "args", ()):
        if isinstance(arg, str) and "invalid_grant" in arg.lower():
            return True
        if isinstance(arg, dict):
            error = str(arg.get("error") or "").lower()
            description = str(arg.get("error_description") or "").lower()
            if error == "invalid_grant" or "invalid_grant" in error or "invalid_grant" in description:
                return True
    return False


_AUTH_EXPIRED_MESSAGE = (
    "YouTube OAuth refresh failed with invalid_grant. "
    "YT_REFRESH_TOKEN 을 다시 발급해야 합니다."
)


def build_shorts_title(source_title: str, hook: Optional[str] = None) -> str:
    base = (hook or source_title or "나두 AI 요약").strip()
    base = " ".join(base.split())
    suffix = f" {SHORTS_TAG}"
    if SHORTS_TAG.lower() not in base.lower():
        budget = TITLE_MAX - len(suffix)
        if len(base) > budget:
            base = base[:budget].rstrip()
        return f"{base}{suffix}"
    return base[:TITLE_MAX]


def build_shorts_description(
    title: str,
    takeaway: str,
    source_youtube_id: Optional[str] = None,
    extra: Optional[str] = None,
) -> str:
    lines = [
        (takeaway or "").strip(),
        "",
        f"원본: {title}".strip(),
    ]
    if source_youtube_id:
        lines.append(f"https://www.youtube.com/watch?v={source_youtube_id}")
    if extra:
        lines.extend(["", extra.strip()])
    lines.extend(["", "나두 AI (AI Tools Korea)", SHORTS_TAG, "#나두AI #AI툴 #Shorts"])
    return "\n".join(lines).strip() + "\n"


def credentials_from_env(env: Optional[Dict[str, str]] = None) -> Credentials:
    source = env if env is not None else os.environ
    client_id = (source.get("YT_CLIENT_ID") or "").strip()
    client_secret = (source.get("YT_CLIENT_SECRET") or "").strip()
    refresh_token = (source.get("YT_REFRESH_TOKEN") or "").strip()
    if not client_id or not client_secret or not refresh_token:
        raise YouTubeUploadError(
            "YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN이 모두 필요합니다."
        )
    return Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=TOKEN_URI,
        client_id=client_id,
        client_secret=client_secret,
        scopes=YOUTUBE_UPLOAD_SCOPES,
    )


def refresh_access_token(creds: Credentials) -> Credentials:
    try:
        creds.refresh(Request())
    except YouTubeAuthExpired:
        raise
    except Exception as exc:
        if is_invalid_grant(exc):
            raise YouTubeAuthExpired(_AUTH_EXPIRED_MESSAGE) from exc
        raise YouTubeUploadError(f"YouTube 액세스 토큰 갱신 실패: {exc}") from exc
    if not creds.valid:
        raise YouTubeUploadError("YouTube refresh token으로 액세스 토큰을 갱신하지 못했습니다.")
    return creds


def assert_expected_channel(actual_channel_id: str, expected_channel_id: Optional[str]) -> None:
    expected = (expected_channel_id or "").strip()
    if expected and actual_channel_id != expected:
        raise YouTubeUploadError(
            f"YouTube 채널 불일치: expected={expected} actual={actual_channel_id}"
        )


def build_youtube_client(creds: Optional[Credentials] = None):
    creds = creds or credentials_from_env()
    if not creds.valid:
        refresh_access_token(creds)
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def fetch_my_channel_id(youtube) -> str:
    resp = youtube.channels().list(part="id,snippet", mine=True).execute()
    items = resp.get("items") or []
    if not items:
        raise YouTubeUploadError("이 자격 증명에 연결된 YouTube 채널이 없습니다.")
    return items[0]["id"]


def build_video_resource(title: str, description: str) -> Dict[str, Any]:
    """Retired. Does not build a public video resource."""
    del title, description
    refuse_legacy_black_card_shorts("YouTube video resource")
    raise AssertionError("unreachable")


def upload_shorts(
    video_path: str,
    title: str,
    description: str,
    thumbnail_path: Optional[str] = None,
    expected_channel_id: Optional[str] = None,
    youtube: Any = None,
) -> str:
    """Retired. Does not refresh credentials or call the YouTube insert API."""
    del video_path, title, description, thumbnail_path, expected_channel_id, youtube
    refuse_legacy_black_card_shorts("YouTube Shorts upload")
    raise AssertionError("unreachable")
