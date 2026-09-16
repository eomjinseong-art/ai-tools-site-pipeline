import unittest

from google.oauth2.credentials import Credentials

from youtube_upload import (
    TOKEN_URI,
    YouTubeUploadError,
    assert_expected_channel,
    build_shorts_description,
    build_shorts_title,
    build_video_resource,
    credentials_from_env,
)


class YouTubeHelperTests(unittest.TestCase):
    def test_title_appends_shorts_and_fits(self):
        title = build_shorts_title("ChatGPT로 업무 자동화하는 법", hook="반복 업무를 바로 맡기는 방법")
        self.assertTrue(title.endswith("#Shorts"))
        self.assertLessEqual(len(title), 100)
        self.assertIn("반복 업무", title)

    def test_title_does_not_duplicate_shorts(self):
        title = build_shorts_title("이미 있는 제목 #Shorts")
        self.assertEqual(title.count("#Shorts"), 1)

    def test_description_includes_source_and_shorts(self):
        desc = build_shorts_description("원본 제목", "핵심 한 줄입니다", "abc123")
        self.assertIn("#Shorts", desc)
        self.assertIn("https://www.youtube.com/watch?v=abc123", desc)
        self.assertIn("나두 AI", desc)

    def test_credentials_from_env(self):
        creds = credentials_from_env(
            {
                "YT_CLIENT_ID": "cid.apps.googleusercontent.com",
                "YT_CLIENT_SECRET": "secret",
                "YT_REFRESH_TOKEN": "refresh-token",
            }
        )
        self.assertIsInstance(creds, Credentials)
        self.assertEqual(creds.client_id, "cid.apps.googleusercontent.com")
        self.assertEqual(creds.refresh_token, "refresh-token")
        self.assertEqual(creds.token_uri, TOKEN_URI)
        self.assertIsNone(creds.token)

    def test_credentials_require_all_three(self):
        with self.assertRaises(YouTubeUploadError):
            credentials_from_env({"YT_CLIENT_ID": "only-id"})

    def test_channel_mismatch_aborts(self):
        with self.assertRaises(YouTubeUploadError):
            assert_expected_channel("UC-actual", "UC-expected")
        assert_expected_channel("UC-same", "UC-same")
        assert_expected_channel("UC-actual", "")

    def test_video_resource_is_public_shorts_payload(self):
        body = build_video_resource("제목 #Shorts", "설명 #Shorts")
        self.assertEqual(body["snippet"]["categoryId"], "28")
        self.assertIn("Shorts", body["snippet"]["tags"])
        self.assertEqual(body["status"]["privacyStatus"], "public")
        self.assertFalse(body["status"]["selfDeclaredMadeForKids"])


if __name__ == "__main__":
    unittest.main()
