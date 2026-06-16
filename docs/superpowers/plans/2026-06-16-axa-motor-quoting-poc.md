# AXA Motor Quoting POC — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a locally-runnable, AXA-branded conversational web app where a user describes their car/circumstances in natural language and gets an instant, adjustable mock motor-insurance premium.

**Architecture:** React (Vite + TS) chat UI ↔ Python FastAPI backend. The backend runs an OpenAI function-calling loop (`/chat`, SSE) whose tools call a pure, deterministic pricing engine + mock services; a separate deterministic `/reprice` endpoint powers live slider/selector updates without the LLM. All external data is synthetic mock data — no AXA systems.

**Tech Stack:** Python 3.x + uv, FastAPI, uvicorn, `openai`, pydantic, pytest, httpx; React + Vite + TypeScript.

---

## File Structure

```
axa-motor-quote-prototype/
├── backend/
│   ├── pyproject.toml
│   ├── .env.example
│   ├── app/
│   │   ├── __init__.py
│   │   ├── quoting/
│   │   │   ├── __init__.py
│   │   │   ├── models.py        # pydantic models + enums + constants
│   │   │   └── engine.py        # pure pricing logic
│   │   ├── mocks/
│   │   │   ├── __init__.py
│   │   │   ├── risk.py          # group base rate, postcode→band, band factor
│   │   │   └── vehicles.py      # mock reg lookup
│   │   ├── llm/
│   │   │   ├── __init__.py
│   │   │   ├── tools.py         # tool schemas + dispatch to engine/mocks
│   │   │   └── agent.py         # OpenAI loop + MOCK_LLM scripted mode
│   │   └── api/
│   │       ├── __init__.py
│   │       └── main.py          # FastAPI: /health, /reprice, /chat(SSE), sessions
│   └── tests/
│       ├── test_engine.py
│       ├── test_mocks.py
│       ├── test_tools.py
│       ├── test_reprice_api.py
│       └── test_agent_loop.py
└── frontend/
    ├── package.json
    ├── index.html
    ├── src/
    │   ├── main.tsx
    │   ├── App.tsx
    │   ├── theme.css            # AXA palette
    │   ├── api.ts               # chat SSE + reprice client
    │   ├── types.ts
    │   └── components/
    │       ├── ChatWindow.tsx
    │       ├── MessageList.tsx
    │       ├── Composer.tsx
    │       ├── QuoteCard.tsx
    │       ├── CoverTierSelector.tsx
    │       └── ExcessSlider.tsx
    └── src/components/QuoteCard.test.tsx
```

**Conventions used across all tasks**
- Backend commands run from `backend/` via `uv run`.
- `CoverTier` values: `"comprehensive"`, `"third_party_fire_theft"`, `"third_party_only"`.
- `ALLOWED_EXCESS = [0, 100, 250, 500, 750, 1000]`.
- Premiums are floats rounded to 2 dp; monthly = annual / 12 rounded to 2 dp.

---

## Task 1: Backend scaffold

**Files:**
- Create: `backend/pyproject.toml`, `backend/app/__init__.py`, package `__init__.py` files, `backend/.env.example`

- [ ] **Step 1: Initialise the uv project**

Run from the repo root:
```bash
cd backend 2>/dev/null || (mkdir -p backend && cd backend)
uv init --no-readme .
uv add fastapi "uvicorn[standard]" "openai>=1.40" "pydantic>=2"
uv add --dev pytest httpx
```

- [ ] **Step 2: Create the package directories**

```bash
mkdir -p app/quoting app/mocks app/llm app/api tests
touch app/__init__.py app/quoting/__init__.py app/mocks/__init__.py app/llm/__init__.py app/api/__init__.py tests/__init__.py
rm -f main.py        # remove uv's default entrypoint
```

- [ ] **Step 3: Create `.env.example`**

Create `backend/.env.example`:
```
# Set a real key for live LLM mode:
OPENAI_API_KEY=
# When 1, the app runs a scripted offline flow with no API key:
MOCK_LLM=1
```

- [ ] **Step 4: Verify pytest runs (no tests yet)**

Run: `uv run pytest -q`
Expected: `no tests ran` (exit 5) — confirms the toolchain works.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "chore: scaffold backend (uv, fastapi, pytest)"
```

---

## Task 2: Quoting models & constants

**Files:**
- Create: `backend/app/quoting/models.py`
- Test: `backend/tests/test_engine.py` (shared test file, started here)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_engine.py`:
```python
from app.quoting.models import (
    ALLOWED_EXCESS,
    CoverTier,
    DriverInput,
    QuoteInput,
    VehicleInput,
)


def make_quote_input(**overrides) -> QuoteInput:
    vehicle = VehicleInput(
        registration="AB12CDE",
        make="Volkswagen",
        model="Golf",
        year=2019,
        value=14000.0,
        insurance_group=20,
    )
    driver = DriverInput(age=34, ncb_years=5, postcode="SW1A1AA")
    defaults = dict(
        vehicle=vehicle,
        driver=driver,
        cover_tier=CoverTier.COMPREHENSIVE,
        voluntary_excess=250,
    )
    defaults.update(overrides)
    return QuoteInput(**defaults)


def test_models_construct_and_defaults():
    qi = make_quote_input()
    assert qi.cover_tier == CoverTier.COMPREHENSIVE
    assert qi.voluntary_excess in ALLOWED_EXCESS
    assert qi.vehicle.insurance_group == 20


def test_invalid_excess_rejected():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        make_quote_input(voluntary_excess=333)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_engine.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.quoting.models'`.

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/quoting/models.py`:
```python
from enum import Enum

