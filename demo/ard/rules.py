# SPDX-License-Identifier: Apache-2.0
"""Maya's deal check under a spending limit a person set: the Everyday Rules (``asg/everyday/0.3.8``, embedded in
``capsule-engine``) run on the order's check record before any payment leaves.

The limit is ``ARD_LIMIT_MSAT``: the most Maya may spend in a rolling week, and on one order. Unset, nothing here
runs and the demo behaves as before. With it set, each order's check record is sealed first, handed to
``capsule-engine guard check --limits FILE`` with Maya's earlier paid orders as history, and a failing caps finding
(an order over the limit the person set) is HELD for the person's OK, not refused (Steven, ops u325, 2026-10-12: a failing
caps check on a person-set limit is ESCALATE): the screen names the rule, the limit and the amount and asks the person
to approve or decline. A decline pays nothing; an approval goes on to the payment. Either answer is sealed as a note of
Maya's (:data:`CHECKED`). The pack's other asks (a new merchant, a payment that cannot be undone) are what the
presenter's payment dialog already puts to the person, so they are listed, not held.

The check record is sealed before the payment and the act after it, so the deal check can stop the order. The
evidencebook goose reference seals the check, its verdict, the approval and the act in one call
(``DealChain.check_and_pay``, python/examples/goose/deal_records.py, at the commit the run sheet pins);
:func:`pay_check` and :func:`pay_after_check` are that method cut at the payment, and ``tests/test_rules.py`` holds them
to its output. The verdict record keeps the reference's ``rules: not_configured``: this demo adds no protocol, so what
the rules said is sealed as a node-book note of Maya's (:data:`CHECKED`) and shown on screen."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import deal_records as dr
from evidencebook import deal

#: A note: Maya's deal check ran the Everyday Rules on this order and what they said.
CHECKED = "ard_rules_checked"
ENGINE_FLAG_MISSING = ("this capsule-engine has no `guard check --limits`: it needs the capsule-engine release of "
                       "person-set limits (capsule-engine#314)")
ACTION_CLASS = "money.purchase"


class RulesError(RuntimeError):
    """The check could not run (no engine, an engine without ``--limits``, an input it refused). Nothing was paid."""


class RuleHeld(RuntimeError):
    """The deal check held the order for the person's OK and the person declined it: nothing was paid. ``reasons`` are
    the rules' own words."""

    def __init__(self, message: str, reasons: list[str]):
        super().__init__(message)
        self.reasons = reasons


@dataclass
class Outcome:
    verdict: str
    held: bool
    limit_msat: int
    amount_msat: int
    reasons: list[str] = field(default_factory=list)  # the failing caps findings: the rule's reason with its numbers
    asks: list[str] = field(default_factory=list)  # the pack's other failing rules: the presenter's dialog covers these
    ruleset: str = ""
    decision: str = ""  # "approved" or "declined" when the order was held and the person was asked, else ""


def limit_msat() -> int | None:
    """The person's spending limit in msat, from ``ARD_LIMIT_MSAT``; ``None`` when none is set."""
    raw = os.environ.get("ARD_LIMIT_MSAT", "").strip()
    if not raw:
        return None
    if not raw.isdigit() or int(raw) <= 0:
        raise RulesError(f"ARD_LIMIT_MSAT must be a whole number of msat above 0, not {raw!r}")
    return int(raw)


# -- the check record, sealed before the payment ---------------------------------------------------------------

def pay_check(chain: dr.DealChain, at: datetime) -> list[dr.Step]:
    """The buyer's check on the payment: ``check_and_pay`` up to and including its check record."""
    if chain._seller:
        raise ValueError("only a buyer pays")
    chain._open_for_more()
    if chain._has(deal.TYPE_ACTION, "pay"):
        raise ValueError(f"deal {chain.deal_id} is already paid")
    n, t = len(chain._built), chain.terms
    body = {"action": "pay", "action_class": ACTION_CLASS, "amount_minor": t.price_minor,
            "authorized_max_minor": t.price_minor, "currency": t.currency, "spend_minor": t.price_minor,
            "spend_authorized_minor": t.price_minor, "taxonomy_version": dr.TAXONOMY_VERSION,
            "terms": {"item": t.item, "price_minor": t.price_minor, "currency": t.currency},
            "recourse": {"rail": t.rail, "refundable": t.refundable}}
    chain._step(chain._untyped(deal.TYPE_CHECK, at, body, counterparty=chain._counterparty(deal.FP_ALG)),
                at, {"check": "pay"})
    return chain._since(n)


