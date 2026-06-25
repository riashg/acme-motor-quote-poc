"""Turn driver: greedy advance, conflict event, resolution, ready_to_price."""

import pytest

from app.agent import apply_resolution, collect_turn
from app.quote_session_client import FakeQuoteService

# A complete whole-model patch that satisfies every mandatory field, so a single
# turn can reach ready_to_price (stubbed extraction returns it).
_FULL_PATCH = {
    "vehicle": {
        "registration": "FX19ZTC",
        "make": "Ford",
        "model": "Focus",
        "datePurchased": {"month": 3, "year": 2019},
        "value": 12000,
        "useOfVehicle": "Social + commuting",
        "security": "Factory-fitted",
        "dashcam": True,
        "modified": False,
        "imported": "No",
        "daytimeLocation": "Drive",
        "overnightLocation": "Drive",
        "annualMileage": 8000,
        "registeredKeeper": True,
        "legalOwner": True,
    },
    "customer": {
        "title": "Mr",
        "firstName": "Sam",
        "surname": "Sample",
        "dateOfBirth": "1990-01-01",
        "maritalStatus": "Single",
        "childrenUnder16": "0",
        "employmentStatus": "Employed",
        "partTimeJob": False,
        "yearsLivedInUK": "Since birth",
        "address": {"houseNumberOrName": "1", "postcode": "RG1 1AA"},
        "ownsProperty": True,
        "carKeptOvernightAtAddress": True,
        "email": "sam@example.com",
    },
    "driver": {
        "licenceType": "Full UK",
        "licenceHeldFor": "5",
        "insuranceCancelledOrVoid": False,
        "ncdYears": 5,
        "ncdOnCompanyCar": False,
    },
    "history": {
        "claimsLast3Years": 0,
        "offencesLast5Years": 0,
        "unspentCriminalConvictions": False,
    },
    "household": {
        "carsInHousehold": "1",
        "anotherCarHasCover": False,
        "regularUseOfOtherVehicles": "None",
    },
    "cover": {
        "paymentMethod": "Single payment",
        "coverLevel": "Comprehensive",
        "coverStartDate": "2026-07-01",
        "voluntaryExcess": 250,
    },
}


def _stub_extract(patch):
    def _fn(message, asked_question=None, schema=None, client=None):
        return patch
    return _fn


async def _session(service):
    created = await service.start()
    return {
        "quoteId": created["quoteId"],
        "sessionId": created["sessionId"],
        "current": {},
        "asked_question": None,
        "pending_conflicts": [],
    }


async def _run(gen):
    return [event async for event in gen]


@pytest.mark.asyncio
async def test_greedy_multi_field_advances_missing_fields(monkeypatch):
    service = FakeQuoteService()
    session = await _session(service)
    patch = {
        "customer": {"firstName": "Sam", "surname": "Sample", "dateOfBirth": "1990-01-01"},
        "vehicle": {"annualMileage": 8000},
    }
    monkeypatch.setattr("app.agent.extract_patch", _stub_extract(patch))

    events = await _run(collect_turn("...", session, service))
    types = [e["type"] for e in events]
    assert "echo" in types
    # Three customer + one vehicle field applied; not re-asked.
    state = await service.get(session["quoteId"], session["sessionId"])
    for path in ("customer.firstName", "customer.surname", "customer.dateOfBirth", "vehicle.annualMileage"):
        assert path not in state["missingFields"]
    # Echo summarises and counts the rest.
    echo = next(e for e in events if e["type"] == "echo")
    assert echo["data"].startswith("✓")
    assert "+" in echo["data"]


