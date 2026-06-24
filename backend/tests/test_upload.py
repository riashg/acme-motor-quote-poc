"""POST /upload — document-assisted extraction endpoint (brief §4.4, §4.5, §13).

Multipart (session_id, file, optional message=instruction) → extract a partial
whole-model patch → reconcile against the current quote → apply non-conflicting
via update, queue genuine conflicts (resolved via the existing /resolve) → return
{extracted, applied, conflicts, echo, missingFields, journeyState}. A named-driver
instruction appends to namedDrivers[] instead of touching the applicant.
"""

import pytest
from fastapi.testclient import TestClient

from app import main
from app.quote_session_client import FakeQuoteService


@pytest.fixture
def client(monkeypatch):
    main.sessions.clear()
    main.app.state.service = FakeQuoteService()
    monkeypatch.setenv("MOCK_LLM", "1")
    return TestClient(main.app)


def _start(client):
    return client.post("/start").json()["session_id"]


def test_upload_unknown_session_404(client):
    resp = client.post(
        "/upload",
        data={"session_id": "nope"},
        files={"file": ("uk-renewal-notice.pdf", b"%PDF", "application/pdf")},
    )
    assert resp.status_code == 404


def test_upload_renewal_applies_fields(client):
    sid = _start(client)
    resp = client.post(
        "/upload",
        data={"session_id": sid},
        files={"file": ("uk-renewal-notice.pdf", b"%PDF renewal", "application/pdf")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "vehicle.registration" in body["extracted"]
    assert "vehicle.registration" in body["applied"]
    assert body["conflicts"] == []
    assert body["echo"]
    assert isinstance(body["missingFields"], list)
    assert body["journeyState"]
    # Persisted into the backend session's merged copy.
    assert main.sessions[sid]["current"]["vehicle"]["registration"] == "FX19ZTC"


def test_upload_licence_image_applies_identity(client):
    sid = _start(client)
    resp = client.post(
        "/upload",
        data={"session_id": sid},
        files={"file": ("uk-driving-licence.png", b"\x89PNG", "image/png")},
    )
    body = resp.json()
    assert "customer.firstName" in body["applied"]
    assert main.sessions[sid]["current"]["customer"]["firstName"] == "Sam"


def _seed(client, sid, patch):
    """Seed a held value into the quote via an extraction-stubbed /chat turn."""
    import json as _json

    from app import agent

    orig = agent.extract_patch
    agent.extract_patch = lambda *a, **k: patch
    try:
        client.post("/chat", json={"session_id": sid, "message": "seed"})
    finally:
        agent.extract_patch = orig


def test_upload_matching_value_no_conflict(client):
    sid = _start(client)
    # Hold the SAME registration the renewal doc carries.
    _seed(client, sid, {"vehicle": {"registration": "FX19ZTC"}})
    resp = client.post(
        "/upload",
        data={"session_id": sid},
        files={"file": ("uk-renewal-notice.pdf", b"%PDF", "application/pdf")},
    )
    body = resp.json()
    # Same FX19ZTC value held — no conflict.
    assert body["conflicts"] == []


def test_upload_conflicting_value_is_queued(client):
    sid = _start(client)
    # Hold a differing registration.
    _seed(client, sid, {"vehicle": {"registration": "AB12CDE"}})

    resp = client.post(
        "/upload",
        data={"session_id": sid},
        files={"file": ("uk-renewal-notice.pdf", b"%PDF", "application/pdf")},
    )
    body = resp.json()
    paths = [c["path"] for c in body["conflicts"]]
    assert "vehicle.registration" in paths
    # NOT overwritten — held value preserved.
    assert main.sessions[sid]["current"]["vehicle"]["registration"] == "AB12CDE"
    # And resolvable via the existing /resolve.
    resolve = client.post(
        "/resolve",
        json={"session_id": sid, "path": "vehicle.registration", "value": "FX19ZTC"},
    )
    assert resolve.status_code == 200
    assert main.sessions[sid]["current"]["vehicle"]["registration"] == "FX19ZTC"


def test_upload_named_driver_instruction_appends(client):
    sid = _start(client)
    resp = client.post(
        "/upload",
        data={"session_id": sid, "message": "add this as a named driver"},
        files={"file": ("uk-driving-licence.png", b"\x89PNG", "image/png")},
    )
    body = resp.json()
    assert body["target"] == "named_driver"
    named = main.sessions[sid]["current"].get("namedDrivers", [])
    assert len(named) == 1
    assert named[0]["firstName"] == "Sam"
    # Applicant untouched (no customer identity written).
    assert "customer" not in main.sessions[sid]["current"]


def test_upload_named_driver_appends_second(client):
    sid = _start(client)
    for _ in range(2):
        client.post(
            "/upload",
            data={"session_id": sid, "message": "add as a named driver"},
            files={"file": ("uk-driving-licence.png", b"\x89PNG", "image/png")},
        )
    assert len(main.sessions[sid]["current"]["namedDrivers"]) == 2
