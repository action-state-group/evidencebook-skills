# SPDX-License-Identifier: Apache-2.0
"""The words the audience reads, in one place so the terminal and the popup say the same thing.

Wording rules (design §8, Sherlock2 11-17): the screen says *assessment*, never *admission*; every
amount is msat from the invoice; a seller's history is shown, never scored, and never called lost,
failed or dishonest; the sample and demo labels are always there."""
from __future__ import annotations

from buyer import Assessment, Evidence

BANNER = ("DEMO · sample history, run by the demo operator · test nodes with real Lightning (the buyer's node pays, "
          "the sellers' node receives; both sellers settle to the one test node)")
BANNER_FAKE = "DEMO · sample history, run by the demo operator · SIMULATED payment: no money moves"


BANNER_LOCAL = ("DEMO · sample history, run by the demo operator · real Lightning (real money, mainnet) between two demo wallets "
                "(the buyer's wallet pays, the seller's wallet receives; both sellers settle to the one test wallet)")


def banner(rail: str) -> str:
    return {"lightning": BANNER, "local": BANNER_LOCAL}.get(rail, BANNER_FAKE)
PACK_NOTE = "a copy, not published · placeholder thresholds"
#: What the demo adapter fills in for the demo operator (buyer.inputs): those rows pass by construction, not by a check.
OPERATOR_NOTE = ("filled in by the operator, not checked: the platform, the allow-list, the card's witness and "
                 "controller; this assessment does not read the card's witness time-stamp")
CLAIMS_NOTE = "claims-held is not read today: no card carries claims yet"
#: The demo adapter reads the seller's selection as verified although it carries no inclusion proofs; the screen says so
#: (design note §3.6 item 6). The buyer skill's own rule is that an unproven selection is never a pass.
SELECTION_NOTE = "selection: signed answer, no inclusion proofs; this pack counts it"
ASSESSMENT_NOTE = ("the agent's assessment of each seller; the presenter's pick decides who is paid, "
                   "and nothing is paid above a seller's limit")


def fee_note(fee_msat: int | None, real: bool) -> str:
    """The fee on Maya's payment line: on a real rail it is the routing fee her own wallet reports for the
    send. It says nothing about what the seller's wallet was credited (Maya has no record of that)."""
    if fee_msat is None:
        return ""
    return f" (routing fee {fee_msat} msat, as her wallet reports it)" if real else f" (fee {fee_msat} msat)"


def seller_credit_note(price_msat: int) -> str:
    """The seller's receipt line on a real rail: the agreed price is in its records, the amount its wallet
    was credited is not (the wallet provider may keep a receiving fee)."""
    return (f"Agreed price {price_msat:,} msat. What this seller's wallet was credited is not in these records: "
            "its wallet provider may deduct a receiving fee.")


def msat(n: int) -> str:
    return f"{n:,} msat"


def _totals(ev: Evidence) -> tuple[int, int]:
    """Deals counted and deals that did not hold, over every band of the card (its own ``of``)."""
    outcomes = ev.card["outcomes"]  # the card's own totals
    return outcomes["of"], outcomes["did_not_hold"]


def card_line(ev: Evidence, sample_card: bool) -> str:
    """The card summary: deals counted and how many did not hold, with the label its count needs, if any: a
    sample card is said to be one, and a did-not-hold from the owner's own note says so (u597). No "sample
    history" tag of the demo's on the count (Ethan, 2026-11-17)."""
    of, bad = _totals(ev)
    if sample_card:
        label = "sample card, written by hand; not recomputed from records"
    elif bad:  # the owner's own outcome_note: not confirmed by the buyer or by a ruling
        label = "did not hold counted from the seller's own note, not confirmed by the buyer or a ruling"
    else:
        return f"{bad} of {of} deals did not hold"
    return f"{bad} of {of} deals did not hold ({label})"


def decision_line(a: Assessment, ev: Evidence, max_permille: int, ceiling_msat_for_tier: int | None = None) -> str:
    """One line: the decision and why, for this seller and this price."""
    if a.verdict == "GO":
        within = f" ({a.tier}, under {msat(ceiling_msat_for_tier)})" if ceiling_msat_for_tier else ""
        return f"GO: {msat(a.price_msat)} is within this pack's limit for it{within}"
    if a.verdict == "LIMIT" and a.cap_msat is not None:
        why = (f"; the pack lets at most {max_permille} of every 1,000 deals not hold"
               if "band-history" in a.reasons else "")
        return f"LIMIT: this history supports deals under {msat(a.cap_msat)}; the {msat(a.price_msat)} price is not under that{why}"
    return f"{a.verdict}: see the assessment rows"


