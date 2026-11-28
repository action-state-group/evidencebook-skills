# SPDX-License-Identifier: Apache-2.0
"""Maya's side: read each seller's History card, assess each seller under her pack, pick, deal, pay, and dispute.

The card is the seller's shared ``standard_history/3`` bundle (:func:`flow.fetch_card`), checked with ``capsulectl
verify --bundle``. The assessment is ``capsule-engine admission evaluate`` under the demo pack; its inputs are what
Maya verified (the card) and what her own book holds about the seller, read from capsulectl's own report of each of
her deals with it (``deal report --read-only``): a ruling she holds against the seller is a verdict, adverse when it
went against the seller (Steven, ops u187: a person's own sealed ruling against a merchant decides NO). What the
evaluator reads and the decision are sealed in Maya's node book."""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import adjudicator as adj
import ard
import feeds
import flow
import limits
import party as pt
import pay as rails  # buyer.pay is the function below
import screens
import wire
from cast import ASK, BUYER, SELLERS, label
from pack import Pack

ASSESSED = "ard_assessment"
PICKED = "ard_pick"
CARD_RECEIVED = "ard_card_received"
DEAL_OPENED = "ard_deal_opened"
LISTING_CHECKED = "ard_listing_checked"  # one per seller a search found: what was fetched and checked (#345)
#: What the operator fills in for the rows the card cannot answer: the controller the pack's trust roots name, and the
#: witness of the card's checkpoint. A card carries its witness's receipt for its anchor and ``verify --bundle`` checks
#: it (evidencebook#957, ``flow.anchor_witness``); ``gather`` shows that check, and the operator note names the witness
#: as unchecked only for cards whose receipt did not pass (``screens.operator_note``). The pack's witness input stays
#: the operator's either way, so a card with no receipt (``ARD_WITNESS=off``) is assessed as before. Never printed.
OPERATOR_FACTS = {"controller": "demo-controller", "witness": pt.WITNESS_KEY}
#: The witness line when the card's time-stamp is not checked: a receipt that could not be checked, or none (Sherlock2's
#: words on #350).
STAMP_WITHHELD = "not checked: the card carries a time-stamp receipt this buyer could not check"
STAMP_NONE = "not checked: the card carries no time-stamp receipt"


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    stated: bool = False  # filled in or stated, not checked here


@dataclass
class Evidence:
    seller: str
    checks: list[Check] = field(default_factory=list)
    card: dict | None = None
    read: flow.CardRead | None = None
    card_record: str = ""

    def ok(self, name: str, detail: str = "") -> None:
        self.checks.append(Check(name, True, detail))

    def fail(self, name: str, detail: str) -> None:
        self.checks.append(Check(name, False, detail))

    def stated(self, name: str, detail: str) -> None:
        self.checks.append(Check(name, True, detail, stated=True))


@dataclass
class Own:
    """What Maya's own book holds about a seller, read from capsulectl's reports of her deals with it."""
    deals: int = 0
    settled: int = 0
    rulings: list[dict] = field(default_factory=list)  # [{"deal_id", "at", "adverse", "row", "value"}]


@dataclass
class Assessment:
    seller: str
    price_msat: int
    verdict: str
    tier: str | None
    cap_msat: int | None
    pack_id: str
    pack_digest: str
    reasons: list[str]
    rows: list[dict]
    record_id: str
    decision: dict
    own: Own


