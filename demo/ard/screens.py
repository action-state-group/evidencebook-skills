# SPDX-License-Identifier: Apache-2.0
"""The words the audience reads, in one place so the terminal and the Goose windows say the same thing.

Wording rules (design §8, Sherlock2 11-17, and Sherlock2's what-check on #285): the screen says *assessment*, never
*admission*; every amount is msat; a seller's history is shown, never scored, and never called lost, failed or
dishonest; counts are the seller's own, signed and witnessed, and the screen says so; the adjudicator and the witness
are said to be run by Action State, which runs every party here, so neither is independent of them."""
from __future__ import annotations

from typing import TYPE_CHECKING

import party as pt
from adjudicator import CHALLENGE_DAYS
from cast import SAMPLE_DEALS

if TYPE_CHECKING:
    from buyer import Assessment, Evidence

PACK_NOTE = "a copy, not published · placeholder thresholds"
#: What the demo adapter fills in for the demo operator (buyer.inputs): those rows pass by construction, not by a check.
OPERATOR_NOTE = ("Some inputs were set by the operator and not checked: which marketplace the seller is on, the "
                 "list of sellers this pack accepts, who time-stamps the seller's card, and who controls the seller's "
                 "key.")
ASSESSMENT_NOTE = ("the agent's assessment of each seller; the presenter's pick decides who is paid, "
                   "and nothing is paid above a seller's limit")
#: Said wherever a seller's card is shown as signed or time-stamped: its first deals are the seed's sample history, so a
#: witnessed count never reads as real trade (the twin's plan review, checked by the coordinator, 2026-11-25).
def sample_note(seller: str) -> str:
    """Said wherever a seller's card is shown: how many of its deals are the sample history ``demo.py seed`` made."""
    return f"Its first {SAMPLE_DEALS[seller]} deals are sample history the operator made before this run."
WITNESS_LINE = (f"time-stamped by {pt.WITNESS_NAME}. The operator, Action State, also runs every party here, so the "
                "witness is not independent of them.")
#: The adjudicator's conflict determination, as the ruling records it and the dialog shows it.
ADJUDICATOR_INDEPENDENCE = ("This adjudicator is run by the operator, who also runs every party here: it is not "
                            "independent of the parties.")


def trying_again(what: str, exc: BaseException) -> str:
    """A step an agent does on its own that failed this round, in a person's words (evidencebook-skills#327, Sherlock2:
    "one plain line saying it will retry"). A slow witness says so; any other failure says only that it is retried. The
    failure's own text goes to the party's log (:meth:`party.Party.log`), never into a chat."""
    if isinstance(exc, pt.WitnessSlow):
        return f"{what}: waiting for {pt.WITNESS_NAME}, which is slow or not answering; {TRYING_AGAIN}"
    return f"{what}: not done yet (the reason is in this party's log, agent.log); {TRYING_AGAIN}"


#: How every :func:`trying_again` line ends: a party's log says it once until something else happens (once_per_failure).
TRYING_AGAIN = "trying again"


def once_per_failure(failing: set[str], line: str) -> bool:
    """Whether ``line`` should be said: a :func:`trying_again` line only while it is not already said for this failure
    (a step that keeps failing says so once, not every round or every request); any other line is said, and ends every
    failure said so far, so a failure that comes back after progress is said again."""
    if line.endswith(TRYING_AGAIN):
        if line in failing:
            return False
        failing.add(line)
        return True
    failing.clear()
    return True


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


def local_time(iso: str, date: bool = False) -> str:
    """A record's UTC time as a person reads it: this Mac's local time with its zone ("12:16:32 CST"), with the date
    when ``date`` is set ("2026-11-25 12:16:32 CST"). The records keep UTC; only what is shown changes (run finding F7,
    2026-11-25). Anything that is not an ISO time is shown as it is."""
    from datetime import datetime
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
    except (ValueError, AttributeError):
        return iso
    return t.strftime(("%Y-%m-%d " if date else "") + "%H:%M:%S %Z")


def msat(n: int) -> str:
    return f"{n:,} msat"