def pay_after_check(chain: dr.DealChain, at: datetime, reference: str) -> list[dr.Step]:
    """The rest of ``check_and_pay`` once the check is sealed and the payment is made: the verdict, the approval and
    the ``pay`` act naming the payment reference by its commitment."""
    n, t = len(chain._built), chain.terms
    checked = chain._latest(deal.TYPE_CHECK)
    verdict = chain._step(chain._untyped(deal.TYPE_VERDICT, at, {
        "result": "pass", "differences": [], "options": [], "judge": {"kind": "rules"},
        "rules": {"status": "not_configured"}}, [("checks", checked)]), at, {"verdict": "pass"}).digest
    approval = chain._step(chain._untyped(deal.TYPE_APPROVAL, at, {
        "choice": "proceed", "proceed": True, "approver": "standing_intent"}, [("approves", verdict)]),
        at, {"approval": "standing_intent"}).digest
    commitment, nonce = dr._commit(reference)
    decide = deal.Decide(deal.Disposition("accept", "policy", False, "executed"), "send_payment",
                         "one_way_recoverable" if t.refundable else "one_way_consequential")
    chain._step(chain._untyped(deal.TYPE_ACTION, at, {
        "action": "pay", "action_class": ACTION_CLASS, "amount_minor": t.price_minor,
        "currency": t.currency, "direction": "out", "rail": t.rail, "reference_commitment": commitment,
        "spend_minor": t.price_minor, "taxonomy_version": dr.TAXONOMY_VERSION},
        [("authorized_by", approval)], counterparty=chain._counterparty(deal.FP_ALG)),
        at, {"act": {"action": "pay", "reference": reference}, "nonces": {"reference": nonce}}, decide)
    return chain._since(n)


# -- the Everyday Rules over it --------------------------------------------------------------------------------

def _record(node, book, payloads: list[bytes], i: int) -> dict:
    """A sealed record as ``guard check`` reads it: its capsule, with the body it seals beside it."""
    capsule = node.capsule(book.records()[i].record_id)
    return {**capsule, "agent_input": json.loads(payloads[i])}


WINDOW_DAYS = 7
MAX_HISTORY = 200


def _paid_acts(node, skip_deal: str, now: datetime | None = None) -> list[dict]:
    """Maya's earlier ``pay`` acts on her other deals within the last 7 days, newest first (the history the weekly limit
    sums), at most :data:`MAX_HISTORY` of them (the input says so in its ``history_scope``)."""
    since = (now or datetime.now(timezone.utc)) - timedelta(days=WINDOW_DAYS)
    acts = []
    for book_id in sorted(node.shelf.books()):
        if not book_id.startswith("deal/") or book_id.count("/") != 1 or book_id == f"deal/{skip_deal}":
            continue
        book = node.shelf.open(book_id)
        payloads = node.deal_payloads(book_id[len("deal/"):])
        for i, p in enumerate(payloads):
            j = json.loads(p)
            if (j.get("x-deal-v0") or {}).get("record_type") == deal.TYPE_ACTION and j.get("body", {}).get("action") == "pay":
                at = j["x-deal-v0"]["at"]
                if datetime.fromisoformat(at.replace("Z", "+00:00")) >= since:
                    acts.append((at, _record(node, book, payloads, i)))
    return [a for _, a in sorted(acts, key=lambda x: x[0], reverse=True)][:MAX_HISTORY]


def engine() -> str:
    path = os.environ.get("CAPSULE_ENGINE", "")
    if not path:
        raise RulesError("CAPSULE_ENGINE does not name a capsule-engine binary, so the deal check cannot run")
    return path


def limits_profile(limit: int) -> dict:
    """The person's limits as ``capsule-engine``'s ``policy-profile/v0``: the most Maya may spend in a rolling week
    and on one order, both the same here (the amount of the first order)."""
    return {"format": "policy-profile/v0", "packs": [{"pack": "asg/everyday", "parameters": {"caps": {
        "caps_minor": {ACTION_CLASS: limit}, "per_action_minor": {ACTION_CLASS: limit}}}}]}


