from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.types import Lifespan

from backend.api import build_router
from backend.chromium_driver import make_chromium_driver_factory
from backend.sessions import SessionCache, SessionManager, SessionRegistry
from spike.config import load_config

# Allowed browser origins for CORS. Comma-separated; defaults to both common Vite dev ports
# (5173, and 5174 which Vite falls back to when 5173 is taken). Resolved at app-build time so a
# FRONTEND_ORIGIN set in .env (loaded by build_production_app) is honored.
_DEFAULT_FRONTEND_ORIGINS = "http://localhost:5173,http://localhost:5174"
SESSION_TTL_SECONDS = 900.0
SWEEP_INTERVAL_SECONDS = 60.0


def _frontend_origins() -> list[str]:
    raw = os.environ.get("FRONTEND_ORIGIN", _DEFAULT_FRONTEND_ORIGINS)
    return [o.strip() for o in raw.split(",") if o.strip()]


def _configure_logging() -> None:
    """Emit app (backend.*) INFO logs — e.g. the [geico] timing breakdown — to stdout.

    uvicorn only attaches handlers to its own loggers, so without this the app's INFO logs are
    swallowed. Isolated to the "backend" logger (propagate=False) to avoid double-printing
    uvicorn's access lines.
    """
    log = logging.getLogger("backend")
    log.setLevel(logging.INFO)
    if not log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:    %(name)s - %(message)s"))
        log.addHandler(handler)
        log.propagate = False


def build_app(
    manager: SessionManager,
    registry: SessionRegistry,
    lifespan: Lifespan[FastAPI] | None = None,
    frontend_dist: Path | None = None,
) -> FastAPI:
    app = FastAPI(title="infer — LM policy fetcher", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_frontend_origins(),
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(build_router(manager, registry))
    # Serve the built React SPA (if present) at / — the API routes above are registered
    # first, so /health, /sessions, … still resolve to the API; everything else falls
    # through to the static bundle. The dist dir exists only in the built image, so this
    # is a no-op in dev/tests (where the frontend runs via Vite on its own port).
    dist = frontend_dist or (Path(__file__).resolve().parent.parent / "frontend" / "dist")
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")
    return app


async def _sweep_loop(manager: SessionManager) -> None:
    while True:
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
        await manager.sweep(now=time.monotonic(), ttl=SESSION_TTL_SECONDS)


def build_production_app() -> FastAPI:
    """Wire the real Chromium driver + monotonic clock + background sweeper.

    Exercised live (needs real env + a running browser), not in the offline suite."""
    # Dev convenience: load .env if present so `uvicorn --factory ...` works without
    # sourcing it first. override=False — real environment vars win in prod, and a
    # missing .env (e.g. in the container, where vars are injected) is a silent no-op.
    load_dotenv(override=False)
    _configure_logging()
    registry = SessionRegistry()
    cfg = load_config(os.environ)
    login_urls: dict[str, str] = {"liberty_mutual": cfg.lm_login_url}
    if cfg.geico_login_url is not None:
        login_urls["geico"] = cfg.geico_login_url
    manager = SessionManager(
        registry=registry,
        driver_factory=make_chromium_driver_factory(cfg),
        login_urls=login_urls,
        clock=time.monotonic,
        # Generous window to receive the SMS + enter it; does NOT affect the graded latency,
        # which is measured from MFA-submit onward.
        mfa_deadline=300.0,
        cache=SessionCache(clock=time.monotonic),
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        sweeper = asyncio.create_task(_sweep_loop(manager))
        try:
            yield
        finally:
            sweeper.cancel()
            with suppress(asyncio.CancelledError):
                await sweeper

    return build_app(manager, registry, lifespan=lifespan)
