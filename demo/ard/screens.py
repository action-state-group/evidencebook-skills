# SPDX-License-Identifier: Apache-2.0
"""The words the audience reads, in one place so the terminal and the Goose windows say the same thing.

Wording rules (design §8, Sherlock2 11-17, and Sherlock2's what-check on #285): the screen says *assessment*, never
*admission*; every amount is msat; a seller's history is shown, never scored, and never called lost, failed or
dishonest; counts are the seller's own, signed and witnessed, and the screen says so; the adjudicator and the witness
are said to be run by Action State, which runs every party here, so neither is independent of them."""
from __future__ import annotations

from typing import TYPE_CHECKING

import party as pt
from cast import SAMPLE_DEALS

if TYPE_CHECKING:
    from buyer import Assessment, Evidence

PACK_NOTE = "example rules for this demo, not a published set"  # Sherlock2 on #332 (buzz 458673a9)
#: What the demo adapter fills in for the demo operator (buyer.inputs): those rows pass by construction, not by a check.
OPERATOR_NOTE = ("Some inputs were set by the operator and not checked: which marketplace the seller is on, the "
                 "list of sellers this pack accepts, who time-stamps the seller's card, and who controls the seller's "
                 "key.")
#: The note once some card shown carries a time-stamp receipt that verified (evidencebook#957; Sherlock2's words on
#: #350): who time-stamps a card is the operator's only where its receipt is not checked, and a passing receipt shows
#: only that the stamp came from the key the operator named (``party.witness_directory``), so that stays on the screen.
OPERATOR_NOTE_SOME_STAMPED = ("Some inputs were set by the operator and not checked: which marketplace the seller is "
                              "on, the list of sellers this pack accepts, who time-stamps a seller's card whose receipt "
                              "is not checked, which key belongs to the witness, and who controls the seller's key.")
OPERATOR_NOTE_STAMPED = ("Some inputs were set by the operator and not checked: which marketplace the seller is on, the "
                         "list of sellers this pack accepts, which key belongs to the witness, and who controls the "
                         "seller's key.")


def operator_note(stamped: int, of: int) -> str:
    """The operator note for ``of`` cards shown, ``stamped`` of them with a time-stamp receipt that verified."""
    if of and stamped == of:
        return OPERATOR_NOTE_STAMPED
    return OPERATOR_NOTE_SOME_STAMPED if stamped else OPERATOR_NOTE
ASSESSMENT_NOTE = ("the agent's assessment of each seller; the presenter's pick decides who is paid, "
                   "and nothing is paid above a seller's limit")
#: Said wherever a seller's card is shown as signed or time-stamped: its first deals are the seed's sample history, so a
#: witnessed count never reads as real trade (the twin's plan review, checked by the coordinator, 2026-11-25).
def sample_note(seller: str) -> str:
    """Said wherever a seller's card is shown: how many of its deals are the sample history ``demo.py seed`` made."""
    return f"Its first {SAMPLE_DEALS[seller]} deals are sample history the operator made before this run."
WITNESS_LINE = (f"time-stamped by {pt.WITNESS_NAME}. The operator, Action State, also runs every party here, so the "
                "witness is not independent of the parties.")
#: The adjudicator's conflict determination, as the ruling records it and the dialog shows it.
ADJUDICATOR_INDEPENDENCE = ("This adjudicator is run by the operator, who also runs every party here: it is not "
                            "independent of the parties.")


def own_sample_note(seller: str, made: int, real: bool) -> str:
    """:func:`sample_note` as the seller's owner reads it in their own window (Sherlock2 on evidencebook-skills#456):
    "your" first deals, then the deals made in this run, counted from the seller's own records (``made``:
    :func:`flow.deals_made`, never the card, whose counts can lag a stamp), on this run's rail: "the only deal made in
    this run (simulated payment, no money moved)", never "real". On a real rail it names the rail only, not a payment,
    which the deal's own lines report."""
    n = SAMPLE_DEALS[seller]
    line = f"Your first {n} deals are sample history the operator made before this run"
    rail = "on the real Lightning rail" if real else "simulated payment, no money moved"
    if made <= 0:
        return line + "; no deal has been made in this run yet."
    if made == 1:
        return line + f"; the other one is the only deal made in this run ({rail})."
    return line + f"; {made} deals were made in this run ({rail})."


