"""Offline tests for the pure Geico ID-card API helpers (no browser, no network)."""

from __future__ import annotations

import json

from backend.browser import DocRef
from backend.geico_idcard_api import id_card_url, parse_id_card_docs

# Mirrors the real /ws/proof-of-insurance shape: each vehicle is listed twice (as Geico does),
# vehicleId is the full 32-char token, vinSymbol carries year/make/model.
_VEH_A = {
    "vehicleId": "AAA11111111111111111111111111111",
    "vinSymbol": {"make": "LEXS", "model": "RX 350 AWD", "year": 2009},
}
_VEH_B = {
    "vehicleId": "BBB22222222222222222222222222222",
    "vinSymbol": {"make": "HONDA", "model": "CR-V", "year": 2020},
}
# Real Geico /ws/ responses are compact (no spaces) — match that so the regex fallback path
# is exercised against a realistic byte stream.
_POI_BODY = json.dumps(
    {"_payload": {"policyNumber": "X", "poiVehiclesInfo": [_VEH_A, _VEH_B, _VEH_A]}},
    separators=(",", ":"),
)


def test_parse_returns_one_docref_per_unique_vehicle() -> None:
    docs = parse_id_card_docs(_POI_BODY)
    assert [d.doc_id for d in docs] == [_VEH_A["vehicleId"], _VEH_B["vehicleId"]]
    assert all(isinstance(d, DocRef) for d in docs)


def test_parse_uses_year_make_model_in_name() -> None:
    docs = parse_id_card_docs(_POI_BODY)
    assert docs[0].name == "Geico ID Card — 2009 LEXS RX 350 AWD"
    assert docs[1].name == "Geico ID Card — 2020 HONDA CR-V"


def test_parse_dedupes_repeated_vehicles() -> None:
    # _VEH_A appears twice in the payload but must yield exactly one document.
    docs = parse_id_card_docs(_POI_BODY)
    assert len(docs) == 2


def test_parse_regex_fallback_on_truncated_json() -> None:
    # A capture cut off mid-stream (after VEH_B's id, before its vinSymbol) is still mined for
    # complete vehicle ids via regex; the dangling vinSymbol just yields numbered labels.
    cut = _POI_BODY.index(_VEH_B["vehicleId"]) + len(_VEH_B["vehicleId"]) + 1
    docs = parse_id_card_docs(_POI_BODY[:cut])
    assert [d.doc_id for d in docs] == [_VEH_A["vehicleId"], _VEH_B["vehicleId"]]
    # Without parseable vinSymbol, names fall back to a numbered label.
    assert [d.name for d in docs] == ["Geico ID Card 1", "Geico ID Card 2"]


def test_parse_empty_when_no_vehicles() -> None:
    assert parse_id_card_docs(json.dumps({"_payload": {"poiVehiclesInfo": []}})) == []


def test_id_card_url_includes_vehicle_and_token() -> None:
    url = id_card_url("VEH123", "token=abc%2Fdef")
    assert url == (
        "https://edgecustomer.geico.com/ws/view-document/id-card?vehicleId=VEH123&token=abc%2Fdef"
    )


def test_id_card_url_without_token() -> None:
    assert id_card_url("VEH123", "") == (
        "https://edgecustomer.geico.com/ws/view-document/id-card?vehicleId=VEH123"
    )