from pydantic import BaseModel, Field, field_validator

ALLOWED_EXCESS = [0, 100, 250, 500, 750, 1000]


class CoverTier(str, Enum):
    COMPREHENSIVE = "comprehensive"
    THIRD_PARTY_FIRE_THEFT = "third_party_fire_theft"
    THIRD_PARTY_ONLY = "third_party_only"


class VehicleInput(BaseModel):
    registration: str
    make: str
    model: str
    year: int = Field(ge=1980, le=2027)
    value: float = Field(gt=0)
    insurance_group: int = Field(ge=1, le=50)


class DriverInput(BaseModel):
    age: int = Field(ge=17, le=99)
    ncb_years: int = Field(ge=0, le=20)
    postcode: str


class QuoteInput(BaseModel):
    vehicle: VehicleInput
    driver: DriverInput
    cover_tier: CoverTier = CoverTier.COMPREHENSIVE
    voluntary_excess: int = 250

    @field_validator("voluntary_excess")
    @classmethod
    def _excess_allowed(cls, v: int) -> int:
        if v not in ALLOWED_EXCESS:
            raise ValueError(f"voluntary_excess must be one of {ALLOWED_EXCESS}")
        return v


class PriceBreakdown(BaseModel):
    base_rate: float
    age_factor: float
    cover_factor: float
    postcode_factor: float
    ncb_discount: float
    excess_factor: float


class Quote(BaseModel):
    quote_id: str
    input: QuoteInput
    breakdown: PriceBreakdown
    annual_premium: float
    monthly_premium: float
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_engine.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/quoting/models.py backend/tests/test_engine.py
git commit -m "feat: quoting models, enums, and excess validation"
```

---

## Task 3: Mock risk tables

**Files:**
- Create: `backend/app/mocks/risk.py`
- Test: `backend/tests/test_mocks.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_mocks.py`:
```python
from app.mocks.risk import band_factor, group_base_rate, postcode_to_band


def test_group_base_rate_increases_with_group():
    assert group_base_rate(1) < group_base_rate(50)
    assert group_base_rate(20) == 200 + 20 * 12


def test_postcode_to_band_is_deterministic():
    assert postcode_to_band("SW1A1AA") == postcode_to_band("sw1a 1aa")
    assert postcode_to_band("SW1A1AA") in {"low", "medium", "high"}


def test_band_factor_ordering():
    assert band_factor("low") < band_factor("medium") < band_factor("high")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mocks.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.mocks.risk'`.

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/mocks/risk.py`:
```python
# MOCK DATA — synthetic/public only, NOT AXA systems or data.
"""Synthetic risk lookup tables for the POC."""

_BAND_FACTORS = {"low": 0.9, "medium": 1.0, "high": 1.25}

# Mock mapping of postcode area (leading letters) to a risk band.
_AREA_BAND = {
    "SW": "high", "E": "high", "M": "high", "B": "medium",
    "LS": "medium", "G": "medium", "EH": "low", "AB": "low", "CF": "low",
}


def group_base_rate(insurance_group: int) -> float:
    """Higher insurance group -> higher base annual rate."""
    return float(200 + insurance_group * 12)


def postcode_to_band(postcode: str) -> str:
    """Deterministically map a postcode to a risk band."""
    pc = postcode.strip().upper().replace(" ", "")
    for prefix in sorted(_AREA_BAND, key=len, reverse=True):
        if pc.startswith(prefix):
            return _AREA_BAND[prefix]
    # Deterministic fallback from the first character.
    return "medium" if (ord(pc[:1] or "M") % 2 == 0) else "low"


def band_factor(band: str) -> float:
    return _BAND_FACTORS[band]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mocks.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/mocks/risk.py backend/tests/test_mocks.py
git commit -m "feat: mock risk tables (base rate, postcode band)"
```

---

## Task 4: Mock vehicle lookup

**Files:**
- Create: `backend/app/mocks/vehicles.py`
- Test: `backend/tests/test_mocks.py` (append)

- [ ] **Step 1: Write the failing test (append to `tests/test_mocks.py`)**

Add to `backend/tests/test_mocks.py`:
```python
from app.mocks.vehicles import lookup_vehicle


def test_seeded_registration_returns_known_car():
    v = lookup_vehicle("AB12CDE")
    assert v is not None
    assert v.make and v.model and 1 <= v.insurance_group <= 50


def test_unknown_registration_returns_deterministic_fallback():
    a = lookup_vehicle("ZZ99ZZZ")
    b = lookup_vehicle("zz99 zzz")
    assert a is not None and a.registration == "ZZ99ZZZ"
    assert a.insurance_group == b.insurance_group  # deterministic
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mocks.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.mocks.vehicles'`.

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/mocks/vehicles.py`:
```python
# MOCK DATA — synthetic/public only, NOT AXA systems or data.
"""Synthetic vehicle registration lookup for the POC."""

from app.quoting.models import VehicleInput

_SEED = {
    "AB12CDE": ("Volkswagen", "Golf", 2019, 14000.0, 20),
    "LR68XYZ": ("Land Rover", "Discovery", 2018, 32000.0, 40),
    "FT19ABC": ("Ford", "Fiesta", 2020, 11000.0, 10),
    "TS21EVS": ("Tesla", "Model 3", 2021, 38000.0, 48),
}


def _normalise(reg: str) -> str:
    return reg.strip().upper().replace(" ", "")


