"""ACME Motor Quote MCP server — the integration layer over the platform.

The Python platform (``PLATFORM_URL``, default ``http://localhost:8070``) is the
**source of truth**: it owns quote state, the journey, validation, pricing and
underwriting. This MCP exposes typed, host-agnostic tools over that contract so
the same server backs both our web app and a ChatGPT App (brief §8).

Design (brief §8):
  * **Stateless** — the platform owns state. The conversation layer holds the
    ``quoteId`` + ``sessionId`` and passes them on every call; we never cache them.
  * **Idempotent** — tools are thin pass-throughs to the platform API.
  * **Session security** — quote state is retrievable only with the matching
    ``sessionId`` (carried as ``X-Session-Id`` by the client); the platform
    returns 404 on cross-session access.

No pricing or underwriting logic lives here — the conversation must never invent
premiums, cover or outcomes.
"""

from __future__ import annotations

import base64
import binascii
import re
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from app.platform_client import PlatformClient

# Server-level guidance for the host LLM driving the journey (brief §7 / §16).
_INSTRUCTIONS = (
    "ACME motor-insurance new-quote assistant. The platform is the source of "
    "truth: use tool responses as fact and NEVER invent premiums, cover, "
    "underwriting outcomes, or whether a quote can be priced.\n"
    "Flow:\n"
    "1) Call start_motor_quote() once to create a draft. Keep the returned "
    "quoteId AND sessionId for the whole conversation and pass BOTH on every "
    "get/update call — they are the only key to this quote's state.\n"
    "2) Collect details greedily and in ANY order: fill as many fields at once "
    "as the user gives you. Do not enforce a question order. Send everything you "
    "confidently know via update_motor_quote(quote_id, session_id, patch) using a "
    "partial, multi-field patch.\n"
    "3) The platform decides what is still required: drive the conversation from "
    "the returned missingFields and journeyState. Ask only for what is still "
    "missing. When journeyState is ready_to_price, the quote is complete.\n"
    "4) Use lookup_vehicle(registration) to resolve make/model and "
    "lookup_address(postcode) to resolve an address; confirm with the user "
    "before storing.\n"
    "5) When missingFields is empty (the quote is complete), call "
    "price_motor_quote(quote_id, session_id). The pricing comes ONLY from this "
    "tool — never invent a premium. Read the response 'outcome':\n"
    "   - 'quote': share the annualPremium (and monthly figures), excesses and "
    "the breakdown exactly as returned, then offer to proceed.\n"
    "   - 'refer' or 'decline': explain using the returned 'reasons' verbatim; "
    "do NOT invent a price or a reason, and do not offer to purchase.\n"
    "   (price_motor_quote may return an error dict with missingFields if the "
    "quote is not yet complete — go back and collect those fields.)\n"
    "6) Only if the outcome is a clean 'quote' and the user wants to proceed, "
    "call generate_purchase_link(quote_id, session_id) and give the user the "
    "returned purchaseUrl so they can pay.\n"
    "7) Only after the user explicitly confirms, call "
    "issue_policy(quote_id, session_id) and report the returned policyNumber, "
    "status and effectiveDate. (generate_purchase_link / issue_policy return an "
    "error dict on 409 if the quote is not a clean quote — surface that, do not "
    "fabricate a policy.)\n"
    "8) For renewals, claims, multi-vehicle, cancellations or any journey other "
    "than a new motor quote, tell the user to visit ACME's website instead."
)

mcp = FastMCP(
    "acme-motor-quote", host="0.0.0.0", port=8090, instructions=_INSTRUCTIONS
)

# Module-level platform client (tests monkeypatch this with a fake).
_platform = PlatformClient()

# --- MCP Apps UI widget (ext-apps spec 2026-01-26) ----------------------------
# A tool can declare a UI resource; an ext-apps-aware host fetches the HTML and
# renders it in a sandboxed iframe, then pushes the tool result to it. The HTML
# is host-agnostic and talks raw JSON-RPC over postMessage (no SDK dependency).
_UI_MIME = "text/html;profile=mcp-app"  # ext-apps RESOURCE_MIME_TYPE
_QUOTE_CARD_URI = "ui://acme-motor-quote/quote-card.html"
_DOC_UPLOAD_URI = "ui://acme-motor-quote/document-upload.html"
_WIDGETS_DIR = Path(__file__).parent / "widgets"

