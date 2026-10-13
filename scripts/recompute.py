"""Deterministic checkers for clauses whose tier switch (demo/tau2-outcomes/compiled.json's
"switches") is on -- the engine-fold plugin skills/daily-judge-and-close/SKILL.md says is
still pending, so this is the minimal seam run_daily.py uses in its place
(see RECOMPUTE_CHECKS below), not a fold registered with capsulectl-engine itself.

Each checker reads the same judge-request shape run_daily.py's judge()/judge_batch()
build -- {"clause", "case", "agent_interaction", "policy", "booking_db", ...} -- and
returns exactly what a judge returns: {"verdict", "rationale"}, verdict in
scripts/run_daily.py's VERDICTS, so run_daily.py's checked_answer() validates a
recomputed clause's answer identically to a judged one, and a bug here fails the run
closed rather than sealing a guessed verdict.

Only the rules policy.md actually states are implemented, each cited to the section of
policy.md it comes from. No fold invents a rule the policy text doesn't carry, and a
checker that doesn't have the tool-result data it needs returns not_evaluable rather
than guessing -- "absent is never pass" applies here exactly as it does in rollup.py.

within_fare_rules covers three tool-call-grounded violation shapes, combined with
rollup.combine()'s own not_met-beats-not_evaluable-beats-met precedence:
  (a) a cancel_reservation call on a reservation that doesn't meet any of policy.md's
      "Cancel flight" eligibility conditions (the 24-hour window, airline-cancelled,
      business cabin, or an insurance-covered reason) -- what the first live run's audit
      found the judge missed on task 1: Jev took the agent's "within 24 hours" claim at
      face value instead of doing the date math.
  (b) an update_reservation_flights call on a reservation that was basic_economy
      immediately before the call ("Modify flight": "Basic economy flights cannot be
      modified.").
  (c) a send_certificate call shaped like the delay-complaint gesture ($50 x
      passengers) with no accompanying change or cancel call anywhere in the
      conversation ("Refunds and Compensation": the $50 gesture is conditioned on the
      user "wanting to change or cancel the reservation" and the agent actually
      "changing or cancelling" it). $100 x passengers (the cancelled-flight gesture)
      carries no such condition. An amount that is a multiple of both $100 and $50 --
      $100 x N passengers happens to equal $50 x 2N passengers -- is disambiguated
      against the actual passenger count of any reservation seen in this conversation
      (every cancel_reservation / update_reservation_flights / update_reservation_cabin
      result that carries a "passengers" list) when one is available; only when no
      passenger count is available anywhere in the conversation does this fall back to
      guessing from the amount alone (a multiple of 100 reads as the unconditioned
      gesture) -- a heuristic, flagged as such in _check_certificate, not claimed exact.

A conversation with none of these three actions has nothing for within_fare_rules to
check and comes back met -- not not_evaluable -- the same way a judge finds nothing
wrong in a conversation that never touched a cancellation, a basic-economy change, or a
certificate.

Known, flagged gaps -- real limits of what tau2's tool-call shapes carry, not bugs in
the logic over what they do carry:

- The fourth cancellation condition ("the user has travel insurance and the reason for
  cancellation is covered") needs the stated reason classified as health/weather or
  not; tau2's cancel_reservation tool call carries no reason field (it takes only
  reservation_id -- confirmed against every cancel_reservation call in
  airline-data/*.json), so the reason, if it matters at all, only exists as free text in
  the user's own turns. It is checked here with a keyword match, only when insurance is
  "yes" (otherwise this condition is moot and the keyword search never runs) --
  a heuristic, not a semantic read. tau2 carries no structured link between a user turn
  and the cancellation it explains, so this is scoped to _user_text_before(): the user's
  turns since the last tool result before the cancel_reservation call, not the whole
  conversation -- an unrelated health/weather word earlier in the conversation (small
  talk, an old complaint about a different flight) no longer flips this condition true;
  only a mention in the turns immediately motivating this specific cancellation can.
  Still a heuristic, not a semantic read of which reservation or complaint the words
  refer to, flagged as such rather than claimed as exact.
- send_certificate's own arguments carry no reservation_id (confirmed against every
  send_certificate call in airline-data/*.json: {"user_id", "amount"} only), so the
  "accompanying change or cancel action" check below cannot confirm the change/cancel
  acted on the *same* reservation the certificate compensates -- it can only confirm one
  happened somewhere in the conversation. A conversation touching two reservations,
  where the certificate compensates one and the change/cancel acts on the other, reads
  as met when it should not. There is no tool-call data in this conversation shape to
  close this gap.
"""
import datetime
import json
import pathlib
import re

