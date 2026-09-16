"""
YouTube Shorts 업로드 (설치된 앱 + refresh token, CI에서 브라우저 없음).

환경변수:
  YT_CLIENT_ID
  YT_CLIENT_SECRET
  YT_REFRESH_TOKEN
  EXPECTED_YOUTUBE_CHANNEL_ID  (선택 — 불일치 시 업로드 중단)
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

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
    creds.refresh(Request())
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
    return {
        "snippet": {
            "title": title[:TITLE_MAX],
            "description": description,
            "tags": ["Shorts", "나두AI", "AI툴", "AI Tools Korea"],
            "categoryId": "28",
        },
        "status": {
            "privacyStatus": os.environ.get("YT_PRIVACY_STATUS", "public"),
            "selfDeclaredMadeForKids": False,
        },
    }


def upload_shorts(
    video_path: str,
    title: str,
    description: str,
    thumbnail_path: Optional[str] = None,
    expected_channel_id: Optional[str] = None,
    youtube: Any = None,
) -> str:
    if not os.path.isfile(video_path):
        raise YouTubeUploadError(f"업로드할 파일이 없습니다: {video_path}")

    if youtube is None:
        youtube = build_youtube_client()

    channel_id = fetch_my_channel_id(youtube)
    expected = expected_channel_id if expected_channel_id is not None else os.environ.get("EXPECTED_YOUTUBE_CHANNEL_ID")
    assert_expected_channel(channel_id, expected)

    body = build_video_resource(title, description)
    media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True, chunksize=1024 * 1024)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"[youtube] upload {int(status.progress() * 100)}%")

    video_id = (response or {}).get("id")
    if not video_id:
        raise YouTubeUploadError(f"YouTube 업로드 응답에 id가 없습니다: {response}")

    if thumbnail_path and os.path.isfile(thumbnail_path):
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path, mimetype="image/jpeg"),
            ).execute()
        except Exception as exc:
            print(f"[youtube] 썸네일 설정 실패(영상은 업로드됨): {exc}")

    print(f"[youtube] uploaded https://www.youtube.com/shorts/{video_id} (channel={channel_id})")
    return video_id