# A clean £430 sample quote (base £350 + comprehensive £80) — the same shape the
# platform's price tool returns, so the widget renders mock or live data alike.
_MOCK_PRICING = {
    "annualPremium": 430.0,
    "currency": "GBP",
    "iptIncluded": True,
    "monthly": {"deposit": 43.0, "instalment": 43.0, "instalments": 10},
    "compulsoryExcess": 350,
    "voluntaryExcess": 250,
    "totalExcess": 600,
    "ncdYears": 5,
    "outcome": "quote",
    "reasons": [],
    "breakdown": [
        {"label": "Base premium", "amount": 350.0},
        {"label": "Comprehensive cover", "amount": 80.0},
    ],
}


def _load_widget(name: str) -> str:
    """Read a widget's HTML from app/widgets (per-call, so edits show live)."""
    return (_WIDGETS_DIR / name).read_text(encoding="utf-8")


# --- Mock document extraction (mirrors backend/app/documents.py canned patches) ---
# The MCP server is LLM-free; real extraction (vision) lives in the Python
# backend. For the upload widget demo, we return the same fixture-consistent
# patches deterministically, routed by filename + instruction.
_NAMED_DRIVER_RE = re.compile(r"\bnamed\s+driver\b|\badd\b.*\bdriver\b", re.IGNORECASE)
_LICENCE_HINTS = ("licence", "license", "driving", "dvla")


def _is_named_driver(instruction: str | None) -> bool:
    return bool(instruction and _NAMED_DRIVER_RE.search(instruction))


def _doc_type(filename: str) -> str:
    """Infer 'licence' | 'renewal' from the filename (renewal is the default)."""
    name = (filename or "").lower()
    return "licence" if any(h in name for h in _LICENCE_HINTS) else "renewal"


def _mock_renewal_patch() -> dict:
    return {
        "vehicle": {"registration": "FX19ZTC", "make": "Ford", "model": "Focus", "value": 12000},
        "cover": {"coverLevel": "Comprehensive", "voluntaryExcess": 250},
        "driver": {"ncdYears": 5},
        "history": {"claimsLast3Years": 0, "offencesLast5Years": 0},
    }


def _mock_licence_applicant_patch() -> dict:
    return {
        "customer": {
            "title": "Mr", "firstName": "Sam", "surname": "Sample",
            "dateOfBirth": "1990-01-01",
            "address": {"houseNumberOrName": "10", "postcode": "RG1 1AA"},
        },
        "driver": {"licenceType": "Full UK", "licenceHeldFor": 15},
    }


def _mock_licence_named_driver_patch() -> dict:
    return {
        "title": "Mr", "firstName": "Sam", "surname": "Sample",
        "dateOfBirth": "1990-01-01", "relationshipToPolicyholder": "Partner",
        "licenceType": "Full UK", "licenceHeldFor": 15,
    }


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


def start_motor_quote() -> dict:
    """Create a new draft motor quote.

    Returns the quoteId, sessionId, journeyState and missingFields. The caller
    must retain the quoteId and sessionId for the rest of the conversation.
    """
    return _platform.start_quote()


def get_motor_quote(quote_id: str, session_id: str) -> dict:
    """Return the current state (journeyState, missingFields, outcome) of a quote.

    Requires the sessionId issued by start_motor_quote; a mismatch is rejected.
    """
    return _platform.get_quote(quote_id, session_id)


def update_motor_quote(quote_id: str, session_id: str, patch: dict) -> dict:
    """Apply a partial, multi-field patch and return the recomputed state.

    The patch may touch any subset of fields in any order; the platform
    deep-merges it, never blanking untouched data. Requires the matching sessionId.
    """
    return _platform.update_quote(quote_id, session_id, patch)


def price_motor_quote(quote_id: str, session_id: str) -> dict[str, Any]:
    """Price a completed quote and return the pricing object.

    Returns the platform's pricing (annualPremium, monthly, excesses, ncdYears,
    outcome, reasons, breakdown). If the quote is incomplete the platform
    returns an error dict with missingFields instead of raising — surface that
    and collect the missing fields. Never invent a premium or outcome; they come
    only from this tool. Requires the matching sessionId.

    The ``dict[str, Any]`` return makes FastMCP emit ``structuredContent`` so the
    linked quote-card UI widget renders the priced quote (or the not-ready /
    refer / decline state) in a capable host.
    """
    return _platform.price(quote_id, session_id)


