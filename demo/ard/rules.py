# SPDX-License-Identifier: Apache-2.0
"""Maya's deal check under a spending limit a person set: the Everyday Rules (``asg/everyday/0.3.8``, embedded in
``capsule-engine``) run on the order's check record before any payment leaves.

The limit is ``ARD_LIMIT_MSAT``: the most Maya may spend in a rolling week, and on one order. Unset, nothing here
runs and the demo behaves as before. With it set, each order's check record is sealed first, handed to
``capsule-engine guard check --limits FILE`` with Maya's earlier paid orders as history, and a failing caps finding
(an order over the limit the person set) is HELD for the person's OK, not refused (Steven, ops u325, 2026-10-12: a failing
caps check on a person-set limit is ESCALATE). So is any other failing ASK rule (a new merchant, a payment that cannot
be undone, a repeated payment): Sherlock2 2026-11-23, rules doc section 4.5, any failing ASK rule makes the order one ask
that lists every reason, each in the rule's own words. A decline pays nothing; an approval goes on to the payment.
Either answer is sealed as a note of Maya's (:data:`CHECKED`).

The check record is sealed before the payment and the act after it, so the deal check can stop the order. The
evidencebook goose reference seals the check, its verdict, the approval and the act in one call
(``DealChain.check_and_pay``, python/examples/goose/deal_records.py, at the commit the run sheet pins);
:func:`pay_check` and :func:`pay_after_check` are that method cut at the payment, and ``tests/test_rules.py`` holds them
to its output when no limit is set and no one clicked. With a limit, the verdict record seals what the rules said
(x-deal-v0 section 8: ``rules: evaluated``, the ruleset, its digest, the engine's sha256, the verdict, every finding
and the history it was given; an ``escalate`` pauses the check with one ``rules_escalate`` difference per failing
finding, as evidencebook-deal folds a checker's answer). The approval names who answered: the person (``user``, with a
commitment to the words they were shown and the button they clicked) when they clicked Pay or Buy anyway (#261, Steven's
receipt review of 2026-11-24). What the rules said is also kept as a node-book note of Maya's (:data:`CHECKED`)."""
from __future__ import annotations

import hashlib
import json
import os
import re
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


class RulesRefused(RulesError):
    """The rules answered ``deny`` or ``not_evaluable``: the check ran and the order cannot go ahead. Nothing was paid."""


class RuleHeld(RuntimeError):
    """The deal check held the order for the person's OK and the person declined it: nothing was paid. ``reasons`` are
    the rules' own words."""

    def __init__(self, message: str, reasons: list[str]):
        super().__init__(message)
        self.reasons = reasons


@dataclass(frozen=True)
class Answer:
    """What the person answered in a dialog: the words it showed them and the button they clicked."""
    shown: str
    button: str

    def said(self) -> str:
        """The text the approval's ``said_commitment`` commits to."""
        return f"{self.shown}\nAnswer: {self.button}"


@dataclass
class Outcome:
    verdict: str
    held: bool
    limit_msat: int
    amount_msat: int
    reasons: list[str] = field(default_factory=list)  # every failing ASK rule in its own words, caps with its numbers
    asks: list[str] = field(default_factory=list)  # a failing DO rule (no allowance given): sealed, never asked about
    refused: list[str] = field(default_factory=list)  # a failing NEVER rule (23 to 25): the order is not put to the person
    ruleset: str = ""
    findings: list[dict] = field(default_factory=list)  # every finding the engine returned: id, check, verdict, reason (and limit, value when it names them)
    decision: str = ""  # "approved" or "declined" when the person was asked (a held order, or any under ask_always), else ""
    rules: dict = field(default_factory=dict)  # the verdict record's ``rules`` block, as sealed
    differences: list[dict] = field(default_factory=list)  # the verdict's differences: one per failing finding
    answer: Answer | None = None  # the person's answer (Buy anyway on a held order, or Pay under ask_always), when they said yes
    over_limit: bool = False  # every held reason is a spending limit (caps): the ask shows the limit's figures
    item: str = ""  # the order's item, from the deal's terms
    limits: dict = field(default_factory=dict)  # each failing caps finding's (limit, value): "weekly", "per_order"

    @property
    def paused(self) -> bool:
        """Whether the check pauses: the rules escalated (a hold over the limit, or the pack's other asks)."""
        return self.verdict == "escalate"