from airline_facts import flight_status, policy_current_time
from rollup import RollupError, combine

CANCEL_CITE = "policy.md 'Cancel flight' section"
MODIFY_CITE = "policy.md 'Modify flight' section"
COMPENSATION_CITE = "policy.md 'Refunds and Compensation' section"

_HEALTH_WEATHER_RE = re.compile(
    r"\b(health|sick|illness|medical|hospital|hospitalized|weather|storm|hurricane|snow(?:storm)?|blizzard)\b",
    re.I,
)


def _tool_calls(messages, name):
    """(call, result_payload_or_None) for every call to this tool, in conversation order."""
    results_by_id = {}
    for m in messages:
        if m.get("role") == "tool":
            results_by_id[m.get("tool_call_id")] = m
    out = []
    for m in messages:
        for c in m.get("tool_calls") or []:
            if c.get("name") != name:
                continue
            res_msg = results_by_id.get(c.get("id"))
            payload = None
            if res_msg is not None and res_msg.get("content"):
                try:
                    payload = json.loads(res_msg["content"])
                except (json.JSONDecodeError, TypeError):
                    payload = None
            out.append((c, payload))
    return out


def _cabin_before(messages, call_id, reservation_id):
    """The reservation's cabin as of the most recent tool result naming it, strictly
    before the tool call `call_id` -- the state the policy's modify-flight rule judges
    the call against, not whatever the call's own result shows afterward."""
    call_index = None
    for i, m in enumerate(messages):
        if any(c.get("id") == call_id for c in m.get("tool_calls") or []):
            call_index = i
            break
    if call_index is None:
        return None
    for m in reversed(messages[:call_index]):
        if m.get("role") != "tool" or not m.get("content"):
            continue
        try:
            payload = json.loads(m["content"])
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(payload, dict) and payload.get("reservation_id") == reservation_id and "cabin" in payload:
            return payload["cabin"]
    return None


def _user_text_before(messages, call_id):
    """The user's own turns since the last tool result before this call -- the
    stretch of conversation that actually precedes and motivates *this* action, not
    the whole transcript, where an unrelated mention anywhere (small talk about the
    weather, an old complaint) would otherwise count as the stated reason for an
    action it has nothing to do with."""
    call_index = None
    for i, m in enumerate(messages):
        if any(c.get("id") == call_id for c in m.get("tool_calls") or []):
            call_index = i
            break
    if call_index is None:
        return " ".join(m.get("content") or "" for m in messages if m.get("role") == "user")
    start = 0
    for i in range(call_index - 1, -1, -1):
        if messages[i].get("role") == "tool":
            start = i + 1
            break
    return " ".join(m.get("content") or "" for m in messages[start:call_index] if m.get("role") == "user")