def lookup_vehicle(registration: str) -> VehicleInput | None:
    """Return a VehicleInput for a registration, or a deterministic fallback."""
    reg = _normalise(registration)
    if reg in _SEED:
        make, model, year, value, group = _SEED[reg]
        return VehicleInput(
            registration=reg, make=make, model=model,
            year=year, value=value, insurance_group=group,
        )
    # Deterministic synthetic fallback derived from the plate characters.
    seed = sum(ord(c) for c in reg) if reg else 100
    group = (seed % 45) + 1
    return VehicleInput(
        registration=reg,
        make="Generic",
        model="Hatchback",
        year=2015 + (seed % 10),
        value=float(8000 + (seed % 20) * 1000),
        insurance_group=group,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mocks.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/mocks/vehicles.py backend/tests/test_mocks.py
git commit -m "feat: mock vehicle registration lookup"
```

---

## Task 5: Pricing engine (the core)

**Files:**
- Create: `backend/app/quoting/engine.py`
- Test: `backend/tests/test_engine.py` (append)

- [ ] **Step 1: Write the failing tests (append to `tests/test_engine.py`)**

Add to `backend/tests/test_engine.py`:
```python
from app.quoting.engine import price
from app.quoting.models import CoverTier


def test_price_is_positive_and_has_breakdown():
    q = price(make_quote_input())
    assert q.annual_premium > 0
    assert round(q.monthly_premium * 12, 2) == q.annual_premium
    assert q.breakdown.base_rate > 0


def test_higher_excess_lowers_premium():
    low = price(make_quote_input(voluntary_excess=0)).annual_premium
    high = price(make_quote_input(voluntary_excess=1000)).annual_premium
    assert high < low


def test_more_ncb_lowers_premium():
    p0 = price(make_quote_input(driver=DriverInput(age=34, ncb_years=0, postcode="SW1A1AA"))).annual_premium
    p9 = price(make_quote_input(driver=DriverInput(age=34, ncb_years=9, postcode="SW1A1AA"))).annual_premium
    assert p9 < p0


def test_cover_tier_ordering_comp_highest():
    comp = price(make_quote_input(cover_tier=CoverTier.COMPREHENSIVE)).annual_premium
    tpft = price(make_quote_input(cover_tier=CoverTier.THIRD_PARTY_FIRE_THEFT)).annual_premium
    tpo = price(make_quote_input(cover_tier=CoverTier.THIRD_PARTY_ONLY)).annual_premium
    assert comp > tpft > tpo


def test_young_driver_pays_more():
    young = price(make_quote_input(driver=DriverInput(age=19, ncb_years=0, postcode="SW1A1AA"))).annual_premium
    mid = price(make_quote_input(driver=DriverInput(age=40, ncb_years=0, postcode="SW1A1AA"))).annual_premium
    assert young > mid
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_engine.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.quoting.engine'`.

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/quoting/engine.py`:
```python
"""Pure, deterministic motor pricing. No I/O, no LLM, no network."""

import uuid

from app.mocks.risk import band_factor, group_base_rate, postcode_to_band
from app.quoting.models import (
    CoverTier,
    PriceBreakdown,
    Quote,
    QuoteInput,
)

_COVER_FACTOR = {
    CoverTier.COMPREHENSIVE: 1.0,
    CoverTier.THIRD_PARTY_FIRE_THEFT: 0.85,
    CoverTier.THIRD_PARTY_ONLY: 0.70,
}

_EXCESS_FACTOR = {0: 1.10, 100: 1.05, 250: 1.00, 500: 0.92, 750: 0.86, 1000: 0.80}


def _age_factor(age: int) -> float:
    if age < 21:
        return 1.8
    if age < 25:
        return 1.4
    if age < 30:
        return 1.15
    if age < 60:
        return 1.0
    if age < 70:
        return 1.05
    return 1.3


def _ncb_discount(years: int) -> float:
    return min(years * 0.07, 0.65)


def price(qi: QuoteInput) -> Quote:
    base = group_base_rate(qi.vehicle.insurance_group)
    age_f = _age_factor(qi.driver.age)
    cover_f = _COVER_FACTOR[qi.cover_tier]
    band = postcode_to_band(qi.driver.postcode)
    pc_f = band_factor(band)
    ncb_d = _ncb_discount(qi.driver.ncb_years)
    exc_f = _EXCESS_FACTOR[qi.voluntary_excess]

    annual = base * age_f * cover_f * pc_f * (1 - ncb_d) * exc_f
    annual = round(annual, 2)

    return Quote(
        quote_id=str(uuid.uuid4()),
        input=qi,
        breakdown=PriceBreakdown(
            base_rate=base,
            age_factor=age_f,
            cover_factor=cover_f,
            postcode_factor=pc_f,
            ncb_discount=ncb_d,
            excess_factor=exc_f,
        ),
        annual_premium=annual,
        monthly_premium=round(annual / 12, 2),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_engine.py -q`
Expected: PASS (all engine tests green).

- [ ] **Step 5: Commit**

```bash
git add backend/app/quoting/engine.py backend/tests/test_engine.py
git commit -m "feat: deterministic pricing engine with invariants"
```

---

## Task 6: LLM tool definitions & dispatch

**Files:**
- Create: `backend/app/llm/tools.py`
- Test: `backend/tests/test_tools.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_tools.py`:
```python
from app.llm.tools import TOOL_SCHEMAS, dispatch_tool


def test_tool_schemas_present():
    names = {t["function"]["name"] for t in TOOL_SCHEMAS}
    assert names == {"lookup_vehicle", "get_quote", "reprice"}


def test_dispatch_lookup_vehicle():
    out = dispatch_tool("lookup_vehicle", {"registration": "AB12CDE"}, state={})
    assert out["make"] == "Volkswagen"


def test_dispatch_get_quote_stores_state():
    state = {}
    out = dispatch_tool(
        "get_quote",
        {
            "registration": "AB12CDE",
            "age": 34,
            "ncb_years": 5,
            "postcode": "SW1A1AA",
            "cover_tier": "comprehensive",
            "voluntary_excess": 250,
        },
        state=state,
    )
    assert out["annual_premium"] > 0
    assert "quote_input" in state  # remembered for later reprice


def test_dispatch_reprice_uses_state():
    state = {}
    dispatch_tool(
        "get_quote",
        {
            "registration": "AB12CDE", "age": 34, "ncb_years": 5,
            "postcode": "SW1A1AA", "cover_tier": "comprehensive",
            "voluntary_excess": 250,
        },
        state=state,
    )
    cheaper = dispatch_tool("reprice", {"voluntary_excess": 1000}, state=state)
    assert cheaper["annual_premium"] > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tools.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.llm.tools'`.

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/llm/tools.py`:
```python
"""Tool schemas exposed to the LLM, and dispatch into the quoting core.

`state` is a per-session mutable dict; get_quote stores the QuoteInput so a
later reprice can reuse everything except the changed field.
"""

from app.mocks.vehicles import lookup_vehicle
from app.quoting.engine import price
from app.quoting.models import CoverTier, DriverInput, QuoteInput

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "lookup_vehicle",
            "description": "Look up a vehicle's details from its registration plate.",
            "parameters": {
                "type": "object",
                "properties": {
                    "registration": {"type": "string", "description": "UK-style registration plate"}
                },
                "required": ["registration"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_quote",
            "description": "Produce a motor insurance quote. Looks up the vehicle by registration, then prices it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "registration": {"type": "string"},
                    "age": {"type": "integer"},
                    "ncb_years": {"type": "integer", "description": "Years of no-claims bonus"},
                    "postcode": {"type": "string"},
                    "cover_tier": {
                        "type": "string",
                        "enum": [c.value for c in CoverTier],
                    },
                    "voluntary_excess": {"type": "integer", "enum": [0, 100, 250, 500, 750, 1000]},
                },
                "required": ["registration", "age", "ncb_years", "postcode"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reprice",
            "description": "Re-price the current quote after changing cover tier and/or voluntary excess.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cover_tier": {"type": "string", "enum": [c.value for c in CoverTier]},
                    "voluntary_excess": {"type": "integer", "enum": [0, 100, 250, 500, 750, 1000]},
                },
            },
        },
    },
]


