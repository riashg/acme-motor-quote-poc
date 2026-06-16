# AXA Motor Quoting — POC Design Spec

- **Date:** 2026-06-16
- **Status:** Draft for review
- **Type:** Proof of concept / R&D prototype to support a client proposal
- **Owner:** (internal) — originated from Head of Engineering

> **Disclaimer / AXA isolation:** This is an independent R&D prototype. It uses
> **only publicly available information** and **synthetic mock data**. It does
> **not** connect to, replicate, or use any AXA internal systems, data, pricing,
> or APIs. All "AXA" references are brand styling drawn from public sources
> (axa.com) for demo realism only.

## 1. Goal

Build a small, locally-runnable **conversational motor-insurance quoting app**
that demonstrates, for a client proposal:

1. **Natural-language intake** — the user describes their car and circumstances
   in plain English; an LLM (OpenAI) extracts the details needed to quote.
2. **An actual (mock) priced premium** as the end result — not just a captured
   lead — shown in a rich, AXA-styled quote card.
3. **Live adjustment** — the user can change cover tier and voluntary excess and
   see the premium re-price instantly.

**Success bar:** convincing in a live demo + visibly clean separation from AXA
systems. *Not* production-readiness.

### Non-goals (explicitly out of scope for the POC)
- No database, authentication, user accounts, or deployment infrastructure.
- No real integrations (vehicle registries, payment, CRM, underwriting).
- No multi-driver, vehicle modifications, or add-ons in the core journey
  (noted as easy future extensions).
- Not a scripted/menu lead-gen bot. (The Tars motor-insurance agent was raised
  as a *loose reference only*; it is a scripted form that captures a lead with
  no price. We deliberately go further: free-form NL + an instant priced quote.)

## 2. Form factor

A **standalone, AXA-branded chat web app that we build and control**
(ChatGPT-style UI), with OpenAI providing the language layer and a mock backend
doing the quoting. (An OpenAI Apps-SDK / in-ChatGPT version was considered; the
"it has to be like a chat UI" steer points to a standalone branded app. The
backend is structured so the quoting logic could later be exposed via MCP / an
Apps-SDK app with minimal rework.)

## 3. Architecture

```
React chat UI (Vite + TS)          Python backend (FastAPI)              Quoting core (pure Python)
─────────────────────────          ───────────────────────────          ──────────────────────────
ChatWindow / MessageList    ──▶     POST /chat   (SSE stream)      ──▶    quoting/engine.py  (pricing)
Composer (text input)               ├─ OpenAI Responses API               quoting/models.py  (pydantic)
QuoteCard / CoverTier /             │   + function-calling loop
ExcessSlider (rich cards)   ◀──     │   tools: lookup_vehicle,      ──▶    mocks/vehicles.py (reg → car)
                                    │          get_quote, reprice          mocks/risk.py     (group/postcode)
            ▲                       │
            └── live re-price ──────┴─ POST /reprice (deterministic, NO LLM)
```

### Two backend endpoints (deliberate split)
- **`POST /chat`** — conversational path. Streams the assistant turn over SSE.
  Runs the OpenAI function-calling loop: the model calls `lookup_vehicle` /
  `get_quote`; the backend executes them against the mock services + quoting
  core and feeds results back until the model replies. On a produced quote, the
  backend emits a structured `quote` event for the UI to render as a card.
- **`POST /reprice`** — deterministic. When the user drags the excess slider or
  flips cover tier, the UI calls this (no LLM round-trip); the quoting core
  recomputes instantly and the change is recorded into the session so the
  conversation stays consistent.

**Rationale:** the LLM is right for *conversation*, wrong for a slider. Both the
chat tools and the slider call the **same** pure pricing engine — one source of
truth, fully testable without LLM or network.

**Note on `reprice` (two entry points, one engine):** `reprice` exists both as
an LLM tool (so the user can say "what if I raise my excess to £500?" in chat)
and as the deterministic `POST /reprice` endpoint (the slider/selector path).
Both call `quoting/engine.price(...)` — they are two doors into the same logic,
never two implementations.

### Session state
In-memory, keyed by session id (POC-grade). Holds conversation history + the
current quote inputs. No persistence.

## 4. Components

### Backend (`/backend`, Python 3.x + uv)