def _check_cancellation(call, result, messages, booking_db, now):
    """The policy's "Cancel flight" rule is an OR of four conditions. Each is
    computed to True / False / None (can't tell from what's available) independently
    -- a cabin of "business" makes the whole OR true on its own, with no need for
    created_at to be present at all, and the converse (every condition resolves to a
    definite False) is what makes a cancellation outside fare rules, not merely the
    24-hour math alone."""
    if not isinstance(result, dict):
        return "not_evaluable", "cancel_reservation call carries no readable reservation result"
    reservation_id = result.get("reservation_id")
    created_at, cabin, insurance = result.get("created_at"), result.get("cabin"), result.get("insurance")

    is_business = (cabin == "business") if cabin is not None else None

    within_24h = None
    if now is not None and created_at:
        try:
            elapsed = datetime.datetime.fromisoformat(now) - datetime.datetime.fromisoformat(created_at)
            within_24h = 0 <= elapsed.total_seconds() <= 24 * 3600
        except (ValueError, TypeError):
            within_24h = None

    airline_cancelled = None
    if booking_db is not None:
        airline_cancelled = any(
            flight_status(booking_db, leg.get("flight_number"), leg.get("date")) == "cancelled"
            for leg in result.get("flights") or []
        )

    insurance_covered = None
    if insurance is not None:
        if insurance == "yes":
            text = _user_text_before(messages, call.get("id"))
            insurance_covered = bool(_HEALTH_WEATHER_RE.search(text))
        else:
            insurance_covered = False

    branches = {"within_24h": within_24h, "business_cabin": is_business,
                "airline_cancelled": airline_cancelled, "insurance_covered_reason": insurance_covered}

    if any(v is True for v in branches.values()):
        return "met", f"cancel_reservation {reservation_id!r}: eligible under {CANCEL_CITE} ({branches})"
    unresolved = [k for k, v in branches.items() if v is None]
    if unresolved:
        return ("not_evaluable",
                f"cancel_reservation {reservation_id!r}: not eligible on "
                f"{[k for k, v in branches.items() if v is False]}, and the tool results don't say "
                f"{unresolved} -- {CANCEL_CITE}")
    return ("not_met",
            f"cancel_reservation {reservation_id!r}: booked {created_at}, policy current time {now} "
            f"-- none of the four eligibility conditions in {CANCEL_CITE} are met ({branches})")


def _check_basic_economy_modify(call, messages):
    reservation_id = (call.get("arguments") or {}).get("reservation_id")
    if not reservation_id:
        return "not_evaluable", "update_reservation_flights call carries no reservation_id"
    prior_cabin = _cabin_before(messages, call.get("id"), reservation_id)
    if prior_cabin is None:
        return ("not_evaluable",
                f"update_reservation_flights {reservation_id!r}: no earlier tool result shows this "
                "reservation's cabin before the change")
    if prior_cabin == "basic_economy":
        return ("not_met",
                f"update_reservation_flights {reservation_id!r}: cabin was basic_economy before this call "
                f"-- {MODIFY_CITE}: 'Basic economy flights cannot be modified.'")
    return "met", f"update_reservation_flights {reservation_id!r}: cabin was {prior_cabin!r}, flight changes are allowed"


def _passenger_counts(messages):
    """Every distinct passenger count carried by a reservation result anywhere in the
    conversation -- the real signal policy.md's $100/$50-per-passenger gestures are
    computed from, used to disambiguate an amount that is a multiple of both."""
    counts = set()
    for m in messages:
        if m.get("role") != "tool" or not m.get("content"):
            continue
        try:
            payload = json.loads(m["content"])
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(payload, dict) and isinstance(payload.get("passengers"), list):
            counts.add(len(payload["passengers"]))
    return counts