def limit_outcome(a: Assessment) -> str:
    """What a tap on a seller that is not GO shows: nothing opens and nothing is paid."""
    if a.verdict == "LIMIT" and a.cap_msat:
        why = "; more of its deals did not hold than the pack allows" if "band-history" in a.reasons else ""
        return (f"LIMIT: {msat(a.price_msat)} is at or over this seller's limit (deals under {msat(a.cap_msat)}){why}; "
                "no deal opens and nothing is paid")
    return f"{a.verdict}: no deal opens and nothing is paid"


def button(name: str, a: Assessment) -> str:
    """The popup button: it says what a tap does."""
    if a.verdict == "GO":
        return f"Pay {name} {msat(a.price_msat)}"
    if a.verdict == "LIMIT":
        return f"Pick {name} (outside its limit: nothing is paid)"
    return f"Pick {name} ({a.verdict}: nothing is paid)"


def check_lines(ev: Evidence) -> list[str]:
    return [f"{'–' if c.stated else '✓' if c.ok else '✗'} {c.name}: {c.detail}" for c in ev.checks]


#: The foot of the spending-limit question (Steven's design, evidencebook-skills#270 item 2).
LIMIT_FOOT = "Your answer is saved on the receipt. Change your limit any time in Everyday Rules."
#: The foot when a rule other than the limit holds the order (#270 item 3).
RULES_FOOT = "Your answer is saved on the receipt. Change your rules any time in Everyday Rules."
HELD_TITLE = "The Everyday Rules held this order for your OK"  # Sherlock2 on #237


def hold_question(item: str, price_msat: int, limits: dict, reasons: list[str], over_limit: bool,
                  seller: str | None = None, rail: str | None = None) -> tuple[str, str]:
    """The one question for an order the Everyday Rules hold, as a dialog's title and text (evidencebook-skills#270,
    Steven's "Spending-limit question"). Over a limit alone it shows the figures from the sealed caps findings
    (``limits``: ``weekly`` and ``per_order``, each the finding's ``(limit, value)``, never recomputed); when another rule
    holds the order too, it lists every reason in their place (Steven, 2026-11-23: one ask, every reason). ``rail`` is
    the payment's rail clause, such as "on the simulated rail: no money moves"."""
    weekly, per_order = limits.get("weekly"), limits.get("per_order")
    if over_limit and weekly:
        cap, total = weekly
        spent, with_order, limit = msat(total - price_msat), msat(total), msat(cap)
        title = "This order goes over your weekly limit"
        figures = [f"Spent this week: {spent}", f"With this order: {with_order}", f"Your weekly limit: {limit}"]
        foot = LIMIT_FOOT
    elif over_limit and per_order:
        cap, value = per_order
        this, limit = msat(value), msat(cap)
        title = "This order goes over your per-order limit"
        figures = [f"This order: {this}", f"Your per-order limit: {limit}"]
        foot = LIMIT_FOOT
    else:
        title, figures, foot = HELD_TITLE, [r[:1].upper() + r[1:] for r in reasons], RULES_FOOT  # each with a capital (Sherlock2 on #270)
    what = f"{item} from {seller}" if seller else item
    line = f"{what} for {msat(price_msat)}" + (f", {rail}" if rail else "") + ". Nothing has been paid yet."
    return title, "\n".join([line, *figures, foot])


def rules_approved(reasons: list[str], over_limit: bool = True) -> str:
    """What the screen says after the person approves a held order."""
    what = "this order over your limit" if over_limit else "this held order"
    return (f"You approved {what} (" + "; ".join(reasons) + "). Paying now. Your approval goes "
            "into this deal's records and will show on its receipt.")  # Sherlock2 on #265: not recorded until paid


def rules_held(reasons: list[str]) -> str:
    """What the screen says when the deal check holds an order: over the spending limit the person set (Steven's ruling
    that a failing caps check on a person-set limit escalates, ops u325) or on any other ASK rule (Sherlock2, 2026-11-23)."""
    return ("Held for your OK at deal check, nothing paid. The Everyday Rules held this order: "
            + "; ".join(reasons) + ".")
