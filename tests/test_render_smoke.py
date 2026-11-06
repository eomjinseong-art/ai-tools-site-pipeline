import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from full_orchestrator import make_card_image, orchestrate
from legacy_shorts_retirement import LegacyBlackCardShortsRetired


class RenderSmokeTests(unittest.TestCase):
    def test_black_card_render_is_refused(self):
        metadata = {
            "title": "스모크 테스트",
            "short_title": "카드 렌더 확인",
            "cards": [
                "반복 업무를 바로 맡기는 방법",
                "이메일 초안은 먼저 맡기세요",
                "표와 요약은 템플릿으로 고정",
                "결과는 사람이 한 번 검수하세요",
                "템플릿만 있으면 시간을 줄입니다",
            ],
        }
        with TemporaryDirectory() as tmp:
            with self.assertRaises(LegacyBlackCardShortsRetired):
                orchestrate(tmp, metadata=metadata, allow_silent_tts=True)
            with self.assertRaises(LegacyBlackCardShortsRetired):
                make_card_image("반복 업무를 바로 맡기는 방법", str(Path(tmp) / "card.png"))
            self.assertFalse((Path(tmp) / "final.mp4").exists())
            self.assertFalse((Path(tmp) / "card.png").exists())
