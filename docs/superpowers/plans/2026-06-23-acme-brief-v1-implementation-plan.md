# ACME Motor Quote PoC — Implementation Plan (Brief v1.0)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.
> Spec = `ACME_ChatGPT_PoC_Build_Brief_v1_0.md` (repo root). This plan sequences that
> brief into buildable slices. No real brand/data anywhere — "ACME" is a placeholder.

**Goal:** Deliver the brief's capabilities — greedy whole-model motor-quote collection,
document-assisted extraction, conflict resolution, quote/refer/decline underwriting,
quote continuation, purchase handoff, and a **live dashboard** — with the insurer
**mock platform as the source of truth**, an **MCP integration layer**, and a
**conversation layer**.

**Form-factor decision:** the conversation layer is our **standalone web app** (chat UI
+ backend LLM) for now, *not* the ChatGPT App — adding a write-capable ChatGPT connector
needs a Business/Enterprise plan, which is unavailable.

**Extensibility is a first-class requirement.** The conversation layer is a **thin,
swappable adapter**; the durable core is the **MCP + platform**, which make **no
assumption about the front end**. We must be able to swap the conversation layer between
the **web app (now)**, a **ChatGPT App**, or a **standalone React UI** with **zero
changes to the platform and only thin changes at the MCP edge**. Concretely:
- The **platform** exposes a versioned **OpenAPI** contract and knows nothing about any UI.
- The **MCP** exposes typed tools over that contract and is host-agnostic (works for
  ChatGPT connectors, our web backend, or any MCP client).
- Host-specific concerns (how documents are uploaded, who runs the extraction LLM, how
  questions are phrased) live **only** in the conversation adapter — never in the core.
  (e.g. ChatGPT does OCR natively; our web backend calls a vision model — same MCP/platform.)

**Architectural invariant (brief §3):** *the conversation layer owns the conversation;
the backend owns the journey.* The app may collect data in any order and fill many fields
at once, but only the backend decides what is still required and whether it can be priced.

---

## Target structure (evolves the current repo)

```
acme-motor-quote-poc/
├── platform/                 # mock insurer platform — the SOURCE OF TRUTH (FastAPI + OpenAPI)
│   ├── app/
│   │   ├── model.py          # whole-model pydantic; every leaf OPTIONAL (partial patches validate)
│   │   ├── required.py       # mandatory-field spec → missingFields computation
│   │   ├── events.py         # append-only event store + in-process pub/sub
│   │   ├── quote_service.py  # create/get/update (deep-merge); missingFields
│   │   ├── rating.py         # mock pricing (base £350 + adjustments, brief §15)
│   │   ├── underwriting.py   # quote / refer / decline + reasons
│   │   ├── documents.py      # LLM-backed extraction (whole-model + image); no regex fallback
│   │   ├── purchase_link.py  # signed, GUID-addressed purchase URLs + stable demo GUID
│   │   ├── api.py            # FastAPI; three-layer logging; serves OpenAPI
│   │   └── channel.py        # WebSocket (+ SSE fallback) event channel for the dashboard
│   └── tests/
├── mcp-server/               # EXPAND: ~12 typed tools → platform API (stateless, idempotent)
├── backend/                  # conversation backend (evolve): greedy+anchored extraction,
│                             #   conflict resolution, doc upload (attach+message), MCP client
├── frontend/                 # conversation UI (evolve): staged-doc composer, confirmation
│                             #   echoes, conflict chips
├── dashboard/                # NEW: live dashboard UI (Quote Sessions / State / Events / Tool / API)
└── landing/                  # NEW: strict GUID purchase/quote landing page (+ demo GUID)
```

> **Note — WireMock is superseded.** The brief requires a **stateful** mock platform
> (quote state, event store, underwriting outcomes, OpenAPI). WireMock (stateless stubs)
> can't do this, so `mock-acme/` is replaced by `platform/`. The existing `mcp-server/`,
> `backend/`, and `frontend/` are evolved, not discarded.