def _build_quote_input(args: dict) -> QuoteInput:
    vehicle = lookup_vehicle(args["registration"])
    driver = DriverInput(
        age=args["age"], ncb_years=args["ncb_years"], postcode=args["postcode"]
    )
    return QuoteInput(
        vehicle=vehicle,
        driver=driver,
        cover_tier=CoverTier(args.get("cover_tier", "comprehensive")),
        voluntary_excess=int(args.get("voluntary_excess", 250)),
    )


def dispatch_tool(name: str, args: dict, state: dict) -> dict:
    if name == "lookup_vehicle":
        return lookup_vehicle(args["registration"]).model_dump()

    if name == "get_quote":
        qi = _build_quote_input(args)
        state["quote_input"] = qi
        return price(qi).model_dump()

    if name == "reprice":
        qi: QuoteInput = state["quote_input"]
        updated = qi.model_copy(
            update={
                "cover_tier": CoverTier(args.get("cover_tier", qi.cover_tier.value)),
                "voluntary_excess": int(args.get("voluntary_excess", qi.voluntary_excess)),
            }
        )
        state["quote_input"] = updated
        return price(updated).model_dump()

    raise ValueError(f"Unknown tool: {name}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_tools.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/llm/tools.py backend/tests/test_tools.py
git commit -m "feat: LLM tool schemas and dispatch into quoting core"
```

---

## Task 7: Agent loop (real + MOCK_LLM)

**Files:**
- Create: `backend/app/llm/agent.py`
- Test: `backend/tests/test_agent_loop.py`

The agent yields a sequence of events: `{"type": "text", "data": str}` for assistant prose and `{"type": "quote", "data": dict}` whenever a `get_quote`/`reprice` tool produced a quote. The real path uses the OpenAI Chat Completions API with `TOOL_SCHEMAS`; tests inject a fake client so no network is touched.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_agent_loop.py`:
```python
from app.llm.agent import run_agent_turn


class _FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class _FakeToolCall:
    def __init__(self, call_id, name, arguments):
        self.id = call_id
        self.type = "function"
        self.function = type("F", (), {"name": name, "arguments": arguments})


class _FakeChoice:
    def __init__(self, message):
        self.message = message


class _FakeResponse:
    def __init__(self, message):
        self.choices = [_FakeChoice(message)]


class FakeClient:
    """Returns a tool call first, then a final text answer."""

    def __init__(self):
        self._calls = 0
        self.chat = type("C", (), {"completions": self})

    def create(self, **kwargs):
        self._calls += 1
        if self._calls == 1:
            tc = _FakeToolCall(
                "call_1",
                "get_quote",
                '{"registration":"AB12CDE","age":34,"ncb_years":5,"postcode":"SW1A1AA"}',
            )
            return _FakeResponse(_FakeMessage(tool_calls=[tc]))
        return _FakeResponse(_FakeMessage(content="Here is your quote."))


def test_agent_emits_quote_then_text():
    session = {"history": [], "state": {}}
    events = list(run_agent_turn("Quote my AB12CDE", session, client=FakeClient()))
    types = [e["type"] for e in events]
    assert "quote" in types
    assert events[-1] == {"type": "text", "data": "Here is your quote."}
    assert session["state"]["quote_input"].voluntary_excess == 250


def test_mock_llm_mode_runs_without_client(monkeypatch):
    monkeypatch.setenv("MOCK_LLM", "1")
    session = {"history": [], "state": {}}
    events = list(run_agent_turn("I drive AB12CDE, age 34, 5 years NCB, SW1A1AA", session, client=None))
    assert any(e["type"] == "quote" for e in events)
    assert any(e["type"] == "text" for e in events)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_agent_loop.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.llm.agent'`.

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/llm/agent.py`:
```python
"""OpenAI function-calling loop with an offline MOCK_LLM fallback."""

import json
import os
import re

from app.llm.tools import TOOL_SCHEMAS, dispatch_tool

SYSTEM_PROMPT = (
    "You are AXA's friendly motor insurance assistant. Help the user get a car "
    "insurance quote by collecting, in natural language: vehicle registration, "
    "driver age, years of no-claims bonus, and postcode. Call get_quote once you "
    "have them. Offer to adjust cover tier or voluntary excess via reprice. Be "
    "concise, warm, and professional. Never claim to be a real or binding quote — "
    "this is an illustrative demo."
)

_QUOTE_TOOLS = {"get_quote", "reprice"}


def _emit_quote_events(tool_name, result):
    events = []
    if tool_name in _QUOTE_TOOLS and "annual_premium" in result:
        events.append({"type": "quote", "data": result})
    return events


def run_agent_turn(user_message: str, session: dict, client=None):
    """Generator of events for one user turn. Mutates session history/state."""
    if os.getenv("MOCK_LLM") == "1" and client is None:
        yield from _run_mock_turn(user_message, session)
        return

    history = session["history"]
    state = session["state"]
    if not history:
        history.append({"role": "system", "content": SYSTEM_PROMPT})
    history.append({"role": "user", "content": user_message})

    while True:
        resp = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=history,
            tools=TOOL_SCHEMAS,
        )
        msg = resp.choices[0].message

        if msg.tool_calls:
            history.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                }
            )
            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments or "{}")
                result = dispatch_tool(tc.function.name, args, state)
                yield from _emit_quote_events(tc.function.name, result)
                history.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result),
                    }
                )
            continue

        history.append({"role": "assistant", "content": msg.content or ""})
        yield {"type": "text", "data": msg.content or ""}
        return


