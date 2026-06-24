"""FastAPI conversation backend (brief Slice 3).

One conversation adapter onto the mock platform / MCP. The backend owns the
journey (brief §6): it holds the quoteId + platform sessionId per backend
session and drives a greedy, order-free, question-anchored collection with
conflict resolution.

Endpoints:
  * ``POST /start``                      → start a quote; returns a backend session_id.
  * ``POST /chat {session_id, message}`` → one greedy turn, SSE (echo/text/conflict/done).
  * ``POST /resolve {session_id, path, value}`` → apply a conflict resolution, SSE.

``MOCK_LLM=1`` selects the deterministic offline extractor; service selection is
via ``QUOTE_SERVICE`` (``fake`` | ``platform``).
"""

from __future__ import annotations

import json
import os
import secrets

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.agent import apply_resolution, collect_turn, confirmation_echo
from app.conflict import reconcile
from app.documents import extract_document
from app.explain import explain_quote
from app.extraction import whole_model_schema
from app.quote_session_client import FakeQuoteService, PlatformQuoteService, deep_merge

app = FastAPI(title="ACME Motor Quote — conversation backend (Slice 3)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory backend sessions: session_id -> {quoteId, sessionId, current,
# asked_question, pending_conflicts}.
sessions: dict[str, dict] = {}


def _get_service():
    service = getattr(app.state, "service", None)
    if service is not None:
        return service
    backend = os.getenv("QUOTE_SERVICE", "fake" if os.getenv("MOCK_LLM") == "1" else "platform")
    if backend == "platform":
        return PlatformQuoteService()
    return FakeQuoteService()


def _llm_client():
    if os.getenv("MOCK_LLM") == "1":
        return None
    from openai import OpenAI

    return OpenAI()


def _vision_client():
    """The OpenAI client used for document (vision) extraction — None in MOCK mode.

    Mirrors ``_llm_client`` so the document path uses the same client selection;
    ``app.documents.extract_document`` picks the vision model itself."""
    if os.getenv("MOCK_LLM") == "1":
        return None
    from openai import OpenAI

    return OpenAI()


class ChatRequest(BaseModel):
    session_id: str
    message: str


class ResolveRequest(BaseModel):
    session_id: str
    path: str
    value: object = None


class SessionRequest(BaseModel):
    session_id: str


def _sse(events):
    async def stream():
        async for event in events:
            yield f"data: {json.dumps(event)}\n\n"
        yield 'data: {"type": "done"}\n\n'

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/start")
async def start():
    service = _get_service()
    created = await service.start()
    session_id = secrets.token_urlsafe(16)
    sessions[session_id] = {
        "quoteId": created["quoteId"],
        "sessionId": created["sessionId"],
        "current": {},
        "asked_question": None,
        "pending_conflicts": [],
    }
    return {
        "session_id": session_id,
        "quoteId": created["quoteId"],
        "journeyState": created["journeyState"],
        "missingFields": created["missingFields"],
    }


@app.post("/chat")
async def chat(req: ChatRequest):
    session = sessions.get(req.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Unknown session")
    service = _get_service()
    client = _llm_client()
    return _sse(collect_turn(req.message, session, service, client=client))


@app.post("/resolve")
async def resolve(req: ResolveRequest):
    session = sessions.get(req.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Unknown session")
    service = _get_service()
    client = _llm_client()
    return _sse(apply_resolution(session, service, req.path, req.value, client=client))


def _flatten_paths(patch: dict, prefix: str = "") -> list[str]:
    """Dot-paths of every leaf in a nested patch (lists are leaves)."""
    out: list[str] = []
    for key, value in (patch or {}).items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.extend(_flatten_paths(value, path))
        else:
            out.append(path)
    return out


@app.post("/upload")
async def upload(
    session_id: str = Form(...),
    file: UploadFile = File(...),
    message: str = Form(""),
):
    """Document-assisted extraction (brief §4.4, §4.5, §13, §17.8).

    Multipart: ``session_id``, ``file`` (attachment), optional ``message`` (the
    accompanying instruction). The file bytes + whole-model schema (+ instruction)
    go to the extraction LLM (vision; image AND PDF). The raw bytes are ``del``'d
    immediately after extraction and never persisted.

    * A *named-driver* instruction appends the extracted person to
      ``namedDrivers[]`` via ``update`` — the applicant is left untouched.
    * Otherwise the patch is ``reconcile``d against the current quote: the
      non-conflicting part is applied; genuine conflicts are queued for the
      existing ``/resolve`` endpoint (never silently overwritten, §4.6).

    Returns ``{extracted, applied, conflicts, echo, missingFields, journeyState,
    target}``."""
    session = _require_session(session_id)
    service = _get_service()

    file_bytes = await file.read()
    result = extract_document(
        file_bytes,
        file.content_type or "application/octet-stream",
        file.filename or "",
        message or "",
        whole_model_schema(),
        client=_vision_client(),
    )
    del file_bytes  # never persist the raw document bytes.

    patch = result["patch"]
    extracted = _flatten_paths(patch)
    quote_id = session["quoteId"]
    platform_session = session["sessionId"]
    session.setdefault("current", {})

    if result["target"] == "named_driver":
        # Append (do NOT overwrite the applicant). Read-modify-write the list.
        existing = list(session["current"].get("namedDrivers", []))
        existing.append(patch)
        state = await service.update(quote_id, platform_session, {"namedDrivers": existing})
        session["current"]["namedDrivers"] = existing
        return {
            "extracted": extracted,
            "applied": ["namedDrivers[]"],
            "conflicts": [],
            "echo": f"✓ Added named driver {patch.get('firstName', '')} {patch.get('surname', '')}".strip(),
            "missingFields": (state or {}).get("missingFields", []),
            "journeyState": (state or {}).get("journeyState"),
            "target": "named_driver",
        }

    # Applicant path: reconcile against the held quote (§4.6).
    applicable, conflicts = reconcile(session["current"], patch)

    if applicable:
        state = await service.update(quote_id, platform_session, applicable)
        deep_merge(session["current"], applicable)
    else:
        state = await service.get(quote_id, platform_session)

    if conflicts:
        # Queue for the existing /resolve flow — do not overwrite held values.
        session["pending_conflicts"] = conflicts

    return {
        "extracted": extracted,
        "applied": _flatten_paths(applicable),
        "conflicts": conflicts,
        "echo": confirmation_echo(applicable),
        "missingFields": (state or {}).get("missingFields", []),
        "journeyState": (state or {}).get("journeyState"),
        "target": "applicant",
    }


def _require_session(session_id: str) -> dict:
    session = sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Unknown session")
    return session


@app.post("/price")
async def price(req: SessionRequest):
    """Price the quote via the platform. Returns ``{pricing, explanation}`` on a
    priced quote; surfaces the platform's 422 (``not_ready_to_price`` +
    ``missingFields``) when the quote is still incomplete."""
    session = _require_session(req.session_id)
    service = _get_service()
    result = await service.price(session["quoteId"], session["sessionId"])

    if result.get("error") == "not_found":
        raise HTTPException(status_code=404, detail="Unknown session")
    if result.get("error") == "not_ready_to_price":
        return JSONResponse(status_code=422, content=result)

    session["outcome"] = result.get("outcome")
    session["pricing"] = result
    return {"pricing": result, "explanation": explain_quote(result)}


@app.post("/purchase")
async def purchase(req: SessionRequest):
    """Generate a purchase link for a cleanly-priced quote. 409-style message if
    the quote isn't a clean ``quote`` outcome."""
    session = _require_session(req.session_id)
    service = _get_service()
    result = await service.generate_purchase_link(session["quoteId"], session["sessionId"])

    if result.get("error") == "not_found":
        raise HTTPException(status_code=404, detail="Unknown session")
    if result.get("error"):
        return JSONResponse(
            status_code=409,
            content={
                "error": result["error"],
                "message": "This quote can't be purchased — it isn't a clean quote.",
            },
        )
    return {"purchaseUrl": result["purchaseUrl"]}


@app.post("/issue-policy")
async def issue_policy(req: SessionRequest):
    """Issue a (mock) policy for a cleanly-priced quote. 409-style message if the
    quote isn't a clean ``quote`` outcome."""
    session = _require_session(req.session_id)
    service = _get_service()
    result = await service.issue_policy(session["quoteId"], session["sessionId"])

    if result.get("error") == "not_found":
        raise HTTPException(status_code=404, detail="Unknown session")
    if result.get("error"):
        return JSONResponse(
            status_code=409,
            content={
                "error": result["error"],
                "message": "This quote can't be issued — it isn't a clean quote.",
            },
        )
    return {
        "policyNumber": result["policyNumber"],
        "status": result["status"],
        "effectiveDate": result["effectiveDate"],
    }
