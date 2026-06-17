from pathlib import Path

from fastapi.testclient import TestClient

from backend.browser import FakeDriver
from backend.main import build_app
from backend.sessions import SessionManager, SessionRegistry


def _app(frontend_dist: Path | None):
    reg = SessionRegistry()
    mgr = SessionManager(
        registry=reg,
        driver_factory=lambda carrier: FakeDriver(),
        login_urls={"liberty_mutual": "x"},
        clock=lambda: 0.0,
    )
    return build_app(manager=mgr, registry=reg, frontend_dist=frontend_dist)


def test_serves_spa_at_root_when_dist_present(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html><body>infer SPA</body></html>")
    client = TestClient(_app(dist))

    # API routes keep precedence over the static mount...
    assert client.get("/health").json() == {"status": "ok"}
    # ...and the SPA is served at the root.
    root = client.get("/")
    assert root.status_code == 200
    assert "infer SPA" in root.text


def test_no_spa_mount_when_dist_absent(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path / "does-not-exist"))
    assert client.get("/health").json() == {"status": "ok"}
    # Nothing mounted at "/" → root is a 404 (API still fine).
    assert client.get("/").status_code == 404