def check(node, chain: dr.DealChain, check_step_index: int, limit: int) -> Outcome:
    """Run the Everyday Rules on the sealed check record (the deal book's record ``check_step_index``) under the
    person's ``limit``. Raises :class:`RulesError` when the engine could not answer."""
    book = node.shelf.open(f"deal/{chain.deal_id}")
    payloads = node.deal_payloads(chain.deal_id)
    inp = {"schema": "external-check-input/v0", "party_role": "buyer",
           "record": _record(node, book, payloads, check_step_index), "history": _paid_acts(node, chain.deal_id),
           "history_scope": {"days": WINDOW_DAYS, "max_records": MAX_HISTORY, "complete": True}}
    try:
        with tempfile.TemporaryDirectory(prefix="ard-rules-") as tmp:
            limits = Path(tmp) / "limits.json"
            limits.write_text(json.dumps(limits_profile(limit)))
            run = subprocess.run([engine(), "guard", "check", "--limits", str(limits)], input=json.dumps(inp),
                                 capture_output=True, text=True, timeout=60)
        if run.returncode != 0:
            say = run.stderr.strip().splitlines()[-1] if run.stderr.strip() else f"exit {run.returncode}"
            if "--limits" in run.stderr or "usage" in run.stderr:
                raise RulesError(ENGINE_FLAG_MISSING)
            raise RulesError(f"the deal check could not run: {say}")
        result = json.loads(run.stdout)
        result["findings"], result["ruleset_id"], result["verdict"]  # the members read below
    except RulesError:
        raise
    except (OSError, subprocess.SubprocessError, ValueError, KeyError) as exc:
        raise RulesError(f"the deal check could not run: {type(exc).__name__}: {exc}") from None
    failing = [f for f in result["findings"] if f["verdict"] == "fail"]
    caps = [f for f in failing if str(f.get("check", "")).startswith("caps/")]
    reasons = [_words(f) for f in caps]
    asks = [f["reason"] for f in failing if f not in caps and f.get("reason")]
    return Outcome(result["verdict"], bool(caps), limit, chain.terms.price_minor, reasons, asks, result["ruleset_id"])


def _words(finding: dict) -> str:
    out = finding.get("reason", "over the limit you set")
    if finding.get("limit") is not None and finding.get("value") is not None:
        out += f" (limit {finding['limit']:,} msat, this order would bring it to {finding['value']:,} msat)"
    return out


def seal_note(node, deal_id: str, outcome: Outcome) -> None:
    """Maya's own record of what the deal check said, in her node book (the verdict record keeps the reference's
    ``not_configured``)."""
    node.note(CHECKED, {"deal_id": deal_id, "ruleset": outcome.ruleset, "verdict": outcome.verdict,
                        "held": outcome.held, "decision": outcome.decision, "limit_msat": outcome.limit_msat,
                        "amount_msat": outcome.amount_msat, "reasons": outcome.reasons}, subject_ref=deal_id)


def gate(node, chain: dr.DealChain, limit: int, at: datetime,
         approve: Callable[[Outcome], bool] | None = None) -> Outcome:
    """Seal the check record and run the rules on it; return what they said once the order may go ahead. An order the
    rules hold is put to the person through ``approve`` (no ``approve``: declined); a decline raises
    :class:`RuleHeld`: the check is sealed, nothing else, and nothing is paid. Either answer is sealed as a note."""
    node.seal(chain, pay_check(chain, at))
    outcome = check(node, chain, len(node.deal_payloads(chain.deal_id)) - 1, limit)
    if outcome.held:
        try:
            ok = approve is not None and bool(approve(outcome))
        except Exception as exc:  # the question could not be put: nothing is paid and the order is not approved
            outcome.decision = "declined"
            seal_note(node, chain.deal_id, outcome)
            raise RulesError(f"the person could not be asked about the held order: {type(exc).__name__}: {exc}") from None
        outcome.decision = "approved" if ok else "declined"
    seal_note(node, chain.deal_id, outcome)
    if outcome.decision == "declined":
        raise RuleHeld("held for your OK at deal check, and declined: " + "; ".join(outcome.reasons), outcome.reasons)
    return outcome
