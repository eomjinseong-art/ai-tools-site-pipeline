import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from supabase_source import (
    SupabaseSource,
    already_uploaded,
    load_state,
    normalize_summary_points,
    row_to_video,
    video_is_filled,
)


class _Resp:
    def __init__(self, status_code, payload, text=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload)

    def json(self):
        return self._payload


FILLED_ROW = {
    "id": "vid-1",
    "youtube_id": "abc",
    "title": "제목",
    "hook": "반복 업무를 챗GPT에게 맡기는 방법",
    "summary_points": [
        "반복되는 이메일 초안을 먼저 맡기세요",
        "표와 요약은 프롬프트 템플릿으로 고정하세요",
        "결과는 사람이 한 번만 검수하면 됩니다",
    ],
    "takeaway": "템플릿만 있으면 초보도 업무 시간을 줄일 수 있습니다",
    "published_at": "2026-01-01T00:00:00Z",
    "status": "published",
    "promo_short_youtube_id": None,
}


class SupabaseSourceTests(unittest.TestCase):
    def test_normalize_points_from_json_string(self):
        points = normalize_summary_points('["하나 포인트입니다", "둘", "셋"]')
        self.assertEqual(points[0], "하나 포인트입니다")

    def test_video_is_filled(self):
        video = row_to_video(FILLED_ROW)
        self.assertTrue(video_is_filled(video.hook, video.summary_points, video.takeaway))
        self.assertFalse(video_is_filled("", ["a", "b", "c"], "takeaway here"))

    def test_pick_skips_already_uploaded_and_empty(self):
        empty = dict(FILLED_ROW, id="vid-empty", hook="", takeaway="")
        posted = dict(FILLED_ROW, id="vid-posted", promo_short_youtube_id="yt1")
        http = Mock()
        http.get.return_value = _Resp(200, [empty, posted, FILLED_ROW])
        with TemporaryDirectory() as tmp:
            source = SupabaseSource(
                url="https://example.supabase.co",
                service_key="key",
                http=http,
                state_path=Path(tmp) / "state.json",
            )
            picked = source.pick_next()
        self.assertIsNotNone(picked)
        self.assertEqual(picked.id, "vid-1")

    def test_unknown_columns_fall_back_to_legacy_and_state(self):
        http = Mock()
        http.get.side_effect = [
            _Resp(400, {}, text='column videos.promo_short_youtube_id does not exist'),
            _Resp(200, [FILLED_ROW]),
        ]
        with TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            source = SupabaseSource(
                url="https://example.supabase.co",
                service_key="key",
                http=http,
                state_path=state_path,
            )
            first = source.pick_next()
            self.assertEqual(first.id, "vid-1")
            self.assertFalse(source.promo_columns_available)
            source.mark_uploaded("vid-1", "yt-new")
            self.assertTrue(already_uploaded("vid-1", load_state(state_path)))
            source2 = SupabaseSource(
                url="https://example.supabase.co",
                service_key="key",
                http=http,
                state_path=state_path,
            )
            http.get.side_effect = [
                _Resp(400, {}, text='column videos.promo_short_youtube_id does not exist'),
                _Resp(200, [FILLED_ROW]),
            ]
            self.assertIsNone(source2.pick_next())

    def test_mark_uploaded_patches_db(self):
        http = Mock()
        http.patch.return_value = _Resp(204, None, text="")
        with TemporaryDirectory() as tmp:
            source = SupabaseSource(
                url="https://example.supabase.co",
                service_key="key",
                http=http,
                state_path=Path(tmp) / "state.json",
            )
            result = source.mark_uploaded("vid-1", "yt-9")
        self.assertTrue(result["db_updated"])
        http.patch.assert_called_once()
        kwargs = http.patch.call_args.kwargs
        self.assertEqual(kwargs["json"]["promo_short_youtube_id"], "yt-9")
        self.assertEqual(kwargs["params"]["id"], "eq.vid-1")


if __name__ == "__main__":
    unittest.main()