def limit_msat() -> int | None:
    """The person's spending limit in msat, from ``ARD_LIMIT_MSAT``; ``None`` when none is set."""
    raw = os.environ.get("ARD_LIMIT_MSAT", "").strip()
    if not raw:
        return None
    if not raw.isdigit() or int(raw) <= 0:
        raise RulesError(f"ARD_LIMIT_MSAT must be a whole number of msat above 0, not {raw!r}")
    return int(raw)


# -- the check record, sealed before the payment ---------------------------------------------------------------

def pay_check(chain: dr.DealChain, at: datetime, upfront: bool = False) -> list[dr.Step]:
    """The buyer's check on the payment: ``check_and_pay`` up to and including its check record. With ``upfront`` (the
    deal check under a limit, :func:`gate`) it also states that the whole price is due up front (the demo pays first,
    delivery follows), which the reference does not state and Everyday Rule 22 reads."""
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
    if upfront:  # rule 22 (up-front above 25%) reads it and asks
        body["upfront_amount_minor"] = t.price_minor
    chain._step(chain._untyped(deal.TYPE_CHECK, at, body, counterparty=chain._counterparty(deal.FP_ALG)),
                at, {"check": "pay"})
    return chain._since(n)


def pay_after_check(chain: dr.DealChain, at: datetime, reference: str, outcome: Outcome | None = None,
                    clicked: Answer | None = None) -> list[dr.Step]:
    """The rest of ``check_and_pay`` once the check is sealed and the payment is made: the verdict, the approval and
    the ``pay`` act naming the payment reference by its commitment.

    ``outcome`` is what the deal check said under the person's limit (none: no limit, ``rules: not_configured``).
    ``clicked`` is the person's Pay click in the payment dialog with no limit set (none: the gate was off). The approval is the
    person's (``user``) when they answered: the Buy anyway click on a held order, else the Pay click; with no answer it
    is ``standing_intent`` on a passing check, and ``agent_card`` on a paused one (x-deal-v0 section 6: a pause
    always needs an answer, and standing intent approves only a pass)."""
    n, t = len(chain._built), chain.terms
    checked = chain._latest(deal.TYPE_CHECK)
    if outcome is None:
        body = {"result": "pass", "differences": [], "options": [], "judge": {"kind": "rules"},
                "rules": {"status": "not_configured"}}
    elif outcome.paused:
        body = {"result": "pause", "differences": outcome.differences, "options": ["hold", "proceed"],
                "judge": {"kind": "rules"}, "rules": outcome.rules}
    else:
        body = {"result": "pass", "differences": [], "options": [], "judge": {"kind": "rules"}, "rules": outcome.rules}
    verdict = chain._step(chain._untyped(deal.TYPE_VERDICT, at, body, [("checks", checked)]), at,
                          {"verdict": body["result"]}).digest
    answer = (outcome.answer if outcome is not None else None) or clicked
    local: dict = {}
    if answer is not None:
        said, nonce = dr._commit(answer.said())
        approver, extra = "user", {"said_commitment": said}
        local = {"said": answer.said(), "nonces": {"said": nonce}}
    else:
        approver, extra = ("agent_card" if body["result"] == "pause" else "standing_intent"), {}
    approval = chain._step(chain._untyped(deal.TYPE_APPROVAL, at, {
        "choice": "proceed", "proceed": True, "approver": approver, **extra}, [("approves", verdict)]),
        at, {"approval": approver, **local}).digest
    commitment, nonce = dr._commit(reference)
    # x-deal-v0 section 3: disposed by the human when the user approved it in their own words, by policy under their
    # standing intent; an agent_card answer certifies no one, so the act is not a decide Capsule.
    decide = (None if approver == "agent_card" else
              deal.Decide(deal.Disposition("accept", "human" if approver == "user" else "policy", approver == "user",
                                           "executed"), "send_payment",
                          "one_way_recoverable" if t.refundable else "one_way_consequential"))
    chain._step(chain._untyped(deal.TYPE_ACTION, at, {
        "action": "pay", "action_class": ACTION_CLASS, "amount_minor": t.price_minor,
        "currency": t.currency, "direction": "out", "rail": t.rail, "reference_commitment": commitment,
        "spend_minor": t.price_minor, "taxonomy_version": dr.TAXONOMY_VERSION},
        [("authorized_by", approval)], counterparty=chain._counterparty(deal.FP_ALG)),
        at, {"act": {"action": "pay", "reference": reference}, "nonces": {"reference": nonce}}, decide)
    return chain._since(n)


