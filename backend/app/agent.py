"""Conversation turn driver (brief §4.1, §4.6, §4.7, §4.8, §6).

``collect_turn`` is an async generator that drives ONE customer turn:

1. Extract a greedy, question-anchored whole-model patch from the message.
2. ``reconcile`` it against the current quote (the backend's merged copy).
3. Apply the non-conflicting part via the platform's ``update`` and adopt the
   recomputed ``missingFields`` / ``journeyState`` (the backend owns the journey
   — brief §6; the platform decides what is still required).
4. If there are conflicts, emit a ``conflict`` event (offer both values as chips)
   and stop — never silently overwrite (brief §4.6).
5. Otherwise emit a brief confirmation echo (brief §4.8) and ask the next missing
   field, or announce ``ready_to_price`` when the model is complete.

A correction is just another patch (brief §4.7): re-running the same path with a
new value flows through reconcile → conflict (if it clashes) or apply.

The conversation layer owns conversation only; nothing here prices or validates.
Front-end-agnostic: emits plain event dicts, no web/ChatGPT assumptions.
"""

from __future__ import annotations

from typing import Optional

from app.conflict import KEEP_CURRENT, reconcile, resolve_conflict
from app.extraction import extract_patch
from app.quote_session_client import deep_merge, gap_fill_patch

# Human-readable label + the question string (== the anchor dot-path) for each
# mandatory field, so the agent can ask the next gap and anchor the next reply.
_FIELD_PROMPTS: dict[str, str] = {
    "vehicle.registration": "What's your car's registration?",
    "vehicle.make": "What's the make of your car?",
    "vehicle.model": "What's the model of your car?",
    "vehicle.datePurchased": "When did you buy the car (month and year), or have you not bought it yet?",
    "vehicle.value": "Roughly what is the car worth (£)?",
    "vehicle.useOfVehicle": "How do you use the car — social only, social + commuting, or business use?",
    "vehicle.security": "What security does it have — factory-fitted, Thatcham alarm, tracker, or none?",
    "vehicle.dashcam": "Does the car have a dashcam?",
    "vehicle.modified": "Has the car been modified?",
    "vehicle.imported": "Is the car imported — no, EU, or non-EU?",
    "vehicle.daytimeLocation": "Where is the car kept in the daytime — drive, garage, car park, or street?",
    "vehicle.overnightLocation": "Where is the car kept overnight — drive, garage, car park, or street?",
    "vehicle.annualMileage": "About how many miles a year do you drive?",
    "vehicle.registeredKeeper": "Are you the registered keeper?",
    "vehicle.legalOwner": "Are you the legal owner?",
    "customer.title": "What's your title — Mr, Mrs, Miss, Ms, Dr, or Mx?",
    "customer.firstName": "What's your first name?",
    "customer.surname": "What's your surname?",
    "customer.dateOfBirth": "What's your date of birth?",
    "customer.maritalStatus": "What's your marital status?",
    "customer.childrenUnder16": "How many children under 16 do you have?",
    "customer.employmentStatus": "What's your employment status?",
    "customer.partTimeJob": "Do you have a part-time job?",
    "customer.yearsLivedInUK": "How long have you lived in the UK?",
    "customer.address.houseNumberOrName": "What's your house number or name?",
    "customer.address.postcode": "What's your postcode?",
    "customer.ownsProperty": "Do you own your property?",
    "customer.carKeptOvernightAtAddress": "Is the car kept overnight at your address?",
    "customer.email": "What's your email address?",
    "driver.licenceType": "What type of licence do you hold?",
    "driver.licenceHeldFor": "How many years have you held your licence?",
    "driver.insuranceCancelledOrVoid": "Has any insurance ever been cancelled or voided?",
    "driver.ncdYears": "How many years no-claims discount do you have?",
    "driver.ncdOnCompanyCar": "Is your no-claims discount on a company car?",
    "history.claimsLast3Years": "How many claims or accidents have you had in the last 3 years?",
    "history.offencesLast5Years": "How many motoring offences in the last 5 years?",
    "history.unspentCriminalConvictions": "Do you have any unspent (non-motoring) criminal convictions?",
    "household.carsInHousehold": "How many cars are in your household, including this one?",
    "household.anotherCarHasCover": "Is another car in the household insured with us?",
    "household.regularUseOfOtherVehicles": "Do you regularly use other vehicles — none, named car, any car, or company car?",
    "cover.paymentMethod": "How would you like to pay — monthly instalments or a single payment?",
    "cover.coverLevel": "What cover level — comprehensive, or third party fire & theft?",
    "cover.coverStartDate": "When would you like cover to start?",
    "cover.voluntaryExcess": "How much voluntary excess would you like (£)?",
}

# Short labels for the confirmation echo (brief §4.8).
_ECHO_LABELS: dict[str, str] = {
    "customer.dateOfBirth": "Date of birth",
    "customer.firstName": "First name",
    "customer.surname": "Surname",
    "customer.title": "Title",
    "customer.email": "Email",
    "customer.address.postcode": "Postcode",
    "vehicle.registration": "Registration",
    "vehicle.value": "Value",
    "vehicle.annualMileage": "Mileage",
    "driver.ncdYears": "NCD years",
}


def _flatten(patch: dict, prefix: str = "") -> list[tuple[str, object]]:
    out: list[tuple[str, object]] = []
    for key, value in (patch or {}).items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.extend(_flatten(value, path))
        else:
            out.append((path, value))
    return out


