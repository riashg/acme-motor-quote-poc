"""Tests for the platform HTTP client (the MCP's integration seam).

We drive httpx via a MockTransport so each method's path, headers, method, and
body are asserted exactly, and the parsed JSON is returned to the caller. The
session security contract is exercised here: X-Session-Id must be sent on get
and update, and must NOT be sent on the open lookups.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.platform_client import PlatformClient


def _client(handler) -> PlatformClient:
    transport = httpx.MockTransport(handler)
    return PlatformClient(base_url="http://platform.test", transport=transport)


def test_start_quote_posts_to_quotes_and_parses_response():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["session_header"] = request.headers.get("X-Session-Id")
        return httpx.Response(
            201,
            json={
                "quoteId": "q-1",
                "sessionId": "s-1",
                "journeyState": "quote_started",
                "missingFields": ["vehicle.registration"],
                "currentOutcome": None,
            },
        )

    result = _client(handler).start_quote()

    assert seen["method"] == "POST"
    assert seen["path"] == "/quotes"
    # No session id exists yet at creation.
    assert seen["session_header"] is None
    assert result["quoteId"] == "q-1"
    assert result["sessionId"] == "s-1"
    assert result["missingFields"] == ["vehicle.registration"]


def test_get_quote_sends_session_header_and_parses_state():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["session_header"] = request.headers.get("X-Session-Id")
        return httpx.Response(
            200,
            json={
                "quoteId": "q-1",
                "journeyState": "collecting",
                "missingFields": ["customer.dateOfBirth"],
                "currentOutcome": None,
            },
        )

    result = _client(handler).get_quote("q-1", "s-1")

    assert seen["method"] == "GET"
    assert seen["path"] == "/quotes/q-1"
    assert seen["session_header"] == "s-1"
    assert result["journeyState"] == "collecting"


def test_update_quote_patches_with_session_header_and_patch_body():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["session_header"] = request.headers.get("X-Session-Id")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "quoteId": "q-1",
                "journeyState": "ready_to_price",
                "missingFields": [],
                "currentOutcome": None,
            },
        )

    patch = {"customer": {"firstName": "Sam"}, "vehicle": {"annualMileage": 8000}}
    result = _client(handler).update_quote("q-1", "s-1", patch)

    assert seen["method"] == "PATCH"
    assert seen["path"] == "/quotes/q-1"
    assert seen["session_header"] == "s-1"
    # Platform expects the patch wrapped under a "patch" key.
    assert seen["body"] == {"patch": patch}
    assert result["missingFields"] == []


def test_lookup_vehicle_hits_vehicles_path_without_session_header():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["session_header"] = request.headers.get("X-Session-Id")
        return httpx.Response(
            200, json={"registration": "AB12CDE", "make": "Ford", "model": "Focus"}
        )

    result = _client(handler).lookup_vehicle("AB12 CDE")

    assert seen["method"] == "GET"
    assert seen["path"] == "/vehicles/AB12 CDE"
    assert seen["session_header"] is None
    assert result["make"] == "Ford"


def test_lookup_address_hits_addresses_with_postcode_query():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["postcode"] = request.url.params.get("postcode")
        seen["session_header"] = request.headers.get("X-Session-Id")
        return httpx.Response(
            200, json={"postcode": "SW1A 1AA", "candidates": [{"line1": "10 Downing St"}]}
        )

    result = _client(handler).lookup_address("SW1A 1AA")

    assert seen["path"] == "/addresses"
    assert seen["postcode"] == "SW1A 1AA"
    assert seen["session_header"] is None
    assert result["candidates"][0]["line1"] == "10 Downing St"


def test_get_quote_raises_on_404_for_session_mismatch():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Quote not found"})

    with pytest.raises(httpx.HTTPStatusError):
        _client(handler).get_quote("q-1", "wrong-session")


# --- Journey tools: price / purchase-link / issue-policy ---


def test_price_posts_to_price_path_with_session_header_and_parses_pricing():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["session_header"] = request.headers.get("X-Session-Id")
        return httpx.Response(
            200,
            json={
                "annualPremium": 612.50,
                "currency": "GBP",
                "iptIncluded": True,
                "monthly": {"deposit": 61.25, "installment": 50.11, "instalments": 11},
                "compulsoryExcess": 150,
                "voluntaryExcess": 100,
                "totalExcess": 250,
                "ncdYears": 5,
                "outcome": "quote",
                "reasons": [],
                "breakdown": [{"label": "Base", "amount": 500.0}],
            },
        )

    result = _client(handler).price("q-1", "s-1")

    assert seen["method"] == "POST"
    assert seen["path"] == "/quotes/q-1/price"
    assert seen["session_header"] == "s-1"
    assert result["annualPremium"] == 612.50
    assert result["outcome"] == "quote"


def test_price_returns_error_dict_on_422_incomplete():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={"error": "Quote incomplete", "missingFields": ["customer.dateOfBirth"]},
        )

    result = _client(handler).price("q-1", "s-1")

    assert result["error"] == "Quote incomplete"
    assert result["missingFields"] == ["customer.dateOfBirth"]


def test_price_raises_on_5xx():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(httpx.HTTPStatusError):
        _client(handler).price("q-1", "s-1")


def test_generate_purchase_link_posts_to_path_with_session_and_parses():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["session_header"] = request.headers.get("X-Session-Id")
        return httpx.Response(
            200,
            json={"purchaseToken": "tok-9", "purchaseUrl": "https://acme.test/buy/tok-9"},
        )

    result = _client(handler).generate_purchase_link("q-1", "s-1")

    assert seen["method"] == "POST"
    assert seen["path"] == "/quotes/q-1/purchase-link"
    assert seen["session_header"] == "s-1"
    assert result["purchaseToken"] == "tok-9"
    assert result["purchaseUrl"] == "https://acme.test/buy/tok-9"


def test_generate_purchase_link_returns_error_dict_on_409():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"error": "Quote is not a clean quote"})

    result = _client(handler).generate_purchase_link("q-1", "s-1")

    assert result["error"] == "Quote is not a clean quote"


def test_issue_policy_posts_to_path_with_session_and_parses():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["session_header"] = request.headers.get("X-Session-Id")
        return httpx.Response(
            200,
            json={
                "policyNumber": "POL-123",
                "status": "issued",
                "effectiveDate": "2026-07-01",
            },
        )

    result = _client(handler).issue_policy("q-1", "s-1")

    assert seen["method"] == "POST"
    assert seen["path"] == "/quotes/q-1/issue-policy"
    assert seen["session_header"] == "s-1"
    assert result["policyNumber"] == "POL-123"
    assert result["status"] == "issued"


def test_issue_policy_returns_error_dict_on_409():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"error": "Quote is not a clean quote"})

    result = _client(handler).issue_policy("q-1", "s-1")

    assert result["error"] == "Quote is not a clean quote"
