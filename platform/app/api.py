"""ACME Mock Motor Quote Platform — FastAPI app.

Implements the three-layer discipline foundation:
    (tool fn) -> platform API fn (logs request+response via record_api_call)
             -> mutate state + append domain event.

State (quotes etc.) arrives in a later slice; this is the clean,
front-end-agnostic foundation: HTTP in, events out.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Body, FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles

from app.channel import router as channel_router
from app.demo import DEMO_QUOTE_ID, ensure_demo_seeded
from app.events import store
from app.quote_service import apply_patch, create_quote, get_quote
from app.vendor import vendor


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Self-seed the stable demo quote so it is always resolvable (brief §9).
    ensure_demo_seeded()
    yield


app = FastAPI(title="ACME Mock Motor Quote Platform", lifespan=lifespan)
app.include_router(channel_router)

# Serve the live operational dashboard (brief §14) same-origin at /dashboard so
# it can use the SSE/WS channel without CORS. Mounted under a sub-path so it
# never shadows the API routes. Guarded so the app/tests still load if the
# dashboard dir is absent. Path: <repo>/platform/app/api.py -> <repo>/dashboard.
_DASHBOARD_DIR = Path(__file__).resolve().parents[2] / "dashboard"
if _DASHBOARD_DIR.is_dir():
    app.mount(
        "/dashboard",
        StaticFiles(directory=str(_DASHBOARD_DIR), html=True),
        name="dashboard",
    )


def record_api_call(name: str, request, response) -> None:
    """API layer primitive: log an API call's request + response.

    Appends an ``API_CALL`` event (category ``"api"``) so every call
    crossing the platform boundary is observable on the live channel.
    """
    store.append(
        "API_CALL",
        {"api": name, "request": request, "response": response},
        "api",
    )


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/ping")
async def ping(body: Optional[dict] = Body(default=None)) -> dict:
    request = body or {}
    result = {"pong": True, "echo": request}

    # API layer: log request + response.
    record_api_call("ping", request, result)

    # Domain layer: mutate state (none yet) + append a domain event.
    store.append("PING", {"echo": request}, "domain")

    return result


# ----------------------------------------------------------------------------
# Slice 2 — session-scoped quote creation (three-layer discipline).
# Each route logs an API_CALL (request + response) via record_api_call, then
# the service mutates state + appends the QUOTE_* domain event.
# ----------------------------------------------------------------------------


@app.post("/quotes", status_code=201)
async def post_quote() -> dict:
    """Create a draft quote. Returns quoteId, sessionId, journeyState, missingFields."""
    result = create_quote()  # emits QUOTE_CREATED (domain)
    # API layer log must not leak the sessionId beyond the creator.
    record_api_call("create_quote", {}, {k: v for k, v in result.items() if k != "sessionId"})
    return result


@app.get("/quotes/{quote_id}")
async def get_quote_route(
    quote_id: str,
    x_session_id: Optional[str] = Header(default=None),
) -> dict:
    """Retrieve a quote. Requires X-Session-Id; 404 on unknown id or mismatch."""
    if quote_id == DEMO_QUOTE_ID:
        # Self-seed the stable demo quote on first access (brief §9, §17.7).
        ensure_demo_seeded()
    state = get_quote(quote_id, x_session_id or "")
    record_api_call(
        "get_quote",
        {"quoteId": quote_id},
        state if state is not None else {"error": "not_found"},
    )
    if state is None:
        # Do not reveal whether the quote exists.
        raise HTTPException(status_code=404, detail="Quote not found")
    return state


@app.patch("/quotes/{quote_id}")
async def patch_quote_route(
    quote_id: str,
    body: dict = Body(default_factory=dict),
    x_session_id: Optional[str] = Header(default=None),
) -> dict:
    """Apply a partial patch. Body: {"patch": {...}}. 404 on mismatch."""
    patch = (body or {}).get("patch", {})
    state = apply_patch(quote_id, x_session_id or "", patch)  # emits QUOTE_UPDATED
    record_api_call(
        "update_quote",
        {"quoteId": quote_id, "patch": patch},
        state if state is not None else {"error": "not_found"},
    )
    if state is None:
        raise HTTPException(status_code=404, detail="Quote not found")
    return state


@app.get("/vehicles/{registration}")
async def lookup_vehicle_route(registration: str) -> dict:
    """Vehicle lookup via the vendor SOAP seam (no session required)."""
    result = vendor.lookup_vehicle(registration)
    record_api_call("lookup_vehicle", {"registration": registration}, result)
    if result is None:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return result


@app.get("/addresses")
async def lookup_address_route(postcode: str) -> dict:
    """Address candidates via the vendor SOAP seam (no session required)."""
    candidates = vendor.lookup_address(postcode)
    result = {"postcode": postcode, "candidates": candidates}
    record_api_call("lookup_address", {"postcode": postcode}, result)
    return result
