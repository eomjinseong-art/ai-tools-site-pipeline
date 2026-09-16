import json
import os
import unittest
from unittest import mock

import rewrite_for_shorts as rw


VALID_JSON = json.dumps(
    {
        "card1_hook": "반복 업무를 바로 맡기는 방법",
        "card2": "이메일 초안은 먼저 맡기세요",
        "card3": "표와 요약은 템플릿으로 고정",
        "card4": "결과는 사람이 한 번 검수하세요",
        "card5_takeaway": "템플릿만 있으면 시간을 줄입니다",
    },
    ensure_ascii=False,
)


class RewriteParsingTests(unittest.TestCase):
    def test_clean_model_text_strips_fence(self):
        raw = "```json\n" + VALID_JSON + "\n```"
        parsed = rw.parse_cards_json(raw)
        self.assertEqual(parsed["card1_hook"], "반복 업무를 바로 맡기는 방법")
        self.assertEqual(len(rw.cards_as_list(parsed)), 5)

    def test_parse_rejects_missing_keys(self):
        with self.assertRaises(rw.RewriteError):
            rw.parse_cards_json('{"card1_hook": "짧음"}')

    def test_parse_rejects_hashtag(self):
        payload = json.loads(VALID_JSON)
        payload["card2"] = "해시태그는 안 됩니다 #Shorts"
        with self.assertRaises(rw.RewriteError):
            rw.parse_cards_json(json.dumps(payload, ensure_ascii=False))

    def test_source_has_usable_cards(self):
        self.assertTrue(
            rw.source_has_usable_cards(
                "반복 업무를 챗GPT에게 맡기는 방법",
                [
                    "반복되는 이메일 초안을 먼저 맡기세요",
                    "표와 요약은 프롬프트 템플릿으로 고정하세요",
                    "결과는 사람이 한 번만 검수하면 됩니다",
                ],
                "템플릿만 있으면 초보도 업무 시간을 줄일 수 있습니다",
            )
        )
        self.assertFalse(rw.source_has_usable_cards("짧음", ["a", "b", "c"], "짧음"))

    def test_fallback_uses_source_not_canva_sample(self):
        hook = "노션 AI로 회의록을 정리하는 방법"
        points = [
            "녹음 파일을 업로드하고 요약을 요청하세요",
            "액션 아이템만 따로 뽑아 공유하세요",
            "다음 회의 전에 할 일을 다시 확인하세요",
        ]
        takeaway = "정리 시간을 줄이면 회의 자체에 집중할 수 있습니다"
        cards = rw.simple_rewrite_fallback(hook, points, takeaway)
        blob = " ".join(cards.values())
        self.assertIn("노션", blob)
        self.assertNotIn("캔바", blob)

    def test_resolve_model_ignores_claude(self):
        with mock.patch.dict(os.environ, {"REWRITE_MODEL": "claude-haiku-4-5-20251001"}, clear=False):
            self.assertEqual(rw.resolve_rewrite_model(), "gpt-4.1-mini")
        with mock.patch.dict(os.environ, {"OPENAI_MODEL": "gpt-4o-mini", "REWRITE_MODEL": ""}, clear=False):
            self.assertEqual(rw.resolve_rewrite_model(), "gpt-4o-mini")

    def test_openai_success_parses_json(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False):
            with mock.patch.object(rw, "_openai_complete", return_value="Here you go\n" + VALID_JSON):
                cards = rw.rewrite_summary_for_shorts(
                    "반복 업무를 챗GPT에게 맡기는 방법",
                    [
                        "반복되는 이메일 초안을 먼저 맡기세요",
                        "표와 요약은 프롬프트 템플릿으로 고정하세요",
                        "결과는 사람이 한 번만 검수하면 됩니다",
                    ],
                    "템플릿만 있으면 초보도 업무 시간을 줄일 수 있습니다",
                )
        self.assertEqual(cards["card3"], "표와 요약은 템플릿으로 고정")

    def test_fallback_only_when_source_usable(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False):
            with mock.patch.object(rw, "_openai_complete", side_effect=RuntimeError("billing")):
                cards = rw.rewrite_summary_for_shorts(
                    "반복 업무를 챗GPT에게 맡기는 방법",
                    [
                        "반복되는 이메일 초안을 먼저 맡기세요",
                        "표와 요약은 프롬프트 템플릿으로 고정하세요",
                        "결과는 사람이 한 번만 검수하면 됩니다",
                    ],
                    "템플릿만 있으면 초보도 업무 시간을 줄일 수 있습니다",
                    max_retries=1,
                )
        self.assertTrue(rw.validate_card_text(cards["card1_hook"]))
        self.assertNotIn("캔바", cards["card1_hook"])

        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False):
            with mock.patch.object(rw, "_openai_complete", side_effect=RuntimeError("billing")):
                with self.assertRaises(rw.RewriteError):
                    rw.rewrite_summary_for_shorts("x", ["a", "b", "c"], "y", max_retries=1)


if __name__ == "__main__":
    unittest.main()