def pay(chain: dr.DealChain, at: datetime, reference: str, outcome: Outcome | None, clicked: Answer | None) -> list[dr.Step]:
    """The steps after the payment for any order: the reference method when there was neither a limit nor a click
    (today's records, unchanged), else :func:`pay_after_check` (the check is sealed first, by :func:`gate`, or here)."""
    if outcome is None and clicked is None:
        return chain.check_and_pay(at, reference)
    steps = pay_check(chain, at) if outcome is None else []
    return steps + pay_after_check(chain, at, reference, outcome, clicked)


# -- the Everyday Rules over it --------------------------------------------------------------------------------

def _record(node, book, payloads: list[bytes], i: int, peer: str) -> dict:
    """A sealed record as ``guard check`` reads it: its capsule, with the body it seals beside it and the deal's ``peer``
    (the seller) keyed per profile, so a seller paid in an earlier deal is not a new merchant (rules 2 and 6). ``peer``
    is required: a caller that left it out would silently lose that link."""
    capsule = node.capsule(book.records()[i].record_id)
    return {**capsule, "agent_input": json.loads(payloads[i]), "counterparty_profile": node.profile_payee(peer)}


WINDOW_DAYS = 7
MAX_HISTORY = 200


def _paid_acts(node, skip_deal: str, now: datetime | None = None) -> list[dict]:
    """Maya's earlier ``pay`` acts on her other deals within the last 7 days, newest first (the history the weekly limit
    sums), at most :data:`MAX_HISTORY` + 1 of them: one past the cap shows the history was cut (``history_scope``)."""
    since = (now or datetime.now(timezone.utc)) - timedelta(days=WINDOW_DAYS)
    acts = []
    for book_id in sorted(node.shelf.books()):
        if not book_id.startswith("deal/") or book_id.count("/") != 1 or book_id == f"deal/{skip_deal}":
            continue
        book = node.shelf.open(book_id)
        payloads = node.deal_payloads(book_id[len("deal/"):])
        peer = None  # the deal's seller, read once per book and only when it holds a pay act in the window
        for i, p in enumerate(payloads):
            j = json.loads(p)
            if (j.get("x-deal-v0") or {}).get("record_type") == deal.TYPE_ACTION and j.get("body", {}).get("action") == "pay":
                at = j["x-deal-v0"]["at"]
                if datetime.fromisoformat(at.replace("Z", "+00:00")) >= since:
                    peer = peer or node.deal(book_id[len("deal/"):]).peer
                    acts.append((at, _record(node, book, payloads, i, peer)))
    return [a for _, a in sorted(acts, key=lambda x: x[0], reverse=True)][:MAX_HISTORY + 1]


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
    try:
        history = _paid_acts(node, chain.deal_id)  # fingerprints each earlier seller: inside, so it maps like the record
        complete = len(history) <= MAX_HISTORY
        history = history[:MAX_HISTORY]
        inp = {"schema": "external-check-input/v0", "party_role": "buyer",
               "record": _record(node, book, payloads, check_step_index, chain.peer), "history": history,
               "history_scope": {"days": WINDOW_DAYS, "max_records": MAX_HISTORY, "complete": complete}}
    except ValueError as exc:  # a seller id that cannot be fingerprinted (deal.NotNormalizable)
        raise RulesError(f"the deal check could not run: {type(exc).__name__}: {exc}") from None
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
        result["findings"], result["ruleset_id"], result["verdict"], result["definition_digest"]  # the members read below
    except RulesError:
        raise
    except (OSError, subprocess.SubprocessError, ValueError, KeyError) as exc:
        raise RulesError(f"the deal check could not run: {type(exc).__name__}: {exc}") from None
    if result["verdict"] not in ("allow", "escalate", "deny", "not_evaluable"):
        raise RulesError(f"the deal check could not run: the engine answered {result['verdict']!r}")
    failing = [f for f in result["findings"] if f["verdict"] == "fail"]
    asking = [f for f in failing if _is_ask(f)]
    refusing = [f for f in failing if _is_never(f)]
    sealed_check = inp["record"]["agent_input"].get("body") or {}  # the check record's own amounts, as the receipt reads them
    reasons = list(dict.fromkeys(_words(f, sealed_check) for f in asking))  # one line per rule; rules 5 to 22, 26 and 27
    asks = [f["reason"] for f in failing if f not in asking and f.get("reason")]  # a DO rule that gave no allowance
    sealed = {"status": "evaluated", "ruleset_id": result["ruleset_id"], "definition_digest": result["definition_digest"],
              "checker_sha256": _sha256(engine()), "verdict": result["verdict"],
              "tier": result.get("tier") if result.get("tier") in ("recomputed", "judged") else "not_stated",
              "findings": [_sealed(f) for f in result["findings"]],
              "history": {"days": WINDOW_DAYS, "acts": len(history), "complete": complete}}
    if result.get("grade") in ("self-attested", "witnessed", "countersigned"):
        sealed["grade"] = result["grade"]
    seen = [{k: f[k] for k in ("id", "check", "verdict", "reason", "limit", "value") if f.get(k) is not None}
            for f in result["findings"]]
    # The engine's escalate holds too when no failing ASK rule made it (only a DO rule failed, or an ASK rule could not be
    # evaluated): the pause is put to the person, so the approval of it is an answer to a hold, as the receipt says.
    held = bool(asking) or result["verdict"] == "escalate"
    limits = {CAPS_PERIODS[_period(f)]: (f["limit"], f["value"]) for f in asking
              if _period(f) in CAPS_PERIODS and isinstance(f.get("limit"), int) and isinstance(f.get("value"), int)}
    if held and not reasons:
        reasons = list(dict.fromkeys(_words(f) for f in result["findings"] if f["verdict"] in ("fail", "not_evaluable")
                                     and f.get("reason") and f.get("reason") != DECLARED)) or ["the Everyday Rules asked for your OK"]
    return Outcome(result["verdict"], held, limit, chain.terms.price_minor, reasons, asks,
                   refused=[_words(f) for f in refusing], ruleset=result["ruleset_id"], findings=seen, rules=sealed,
                   differences=_differences(result),
                   over_limit=bool(asking) and all(str(f.get("check", "")).startswith("caps/") for f in asking),
                   item=chain.terms.item, limits=limits)


