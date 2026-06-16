from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from backend.models import (
    BotChallengeError,
    CarrierAuthError,
    DocFetchError,
    MfaError,
)


class AuthStep(StrEnum):
    NEEDS_MFA = "NEEDS_MFA"
    AUTHENTICATED = "AUTHENTICATED"


@dataclass(frozen=True)
class DocRef:
    doc_id: str
    name: str
    url: str


@dataclass(frozen=True)
class FetchedDoc:
    name: str
    content: bytes


class BrowserDriver(Protocol):
    async def open_login(self, login_url: str) -> None: ...
    async def submit_credentials(self, username: str, password: str) -> AuthStep: ...
    async def submit_mfa(self, code: str) -> AuthStep: ...
    async def list_documents(self) -> list[DocRef]: ...
    async def fetch_document(self, ref: DocRef) -> FetchedDoc: ...
    async def close(self) -> None: ...


_SAMPLE_PDF = b"%PDF-1.7\n" + b"0" * 2000 + b"\n%%EOF"


class FakeDriver:
    """In-memory driver for deterministic offline orchestration tests."""

    def __init__(
        self,
        *,
        bot_block: bool = False,
        auth_fail: bool = False,
        mfa_fail_times: int = 0,
        doc_fail: bool = False,
        hang_on_mfa: bool = False,
        cancel_on_mfa: bool = False,
        connection_lost_on_fetch: bool = False,
    ) -> None:
        self._bot_block = bot_block
        self._auth_fail = auth_fail
        self._mfa_fail_remaining = mfa_fail_times
        self._doc_fail = doc_fail
        self._hang_on_mfa = hang_on_mfa
        self._cancel_on_mfa = cancel_on_mfa
        self._connection_lost_on_fetch = connection_lost_on_fetch
        self.closed = False

    async def open_login(self, login_url: str) -> None:
        if self._bot_block:
            raise BotChallengeError(
                "access denied",
                fields={"kind": "AKAMAI_ACCESS_DENIED", "status": 403},
            )

    async def submit_credentials(self, username: str, password: str) -> AuthStep:
        if self._auth_fail:
            raise CarrierAuthError("credentials rejected")
        return AuthStep.NEEDS_MFA

    async def submit_mfa(self, code: str) -> AuthStep:
        if self._hang_on_mfa:
            await asyncio.sleep(3600)
        if self._cancel_on_mfa:
            raise asyncio.CancelledError()
        if self._mfa_fail_remaining > 0:
            self._mfa_fail_remaining -= 1
            raise MfaError("code rejected")
        return AuthStep.AUTHENTICATED

    async def list_documents(self) -> list[DocRef]:
        if self._doc_fail:
            raise DocFetchError("no documents found")
        return [DocRef(doc_id="doc-0", name="Declarations", url="https://lm/docs/dec.pdf")]

    async def fetch_document(self, ref: DocRef) -> FetchedDoc:
        if self._connection_lost_on_fetch:
            raise DocFetchError("connection lost")
        return FetchedDoc(name=ref.name, content=_SAMPLE_PDF)

    async def close(self) -> None:
        self.closed = True
