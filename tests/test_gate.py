import pytest

from spike.gate import (
    AttemptGuard,
    GateOutcome,
    LockoutError,
    evaluate_gate,
)


def test_attempt_guard_allows_one_then_blocks():
    guard = AttemptGuard(max_attempts=1)
    guard.use()  # ok
    with pytest.raises(LockoutError):
        guard.use()


def test_gate_pass_requires_renders_and_completion():
    r = evaluate_gate(form_renders_ok=3, completions=1, bot_blocked=False)
    assert r.outcome is GateOutcome.PASS


def test_gate_fail_when_bot_blocked():
    r = evaluate_gate(form_renders_ok=3, completions=1, bot_blocked=True)
    assert r.outcome is GateOutcome.FAIL
    assert "block" in r.reason.lower()


def test_gate_fail_without_enough_renders():
    r = evaluate_gate(form_renders_ok=2, completions=1, bot_blocked=False)
    assert r.outcome is GateOutcome.FAIL


def test_gate_fail_without_completion():
    r = evaluate_gate(form_renders_ok=3, completions=0, bot_blocked=False)
    assert r.outcome is GateOutcome.FAIL
