from fastapi import FastAPI
from fastapi.routing import _iter_included_route_candidates  # type: ignore[attr-defined]

from backend.browser import FakeDriver
from backend.main import build_app
from backend.sessions import SessionManager, SessionRegistry


def test_build_app_returns_fastapi_with_routes():
    reg = SessionRegistry()
    mgr = SessionManager(
        registry=reg, driver_factory=lambda: FakeDriver(), login_url="x", clock=lambda: 0.0
    )
    app = build_app(manager=mgr, registry=reg)
    assert isinstance(app, FastAPI)
    # FastAPI 0.137.x stores included routers as lazy _IncludedRouter objects that
    # lack a .path attribute on app.routes directly; _iter_included_route_candidates
    # flattens them into actual route objects so we can collect paths.
    paths = {r.path for r in _iter_included_route_candidates(app.routes) if hasattr(r, "path")}
    assert "/sessions" in paths
    assert "/sessions/{session_id}" in paths
    assert "/sessions/{session_id}/mfa" in paths
    assert "/sessions/{session_id}/documents/{doc_id}" in paths
