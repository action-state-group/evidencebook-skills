# SPDX-License-Identifier: Apache-2.0
"""The deal flow both front ends run (the script, ``demo.py run``, and the Goose windows, ``desktop_server.py``): a
seller's agent, which answers on its own, and the buyer's and the adjudicator's steps, which a person drives.

Every party is its own capsulectl-deal profile (:mod:`party`); they meet through the stage (:mod:`stage`): each
seller's commitment and its shared History card under ``<home>/stage``, and the files the parties hand each other
(:mod:`wire`). A dispute goes to the local ledger-cloud adjudicator (:mod:`adjudicator`). Nothing here seals a deal
record or computes a row's status: each step is a capsulectl verb, and what the screen says is read back from it."""
from __future__ import annotations

import base64
import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import adjudicator as adj
import ard
import party as pt
import wire
from cast import ADJUDICATOR, BUYER, ITEM, SELLERS, label

_paths_setup = pt._paths  # party already put the Goose reference on the path
import commitment as cm  # noqa: E402
import goose_node as gn  # noqa: E402

#: Node-book record types of the demo (its own names; capsulectl refuses a library name).
JOINED = gn.JOINED
CASE = "ard_case"            # a party sent its copy to the adjudicator for a case
RULING_ENTERED = "ard_ruling_entered"
RULING_STAMPED = "ard_ruling_stamped"  # the ruling's witnessed time, once a fetched copy carried its receipt
BOOK_SENT = "ard_book_sent"
DELIVERED_SEEN = "ard_delivery_seen"
#: How long a party waits for the other side's next file before it gives up on that step.
WAIT_S = 180


def stage_dir(home: Path) -> Path:
    return Path(home).expanduser() / "stage"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# -- the card ---------------------------------------------------------------------------------------

@dataclass
class CardRead:
    """A shared History card bundle as a buyer read it: the card, its anchor, who signed it and what was verified."""
    card: dict
    anchor: str
    anchor_time: str
    signer: str
    verdict: str
    witness_status: str
    file: Path


def read_card(bundle: Path) -> tuple[dict, dict, str]:
    """The card, its ``as_of`` and the signing key of a ``standard-history card`` bundle (the card is the disclosed
    ``agent_input`` of the bundle's one record)."""
    doc = json.loads(Path(bundle).read_text())
    rec = doc["records"][0]
    card = doc["disclosures"][rec["capsule_id"]]["agent_input"]
    return card, doc["extensions"]["x-standard-history/v0"]["as_of"], rec["key_id"]


def publish_card(home: Path, p: pt.Party) -> Path:
    """Write the party's shared card (as of its newest checkpoint) where buyers fetch it."""
    src = p.card_bundle(shared=True)
    dest = stage_dir(home) / "cards" / f"{p.name}.json"
    wire.write_atomic(dest, src.read_bytes())
    return dest


def fetch_card(home: Path, reader: pt.Party, seller: str, key_id: str) -> CardRead:
    """Fetch a seller's shared card from the stage and verify it with ``capsulectl verify --bundle``: VALID, signed by
    the key the seller's commitment names, a ``standard_history/3`` card."""
    src = stage_dir(home) / "cards" / f"{seller}.json"
    if not src.is_file():
        raise pt.Refused(f"{label(seller)} has published no History card: its agent is not running")
    local = Path(reader.tmp(f"{seller}-card.json"))
    local.write_bytes(src.read_bytes())
    out = reader.verify(local)
    card, as_of, signer = read_card(local)
    if out.get("verdict") != "VALID":
        raise pt.Refused(f"{label(seller)}'s card does not verify: {out.get('verdict')}")
    if signer != key_id:
        raise pt.Refused(f"{label(seller)}'s card is signed by {signer[:8]}…, not the key its commitment names")
    if card.get("derivation") != "standard_history/3":
        raise pt.Refused(f"{label(seller)}'s card is {card.get('derivation')}, not standard_history/3")
    return CardRead(card, as_of["anchor"], as_of["anchor_time"], signer, out["verdict"],
                    out.get("witnesses", {}).get("status", ""), local)