**Three-layer discipline (brief §3) — every state change:**
`MCP tool fn → platform API fn (logs request+response) → mutate state + append domain event`.
This yields the dashboard's Tool Activity, API Activity, and Event Timeline for free.

---

## Tool surface (brief §7) — MCP

Core: `start_motor_quote`, `update_motor_quote` (partial multi-field patch), `get_motor_quote`,
`price_motor_quote`, `retrieve_motor_quote`, `generate_purchase_link`.
Lookups: `lookup_vehicle`, `lookup_address`, `add_named_driver`, `save_quote`.
Documents: `extract_quote_from_document`, `confirm_extracted_quote_details`.
Routing: `route_to_alternative_channel`.

---

## Slice roadmap (brief §18)

| Slice | Delivers | Status |
|---|---|---|
| **1** | conversation→MCP→API→Dashboard wiring; hello-world API; **live** dashboard updates | THIS PLAN — detailed below |
| **2** | Quote creation (GUID identity, event store, three-layer) | detailed below |
| 3 | Greedy, order-free collection + validation + **question-anchored** extraction + **conflict resolution** | outline |
| 4 | Document-assisted quotes (attach+message, whole-model + **image** extraction, instruction routing) | outline |
| 5 | Pricing & underwriting (quote/refer/decline) + explainable breakdown | outline |
| 6 | Quote continuation (save / mock OTP / resume / reprice) | outline |
| 7 | Purchase handoff to the **strict GUID** landing page | outline |

Cadence: ~one slice per weekly iteration; each ends with a working, demoable increment.

---

## Slice 1 — Wiring + live dashboard (detailed)

**Outcome:** a `ping` flows conversation → MCP → platform API → event store → dashboard
updates **live**, exercising the three-layer discipline end to end.

### Task 1.1 — Platform skeleton + event store (TDD)
- Create `platform/` uv project (FastAPI, pydantic, uvicorn; dev pytest, httpx).
- `events.py`: `EventStore` with `append(event_type, payload) -> Event` (GUID id, monotonic seq, timestamp passed in), `all()`, and an async pub/sub (`subscribe()` async generator) for the channel.
- `api.py`: `GET /health`; a three-layer demo route `POST /ping` that logs an `API_REQUEST`/`API_RESPONSE` and appends a `PING` domain event.
- Tests: append+read; `/health`; `/ping` appends exactly the expected events.
- Commit `feat(platform): event store + ping (three-layer)`.

### Task 1.2 — Live channel (WebSocket + SSE fallback)
- `channel.py`: `GET /events` (SSE) and `WS /ws` that stream appended events from `EventStore.subscribe()`.
- Test with `httpx`/`TestClient`: connect, append an event, assert it is received.
- Commit `feat(platform): live event channel (WS + SSE)`.

### Task 1.3 — MCP `ping` tool → platform
- In `mcp-server/`: add an `acme_platform` HTTP client (base `PLATFORM_URL`, default `http://localhost:8070`) and a `ping` tool that calls `POST /ping` and returns the result. (Annotations per Apps-SDK convention retained.)
- Test with stubbed transport.
- Commit `feat(mcp): platform client + ping tool`.

### Task 1.4 — Dashboard (minimal live)
- `dashboard/`: a single static page (served by the platform at `/dashboard`, or a tiny Vite app) that connects to `/events` (SSE) and renders an **Event Timeline** live.
- Manual verify: start platform, open dashboard, call `/ping`, see the event appear without refresh.
- Commit `feat(dashboard): live event timeline (Slice 1)`.

### Task 1.5 — Conversation hook (smoke)
- Backend: a thin `/ping` passthrough that calls the MCP `ping` tool (proving conversation→MCP→API→dashboard). Wire a temporary "ping" affordance or test.
- Commit `chore: end-to-end ping wiring (Slice 1 complete)`.

---

## Slice 2 — Quote creation (detailed)

**Outcome:** `start_motor_quote` creates a GUID quote; `QUOTE_CREATED` shows on the
dashboard; `get_motor_quote` returns `{quoteId, journeyState, missingFields, currentOutcome}`.

