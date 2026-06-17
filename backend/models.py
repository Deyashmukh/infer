from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, field_validator


class CarrierError(Exception):
    """Base for carrier-flow errors."""


class BotChallengeError(CarrierError):
    def __init__(self, message: str, *, fields: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.fields = fields or {}


class CarrierAuthError(CarrierError):
    """Credentials rejected."""


class MfaError(CarrierError):
    """MFA code rejected."""


class DocFetchError(CarrierError):
    """Document discovery/fetch failed."""


class SessionExpiredError(CarrierError):
    """MFA deadline elapsed, TTL sweep, or task cancelled."""


class Carrier(StrEnum):
    LIBERTY_MUTUAL = "liberty_mutual"
    GEICO = "geico"


class SessionStatus(StrEnum):
    STARTING = "STARTING"
    AWAITING_MFA = "AWAITING_MFA"
    VERIFYING_MFA = "VERIFYING_MFA"
    FETCHING = "FETCHING"
    READY = "READY"
    FAILED = "FAILED"


class ErrorInfo(BaseModel):
    type: str
    message: str
    fields: dict[str, object] | None = None

    @classmethod
    def from_exception(cls, exc: Exception) -> ErrorInfo:
        fields = getattr(exc, "fields", None) or None
        return cls(type=type(exc).__name__, message=str(exc), fields=fields)


class CreateSessionRequest(BaseModel):
    carrier: Carrier
    username: str
    password: str

    @field_validator("username", "password")
    @classmethod
    def _nonempty(cls, v: str) -> str:
        if not v:
            raise ValueError("must not be empty")
        return v


class MfaRequest(BaseModel):
    code: str

    @field_validator("code")
    @classmethod
    def _nonempty(cls, v: str) -> str:
        if not v:
            raise ValueError("code must not be empty")
        return v


class DocumentMeta(BaseModel):
    doc_id: str
    name: str


class SessionStatusResponse(BaseModel):
    session_id: str
    status: SessionStatus
    mfa_required: bool
    documents: list[DocumentMeta] | None = None
    error: ErrorInfo | None = None
    latency_ms: float | None = None
