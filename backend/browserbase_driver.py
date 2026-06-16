from __future__ import annotations

from collections.abc import Callable

from backend.browser import BrowserDriver
from spike.config import Config


def make_browserbase_driver_factory(cfg: Config) -> Callable[[], BrowserDriver]:
    """Return a factory that builds a live BrowserbaseDriver per session.

    Stub: the real async-Playwright/Browserbase driver is implemented in the
    live-integration task. Calling the factory raises until then."""

    def factory() -> BrowserDriver:
        raise NotImplementedError("BrowserbaseDriver is implemented in the live-integration task")

    return factory
