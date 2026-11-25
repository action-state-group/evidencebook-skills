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
from cast import DEALS_EACH

if TYPE_CHECKING:
    from buyer import Assessment, Evidence

PACK_NOTE = "a copy, not published · placeholder thresholds"
#: What the demo adapter fills in for the demo operator (buyer.inputs): those rows pass by construction, not by a check.
OPERATOR_NOTE = ("filled in by the operator, not checked: the platform, the allow-list, the card's witness and "
                 "controller")
CLAIMS_NOTE = "claims-held is not read today: no card carries claims yet"
ASSESSMENT_NOTE = ("the agent's assessment of each seller; the presenter's pick decides who is paid, "
                   "and nothing is paid above a seller's limit")
#: Said wherever a seller's card is shown as signed or time-stamped: its first deals are the seed's sample history, so a
#: witnessed count never reads as real trade (the twin's plan review, checked by the coordinator, 2026-11-25).
SAMPLE_NOTE = f"Its first {DEALS_EACH} deals are sample history the operator made before this run."
WITNESS_LINE = (f"time-stamped by {pt.WITNESS_NAME}. The operator, Action State, also runs every party here, so the "
                "witness is not independent of them.")
#: The adjudicator's conflict determination, as the ruling records it and the dialog shows it.
ADJUDICATOR_INDEPENDENCE = ("This adjudicator is run by the operator, who also runs every party here: it is not "
                            "independent of the parties.")


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


def signed_line(name: str, witness_checked: bool = False) -> str:
    """Who signed the card, and its time-stamp when Maya could check it (no verb gives her the receipt today)."""
    if witness_checked:
        return f"Signed by {name} and {WITNESS_LINE} These are the seller's own counts. {SAMPLE_NOTE}"
    return f"Signed by {name}. These are the seller's own counts. {SAMPLE_NOTE}"


def own_ruling(a: Assessment) -> dict | None:
    return next((v for v in a.own.rulings if v["adverse"]), None)


def decision_line(a: Assessment, ev: Evidence, ceiling_msat_for_tier: int | None = None) -> str:
    """One line: the decision and why, for this seller and this price (Sherlock2's wording, #285)."""
    if a.verdict == "GO":
        within = f" ({a.tier}, under {msat(ceiling_msat_for_tier)})" if ceiling_msat_for_tier else ""
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

