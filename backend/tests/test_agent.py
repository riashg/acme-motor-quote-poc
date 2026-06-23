import pytest

from app.agent import collect_turn
from app.service import FakeQuoteService


@pytest.fixture(autouse=True)
def _mock_mode(monkeypatch):
    monkeypatch.setenv("MOCK_LLM", "1")


async def _drain(message, session, service):
    events = []
    async for event in collect_turn(message, session, service):
        events.append(event)
    return events


async def test_incomplete_message_asks_for_missing():
    svc = FakeQuoteService()
    session = {"country_code": "GB", "fields": {}, "schema": {}, "history": []}
    events = await _drain("Hi, I drive AB12CDE", session, svc)
    assert events, "expected at least one event"
    assert events[-1]["type"] == "text"
    # registration was present; still missing other required fields
    assert "still need" in events[-1]["data"].lower()
    assert session["schema"]["currency"] == "GBP"


async def test_complete_gb_message_emits_confirm():
    svc = FakeQuoteService()
    session = {"country_code": "GB", "fields": {}, "schema": {}, "history": []}
    message = (
        "registration AB12CDE, full_name Jane Doe, date_of_birth 1990-05-01, "
        "postcode SW1A1AA, ncb_years 5"
    )
    events = await _drain(message, session, svc)
    confirm = [e for e in events if e["type"] == "confirm"]
    assert len(confirm) == 1
    candidate = confirm[0]["data"]
    assert candidate["vehicle"]["make"] == "Volkswagen"
    assert "found" not in candidate["vehicle"]
    assert "country_code" not in candidate["vehicle"]
    driver = candidate["driver"]
    assert driver["full_name"] == "Jane Doe"
    assert driver["date_of_birth"] == "1990-05-01"
    assert driver["postcode"] == "SW1A1AA"
    assert driver["ncb_years"] == 5
    assert candidate["cover_tier"] == "comprehensive"
    assert candidate["voluntary_excess"] == 250
    assert session["candidate"] == candidate
    # text precedes confirm
    assert events[-2]["type"] == "text"


async def test_prepopulated_fields_from_upload_emit_confirm():
    svc = FakeQuoteService()
    session = {
        "country_code": "GB",
        "fields": {
            "registration": "AB12CDE",
            "full_name": "Jane Doe",
            "date_of_birth": "1990-05-01",
            "postcode": "SW1A1AA",
            "ncb_years": 5,
        },
        "schema": {},
        "history": [],
    }
    events = await _drain("done", session, svc)
    confirm = [e for e in events if e["type"] == "confirm"]
    assert len(confirm) == 1
    assert confirm[0]["data"]["vehicle"]["make"] == "Volkswagen"


async def test_fr_session_emits_fr_candidate_shape():
    svc = FakeQuoteService()
    session = {
        "country_code": "FR",
        "fields": {
            "immatriculation": "AB123CD",
            "full_name": "Jean Dupont",
            "date_of_birth": "1985-03-10",
            "code_postal": "75001",
            "bonus_malus": 0.90,
        },
        "schema": {},
        "history": [],
    }
    events = await _drain("voila", session, svc)
    confirm = [e for e in events if e["type"] == "confirm"]
    assert len(confirm) == 1
    candidate = confirm[0]["data"]
    assert candidate["vehicle"]["make"] == "Renault"
    driver = candidate["driver"]
    assert driver["full_name"] == "Jean Dupont"
    assert driver["code_postal"] == "75001"
    assert driver["bonus_malus"] == 0.90
    assert candidate["formule"] == "tous_risques"
    assert candidate["franchise"] == 300


async def test_unknown_vehicle_asks_for_make_model_year():
    svc = FakeQuoteService()
    session = {"country_code": "GB", "fields": {}, "schema": {}, "history": []}
    message = (
        "registration ZZ99ZZZ, full_name Jane Doe, date_of_birth 1990-05-01, "
        "postcode SW1A1AA, ncb_years 5"
    )
    events = await _drain(message, session, svc)
    assert not [e for e in events if e["type"] == "confirm"]
    assert events[-1]["type"] == "text"
    assert "make" in events[-1]["data"].lower()
