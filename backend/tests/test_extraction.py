"""Greedy, question-anchored extraction (brief §4.1, §4.2, §17.1)."""

import os

import pytest

from app.extraction import extract_patch


@pytest.fixture(autouse=True)
def _mock_mode(monkeypatch):
    monkeypatch.setenv("MOCK_LLM", "1")


def test_anchored_bare_answer_maps_to_asked_field():
    # "8000" replying to the annual-mileage question must land on annualMileage,
    # NOT on vehicle.value (the §17.1 gotcha).
    patch = extract_patch("8000", asked_question="vehicle.annualMileage")
    assert patch == {"vehicle": {"annualMileage": 8000}}


def test_anchored_bare_answer_not_misread_as_value():
    patch = extract_patch("8000", asked_question="vehicle.value")
    # With the value anchor it is a value; the point is the anchor decides.
    assert patch == {"vehicle": {"value": 8000.0}}


def test_greedy_multi_fact_sentence_fills_several_fields():
    msg = "I'm Mr Sam Sample, born 1990-01-01, reg FX19 ZTC worth 12k, 8000 miles, 5 yrs NCD"
    patch = extract_patch(msg, asked_question=None)
    assert patch["customer"]["title"] == "Mr"
    assert patch["customer"]["firstName"] == "Sam"
    assert patch["customer"]["surname"] == "Sample"
    assert patch["customer"]["dateOfBirth"] == "1990-01-01"
    assert patch["vehicle"]["registration"] == "FX19ZTC"
    assert patch["vehicle"]["value"] == 12000.0
    assert patch["vehicle"]["annualMileage"] == 8000
    assert patch["driver"]["ncdYears"] == 5


def test_unrelated_facts_omitted():
    patch = extract_patch("the weather is nice today", asked_question=None)
    assert patch == {}


def test_bare_reply_with_anchor_still_extracts_volunteered_extra():
    # A short reply that also volunteers a postcode: anchor + greedy.
    patch = extract_patch("RG1 1AA", asked_question="customer.address.postcode")
    assert patch["customer"]["address"]["postcode"] == "RG1 1AA"


# --- Previously-unfillable fields: make / model / datePurchased (the loop bug).


def test_make_anchors_from_bare_reply():
    patch = extract_patch("Ford", asked_question="vehicle.make")
    assert patch == {"vehicle": {"make": "Ford"}}


def test_model_anchors_from_bare_reply():
    patch = extract_patch("Focus", asked_question="vehicle.model")
    assert patch == {"vehicle": {"model": "Focus"}}


def test_date_purchased_month_and_year():
    patch = extract_patch("June 2021", asked_question="vehicle.datePurchased")
    assert patch == {"vehicle": {"datePurchased": {"year": 2021, "month": 6}}}


def test_date_purchased_numeric_month_and_year():
    patch = extract_patch("06/2021", asked_question="vehicle.datePurchased")
    assert patch == {"vehicle": {"datePurchased": {"year": 2021, "month": 6}}}


def test_date_purchased_not_bought_yet():
    patch = extract_patch("not bought it yet", asked_question="vehicle.datePurchased")
    assert patch == {"vehicle": {"datePurchased": {"notBoughtYet": True}}}


# --- Natural (>3-word) replies still anchor instead of looping.


def test_natural_yes_reply_anchors_boolean():
    patch = extract_patch("yes I am the keeper", asked_question="vehicle.registeredKeeper")
    assert patch == {"vehicle": {"registeredKeeper": True}}


def test_natural_no_reply_anchors_boolean():
    patch = extract_patch("no it isn't", asked_question="vehicle.modified")
    assert patch == {"vehicle": {"modified": False}}


def test_natural_numeric_reply_anchors_mileage():
    patch = extract_patch("about 8000 a year", asked_question="vehicle.annualMileage")
    assert patch == {"vehicle": {"annualMileage": 8000}}
