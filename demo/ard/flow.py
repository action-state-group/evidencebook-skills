# SPDX-License-Identifier: Apache-2.0
"""The deal flow both front ends run (the script, ``demo.py run``, and the Goose windows, ``desktop_server.py``): a
seller's agent, which answers on its own, and the buyer's and the adjudicator's steps, which a person drives.

Every party is its own capsulectl-deal profile (:mod:`party`); they meet through the stage (:mod:`stage`): each
seller's commitment and its shared History card under ``<home>/stage``, and the files the parties hand each other
(:mod:`wire`). A dispute goes to the adjudicator the agreement names, a capsulectl-deal profile (:mod:`adjudicator`). Nothing here seals a deal
record or computes a row's status: each step is a capsulectl verb, and what the screen says is read back from it."""
from __future__ import annotations

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
import screens
import wire
from cast import BUYER, HELD_FROM, ITEM, SELLERS, label

_paths_setup = pt._paths  # party already put the Goose reference on the path
import commitment as cm  # noqa: E402
import goose_node as gn  # noqa: E402

#: Node-book record types of the demo (its own names; capsulectl refuses a library name).
JOINED = gn.JOINED
CASE = "ard_case"            # a party's dispute went to the adjudicator
RULING_ENTERED = "ard_ruling_entered"
RULING_STAMPED = "ard_ruling_stamped"  # the ruling's witnessed time, once a later file carried its receipt
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
    if card.get("derivation") != pt.CARD_DERIVATION:
        raise pt.Refused(f"{label(seller)}'s card is {card.get('derivation')}, not {pt.CARD_DERIVATION}")
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
        self.threads: list[threading.Thread] = []
        self.advertise()
        self.wait_sample_held()
        self.republish(now=True)
        if start:
            t = threading.Thread(target=self._loop, name=f"seller-{name}", daemon=True)
            t.start()
            self.threads.append(t)

    def say(self, line: str) -> None:
        with self._lock:
            self.log.append(f"{datetime.now().astimezone().strftime('%H:%M:%S %Z')}  {line}")

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

    def wait_sample_held(self) -> None:
        """On a home seeded under a minute ago, wait for the minute from which a stamp counts the sample deals held
        (``seed.py``), so the card this agent publishes counts them."""
        f = self.home / HELD_FROM
        left = int(f.read_text()) - time.time() if f.is_file() else 0
        if left > 0:
            self.say(f"waiting {left:.0f} s for the sample deals' contest windows to end, so the card counts them held")
            print(f"{self.label}: the sample deals' contest windows end in {left:.0f} s; its card counts them then")
            time.sleep(left + 0.5)

    def republish(self, now: bool = False) -> None:
        """Take a checkpoint (``now``: at once; otherwise if one is due) and publish the card as of the newest one."""
        try:
            self.party.stamp() if now else self.party.tick()
            publish_card(self.home, self.party)
        except pt.Refused as exc:
            self.say(f"card not published yet: {exc}")

    def _loop(self) -> None:
        last_card = 0.0
        while not self._stop.is_set():
            for step in (self._offers, self._agreements, self._payments, self._statements, self._disputes, self._requests,
                         self._rulings, self._named):
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
        for deal_id, f in wire.pending(self.home, self.name, "dispute"):
            if not self._done(deal_id, "dispute"):
                self.party.receive(f)
                self._mark(deal_id, "dispute")
                self.say(f"the buyer disputed the delivery of deal {deal_id[5:13]}: the adjudicator will ask for this "
                         "seller's books")

    def _requests(self) -> None:
        adj.answer_requests(self.home, self.party, self.name, "seller", self.say)

    def take_rulings(self) -> None:
        """Take any ruling file waiting for this seller now (as its loop does each round): for a run that closes."""
        self._rulings()

    def _rulings(self) -> None:
        enter_rulings(self.home, self.party, "seller", self.buyer_of, self.say)

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

def enter_rulings(home: Path, p: pt.Party, side: str, other: str | Callable[[str], str],
                  say: Callable[[str], None]) -> list[str]:
    """For each ruling the adjudicator sent this party: enter it in the party's own book (``deal receive --out``), hand the
    naming statement to the other side, and send the adjudicator this party's book with the entry and its stamp proof,
    for its entry check. A ruling file that arrives again after the adjudicator's stamp reached the witness is taken again
    for its receipt. Returns the deals whose ruling was entered now."""
    entered = {n["statement"]["deal_id"]: n["statement"].get("stamped_at", "") for n in p.notes(RULING_ENTERED)}
    stamped = {n["statement"]["deal_id"] for n in p.notes(RULING_STAMPED)}
    sent = {n["statement"]["deal_id"] for n in p.notes(BOOK_SENT)}
    done = []
    for deal_id, file in wire.pending(home, p.name, "ruling"):
        if deal_id not in entered:
            named = p.tmp("named.json")
            when = _stamped(p.receive(file, out=named))
            wire.send(home, other(deal_id) if callable(other) else other, deal_id, "named", named)
            p.note(RULING_ENTERED, {"deal_id": deal_id, "stamped_at": when}, subject_ref=deal_id)
            entered[deal_id] = when
            done.append(deal_id)
            say(f"the adjudicator's ruling on deal {deal_id[5:13]} entered in this party's records"
                + (f" (time-stamped by {pt.WITNESS_NAME} at {screens.local_time(when, date=True)})" if when else ""))
        elif not entered[deal_id] and deal_id not in stamped and pt.witnessed():
            mark = p.dir / "handled" / f"{deal_id}.ruling-seen"
            if not mark.exists() or file.stat().st_mtime > mark.stat().st_mtime:
                mark.parent.mkdir(exist_ok=True)
                mark.touch()
                when = _stamped(p.receive(file))
                if when:
                    p.note(RULING_STAMPED, {"deal_id": deal_id, "stamped_at": when}, subject_ref=deal_id)
                    stamped.add(deal_id)
                    say(f"the ruling on deal {deal_id[5:13]} was time-stamped by {pt.WITNESS_NAME} at "
                        f"{screens.local_time(when, date=True)}")
        if deal_id not in sent:
            adj.send_book(home, p, deal_id, side, say)
            p.note(BOOK_SENT, {"deal_id": deal_id}, subject_ref=deal_id)
            sent.add(deal_id)
    return done


