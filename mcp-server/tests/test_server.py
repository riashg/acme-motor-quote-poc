"""Tests for the MCP tool functions.

Tools are stateless thin wrappers: they forward to the module-level platform
client and return its parsed dict unchanged. We monkeypatch that client with a
fake and assert each tool delegates correctly — in particular that the session
id flows through get/update.
"""

from __future__ import annotations

import pytest

from app import server


class FakePlatformClient:
    def __init__(self):
        self.calls = []

    def start_quote(self):
        self.calls.append(("start_quote",))
        return {
            "quoteId": "q-1",
            "sessionId": "s-1",
            "journeyState": "quote_started",
            "missingFields": ["vehicle.registration"],
            "currentOutcome": None,
        }

    def get_quote(self, quote_id, session_id):
        self.calls.append(("get_quote", quote_id, session_id))
        return {"quoteId": quote_id, "journeyState": "collecting", "missingFields": []}

    def update_quote(self, quote_id, session_id, patch):
        self.calls.append(("update_quote", quote_id, session_id, patch))
        return {"quoteId": quote_id, "journeyState": "ready_to_price", "missingFields": []}

    def lookup_vehicle(self, registration):
        self.calls.append(("lookup_vehicle", registration))
        return {"registration": registration, "make": "Ford", "model": "Focus"}

    def lookup_address(self, postcode):
        self.calls.append(("lookup_address", postcode))
        return {"postcode": postcode, "candidates": [{"line1": "10 Downing St"}]}

    def price(self, quote_id, session_id):
        self.calls.append(("price", quote_id, session_id))
        return {"annualPremium": 612.50, "currency": "GBP", "outcome": "quote", "reasons": []}

    def generate_purchase_link(self, quote_id, session_id):
        self.calls.append(("generate_purchase_link", quote_id, session_id))
        return {"purchaseToken": "tok-9", "purchaseUrl": "https://acme.test/buy/tok-9"}

    def issue_policy(self, quote_id, session_id):
        self.calls.append(("issue_policy", quote_id, session_id))
        return {"policyNumber": "POL-123", "status": "issued", "effectiveDate": "2026-07-01"}


@pytest.fixture
def fake(monkeypatch):
    client = FakePlatformClient()
    monkeypatch.setattr(server, "_platform", client)
    return client


def test_start_motor_quote_returns_creation_state(fake):
    result = server.start_motor_quote()
    assert result["quoteId"] == "q-1"
    assert result["sessionId"] == "s-1"
    assert result["journeyState"] == "quote_started"
    assert fake.calls == [("start_quote",)]


def test_get_motor_quote_forwards_session_id(fake):
    result = server.get_motor_quote("q-1", "s-1")
    assert result["journeyState"] == "collecting"
    assert fake.calls == [("get_quote", "q-1", "s-1")]


def test_update_motor_quote_forwards_session_id_and_patch(fake):
    patch = {"customer": {"firstName": "Sam"}, "vehicle": {"annualMileage": 8000}}
    result = server.update_motor_quote("q-1", "s-1", patch)
    assert result["journeyState"] == "ready_to_price"
    assert fake.calls == [("update_quote", "q-1", "s-1", patch)]


def test_lookup_vehicle_delegates(fake):
    result = server.lookup_vehicle("AB12 CDE")
    assert result["make"] == "Ford"
    assert fake.calls == [("lookup_vehicle", "AB12 CDE")]


def test_lookup_address_delegates(fake):
    result = server.lookup_address("SW1A 1AA")
    assert result["candidates"][0]["line1"] == "10 Downing St"
    assert fake.calls == [("lookup_address", "SW1A 1AA")]


def test_price_motor_quote_forwards_session_id(fake):
    result = server.price_motor_quote("q-1", "s-1")
    assert result["outcome"] == "quote"
    assert fake.calls == [("price", "q-1", "s-1")]


def test_generate_purchase_link_forwards_session_id(fake):
    result = server.generate_purchase_link("q-1", "s-1")
    assert result["purchaseUrl"] == "https://acme.test/buy/tok-9"
    assert fake.calls == [("generate_purchase_link", "q-1", "s-1")]


def test_issue_policy_forwards_session_id(fake):
    result = server.issue_policy("q-1", "s-1")
    assert result["policyNumber"] == "POL-123"
    assert fake.calls == [("issue_policy", "q-1", "s-1")]


def test_tools_are_registered_with_expected_annotations():
    tools = {t.name: t for t in server.mcp._tool_manager.list_tools()}
    expected = {
        "start_motor_quote",
        "get_motor_quote",
        "update_motor_quote",
        "lookup_vehicle",
        "lookup_address",
        "price_motor_quote",
        "generate_purchase_link",
        "issue_policy",
    }
    assert expected <= set(tools)

    # read-only hints per the brief.
    assert tools["get_motor_quote"].annotations.readOnlyHint is True
    assert tools["lookup_vehicle"].annotations.readOnlyHint is True
    assert tools["lookup_address"].annotations.readOnlyHint is True
    # state-changing tools are not read-only.
    assert tools["start_motor_quote"].annotations.readOnlyHint is False
    assert tools["update_motor_quote"].annotations.readOnlyHint is False
    # open-world lookups + creation reach external/world state.
    assert tools["lookup_vehicle"].annotations.openWorldHint is True
    assert tools["lookup_address"].annotations.openWorldHint is True
    assert tools["start_motor_quote"].annotations.openWorldHint is True

    # journey tools change state, reach the platform/world, and are not read-only.
    assert tools["price_motor_quote"].annotations.readOnlyHint is False
    assert tools["price_motor_quote"].annotations.openWorldHint is True
    assert tools["generate_purchase_link"].annotations.readOnlyHint is False
    assert tools["generate_purchase_link"].annotations.openWorldHint is True
    assert tools["issue_policy"].annotations.readOnlyHint is False
    assert tools["issue_policy"].annotations.openWorldHint is True
    # issuing a policy is not idempotent.
    assert tools["issue_policy"].annotations.idempotentHint is False
