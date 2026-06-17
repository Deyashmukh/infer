from backend.models import SessionStatus
from backend.sessions import Session, SessionRegistry


def test_registry_create_and_get():
    reg = SessionRegistry()
    s = reg.create()
    assert isinstance(s, Session)
    assert reg.get(s.id) is s
    assert s.status is SessionStatus.STARTING


def test_registry_get_unknown_returns_none():
    assert SessionRegistry().get("nope") is None


def test_registry_ids_are_unique():
    reg = SessionRegistry()
    ids = {reg.create().id for _ in range(50)}
    assert len(ids) == 50


def test_session_stores_documents_bytes():
    reg = SessionRegistry()
    s = reg.create()
    s.documents["doc-0"] = ("Declarations", b"%PDF-1.7 ...")
    name, content = s.documents["doc-0"]
    assert name == "Declarations" and content.startswith(b"%PDF")