@pytest.mark.asyncio
async def test_conflicting_value_raises_conflict_event(monkeypatch):
    service = FakeQuoteService()
    session = await _session(service)
    session["current"] = {"vehicle": {"annualMileage": 8000}}
    # Reflect the held value in the platform too.
    await service.update(session["quoteId"], session["sessionId"], {"vehicle": {"annualMileage": 8000}})

    monkeypatch.setattr("app.agent.extract_patch", _stub_extract({"vehicle": {"annualMileage": 18000}}))
    events = await _run(collect_turn("actually 18000", session, service))

    conflict = next(e for e in events if e["type"] == "conflict")
    assert conflict["data"]["path"] == "vehicle.annualMileage"
    assert conflict["data"]["chips"] == [8000, 18000]
    # Not applied: still 8000.
    assert session["current"]["vehicle"]["annualMileage"] == 8000
    assert session["pending_conflicts"]


@pytest.mark.asyncio
async def test_resolve_applies_chosen_value(monkeypatch):
    service = FakeQuoteService()
    session = await _session(service)
    session["current"] = {"vehicle": {"annualMileage": 8000}}
    await service.update(session["quoteId"], session["sessionId"], {"vehicle": {"annualMileage": 8000}})
    session["pending_conflicts"] = [
        {"path": "vehicle.annualMileage", "current": 8000, "proposed": 18000}
    ]

    events = await _run(apply_resolution(session, service, "vehicle.annualMileage", "18000"))
    assert session["current"]["vehicle"]["annualMileage"] == 18000
    assert session["pending_conflicts"] == []
    assert any(e["type"] == "echo" for e in events)


@pytest.mark.asyncio
async def test_resolve_unparseable_keeps_current(monkeypatch):
    service = FakeQuoteService()
    session = await _session(service)
    session["current"] = {"vehicle": {"value": 12000}}
    await service.update(session["quoteId"], session["sessionId"], {"vehicle": {"value": 12000}})
    session["pending_conflicts"] = [
        {"path": "vehicle.value", "current": 12000, "proposed": 8000}
    ]

    events = await _run(apply_resolution(session, service, "vehicle.value", "that was miles not value"))
    # Kept current — never invented 0.
    assert session["current"]["vehicle"]["value"] == 12000
    assert any(e["type"] == "text" for e in events)


@pytest.mark.asyncio
async def test_full_patch_reaches_ready_to_price(monkeypatch):
    service = FakeQuoteService()
    session = await _session(service)
    monkeypatch.setattr("app.agent.extract_patch", _stub_extract(_FULL_PATCH))

    events = await _run(collect_turn("everything at once", session, service))
    state = await service.get(session["quoteId"], session["sessionId"])
    assert state["journeyState"] == "ready_to_price"
    assert state["missingFields"] == []
    assert any("ready" in e.get("data", "") for e in events if e["type"] == "text")


@pytest.mark.asyncio
async def test_autofill_completes_in_one_turn(monkeypatch):
    # MOCK_AUTOFILL demo fast-path: even an empty extraction ("type anything")
    # reaches ready_to_price in a single turn.
    service = FakeQuoteService()
    session = await _session(service)
    monkeypatch.setattr("app.agent.extract_patch", _stub_extract({}))

    events = await _run(collect_turn("hello", session, service, autofill=True))
    state = await service.get(session["quoteId"], session["sessionId"])
    assert state["journeyState"] == "ready_to_price"
    assert state["missingFields"] == []
    assert any("ready" in e.get("data", "") for e in events if e["type"] == "text")


@pytest.mark.asyncio
async def test_autofill_preserves_typed_value(monkeypatch):
    # Gap-fill must not overwrite what the customer actually said.
    service = FakeQuoteService()
    session = await _session(service)
    monkeypatch.setattr("app.agent.extract_patch", _stub_extract({"vehicle": {"annualMileage": 15000}}))

    await _run(collect_turn("I drive 15000 miles", session, service, autofill=True))
    state = await service.get(session["quoteId"], session["sessionId"])
    assert state["journeyState"] == "ready_to_price"
    # The typed mileage stands; the sample's 8000 did not clobber it.
    assert session["current"]["vehicle"]["annualMileage"] == 15000
