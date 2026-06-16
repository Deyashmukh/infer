from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True)
class ChallengeSignals:
    url: str
    status: int
    body_text: str
    cookies: dict[str, str]
    has_captcha: bool


class ChallengeKind(StrEnum):
    NONE = "NONE"
    AKAMAI_ACCESS_DENIED = "AKAMAI_ACCESS_DENIED"
    CAPTCHA = "CAPTCHA"
    RATE_LIMIT = "RATE_LIMIT"
    UNKNOWN_BLOCK = "UNKNOWN_BLOCK"

    def to_fields(self, signals: ChallengeSignals) -> dict[str, object]:
        """Structured failure record for RESULTS.md (spec §8)."""
        abck = signals.cookies.get("_abck")
        abck_state: str = f"_abck={abck}" if abck is not None else "<absent>"
        return {
            "kind": self.value,
            "url": signals.url,
            "status": signals.status,
            "abck_state": abck_state,
            "has_captcha": signals.has_captcha,
        }


def classify_challenge(signals: ChallengeSignals) -> ChallengeKind:
    if signals.has_captcha:
        return ChallengeKind.CAPTCHA
    if signals.status == 429:
        return ChallengeKind.RATE_LIMIT
    if "access denied" in signals.body_text.lower():
        return ChallengeKind.AKAMAI_ACCESS_DENIED
    if signals.status >= 400:
        return ChallengeKind.UNKNOWN_BLOCK
    return ChallengeKind.NONE
