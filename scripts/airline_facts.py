"""Facts read out of a tau2 airline conversation and the policy text, shared by
scripts/judges/jev_judge.py (the date-aware prompt, always on) and scripts/recompute.py
(the deterministic within_fare_rules checker, switch-gated). No model calls, no I/O
beyond what the caller already has in hand (policy text, parsed booking_db, messages).

Pure functions only, same discipline as scripts/rollup.py: given the same inputs,
always the same answer, and a missing fact comes back as None, never guessed.
"""
import json
import re

_CURRENT_TIME_RE = re.compile(r"current time is (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")


def policy_current_time(policy_text):
    """The policy's own 'current time' sentence (airline-data/policy.md line 3),
    as an ISO 8601 string -- None if the policy carries no such sentence."""
    m = _CURRENT_TIME_RE.search(policy_text or "")
    if not m:
        return None
    return m.group(1).replace(" ", "T")


def _tool_payloads(messages):
    for m in messages or []:
        if m.get("role") != "tool":
            continue
        try:
            payload = json.loads(m.get("content") or "null")
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(payload, dict):
            yield payload


def reservation_timestamps(messages):
    """Every reservation_id -> created_at this conversation's tool results show,
    deduplicated. These are the only reservation timestamps a date-dependent
    criterion (e.g. the 24-hour cancellation window) has to work with -- tau2's
    airline tools return created_at on every get/cancel/update_reservation* call,
    never as a standalone lookup."""
    out = {}
    for payload in _tool_payloads(messages):
        rid, created_at = payload.get("reservation_id"), payload.get("created_at")
        if rid and created_at:
            out[rid] = created_at
    return out


def flight_status(booking_db, flight_number, date):
    """The scheduled status tau2's flight database records for one flight on one
    date (airline-data/db.json's flights[flight_number].dates[date].status --
    e.g. "available", "cancelled", "delayed") -- None if booking_db wasn't
    readable, or carries no such flight or date."""
    if not isinstance(booking_db, dict):
        return None
    flights = booking_db.get("flights")
    if not isinstance(flights, dict):
        return None
    entry = (flights.get(flight_number) or {}).get("dates", {}).get(date)
    return (entry or {}).get("status")
