"""QuoteService — the conversation backend's seam onto the platform/MCP.

The conversation layer owns conversation only; **the backend owns the journey**
(brief §6 invariant). It never prices or validates — it asks the platform what is
still ``missing`` and what the ``journeyState`` is, and drives the conversation
from that.

Two implementations behind one ``QuoteService`` Protocol:

* ``PlatformQuoteService`` — an HTTP client straight to the mock platform
  (``PLATFORM_URL``, default ``http://localhost:8070``). This is the path used in
  production wiring's place for determinism; the MCP server is the production
  integration layer and an MCP-backed adapter could implement the same Protocol.
* ``FakeQuoteService`` — an in-process fake that mirrors the platform's
  deep-merge + ``missingFields`` + ``journeyState`` behaviour exactly, so tests
  and offline runs need no network and no running platform.

Front-end-agnostic: nothing here assumes web vs ChatGPT — this is one
conversation adapter onto the same platform contract.
"""

from __future__ import annotations

import os
import secrets
from datetime import date
from typing import Any, Optional, Protocol, runtime_checkable

# --- Whole-model mandatory spec (brief §11), mirrored from the platform so the
# FakeQuoteService computes the same missingFields without importing the platform.
MANDATORY_FIELDS: list[str] = [
    "vehicle.registration",
    "vehicle.make",
    "vehicle.model",
    "vehicle.datePurchased",
    "vehicle.value",
    "vehicle.useOfVehicle",
    "vehicle.security",
    "vehicle.dashcam",
    "vehicle.modified",
    "vehicle.imported",
    "vehicle.daytimeLocation",
    "vehicle.overnightLocation",
    "vehicle.annualMileage",
    "vehicle.registeredKeeper",
    "vehicle.legalOwner",
    "customer.title",
    "customer.firstName",
    "customer.surname",
    "customer.dateOfBirth",
    "customer.maritalStatus",
    "customer.childrenUnder16",
    "customer.employmentStatus",
    "customer.partTimeJob",
    "customer.yearsLivedInUK",
    "customer.address.houseNumberOrName",
    "customer.address.postcode",
    "customer.ownsProperty",
    "customer.carKeptOvernightAtAddress",
    "customer.email",
    "driver.licenceType",
    "driver.licenceHeldFor",
    "driver.insuranceCancelledOrVoid",
    "driver.ncdYears",
    "driver.ncdOnCompanyCar",
    "history.claimsLast3Years",
    "history.offencesLast5Years",
    "history.unspentCriminalConvictions",
    "household.carsInHousehold",
    "household.anotherCarHasCover",
    "household.regularUseOfOtherVehicles",
    "cover.paymentMethod",
    "cover.coverLevel",
    "cover.coverStartDate",
    "cover.voluntaryExcess",
]