def decided(card: dict) -> dict:
    """The received disputes as the pack reads them (profile §3.3): open, all, and those decided with how many were
    decided against the holder (``for + against + split + no_finding``)."""
    r = card.get("disputes", {}).get("received", {})
    o = r.get("by_outcome", {})
    return {"open": o.get("open", 0), "of": r.get("of", 0),
            "decided": {"against": o.get("against", 0),
                        "of": sum(o.get(k, 0) for k in ("for", "against", "split", "no_finding"))}}


# -- the seller's agent --------------------------------------------------------------------------------

class SellerAgent:
    """A seller's agent: it advertises, publishes its card, and answers the buyer's deal files, a dispute and a ruling,
    on its own, with no person at the keyboard (its profile pins ``builtin:neutral`` materiality, so its delivery check
    does not pause). It keeps a log its own window shows (``ard_seller_activity``)."""

    def __init__(self, home: Path, name: str, start: bool = True):
        self.home, self.name, self.label = Path(home).expanduser(), name, SELLERS[name]["label"]
        self.party = pt.Party(self.home, name)
        if not self.party.exists:
            raise pt.Refused("no sample history yet: run `python demo.py seed` first")
        self.log: list[str] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._last_rulings = 0.0
        self.threads: list[threading.Thread] = []
        self.advertise()
        self.republish()
        if start:
            t = threading.Thread(target=self._loop, name=f"seller-{name}", daemon=True)
            t.start()
            self.threads.append(t)

    def say(self, line: str) -> None:
        with self._lock:
            self.log.append(f"{datetime.now().strftime('%H:%M:%S')}  {line}")

    def stop(self) -> None:
        self._stop.set()
        for t in self.threads:
            t.join(timeout=5)
        self.party.close()

    def advertise(self) -> dict:
        """The seller's signed ``evidence-commitment/1``, with the profile's ``history_card/2`` stapled (ops u539)."""
        p = self.party
        if not p.notes(JOINED):
            p.note(JOINED, {"operator": p.profile, "key_id": p.key_id})
        settings = cm.Settings(endpoint="ard:stage", derivations=("history_card/2",), human_gated=False,
                               answers_within="PT1H")
        doc, _ = cm.build(p.node, settings=settings)
        wire.write_atomic(stage_dir(self.home) / "commitments" / f"{self.name}.json", ard.commitment_octets(doc))
        self.say(f"advertised: commitment signed by {doc['key_id'][:8]}…, price {SELLERS[self.name]['price_msat']:,} msat")
        return doc

    def republish(self) -> None:
        """Take a checkpoint if one is due and publish the card as of the newest one."""
        try:
            self.party.tick()
            publish_card(self.home, self.party)
        except pt.Refused as exc:
            self.say(f"card not published yet: {exc}")

    def _loop(self) -> None:
        last_card = 0.0
        while not self._stop.is_set():
            for step in (self._offers, self._agreements, self._payments, self._statements, self._disputes, self._rulings,
                         self._named):
                try:
                    step()
                except Exception as exc:  # one failed step is shown in the seller's log and retried next round
                    self.say(f"refused or failed: {exc}")
            if time.monotonic() - last_card > 20:
                self.republish()
                last_card = time.monotonic()
            self._stop.wait(0.5)

    def buyer_of(self, deal_id: str) -> str:
        """The buyer's folder on the wire for this deal, as its offer's sidecar names it."""
        f = wire.path(self.home, self.name, deal_id, "from")
        return json.loads(f.read_text())["buyer"] if f.is_file() else BUYER

    def _done(self, deal_id: str, kind: str) -> bool:
        return (self.party.dir / "handled" / f"{deal_id}.{kind}").exists()

    def _mark(self, deal_id: str, kind: str, value: str = "") -> None:
        d = self.party.dir / "handled"
        d.mkdir(exist_ok=True)
        (d / f"{deal_id}.{kind}").write_text(value)

    def _step(self, deal_id: str, kind: str, make: Callable[[], str]) -> str:
        """One step of a deal, once: the file it wrote, made now or by an earlier round. A step is marked only after it
        succeeded, so a failure is retried next round, and a step that succeeded is never sealed twice."""
        f = self.party.dir / "handled" / f"{deal_id}.{kind}"
        if f.exists():
            return f.read_text()
        out = str(make())
        self._mark(deal_id, kind, out)
        return out

    def _offers(self) -> None:
        p, listed = self.party, SELLERS[self.name]["price_msat"]
        for deal_id, f in wire.pending(self.home, self.name, "offer"):
            if self._done(deal_id, "offer"):
                continue
            offer = json.loads(f.read_text())
            body = offer["agent_input"]["body"]
            price = body["terms_rows"]["rows"][0]["owed"]["amount_minor"]
            if price != listed:
                self.say(f"an offer at {price:,} msat, not the listed {listed:,} msat: not taken")
                self._mark(deal_id, "offer")
                continue
            p.receive(f)  # "already kept" on a retry
            self._step(deal_id, "admit", lambda: p.admit(deal_id, seller_decision(price)))
            self._step(deal_id, "intent", lambda: p.intent(deal_id, f"sell {body['terms']['item']} at the listed price",
                                                           "service", ["commit"], None, "the buyer"))
            agreed = self._step(deal_id, "agreed", lambda: p.agree(digest_of(offer))["file"])
            wire.send(self.home, self.buyer_of(deal_id), deal_id, "agree", agreed)
            self._mark(deal_id, "offer")
            self.say(f"a buyer offered {price:,} msat for {body['terms']['item']}: agreed at the listed price, and this "
                     "seller's agreement sent to the buyer")

    def _agreements(self) -> None:
        for deal_id, f in wire.pending(self.home, self.name, "agree"):
            if self._done(deal_id, "agree"):
                continue
            self.party.receive(f)
            self._mark(deal_id, "agree")
            self.say("the buyer's agreement kept: the deal is agreed by both")

    def _payments(self) -> None:
        p, info = self.party, SELLERS[self.name]
        for deal_id, f in wire.pending(self.home, self.name, "paid"):
            if self._done(deal_id, "paid"):
                continue
            ref = json.loads(wire.path(self.home, self.name, deal_id, "ref").read_text())
            to = self.buyer_of(deal_id)
            if not self._done(deal_id, "paid-kept"):
                p.receive(f)
                self._mark(deal_id, "paid-kept")
                self.say(f"payment of {ref['amount_msat']:,} msat recorded by the buyer"
                         + (" (simulated rail: no money moved)" if ref.get("simulated") else ""))
            leg = self._step(deal_id, "received", lambda: p.received_leg(deal_id, ref["amount_msat"], ref["payment_ref"]))
            wire.send(self.home, to, deal_id, "received", leg)

            def deliver() -> str:
                check = p.check(deal_id, "commit", ITEM, ref["amount_msat"], "the buyer")
                if not check.get("proceed"):
                    raise pt.Refused(f"delivery held by this seller's own check: {check.get('verdict')}")
                return p.perform(deal_id, check["check_id"], info["observed"])
            if self._done(deal_id, "held"):
                continue  # this seller's own check held the delivery: it is not retried every round
            try:
                act = self._step(deal_id, "act", deliver)
            except pt.Refused as exc:
                if "held by this seller's own check" not in str(exc):
                    raise
                self._mark(deal_id, "held")
                self.say(str(exc))
                continue
            wire.send(self.home, to, deal_id, "act", act)
            if self.name != "kestrel":  # Kestrel says nothing on the row (plan Q3): the ruling rests on its own record
                st = self._step(deal_id, "statement-sent", lambda: p.statement(deal_id, {pt.PAID: "met", pt.DELIVERED: "met"}))
                wire.send(self.home, to, deal_id, "statement", st)
            self._mark(deal_id, "paid")
            self.say(f"delivered to the buyer: {info['shipped']} (this seller's delivery record says so)")

    def _statements(self) -> None:
        for deal_id, f in wire.pending(self.home, self.name, "statement"):
            if not self._done(deal_id, "statement"):
                self.party.receive(f)
                self._mark(deal_id, "statement")
                self.say(f"the buyer's statement on deal {deal_id[5:13]} kept")

    def _disputes(self) -> None:
        p = self.party
        for deal_id, f in wire.pending(self.home, self.name, "dispute"):
            if self._done(deal_id, "dispute"):
                continue
            if not self._done(deal_id, "dispute-kept"):
                p.receive(f)
                self._mark(deal_id, "dispute-kept")
                self.say(f"the buyer disputed the delivery of deal {deal_id[5:13]}: sending this seller's records to the "
                         "adjudicator")
            copy = Path(self._step(deal_id, "adj-copy",  # one copy: a retry sends the same one, never a second
                                   lambda: p.bundle(deal_id, "adjudicator", "the deal's adjudicator", wait=120)))
            case = adj.open_case(f, copy)  # the front keeps each object once: a retry stores nothing twice
            p.note(CASE, {"deal_id": deal_id, "case": case["case"], "copy": case["copies"][0]}, subject_ref=deal_id)
            self._mark(deal_id, "dispute")
            self.say("this seller's records were sent to the adjudicator")

    def _rulings(self) -> None:
        if time.monotonic() - self._last_rulings >= 5:  # the adjudicator is read every few seconds, not every round
            self._last_rulings = time.monotonic()
            enter_rulings(self.home, self.party, self.buyer_of, self.say)

    def _named(self) -> None:
        for deal_id, f in wire.pending(self.home, self.name, "named"):
            if not self._done(deal_id, "named"):
                self.party.receive(f)
                self._mark(deal_id, "named")


