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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import adjudicator as adj
import ard
import flow
import party as pt
import wire
from cast import ASK, BUDGET_MSAT, BUYER, ITEM, SELLERS, label
from pack import Pack

ASSESSED = "ard_assessment"
PICKED = "ard_pick"
CARD_RECEIVED = "ard_card_received"
DEAL_OPENED = "ard_deal_opened"
#: What the operator fills in for the rows the card cannot answer: the controller the pack's trust roots name, and the
#: witness of the card's checkpoint. No verb at the pinned evidencebook gives a buyer the witness receipt for a /3
#: card's anchor (neither the card bundle nor the history_card/2 staple carries one), so Maya cannot check it; the screen
#: says these are filled in by the operator, not checked (``screens.OPERATOR_NOTE``). Never printed.
OPERATOR_FACTS = {"controller": "demo-controller", "witness": pt.WITNESS_KEY}


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


def gather(home: Path, maya: pt.Party, entry: dict) -> Evidence:
    """Fetch one seller's shared History card and check it: VALID under ``verify --bundle``, signed by the key the
    seller's verified commitment names, a ``standard_history/3`` card, its witness receipts checked."""
    ev = Evidence(entry["id"])
    if entry.get("problem") or "commitment" not in entry:
        ev.fail("commitment", entry.get("problem", "no commitment"))
        return ev
    key = entry["commitment"]["key_id"]
    ev.ok("commitment", f"signature verifies under {key[:8]}…, and matches the seller's entry")
    try:
        r = flow.fetch_card(home, maya, entry["id"], key)
    except pt.Refused as exc:
        ev.fail("History card", str(exc))
        return ev
    ev.read, ev.card = r, r.card
    ev.ok("History card", f"standard_history/3, signed by {r.signer[:8]}… (the key the commitment names), "
                          f"verify --bundle: {r.verdict}, as of checkpoint {r.anchor[:8]}… at {r.anchor_time}")
    if r.witness_status == "pass":
        ev.ok("witness", f"time-stamped by {pt.WITNESS_NAME}: its receipt verifies under the witness's key")
    else:
        ev.stated("witness", "the card carries no witness receipt, so its time-stamp is not checked here")
    ev.card_record = maya.note(CARD_RECEIVED, {"seller": key, "anchor": r.anchor, "card_sha256": card_digest(r.card)},
                               subject_ref=key)["record_id"]
    return ev


