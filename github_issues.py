"""
GitHub 이슈를 열거나 같은 제목의 열린 이슈 본문을 갱신한다.

워크플로에서는 GITHUB_TOKEN + GITHUB_REPOSITORY 가 있다.
토큰이 없으면 호출부는 업로드를 막지 않고 경고만 남긴다.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

ISSUE_TITLE_YOUTUBE = "유튜브 로그인 다시 필요"
ISSUE_TITLE_QUEUE = "쇼츠 대본 대기열 부족"
API_ROOT = "https://api.github.com"
MAX_PAGES = 5


class GithubIssueError(Exception):
    pass


def issues_enabled() -> bool:
    if os.environ.get("GITHUB_ACTIONS", "").strip().lower() != "true":
        return False
    return bool(_token())


def _token() -> str:
    return (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()


def _repo() -> str:
    return (os.environ.get("GITHUB_REPOSITORY") or "").strip()


def run_url() -> str:
    server = (os.environ.get("GITHUB_SERVER_URL") or "https://github.com").rstrip("/")
    repo = _repo()
    run_id = (os.environ.get("GITHUB_RUN_ID") or "").strip()
    if repo and run_id:
        return f"{server}/{repo}/actions/runs/{run_id}"
    return ""


def youtube_reauth_body() -> str:
    url = run_url()
    lines = [
        "YouTube OAuth refresh token 갱신이 invalid_grant 로 실패했습니다.",
        "",
        "시크릿 `YT_REFRESH_TOKEN` 을 같은 OAuth 클라이언트에서 다시 발급해 넣어 주세요.",
        "`YT_CLIENT_ID` 와 `YT_CLIENT_SECRET` 도 그 클라이언트의 값이어야 합니다.",
        "토큰 값 자체는 이슈에 적지 않습니다.",
    ]
    if url:
        lines.extend(["", f"워크플로 실행: {url}"])
    return "\n".join(lines) + "\n"


class GithubClient:
    def __init__(self, token: str, repo: str, http: Any = None):
        self.token = token
        self.repo = repo.strip().strip("/")
        self.http = http or requests

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "promo-shorts-pipeline",
        }

    def _check(self, response: Any, action: str) -> Any:
        status = getattr(response, "status_code", 0)
        if status >= 400:
            body = getattr(response, "text", "") or ""
            raise GithubIssueError(f"GitHub {action} 실패 ({status}): {body[:300]}")
        return response

    def list_open_issues(self) -> list:
        found = []
        for page in range(1, MAX_PAGES + 1):
            response = self.http.get(
                f"{API_ROOT}/repos/{self.repo}/issues",
                headers=self._headers(),
                params={"state": "open", "per_page": 100, "page": page},
                timeout=30,
            )
            self._check(response, "list issues")
            batch = response.json()
            if not isinstance(batch, list) or not batch:
                break
            for item in batch:
                if not isinstance(item, dict) or "pull_request" in item:
                    continue
                found.append(item)
            if len(batch) < 100:
                break
        return found

    def find_open(self, title: str) -> Optional[Dict[str, Any]]:
        matches = [item for item in self.list_open_issues() if item.get("title") == title]
        if not matches:
            return None
        matches.sort(key=lambda item: int(item.get("number") or 0))
        return matches[0]

    def create_issue(self, title: str, body: str) -> Dict[str, Any]:
        response = self.http.post(
            f"{API_ROOT}/repos/{self.repo}/issues",
            headers=self._headers(),
            json={"title": title, "body": body},
            timeout=30,
        )
        self._check(response, "create issue")
        data = response.json()
        if not isinstance(data, dict) or "number" not in data:
            raise GithubIssueError("GitHub create issue 응답에 number 가 없습니다.")
        return data

    def patch_issue(self, number: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        response = self.http.patch(
            f"{API_ROOT}/repos/{self.repo}/issues/{number}",
            headers=self._headers(),
            json=payload,
            timeout=30,
        )
        self._check(response, "update issue")
        data = response.json()
        return data if isinstance(data, dict) else {}

    def add_comment(self, number: int, body: str) -> None:
        response = self.http.post(
            f"{API_ROOT}/repos/{self.repo}/issues/{number}/comments",
            headers=self._headers(),
            json={"body": body},
            timeout=30,
        )
        self._check(response, "comment")

    def upsert_open_issue(
        self,
        title: str,
        body: str,
        *,
        comment: Optional[str] = None,
        comment_on_unchanged: bool = False,
    ) -> Dict[str, Any]:
        existing = self.find_open(title)
        if existing is None:
            created = self.create_issue(title, body)
            number = int(created["number"])
            if comment:
                self.add_comment(number, comment)
            logger.info("opened GitHub issue #%s %s", number, title)
            return {"action": "created", "number": number, "title": title}

        number = int(existing["number"])
        changed = (existing.get("body") or "") != body
        self.patch_issue(number, {"title": title, "body": body})
        commented = False
        if comment and (changed or comment_on_unchanged):
            self.add_comment(number, comment)
            commented = True
        logger.info("updated GitHub issue #%s %s", number, title)
        return {"action": "updated", "number": number, "title": title, "commented": commented, "changed": changed}

    def close_open_issue(self, title: str, comment: str) -> Dict[str, Any]:
        existing = self.find_open(title)
        if existing is None:
            return {"action": "none", "title": title}
        number = int(existing["number"])
        if comment:
            self.add_comment(number, comment)
        self.patch_issue(number, {"state": "closed"})
        logger.info("closed GitHub issue #%s %s", number, title)
        return {"action": "closed", "number": number, "title": title}


def client_from_env(http: Any = None) -> GithubClient:
    token = _token()
    repo = _repo()
    if not token or not repo:
        raise GithubIssueError("GITHUB_TOKEN 과 GITHUB_REPOSITORY 가 필요합니다.")
    return GithubClient(token, repo, http=http)


def open_youtube_reauth_issue(http: Any = None) -> Dict[str, Any]:
    if not issues_enabled() and http is None:
        logger.error("invalid_grant 이지만 GitHub 이슈를 열 토큰이 없습니다.")
        return {"skipped": True, "reason": "github issues disabled"}
    client = client_from_env(http=http) if http is None else GithubClient(_token() or "test", _repo() or "owner/repo", http=http)
    url = run_url()
    comment = "이번 실행에서도 invalid_grant 로 업로드가 실패했습니다."
    if url:
        comment = f"{comment}\n{url}"
    return client.upsert_open_issue(
        ISSUE_TITLE_YOUTUBE,
        youtube_reauth_body(),
        comment=comment,
        comment_on_unchanged=True,
    )


def sync_queue_issue(report: Dict[str, Any], http: Any = None) -> Dict[str, Any]:
    """days_left < 14 이면 이슈를 열거나 본문을 갱신하고, 회복되면 닫는다."""
    from content_queue import low_water_issue_body, queue_recovered_comment

    if http is None and not issues_enabled():
        return {"skipped": True, "reason": "github issues disabled"}
    client = client_from_env(http=http) if http is None else GithubClient(_token() or "test", _repo() or "owner/repo", http=http)
    days_left = int(report.get("days_left") or 0)
    threshold = int(report.get("low_water_days") or 14)
    if days_left < threshold:
        comment = f"사전 대본 잔여 {days_left}일분입니다. {threshold}일 미만이라 이슈를 갱신합니다."
        return client.upsert_open_issue(
            ISSUE_TITLE_QUEUE,
            low_water_issue_body(report),
            comment=comment,
            comment_on_unchanged=False,
        )
    return client.close_open_issue(ISSUE_TITLE_QUEUE, queue_recovered_comment(report))
