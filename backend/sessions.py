from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

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


@dataclass
class Session:
    id: str
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
        driver_factory: Callable[[], BrowserDriver],
        login_url: str,
        clock: Callable[[], float],
        mfa_deadline: float = 120.0,
        max_mfa_attempts: int = 3,
    ) -> None:
        self._registry = registry
        self._driver_factory = driver_factory
        self._login_url = login_url
        self._clock = clock
        self._mfa_deadline = mfa_deadline
        self._max_mfa_attempts = max_mfa_attempts

    def start(self, username: str, password: str) -> Session:
        session = self._registry.create()
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
        driver = self._driver_factory()
        try:
            await driver.open_login(self._login_url)
            step = await driver.submit_credentials(username, password)
            while step is AuthStep.NEEDS_MFA:
                session.status = SessionStatus.AWAITING_MFA
                code = await asyncio.wait_for(session.mfa_codes.get(), timeout=self._mfa_deadline)
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
            session.status = SessionStatus.FETCHING
            refs = await driver.list_documents()
            if not refs:
                raise DocFetchError("no documents found")
            session.doc_refs = refs
            for i, ref in enumerate(refs):
                fetched = await driver.fetch_document(ref)
                session.documents[ref.doc_id] = (fetched.name, fetched.content)
                if i == 0:
                    session.latency_ms = (self._clock() - session.mfa_start) * 1000.0
                    session.status = SessionStatus.READY  # servable after the first doc
            # browser closes in `finally` after the last doc is fetched
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
