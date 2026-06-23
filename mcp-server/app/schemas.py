"""Static, country-aware form schemas served to the LLM host.

The host calls ``get_schema(country_code)`` to learn which documents and fields
to collect for a detected country. No pricing or validation logic lives here —
just the declarative field list. Supported countries: GB (default) and FR.
"""

from __future__ import annotations

from app.models import ALLOWED_EXCESS, ALLOWED_FRANCHISE

SUPPORTED = ["GB", "FR"]

_GB_SCHEMA = {
    "country": "GB",
    "currency": "GBP",
    "documents": ["driving_licence", "renewal_notice"],
    "documents_required": True,
    "fields": [
        {"name": "registration", "label": "Vehicle registration",
         "type": "string", "required": True},
        {"name": "full_name", "label": "Full name",
         "type": "string", "required": True},
        {"name": "date_of_birth", "label": "Date of birth",
         "type": "date", "required": True},
        {"name": "postcode", "label": "Postcode",
         "type": "string", "required": True},
        {"name": "ncb_years", "label": "No-claims bonus (years)",
         "type": "integer", "required": True},
        {"name": "cover_tier", "label": "Cover level", "type": "enum",
         "required": False,
         "enum": ["comprehensive", "third_party_fire_theft", "third_party_only"],
         "default": "comprehensive"},
        {"name": "voluntary_excess", "label": "Voluntary excess (£)",
         "type": "enum", "required": False,
         "enum": ALLOWED_EXCESS, "default": 250},
    ],
}

_FR_SCHEMA = {
    "country": "FR",
    "currency": "EUR",
    "documents": ["carte_grise", "permis_de_conduire"],
    "documents_required": True,
    "fields": [
        {"name": "immatriculation", "label": "Plaque d'immatriculation",
         "type": "string", "required": True},
        {"name": "full_name", "label": "Nom complet",
         "type": "string", "required": True},
        {"name": "date_of_birth", "label": "Date de naissance",
         "type": "date", "required": True},
        {"name": "code_postal", "label": "Code postal",
         "type": "string", "required": True},
        {"name": "bonus_malus", "label": "Coefficient bonus-malus",
         "type": "number", "required": True},
        {"name": "formule", "label": "Formule", "type": "enum",
         "required": False,
         "enum": ["tous_risques", "tiers_plus", "au_tiers"],
         "default": "tous_risques"},
        {"name": "franchise", "label": "Franchise (€)", "type": "enum",
         "required": False, "enum": ALLOWED_FRANCHISE, "default": 300},
    ],
}

_SCHEMAS = {"GB": _GB_SCHEMA, "FR": _FR_SCHEMA}


def get_schema(country_code: str | None = "GB") -> dict:
    """Return the form schema for a country. Missing/empty -> GB. Normalises
    case. Unsupported -> an ``unsupported_country`` error dict."""
    cc = (country_code or "GB").upper()
    if cc not in _SCHEMAS:
        return {"country": cc, "supported": SUPPORTED, "error": "unsupported_country"}
    return _SCHEMAS[cc]
