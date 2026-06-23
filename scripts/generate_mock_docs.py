#!/usr/bin/env python3
"""Generate synthetic, OCR-able mock documents for the ACME quote demo.

These are SAMPLE documents with synthetic data only — not real policies and not
connected to any real ACME / DVLA / ANTS system. They give the customer something
to upload (a renewal notice / policy / carte grise) so the assistant can extract
the fields. The data matches the demo's seeded vehicles (GB AB12CDE, FR AB123CD).

Run (no permanent dependency needed — reportlab is fetched ephemerally by uv):

    uv run --no-project --with reportlab python scripts/generate_mock_docs.py [OUTPUT_DIR]

OUTPUT_DIR defaults to ./mock-docs/.
"""

from __future__ import annotations

import sys
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

_ACME_BLUE = (0.0, 0.0, 0.56)


def _doc(path: Path, header: str, subtitle: str, rows: list[tuple[str, str]], footer: str) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    w, h = A4
    # Header band
    c.setFillColorRGB(*_ACME_BLUE)
    c.rect(0, h - 30 * mm, w, 30 * mm, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 22)
    c.drawString(20 * mm, h - 17 * mm, "ACME Insurance")
    c.setFont("Helvetica", 11)
    c.drawString(20 * mm, h - 24 * mm, header)
    # Body
    c.setFillColorRGB(0.1, 0.1, 0.18)
    y = h - 45 * mm
    c.setFont("Helvetica-Bold", 14)
    c.drawString(20 * mm, y, subtitle)
    y -= 12 * mm
    for label, value in rows:
        c.setFont("Helvetica", 10)
        c.setFillColorRGB(0.42, 0.42, 0.48)
        c.drawString(20 * mm, y, label)
        c.setFont("Helvetica-Bold", 12)
        c.setFillColorRGB(0.1, 0.1, 0.18)
        c.drawString(85 * mm, y, value)
        y -= 9 * mm
    c.setFont("Helvetica-Oblique", 8)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.drawString(20 * mm, 14 * mm, footer)
    c.showPage()
    c.save()


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("mock-docs")
    out.mkdir(parents=True, exist_ok=True)

    _doc(
        out / "uk-renewal-notice.pdf",
        "Motor Policy Renewal Notice",
        "Your renewal — please review your details",
        [
            ("Policy number", "ACME-MTR-2026-001234"),
            ("Policyholder", "Jane Doe"),
            ("Date of birth", "01 May 1990"),
            ("Address", "10 Example Street, London"),
            ("Postcode", "SW1A 1AA"),
            ("Vehicle registration", "AB12 CDE"),
            ("Make / Model", "Volkswagen Golf (2019)"),
            ("No Claims Bonus", "5 years"),
            ("Cover", "Comprehensive"),
            ("Voluntary excess", "GBP 250"),
            ("Last year's premium", "GBP 412.50"),
        ],
        "SAMPLE / synthetic data only — not a real policy, not connected to any real ACME system.",
    )

    _doc(
        out / "uk-policy.pdf",
        "Certificate of Motor Insurance",
        "Policy summary",
        [
            ("Policy number", "ACME-MTR-2025-009988"),
            ("Policyholder", "Jane Doe"),
            ("Date of birth", "01 May 1990"),
            ("Postcode", "SW1A 1AA"),
            ("Vehicle registration", "AB12 CDE"),
            ("Make / Model", "Volkswagen Golf (2019)"),
            ("No Claims Bonus", "5 years"),
            ("Cover", "Comprehensive"),
        ],
        "SAMPLE / synthetic data only — not a real policy.",
    )

    _doc(
        out / "fr-carte-grise.pdf",
        "Certificat d'immatriculation (carte grise)",
        "Certificat — exemple",
        [
            ("Immatriculation", "AB123CD"),
            ("Titulaire", "Jean Dupont"),
            ("Date de naissance", "10 mars 1985"),
            ("Adresse", "1 Rue de Rivoli, Paris"),
            ("Code postal", "75001"),
            ("Marque / Modele", "Renault Clio (2020)"),
            ("Coefficient bonus-malus", "0,90"),
            ("Formule", "Tous risques"),
            ("Franchise", "300 EUR"),
        ],
        "EXEMPLE / donnees fictives — document non officiel.",
    )

    print("Generated mock documents in", out.resolve())
    for p in sorted(out.glob("*.pdf")):
        print("  -", p.name)


if __name__ == "__main__":
    main()
