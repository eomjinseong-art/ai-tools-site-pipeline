import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from content_queue import (
    CONSUMED_PATH,
    LOW_WATER_DAYS,
    build_queue_report,
    compute_days_left,
    load_queue,
    mark_script_consumed,
    resolve_shorts_script,
    template_cards,
    tool_card_from_mapping,
)
from rewrite_for_shorts import CARD_KEYS, MAX_CHARS, MIN_CHARS, validate_card_text


def _script(script_id: str, tool_name: str, hook: str) -> dict:
    cards = {
        "card1_hook": hook,
        "card2": "한 줄 설명을 카드에 옮겼습니다",
        "card3": "첫 번째 기능을 짧게 적었습니다",
        "card4": "두 번째 기능도 같이 확인하세요",
        "card5_takeaway": "설명란 링크에서 바로 확인하세요",
    }
    return {"id": script_id, "tool_name": tool_name, "aliases": [tool_name], "link": "https://example.com", "cards": cards}


class ContentQueueTests(unittest.TestCase):
    def test_days_left_formula_boundaries(self):
        self.assertEqual(compute_days_left(20, 1), 20)
        self.assertEqual(compute_days_left(14, 1), 14)
        self.assertEqual(compute_days_left(13, 1), 13)
        self.assertEqual(compute_days_left(27, 2), 13)
        self.assertEqual(compute_days_left(0, 1), 0)
        self.assertFalse(compute_days_left(14, 1) < LOW_WATER_DAYS)
        self.assertTrue(compute_days_left(13, 1) < LOW_WATER_DAYS)

    def test_template_uses_name_description_features_and_host(self):
        card = tool_card_from_mapping(
            {
                "tool_name": "완전새도구",
                "one_line": "완전새도구는 초안을 대신 써 줍니다",
                "key_features": [
                    "첫 기능은 초안을 바로 만듭니다",
                    "둘째 기능은 문장을 다듬습니다",
                    "셋째 기능은 결과를 저장합니다",
                ],
                "link": "https://www.example.com/tools/new",
            }
        )
        cards = template_cards(card)
        blob = " ".join(cards.values())
        self.assertIn("완전새도구", blob)
        self.assertIn("초안을 대신", cards["card2"])
        self.assertIn("첫 기능", cards["card3"])
        self.assertIn("둘째 기능", cards["card4"])
        self.assertIn("example.com", cards["card5_takeaway"])
        self.assertNotIn("http", blob)
        self.assertNotIn("셋째", blob)
        self.assertTrue(all(validate_card_text(cards[key]) for key in CARD_KEYS))

    def test_empty_card_still_renders_valid_template(self):
        cards = template_cards(tool_card_from_mapping({}))
        self.assertTrue(all(validate_card_text(cards[key]) for key in CARD_KEYS))

    def test_invalid_and_duplicate_scripts_do_not_count(self):
        payload = {
            "version": 1,
            "cadence_per_day": 1,
            "scripts": [
                _script("ok-1", "도구하나", "도구하나로 오늘 일을 줄이세요"),
                _script("ok-1", "도구둘", "도구둘로 오늘 일을 줄이세요"),
                {
                    "id": "bad-cards",
                    "tool_name": "나쁜카드",
                    "cards": {"card1_hook": "짧음"},
                },
                {"id": "no-match", "cards": _script("no-match", "없음", "매칭 키가 없는 대본은 빼세요")["cards"]},
            ],
        }
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "queue.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            queue = load_queue(path)
            report = build_queue_report(queue_file=path, consumed_paths=[])
        self.assertEqual([item["id"] for item in queue["scripts"]], ["ok-1"])
        self.assertEqual(report["days_left"], 1)
        self.assertTrue(any("duplicate" in warning for warning in report["warnings"]))
        self.assertTrue(any("invalid" in warning for warning in report["warnings"]))
        self.assertTrue(any("unmatchable" in warning for warning in report["warnings"]))

    def test_match_skips_consumed_and_template_does_not_consume(self):
        payload = {
            "cadence_per_day": 1,
            "scripts": [
                _script("short-key", "짧은", "짧은 이름으로 매칭되면 안 됩니다"),
                _script("long-key", "완전새도구 프로", "완전새도구 프로를 바로 써 보세요"),
            ],
        }
        payload["scripts"][0]["aliases"] = ["전혀다른이름"]
        with TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "queue.json"
            consumed_path = Path(tmp) / "consumed.json"
            runtime_path = Path(tmp) / "runtime.json"
            queue_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            video = {
                "tool_name": "완전새도구 프로",
                "hook": "완전새도구 프로로 초안을 만듭니다",
                "summary_points": ["기능 하나를 길게 설명하는 문장입니다"],
                "takeaway": "링크에서 바로 확인하면 됩니다",
            }
            first = resolve_shorts_script(video, queue_file=queue_path, consumed_paths=[consumed_path])
            self.assertEqual(first.source, "queue")
            self.assertEqual(first.script_id, "long-key")
            mark_script_consumed(first.script_id, [consumed_path, runtime_path])
            second = resolve_shorts_script(video, queue_file=queue_path, consumed_paths=[consumed_path, runtime_path])
            self.assertEqual(second.source, "template")
            self.assertIsNone(second.script_id)
            stored = json.loads(consumed_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["consumed_ids"], ["long-key"])
            self.assertEqual(json.loads(runtime_path.read_text(encoding="utf-8"))["consumed_ids"], ["long-key"])

    def test_force_template_ignores_queue(self):
        with TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "queue.json"
            queue_path.write_text(
                json.dumps({"scripts": [_script("chatgpt-handoff", "ChatGPT", "챗GPT에 반복 업무를 맡기세요")]}, ensure_ascii=False),
                encoding="utf-8",
            )
            resolved = resolve_shorts_script(
                {"tool_name": "ChatGPT", "hook": "챗GPT로 일을 줄이는 방법입니다"},
                queue_file=queue_path,
                consumed_paths=[],
                force_template=True,
            )
        self.assertEqual(resolved.source, "template")
        self.assertIsNone(resolved.script_id)

    def test_committed_queue_matches_formula(self):
        report = build_queue_report(consumed_paths=[CONSUMED_PATH])
        self.assertEqual(report["warnings"], [])
        self.assertEqual(report["cadence_per_day"], 1)
        self.assertEqual(report["low_water_days"], 14)
        self.assertGreaterEqual(report["valid_scripts"], 14)
        self.assertEqual(report["days_left"], report["unused_scripts"] // report["cadence_per_day"])
        queue = load_queue()
        for script in queue["scripts"]:
            for key in CARD_KEYS:
                text = script["cards"][key]
                self.assertGreaterEqual(len(text), MIN_CHARS, script["id"] + key)
                self.assertLessEqual(len(text), MAX_CHARS, script["id"] + " " + key + " " + text)
                self.assertNotIn("http", text)
            self.assertTrue(script["tool_name"])


if __name__ == "__main__":
    unittest.main()