def _stamped(received: dict) -> str:
    """The ruling's witnessed time as ``deal receive`` reports it, or "" while no receipt is held."""
    when = received.get("stamped_at", "")
    return "" if not when or when.startswith("unknown") else when


@dataclass
class Case:
    """A case as the adjudicator's window shows it."""
    deal_id: str
    row: str
    answered: dict[str, str] = field(default_factory=dict)  # side -> when its answer arrived
    deciding: list[str] = field(default_factory=list)       # lines read from the books
    asked_at: str = ""
    ruling: dict | None = None
    signed: set[str] = field(default_factory=set)            # sides with at least one of their records read


def _records(book: dict) -> list[tuple[str, dict]]:
    """An answer's records with whose book each comes from: ``own`` (the answering side's) or ``held`` (its copy of the
    other side's)."""
    def each(records) -> list[dict]:  # keyed by record id
        return list((records or {}).values())
    return [("own", r) for r in each(book.get("records"))] + \
        [("held", r) for r in each((book.get("received") or {}).get("records"))]


def case_view(case: dict, names: dict[str, str]) -> Case:
    """What the case's books show: which side answered and when, the seller's delivery record and each side's statement
    on the row, from each answer's own book and the copy it holds of the other side's. ``names`` maps a side to its
    name."""
    dispute = json.loads(Path(case["dispute"]).read_text())
    row = dispute.get("record", {}).get("payload", {}).get("body", {}).get("row")
    if not row:  # a dispute file of another shape: never show or rule on a guessed row
        raise ValueError(f"the dispute for {case['deal_id']} names no row")
    c = Case(case["deal_id"], row, asked_at=case.get("asked_at", ""), ruling=case.get("ruling"))
    seen: set[str] = set()
    for side, a in case["answers"].items():
        c.answered[side] = a["at"]
        book = json.loads(Path(a["file"]).read_text())["bundle"].get("extensions", {}).get("x-deal-v1", {}).get("book", {})
        other = "seller" if side == "buyer" else "buyer"
        for whose, rec in _records(book):
            signer = side if whose == "own" else other
            c.signed.add(signer)
            b = (rec.get("payload") or {}).get("body", {})
            line = ""
            if "observed" in b and b.get("act"):
                line = f"{names.get(signer, signer)}'s own signed delivery record: {buyer_words(b['observed'])}"
            for st in b.get("statements", []) if isinstance(b.get("statements"), list) else []:
                if st.get("row") == row:
                    line = f"{names.get(signer, signer)}'s statement on the row: {st.get('value', '').replace('_', ' ')}"
            if line and line not in seen:
                seen.add(line)
                c.deciding.append(line)
    return c


def buyer_words(observed: str) -> str:
    import buyer
    return buyer.shipped(observed)


def case_names(case: dict) -> dict[str, str]:
    """Each side's name in a case, from the stage folders its dispute named."""
    return {side: label(case["parties"][side]) for side in ("buyer", "seller")}


def case_lines(c: Case, names: dict[str, str]) -> list[str]:
    """What the adjudicator's screen says about a case: who was asked and who answered, what their books show, and the
    ruling once recorded. It decides nothing."""
    out = [f"deal {c.deal_id[5:13]}, row {c.row}: disputed by {names['buyer']}"]
    if c.asked_at:
        out.append(f"  asked both sides for their books at {screens.local_time(c.asked_at)}")
    for side in ("buyer", "seller"):
        other = names["seller" if side == "buyer" else "buyer"]
        if side in c.answered:
            out.append(f"  {names[side]} answered at {screens.local_time(c.answered[side])}: own book and the copy held of "
                       f"{other}'s")
        elif side in c.signed:  # read from the copy the other side holds (u211 item 2)
            out.append(f"  {names[side]}: no answer yet (its own copy of its book not received; its records here come "
                       f"from the copy {other} holds)")
        else:
            out.append(f"  {names[side]}: no answer yet")
    out += [f"  {line}" for line in c.deciding]
    if c.ruling:
        who = names.get(c.ruling["against"], "no one")
        found = "not met" if c.ruling["value"] == "not_met" else "met"
        out.append(f"  ruling recorded: {found}, against {who} (ruling {c.ruling['ruling'][:8]}…)")
    return out
