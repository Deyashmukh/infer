from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from backend.models import (
    CreateSessionRequest,
    DocumentMeta,
    MfaRequest,
    SessionStatus,
    SessionStatusResponse,
)
from backend.sessions import SessionManager, SessionRegistry


def build_router(manager: SessionManager, registry: SessionRegistry) -> APIRouter:
    router = APIRouter()

    @router.post("/sessions", status_code=201)
    async def create_session(req: CreateSessionRequest) -> dict[str, str]:
        session = manager.start(req.username, req.password)
        return {"session_id": session.id, "status": session.status.value}

    @router.get("/sessions/{session_id}")
    async def get_session(session_id: str) -> SessionStatusResponse:
        session = registry.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="unknown session")
        docs = (
            [DocumentMeta(doc_id=r.doc_id, name=r.name) for r in session.doc_refs]
            if session.status is SessionStatus.READY
            else None
        )
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
            headers={"Content-Disposition": f'{disposition}; filename="{name}.pdf"'},
        )

    return router