def digest_of(offer: dict) -> str:
    return gn.Node._digest(offer)


def seller_decision(price_msat: int) -> dict:
    """The seller's own admission decision on the buyer: capsule-engine on the Goose reference's admission pack (a test
    pack, evidencebook ``python/examples/goose/admission-pack.json``), as the Goose reference's seller does."""
    inputs = {"now": now_iso(), "amount": str(price_msat), "currency": "msat", "platform": {"release_attestation": "valid"},
              "card": {}, "own": {"exchanges": 0, "settled": 0, "held_halves": 0, "conflicting": 0, "verdicts": []},
              "operator": {"deny_listed": False}, "vouches": [], "subject": "", "judged": {}, "asks": {}, "asks_made": 0}
    return pt.decide(gn.PACK, inputs, pt.empty_refs())


# -- a party and a ruling --------------------------------------------------------------------------------

def enter_rulings(home: Path, p: pt.Party, other: str | Callable[[str], str], say: Callable[[str], None]) -> list[str]:
    """For each case the party sent its copy to: fetch any ruling not yet entered, enter it in the party's own book
    (``deal receive --out``), hand the naming statement to the other side, and after the party's next checkpoint send
    its book to the adjudicator for the entry check. Returns the rulings entered now."""
    entered = {n["statement"]["ruling"]: n["statement"].get("stamped_at", "") for n in p.notes(RULING_ENTERED)}
    stamped = {n["statement"]["ruling"] for n in p.notes(RULING_STAMPED)}
    sent = {n["statement"]["ruling"] for n in p.notes(BOOK_SENT)}
    done = []
    finished = {n["statement"]["deal_id"] for n in p.notes(BOOK_SENT)
                if n["statement"]["ruling"] in stamped or entered.get(n["statement"]["ruling"]) or not pt.witnessed()}
    for n in p.notes(CASE):
        case, deal_id = n["statement"]["case"], n["statement"]["deal_id"]
        if deal_id in finished:
            continue
        for r in adj.list_rulings(p, case).get("rulings", []):
            # a listed ruling is its record; its digest is the record's payload commitment (what `deal ruling` prints)
            digest = (r.get("record", {}).get("header", {}).get("payload_commitments") or [""])[0]
            if not digest:
                continue
            if digest not in entered:
                file = adj.fetch_ruling(p, case, digest)
                named = p.tmp("named.json")
                got = p.receive(file, out=named)
                wire.send(home, other(deal_id) if callable(other) else other, deal_id, "named", named)
                when = _stamped(got)
                p.note(RULING_ENTERED, {"deal_id": deal_id, "case": case, "ruling": digest, "stamped_at": when},
                       subject_ref=deal_id)
                entered[digest] = when
                done.append(digest)
                say(f"the adjudicator's ruling on deal {deal_id[5:13]} entered in this party's records"
                    + (f" (time-stamped by {pt.WITNESS_NAME} at {when})" if when else ""))
            if not entered.get(digest) and digest not in stamped and pt.witnessed():
                # entered before the adjudicator's stamp reached the witness: fetch it again for its receipt
                when = _stamped(p.receive(adj.fetch_ruling(p, case, digest)))
                if when:
                    p.note(RULING_STAMPED, {"deal_id": deal_id, "ruling": digest, "stamped_at": when}, subject_ref=deal_id)
                    stamped.add(digest)
                    say(f"the ruling on deal {deal_id[5:13]} was time-stamped by {pt.WITNESS_NAME} at {when}")
            if digest not in sent:
                copy = p.bundle(deal_id, "adjudicator", "the deal's adjudicator", wait=120)
                adj.send_book(case, copy, p.proof(deal_id, copy))
                p.note(BOOK_SENT, {"deal_id": deal_id, "case": case, "ruling": digest}, subject_ref=deal_id)
                sent.add(digest)
                say("this party's book, with the ruling entered, sent to the adjudicator")
    return done


