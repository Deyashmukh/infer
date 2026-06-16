from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field

from backend.browser import DocRef
from backend.models import ErrorInfo, SessionStatus


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
    mfa_start: float = 0.0  # set on the /mfa request path (later task); used for latency


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
