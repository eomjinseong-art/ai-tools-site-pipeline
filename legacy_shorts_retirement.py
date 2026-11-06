"""Fail-closed retirement of the legacy black-card YouTube Shorts path.

The beige/pastel 9-card carousel is a different pipeline and is not this module.
There is no environment variable, privacy flag, or workflow switch that turns
black-card generation or upload back on. Reactivation requires an explicit new
design permission and a code change.
"""

from __future__ import annotations

RETIREMENT_EXIT_CODE = 2

RETIREMENT_REASON = (
    "Legacy black-card Shorts are retired (레거시 검정 카드 쇼츠는 중단됨). "
    "This path must not generate or upload videos: it drew generic black/white cards "
    "watermarked '나두 AI 요약' and published them as public YouTube Shorts. "
    "Schedule, workflow_dispatch, manual commands, and template fallbacks cannot turn it back on. "
    "The beige/pastel 9-card carousel is a separate pipeline and is not modified here. "
    "Reactivation requires explicit new design permission and a new code change. "
    "No environment variable or privacy setting re-enables this path."
)


class LegacyBlackCardShortsRetired(RuntimeError):
    """Raised when retired black-card generation or upload is attempted."""


def refuse_legacy_black_card_shorts(action: str) -> None:
    action_text = (action or "Legacy black-card Shorts").strip()
    raise LegacyBlackCardShortsRetired(f"{action_text} refused. {RETIREMENT_REASON}")