def generate_purchase_link(quote_id: str, session_id: str) -> dict:
    """Generate a purchase link for a clean quote.

    Returns {purchaseToken, purchaseUrl} to hand to the user. Only valid when
    the quote's outcome is a clean 'quote'; otherwise the platform returns an
    error dict (409) which must be surfaced, not fabricated. Requires the
    matching sessionId.
    """
    return _platform.generate_purchase_link(quote_id, session_id)


def issue_policy(quote_id: str, session_id: str) -> dict:
    """Issue a policy for a clean quote after the user confirms.

    Returns {policyNumber, status, effectiveDate}. Only valid when the quote's
    outcome is a clean 'quote'; otherwise the platform returns an error dict
    (409) which must be surfaced. This is not idempotent. Requires the matching
    sessionId.
    """
    return _platform.issue_policy(quote_id, session_id)


def lookup_vehicle(registration: str) -> dict:
    """Resolve a vehicle (make/model/derivative/fuel/transmission) from its registration."""
    return _platform.lookup_vehicle(registration)


def lookup_address(postcode: str) -> dict:
    """Resolve candidate addresses from a UK postcode."""
    return _platform.lookup_address(postcode)


def display_quote_card(quote_id: str | None = None) -> dict[str, Any]:
    """Return a sample motor quote and render it in the quote-card UI widget.

    A demo of the MCP Apps UI surface: the returned pricing object is delivered
    to the linked ``ui://acme-motor-quote/quote-card.html`` widget as structured
    output (the ``dict[str, Any]`` return makes FastMCP emit ``structuredContent``,
    which the widget reads from the host's ``tool-result`` notification). Mock
    data only — not a real or binding quote.
    """
    return dict(_MOCK_PRICING)


@mcp.resource(
    _QUOTE_CARD_URI,
    name="quote-card",
    title="ACME quote card",
    mime_type=_UI_MIME,
)
def quote_card_widget() -> str:
    """The HTML for the quote-card UI widget (MCP Apps UI resource)."""
    return _load_widget("quote_card.html")


def open_document_upload(
    quote_id: str | None = None, session_id: str | None = None
) -> dict[str, Any]:
    """Open the document-upload widget to attach a policy, renewal or licence.

    Renders the upload UI (linked via ``_meta.ui.resourceUri``). Any quoteId /
    sessionId are passed through as structured output so the widget can forward
    them to ``extract_document`` and apply the result to the right quote.
    """
    return {
        "quoteId": quote_id,
        "sessionId": session_id,
        "accepts": ["application/pdf", "image/*"],
    }


def _received_bytes(file_base64: str | None) -> int:
    """Decode the uploaded base64 to count the bytes the server received.

    Proves the file physically reached the server. We do NOT parse or persist it
    (real extraction lives in the backend); the raw bytes are dropped immediately.
    """
    if not file_base64:
        return 0
    try:
        return len(base64.b64decode(file_base64, validate=False))
    except (binascii.Error, ValueError):
        return 0