def _run_mock_turn(user_message: str, session: dict):
    """Deterministic offline flow: extract details by regex, quote, explain."""
    state = session["state"]
    reg = (re.search(r"\b([A-Z]{2}\d{2}\s?[A-Z]{3})\b", user_message.upper()) or [None, None])[1]
    age = (re.search(r"\bage\s*(\d{2})\b|\b(\d{2})\s*years old", user_message) or [None])
    age_val = next((g for g in (age.groups() if hasattr(age, "groups") else []) if g), None)
    ncb = re.search(r"(\d{1,2})\s*(?:years?\s*)?(?:ncb|no[- ]?claims)", user_message.lower())
    postcode = re.search(r"\b([A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2})\b", user_message.upper())

    if reg and age_val and ncb and postcode:
        result = dispatch_tool(
            "get_quote",
            {
                "registration": reg.replace(" ", ""),
                "age": int(age_val),
                "ncb_years": int(ncb.group(1)),
                "postcode": postcode.group(1),
            },
            state,
        )
        yield {"type": "quote", "data": result}
        yield {
            "type": "text",
            "data": (
                f"Thanks! Here's your illustrative AXA quote: "
                f"£{result['annual_premium']:.2f}/year "
                f"(£{result['monthly_premium']:.2f}/month). "
                "Try adjusting the excess or cover tier below."
            ),
        }
    else:
        yield {
            "type": "text",
            "data": (
                "I can quote your car insurance. Please tell me your registration, "
                "age, years of no-claims bonus, and postcode — e.g. "
                "'I drive AB12CDE, age 34, 5 years NCB, SW1A 1AA'."
            ),
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_agent_loop.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/llm/agent.py backend/tests/test_agent_loop.py
git commit -m "feat: agent loop with OpenAI tools + offline MOCK_LLM mode"
```

---

## Task 8: FastAPI app (`/health`, `/reprice`, `/chat`)

**Files:**
- Create: `backend/app/api/main.py`
- Test: `backend/tests/test_reprice_api.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_reprice_api.py`:
```python
from fastapi.testclient import TestClient

from app.api.main import app, sessions

client = TestClient(app)


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_reprice_requires_existing_quote():
    r = client.post("/reprice", json={"session_id": "missing", "voluntary_excess": 500})
    assert r.status_code == 404


def test_reprice_updates_premium():
    # Seed a session with a quote via the tool dispatch directly.
    from app.llm.tools import dispatch_tool

    sessions["s1"] = {"history": [], "state": {}}
    dispatch_tool(
        "get_quote",
        {"registration": "AB12CDE", "age": 34, "ncb_years": 5, "postcode": "SW1A1AA"},
        sessions["s1"]["state"],
    )
    r = client.post("/reprice", json={"session_id": "s1", "voluntary_excess": 1000})
    assert r.status_code == 200
    assert r.json()["annual_premium"] > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_reprice_api.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.api.main'`.

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/api/main.py`:
```python
import json
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.llm.agent import run_agent_turn
from app.quoting.engine import price
from app.quoting.models import CoverTier, QuoteInput

app = FastAPI(title="AXA Motor Quoting POC (mock)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session store: session_id -> {"history": [...], "state": {...}}
sessions: dict[str, dict] = {}


def _get_client():
    if os.getenv("MOCK_LLM") == "1":
        return None
    from openai import OpenAI

    return OpenAI()


class ChatRequest(BaseModel):
    session_id: str
    message: str


class RepriceRequest(BaseModel):
    session_id: str
    cover_tier: CoverTier | None = None
    voluntary_excess: int | None = None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat")
def chat(req: ChatRequest):
    session = sessions.setdefault(req.session_id, {"history": [], "state": {}})
    client = _get_client()

    def event_stream():
        for event in run_agent_turn(req.message, session, client=client):
            yield f"data: {json.dumps(event)}\n\n"
        yield "data: {\"type\": \"done\"}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/reprice")
def reprice(req: RepriceRequest):
    session = sessions.get(req.session_id)
    if not session or "quote_input" not in session.get("state", {}):
        raise HTTPException(status_code=404, detail="No quote in session yet.")
    qi: QuoteInput = session["state"]["quote_input"]
    updated = qi.model_copy(
        update={
            "cover_tier": req.cover_tier or qi.cover_tier,
            "voluntary_excess": req.voluntary_excess
            if req.voluntary_excess is not None
            else qi.voluntary_excess,
        }
    )
    session["state"]["quote_input"] = updated
    return price(updated).model_dump()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_reprice_api.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Run the full backend suite + commit**

Run: `uv run pytest -q`
Expected: all tests pass.
```bash
git add backend/app/api/main.py backend/tests/test_reprice_api.py
git commit -m "feat: FastAPI app with /health, /chat (SSE), /reprice"
```

---

## Task 9: Frontend scaffold + AXA theme

**Files:**
- Create: `frontend/` (Vite React TS), `frontend/src/theme.css`, `frontend/src/types.ts`

- [ ] **Step 1: Scaffold Vite + React + TS**

Run from the repo root:
```bash
npm create vite@latest frontend -- --template react-ts
cd frontend && npm install && npm install --save-dev vitest @testing-library/react @testing-library/jest-dom jsdom
```

- [ ] **Step 2: Add the AXA theme**

Create `frontend/src/theme.css`:
```css
:root {
  --axa-blue: #00008f;
  --axa-red: #ff1721;
  --axa-bg: #f7f7fb;
  --axa-card: #ffffff;
  --axa-text: #1a1a2e;
}
* { box-sizing: border-box; font-family: -apple-system, Segoe UI, Roboto, sans-serif; }
body { margin: 0; background: var(--axa-bg); color: var(--axa-text); }
.axa-header { background: var(--axa-blue); color: #fff; padding: 12px 16px; font-weight: 700; }
.axa-accent { color: var(--axa-red); }
button { cursor: pointer; }
```

- [ ] **Step 3: Add shared types**

Create `frontend/src/types.ts`:
```typescript
export type CoverTier =
  | "comprehensive"
  | "third_party_fire_theft"
  | "third_party_only";

export interface Quote {
  quote_id: string;
  annual_premium: number;
  monthly_premium: number;
  input: {
    cover_tier: CoverTier;
    voluntary_excess: number;
    vehicle: { make: string; model: string; year: number; registration: string };
  };
  breakdown: Record<string, number>;
}

export interface ChatEvent {
  type: "text" | "quote" | "done";
  data?: string | Quote;
}
```

- [ ] **Step 4: Verify the dev build boots**

Run: `npm run build`
Expected: build succeeds (TypeScript compiles).

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "chore: scaffold React+Vite frontend with AXA theme and types"
```

---

## Task 10: API client (chat SSE + reprice)

**Files:**
- Create: `frontend/src/api.ts`

- [ ] **Step 1: Implement the client**

Create `frontend/src/api.ts`:
```typescript
import type { ChatEvent, CoverTier, Quote } from "./types";

const BASE = "http://localhost:8000";

export async function streamChat(
  sessionId: string,
  message: string,
  onEvent: (e: ChatEvent) => void,
): Promise<void> {
  const resp = await fetch(`${BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, message }),
  });
  const reader = resp.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const line = part.replace(/^data: /, "").trim();
      if (line) onEvent(JSON.parse(line) as ChatEvent);
    }
  }
}

export async function reprice(
  sessionId: string,
  changes: { cover_tier?: CoverTier; voluntary_excess?: number },
): Promise<Quote> {
  const resp = await fetch(`${BASE}/reprice`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, ...changes }),
  });
  if (!resp.ok) throw new Error("reprice failed");
  return (await resp.json()) as Quote;
}
```

- [ ] **Step 2: Verify it compiles**

Run: `npm run build`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api.ts
git commit -m "feat: frontend API client for chat SSE and reprice"
```

---

## Task 11: Rich components (QuoteCard, selector, slider) + smoke test

**Files:**
- Create: `frontend/src/components/QuoteCard.tsx`, `CoverTierSelector.tsx`, `ExcessSlider.tsx`
- Test: `frontend/src/components/QuoteCard.test.tsx`

- [ ] **Step 1: Write the failing smoke test**

Create `frontend/src/components/QuoteCard.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { QuoteCard } from "./QuoteCard";
import type { Quote } from "../types";

const quote: Quote = {
  quote_id: "q1",
  annual_premium: 612.34,
  monthly_premium: 51.03,
  input: {
    cover_tier: "comprehensive",
    voluntary_excess: 250,
    vehicle: { make: "Volkswagen", model: "Golf", year: 2019, registration: "AB12CDE" },
  },
  breakdown: {},
};

describe("QuoteCard", () => {
  it("renders the annual premium and vehicle", () => {
    render(<QuoteCard quote={quote} onChange={() => {}} />);
    expect(screen.getByText(/612.34/)).toBeInTheDocument();
    expect(screen.getByText(/Volkswagen Golf/)).toBeInTheDocument();
  });
});
```

Add to `frontend/package.json` scripts: `"test": "vitest run"`, and create `frontend/vitest.config.ts`:
```typescript
import { defineConfig } from "vitest/config";
export default defineConfig({ test: { environment: "jsdom", globals: true, setupFiles: [] } });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test`
Expected: FAIL — cannot find `./QuoteCard`.

- [ ] **Step 3: Implement the components**

Create `frontend/src/components/ExcessSlider.tsx`:
```tsx
const ALLOWED = [0, 100, 250, 500, 750, 1000];

export function ExcessSlider({
  value,
  onChange,
}: {
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <label style={{ display: "block", margin: "8px 0" }}>
      Voluntary excess: <strong>£{value}</strong>
      <input
        type="range"
        min={0}
        max={ALLOWED.length - 1}
        step={1}
        value={ALLOWED.indexOf(value)}
        onChange={(e) => onChange(ALLOWED[Number(e.target.value)])}
        style={{ width: "100%" }}
      />
    </label>
  );
}
```

Create `frontend/src/components/CoverTierSelector.tsx`:
```tsx
import type { CoverTier } from "../types";

const TIERS: { id: CoverTier; label: string }[] = [
  { id: "comprehensive", label: "Comprehensive" },
  { id: "third_party_fire_theft", label: "TPFT" },
  { id: "third_party_only", label: "Third Party" },
];

export function CoverTierSelector({
  value,
  onChange,
}: {
  value: CoverTier;
  onChange: (t: CoverTier) => void;
}) {
  return (
    <div style={{ display: "flex", gap: 8, margin: "8px 0" }}>
      {TIERS.map((t) => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          style={{
            padding: "6px 10px",
            border: "1px solid var(--axa-blue)",
            background: value === t.id ? "var(--axa-blue)" : "#fff",
            color: value === t.id ? "#fff" : "var(--axa-blue)",
            borderRadius: 6,
          }}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
```

Create `frontend/src/components/QuoteCard.tsx`:
```tsx
import type { CoverTier, Quote } from "../types";
import { CoverTierSelector } from "./CoverTierSelector";
import { ExcessSlider } from "./ExcessSlider";

export function QuoteCard({
  quote,
  onChange,
}: {
  quote: Quote;
  onChange: (changes: { cover_tier?: CoverTier; voluntary_excess?: number }) => void;
}) {
  const v = quote.input.vehicle;
  return (
    <div
      style={{
        background: "var(--axa-card)",
        border: "1px solid #e0e0ef",
        borderLeft: "6px solid var(--axa-blue)",
        borderRadius: 10,
        padding: 16,
        margin: "8px 0",
        maxWidth: 420,
      }}
    >
      <div style={{ color: "var(--axa-blue)", fontWeight: 700 }}>AXA Motor Quote</div>
      <div style={{ fontSize: 13, opacity: 0.7 }}>
        {v.make} {v.model} ({v.year}) · {v.registration}
      </div>
      <div style={{ fontSize: 32, fontWeight: 800, margin: "8px 0" }}>
        £{quote.annual_premium.toFixed(2)}
        <span style={{ fontSize: 14, fontWeight: 400 }}> /year</span>
      </div>
      <div className="axa-accent">£{quote.monthly_premium.toFixed(2)} /month</div>
      <CoverTierSelector
        value={quote.input.cover_tier}
        onChange={(t) => onChange({ cover_tier: t })}
      />
      <ExcessSlider
        value={quote.input.voluntary_excess}
        onChange={(e) => onChange({ voluntary_excess: e })}
      />
      <div style={{ fontSize: 11, opacity: 0.6, marginTop: 8 }}>
        Illustrative demo — mock data only, not a real or binding AXA quote.
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components frontend/vitest.config.ts frontend/package.json
git commit -m "feat: AXA quote card, cover-tier selector, excess slider"
```

---

## Task 12: Chat shell + wire-up + run

**Files:**
- Create: `frontend/src/components/ChatWindow.tsx`, `MessageList.tsx`, `Composer.tsx`
- Modify: `frontend/src/App.tsx`, `frontend/src/main.tsx`
- Create: `README.md` run instructions (repo root, append)

- [ ] **Step 1: MessageList + Composer**

Create `frontend/src/components/MessageList.tsx`:
```tsx
import type { Quote } from "../types";
import { QuoteCard } from "./QuoteCard";

export interface ChatItem {
  role: "user" | "assistant";
  text?: string;
  quote?: Quote;
}

export function MessageList({
  items,
  onQuoteChange,
}: {
  items: ChatItem[];
  onQuoteChange: (changes: { cover_tier?: string; voluntary_excess?: number }) => void;
}) {
  return (
    <div style={{ flex: 1, overflowY: "auto", padding: 16 }}>
      {items.map((it, i) => (
        <div key={i} style={{ textAlign: it.role === "user" ? "right" : "left" }}>
          {it.text && (
            <div
              style={{
                display: "inline-block",
                background: it.role === "user" ? "var(--axa-blue)" : "#eee",
                color: it.role === "user" ? "#fff" : "#000",
                padding: "8px 12px",
                borderRadius: 12,
                margin: "4px 0",
                maxWidth: "80%",
              }}
            >
              {it.text}
            </div>
          )}
          {it.quote && <QuoteCard quote={it.quote} onChange={onQuoteChange as never} />}
        </div>
      ))}
    </div>
  );
}
```

Create `frontend/src/components/Composer.tsx`:
```tsx
import { useState } from "react";

export function Composer({ onSend }: { onSend: (msg: string) => void }) {
  const [text, setText] = useState("");
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (text.trim()) {
          onSend(text.trim());
          setText("");
        }
      }}
      style={{ display: "flex", gap: 8, padding: 12, borderTop: "1px solid #ddd" }}
    >
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="e.g. I drive AB12CDE, age 34, 5 years NCB, SW1A 1AA"
        style={{ flex: 1, padding: 10, borderRadius: 8, border: "1px solid #ccc" }}
      />
      <button style={{ background: "var(--axa-blue)", color: "#fff", border: 0, borderRadius: 8, padding: "0 16px" }}>
        Send
      </button>
    </form>
  );
}
```

- [ ] **Step 2: ChatWindow (state + wiring)**

Create `frontend/src/components/ChatWindow.tsx`:
```tsx
import { useRef, useState } from "react";
import { reprice, streamChat } from "../api";
import type { Quote } from "../types";
import { Composer } from "./Composer";
import { ChatItem, MessageList } from "./MessageList";

export function ChatWindow() {
  const [items, setItems] = useState<ChatItem[]>([
    { role: "assistant", text: "Hi! I'm your AXA motor assistant. Tell me about your car to get a quote." },
  ]);
  const sessionId = useRef(crypto.randomUUID()).current;

  async function send(msg: string) {
    setItems((p) => [...p, { role: "user", text: msg }]);
    await streamChat(sessionId, msg, (e) => {
      if (e.type === "text") setItems((p) => [...p, { role: "assistant", text: e.data as string }]);
      if (e.type === "quote") setItems((p) => [...p, { role: "assistant", quote: e.data as Quote }]);
    });
  }

  async function onQuoteChange(changes: { cover_tier?: string; voluntary_excess?: number }) {
    const updated = await reprice(sessionId, changes as never);
    setItems((p) => {
      const copy = [...p];
      for (let i = copy.length - 1; i >= 0; i--) {
        if (copy[i].quote) {
          copy[i] = { ...copy[i], quote: updated };
          break;
        }
      }
      return copy;
    });
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      <div className="axa-header">AXA <span className="axa-accent">Motor</span> — quote assistant (demo)</div>
      <MessageList items={items} onQuoteChange={onQuoteChange} />
      <Composer onSend={send} />
    </div>
  );
}
```

- [ ] **Step 3: App + main**

Replace `frontend/src/App.tsx`:
```tsx
import "./theme.css";
import { ChatWindow } from "./components/ChatWindow";

export default function App() {
  return <ChatWindow />;
}
```

Ensure `frontend/src/main.tsx` renders `<App />` (Vite default already does). Remove `App.css`/`index.css` imports if present.

- [ ] **Step 4: Run end-to-end manually**

Terminal 1 (backend, offline mode):
```bash
cd backend && MOCK_LLM=1 uv run uvicorn app.api.main:app --reload --port 8000
```
Terminal 2 (frontend):
```bash
cd frontend && npm run dev
```
Open the printed localhost URL. Type: `I drive AB12CDE, age 34, 5 years NCB, SW1A 1AA`.
Expected: a quote card appears; dragging the excess slider re-prices live; switching cover tier re-prices.

- [ ] **Step 5: Add run instructions to README + commit**

Append a "## Running locally" section to the repo-root `README.md` documenting the two commands above (offline `MOCK_LLM=1`, and live mode with `OPENAI_API_KEY` set + `MOCK_LLM` unset).
```bash
git add frontend/src README.md
git commit -m "feat: chat shell wired to backend; live reprice; run docs"
```

---

## Self-Review

**Spec coverage:**
- NL intake → Task 7 (agent loop) + Task 12 (composer). ✓
- Actual mock premium → Task 5 (engine) surfaced via Task 7/8/11. ✓
- Live adjustment (tier + excess) → Task 8 (`/reprice`) + Task 11 (slider/selector) + Task 12 (wire-up). ✓
- Two-endpoint split → Task 8. ✓
- Pricing factor model → Task 5 (matches spec formula). ✓
- Mock vehicle/risk services → Tasks 3–4. ✓
- Error handling: unknown reg fallback (Task 4), excess validation (Task 2), no-key offline mode (Task 7), reprice 404 (Task 8). ✓
- Testing: engine invariants (Task 5), mocks (3–4), tools (6), agent stubbed (7), reprice API (8), QuoteCard smoke (11). ✓
- AXA isolation/branding: mock-data headers (Tasks 3–4), theme (Task 9), demo disclaimer in QuoteCard (Task 11). ✓
- Open-questions/SME + future extensions: documentation-only in the spec; no implementation tasks needed. ✓

**Placeholder scan:** No TBD/TODO; every code step contains full code; every test step has real assertions.

**Type consistency:** `CoverTier` values, `ALLOWED_EXCESS`, `Quote`/`PriceBreakdown` field names, tool names (`lookup_vehicle`/`get_quote`/`reprice`), and `dispatch_tool(name, args, state)` signature are consistent across backend tasks; frontend `Quote`/`ChatEvent`/`CoverTier` types match the backend JSON shape (`annual_premium`, `monthly_premium`, `input.cover_tier`, `input.voluntary_excess`, `input.vehicle.*`).

No gaps found.