#: The caps findings' periods (everyday-0.3.8 r05: one limit per action, one on the rolling 7-day total), by the
#: suffix of the finding's id, and the name the question gives each.
CAPS_PERIODS = {"7d": "weekly", "per_purchase": "per_order"}


def _period(finding: dict) -> str:
    """A caps finding's period: its id's suffix after "#" ("" for any other finding)."""
    fid = str(finding.get("id", ""))
    return fid.rsplit("#", 1)[1] if str(finding.get("check", "")).startswith("caps/") and "#" in fid else ""


#: The members of a finding the verdict seals (x-deal-v0 section 8); the checker's own words (``reason``) are not sealed.
SEALED_FINDING = ("id", "check", "verdict", "disposition", "limit", "value")
#: A finding the ruleset declares and the checker does not measure: never a difference (x-deal-v0 section 8).
DECLARED = "declared, not measured"


def _sealed(finding: dict) -> dict:
    return {k: finding[k] for k in SEALED_FINDING if finding.get(k) is not None}


def _field(finding_id: str) -> str:
    """A finding's id as a difference field (lowercase a-z0-9_), as evidencebook-deal's ``findingField`` makes it."""
    f = re.sub(r"[^a-z0-9_]+", "_", finding_id.lower()).strip("_")
    return f if f and "a" <= f[0] <= "z" else "rule_" + f