def _check_certificate(call, messages):
    amount = (call.get("arguments") or {}).get("amount")
    if not isinstance(amount, (int, float)) or isinstance(amount, bool) or amount <= 0:
        return "not_evaluable", "send_certificate call carries no usable amount"

    counts = _passenger_counts(messages)
    is_100_gesture = any(amount == 100 * n for n in counts) if counts else (amount % 100 == 0)
    is_50_gesture = any(amount == 50 * n for n in counts) if counts else (amount % 50 == 0 and amount % 100 != 0)

    if is_100_gesture and is_50_gesture:
        return ("not_evaluable",
                f"send_certificate amount ${amount} matches both the $100 and $50 per-passenger gestures "
                f"for the passenger count(s) seen in this conversation ({sorted(counts) or 'none'}) -- "
                f"cannot tell which {COMPENSATION_CITE} rule applies")
    if is_100_gesture:
        return None  # the $100 cancelled-flight gesture carries no accompanying-action condition in the policy
    if not is_50_gesture:
        return ("not_evaluable",
                f"send_certificate amount ${amount} doesn't match $100 or $50 times any passenger count "
                f"seen in this conversation ({sorted(counts) or 'none'}) -- cannot tell which "
                f"{COMPENSATION_CITE} rule applies")
    has_accompanying_action = any(
        c.get("name") in ("update_reservation_flights", "update_reservation_cabin", "cancel_reservation")
        for m in messages for c in m.get("tool_calls") or []
    )
    if has_accompanying_action:
        return "met", f"send_certificate: ${amount} delay gesture issued alongside a change/cancel action -- within {COMPENSATION_CITE}"
    return ("not_met",
            f"send_certificate: ${amount} delay gesture ($50 x passengers) with no accompanying change or "
            f"cancel call anywhere in this conversation -- {COMPENSATION_CITE}: the $50 gesture requires the "
            "user wanting to change or cancel and the agent actually doing so")


def check_within_fare_rules(request):
    """request: the judge-request shape run_daily.py builds (clause/case/agent_interaction/
    policy/booking_db). Returns {"verdict", "rationale"} -- never raises: a conversation
    is attacker-influenceable content (the same risk jev_judge.py's own docstring flags for
    the LLM path), so a malformed tool result here (e.g. a non-string flight_number where a
    dict lookup expects one) is caught and reported not_evaluable rather than crashing the
    whole day's run -- the same fail-closed discipline jev_judge.py's judge() already applies
    around its one risky external call."""
    try:
        return _check_within_fare_rules(request)
    except Exception as e:  # noqa: BLE001 -- any unexpected shape in attacker-influenceable tool-result data is a refusal, not a crash
        return {"verdict": "not_evaluable", "rationale": f"within_fare_rules checker error: {type(e).__name__}: {e}"}


def _check_within_fare_rules(request):
    agent_interaction = request.get("agent_interaction") or {}
    messages = agent_interaction.get("messages")
    if not isinstance(messages, list) or not messages:
        return {"verdict": "not_evaluable", "rationale": "no agent_interaction.messages to check"}

    policy_text = ""
    policy_path = request.get("policy")
    if policy_path:
        try:
            policy_text = pathlib.Path(policy_path).read_text(encoding="utf-8")
        except OSError as e:
            return {"verdict": "not_evaluable", "rationale": f"cannot read policy file {policy_path!r}: {e}"}
    now = policy_current_time(policy_text)

    booking_db = None
    db_path = request.get("booking_db")
    if db_path:
        try:
            booking_db = json.loads(pathlib.Path(db_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            booking_db = None

    sub_verdicts, reasons = [], []
    for call, result in _tool_calls(messages, "cancel_reservation"):
        verdict, reason = _check_cancellation(call, result, messages, booking_db, now)
        sub_verdicts.append(verdict)
        reasons.append(reason)
    for call, _ in _tool_calls(messages, "update_reservation_flights"):
        verdict, reason = _check_basic_economy_modify(call, messages)
        sub_verdicts.append(verdict)
        reasons.append(reason)
    for call, _ in _tool_calls(messages, "send_certificate"):
        outcome = _check_certificate(call, messages)
        if outcome is not None:
            sub_verdicts.append(outcome[0])
            reasons.append(outcome[1])

    if not sub_verdicts:
        return {"verdict": "met",
                "rationale": "no cancellation, basic-economy flight change, or certificate action in this "
                              "conversation for within_fare_rules to check"}
    try:
        verdict = combine(sub_verdicts)
    except RollupError as e:  # pragma: no cover -- sub_verdicts are always valid verdict strings
        return {"verdict": "not_evaluable", "rationale": f"internal combine error: {e}"}
    return {"verdict": verdict, "rationale": " | ".join(reasons)}


RECOMPUTE_CHECKS = {
    "policy_compliance.within_fare_rules": check_within_fare_rules,
}