| Unit | Responsibility | Depends on |
|------|----------------|------------|
| `quoting/models.py` | Pydantic models: `VehicleInput`, `DriverInput`, `QuoteInput`, `Quote`, `PriceBreakdown`, `CoverTier` (COMP/TPFT/TPO) | — |
| `quoting/engine.py` | **Pure** pricing: `price(QuoteInput) -> Quote`. No I/O, no LLM. | models |
| `mocks/vehicles.py` | Mock reg lookup: seeded plates → make/model/year/value/insurance-group + deterministic fallback | models |
| `mocks/risk.py` | Mock tables: postcode → risk band; insurance group → base rate | — |
| `llm/agent.py` | OpenAI client, 3 tool schemas, AXA assistant system prompt, function-calling loop | quoting, mocks |
| `api/main.py` | FastAPI app: `POST /chat` (SSE), `POST /reprice`, `GET /health`; in-memory session store | llm, quoting |

### Pricing model (transparent & deterministic)
```
premium = base_rate(insurance_group)
          × age_factor(driver_age)
          × cover_factor(tier)
          × postcode_factor(risk_band)
          × (1 − ncb_discount(years))
          × excess_factor(voluntary_excess)
```
Each factor is a small documented lookup — explainable in the demo ("here's why
the price moved") and assertable in tests.

### Frontend (`/frontend`, React + Vite + TS)

| Component | Responsibility |
|-----------|----------------|
| `App` / `ChatWindow` | Layout, AXA theming (deep-blue `#00008F` + red accent), session id |
| `MessageList` / `Message` | Streamed turn-by-turn transcript |
| `Composer` | Text input → `POST /chat`, consumes SSE |
| `QuoteCard` | AXA-styled card: premium, vehicle, cover tier, breakdown |
| `CoverTierSelector` | Toggle COMP/TPFT/TPO → `POST /reprice` |
| `ExcessSlider` | Drag voluntary excess → `POST /reprice`, live premium update |

## 5. Error handling

- **No OpenAI key / API error:** env flag `MOCK_LLM=1` runs a scripted tool-call
  flow so the app demos **offline** with no key; a real key flips to live. API
  errors surface as a graceful in-chat message, never a crash.
- **Unknown registration:** mock returns "not found" → assistant asks the user
  to confirm car details manually.
- **Invalid inputs:** pydantic validation → assistant asks a clarifying question.
- **Reprice bounds:** excess constrained to an allowed set; tier to the enum.

## 6. Testing (right-sized for a POC)

- **Unit (core):** pricing engine — exact premiums on seeded inputs + invariants
  (↑ excess ⇒ ↓ premium; ↑ NCB ⇒ ↓ premium; COMP > TPFT > TPO). Most test value
  lives here so demo numbers are defensible.
- **Unit (mocks):** vehicle lookup + risk tables return expected shapes.
- **Integration:** `POST /reprice` end-to-end; `/chat` tool loop with a
  **stubbed OpenAI client** (no network) asserting correct tool dispatch.
- **Frontend:** one smoke test of `QuoteCard` rendering. No further FE tests.

## 7. Tech & runtime

- **Backend:** Python + uv, FastAPI, `openai` SDK, pydantic, uvicorn.
- **Frontend:** React + Vite + TypeScript, minimal CSS in AXA palette.
- **Location:** `/Users/gokulanr/IdeaProjects/axa-motor-quote-prototype/`
- **Dependency:** an OpenAI API key for live mode; `MOCK_LLM=1` for offline.

## 8. Open questions / needs-an-SME

These should be confirmed by a motor-underwriting / AXA domain expert before any
real build; for the POC we use reasonable public/synthetic stand-ins:

1. **Real rating factors** — which factors actually drive AXA motor pricing, and
   their weightings. (POC uses a simplified, documented factor model.)
2. **Cover tiers & products** — AXA's actual UK/region motor product tiers and
   naming. (POC uses generic COMP/TPFT/TPO.)
3. **Target market/region** — UK vs other geographies changes reg format,
   postcode risk, NCB conventions, regulatory wording. (POC assumes UK-style.)
4. **Lead vs price** — does the eventual product compute an instant premium
   (this POC) or capture a lead for underwriting (Tars-style)? POC assumes price.
5. **Right contact for requirements** — open internal question (e.g. "Vishwas?")
   — to be resolved by the proposal team, not by this prototype.

## 9. Future extensions (not in POC)
- Multi-driver / named drivers, add-ons (breakdown, legal, courtesy car),
  vehicle modifications, multi-quote comparison.
- Expose the quoting core as an MCP server → drop into an OpenAI Apps-SDK app
  running inside ChatGPT.
- Persistence, auth, real integrations.