### Task 2.1 — Whole-model + required-fields (TDD)
- `model.py`: the full data model (brief §11) as nested pydantic, **every leaf optional**.
- `required.py`: the mandatory-field list → `missing_fields(quote) -> [paths]` (dot paths e.g. `customer.dateOfBirth`).
- Tests: empty quote → all mandatory missing; a partial quote → correct remaining.

### Task 2.2 — Quote service (create/get/deep-merge) (TDD)
- `quote_service.py`: `create() -> quote(GUID, draft)`; `get(id)`; `apply_patch(id, patch)` **deep-merging** (drop null/empty leaves; never blank siblings — brief §17.4); recompute `missingFields`; `journeyState` (`quote_started`/`collecting`/`ready_to_price`).
- Tests: create; deep-merge keeps existing; missingFields recompute; equal-value no-op.

### Task 2.3 — API + MCP tools `start/get/update_motor_quote`
- `api.py`: `POST /quotes`, `GET /quotes/{id}`, `PATCH /quotes/{id}` — three-layer (log + `QUOTE_CREATED`/`QUOTE_UPDATED` events).
- MCP: `start_motor_quote`, `get_motor_quote`, `update_motor_quote` tools.
- Dashboard: add **Quote Sessions** + **Quote State** views.
- Tests: end-to-end create→patch→missingFields; events emitted.

### Task 2.4 — Stable demo GUID
- A fixed GUID that self-seeds a fully-priced sample quote on first access, isolated from in-progress quotes (brief §9, §17.7). (Pricing stub until Slice 5.)

---

## Slices 3–7 — outline (expand when reached)

- **3 — Greedy collection + conflict:** compose the whole-model JSON schema; backend extractor returns every confidently-determined field, **anchored on the asked question** (§4.2/§17.1); `update_motor_quote` applies the patch; **conflict engine** (§4.6/§17.2-3): loose equality, queue genuine clashes, ask via chips, never invent (`null` sentinel, never `0`/`""`).
- **4 — Documents:** primary upload types are a **driving licence** (image/photo) and a
  **previous-year policy** (text PDF) — both must extract into the whole-model patch
  (licence → identity/licence fields; policy → vehicle/cover/NCD/history fields).
  `extract_quote_from_document` (whole-model schema + optional instruction; **image + text**);
  composer **stages** a file + message and sends together (§4.4/§17.5); instruction routing →
  `add_named_driver` without overwriting the applicant (§4.5). Mock-doc generator extended to
  produce a sample **driving licence** alongside the policy/renewal.
- **5 — Pricing & underwriting:** `rating.py` (base £350 + adjustments, §15), `underwriting.py` (quote/refer/decline + reasons), `price_motor_quote` → full pricing object (§11) with `breakdown` so the conversation explains without inventing (§4.9).
- **6 — Continuation:** `save_quote`; reference → email → **mock OTP** → `retrieve_motor_quote` → revalidate + reprice (§12).
- **7 — Purchase handoff:** `purchase_link.py` signed GUID URL; `landing/` resolves **only** the GUID and renders **only** if cleanly priced, else "Quote not found" (§17.6); use the stable demo GUID.

---

## Cross-cutting requirements (apply throughout)

- **No real brand/data** anywhere; all synthetic; "representative UK motor insurer".
- **Three-layer discipline** on every state change (dashboard feeds come for free).
- **Guardrails (§16):** conversation never invents premiums/cover/outcomes; backend is the only source of pricing/underwriting; unsupported journeys → `route_to_alternative_channel` (already prototyped).
- **GUIDs** for quote IDs and purchase links; one stable demo GUID.
- **OpenAPI** published by the platform (§10) — MCP and dashboard build against it.

## Self-review
- Spec coverage: every brief §4 behaviour, §5 journey, §7 tool, §9 service, §11 model section, §14 dashboard view, §15 pricing rule, and §18 slice maps to a slice above. Slices 1–2 are task-detailed; 3–7 are outlined and will be detailed on entry.
- No placeholders in Slice 1–2 tasks. Form-factor divergence (web app vs ChatGPT) explicitly recorded and justified.