def _resolve(data: dict, path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _is_absent(value: Any) -> bool:
    """Absent = None / empty string / empty container. ``False`` and ``0`` are present."""
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    if isinstance(value, (dict, list)) and len(value) == 0:
        return True
    return False


def missing_fields(data: dict) -> list[str]:
    data = data or {}
    return [p for p in MANDATORY_FIELDS if _is_absent(_resolve(data, p))]


def journey_state(data: dict, missing: list[str]) -> str:
    if not missing:
        return "ready_to_price"
    if not data:
        return "quote_started"
    return "collecting"


def _is_empty_leaf(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def deep_merge(base: dict, patch: dict) -> dict:
    """Deep-merge ``patch`` into ``base`` in place (brief §17.4).

    Nested dicts merge recursively so a greedy patch never blanks a sibling;
    null / empty-string leaves are dropped (never used to blank existing data).
    Mirrors ``platform.app.quote_service.deep_merge``.
    """
    for key, value in patch.items():
        if isinstance(value, dict):
            existing = base.get(key)
            if not isinstance(existing, dict):
                existing = {}
            merged = deep_merge(existing, value)
            if merged:
                base[key] = merged
        elif _is_empty_leaf(value):
            continue
        else:
            base[key] = value
    return base


# --- Demo fast-path (MOCK_AUTOFILL=1) -------------------------------------------
# A complete, internally-consistent synthetic quote that prices to a clean
# "quote" outcome (£430: base £350 + comprehensive £80; no other loadings). Used
# only to fill the gaps a customer hasn't answered yet, so the whole model
# completes in one turn and the frontend can reach a priced quote without the
# full collection loop. Mirrors the test helper ``_complete_patch``. Synthetic
# only — no real person, vehicle, or address.
COMPLETE_SAMPLE: dict = {
    "vehicle": {
        "registration": "FX19ZTC",
        "make": "Ford",
        "model": "Focus",
        "datePurchased": {"month": 6, "year": 2021},
        "value": 12000,
        "useOfVehicle": "Social + commuting",
        "security": "Factory-fitted",
        "dashcam": False,
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
        "maritalStatus": "Married",
        "childrenUnder16": 0,
        "employmentStatus": "Employed",
        "partTimeJob": False,
        "yearsLivedInUK": "Since birth",
        "address": {"houseNumberOrName": "1", "postcode": "RG1 1AA"},
        "ownsProperty": True,
        "carKeptOvernightAtAddress": True,
        "email": "sam.sample@example.com",
    },
    "driver": {
        "licenceType": "Full UK",
        "licenceHeldFor": 10,
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
        "carsInHousehold": 1,
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


def _set_path(target: dict, path: str, value: Any) -> None:
    """Set ``value`` at a dot-path inside ``target``, creating nested dicts."""
    parts = path.split(".")
    node = target
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value


def gap_fill_patch(current: dict) -> dict:
    """Build a patch that fills only the currently-absent mandatory fields from
    ``COMPLETE_SAMPLE`` — never overwrites a value the customer already gave.

    Used by the ``MOCK_AUTOFILL`` demo fast-path so the whole model completes in
    a single turn while preserving anything the customer actually typed.
    """
    patch: dict = {}
    for path in missing_fields(current):
        value = _resolve(COMPLETE_SAMPLE, path)
        if value is None:
            continue
        _set_path(patch, path, value)
    return patch


@runtime_checkable
class QuoteService(Protocol):
    """Async seam onto the platform's quote tools (brief §6, §8)."""

    async def start(self) -> dict: ...

    async def get(self, quote_id: str, session_id: str) -> Optional[dict]: ...

    async def update(self, quote_id: str, session_id: str, patch: dict) -> Optional[dict]: ...

    async def lookup_vehicle(self, registration: str) -> dict: ...

    async def lookup_address(self, postcode: str) -> dict: ...

    async def price(self, quote_id: str, session_id: str) -> dict: ...

    async def generate_purchase_link(self, quote_id: str, session_id: str) -> dict: ...

    async def issue_policy(self, quote_id: str, session_id: str) -> dict: ...


def _platform_url() -> str:
    return os.getenv("PLATFORM_URL", "http://localhost:8070").rstrip("/")


class PlatformQuoteService:
    """QuoteService over the mock platform's HTTP contract (brief §10).

    Stateless: carries the sessionId as ``X-Session-Id`` on get/update, mirroring
    the MCP server's session-security discipline.
    """

    def __init__(self, base_url: Optional[str] = None) -> None:
        self._base = (base_url or _platform_url()).rstrip("/")

    async def _client(self):
        import httpx

        return httpx.AsyncClient(base_url=self._base, timeout=30.0)

    async def start(self) -> dict:
        async with await self._client() as client:
            resp = await client.post("/quotes")
            resp.raise_for_status()
            return resp.json()

    async def get(self, quote_id: str, session_id: str) -> Optional[dict]:
        async with await self._client() as client:
            resp = await client.get(
                f"/quotes/{quote_id}", headers={"X-Session-Id": session_id}
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()

    async def update(self, quote_id: str, session_id: str, patch: dict) -> Optional[dict]:
        async with await self._client() as client:
            resp = await client.patch(
                f"/quotes/{quote_id}",
                json={"patch": patch},
                headers={"X-Session-Id": session_id},
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()

    async def lookup_vehicle(self, registration: str) -> dict:
        async with await self._client() as client:
            resp = await client.get(f"/vehicles/{registration}")
            if resp.status_code == 404:
                return {"found": False, "registration": registration}
            resp.raise_for_status()
            return {"found": True, **resp.json()}

    async def lookup_address(self, postcode: str) -> dict:
        async with await self._client() as client:
            resp = await client.get("/addresses", params={"postcode": postcode})
            resp.raise_for_status()
            return resp.json()

    async def price(self, quote_id: str, session_id: str) -> dict:
        """POST /quotes/{id}/price. 200 → pricing object; 422 → not_ready_to_price
        + missingFields; 404 → not_found. Surfaced as a structured dict, never raised."""
        async with await self._client() as client:
            resp = await client.post(
                f"/quotes/{quote_id}/price", headers={"X-Session-Id": session_id}
            )
            if resp.status_code == 404:
                return {"error": "not_found"}
            if resp.status_code == 422:
                return resp.json()  # {"error": "not_ready_to_price", "missingFields": [...]}
            resp.raise_for_status()
            return resp.json()

    async def generate_purchase_link(self, quote_id: str, session_id: str) -> dict:
        """POST /quotes/{id}/purchase-link. 200 → {purchaseToken, purchaseUrl};
        409 → not_purchasable; 404 → not_found. Structured dict, never raised."""
        async with await self._client() as client:
            resp = await client.post(
                f"/quotes/{quote_id}/purchase-link",
                headers={"X-Session-Id": session_id},
            )
            if resp.status_code == 404:
                return {"error": "not_found"}
            if resp.status_code == 409:
                return resp.json()  # {"error": "not_purchasable"}
            resp.raise_for_status()
            return resp.json()

    async def issue_policy(self, quote_id: str, session_id: str) -> dict:
        """POST /quotes/{id}/issue-policy. 200 → {policyNumber, status, effectiveDate};
        409 → not_issuable; 404 → not_found. Structured dict, never raised."""
        async with await self._client() as client:
            resp = await client.post(
                f"/quotes/{quote_id}/issue-policy",
                headers={"X-Session-Id": session_id},
            )
            if resp.status_code == 404:
                return {"error": "not_found"}
            if resp.status_code == 409:
                return resp.json()  # {"error": "not_issuable"}
            resp.raise_for_status()
            return resp.json()


# --- Seeded synthetic lookups, mirrored from platform.app.vendor (no real data).
_SEEDED_VEHICLES: dict[str, dict] = {
    "FX19ZTC": {
        "make": "Ford",
        "model": "Focus",
        "derivative": "Titanium 1.0 EcoBoost",
        "fuel": "Petrol",
        "transmission": "Manual",
    },
    "VW68ABC": {
        "make": "Volkswagen",
        "model": "Golf",
        "derivative": "Life 1.5 TSI",
        "fuel": "Petrol",
        "transmission": "Automatic",
    },
    "PF21XYZ": {
        "make": "Performance Marque",
        "model": "GT Coupe",
        "derivative": "Twin-Turbo 600",
        "fuel": "Petrol",
        "transmission": "Automatic",
    },
}

_SEEDED_ADDRESSES: dict[str, list[dict]] = {
    "RG11AA": [
        {"houseNumberOrName": "1", "line1": "1 Sample Street", "postcode": "RG1 1AA"},
        {"houseNumberOrName": "2", "line1": "2 Sample Street", "postcode": "RG1 1AA"},
    ],
    "M12AB": [
        {"houseNumberOrName": "10", "line1": "10 Example Road", "postcode": "M1 2AB"},
    ],
}


# --- Mock rating + underwriting (brief §15), mirrored from platform.pricing so
# the FakeQuoteService produces the same pricing object offline.
_BASE_PREMIUM = 350.0
_LOADING_UNDER_25 = 600.0
_LOADING_HIGH_RISK_POSTCODE = 250.0
_LOADING_PERFORMANCE_VEHICLE = 400.0
_LOADING_PER_CLAIM = 200.0
_LOADING_PER_CONVICTION = 300.0
_LOADING_COMPREHENSIVE = 80.0
_LOADING_HIGH_MILEAGE = 100.0
_DISCOUNT_LARGE_EXCESS = 50.0

_PERFORMANCE_VALUE_THRESHOLD = 60_000
_HIGH_MILEAGE_THRESHOLD = 12_000
_LARGE_EXCESS_THRESHOLD = 500
_COMPULSORY_EXCESS = 350
_INSTALMENTS = 10
_HIGH_RISK_POSTCODE_PREFIXES = ("M1", "B1", "L1", "BD1", "BB1")

_VALUE_REFER_THRESHOLD = 75_000
_CLAIMS_REFER_THRESHOLD = 3
_CONVICTIONS_REFER_THRESHOLD = 2
_MIN_DRIVER_AGE = 18


def _section(data: dict, key: str) -> dict:
    value = (data or {}).get(key)
    return value if isinstance(value, dict) else {}


def _int_value(raw: Any, default: int = 0) -> int:
    if isinstance(raw, bool):
        return default
    if isinstance(raw, (int, float)):
        return int(raw)
    if isinstance(raw, str):
        try:
            return int(float(raw.replace(",", "").strip()))
        except ValueError:
            return default
    return default


def _age_from_dob(raw: Any) -> Optional[int]:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        dob = date.fromisoformat(raw.strip())
    except ValueError:
        return None
    today = date.today()
    years = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    return years


def _is_high_risk_postcode(postcode: Optional[str]) -> bool:
    if not postcode:
        return False
    outward = postcode.upper().replace(" ", "")
    if len(outward) > 3:
        outward = outward[:-3]
    return any(outward.startswith(p) for p in _HIGH_RISK_POSTCODE_PREFIXES)


def _rate(data: dict) -> tuple[float, list[dict]]:
    """Deterministic mock rating (brief §15): premium + a {label, amount} breakdown
    whose lines sum to the premium, so the conversation explains without inventing."""
    vehicle = _section(data, "vehicle")
    customer = _section(data, "customer")
    history = _section(data, "history")
    cover = _section(data, "cover")

    breakdown: list[dict] = [{"label": "Base premium", "amount": _BASE_PREMIUM}]
    premium = _BASE_PREMIUM

    age = _age_from_dob(customer.get("dateOfBirth"))
    if age is not None and age < 25:
        premium += _LOADING_UNDER_25
        breakdown.append({"label": "Driver under 25", "amount": _LOADING_UNDER_25})

    postcode = _section(customer, "address").get("postcode")
    if _is_high_risk_postcode(postcode):
        premium += _LOADING_HIGH_RISK_POSTCODE
        breakdown.append({"label": "High-risk postcode", "amount": _LOADING_HIGH_RISK_POSTCODE})

    if _int_value(vehicle.get("value")) >= _PERFORMANCE_VALUE_THRESHOLD:
        premium += _LOADING_PERFORMANCE_VEHICLE
        breakdown.append({"label": "Performance vehicle", "amount": _LOADING_PERFORMANCE_VEHICLE})

    claims = _int_value(history.get("claimsLast3Years"))
    if claims > 0:
        amount = _LOADING_PER_CLAIM * claims
        premium += amount
        breakdown.append({"label": f"{claims} claim(s) in last 3 years", "amount": amount})

    convictions = _int_value(history.get("offencesLast5Years"))
    if convictions > 0:
        amount = _LOADING_PER_CONVICTION * convictions
        premium += amount
        breakdown.append({"label": f"{convictions} conviction(s) in last 5 years", "amount": amount})

    cover_level = str(cover.get("coverLevel") or "").lower()
    if "comprehensive" in cover_level:
        premium += _LOADING_COMPREHENSIVE
        breakdown.append({"label": "Comprehensive cover", "amount": _LOADING_COMPREHENSIVE})

    if _int_value(vehicle.get("annualMileage")) > _HIGH_MILEAGE_THRESHOLD:
        premium += _LOADING_HIGH_MILEAGE
        breakdown.append({"label": "High annual mileage", "amount": _LOADING_HIGH_MILEAGE})

    if _int_value(cover.get("voluntaryExcess")) >= _LARGE_EXCESS_THRESHOLD:
        premium -= _DISCOUNT_LARGE_EXCESS
        breakdown.append({"label": "Large voluntary excess discount", "amount": -_DISCOUNT_LARGE_EXCESS})

    return round(premium, 2), breakdown


def _underwrite(data: dict) -> tuple[str, list[str]]:
    """Platform-owned underwriting (brief §15): quote / refer / decline + reasons."""
    vehicle = _section(data, "vehicle")
    customer = _section(data, "customer")
    history = _section(data, "history")

    decline: list[str] = []
    age = _age_from_dob(customer.get("dateOfBirth"))
    if age is not None and age < _MIN_DRIVER_AGE:
        decline.append("Driver is under 18")
    if vehicle.get("supported") is False:
        decline.append("Vehicle is not supported for cover")
    if decline:
        return "decline", decline

    refer: list[str] = []
    if _int_value(vehicle.get("value")) > _VALUE_REFER_THRESHOLD:
        refer.append("Vehicle value exceeds £75,000")
    if _int_value(history.get("claimsLast3Years")) > _CLAIMS_REFER_THRESHOLD:
        refer.append("More than 3 claims in the last 3 years")
    if _int_value(history.get("offencesLast5Years")) > _CONVICTIONS_REFER_THRESHOLD:
        refer.append("More than 2 convictions in the last 5 years")
    if refer:
        return "refer", refer

    return "quote", []


def _monthly(annual_premium: float) -> dict:
    instalment = round(annual_premium / _INSTALMENTS, 2)
    deposit = round(annual_premium - instalment * (_INSTALMENTS - 1), 2)
    return {"deposit": deposit, "instalment": instalment, "instalments": _INSTALMENTS}


def build_pricing(data: dict) -> dict:
    """Assemble the brief §11 pricing object from quote data (rate + underwrite)."""
    annual_premium, breakdown = _rate(data)
    outcome, reasons = _underwrite(data)
    cover = _section(data, "cover")
    driver = _section(data, "driver")
    voluntary_excess = _int_value(cover.get("voluntaryExcess"))
    return {
        "annualPremium": annual_premium,
        "currency": "GBP",
        "iptIncluded": True,
        "monthly": _monthly(annual_premium),
        "compulsoryExcess": _COMPULSORY_EXCESS,
        "voluntaryExcess": voluntary_excess,
        "totalExcess": _COMPULSORY_EXCESS + voluntary_excess,
        "ncdYears": _int_value(driver.get("ncdYears")),
        "outcome": outcome,
        "reasons": reasons,
        "breakdown": breakdown,
    }


class FakeQuoteService:
    """In-process platform mirror (deep-merge + missingFields + §15 pricing) — no network.

    Holds quote data keyed by (quoteId, sessionId) so it faithfully mirrors the
    platform's session-scoped store, order-free collection, and price → purchase →
    issue-policy contract for tests.
    """

    def __init__(self) -> None:
        # quote_id -> {"session": str, "data": dict, "outcome": str|None, "pricing": dict|None}
        self._records: dict[str, dict] = {}
        self._counter = 0

    def _state(self, quote_id: str, record: dict) -> dict:
        data = record["data"]
        missing = missing_fields(data)
        outcome = record.get("outcome")
        journey = journey_state(data, missing)
        if outcome == "quote":
            journey = "quoted"
        elif outcome == "refer":
            journey = "referred"
        elif outcome == "decline":
            journey = "declined"
        elif record.get("policy") is not None:
            journey = "policy_issued"
        state = {
            "quoteId": quote_id,
            "journeyState": journey,
            "missingFields": missing,
            "currentOutcome": outcome,
        }
        if record.get("pricing") is not None:
            state["pricing"] = record["pricing"]
        return state

    async def start(self) -> dict:
        self._counter += 1
        quote_id = f"fake-quote-{self._counter:04d}"
        session_id = f"fake-session-{self._counter:04d}"
        record = {"session": session_id, "data": {}, "outcome": None, "pricing": None, "policy": None}
        self._records[quote_id] = record
        return {**self._state(quote_id, record), "sessionId": session_id}

    async def get(self, quote_id: str, session_id: str) -> Optional[dict]:
        record = self._records.get(quote_id)
        if record is None or record["session"] != session_id:
            return None
        return self._state(quote_id, record)

    async def update(self, quote_id: str, session_id: str, patch: dict) -> Optional[dict]:
        record = self._records.get(quote_id)
        if record is None or record["session"] != session_id:
            return None
        deep_merge(record["data"], patch or {})
        # A material change re-opens the quote: clear any prior outcome/pricing.
        record["outcome"] = None
        record["pricing"] = None
        return self._state(quote_id, record)

    async def price(self, quote_id: str, session_id: str) -> dict:
        record = self._records.get(quote_id)
        if record is None or record["session"] != session_id:
            return {"error": "not_found"}
        missing = missing_fields(record["data"])
        if missing:
            return {"error": "not_ready_to_price", "missingFields": missing}
        pricing = build_pricing(record["data"])
        record["outcome"] = pricing["outcome"]
        record["pricing"] = pricing
        return pricing

    async def generate_purchase_link(self, quote_id: str, session_id: str) -> dict:
        record = self._records.get(quote_id)
        if record is None or record["session"] != session_id:
            return {"error": "not_found"}
        if record.get("outcome") != "quote":
            return {"error": "not_purchasable"}
        token = secrets.token_urlsafe(12)
        return {
            "purchaseToken": token,
            "purchaseUrl": f"{_platform_url()}/purchase/{token}",
        }

    async def issue_policy(self, quote_id: str, session_id: str) -> dict:
        record = self._records.get(quote_id)
        if record is None or record["session"] != session_id:
            return {"error": "not_found"}
        if record.get("outcome") != "quote":
            return {"error": "not_issuable"}
        cover = _section(record["data"], "cover")
        start = cover.get("coverStartDate")
        try:
            effective = date.fromisoformat(str(start).strip()).isoformat()
        except (ValueError, AttributeError):
            effective = date.today().isoformat()
        policy = {
            "policyNumber": "ACME-POL-TEST",
            "status": "ISSUED",
            "effectiveDate": effective,
        }
        record["policy"] = policy
        return policy

    async def lookup_vehicle(self, registration: str) -> dict:
        key = (registration or "").upper().replace(" ", "")
        if key in _SEEDED_VEHICLES:
            return {"found": True, "registration": registration, **_SEEDED_VEHICLES[key]}
        return {
            "found": True,
            "registration": registration,
            "make": "Sample Motors",
            "model": "Saloon",
            "derivative": "Standard",
            "fuel": "Petrol",
            "transmission": "Manual",
        }

    async def lookup_address(self, postcode: str) -> dict:
        key = (postcode or "").upper().replace(" ", "")
        candidates = _SEEDED_ADDRESSES.get(
            key,
            [{"houseNumberOrName": "1", "line1": "1 Synthetic Avenue", "postcode": (postcode or "").strip().upper()}],
        )
        return {"postcode": postcode, "candidates": list(candidates)}