def plural(n: int, one: str, many: str = "") -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def card_line(card: dict) -> str:
    """A card's counts in words: deals counted, how many did not hold, any still open, and the disputes others raised
    about the holder (decided against it, of those decided; open)."""
    o = card["outcomes"]
    r = card.get("disputes", {}).get("received", {})
    b = r.get("by_outcome", {})
    decided = sum(b.get(k, 0) for k in ("for", "against", "split", "no_finding"))
    # Steven's words (#272 item 4): "didn't go as agreed", "every one went as agreed"; never "failed" or "did not hold"
    still = f", {o['undecided']} not final yet" if o.get("undecided") else ""
    went = ("every one went as agreed" if not o["did_not_hold"] and not o.get("undecided")
            else f"{o['did_not_hold']} didn't go as agreed{still}")
    return (f"{plural(o['of'], 'deal')}, {went}. Disputes others raised about it: "
            f"{b.get('against', 0)} decided against it, of {decided} decided; {b.get('open', 0)} open.")


def signed_line(name: str, seller: str, witness_checked: bool = False) -> str:
    """Who signed the card, and its time-stamp when Maya could check it (no verb gives her the receipt today)."""
    if witness_checked:
        return f"Signed by {name} and {WITNESS_LINE} These are the seller's own counts. {sample_note(seller)}"
    return f"Signed by {name}. These are the seller's own counts. {sample_note(seller)}"


def own_ruling(a: Assessment) -> dict | None:
    return next((v for v in a.own.rulings if v["adverse"]), None)


def decision_line(a: Assessment, ev: Evidence, ceiling_msat_for_tier: int | None = None) -> str:
    """One line: the decision and why, for this seller and this price (Sherlock2's wording, #285)."""
    if a.verdict == "GO":
        within = f" (allows deals under {msat(ceiling_msat_for_tier)})" if ceiling_msat_for_tier else ""
        return f"GO: {msat(a.price_msat)} is within this pack's limit for it{within}"
    card = ev.card or {}
    b = card.get("disputes", {}).get("received", {}).get("by_outcome", {})
    against = b.get("against", 0)
    decided = sum(b.get(k, 0) for k in ("for", "against", "split", "no_finding"))
    ruled = own_ruling(a)
    if a.verdict == "NO" and ruled:
        when = local_time(ruled.get("at") or "", date=True).split(" ")[0] if ruled.get("at") else ""
        line = (f"NO: you hold a ruling against this seller (deal {ruled['deal_id'][5:13]}, delivery not met, ruled {when}). "
                "Your rules block a seller you hold a ruling against for 180 days.")
        if against:
            line += (f" Its card also counts {plural(against, 'dispute')} decided against it, of {decided} decided; "
                     "the card does not say which deal.")
        return line
    if a.verdict == "LIMIT" and "disputes-against" in a.reasons:
        cap = f" At this limit the pack allows deals under {msat(a.cap_msat)} only, so no deal opens at {msat(a.price_msat)}." \
            if a.cap_msat else ""
        return (f"LIMIT: a dispute about this seller was decided against it ({against} of {decided} decided); this pack "
                f"limits any lost dispute.{cap}")
    if a.verdict == "LIMIT" and a.cap_msat is not None:
        why = "; " + ", ".join(a.reasons) if a.reasons else ""
        return f"LIMIT: this history supports deals under {msat(a.cap_msat)}; the {msat(a.price_msat)} price is not under that{why}"
    return f"{a.verdict}: see the assessment rows"


def limit_outcome(a: Assessment) -> str:
    """What a pick of a seller that is not GO shows: nothing opens and nothing is paid."""
    if a.verdict == "LIMIT" and a.cap_msat:
        return (f"LIMIT: {msat(a.price_msat)} is at or over this seller's limit (deals under {msat(a.cap_msat)}); "
                "no deal opens and nothing is paid")
    return f"{a.verdict}: no deal opens and nothing is paid"