def trying_again(what: str, exc: BaseException) -> str:
    """A step an agent does on its own that failed this round, in a person's words (evidencebook-skills#327, Sherlock2:
    "one plain line saying it will retry"). A slow witness says so; any other failure says only that it is retried. The
    failure's own text goes to the party's log (:meth:`party.Party.log`), never into a chat."""
    if isinstance(exc, pt.WitnessSlow):
        return f"{what}: waiting for {pt.WITNESS_NAME}, which is slow or not answering; {TRYING_AGAIN}"
    return f"{what}: not done yet (the reason is in your log, agent.log); {TRYING_AGAIN}"


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
    """The seller's receipt line on a real rail, read by its owner: the agreed price is in their records, the amount
    their wallet was credited is not (the wallet provider may keep a receiving fee)."""
    return (f"Agreed price {price_msat:,} msat. What your wallet was credited is not in these records: "
            "your wallet provider may deduct a receiving fee.")


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


def stop(name: str) -> str:
    """``name`` ending a sentence: a name that already ends in a period ("Alder Print Co.") gets no second one
    (evidencebook-skills#362)."""
    return name if name.endswith(".") else name + "."


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
    # A /3 card leaves out a deal no named witness has timed and tallies it in not_counted.no_witness_time (AAC SH
    # §11.6; the shared copy carries it too); Sherlock2's words (evidencebook#979). A /4 card has no such member.
    waiting = card.get("not_counted", {}).get("no_witness_time", 0)
    if not o["of"]:  # Sherlock2 on #362: never "0 deals, every one went as agreed", nor "no disputes" over one
        # Sherlock2 on #394: none counted but some waiting reads "No deals counted yet: N deal(s) waiting for a
        # time-stamp", ending like #362's sentence when there is no dispute
        counted = (f"No deals counted yet: {plural(waiting, 'deal')} waiting for a time-stamp" if waiting
                   else "No deals yet")
        ds = card.get("disputes", {})
        if not any(ds.get(k, {}).get("of", 0) or any(ds.get(k, {}).get("by_outcome", {}).values())
                   for k in ("received", "raised")):
            return f"{counted}, and no disputes."
        left = ""
    else:
        counted = f"{plural(o['of'], 'deal')}, {went}"
        left = f" {plural(waiting, 'more deal')} not counted yet: waiting for a time-stamp." if waiting else ""
    return (f"{counted}.{left} Disputes others raised about it: "
            f"{b.get('against', 0)} decided against it, of {decided} decided; {b.get('open', 0)} open.")


#: The remedy a ruling against the seller carries here: none, since every deal is agreed as not refundable (each side's
#: own sealed intent says ``recourse.refundable: false``: the buyer's in ``buyer.py``, the seller's in ``flow.py``).
NO_REFUND = "No refund: this deal was agreed as not refundable."


def ruled_for_buyer(report: dict, seller: str, record=None) -> list[str]:
    """What a ruling for the buyer means for her, from capsulectl's report of her deal (evidencebook-skills#334,
    Sherlock2's words): who ruled, on what, the outcome, and that no refund follows, since every deal here is agreed as
    not refundable (``recourse.refundable: false`` in her intent). Only a ruled row the adjudicator found not met against
    the seller. ``record`` is the seller's own signed delivery record as her files hold it (:func:`flow.delivery_record`),
    or None. Sherlock2 on #457 (buzz 7e446929, 79366361): the line says who ruled, on what, and how many were delivered,
    and names what was signed, not our reading of it; her agent had said the seller "didn't deliver", then "because"."""
    out = []
    for row in report.get("rows", []):
        r = row.get("ruling") or {}
        if row.get("status") == "ruled" and r.get("against") == "seller" and r.get("value") == "not_met":
            what = {pt.DELIVERED: "delivery", pt.PAID: "payment"}.get(row.get("id"), row.get("id"))
            ground = _ground(row, record, f"{seller}'s")
            out.append(f"The adjudicator ruled for you {ground}{NO_REFUND}" if ground
                       else f"The adjudicator ruled for you: {what} not met, against {stop(seller)} {NO_REFUND}")
    return out


