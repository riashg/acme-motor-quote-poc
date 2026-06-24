"""Document-assisted extraction (brief §4.4, §4.5, §13, §17.8).

LLM-backed extraction over the whole-model schema. MOCK mode infers the doc type
from filename/first-bytes and returns a canned, fixture-consistent patch; live
mode parses a JSON patch from an OpenAI vision client. Image (PNG) and PDF are
both first-class. The accompanying instruction can re-route to a named driver.
"""

import json

import pytest

from app.documents import extract_document
from app.extraction import whole_model_schema


@pytest.fixture(autouse=True)
def _mock_mode(monkeypatch):
    monkeypatch.setenv("MOCK_LLM", "1")


def _paths(patch: dict, prefix: str = "") -> list[str]:
    out: list[str] = []
    for key, value in (patch or {}).items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.extend(_paths(value, path))
        else:
            out.append(path)
    return out


# --- MOCK extraction by document type ---------------------------------------


def test_mock_renewal_doc_fills_vehicle_cover_ncd():
    result = extract_document(
        b"%PDF-1.4 renewal",
        "application/pdf",
        "uk-renewal-notice.pdf",
        "",
        whole_model_schema(),
        client=None,
    )
    assert result["source"] == "document"
    assert result["target"] == "applicant"
    patch = result["patch"]
    paths = _paths(patch)
    assert "vehicle.registration" in paths
    assert "vehicle.make" in paths
    assert "vehicle.value" in paths
    assert "cover.coverLevel" in paths
    assert "cover.voluntaryExcess" in paths
    assert "driver.ncdYears" in paths
    assert "history.claimsLast3Years" in paths
    # Fixture-consistent (FX19ZTC / Ford Focus).
    assert patch["vehicle"]["registration"] == "FX19ZTC"


def test_mock_policy_doc_also_fills_vehicle():
    result = extract_document(
        b"%PDF policy", "application/pdf", "uk-policy.pdf", "", whole_model_schema()
    )
    assert "vehicle.registration" in _paths(result["patch"])


def test_mock_licence_doc_fills_identity_and_licence():
    result = extract_document(
        b"\x89PNG fake",
        "image/png",
        "uk-driving-licence.png",
        "",
        whole_model_schema(),
        client=None,
    )
    patch = result["patch"]
    paths = _paths(patch)
    assert "customer.title" in paths
    assert "customer.firstName" in paths
    assert "customer.surname" in paths
    assert "customer.dateOfBirth" in paths
    assert "driver.licenceType" in paths
    assert "driver.licenceHeldFor" in paths
    # Fixture-consistent identity.
    assert patch["customer"]["firstName"] == "Sam"
    assert patch["customer"]["dateOfBirth"] == "1990-01-01"


def test_mock_licence_handles_pdf_content_type():
    """A photographed/scanned licence may arrive as a PDF (brief §17.8)."""
    result = extract_document(
        b"%PDF licence",
        "application/pdf",
        "uk-driving-licence.pdf",
        "",
        whole_model_schema(),
    )
    assert "customer.firstName" in _paths(result["patch"])


def test_mock_infers_licence_from_bytes_when_filename_generic():
    result = extract_document(
        b"DRIVING LICENCE DVLA 1. SAMPLE",
        "image/jpeg",
        "scan.jpg",
        "",
        whole_model_schema(),
    )
    assert "driver.licenceType" in _paths(result["patch"])


# --- Instruction routing (brief §4.5) ---------------------------------------


def test_named_driver_instruction_routes_and_shapes_person():
    result = extract_document(
        b"\x89PNG fake",
        "image/png",
        "uk-driving-licence.png",
        "add this as a named driver",
        whole_model_schema(),
    )
    assert result["target"] == "named_driver"
    person = result["patch"]
    # Patch is a single named-driver person, NOT nested on the applicant.
    assert "customer" not in person
    assert person["firstName"]
    assert person["surname"]
    assert person["dateOfBirth"]


def test_no_instruction_keeps_applicant_target():
    result = extract_document(
        b"\x89PNG", "image/png", "uk-driving-licence.png", "please use this", whole_model_schema()
    )
    assert result["target"] == "applicant"
    assert "customer" in result["patch"]


# --- Live mode (stubbed vision client) --------------------------------------


class _StubVisionClient:
    """Minimal OpenAI-shaped stub: records the call, returns a fixed JSON patch."""

    def __init__(self, content: str):
        self._content = content
        self.calls: list[dict] = []
        self.chat = self  # so client.chat.completions.create works
        self.completions = self

    def create(self, **kwargs):
        self.calls.append(kwargs)

        class _Msg:
            def __init__(self, c):
                self.message = type("M", (), {"content": c})

        return type("R", (), {"choices": [_Msg(self._content)]})


def test_live_stub_parses_json_patch_and_sets_source(monkeypatch):
    monkeypatch.delenv("MOCK_LLM", raising=False)
    client = _StubVisionClient(json.dumps({"vehicle": {"registration": "FX19ZTC"}}))
    result = extract_document(
        b"\x89PNG bytes",
        "image/png",
        "licence.png",
        "",
        whole_model_schema(),
        client=client,
    )
    assert result["patch"]["vehicle"]["registration"] == "FX19ZTC"
    assert result["source"] == "document"
    # The image was sent as a base64 data URL to the vision model.
    sent = json.dumps(client.calls[0])
    assert "data:image/png;base64," in sent


def test_live_stub_sends_pdf_as_data_url(monkeypatch):
    monkeypatch.delenv("MOCK_LLM", raising=False)
    client = _StubVisionClient(json.dumps({"customer": {"firstName": "Sam"}}))
    extract_document(
        b"%PDF bytes", "application/pdf", "licence.pdf", "", whole_model_schema(), client=client
    )
    sent = json.dumps(client.calls[0])
    assert "data:application/pdf;base64," in sent


def test_live_named_driver_instruction_routes_target(monkeypatch):
    monkeypatch.delenv("MOCK_LLM", raising=False)
    client = _StubVisionClient(json.dumps({"firstName": "Alex", "surname": "Sample"}))
    result = extract_document(
        b"\x89PNG",
        "image/png",
        "licence.png",
        "add this person as a named driver",
        whole_model_schema(),
        client=client,
    )
    assert result["target"] == "named_driver"
    assert result["patch"]["firstName"] == "Alex"
