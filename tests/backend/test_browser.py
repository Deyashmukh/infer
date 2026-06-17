import dataclasses

from backend.browser import DocRef


def test_docref_fields():
    assert {f.name for f in dataclasses.fields(DocRef)} == {"doc_id", "name"}
