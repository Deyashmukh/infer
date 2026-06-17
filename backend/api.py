from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Response

from backend.models import (
    CreateSessionRequest,
    DocumentMeta,
    MfaRequest,
    SessionStatus,
    SessionStatusResponse,
)
from backend.sessions import SessionManager, SessionRegistry


def _content_disposition(disposition: str, name: str) -> str:
    """Build a Content-Disposition value safe for non-ASCII document names.

    HTTP header values are latin-1; document names can contain characters that aren't (e.g. the
    em dash in "Geico ID Card — 2009 ..."). Per RFC 6266/5987 we emit a latin-1-safe ``filename``
    fallback plus a UTF-8 ``filename*`` that modern browsers prefer.
    """
    filename = f"{name}.pdf"
    fallback = filename.encode("latin-1", "replace").decode("latin-1").replace('"', "'")
    return f"{disposition}; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


def build_router(manager: SessionManager, registry: SessionRegistry) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @router.post("/sessions", status_code=201)
    async def create_session(req: CreateSessionRequest) -> dict[str, str]:
        session = manager.start(req.carrier.value, req.username, req.password)
        return {"session_id": session.id, "status": session.status.value}

    @router.get("/sessions/{session_id}")
    async def get_session(session_id: str) -> SessionStatusResponse:
        session = registry.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="unknown session")
        docs = [
            DocumentMeta(doc_id=doc_id, name=name)
            for doc_id, (name, _content) in session.documents.items()
        ] or None
        return SessionStatusResponse(
            session_id=session.id,
            status=session.status,
            mfa_required=session.status is SessionStatus.AWAITING_MFA,
            documents=docs,
            error=session.error,
            latency_ms=session.latency_ms,
        )

    @router.post("/sessions/{session_id}/mfa")
    async def submit_mfa(session_id: str, req: MfaRequest) -> dict[str, str]:
        session = registry.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="unknown session")
        if session.status is not SessionStatus.AWAITING_MFA:
            raise HTTPException(
                status_code=409,
                detail=f"not awaiting MFA (status={session.status.value})",
            )
        # Synchronous, event-loop-atomic flip (no await before it): a concurrent
        # duplicate POST now sees VERIFYING_MFA and gets 409 — single-flight without a Lock.
        session.status = SessionStatus.VERIFYING_MFA
        manager.submit_mfa(session_id, req.code)
        return {"session_id": session_id, "status": session.status.value}

    @router.get("/sessions/{session_id}/documents/{doc_id}")
    async def get_document(session_id: str, doc_id: str, download: bool = False) -> Response:
        session = registry.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="unknown session")
        if session.status is not SessionStatus.READY:
            raise HTTPException(status_code=409, detail="session not READY")
        entry = await manager.get_document_bytes(session_id, doc_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="unknown document")
        name, content = entry
        disposition = "attachment" if download else "inline"
        return Response(
            content=content,
            media_type="application/pdf",
            headers={"Content-Disposition": _content_disposition(disposition, name)},
        )

    return router