def _ground(row: dict, record, whose: str) -> str:
    """What a ruling against the seller on the delivery rests on, as its own signed delivery record says it: its own
    statement that the delivery was not met when the record states that, else the record itself; "" when the line has
    no record to name (another row, or none held)."""
    if record is None or row.get("id") != pt.DELIVERED:
        return ""
    on = ("own signed statement that the delivery was not met" if record.states_not_met
          else "own signed delivery record")
    return f"on {whose} {on} ({record.shipped} delivered). "


def ruled_for_seller(report: dict, stamped_at: str, record=None) -> list[str]:
    """What a ruling the seller entered says, from its own records (evidencebook-skills#360, Steven's run at 2fa6abe:
    "the seller should see that line too"): who ruled and the outcome from its ``deal report`` row and, for a ruling
    against it on the delivery, what it rests on as its own signed delivery record says it (``record``,
    :func:`flow.delivery_record`); the time Action State's witness stamped the ruling as the seller's agent noted it when
    it took the ruling (``stamped_at``, "" while it holds no receipt); and, for a ruling against it, the remedy Maya's card
    shows (:data:`NO_REFUND`). Sherlock2 on #457 (buzz 7e446929, 79366361): "The adjudicator ruled against you on your
    own signed statement that the delivery was not met (150 of 200 badges delivered). Action State's witness
    time-stamped it at ..." (its agent had said the witness ruled, for not delivering, then "because")."""
    out = []
    for row in report.get("rows", []):
        r = row.get("ruling") or {}
        if row.get("status") != "ruled" or not r:
            continue
        what = {pt.DELIVERED: "delivery", pt.PAID: "payment"}.get(row.get("id"), row.get("id"))
        found = "not met" if r.get("value") == "not_met" else "met"
        when = (f"{pt.WITNESS_NAME} time-stamped it at {local_time(stamped_at, date=True)}." if stamped_at
                else f"{pt.WITNESS_NAME} has not time-stamped it yet.")
        against_it = r.get("against") == "seller" and r.get("value") == "not_met"
        ground = _ground(row, record, "your") if against_it else ""
        if ground:
            line = f"The adjudicator ruled against you {ground}{when}"
        else:
            who = {"seller": "The adjudicator ruled against you", "buyer": "The adjudicator ruled for you"}.get(
                r.get("against"), "The adjudicator ruled")
            line = f"{who}: {what} {found}. {when}"
        if against_it:
            line += f" {NO_REFUND}"
        out.append(line)
    return out


def limit_line(limit_msat: int | None, pack_ceilings: list[int]) -> str:
    """The spending limit the person confirmed, or that none is set and what limits apply then (evidencebook-skills#331): the
    pack's own limits, one per history tier, read from the pack. Names no one; the amounts are configuration."""
    if limit_msat is not None:
        return (f"Your spending limit: {msat(limit_msat)} for any one order, and {msat(limit_msat)} in total over 7 days. "
                "Each payment is checked against it.")  # Sherlock2 on #354 (buzz 7bef2399)
    cs = [msat(c) for c in sorted(pack_ceilings)]
    under = cs[0] if len(cs) == 1 else ", ".join(cs[:-1]) + " or " + cs[-1]
    return (f"No spending limit is set yet, so only this pack's limits apply: deals under {under}, depending on the "
            "seller's history.")  # "yet": a limit is set only from the person's yes (Sherlock2 on #361)


#: The limit dialog's yes button (ard_set_limit).
LIMIT_YES = "Set limit"


def limit_question(limit_msat: int) -> tuple[str, str]:
    """The dialog that sets a spending limit the person's agent proposed (evidencebook-skills#361): only their click on
    :data:`LIMIT_YES` sets it. Its words are sealed with the limit."""
    return ("Set your spending limit",
            f"Set your spending limit to {msat(limit_msat)} for any one order, and {msat(limit_msat)} in total over "
            "7 days? Each payment is then checked against it, and an order over it waits for your OK.")


def within_limit(price_msat: int, limit_msat: int | None) -> str:
    """Whether a price fits the person's limit for one order (the caps finding fails only over it); the 7-day total is
    checked at payment, against the deals she has paid by then. "" with no limit set."""
    if limit_msat is None:
        return ""
    if price_msat <= limit_msat:
        return f" Within your limit of {msat(limit_msat)} for one order; your 7-day total is checked at payment."
    return f" Over your limit of {msat(limit_msat)} for one order: the order would wait for your OK at payment."


