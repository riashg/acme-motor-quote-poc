"""Country-aware deterministic MCP server: schema + lookup + quote + handoff.

No LLM runs here. The server tells the host which fields to collect for a
country (via the static schema), validates the collected input with the
country-specific pydantic model, builds the ACME request payload, and parses
ACME's response. It holds NO pricing logic — ACME owns premiums. Any text that
originated from a document is treated as data, never instructions.
"""

from __future__ import annotations

import html
import os
from datetime import date

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse

from app import schemas
from app.acme_client import AcmeClient
from app.models import FrQuoteInput, GbQuoteInput, Quote
from app.store import QuoteStore

mcp = FastMCP("acme-motor-quote", host="0.0.0.0", port=8090)

_acme = AcmeClient(base_url=os.getenv("ACME_BASE_URL", "http://localhost:8080"))
_store = QuoteStore()

CURRENCY = {"GB": "GBP", "FR": "EUR"}


def _today() -> date:
    return date.today()


def _age(dob: date, today: date) -> int:
    """Canonical birthday-aware age. Normalisation, not pricing."""
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def get_quote_schema(country_code: str = "GB") -> dict:
    """Return the field/document schema to collect for a country (GB or FR)."""
    return schemas.get_schema(country_code)


def lookup_vehicle(identifier: str, country_code: str = "GB") -> dict:
    """Look up a vehicle's details from its registration / immatriculation."""
    cc = (country_code or "GB").upper()
    vehicle = _acme.lookup_vehicle(identifier, cc)
    if vehicle is None:
        ident = identifier.strip().upper().replace(" ", "")
        return {"found": False, "country_code": cc, "identifier": ident}
    return {"found": True, "country_code": cc, **vehicle.model_dump()}


def submit_quote_request(country_code: str, data: dict) -> dict:
    """Validate the collected form, build the ACME payload, and price it."""
    cc = (country_code or "GB").upper()
    if cc not in CURRENCY:
        return {"error": "unsupported_country", "country_code": cc}

    today = _today()
    if cc == "GB":
        qi = GbQuoteInput.model_validate(data)
        payload = {
            "identifier": qi.vehicle.identifier,
            "insurance_group": qi.vehicle.insurance_group,
            "age": _age(qi.driver.date_of_birth, today),
            "ncb_years": qi.driver.ncb_years,
            "cover_tier": qi.cover_tier.value,
            "voluntary_excess": qi.voluntary_excess,
        }
    else:  # FR — rates on the bonus-malus coefficient, not derived age
        qi = FrQuoteInput.model_validate(data)
        payload = {
            "identifier": qi.vehicle.identifier,
            "value": qi.vehicle.value,
            "bonus_malus": qi.driver.bonus_malus,
            "formule": qi.formule.value,
            "franchise": qi.franchise,
        }

    resp = _acme.get_quote(cc, payload)
    annual = round(float(resp["annual_premium"]), 2)
    quote = Quote(
        quote_ref=str(resp["quote_ref"]),
        currency=CURRENCY[cc],
        annual_premium=annual,
        monthly_premium=round(annual / 12, 2),
        country_code=cc,
        input=qi.model_dump(mode="json"),
    )
    return quote.model_dump(mode="json")


def create_handoff_link(quote: dict) -> dict:
    """Store a quote and mint a non-enumerable GUID handoff link."""
    q = Quote.model_validate(quote)
    guid = _store.save(q)
    base = os.getenv("PUBLIC_BASE_URL", "http://localhost:8090").rstrip("/")
    return {"guid": guid, "handoff_url": f"{base}/handoff/{guid}"}


mcp.tool()(get_quote_schema)
mcp.tool()(lookup_vehicle)
mcp.tool()(submit_quote_request)
mcp.tool()(create_handoff_link)


def _quote_html(q: Quote) -> str:
    v = q.input.get("vehicle", {})
    make = html.escape(str(v.get("make", "")))
    model = html.escape(str(v.get("model", "")))
    year = html.escape(str(v.get("year", "")))
    identifier = html.escape(str(v.get("identifier", "")))
    currency = html.escape(q.currency)
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>ACME Motor Quote</title></head>
<body style="font-family:sans-serif;background:#f7f7fb;padding:40px">
  <div style="max-width:480px;margin:auto;background:#fff;border-radius:12px;
       border-left:6px solid #00008f;padding:24px">
    <div style="color:#00008f;font-weight:700">ACME Motor Quote</div>
    <div style="opacity:.7">{make} {model} ({year}) &middot; {identifier}</div>
    <div style="font-size:34px;font-weight:800;margin:12px 0">
      {currency} {q.annual_premium:.2f}<span style="font-size:14px;font-weight:400"> /year</span></div>
    <div style="color:#ff1721">{currency} {q.monthly_premium:.2f} /month</div>
    <div style="font-size:11px;opacity:.6;margin-top:12px">
      Quote ref {html.escape(q.quote_ref)}. Illustrative demo &mdash; mock data only, not a binding ACME quote.</div>
  </div></body></html>"""


@mcp.custom_route("/handoff/{guid}", methods=["GET"])
async def handoff(request: Request) -> HTMLResponse:
    guid = request.path_params["guid"]
    quote = _store.get(guid)
    if quote is None:
        return HTMLResponse("<h1>Quote not found or expired</h1>", status_code=404)
    return HTMLResponse(_quote_html(quote))


def main() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
