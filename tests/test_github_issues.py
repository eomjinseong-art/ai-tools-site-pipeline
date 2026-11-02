import json
import os
import unittest
from unittest import mock

from github_issues import (
    ISSUE_TITLE_QUEUE,
    ISSUE_TITLE_YOUTUBE,
    GithubClient,
    issues_enabled,
    open_youtube_reauth_issue,
    sync_queue_issue,
)


class _Resp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self._payload


class FakeHttp:
    def __init__(self, issues=None):
        self.issues = list(issues or [])
        self.comments = []
        self.posts = []
        self.patches = []

    def get(self, url, headers=None, params=None, timeout=None):
        page = int((params or {}).get("page") or 1)
        if page > 1:
            return _Resp(200, [])
        return _Resp(200, list(self.issues))

    def post(self, url, headers=None, json=None, timeout=None):
        self.posts.append((url, json))
        if url.endswith("/comments"):
            self.comments.append(json["body"])
            return _Resp(201, {"id": len(self.comments)})
        number = len(self.issues) + 10
        issue = {"number": number, "title": json["title"], "body": json["body"], "state": "open"}
        self.issues.append(issue)
        return _Resp(201, issue)

    def patch(self, url, headers=None, json=None, timeout=None):
        self.patches.append((url, json))
        number = int(url.rstrip("/").split("/")[-1])
        for issue in self.issues:
            if issue["number"] == number:
                issue.update(json)
                return _Resp(200, issue)
        raise AssertionError(f"missing issue {number}")


class GithubIssueTests(unittest.TestCase):
    def test_titles_are_exact(self):
        self.assertEqual(ISSUE_TITLE_YOUTUBE, "유튜브 로그인 다시 필요")
        self.assertEqual(ISSUE_TITLE_QUEUE, "쇼츠 대본 대기열 부족")

    def test_disabled_outside_actions_even_with_a_token(self):
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "local-token", "GITHUB_ACTIONS": ""}, clear=False):
            self.assertFalse(issues_enabled())
        with mock.patch.dict(
            os.environ,
            {"GITHUB_TOKEN": "local-token", "GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "example/repo"},
            clear=False,
        ):
            self.assertTrue(issues_enabled())

    def test_pull_request_with_same_title_does_not_block_create(self):
        http = FakeHttp(
            [
                {
                    "number": 1,
                    "title": ISSUE_TITLE_YOUTUBE,
                    "body": "pr",
                    "pull_request": {"url": "https://example.test/pr/1"},
                }
            ]
        )
        with mock.patch.dict(os.environ, {"GITHUB_REPOSITORY": "example/repo", "GITHUB_TOKEN": "t"}, clear=False):
            result = open_youtube_reauth_issue(http=http)
        self.assertEqual(result["action"], "created")
        titles = [issue["title"] for issue in http.issues if "pull_request" not in issue]
        self.assertIn(ISSUE_TITLE_YOUTUBE, titles)
        self.assertTrue(http.comments)

    def test_second_youtube_failure_updates_same_issue(self):
        http = FakeHttp()
        with mock.patch.dict(os.environ, {"GITHUB_REPOSITORY": "example/repo", "GITHUB_TOKEN": "t"}, clear=False):
            first = open_youtube_reauth_issue(http=http)
            second = open_youtube_reauth_issue(http=http)
        self.assertEqual(first["action"], "created")
        self.assertEqual(second["action"], "updated")
        self.assertEqual(first["number"], second["number"])
        self.assertEqual(sum(1 for issue in http.issues if issue["title"] == ISSUE_TITLE_YOUTUBE), 1)
        self.assertGreaterEqual(len(http.comments), 2)
        blob = json.dumps(http.issues, ensure_ascii=False)
        self.assertNotIn("YT_REFRESH_TOKEN=", blob)
        self.assertIn("invalid_grant", blob)

    def test_low_water_opens_then_updates_then_closes(self):
        http = FakeHttp()
        low = {
            "days_left": 13,
            "unused_scripts": 13,
            "cadence_per_day": 1,
            "low_water_days": 14,
            "unused_ids": ["a", "b"],
        }
        same = dict(low)
        recovered = dict(low, days_left=14, unused_scripts=14)
        sync_queue_issue(low, http=http)
        comments_after_open = len(http.comments)
        sync_queue_issue(same, http=http)
        self.assertEqual(len(http.comments), comments_after_open)
        self.assertEqual(sum(1 for issue in http.issues if issue["title"] == ISSUE_TITLE_QUEUE), 1)
        closed = sync_queue_issue(recovered, http=http)
        self.assertEqual(closed["action"], "closed")
        self.assertEqual(http.issues[0]["state"], "closed")

    def test_client_updates_body_when_days_change(self):
        http = FakeHttp(
            [{"number": 4, "title": ISSUE_TITLE_QUEUE, "body": "days_left: 13\n", "state": "open"}]
        )
        client = GithubClient("token", "example/repo", http=http)
        result = client.upsert_open_issue(
            ISSUE_TITLE_QUEUE,
            "days_left: 12\n",
            comment="잔여가 바뀌었습니다",
            comment_on_unchanged=False,
        )
        self.assertEqual(result["action"], "updated")
        self.assertTrue(result["commented"])
        self.assertIn("days_left: 12", http.issues[0]["body"])


if __name__ == "__main__":
    unittest.main()