def _stamped(received: dict) -> str:
    """The ruling's witnessed time as ``deal receive`` reports it, or "" while no receipt is held."""
    when = received.get("stamped_at", "")
    return "" if not when or when.startswith("unknown") else when


@dataclass
class Case:
    """A case as the adjudicator's window shows it."""
    case: str
    deal_id: str
    row: str
    books: list[dict] = field(default_factory=list)   # [{"side", "received_at", "digest"}]
    deciding: list[str] = field(default_factory=list)  # lines read from the books
    dispute: str = ""
    copies: list[str] = field(default_factory=list)


def _payloads(copy_body: dict) -> list[dict]:
    """The records a copy discloses, decoded (``evidencebook/payloads``)."""
    out = []
    for v in copy_body.get("extensions", {}).get("evidencebook/payloads", {}).values():
        raw = v if isinstance(v, str) else json.dumps(v)
        try:
            raw = base64.b64decode(raw + "==").decode()
        except Exception:
            pass
        try:
            out.append(json.loads(raw))
        except ValueError:
            continue
    return out


def case_view(case: dict, names: dict[str, str]) -> Case:
    """What the case's books show: which side's book arrived and when, the seller's delivery record and each side's
    statement on the row, as each side's own copy discloses them. ``names`` maps a party's key to its name."""
    c = Case(case["case"], case["deal_id"], case["row"])
    c.dispute = case["disputes"][0]["digest"] if case["disputes"] else ""
    for cp in case["copies"]:
        body = cp["body"] or {}
        side = body.get("extensions", {}).get("x-deal-v1", {}).get("book", {}).get("agreement", {}).get("payload", {}) \
            .get("body", {}).get("role", "?")
        c.books.append({"side": side, "received_at": cp["received_at"], "digest": cp["digest"]})
        c.copies.append(cp["digest"])
        who = names.get(case["buyer"] if side == "buyer" else case["seller"], "the " + side)
        for rec in _payloads(body):
            b = rec.get("body", {})
            if "observed" in b and b.get("act"):
                c.deciding.append(f"{who}'s own signed delivery record: {b['observed']}")
            for st in b.get("statements", []) if isinstance(b.get("statements"), list) else []:
                if st.get("row") == case["row"]:
                    c.deciding.append(f"{who}'s statement on the row: {st.get('value')}")
    return c
