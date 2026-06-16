from fastapi import FastAPI

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
    paths = set(app.openapi()["paths"].keys())
    assert "/sessions" in paths
    assert "/sessions/{session_id}" in paths
    assert "/sessions/{session_id}/mfa" in paths
    assert "/sessions/{session_id}/documents/{doc_id}" in paths
