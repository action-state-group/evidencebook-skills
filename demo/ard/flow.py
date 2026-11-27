# SPDX-License-Identifier: Apache-2.0
"""The deal flow both front ends run (the script, ``demo.py run``, and the Goose windows, ``desktop_server.py``): a
seller's agent, which answers on its own, and the buyer's and the adjudicator's steps, which a person drives.

Every party is its own capsulectl-deal profile (:mod:`party`); they meet through the stage (:mod:`stage`): each
seller's commitment and its shared History card under ``<home>/stage``, and the files the parties hand each other
(:mod:`wire`). A dispute goes to the adjudicator the agreement names, a capsulectl-deal profile (:mod:`adjudicator`). Nothing here seals a deal
record or computes a row's status: each step is a capsulectl verb, and what the screen says is read back from it."""
from __future__ import annotations

import json
import os
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
from cast import BUYER, HELD_FROM, SELLERS, label

_paths_setup = pt._paths  # party already put the Goose reference on the path
import commitment as cm  # noqa: E402
import goose_node as gn  # noqa: E402

#: Node-book record types of the demo (its own names; capsulectl refuses a library name).
JOINED = gn.JOINED
CASE = "ard_case"            # a party's dispute went to the adjudicator
RULING_ENTERED = "ard_ruling_entered"
RULING_STAMPED = "ard_ruling_stamped"  # the ruling's witnessed time, once a later file carried its receipt
BOOK_SENT = "ard_book_sent"
PROOF_SENT = "ard_proof_witnessed"  # the stamp proof of the book sent, with the witness's receipt, went to the adjudicator
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


#: How long an on-demand publish waits for the witness to take its stamp, so the card carries its receipt (#350).
CARD_STAMP_WAIT_S = 12


def stamped(bundle: Path) -> bool:
    """Whether a card bundle carries its witness's receipt for its anchor (evidencebook#957)."""
    return pt.CARD_ANCHOR_WITNESS in json.loads(Path(bundle).read_text()).get("extensions", {})


def same_counts(a: dict, b: dict) -> bool:
    """Whether two cards count the same: everything but the ``anchor`` each checkpoint changes."""
    return {k: v for k, v in a.items() if k != "anchor"} == {k: v for k, v in b.items() if k != "anchor"}