def _label(path: str) -> str:
    if path in _ECHO_LABELS:
        return _ECHO_LABELS[path]
    return path.split(".")[-1]


def confirmation_echo(applicable: dict) -> str:
    """A tidy one-line echo of what was captured (brief §4.8)."""
    pairs = _flatten(applicable)
    if not pairs:
        return ""
    shown = pairs[:2]
    parts = [f"{_label(p)} {v}" for p, v in shown]
    extra = len(pairs) - len(shown)
    line = "✓ " + ", ".join(parts)
    if extra > 0:
        line += f", +{extra} more"
    return line


def next_question(missing: list[str]) -> Optional[str]:
    if not missing:
        return None
    return missing[0]


async def collect_turn(message: str, session: dict, service, client=None, autofill=False):
    """Drive one customer turn against ``service``, yielding event dicts.

    ``session`` (mutable) holds: quoteId, sessionId (platform), current (the
    backend's merged quote copy), asked_question, pending_conflicts.

    ``autofill`` (the ``MOCK_AUTOFILL`` demo fast-path): after applying whatever
    the customer said, fill any remaining gaps from a complete synthetic sample
    so the quote is ready to price in a single turn — for frontend iteration.
    """
    quote_id = session["quoteId"]
    platform_session = session["sessionId"]
    session.setdefault("current", {})
    asked = session.get("asked_question")

    # 1) Greedy, question-anchored extraction over the whole model (§4.1/§4.2).
    patch = extract_patch(message, asked_question=asked, client=client)

    # 2) Reconcile against the current quote — loose-equal no-ops, clashes queued.
    applicable, conflicts = reconcile(session["current"], patch)

    # 3) Apply the non-conflicting part to the platform; adopt recomputed state.
    state = None
    if applicable:
        state = await service.update(quote_id, platform_session, applicable)
        deep_merge(session["current"], applicable)
    else:
        state = await service.get(quote_id, platform_session)

    if applicable:
        echo = confirmation_echo(applicable)
        if echo:
            yield {"type": "echo", "data": echo}

    # 4) Conflicts: ask which value is correct (offer both as chips). §4.6.
    if conflicts:
        session["pending_conflicts"] = conflicts
        first = conflicts[0]
        yield {
            "type": "conflict",
            "data": {
                "path": first["path"],
                "current": first["current"],
                "proposed": first["proposed"],
                "chips": [first["current"], first["proposed"]],
                "message": (
                    f"I already have {_label(first['path'])} as "
                    f"\"{first['current']}\" but you've said \"{first['proposed']}\". "
                    "Which is correct?"
                ),
            },
        }
        return

    session["pending_conflicts"] = []
    missing = (state or {}).get("missingFields", [])
    journey = (state or {}).get("journeyState")

    # 4b) Demo fast-path (MOCK_AUTOFILL): fill remaining gaps from a complete
    # synthetic sample so the quote completes in one turn. Gap-fill only — what
    # the customer actually said is preserved.
    if autofill and missing:
        gap = gap_fill_patch(session["current"])
        if gap:
            state = await service.update(quote_id, platform_session, gap)
            deep_merge(session["current"], gap)
            yield {"type": "echo", "data": "✓ Autofilled remaining details (demo mode)"}
            missing = (state or {}).get("missingFields", [])
            journey = (state or {}).get("journeyState")

    # 5) Ready, or ask the next still-missing field (§4.1, §6).
    if journey == "ready_to_price" or not missing:
        session["asked_question"] = None
        yield {
            "type": "text",
            "data": "That's everything I need — your quote is ready to be priced.",
        }
        return

    nxt = next_question(missing)
    session["asked_question"] = nxt
    yield {"type": "text", "data": _FIELD_PROMPTS.get(nxt, f"I still need {nxt}.")}


async def apply_resolution(session: dict, service, path: str, value, client=None):
    """Apply a customer's conflict resolution (brief §4.6, §17.2).

    Casts ``value`` for the field; if unparseable, keeps the current value and
    never invents one. Then continues the turn (echo + next gap). Async generator.
    """
    quote_id = session["quoteId"]
    platform_session = session["sessionId"]
    session.setdefault("current", {})

    resolved = resolve_conflict(path, value)
    if resolved is KEEP_CURRENT:
        # Unparseable — keep current, drop the conflict, do not write 0/"".
        yield {
            "type": "text",
            "data": (
                f"I couldn't read that as a valid {path.split('.')[-1]}, so I've "
                "kept the existing value."
            ),
        }
        state = await service.get(quote_id, platform_session)
    else:
        patch: dict = {}
        parts = path.split(".")
        node = patch
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = resolved
        state = await service.update(quote_id, platform_session, patch)
        deep_merge(session["current"], patch)
        yield {"type": "echo", "data": confirmation_echo(patch)}

    # Clear the resolved conflict from the queue.
    pending = [c for c in session.get("pending_conflicts", []) if c["path"] != path]
    session["pending_conflicts"] = pending

    missing = (state or {}).get("missingFields", [])
    journey = (state or {}).get("journeyState")
    if journey == "ready_to_price" or not missing:
        session["asked_question"] = None
        yield {
            "type": "text",
            "data": "That's everything I need — your quote is ready to be priced.",
        }
        return
    nxt = next_question(missing)
    session["asked_question"] = nxt
    yield {"type": "text", "data": _FIELD_PROMPTS.get(nxt, f"I still need {nxt}.")}