def listing_lines(item: dict) -> list[str]:
    """A seller's ARD listing as the search fetched and checked it (evidencebook-skills#345), in Sherlock2's shape
    (buzz 9a59de7c): the verdict in the header, the site name once with its caveat, the offer as the seller's own
    unsigned words, then the checks. Named fields only, never the entry's description or a URL (those stay in the
    buyer's ``ard_listing_checked`` record). Names no party."""
    name = item.get("name", "the seller")
    entry = item.get("entry")
    if entry is None:
        return [f"{name}: no listing could be read at the search: {item.get('problem', 'not fetched')}."]
    checked = "problem" not in item
    out = [f"{name}: its listing at the search. " + ("It checks out." if checked else f"It did not pass: {item['problem']}.")]
    tm = entry.get("trustManifest")
    named = tm.get("identity") if isinstance(tm, dict) else None
    listed = item.get("publisher") or "none"
    site = listed if named == listed else f"{named or 'none named in the listing'}, though the registry names {listed}"
    out.append(f"  site: {site} (a demo site: nothing proves who runs it)")
    reg = item.get("registry") or {}
    if reg.get("displayName") != entry.get("displayName"):
        out.append(f"  name: {entry.get('displayName')}, though the registry names it {reg.get('displayName')}")
    offer = entry.get("x-demo-offer")
    if offer is not None and not isinstance(offer, dict):
        out.append("  offer: not readable in this listing")
    elif offer:
        price = offer.get("price_msat")
        stated = msat(price) if isinstance(price, int) else str(price)
        product = f"; product {offer['product']} in the catalog stand-in" if offer.get("product") else ""
        out.append(f"  offer: {offer.get('item')} at {stated} (the seller's own words, not signed{product})")
    out += [f"  checked: {c}" for c in item.get("checks", [])]
    if not checked:
        out.append(f"  not passed: {item['problem']}")
    return out


def signed_line(name: str, seller: str, witness_checked: bool = False) -> str:
    """Who signed the card, and its time-stamp when its receipt verified (``witness_checked``)."""
    if witness_checked:
        return f"Signed by {name} and {WITNESS_LINE} These are the seller's own counts. {sample_note(seller)}"
    return f"Signed by {stop(name)} These are the seller's own counts. {sample_note(seller)}"


def own_ruling(a: Assessment) -> dict | None:
    return next((v for v in a.own.rulings if v["adverse"]), None)


def open_disputes_line(name: str, card: dict) -> str:
    """Under a GO, the disputes still open about this seller, from its card. The pack's open-disputes row only records
    them (pack-source.yaml: anyone can open one), so a bare GO right after the buyer disputed this seller would read as
    if the dispute had changed nothing without saying why (Sherlock2 on #418, 2026-11-27). Empty when none is open."""
    n = card.get("disputes", {}).get("received", {}).get("by_outcome", {}).get("open", 0)
    if not n:
        return ""
    return (f"{name} has {plural(n, 'open dispute')} (not final yet). This pack records open disputes but does not hold "
            "for them, since anyone can open one. A dispute decided against the seller would lower its limit, and a "
            "ruling against it that you hold would block buying from it for 180 days.")


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


def dispute_stated(seller: str, shipped: str | None) -> str:
    """What Maya's dispute says and what it does not, kept apart (evidencebook-skills#457: her agent called it "your
    signed statement that the delivery was short: 150 of 200 badges"): her statement says only "not met"; a count is the
    seller's own delivery record."""
    said = "Your signed statement says the delivery was not met; it gives no count."
    if shipped:
        return f"{said} The count, {shipped} shipped, is {seller}'s own delivery record."
    return f"{said} {seller} has sent no delivery record yet."


#: The foot of the held-order question, whichever layout (#270 items 2 and 3). It names no place to change the rules:
#: the demo has none (Steven's feedback of 2026-11-25; Sherlock2 on #321, option a); the limit is the one the person
#: confirmed in chat (ard_set_limit, #361).
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
        title = "This order goes over your 7-day limit"
        figures = [f"Spent in the last 7 days: {spent}", f"With this order: {with_order}", f"Your 7-day limit: {limit}"]
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
