"""Pure helpers for Geico's Proof-of-Insurance ID-card API (no browser, no IO).

Geico's post-login portal is a Flutter canvas, but its data is served by JSON ``/ws/``
endpoints. The ID-card PDFs live on ``edgecustomer.geico.com`` and authenticate off the
session ``token`` carried as a URL query param plus a per-vehicle id. These helpers turn the
``/ws/proof-of-insurance`` payload into document refs and build the id-card endpoint URL —
isolated here so they can be unit-tested offline, away from the live browser steps.
"""

from __future__ import annotations

import json
import re

from backend.browser import DocRef

_EDGE = "https://edgecustomer.geico.com"
_VEHICLE_ID_RE = re.compile(r'"vehicleId":\s*"([^"]+)"')


def parse_id_card_docs(proof_of_insurance_body: str) -> list[DocRef]:
    """Turn a ``/ws/proof-of-insurance`` JSON body into one DocRef per insured vehicle.

    ``doc_id`` is the full vehicleId token (used to fetch the card); ``name`` is a human label
    built from the vehicle's year/make/model. Each vehicle is deduped (the payload lists every
    vehicle twice). Falls back to a regex scan if the JSON is malformed or truncated, so a
    partial capture still yields the vehicle ids.
    """
    vehicles: list[tuple[str, str]] = []
    try:
        payload = json.loads(proof_of_insurance_body)["_payload"]
        for v in payload.get("poiVehiclesInfo", []):
            vid = v.get("vehicleId")
            if not vid:
                continue
            vin = v.get("vinSymbol") or {}
            label = " ".join(
                str(p) for p in (vin.get("year"), vin.get("make"), vin.get("model")) if p
            )
            vehicles.append((vid, label))
    except (ValueError, TypeError, KeyError, AttributeError):
        vehicles = [(vid, "") for vid in _VEHICLE_ID_RE.findall(proof_of_insurance_body)]

    # Dedupe by vehicleId, preserving first-seen order.
    seen: dict[str, str] = {}
    for vid, label in vehicles:
        seen.setdefault(vid, label)
    return [
        DocRef(doc_id=vid, name=f"Geico ID Card — {label}" if label else f"Geico ID Card {i + 1}")
        for i, (vid, label) in enumerate(seen.items())
    ]


def id_card_url(vehicle_id: str, token_query: str) -> str:
    """Build the edgecustomer id-card PDF endpoint for *vehicle_id*.

    *token_query* is the raw query string (``token=...``) lifted from the post-login dashboard
    URL; the endpoint authenticates off that token.
    """
    suffix = f"&{token_query}" if token_query else ""
    return f"{_EDGE}/ws/view-document/id-card?vehicleId={vehicle_id}{suffix}"