def extract_document(
    filename: str,
    instruction: str = "",
    file_base64: str | None = None,
    content_type: str | None = None,
    quote_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Extract a quote patch from an uploaded document and report what was found.

    The widget uploads the file as base64 in ``file_base64``; the server decodes
    it to confirm receipt (``receivedBytes``) but does NOT parse or store it —
    real vision extraction lives in the conversation backend. The returned patch
    is MOCK, routed on ``filename`` (licence vs renewal/policy) and ``instruction``
    (a "named driver" request). When a ``quote_id``/``session_id`` is given, the
    patch is applied to the platform (named drivers are appended, never
    overwriting the applicant) and the recomputed ``missingFields``/
    ``journeyState`` are returned. Mock data only.
    """
    received = _received_bytes(file_base64)
    named = _is_named_driver(instruction)

    if _doc_type(filename) == "licence" and named:
        person = _mock_licence_named_driver_patch()
        result: dict[str, Any] = {
            "filename": filename,
            "contentType": content_type,
            "receivedBytes": received,
            "extracted": _flatten_paths(person),
            "patch": {"namedDrivers": [person]},
            "applied": [],
            "target": "named_driver",
            "echo": f"✓ Added named driver {person['firstName']} {person['surname']}",
            "missingFields": [],
            "journeyState": None,
        }
        if quote_id and session_id:
            current = _platform.get_quote(quote_id, session_id) or {}
            drivers = list(current.get("namedDrivers", []))
            drivers.append(person)
            state = _platform.update_quote(quote_id, session_id, {"namedDrivers": drivers})
            result["applied"] = ["namedDrivers[]"]
            result["missingFields"] = state.get("missingFields", [])
            result["journeyState"] = state.get("journeyState")
        return result

    patch = _mock_licence_applicant_patch() if _doc_type(filename) == "licence" else _mock_renewal_patch()
    paths = _flatten_paths(patch)
    result = {
        "filename": filename,
        "contentType": content_type,
        "receivedBytes": received,
        "extracted": paths,
        "patch": patch,
        "applied": [],
        "target": "applicant",
        "echo": "✓ " + ", ".join(paths[:2]) + (f", +{len(paths) - 2} more" if len(paths) > 2 else ""),
        "missingFields": [],
        "journeyState": None,
    }
    if quote_id and session_id:
        state = _platform.update_quote(quote_id, session_id, patch)
        result["applied"] = paths
        result["missingFields"] = state.get("missingFields", [])
        result["journeyState"] = state.get("journeyState")
    return result


@mcp.resource(
    _DOC_UPLOAD_URI,
    name="document-upload",
    title="ACME document upload",
    mime_type=_UI_MIME,
)
def document_upload_widget() -> str:
    """The HTML for the document-upload UI widget (MCP Apps UI resource)."""
    return _load_widget("document_upload.html")


# Register tools with Apps-SDK annotations. Reads are read-only; start/update
# change state (non-read-only). start/lookups reach beyond the closed model
# (the platform / vendor seam), so they are open-world.
mcp.tool(
    annotations=ToolAnnotations(
        title="Start motor quote",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    )
)(start_motor_quote)
mcp.tool(
    annotations=ToolAnnotations(title="Get motor quote", readOnlyHint=True)
)(get_motor_quote)
mcp.tool(
    annotations=ToolAnnotations(
        title="Update motor quote",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
    )
)(update_motor_quote)
mcp.tool(
    annotations=ToolAnnotations(
        title="Price motor quote",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
    # Render the priced quote in the quote-card UI widget (MCP Apps): when the
    # quote is complete this shows the live premium; otherwise the not-ready state.
    meta={"ui": {"resourceUri": _QUOTE_CARD_URI}},
)(price_motor_quote)
mcp.tool(
    annotations=ToolAnnotations(
        title="Generate purchase link",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    )
)(generate_purchase_link)
mcp.tool(
    annotations=ToolAnnotations(
        title="Issue policy",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    )
)(issue_policy)
mcp.tool(
    annotations=ToolAnnotations(
        title="Look up vehicle", readOnlyHint=True, openWorldHint=True
    )
)(lookup_vehicle)
mcp.tool(
    annotations=ToolAnnotations(
        title="Look up address", readOnlyHint=True, openWorldHint=True
    )
)(lookup_address)
# Linked to its UI widget via _meta.ui.resourceUri (MCP Apps): a capable host
# renders the quote card instead of raw JSON.
mcp.tool(
    annotations=ToolAnnotations(title="Display quote card", readOnlyHint=True),
    meta={"ui": {"resourceUri": _QUOTE_CARD_URI}},
)(display_quote_card)
# Launcher for the document-upload widget (carries the UI link); the widget then
# calls extract_document to do the work.
mcp.tool(
    annotations=ToolAnnotations(title="Open document upload", readOnlyHint=True),
    meta={"ui": {"resourceUri": _DOC_UPLOAD_URI}},
)(open_document_upload)
# Mock document extraction; applies to the quote when a session is supplied. Not
# read-only (it can mutate quote state via the platform).
mcp.tool(
    annotations=ToolAnnotations(
        title="Extract document",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )
)(extract_document)


def main() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
