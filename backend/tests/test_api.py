import json

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.service import FakeQuoteService


@pytest.fixture(autouse=True)
def _mock_mode(monkeypatch):
    monkeypatch.setenv("MOCK_LLM", "1")


@pytest.fixture
def client():
    app.state.service = FakeQuoteService()
    from app.api import main as main_mod

    main_mod.sessions.clear()
    return TestClient(app)


def _sse_events(text):
    events = []
    for line in text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_chat_emits_confirm_when_fields_complete(client):
    message = (
        "registration AB12CDE, full_name Jane Doe, date_of_birth 1990-05-01, "
        "postcode SW1A1AA, ncb_years 5"
    )
    resp = client.post("/chat", json={"session_id": "s1", "message": message})
    assert resp.status_code == 200
    events = _sse_events(resp.text)
    assert events[-1] == {"type": "done"}
    confirm = [e for e in events if e["type"] == "confirm"]
    assert len(confirm) == 1
    assert confirm[0]["data"]["vehicle"]["make"] == "Volkswagen"


def test_upload_fr_carte_grise(client):
    files = {"file": ("carte_grise.pdf", b"bytes", "application/pdf")}
    resp = client.post("/upload", data={"session_id": "s2"}, files=files)
    assert resp.status_code == 200
    body = resp.json()
    assert body["country_code"] == "FR"
    assert body["fields"]["immatriculation"] == "AB123CD"
    assert "_source" not in body["fields"]
    assert body["schema"]["currency"] == "EUR"

    from app.api import main as main_mod

    session = main_mod.sessions["s2"]
    assert session["country_code"] == "FR"
    assert session["fields"]["immatriculation"] == "AB123CD"
    assert session["schema"]["currency"] == "EUR"


def test_upload_default_gb(client):
    files = {"file": ("licence.png", b"bytes", "image/png")}
    resp = client.post("/upload", data={"session_id": "s3"}, files=files)
    assert resp.status_code == 200
    body = resp.json()
    assert body["country_code"] == "GB"
    assert body["fields"]["registration"] == "AB12CDE"
    assert "_source" not in body["fields"]


def test_confirm_returns_quote_and_handoff(client):
    # upload to populate fields, then chat to build a candidate, then confirm
    files = {"file": ("licence.png", b"bytes", "image/png")}
    client.post("/upload", data={"session_id": "s4"}, files=files)
    client.post("/chat", json={"session_id": "s4", "message": "looks good"})

    resp = client.post("/confirm", json={"session_id": "s4"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["quote"]["quote_ref"] == "Q-AB12CDE"
    assert body["handoff_url"].endswith("/handoff/fake-guid-0001")
    assert body["guid"] == "fake-guid-0001"


def test_confirm_no_candidate_returns_409(client):
    resp = client.post("/confirm", json={"session_id": "nope"})
    assert resp.status_code == 409
