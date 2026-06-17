"""Session orchestration: lifecycle management and session-reuse cache.

SessionCache is in-memory only, TTL-evicted, and keyed by (carrier, username).
It is single-user-scoped (the account owner re-running) — not multi-tenant-safe —
and cached tokens never touch disk.
"""

from __future__ import annotations

import asyncio
import logging
import time as _time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from backend.browser import AuthStep, BrowserDriver, DocRef
from backend.models import (
    CarrierError,
    DocFetchError,
    ErrorInfo,
    MfaError,
    SessionExpiredError,
    SessionStatus,
)

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_TTL = 600.0  # seconds


class SessionCache:
    """In-memory store of browser storage states keyed by (carrier, username).

    Entries expire after *ttl* seconds (default 600 s).  The cache is
    single-user-scoped — suitable for the account owner re-running — and is
    never written to disk.
    """

    def __init__(
        self,
        clock: Callable[[], float] = _time.monotonic,
        ttl: float = _DEFAULT_CACHE_TTL,
    ) -> None:
        self._clock = clock
        self._ttl = ttl
        self._store: dict[tuple[str, str], tuple[dict[str, Any], float]] = {}

    def get(self, carrier: str, username: str) -> dict[str, Any] | None:
        """Return a cached storage state if present and not expired, else None."""
        entry = self._store.get((carrier, username))
        if entry is None:
            return None
        state, saved_at = entry
        if self._clock() - saved_at >= self._ttl:
            del self._store[(carrier, username)]
            return None
        return state

    def put(self, carrier: str, username: str, state: dict[str, Any]) -> None:
        """Store *state* for *(carrier, username)*, overwriting any previous entry."""
        self._store[(carrier, username)] = (state, self._clock())


@dataclass
class Session:
    id: str
    carrier: str = ""
    status: SessionStatus = SessionStatus.STARTING
    mfa_codes: asyncio.Queue[str] = field(default_factory=asyncio.Queue)
    mfa_attempts: int = 0
    doc_refs: list[DocRef] = field(default_factory=list)
    documents: dict[str, tuple[str, bytes]] = field(default_factory=dict)  # doc_id -> (name, bytes)
    error: ErrorInfo | None = None
    latency_ms: float | None = None
    task: asyncio.Task[None] | None = None
    created_monotonic: float = 0.0
    mfa_start: float = 0.0  # set on the /mfa request path; start of latency window


class SessionRegistry:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create(self) -> Session:
        sid = uuid.uuid4().hex
        session = Session(id=sid)
        self._sessions[sid] = session
        return session

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def remove(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def all(self) -> list[Session]:
        return list(self._sessions.values())


class SessionManager:
    def __init__(
        self,
        registry: SessionRegistry,
        driver_factory: Callable[[str], BrowserDriver],
        login_urls: Mapping[str, str],
        clock: Callable[[], float],
        mfa_deadline: float = 120.0,
        max_mfa_attempts: int = 3,
        cache: SessionCache | None = None,
    ) -> None:
        self._registry = registry
        self._driver_factory = driver_factory
        self._login_urls = login_urls
        self._clock = clock
        self._mfa_deadline = mfa_deadline
        self._max_mfa_attempts = max_mfa_attempts
        self._cache = cache or SessionCache(clock=clock)

    def start(self, carrier: str, username: str, password: str) -> Session:
        session = self._registry.create()
        session.carrier = carrier
        session.created_monotonic = self._clock()
        session.task = asyncio.create_task(self._run(session, username, password))
        return session

    async def sweep(self, now: float, ttl: float) -> None:
        """Cancel + close + evict sessions older than ttl. Best-effort cleanup."""
        for session in self._registry.all():
            if now - session.created_monotonic >= ttl:
                task = session.task
                if task is not None and not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        # The child honored our cancel() -> expected, swallow.
                        # But if WE were cancelled (e.g. app shutdown), propagate.
                        current = asyncio.current_task()
                        if current is not None and current.cancelling() > 0:
                            raise
                    except Exception:
                        logger.exception(
                            "sweep: unexpected error awaiting cancelled session %s", session.id
                        )
                self._registry.remove(session.id)

    async def get_document_bytes(self, session_id: str, doc_id: str) -> tuple[str, bytes] | None:
        session = self._registry.get(session_id)
        if session is None:
            return None
        return session.documents.get(doc_id)

    def submit_mfa(self, session_id: str, code: str) -> None:
        session = self._registry.get(session_id)
        if session is not None:
            if session.mfa_start == 0.0:
                session.mfa_start = self._clock()
            session.mfa_codes.put_nowait(code)

    async def _run(self, session: Session, username: str, password: str) -> None:
        driver = self._driver_factory(session.carrier)
        try:
            # --- session-reuse fast path ---
            cached_state = self._cache.get(session.carrier, username)
            if cached_state is not None and await driver.try_resume(cached_state):
                # Cached session is still live: skip login + MFA entirely.
                session.mfa_start = self._clock()
                session.status = SessionStatus.FETCHING
            else:
                # Normal login flow (also used when try_resume returns False).
                await driver.open_login(self._login_urls[session.carrier])
                step = await driver.submit_credentials(username, password)
                while step is AuthStep.NEEDS_MFA:
                    session.status = SessionStatus.AWAITING_MFA
                    code = await asyncio.wait_for(
                        session.mfa_codes.get(), timeout=self._mfa_deadline
                    )
                    session.status = SessionStatus.VERIFYING_MFA
                    if session.mfa_start == 0.0:  # fallback if API path hasn't set it yet
                        session.mfa_start = self._clock()
                    session.mfa_attempts += 1
                    try:
                        step = await driver.submit_mfa(code)
                    except MfaError:
                        if session.mfa_attempts >= self._max_mfa_attempts:
                            raise
                        step = AuthStep.NEEDS_MFA
                # Authenticated: persist the storage state for future runs.
                self._cache.put(session.carrier, username, await driver.storage_state())
                session.status = SessionStatus.FETCHING

            refs = await driver.list_documents()
            if not refs:
                raise DocFetchError("no documents found")
            # One document per carrier (user requirement): fetching extras adds wall-clock time
            # and risks a flaky doc failing the whole session, without improving the measured
            # MFA->first-doc latency. So serve only the first.
            ref = refs[0]
            session.doc_refs = [ref]
            fetched = await driver.fetch_document(ref)
            session.documents[ref.doc_id] = (fetched.name, fetched.content)
            session.latency_ms = (self._clock() - session.mfa_start) * 1000.0
            session.status = SessionStatus.READY
            # browser closes in `finally` after the single doc is fetched
        except TimeoutError:
            session.error = ErrorInfo.from_exception(SessionExpiredError("MFA deadline elapsed"))
            session.status = SessionStatus.FAILED
        except asyncio.CancelledError:
            session.error = ErrorInfo.from_exception(SessionExpiredError("session cancelled"))
            session.status = SessionStatus.FAILED
            raise
        except CarrierError as exc:
            session.error = ErrorInfo.from_exception(exc)
            session.status = SessionStatus.FAILED
        finally:
            await driver.close()