def check_lines(ev: Evidence) -> list[str]:
    return [f"{'–' if c.stated else '✓' if c.ok else '✗'} {c.name}: {c.detail}" for c in ev.checks]


# -- the dispute, the case and the ruling ------------------------------------------------------------

def delivered_line(seller: str, shipped: str) -> str:
    return f"{seller}'s delivery record says {shipped} were shipped."


DISPUTE_RAISED = ("Dispute raised on this deal's delivery. Sent to {seller} and to the adjudicator your agreement names. "
                  "Nothing is refunded by this step.")


def rule_question(deal_id: str, row: str, seller: str) -> str:
    """The Adjudicator window's dialog: the presenter's decision, recorded by the operator. A challenge is x-deal-v1's
    ``dispute`` of kind ``challenge`` (PROFILE.md §5; ``deal dispute --challenge``, which "changes no row's status");
    the window is 7 days (Steven, ops u214, 2026-11-24), a practice-statement constant (evidencebook
    ``docs/design/861-four-books.md`` §6; :data:`adjudicator.CHALLENGE_DAYS`)."""
    return (f"Rule on deal {deal_id[5:13]}, row {row}: not met, against {seller}. "
            f"Conflict: the operator runs this adjudicator and every party here, so it is not independent "
            f"of the parties. Either side may challenge it within {CHALLENGE_DAYS} days. A challenge is recorded beside the "
            f"ruling and "
            f"never replaces it.")



#: The foot of the held-order question, whichever layout (#270 items 2 and 3). It names no place to change the rules:
#: the demo has none (Steven's feedback of 2026-11-25; Sherlock2 on #321, option a), and the limit is set where the
#: windows are opened (ARD_LIMIT_MSAT).
HELD_FOOT = "Your answer is saved on the receipt."
HELD_TITLE = "The Everyday Rules held this order for your OK"  # Sherlock2 on #237


def hold_question(item: str, price_msat: int, limits: dict, reasons: list[str], over_limit: bool,
                  seller: str | None = None, rail: str | None = None) -> tuple[str, str]:
    """The one question for an order the Everyday Rules hold, as a dialog's title and text (evidencebook-skills#270,
    Steven's "Spending-limit question"). Over a limit alone it shows the figures from the sealed caps findings
    (``limits``: ``weekly`` and ``per_order``, each the finding's ``(limit, value)``, never recomputed); when another rule
    holds the order too, it lists every reason in their place (Steven, 2026-11-23: one ask, every reason). ``rail`` is
    the payment's rail clause, such as "on the simulated rail: no money moves"."""
    weekly, per_order = limits.get("weekly"), limits.get("per_order")
    if over_limit and weekly and not per_order:  # both limits failing: the reasons layout, so neither is dropped
        cap, total = weekly
        spent, with_order, limit = msat(total - price_msat), msat(total), msat(cap)
        title = "This order goes over your weekly limit"
        figures = [f"Spent this week: {spent}", f"With this order: {with_order}", f"Your weekly limit: {limit}"]
        foot = HELD_FOOT
    elif over_limit and per_order and not weekly:
        cap, value = per_order
        this, limit = msat(value), msat(cap)
        title = "This order goes over your per-order limit"
        figures = [f"This order: {this}", f"Your per-order limit: {limit}"]
        foot = HELD_FOOT
    else:
        title, figures, foot = HELD_TITLE, [r[:1].upper() + r[1:] for r in reasons], HELD_FOOT  # each with a capital (Sherlock2 on #270)
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
    return ("The Everyday Rules held this order for your OK, and nothing was paid: "
            + "; ".join(reasons) + ".")


#: The line above capsulectl's card in a dialog: the card is what the person's answer is sealed with, so it is shown in
#: full (Sherlock2's ruling on evidencebook#890, Option A: every word the record says Maya approved was on her screen).
CARD_HEAD = "Saved with your answer:"


def with_card(text: str, card: str) -> str:
    """A dialog's text with capsulectl's card shown in full below it (:data:`CARD_HEAD`)."""
    return f"{text}\n\n{CARD_HEAD}\n{card}" if card else text