def card_digest(card: dict) -> str:
    return hashlib.sha256(json.dumps(card, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def own_history(maya: pt.Party, seller_key: str) -> Own:
    """Maya's own deals with the seller, from capsulectl: each deal's report as it stands. A row ruled by the deal's
    adjudicator is a verdict, adverse when it went against the seller."""
    own = Own()
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
                own.rulings.append({"deal_id": d["deal_id"], "at": d.get("last_record_at", ""), "row": row["id"],
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


def seal_pick(maya: pt.Party, seller_key: str, chosen: Assessment, others: list[Assessment]) -> str:
    """The pick, sealed before any deal or payment, citing every assessment it was made against."""
    cites = tuple(a.record_id for a in [chosen, *others])
    rec = maya.note(PICKED, {"seller": seller_key, "price_msat": chosen.price_msat, "assessment": chosen.verdict,
                             "assessed_against": list(cites)}, subject_ref=seller_key, cites=cites)
    return rec["record_id"]


# -- the deal --------------------------------------------------------------------------------------

@dataclass
class Deal:
    deal_id: str
    seller: str
    seller_key: str
    price_msat: int
    offer: str
    rail: str = "lightning"
    me: str = BUYER  # the buyer's folder on the wire: the seller answers there  # the rail token the intent and the check seal (pay.Rail.SEALED: "simulated" on the fake rail)


def open_deal(home: Path, maya: pt.Party, seller: str, seller_key: str, chosen: Assessment,
              adjudicator: dict, say: Callable[[str], None], rail: str = "lightning", me: str = BUYER) -> Deal:
    """Open Maya's side of the deal from a GO assessment: the offer (naming the adjudicator and the witness), the
    seller's agreement, her admission (the assessment's own decision), her intent and her agreement."""
    if chosen.verdict != "GO":
        raise pt.Refused(f"the assessment is {chosen.verdict}"
                         + (f": deals under {chosen.cap_msat:,} msat" if chosen.cap_msat else "")
                         + "; no deal opens and nothing is paid")
    o = maya.offer(seller_key, ITEM, chosen.price_msat, chosen.pack_digest, adjudicator)
    deal = Deal(o["deal_id"], seller, seller_key, chosen.price_msat, o["offer"], rail, me)
    wire.send_json(home, seller, deal.deal_id, "from", {"buyer": me})  # before the offer: where the seller answers
    wire.send(home, seller, deal.deal_id, "offer", o["file"])
    maya.note(DEAL_OPENED, {"deal_id": deal.deal_id, "seller": seller_key, "price_msat": deal.price_msat},
              subject_ref=deal.deal_id)
    say(f"offer sent to {label(seller)}: {deal.price_msat:,} msat for {ITEM}; the agreement names the deal's adjudicator "
        f"and {pt.WITNESS_NAME}")
    maya.receive(wire.wait(home, me, deal.deal_id, "agree", flow.WAIT_S))
    maya.admit(deal.deal_id, chosen.decision)
    intent = maya.intent(deal.deal_id, ASK, "purchase", ["pay"], BUDGET_MSAT, label(seller), rail=rail,
                         domain=ard.publisher(seller))
    agreed = maya.agree(deal.offer, intent)
    wire.send(home, seller, deal.deal_id, "agree", agreed["file"])
    say(f"agreed: both sides signed the agreement for deal {deal.deal_id[5:13]}")
    return deal


def check_payment(maya: pt.Party, deal: Deal, payment_ref: str) -> dict:
    """Maya's final review of the payment (``deal check``): it pauses for her answer, with the card she is shown."""
    return maya.check(deal.deal_id, "pay", ITEM, deal.price_msat, label(deal.seller),
                      # a rail other than lightning states the most the payment may take (capsulectl's check)
                      {"amount_minor": deal.price_msat, "payment_ref": payment_ref,
                       **({} if deal.rail == "lightning" else {"authorized_max_minor": deal.price_msat})}, rail=deal.rail,
                      domain=ard.publisher(deal.seller))


def pay(home: Path, maya: pt.Party, deal: Deal, check: dict, reference: str, simulated: bool) -> None:
    """After the rail paid: the payer leg, handed to the seller with the payment's reference (the seller's payee leg
    names it)."""
    leg = maya.pay_leg(deal.deal_id, check["check_id"], reference)
    wire.send_json(home, deal.seller, deal.deal_id, "ref",
                   {"amount_msat": deal.price_msat, "payment_ref": reference, "simulated": simulated})
    wire.send(home, deal.seller, deal.deal_id, "paid", leg)


def await_delivery(home: Path, maya: pt.Party, deal: Deal) -> str:
    """Keep the seller's payee leg and its delivery record; return what the delivery record says it shipped."""
    maya.receive(wire.wait(home, deal.me, deal.deal_id, "received", flow.WAIT_S))
    act = wire.wait(home, deal.me, deal.deal_id, "act", flow.WAIT_S)
    maya.receive(act)
    body = json.loads(act.read_text())
    observed = _observed(body)
    maya.note(flow.DELIVERED_SEEN, {"deal_id": deal.deal_id, "observed": observed}, subject_ref=deal.deal_id)
    return observed


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


def close_received(home: Path, maya: pt.Party, deal: Deal) -> None:
    """Maya got what she paid for: her statement that both rows were met, handed to the seller."""
    wire.send(home, deal.seller, deal.deal_id, "statement",
              maya.statement(deal.deal_id, {pt.PAID: "met", pt.DELIVERED: "met"}))


def dispute(home: Path, maya: pt.Party, deal: Deal, say: Callable[[str], None]) -> dict:
    """Maya disputes the delivery: her statement that it was not met, then ``deal dispute``; the dispute goes to the
    seller and, with her adjudicator copy, to the adjudicator the agreement names."""
    wire.send(home, deal.seller, deal.deal_id, "statement",
              maya.statement(deal.deal_id, {pt.PAID: "met", pt.DELIVERED: "not_met"}))
    d = maya.dispute(deal.deal_id, pt.DELIVERED)
    wire.send(home, deal.seller, deal.deal_id, "dispute", d["file"])
    copy = maya.bundle(deal.deal_id, "adjudicator", "the deal's adjudicator", wait=120, say=say)
    case = adj.open_case(Path(d["file"]), copy)
    maya.note(flow.CASE, {"deal_id": deal.deal_id, "case": case["case"], "copy": case["copies"][0]},
              subject_ref=deal.deal_id)
    return case


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
