import json
import unittest

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

    def test_fit_card_strips_url_and_stays_valid(self):
        text = rw.fit_card_text("https://example.com 짧은", "설명란 링크에서 바로 확인하세요")
        self.assertTrue(rw.validate_card_text(text))
        self.assertNotIn("http", text)
        self.assertNotIn("#", text)

    def test_empty_input_still_returns_five_cards(self):
        cards = rw.rewrite_summary_for_shorts("", [], "", force_template=True)
        self.assertEqual(len(rw.cards_as_list(cards)), 5)
        self.assertTrue(all(rw.validate_card_text(item) for item in cards.values()))


if __name__ == "__main__":
    unittest.main()
