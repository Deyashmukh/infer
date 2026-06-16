from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class LockoutError(Exception):
    """Raised when a second login attempt is requested (spec §3 safety rail)."""


class AttemptGuard:
    """Permits at most `max_attempts` password submissions, then refuses."""

    def __init__(self, max_attempts: int = 1) -> None:
        self._max = max_attempts
        self._used = 0

    def use(self) -> None:
        if self._used >= self._max:
            raise LockoutError(
                f"login attempt cap ({self._max}) reached — aborting to avoid account lockout"
            )
        self._used += 1


class GateOutcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


@dataclass(frozen=True)
class GateResult:
    outcome: GateOutcome
    reason: str


def evaluate_gate(
    form_renders_ok: int,
    completions: int,
    bot_blocked: bool,
    min_renders: int = 3,
) -> GateResult:
    """Pre-committed gate rule (spec §3): PASS = >=min_renders clean form renders
    AND >=1 full proxied completion AND not hard-blocked."""
    if bot_blocked:
        return GateResult(GateOutcome.FAIL, "hosted browser was hard-blocked at the bot gate")
    if form_renders_ok < min_renders:
        return GateResult(
            GateOutcome.FAIL,
            f"only {form_renders_ok}/{min_renders} clean form renders",
        )
    if completions < 1:
        return GateResult(
            GateOutcome.FAIL,
            "no full login->MFA->PDF completion through proxied egress",
        )
    return GateResult(GateOutcome.PASS, "reliable form renders + >=1 proxied completion")