def _differences(result: dict) -> list[dict]:
    """The differences an ``escalate`` adds to the check: one per failing or not-evaluable finding, as
    evidencebook-deal's ``rulesDifferences`` folds them (internal/deal/rules_checker.go); an allow adds none."""
    if result["verdict"] == "allow":
        return []
    rule = "rules_" + result["verdict"] if result["verdict"] in ("escalate", "deny") else "rules_not_evaluable"
    out = [{"question": "safety", "rule": rule, "field": _field(f["id"])} for f in result["findings"]
           if f["verdict"] in ("fail", "not_evaluable") and f.get("reason") != DECLARED]
    return out or [{"question": "safety", "rule": rule}]


def _sha256(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


#: The rules whose disposition is ASK (the rules doc, Everyday Rules 27 v0.2): a failing one holds the order for the
#: person's OK, all of them as one ask (section 4.5). Rules 1 to 4 are DO (a failing one only withholds an allowance)
#: and 23 to 25 are NEVER (nothing here asks about them).
ASK_RULES = frozenset(range(5, 23)) | {26, 27}


def _is_ask(finding: dict) -> bool:
    m = re.match(r"r(\d{2})", str(finding.get("id", "")))
    return str(finding.get("check", "")).startswith("caps/") or (bool(m) and int(m.group(1)) in ASK_RULES)


def _is_never(finding: dict) -> bool:
    m = re.match(r"r(\d{2})", str(finding.get("id", "")))
    return bool(m) and int(m.group(1)) in (23, 24, 25)


#: Rule 22's two limits (capsule-engine go/v0.7.0, go/packs/everyday-0.3.8/pack-source.yaml, r22): a stated deposit
#: above 25% of the total, or above 100.00 (10,000 minor units).
UPFRONT_SHARE_BPS, UPFRONT_FIXED_MINOR = 2500, 10_000
UPFRONT_OTHER = "another of the rules' checks"


def upfront_words(check: dict | None) -> str:
    """Rule 22 in plain words, for the limit the check record's own amounts fail (Sherlock2 on #237: one wording for
    both would be false when the other limit is the one that failed). The sealed finding does not say which; the check
    record states the up-front amount and the price, so the words read them."""
    body = check or {}
    upfront, total = body.get("upfront_amount_minor"), (body.get("terms") or {}).get("price_minor")
    if isinstance(upfront, int) and isinstance(total, int) and total > 0 and upfront * 10_000 > total * UPFRONT_SHARE_BPS:
        return "more than a quarter of the price paid up front"
    if isinstance(upfront, int) and upfront > UPFRONT_FIXED_MINOR:
        return "a large amount paid up front"
    return UPFRONT_OTHER


def _words(finding: dict, upfront: dict | None = None) -> str:
    """The rule's own words for the person: the engine's reason without a trailing parenthetical about how the engine
    looked (Sherlock2, 2026-11-23). A caps finding that states its limit and value reads as those figures (Sherlock2 on
    evidencebook-skills#270); another caps finding adds them to the rule's words. Rule 22 (``upfront_amount``) reads as
    the receipt does, with the up-front amount from ``upfront`` (the check record's body), never a bare number
    (Sherlock2, #272 item 1)."""
    limit, value = finding.get("limit"), finding.get("value")
    if str(finding.get("check", "")).startswith("upfront_amount/") and upfront is not None:
        words = upfront_words(upfront)
        if words != UPFRONT_OTHER:
            return f"{words} ({upfront['upfront_amount_minor']:,} msat)"
        # the check's amounts fail neither limit as read here: the rule's own words, each amount with comma and unit
        return re.sub(r"\b(\d{4,})\b", lambda m: f"{int(m.group(1)):,} msat",
                      re.sub(r"\s*\([^)]*\)$", "", finding.get("reason", "the up-front amount is above the limit")))
    if isinstance(limit, int) and isinstance(value, int):
        if _period(finding) == "7d":
            return f"over your weekly limit: {value:,} msat with this order, limit {limit:,} msat"
        if _period(finding) == "per_purchase":
            return f"over your per-order limit: this order {value:,} msat, limit {limit:,} msat"
    out = re.sub(r"\s*\([^)]*\)$", "", finding.get("reason", "over the limit you set"))
    if limit is not None and value is not None:
        out += f" (limit {limit:,} msat, this order would bring it to {value:,} msat)"
    return out


def seal_note(node, deal_id: str, outcome: Outcome) -> None:
    """Maya's own record of what the deal check said, in her node book, with the rules' own words (the verdict record
    seals the findings without them)."""
    node.note(CHECKED, {"deal_id": deal_id, "ruleset": outcome.ruleset, "verdict": outcome.verdict,
                        "held": outcome.held, "decision": outcome.decision, "limit_msat": outcome.limit_msat,
                        "amount_msat": outcome.amount_msat, "reasons": outcome.reasons, "asks": outcome.asks, "refused": outcome.refused,
                        "findings": outcome.findings}, subject_ref=deal_id)


def gate(node, chain: dr.DealChain, limit: int, at: datetime,
         approve: Callable[[Outcome], bool] | None = None, ask_always: bool = False) -> Outcome:
    """Seal the check record and run the rules on it; return what they said once the order may go ahead. An order the
    rules hold is put to the person through ``approve`` (no ``approve``: declined); with ``ask_always`` every order is,
    held or not, so the one dialog that releases the payment also carries any hold reasons. A decline raises
    :class:`RuleHeld` (``reasons`` empty when nothing was held): the check is sealed, nothing else, and nothing is
    paid. Either answer is sealed as a note. ``approve`` returns the :class:`Answer` it showed the person (the dialog's
    words and the button) for a yes, or a plain truthy value when its words are :func:`screens.hold_question`'s, and a falsy
    value for a decline; an approval is kept on the outcome as that :class:`Answer`, for the approval record. A failing
    NEVER rule (23 to 25), a ``deny`` or a ``not_evaluable`` verdict raises :class:`RulesRefused`: there is no way to
    proceed, and nothing is asked or paid."""
    node.seal(chain, pay_check(chain, at, upfront=True))
    outcome = check(node, chain, len(node.deal_payloads(chain.deal_id)) - 1, limit)
    if outcome.refused:  # a NEVER rule failed: not a question for the person, and nothing is paid
        seal_note(node, chain.deal_id, outcome)
        raise RulesRefused("refused by the Everyday Rules, not put to you: " + "; ".join(outcome.refused))
    if outcome.verdict in ("deny", "not_evaluable"):
        seal_note(node, chain.deal_id, outcome)
        raise RulesRefused(f"the Everyday Rules answered {outcome.verdict} on this order, so it cannot go ahead")
    if outcome.held or ask_always:
        try:
            ok = approve(outcome) if approve is not None else False
        except Exception as exc:  # the question could not be put: nothing is paid and the order is not approved
            outcome.decision = "declined"
            seal_note(node, chain.deal_id, outcome)
            raise RulesError(f"the person could not be asked: {type(exc).__name__}: {exc}") from None
        outcome.decision = "approved" if ok else "declined"
        if isinstance(ok, Answer):
            outcome.answer = ok  # the words the dialog actually showed
        elif ok and outcome.held:
            import screens  # here, not at the top: screens imports buyer, which imports this module

            title, text = screens.hold_question(outcome.item, outcome.amount_msat, outcome.limits, outcome.reasons,
                                                outcome.over_limit)
            outcome.answer = Answer(f"{title}\n{text}", "Buy anyway")
    seal_note(node, chain.deal_id, outcome)
    if outcome.decision == "declined":
        raise RuleHeld(("held for your OK at deal check, and declined: " + "; ".join(outcome.reasons)) if outcome.held
                       else "the payment was not approved", outcome.reasons)
    return outcome
