"""FastAPI form-filling backend (POC).

Drives the schema-driven form-filling agent and proxies the quote/handoff to a
QuoteService (the offline FakeQuoteService in MOCK mode, otherwise the live
MCPQuoteService). The backend never prices anything itself.
"""

from __future__ import annotations

import json
import os

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.agent import collect_turn
from app.extraction import extract_document
from app.mcp_client import MCPQuoteService
from app.service import FakeQuoteService

app = FastAPI(title="ACME Motor Quote — form-filling backend (POC)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session store: session_id -> session dict.
sessions: dict[str, dict] = {}


def _get_service():
    service = getattr(app.state, "service", None)
    if service is not None:
        return service
    # Service backend is chosen independently of the LLM mock, so the offline
    # demo (MOCK_LLM=1) can still drive the real MCP -> WireMock chain by setting
    # QUOTE_SERVICE=mcp. Default: fake in MOCK mode, real MCP otherwise.
    backend = os.getenv("QUOTE_SERVICE", "fake" if os.getenv("MOCK_LLM") == "1" else "mcp")
    if backend == "mcp":
        return MCPQuoteService()
    return FakeQuoteService()


def _llm_client():
    if os.getenv("MOCK_LLM") == "1":
        return None
    from openai import OpenAI

    return OpenAI()


def _session(session_id: str) -> dict:
    return sessions.setdefault(
        session_id,
        {"country_code": "GB", "fields": {}, "schema": {}, "history": []},
    )


class ChatRequest(BaseModel):
    session_id: str
    message: str


class ConfirmRequest(BaseModel):
    session_id: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat")
async def chat(req: ChatRequest):
    session = _session(req.session_id)
    service = _get_service()
    client = _llm_client()

    async def event_stream():
        async for event in collect_turn(req.message, session, service, client=client):
            yield f"data: {json.dumps(event)}\n\n"
        yield 'data: {"type": "done"}\n\n'

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/upload")
async def upload(session_id: str = Form(...), file: UploadFile = File(...)):
    session = _session(session_id)
    service = _get_service()

    file_bytes = await file.read()
    extracted = extract_document(
        file_bytes,
        file.content_type or "application/octet-stream",
        file.filename or "",
        client=_llm_client(),
    )
    del file_bytes

    country = extracted["country_code"]
    fields = {k: v for k, v in extracted["fields"].items() if k != "_source"}
    session["country_code"] = country
    session["fields"].update(fields)
    session["schema"] = await service.get_quote_schema(country)

    return {
        "country_code": country,
        "fields": fields,
        "schema": session["schema"],
    }


@app.post("/confirm")
async def confirm(req: ConfirmRequest):
    session = sessions.get(req.session_id) or {}
    candidate = session.get("candidate")
    if not candidate:
        raise HTTPException(status_code=409, detail="No candidate to confirm yet.")

    service = _get_service()
    quote = await service.submit_quote_request(session["country_code"], candidate)
    link = await service.create_handoff_link(quote)
    return {
        "quote": quote,
        "handoff_url": link["handoff_url"],
        "guid": link["guid"],
    }