def _as_text(value: object) -> str | None:
    """A value the registry or a seller supplied, as canonical JSON text: the node book seals no floats, so a seller's
    float price or the registry's relevance score must not stop the buyer's records (or her search)."""
    return None if value is None else json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def record_search(maya: pt.Party, registry_url: str, query: str, entries: list[dict]) -> list[str]:
    """Keep the search's checks in Maya's own records, one ``ard_listing_checked`` note per seller found
    (evidencebook-skills#345, Sherlock2 on #352): its identifier, the address its entry was fetched (or tried) from,
    the sha256 of that entry's canonical JSON (:func:`card_digest`'s form), the offer the entry stated (the seller's
    own words, as JSON text), each check it passed and, when one failed, the plain reason and its detail. Each search adds its own
    notes under one ``search`` id with the number of sellers it found, so an incomplete batch shows; none is rewritten.
    Returns the record ids."""
    search_id, ids = uuid.uuid4().hex, []
    for e in entries:
        own = e.get("entry")
        rec = {"search": search_id, "sellers_found": len(entries), "seller": e.get("id", ""),
               "identifier": str(e.get("identifier", "")), "registry": registry_url, "query": query,
               "score": _as_text(e.get("score")), "fetched_from": e.get("fetched_from", ""),
               "entry_sha256": card_digest(own) if own is not None else "",
               "offer_stated": _as_text(own.get("x-demo-offer")) if isinstance(own, dict) else None,
               "checks": list(e.get("checks", [])), "passed": "problem" not in e}
        if "problem" in e:
            rec["problem"] = e["problem"]
            rec["detail"] = e.get("detail", "")
        ids.append(maya.note(LISTING_CHECKED, rec, subject_ref=e.get("id", ""))["record_id"])
    return ids


def gather(home: Path, maya: pt.Party, entry: dict) -> Evidence:
    """Fetch one seller's shared History card and check it: VALID under ``verify --bundle``, signed by the key the
    seller's verified commitment names, a ``standard_history/3`` card, its time-stamp receipt checked."""
    ev = Evidence(entry["id"])
    if entry.get("problem") or "commitment" not in entry:
        ev.fail("commitment", entry.get("problem", "no commitment"))
        return ev
    key = entry["commitment"]["key_id"]
    # the commitment's checks stay in Maya's records (the search's checks), never in her chat (#332, Sherlock2)
    try:
        r = flow.fetch_card(home, maya, entry["id"], key)
    except pt.Refused as exc:
        ev.fail("History card", str(exc))
        return ev
    ev.read, ev.card = r, r.card
    # no digests, key ids, derivation names or checkpoint hashes in Maya's chat (#332, Sherlock2); they stay in her own
    # records (the CARD_RECEIVED note below names the seller's key, the card's checkpoint and its digest)
    name = entry.get("name") or label(entry["id"])
    ev.ok("History card", f"signed by {name}, and it checks out, as of {screens.local_time(r.anchor_time, date=True)}")
    if r.witness_status == "pass":
        ev.ok("witness", f"time-stamped by {pt.WITNESS_NAME}: its receipt verifies under the witness's key")
    elif r.witness_status == "withheld":  # verify could not check it: no directory row, or the card's checkpoint
        ev.stated("witness", STAMP_WITHHELD)
    elif r.witness_status == "":  # no receipt carried: no witness took the card's checkpoint (or ARD_WITNESS=off)
        ev.stated("witness", STAMP_NONE)
    else:
        ev.fail("witness", f"the card's witness receipt does not verify ({r.witness_status or 'no status'})")
    ev.card_record = maya.note(CARD_RECEIVED, {"seller": key, "anchor": r.anchor, "card_sha256": card_digest(r.card)},
                               subject_ref=key)["record_id"]
    return ev


