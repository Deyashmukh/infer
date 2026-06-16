from __future__ import annotations

from collections.abc import Callable


class Timer:
    """Latency timer with an injected clock for deterministic tests."""

    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._starts: dict[str, float] = {}
        self.durations: dict[str, float] = {}

    def start(self, label: str) -> None:
        self._starts[label] = self._clock()

    def stop(self, label: str) -> float:
        elapsed = self._clock() - self._starts[label]
        self.durations[label] = elapsed
        return elapsed

    def to_dict(self) -> dict[str, float]:
        return dict(self.durations)  # copy — callers must not mutate internal state
