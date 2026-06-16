from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import Lifespan

from backend.api import build_router
from backend.browserbase_driver import make_browserbase_driver_factory
from backend.sessions import SessionManager, SessionRegistry
from spike.config import load_config

FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173")
SESSION_TTL_SECONDS = 900.0
SWEEP_INTERVAL_SECONDS = 60.0


def build_app(
    manager: SessionManager,
    registry: SessionRegistry,
    lifespan: Lifespan[FastAPI] | None = None,
) -> FastAPI:
    app = FastAPI(title="infer — LM policy fetcher", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[FRONTEND_ORIGIN],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(build_router(manager, registry))
    return app


async def _sweep_loop(manager: SessionManager) -> None:
    while True:
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
        await manager.sweep(now=time.monotonic(), ttl=SESSION_TTL_SECONDS)


def build_production_app() -> FastAPI:
    """Wire the real Browserbase driver + monotonic clock + background sweeper.

    Exercised live (needs real env + a paid browser), not in the offline suite."""
    registry = SessionRegistry()
    cfg = load_config(os.environ)
    manager = SessionManager(
        registry=registry,
        driver_factory=make_browserbase_driver_factory(cfg),
        login_url=cfg.lm_login_url,
        clock=time.monotonic,
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
