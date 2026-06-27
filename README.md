# ACME Motor Quote — Demo

Independent R&D demo. **Synthetic mock data only. Not connected to any real ACME / client system.**
"ACME" is a placeholder — no real brand references anywhere.

A motor-insurance quotation journey where the **conversation layer** (a web app, or a
ChatGPT app) does natural-language collection + document extraction, an **MCP server**
is the integration layer, and a **mock insurer platform** is the source of truth for
state, validation, pricing, and underwriting. Journey: **quote → price (quote / refer /
decline) → purchase link → mock policy issuance**, with a **live dashboard**. See
`ACME_ChatGPT_PoC_Build_Brief_v1_0.md` (the brief) and `docs/` for the plan.

## Architecture (layers are decoupled — the UI is swappable)
```
UI (React web app  OR  ChatGPT app)
   → Conversation backend (Python)      runs the LLM / greedy collection / doc extraction
   → MCP server (Python)                integration layer: typed tools (separate process)
   → Platform (Java / Spring Boot)      SOURCE OF TRUTH: quote state, rating, underwriting,
                                          purchase link, mock policy issuance + vendor SOAP seam
   → Dashboard (live, served by the platform)   |   GUID purchase/landing page
```
The conversation layer owns the conversation; the **platform owns the journey**. Rating
and policy issuance go through a **`VendorClient` SOAP seam** (mocked now; a real
`SoapVendorClient` from the vendor WSDL drops in later with no other change).

## Components
- `platform/` — **Java/Spring Boot** mock insurer platform (port 8070): session-scoped quote service (whole-model, deep-merge, missingFields), rating + underwriting (quote/refer/decline), purchase link + strict-GUID landing page, mock policy issuance, event store + three-layer logging, **vendor SOAP seam**, OpenAPI. Serves the dashboard at `/dashboard`.
- `mcp-server/` — **Python** MCP integration layer (port 8090): session-aware tools `start/get/update_motor_quote`, `lookup_vehicle/address`, `price_motor_quote`, `generate_purchase_link`, `issue_policy`. LLM-free.
- `backend/` — **Python** conversation backend (port 8000): greedy, question-anchored collection; conflict resolution; document upload + whole-model vision extraction; price/explain/purchase/issue endpoints.
- `frontend/` — **React/Vite** web UI (port 5173): chat, staged document upload, conflict chips, quote card, purchase, policy.
- `dashboard/` — vanilla-JS live dashboard (event timeline / quote sessions / tool & API activity), served by the platform.
- `docs/` — build plan + `open-questions-for-acme.md`; `mock-docs/` — synthetic sample documents to upload.

## Running the full stack locally (offline — no API key needed)

JDK 26 + `uv` + Node are used; the platform uses the Maven wrapper (`./mvnw`, no local Maven needed).

**1) Platform (Java, :8070 — also serves the dashboard).** Run from `platform/` so the dashboard path resolves:
```bash
cd platform
./mvnw spring-boot:run
# (or: ./mvnw -q -DskipTests package && java -Dplatform.dashboard-dir="$PWD/../dashboard" -jar target/platform-0.0.1-SNAPSHOT.jar)
```

**2) Conversation backend (Python, :8000)** — talks to the live platform; offline LLM:
```bash
cd backend
MOCK_LLM=1 QUOTE_SERVICE=platform PLATFORM_URL=http://localhost:8070 \
  uv run uvicorn app.main:app --port 8000
```

> **Frontend dev shortcut:** add `MOCK_AUTOFILL=1` to the backend command to skip
> collection — any single chat message fills the remaining fields from a synthetic
> sample and the quote becomes ready to price in one turn. For iterating on the UI
> without answering every question. Omit it to exercise real collection.

**3) Frontend (React, :5173):**
```bash
cd frontend
npm install   # first time only
npm run dev
```

Then open **http://localhost:5173** (the app) and **http://localhost:8070/dashboard** (live dashboard).
Try a quote by chatting (e.g. *"I'm Mr Sam Sample, born 1990-01-01, Ford Focus reg FX19ZTC worth 12k, 8000 miles commuting, 5 yrs NCD"*) or upload a sample from `mock-docs/` (renewal/policy/licence). When all required fields are in, get the quote → continue to purchase → issue policy.

**MCP server (optional — the ChatGPT-app integration path):**
```bash
cd mcp-server
PLATFORM_URL=http://localhost:8070 uv run python -m app.server   # streamable-HTTP on :8090
```
The web app talks to the platform directly; the MCP is what a ChatGPT app connects to.

The MCP server also exposes **MCP Apps UI widgets** ([ext-apps](https://github.com/modelcontextprotocol/ext-apps) spec), so an ext-apps-aware host renders styled UI instead of raw JSON:
- **Quote card** (`ui://acme-motor-quote/quote-card.html`): `price_motor_quote` (real flow — live priced quote once all details are in, or a "not ready" state) and a `display_quote_card` demo tool (mock data) both link to it via `_meta.ui.resourceUri`.
- **Document upload** (`ui://acme-motor-quote/document-upload.html`): `open_document_upload` (launcher) renders a file picker; the widget base64-uploads the file to `extract_document`, which decodes it to confirm receipt (`receivedBytes`) but does not parse it — extraction is mock (licence/renewal/named-driver patches, routed on filename, applied to the quote when a session is supplied). After extraction the widget reports the captured fields to the model via `ui/message`.

Each widget is self-contained HTML over a zero-dependency `postMessage` bridge — open the files under `mcp-server/app/widgets/` in a browser to preview them standalone.

**Live LLM mode:** set `OPENAI_API_KEY` and omit `MOCK_LLM` (backend uses OpenAI for extraction/collection; vision for documents).

## Tests
```bash
cd platform   && ./mvnw -q test    # Java platform (journey, rating, underwriting, purchase, policy)
cd backend    && uv run pytest -q  # conversation backend (collection, conflict, documents, journey)
cd mcp-server && uv run pytest -q  # MCP integration tools
cd frontend   && npm run test       # frontend smoke tests
```

## Docs
- `ACME_ChatGPT_PoC_Build_Brief_v1_0.md` — the build brief (the spec).
- `docs/superpowers/plans/2026-06-23-acme-brief-v1-implementation-plan.md` — sliced implementation plan.
- `docs/open-questions-for-acme.md` — open questions to confirm with ACME.