def publish_card(home: Path, p: pt.Party, keep_stamped: bool = False) -> Path:
    """Write the party's shared card (as of its newest checkpoint) where buyers fetch it. With ``keep_stamped``, a card
    whose newest checkpoint the witness has not taken yet does not replace a published one that carries its receipt and
    counts the same (#350): the witness takes checkpoints as it answers, and the next round publishes it once it has. A
    card whose counts changed (a deal, a dispute, a ruling) is published at once, with or without its receipt."""
    src = p.card_bundle(shared=True)
    dest = stage_dir(home) / "cards" / f"{p.name}.json"
    if keep_stamped and pt.witnessed() and dest.is_file() and stamped(dest) and not stamped(src) \
            and same_counts(read_card(dest)[0], read_card(src)[0]):
        return dest
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
    out = reader.verify(local, report_on_fail=True)
    stamp = pt.anchor_witness(out)
    if out.get("verdict") != "VALID":  # before the card is read: a failed card may not carry one
        if stamp == "fail":  # a receipt that does not check makes the verdict INVALID (evidencebook#957)
            raise pt.Refused(f"{label(seller)}'s card does not verify: {pt.STAMP_FAILED}")
        raise pt.Refused(pt.not_verified(f"{label(seller)}'s card", out.get("verdict")))
    card, as_of, signer = read_card(local)
    if signer != key_id:
        raise pt.Refused(f"{label(seller)}'s card is not signed by the key its commitment names")
    if card.get("derivation") != pt.CARD_DERIVATION:
        raise pt.Refused(f"{label(seller)}'s card is not the kind of History card this buyer reads")
    return CardRead(card, as_of["anchor"], as_of["anchor_time"], signer, out["verdict"], stamp, local)


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
            # the trying-again lines said since the last other line (set here, so an agent made without __init__ has it)
            if not screens.once_per_failure(self.__dict__.setdefault("_failing", set()), line):
                return
            self.log.append(f"{datetime.now().astimezone().strftime('%H:%M:%S %Z')}  {line}")

    def event(self, line: str) -> None:
        """One of the events a seller is told of (evidencebook-skills#336, Sherlock2): deal agreed, paid, dispute
        received, ruling. One line in its activity (a Goose window shows nothing until its agent is asked)."""
        self.say(line)

    def _terms(self, deal_id: str) -> str:
        """What the deal is for and its price, from the buyer's offer this seller kept."""
        try:
            body = json.loads(wire.path(self.home, self.name, deal_id, "offer").read_text())["agent_input"]["body"]
            return f"{body['terms_rows']['rows'][0]['owed']['amount_minor']:,} msat for {body['terms']['item']}"
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            return "the buyer's order"

    def failed(self, what: str, exc: BaseException) -> None:
        """One plain line for a step that failed this round (evidencebook-skills#327), said once while it keeps failing
        the same way (:meth:`say`); the error itself goes to the seller's own log every time."""
        self.party.log(f"{what}: {exc!r}")
        self.say(screens.trying_again(what, exc))

    def stop(self, take_rulings: bool = False) -> None:
        """Stop the agent's loop; with ``take_rulings``, then take any ruling file waiting for it (a ruling sent again
        with its stamp as a run closes), never at the same time as the loop; then close its profile."""
        self._stop.set()
        for t in self.threads:
            t.join(timeout=5)
        if take_rulings:
            try:
                self._rulings()
            except Exception as exc:  # shown in its log, as a failed loop step is
                self.failed("entering the adjudicator's ruling", exc)
        self.party.close()

    def advertise(self) -> dict:
        """The seller's signed ``evidence-commitment/1``, with the profile's ``history_card/2`` stapled (ops u539), on the
        terms its own file discloses (``sellers/<name>.yaml``). Its signed ``disclosure-policy/0`` goes where the
        commitment's ``lcap.policy_uri`` points, relative to the commitment's own URL, so the seller's origin serves it."""
        p = self.party
        if not p.notes(JOINED):
            p.note(JOINED, {"operator": p.profile, "key_id": p.key_id})
        d = SELLERS[self.name]["discloses"]
        settings = cm.Settings(endpoint="ard:stage", subjects=tuple(d["subjects"]), derivations=tuple(d["derivations"]),
                               human_gated=d["human_gated"], answers_within=d["answers_within"])
        doc, policy = cm.build(p.node, settings=settings)
        out = stage_dir(self.home) / "commitments"
        wire.write_atomic(out / doc["lcap"]["policy_uri"], policy)  # first, so a served commitment's policy resolves
        wire.write_atomic(out / f"{self.name}.json", ard.commitment_octets(doc))
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
        """Take a checkpoint (``now``: at once, waiting up to :data:`CARD_STAMP_WAIT_S` for the witness to take it;
        otherwise if one is due) and publish the card as of the newest one. A due checkpoint the witness has not taken
        yet leaves the published card in place until it has (:func:`publish_card`), so a buyer reads a card whose
        time-stamp she can check; an on-demand one is published either way, since it is asked for its new counts."""
        try:
            if now:
                try:
                    self.party.wait_checkpoint(CARD_STAMP_WAIT_S)
                except pt.WitnessSlow:
                    pass  # published without its receipt; a later round publishes it once the witness takes it
            else:
                self.party.tick()
            publish_card(self.home, self.party, keep_stamped=not now)
        except pt.Refused as exc:
            self.failed("publishing this seller's History card", exc)

    def _loop(self) -> None:
        last_card = 0.0
        while not self._stop.is_set():
            for what, step in (("taking the buyer's offer", self._offers), ("keeping the buyer's agreement", self._agreements),
                               ("taking the payment and delivering", self._payments),
                               ("keeping the buyer's statement", self._statements), ("keeping the dispute", self._disputes),
                               ("answering the adjudicator's request for this seller's books", self._requests),
                               ("entering the adjudicator's ruling", self._rulings), ("keeping the buyer's copy of the ruling", self._named)):
                try:
                    step()
                except Exception as exc:  # one plain line in the seller's log, retried next round
                    self.failed(what, exc)
            if time.monotonic() - last_card > 20:
                try:
                    self.republish()
                except Exception as exc:  # never ends the seller's loop
                    self.failed("publishing this seller's History card", exc)
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
            # its own log only: the event a seller is told is the deal agreed by both (_agreements, #336)
            self.party.log(f"a buyer offered {price:,} msat for {body['terms']['item']} (deal {deal_id}): agreed at the "
                           "listed price, and this seller's agreement sent to the buyer")

    def _agreements(self) -> None:
        for deal_id, f in wire.pending(self.home, self.name, "agree"):
            if self._done(deal_id, "agree"):
                continue
            self.party.receive(f)
            self._mark(deal_id, "agree")
            self.event(f"deal agreed: {self._terms(deal_id)}, signed by both (deal {deal_id[5:13]})")

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
                # what this seller knows: the buyer's word; its own wallet is not read by this process (#337, Sherlock2:
                # "if the rail can't show that, it says the buyer says paid")
                self.event(f"paid: the buyer says it paid {ref['amount_msat']:,} msat"
                         + (" (simulated rail: no money moved)" if ref.get("simulated")
                            else "; this seller's own wallet is not checked here"))
            leg = self._step(deal_id, "received", lambda: p.received_leg(deal_id, ref["amount_msat"], ref["payment_ref"]))
            wire.send(self.home, to, deal_id, "received", leg)

            def deliver() -> str:
                check = p.check(deal_id, "commit", SELLERS[self.name]["item"], ref["amount_msat"], "the buyer")
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
                self.event(f"dispute received: the buyer disputed the delivery of deal {deal_id[5:13]}; the "
                           "adjudicator asks for this seller's books, which this seller answers in full")

    def _requests(self) -> None:
        def say(line: str) -> None:  # the books going to the adjudicator is an event (#336)
            (self.event if line.startswith("the adjudicator asked for this party's books") else self.say)(line)
        adj.answer_requests(self.home, self.party, self.name, "seller", say)

    def _rulings(self) -> None:
        def say(line: str) -> None:  # the ruling entered is the event; its book and stamp lines are activity only
            (self.event if line.startswith("the adjudicator's ruling on deal") else self.say)(line)
        enter_rulings(self.home, self.party, "seller", self.buyer_of, say)

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
    for its receipt. A book sent before the witness took its stamp has its proof sent again, with the witness's receipt,
    once the witness has taken it (evidencebook-skills#328), so the adjudicator sees the entry time-stamped. Returns the
    deals whose ruling was entered now."""
    entered = {n["statement"]["deal_id"]: n["statement"].get("stamped_at", "") for n in p.notes(RULING_ENTERED)}
    stamped = {n["statement"]["deal_id"] for n in p.notes(RULING_STAMPED)}
    sent = {n["statement"]["deal_id"]: n["statement"].get("copy", "") for n in p.notes(BOOK_SENT)}
    proved = {n["statement"]["deal_id"] for n in p.notes(PROOF_SENT)}
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
            arrived = file.stat().st_mtime
            if not mark.exists() or arrived > mark.stat().st_mtime:
                when = _stamped(p.receive(file))
                if when:
                    p.note(RULING_STAMPED, {"deal_id": deal_id, "stamped_at": when}, subject_ref=deal_id)
                    stamped.add(deal_id)
                    say(f"the ruling on deal {deal_id[5:13]} was time-stamped by {pt.WITNESS_NAME} at "
                        f"{screens.local_time(when, date=True)}")
                # marked only once taken and noted, at the version taken: a failure is tried again next round, and a
                # file that arrives again meanwhile is still newer than the mark
                mark.parent.mkdir(exist_ok=True)
                mark.touch()
                os.utime(mark, (arrived, arrived))
        if deal_id not in sent:
            what = "sending this party's book, with the ruling entered, to the adjudicator"
            try:
                copy = adj.send_book(home, p, deal_id, side, say)
                p.note(BOOK_SENT, {"deal_id": deal_id, "copy": str(copy)}, subject_ref=deal_id)
            except Exception as exc:  # the ruling stays entered; the book goes on a later round
                p.log(f"{what}: {exc!r}")
                say(screens.trying_again(what, exc))
                continue
            sent[deal_id] = str(copy)
        elif deal_id not in proved and pt.witnessed():
            what = "sending the adjudicator this party's book's time-stamp"
            # the copy sent; a note from before evidencebook-skills#328 names none: the copy the adjudicator holds
            copy = Path(sent[deal_id] or wire.path(home, adj.ADJUDICATOR, deal_id, f"book-{side}"))
            try:
                got = adj.send_proof_once_witnessed(home, p, deal_id, copy, side, say)
                if got and got != adj.GAVE_UP:
                    p.note(PROOF_SENT, {"deal_id": deal_id, "copy": str(got)}, subject_ref=deal_id)
                    proved.add(deal_id)
            except Exception as exc:  # tried again on a later round
                p.log(f"{what}: {exc!r}")
                say(screens.trying_again(what, exc))
                continue
    return done


def rulings_entered(p: pt.Party) -> dict[str, str]:
    """Each deal whose ruling this party entered, with the time Action State's witness stamped the ruling as this party
    noted it: at entry, or once the ruling came back with its stamp (:func:`enter_rulings`); "" while it has none."""
    out = {n["statement"]["deal_id"]: n["statement"].get("stamped_at", "") for n in p.notes(RULING_ENTERED)}
    for n in p.notes(RULING_STAMPED):
        out[n["statement"]["deal_id"]] = out.get(n["statement"]["deal_id"]) or n["statement"].get("stamped_at", "")
    return out


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


def entry_lines(deal_id: str, rows: list[dict], names: dict[str, str]) -> list[str]:
    """Whether each party entered the adjudicator's ruling, from ``deal ruling entries`` (``rows``), saying which record
    a missing stamp is on (evidencebook-skills#328): first the ruling's own stamp (its witnessed time, which capsulectl
    reads from the adjudicator's own case book and reports with each party's row), then each party's entry, keeping
    every state capsulectl tells apart (evidencebook ``xdealv1`` entry states, ``deal_v1_entries.go``)."""
    short = deal_id[5:13]
    if not rows:
        return [f"deal {short}: no party has sent its book back yet; the ruling's time-stamp and each entry show once "
                "one has"]
    at = next((r["ruling_witnessed_at"] for r in rows if r.get("ruling_witnessed_at")), "")
    out = [f"deal {short}: the ruling was time-stamped by {pt.WITNESS_NAME} at {screens.local_time(at, date=True)}"
           if at else f"deal {short}: the ruling is not time-stamped yet ({pt.WITNESS_NAME} has not taken its stamp)"]
    seen = set()
    for r in rows:
        who = names.get(r.get("party", ""), r.get("party", "a party"))
        seen.add(r.get("party"))
        state = r.get("state", "")
        if state == "entered":
            out.append(f"  {who}: entered it; the entry is time-stamped by {pt.WITNESS_NAME}")
        elif state == "entered_unwitnessed":
            out.append(f"  {who}: entered it; the entry is not time-stamped yet (its book's stamp has not reached "
                       f"{pt.WITNESS_NAME}; it sends the stamp once it has)")
        elif state == "not_entered":
            out.append(f"  {who}: had not entered it as of its book's checkpoint at "
                       f"{screens.local_time(r.get('checkpoint_at', ''), date=True)}")
        elif state == "not_shown":
            out.append(f"  {who}: its book does not show it entered yet "
                       + ("(the ruling has no time-stamp yet to compare with)" if not at else
                          "(its book was last sealed before the ruling's time-stamp)"))
        else:  # a state this demo does not know: capsulectl's own words
            out.append(f"  {who}: {r.get('words', state)}")
    for side in ("buyer", "seller"):
        if side not in seen and side in names:
            out.append(f"  {names[side]}: has not sent their book back yet")
    return out