def card_digest(card: dict) -> str:
    return hashlib.sha256(json.dumps(card, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def own_history(maya: pt.Party, seller_key: str) -> Own:
    """Maya's own deals with the seller, from capsulectl: each deal's report as it stands. A row ruled by the deal's
    adjudicator is a verdict, adverse when it went against the seller."""
    own = Own()
    stamped = {n["statement"]["deal_id"]: n["statement"].get("stamped_at", "")
               for kind in (flow.RULING_ENTERED, flow.RULING_STAMPED) for n in maya.notes(kind)
               if n["statement"].get("stamped_at")}
    for d in maya.deals():
        if d.get("version") != "x-deal-v1" or d.get("counterparty_key") != seller_key:
            continue
        own.deals += 1
        try:
            rep = maya.report(d["deal_id"])
        except pt.Refused:
            continue  # a deal with records after its last checkpoint is read at the next one
        report = rep.get("report", rep)
        own.settled += 1 if report.get("settled") else 0
        for row in report.get("rows", []):
            r = row.get("ruling")
            if r and r.get("final"):
                # the ruling's time is when the witness stamped it; until then, when Maya's records last changed
                own.rulings.append({"deal_id": d["deal_id"], "at": stamped.get(d["deal_id"]) or d.get("last_record_at", ""),
                                    "row": row["id"],
                                    "value": r.get("value"), "adverse": r.get("against") == "seller"})
    return own


def inputs(ev: Evidence, price_msat: int, own: Own, now: datetime) -> dict:
    """The evaluator's inputs (capsule-engine ``admission/json.go``) from what Maya verified and her own book."""
    card = ev.card or {}
    r = ev.read
    bands = [{"currency": b["currency"], "decade": b["decade"], "subjects": b["held"] + b["did_not_hold"],
              "adverse": b["did_not_hold"]} for b in card.get("bands", []) if b.get("decade") is not None]
    c: dict[str, Any] = {"state": "verified" if ev.card else "unanswered", "bands": bands,
                         "disputes": flow.decided(card), **OPERATOR_FACTS}
    if r:
        c["first_checkpoint_at"], c["latest_checkpoint_at"] = r.anchor_time, r.anchor_time
    return {"now": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "amount": str(price_msat), "currency": "msat",
            "platform": {"release_attestation": "valid", "owner_signed": True}, "card": c,
            "selection": {"state": "unanswered", "unanswered_disputes": []},
            "own": {"exchanges": own.deals, "settled": own.settled, "held_halves": 0, "conflicting": 0,
                    "verdicts": [{"at": v["at"], "adverse": v["adverse"]} for v in own.rulings if v["at"]]},
            "operator": {"deny_listed": False, "allow_listed": True}, "subject": ev.seller,
            "vouches": [], "judged": {}, "asks": {}, "asks_made": 0}


def assess(maya: pt.Party, ev: Evidence, seller_key: str, price_msat: int, pack: Pack) -> Assessment:
    """Decide with capsule-engine under ``pack`` (with the x-deal-v1 admit body, so a GO can be sealed for the deal),
    and seal the decision in Maya's book as an ``ard_assessment`` note citing the card she read."""
    now = datetime.now(timezone.utc)
    own = own_history(maya, seller_key)
    refs = {"asks": [], "answers": [], "card_digest": card_digest(ev.card or {})}
    d = pt.decide(pack.path, inputs(ev, price_msat, own, now), refs)
    tier = d.get("tier")
    cap = pack.ceiling_msat(tier) if d["verdict"] == "LIMIT" and tier else None
    rows = d.get("rows", [])
    reasons = [x["row"] for x in rows if x.get("result") == "fail" and x.get("effect") not in (None, "none")]
    sealed = maya.note(ASSESSED, {"peer": seller_key, "decision": d["verdict"], "pack_id": pack.pack_id,
                                  "pack_digest": pack.digest, "tier": tier, "price_msat": price_msat, "limit_msat": cap,
                                  "own_rulings": len(own.rulings)},
                       subject_ref=seller_key, cites=(ev.card_record,) if ev.card_record else ())
    return Assessment(ev.seller, price_msat, d["verdict"], tier, cap, pack.pack_id, pack.digest, reasons, rows,
                      sealed["record_id"], d, own)


def names_only(words: str, seller: str) -> bool:
    """Whether ``words`` name ``seller`` (its label, or the label's first word) and no other seller: only then are they
    the person's own pick of it. Words naming two sellers ("choose between Alder and Kestrel") or none ("the cheaper
    one") are not."""
    said = set(re.findall(r"[a-z0-9]+", words.lower()))

    def named(key: str) -> bool:
        name = re.findall(r"[a-z0-9]+", SELLERS[key]["label"].lower())
        return bool(name) and name[0] in said
    return named(seller) and not any(named(k) for k in SELLERS if k != seller)


def seal_pick(maya: pt.Party, seller_key: str, chosen: Assessment, others: list[Assessment], said: str = "") -> str:
    """The pick, sealed before any deal or payment, citing every assessment it was made against. ``said`` is the
    person's own words naming the seller when they picked it (``by: maya``); without them the agent picked
    (``by: agent``)."""
    cites = tuple(a.record_id for a in [chosen, *others])
    rec = maya.note(PICKED, {"seller": seller_key, "price_msat": chosen.price_msat, "assessment": chosen.verdict,
                             "assessed_against": list(cites), "by": "maya" if said else "agent",
                             **({"said": said} if said else {})}, subject_ref=seller_key, cites=cites)
    return rec["record_id"]


# -- the deal --------------------------------------------------------------------------------------

@dataclass
class Deal:
    deal_id: str
    seller: str
    seller_key: str
    price_msat: int
    offer: str
    #: the rail token the intent and the check seal (pay.Rail.SEALED: "simulated" on the fake rail)
    rail: str = "lightning"
    #: the buyer's folder on the wire: the seller answers there
    me: str = BUYER
    #: the offer file to send (:func:`draft_deal`), and the intent the agreement cites
    offer_file: str = ""
    intent: str = ""


def draft_deal(maya: pt.Party, seller: str, seller_key: str, chosen: Assessment, adjudicator: dict,
               rail: str = "lightning", me: str = BUYER, limit: int | None = None, request: str = ASK,
               picked: str = "") -> Deal:
    """Maya's side of a deal from a GO assessment, before the seller hears of it: the offer (naming the adjudicator and
    the witness), written but not sent, and her intent. Her payment can be checked on it already (``deal check``), so
    the person answers before anything reaches the seller (evidencebook-skills#289, evidencebook#890). ``picked`` is
    her own words when she picked this seller: sealed as her pick of its item, so capsulectl's card never says the
    agent picked it (#454); without them the agent picked, and the card says so."""
    if chosen.verdict != "GO":
        raise pt.Refused(f"the assessment is {chosen.verdict}"
                         + (f": deals under {chosen.cap_msat:,} msat" if chosen.cap_msat else "")
                         + "; no deal opens and nothing is paid")
    item = SELLERS[seller]["item"]  # the seller's own listing (sellers/<name>.yaml)
    o = maya.offer(seller_key, item, chosen.price_msat, chosen.pack_digest, adjudicator)
    deal = Deal(o["deal_id"], seller, seller_key, chosen.price_msat, o["offer"], rail, me, offer_file=o["file"])
    deal.intent = maya.intent(deal.deal_id, request, "purchase", ["pay"], limit, label(seller), rail=rail,
                              domain=ard.publisher(seller))
    if picked:
        maya.picked(deal.deal_id, picked, item)
    return deal


def cancel_draft(maya: pt.Party, deal: Deal) -> None:
    """Withdraw an offer that was never sent (``deal offer cancel``): the seller's book holds nothing of it, and Maya's
    holds the cancelled offer with any check and answer sealed on it."""
    maya.run("offer", "cancel", deal.offer, "--out", maya.tmp("cancel.json"))


def send_deal(home: Path, maya: pt.Party, deal: Deal, chosen: Assessment, say: Callable[[str], None]) -> Deal:
    """Send a drafted offer and agree: the seller's agreement, Maya's admission (the assessment's own decision) and
    her agreement."""
    seller, me = deal.seller, deal.me
    wire.send_json(home, seller, deal.deal_id, "from", {"buyer": me})  # before the offer: where the seller answers
    wire.send(home, seller, deal.deal_id, "offer", deal.offer_file)
    maya.note(DEAL_OPENED, {"deal_id": deal.deal_id, "seller": deal.seller_key, "seller_name": seller, "price_msat": deal.price_msat,
                            "offer": deal.offer, "rail": deal.rail, "me": me}, subject_ref=deal.deal_id)
    say(f"offer sent to {label(seller)}: {deal.price_msat:,} msat for {SELLERS[seller]['item']}; the agreement names "
        f"the deal's adjudicator and {pt.WITNESS_NAME}")
    try:
        agreed_by_seller = wire.wait(home, me, deal.deal_id, "agree", flow.WAIT_S)
    except pt.Refused:
        # withdraw the offer the seller has not taken, so a seller window opened later does not agree to a deal nobody
        # pays (a deal the seller agreed would count on its card as undecided)
        for kind in ("offer", "from"):
            wire.path(home, seller, deal.deal_id, kind).unlink(missing_ok=True)
        raise pt.Refused(f"{label(seller)} did not answer the offer in {flow.WAIT_S} s (its window may be closed): the "
                         "offer is withdrawn, nothing was paid") from None
    maya.receive(agreed_by_seller)
    maya.admit(deal.deal_id, chosen.decision)
    agreed = maya.agree(deal.offer, deal.intent)
    wire.send(home, seller, deal.deal_id, "agree", agreed["file"])
    say(f"agreed: both sides signed the agreement for deal {deal.deal_id[5:13]}")
    return deal


def open_deal(home: Path, maya: pt.Party, seller: str, seller_key: str, chosen: Assessment,
              adjudicator: dict, say: Callable[[str], None], rail: str = "lightning", me: str = BUYER) -> Deal:
    """Open Maya's side of the deal from a GO assessment and agree it (:func:`draft_deal`, then :func:`send_deal`)."""
    return send_deal(home, maya, draft_deal(maya, seller, seller_key, chosen, adjudicator, rail, me), chosen, say)


def deals_from_notes(maya: pt.Party) -> list[Deal]:
    """Maya's deals, oldest first, from her own node book: a reopened window has no other memory of them."""
    out = []
    for n in maya.notes(DEAL_OPENED):
        st = n["statement"]
        if "seller_name" in st:
            out.append(Deal(st["deal_id"], st["seller_name"], st["seller"], st["price_msat"], st["offer"], st["rail"], st["me"]))
    return out


def seller_of(maya: pt.Party) -> Callable[[str], str]:
    """The seller's folder on the wire for each of Maya's deals: a ruling's naming statement goes to that deal's seller."""
    by_deal = {d.deal_id: d.seller for d in deals_from_notes(maya)}
    return lambda deal_id: by_deal[deal_id]


def check_payment(maya: pt.Party, deal: Deal, payment_ref: str) -> dict:
    """Maya's final review of the payment (``deal check``): it pauses for her answer, with the card she is shown."""
    return maya.check(deal.deal_id, "pay", SELLERS[deal.seller]["item"], deal.price_msat, label(deal.seller),
                      # a rail other than lightning states the most the payment may take (capsulectl's check)
                      {"amount_minor": deal.price_msat, "payment_ref": payment_ref,
                       **({} if deal.rail == "lightning" else {"authorized_max_minor": deal.price_msat})}, rail=deal.rail,
                      domain=ard.publisher(deal.seller))


def pay(home: Path, maya: pt.Party, deal: Deal, check: dict, reference: str, simulated: bool) -> None:
    """After the rail paid: the payer leg, handed to the seller with the payment's reference (the seller's payee leg
    names it)."""
    leg = maya.pay_leg(deal.deal_id, check["check_id"])
    wire.send_json(home, deal.seller, deal.deal_id, "ref",
                   {"amount_msat": deal.price_msat, "payment_ref": reference, "simulated": simulated})
    wire.send(home, deal.seller, deal.deal_id, "paid", leg)


@dataclass
class Question:
    """The one dialog before a payment: its title, text and buttons, and what the rules held, if they did."""
    title: str
    text: str
    yes: str
    no: str
    held: limits.Held | None = None


def question(deal: Deal, check: dict, held: limits.Held | None, summary: str, rail_words: str = "") -> Question:
    """The dialog for the checked payment. Held by the rules: the held-order question (:func:`screens.hold_question`,
    Steven's design in evidencebook-skills#270), Buy anyway or Don't buy. Otherwise the payment dialog, Pay or Cancel.
    A check that paused shows capsulectl's card in full below (:func:`screens.with_card`), since the person's answer is
    sealed with it (Sherlock2's ruling on evidencebook#890, Option A)."""
    card = "" if check.get("proceed") else check.get("card", "")
    if held is not None:
        title, text = screens.hold_question(SELLERS[deal.seller]["item"], deal.price_msat, held.limits, held.reasons,
                                            held.over_limit, label(deal.seller), rail_words or None)
        return Question(title, screens.with_card(text, card), "Buy anyway", "Don't buy", held)
    return Question("Approve this payment", screens.with_card(summary, card), "Pay", "Cancel")


def open_and_pay(home: Path, maya: pt.Party, seller: str, seller_key: str, chosen: Assessment, adjudicator: dict,
                 rail: Any, summary: str, ask: Callable[[Question], Any], say: Callable[[str], None],
                 simulated: bool, said: Callable[[str], str] = lambda text: text,
                 rail_words: str = "", request: str = ASK, picked: str = "") -> tuple[Deal, Any] | None:
    """The payment checked first, then the person's answer, then the deal: nothing reaches the seller until the person
    said yes (evidencebook-skills#289). Maya's offer is drafted, not sent (:func:`draft_deal`), the invoice is made and
    capsulectl's payment check runs on it (under the spending limit she confirmed, if any: :mod:`limits`;
    her sealed intent carries the same figure, with ``request``, what she asked for in her own words, and ``picked``, her
    own words when she picked this seller: :func:`draft_deal`). Then one
    dialog (:func:`question`) through ``ask``, which returns True or ``"yes"`` for the yes button, ``"no"`` for the
    other, and anything else when nobody answered or no dialog was shown. On yes, a paused check is answered in the words
    the dialog showed and the button (``said`` renders them as the dialog did: the dialog as shown, card included, then the button, never words of the person's own beyond that click), the offer is sent and agreed, and the
    invoice paid. Otherwise the person's no to a paused check is sealed (no answer is never sealed as one), the unsent
    offer is cancelled, and None is returned: nothing was sent and nothing paid."""
    limit = limits.sealed(maya)  # the one she confirmed, in her own book: every entry to a payment reads it here
    if limit is not None:
        limits.pin(maya, limit)
    else:
        limits.unpin(maya)
    deal = draft_deal(maya, seller, seller_key, chosen, adjudicator, rail=rail.SEALED, me=maya.name, limit=limit, request=request,
                      picked=picked)
    try:  # until the offer is sent, any failure cancels it: the seller never hears of it
        inv = rail.checked_invoice(chosen.price_msat)  # a failure here moved no money (pay.NotSent)
        feeds.payment(home, "invoice", maya.name, seller, chosen.price_msat, inv.payment_hash, rail.SEALED)
        check = check_payment(maya, deal, inv.payment_hash)
        if check.get("verdict") == "deny":  # a rule that refuses (23 to 25): not put to the person, nothing is paid
            raise pt.Refused("refused by your rules, not put to you: " + "; ".join(limits.refusal(check)) +
                             "; nothing was sent to the seller and nothing was paid")
        held = limits.read(check, limit)
        q = question(deal, check, held, summary, rail_words)
        answer = ask(q)
        words = said(f"{q.title}\n{q.text}")
        if answer is not True and answer != "yes":
            if answer == "no" and not check.get("proceed"):
                maya.approve(deal.deal_id, check, "hold", f"{words}\nAnswer: {q.no}")
            cancel_draft(maya, deal)
            return None
        if not check.get("proceed"):
            maya.approve(deal.deal_id, check, "proceed", f"{words}\nAnswer: {q.yes}")
    except BaseException:
        cancel_draft(maya, deal)
        raise
    send_deal(home, maya, deal, chosen, say)
    maya.sending(deal.deal_id, check["check_id"])  # refused here, nothing has moved
    try:
        payment = rail.pay_invoice(inv)
    except rails.PaymentFailed:  # the rail says no money moved: the payment no longer counts against the limit
        feeds.payment(home, "not_paid", maya.name, seller, chosen.price_msat, inv.payment_hash, rail.SEALED)
        maya.payment_failed(deal.deal_id, check["check_id"])
        raise
    feeds.payment(home, "paid" if payment.status == "succeeded" else "sent", maya.name, seller, chosen.price_msat,
                  payment.reference, rail.SEALED)
    pay(home, maya, deal, check, payment.reference, simulated=simulated)
    return deal, payment


def take_delivery(home: Path, maya: pt.Party, deal: Deal) -> str | None:
    """Keep the seller's payee leg and its delivery record once both are on the stage, and return what the delivery
    record says it shipped; None while either is missing. Each file is kept once, so the payment tool and Maya's agent
    (:func:`pick_up_deliveries`) can both call it."""
    seen = [n["statement"]["observed"] for n in maya.notes(flow.DELIVERED_SEEN) if n["statement"]["deal_id"] == deal.deal_id]
    if seen:
        return seen[0]
    files = {k: wire.path(home, deal.me, deal.deal_id, k) for k in ("received", "act")}
    if not all(f.is_file() for f in files.values()):
        return None
    for kind, f in files.items():
        mark = maya.dir / "handled" / f"{deal.deal_id}.{kind}"
        if not mark.exists():
            maya.receive(f)
            mark.parent.mkdir(exist_ok=True)
            mark.touch()
    observed = _observed(json.loads(files["act"].read_text()))
    maya.note(flow.DELIVERED_SEEN, {"deal_id": deal.deal_id, "observed": observed}, subject_ref=deal.deal_id)
    return observed


def await_delivery(home: Path, maya: pt.Party, deal: Deal, seconds: float = flow.WAIT_S) -> str:
    """Wait for the seller's payee leg and its delivery record (:func:`take_delivery`); refused after ``seconds``, and
    Maya's agent picks the delivery up when it comes (:func:`pick_up_deliveries`)."""
    stop = time.monotonic() + seconds
    while True:
        observed = take_delivery(home, maya, deal)
        if observed is not None:
            return observed
        if time.monotonic() >= stop:
            raise pt.Refused(f"{label(deal.seller)} has not recorded the payment and the delivery yet "
                             f"({label(deal.seller)}'s window may be closed). The payment is recorded on Maya's side; this window shows the delivery when it comes")
        time.sleep(0.5)


def agreed(home: Path, deal: Deal) -> bool:
    """Whether the seller agreed to this deal: its agreement reached Maya (:func:`open_deal`). An offer withdrawn
    unanswered has none."""
    return wire.path(home, deal.me, deal.deal_id, "agree").is_file()


def paid(home: Path, deal: Deal) -> bool:
    """Whether Maya handed the seller her payer leg for this deal."""
    return wire.path(home, deal.seller, deal.deal_id, "paid").is_file()


def pick_up_deliveries(home: Path, maya: pt.Party, say: Callable[[str], None]) -> list[str]:
    """For each of Maya's paid deals whose delivery the payment tool did not see (the seller's window was closed, say):
    take the delivery once it is on the stage and say what was shipped. Nothing is sent in Maya's name
    (:func:`after_delivery`; her own yes does that, F10). Returns the deals picked up now."""
    done = []
    for deal in deals_from_notes(maya):
        if not paid(home, deal) or any(n["statement"]["deal_id"] == deal.deal_id for n in maya.notes(flow.DELIVERED_SEEN)):
            continue
        observed = take_delivery(home, maya, deal)
        if observed is None:
            continue
        done.append(deal.deal_id)
        what = shipped(observed)
        say(screens.delivered_line(label(deal.seller), what))
        say(after_delivery(deal.seller, what))
    return done


def _observed(doc: Any) -> str:
    """The ``observed`` token of a perform record file (the record travels whole; its payload says what was seen)."""
    found = []

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            if "observed" in o and isinstance(o["observed"], str):
                found.append(o["observed"])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str) and len(o) > 40:
            import base64
            try:
                walk(json.loads(base64.b64decode(o + "==")))
            except Exception:
                pass
    walk(doc)
    return found[0] if found else ""


def shipped(observed: str) -> str:
    """The delivery record's token in words: ``partial:badges_150_of_200`` is "150 of 200 badges"."""
    tail = observed.split(":", 1)[-1]
    parts = tail.split("_")
    if len(parts) == 4 and parts[2] == "of":
        return f"{parts[1]} of {parts[3]} {parts[0]}"
    return observed


#: Maya's own note that she said she received a deal's delivery, so her statement is sealed once.
RECEIVED_SAID = "ard_received_said"


def after_delivery(seller: str, what: str) -> str:
    """What Maya is told once a delivery arrives. Nothing is said in her name here: whether she received what she paid
    for is her own answer (run finding F10, evidencebook-skills#304)."""
    if what.startswith("200 of 200"):
        return (f"Nothing has been sent in Maya's name. If she received it, she can say so, and {label(seller)} gets "
                "her statement that she received what she paid for.")
    return "Maya ordered 200 badges. If fewer arrived, she can dispute the delivery."


def received_said(maya: pt.Party, deal: Deal) -> bool:
    return any(n["statement"]["deal_id"] == deal.deal_id for n in maya.notes(RECEIVED_SAID))


def disputed(maya: pt.Party, deal: Deal) -> bool:
    """Whether Maya disputed this deal's delivery (:func:`dispute` notes it): her statement then says it was not met."""
    return any(n["statement"]["deal_id"] == deal.deal_id for n in maya.notes(flow.CASE))


def to_confirm(maya: pt.Party, deals: list[Deal]) -> list[Deal]:
    """Of these deals with one seller, those whose receipt Maya can still confirm: not yet said, not disputed."""
    return [d for d in deals if not received_said(maya, d) and not disputed(maya, d)]


def confirm_by_question(home: Path, maya: pt.Party, deal: Deal, seller_label: str, ask: Callable[[str], bool],
                        say: Callable[[str], None]) -> bool:
    """The run script's own receipt step: ask Maya, and only her yes sends her statement. True when it was sent."""
    if not ask(f"Did you receive what you paid for from {seller_label}? Choosing yes sends {seller_label} your "
               "statement that you received it."):
        say("Nothing was sent in Maya's name.")
        return False
    close_received(home, maya, deal)
    say("Maya's statement sent: she received what she paid for.")
    return True


def close_received(home: Path, maya: pt.Party, deal: Deal) -> None:
    """Maya said she got what she paid for: her statement that both rows were met, handed to the seller. Called only
    after her own yes (desktop_server.ard_confirm_received's dialog, or the run script's question), never on a
    delivery's arrival."""
    if received_said(maya, deal):
        return
    if disputed(maya, deal):
        raise pt.Refused("Maya disputed this delivery: her dispute stands, and nothing was sent")
    wire.send(home, deal.seller, deal.deal_id, "statement",
              maya.statement(deal.deal_id, {pt.PAID: "met", pt.DELIVERED: "met"}))
    maya.note(RECEIVED_SAID, {"deal_id": deal.deal_id}, subject_ref=deal.deal_id)


def dispute(home: Path, maya: pt.Party, deal: Deal, say: Callable[[str], None]) -> dict:
    """Maya disputes the delivery: her statement that it was not met, then ``deal dispute``; the dispute goes to the
    seller and to the adjudicator the agreement names, which then asks each side for its books."""
    # the delivery row is what she disputes; she says the payment was met only when her payer leg reached the seller,
    # never for a deal whose payment did not go through
    rows = {pt.DELIVERED: "not_met", **({pt.PAID: "met"} if paid(home, deal) else {})}
    wire.send(home, deal.seller, deal.deal_id, "statement", maya.statement(deal.deal_id, rows))
    d = maya.dispute(deal.deal_id, pt.DELIVERED)
    wire.send(home, deal.seller, deal.deal_id, "dispute", d["file"])
    adj.send_dispute(home, Path(d["file"]), deal.deal_id, buyer=deal.me, seller=deal.seller)
    maya.note(flow.CASE, {"deal_id": deal.deal_id}, subject_ref=deal.deal_id)
    say("dispute sent to the seller and to the adjudicator")
    return d


def seller_statements(home: Path, maya: pt.Party) -> None:
    """Keep any statement or naming statement a seller sent."""
    for kind in ("statement", "named"):
        for deal_id, f in wire.pending(home, maya.name, kind):
            mark = maya.dir / "handled" / f"{deal_id}.{kind}"
            if not mark.exists():
                maya.receive(f)
                mark.parent.mkdir(exist_ok=True)
                mark.touch()


def sellers_label(key: str, commitments: dict[str, dict]) -> str:
    return next((SELLERS[n]["label"] for n, c in commitments.items() if c.get("key_id") == key), key[:8] + "…")
