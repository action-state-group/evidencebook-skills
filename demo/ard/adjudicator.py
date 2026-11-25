# SPDX-License-Identifier: Apache-2.0
"""The demo's adjudicator: a capsulectl-deal profile of its own (one key for its records and its checkpoints, the key every
agreement names), run by the operator, which rules with capsulectl's own verbs (evidencebook#861, design note
``docs/design/861-four-books.md``; capsulectl at the run sheet's pin):

1. A party sends it the dispute it raised (``deal dispute``'s file).
2. It asks each party for its books: a ``deal_adjudicator_copy/1`` evidence request over the deal's correlation. Each
   party's agent answers on its own with ``deal respond``: its whole deal book and the copy it holds of the other side's
   (u207, u211: full disclosure; four books).
3. The presenter decides, and ``deal ruling --answer A --answer B`` records it over the books read
   (``xdealv1.GatherCase``): the ruling names each side's book read and what timed each record. A side whose own book
   was not shown is ruled on only from records it signed, as the other side holds them (u211 item 2), and capsulectl
   refuses a ruling against a side none of whose records it read.
4. Its checkpoint carries the ruling's stamp to the witness every agreement names; the ruling file, written again
   after the stamp, carries the receipt, and each party enters it with ``deal receive``.
5. ``deal ruling entries`` reads whether each party entered it, from the copies they send back.

Everything travels through the stage's files (:mod:`wire`), as every other deal step does. No adjudication rule is
written here: capsulectl applies evidencebook's (``CheckCase``, ``GatherCase``, ``SealRuling``, ``EntryOf``)."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import party as pt
import wire
from cast import ADJUDICATOR

#: The conflict determination every ruling's dialog shows (ops u120: whether Action State is, or acts for, a party).
CONFLICT = "the operator runs this adjudicator and every party here, so it is not independent of the parties"
#: The challenge window: 7 days (Steven, ops u214, 2026-11-24: "was 30; agents act fast").
CHALLENGE_DAYS = 7
#: The rules the agreements name: what the adjudicator rules on. The stage serves the page; its SHA-256 is the agreement's
#: ``rules_digest``.
RULES_TEXT = f"""Adjudicator: rules

The operator runs this adjudicator and every party here, so it is not independent of the parties.

1. It rules on one row of an x-deal-v1 deal whose agreement names it, when a party disputes that row.
2. It asks each party for its books: its own deal book and the copy it holds of the other side's. It rules against a
   side only on records that side signed itself, and not against a side none of whose records it read.
3. Its ruling says whether the row was met. It is final for the row; either side may challenge it within
   {CHALLENGE_DAYS} days, and a challenge is recorded beside the ruling and never replaces it.
4. It orders no payment and moves no money.
"""
#: The derivation of the adjudicator's request for a party's books (evidencebook ``xdealv1.DerivationAdjudicatorCopy``).
DERIVATION = "deal_adjudicator_copy/1"


class AdjudicatorError(RuntimeError):
    pass


def rules_digest() -> str:
    return hashlib.sha256(RULES_TEXT.encode()).hexdigest()


def rules_url() -> str:
    return f"http://127.0.0.1:{int(os.environ.get('ARD_STAGE_PORT', '47481'))}/adjudicator/rules"


def request_for(deal_id: str) -> dict:
    """The adjudicator's request for a party's books of one deal, in the evidence request draft's wire form
    (``min_freshness`` is a bare time)."""
    return {"coverage": {"min_freshness": "2020-01-01T00:00:00Z"}, "derivation": DERIVATION,
            "nonce": os.urandom(16).hex(), "subject": {"correlation": deal_id}}


def _named_file(home: Path) -> Path:
    return Path(home).expanduser() / "stage" / "adjudicator.json"


def named_key(home: Path) -> str:
    """The adjudicator's key as the stage publishes it: the key a party checks the adjudicator's request against."""
    return json.loads(_named_file(home).read_text())["key_id"]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _mtime(p: Path) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(p.stat().st_mtime))


_PARTIES: dict[Path, pt.Party] = {}
#: How long a party keeps stamping for a timed answer before it answers without one (answer_requests).
ANSWER_WAIT_S = 45
#: How long a ruling stamp the witness did not take in the foreground keeps being taken in the background.
LATER_S = 180
#: One ask at a time in this process (Adjudicator.ask).
_ASKING = threading.Lock()
#: The background stamp threads started (Adjudicator.stamp), so a caller or a test can wait for them.
LATER: list[threading.Thread] = []


@dataclass(frozen=True)
class Adjudicator:
    """The adjudicator's profile under the demo home (``<home>/adjudicator``)."""

    home: Path

    @property
    def party(self) -> pt.Party:
        """The adjudicator's profile, opened once per home in this process."""
        home = Path(self.home).expanduser()
        if home not in _PARTIES:
            _PARTIES[home] = pt.Party(home, ADJUDICATOR)
        return _PARTIES[home]

    @property
    def key_file(self) -> Path:
        return Path(self.home).expanduser() / ADJUDICATOR / "adjudicator.key"

    def create(self) -> Adjudicator:
        """Make the key once (``capsulectl deal key generate``) and the profile on it, records and checkpoints alike: an
        agreement names the adjudicator by that one key, and its case book's stamp proof binds to it."""
        self.key_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not self.key_file.exists():
            run = subprocess.run([os.environ.get("CAPSULECTL_DEAL", "capsulectl-deal"), "key", "generate", "--output",
                                  str(self.key_file)], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
            if run.returncode != 0:
                raise AdjudicatorError(f"capsulectl key generate failed: {run.stderr.strip()}")
        self.party.create("node", key_file=str(self.key_file))
        wire.write_atomic(_named_file(self.home), json.dumps(self.named()).encode())
        return self

    @property
    def key_id(self) -> str:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        seed = bytes.fromhex(self.key_file.read_text().strip())
        return Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes_raw().hex()

    def named(self) -> dict:
        """How an agreement names this adjudicator: its key and its published rules."""
        return {"key_id": self.key_id, "rules_digest": rules_digest(), "rules_url": rules_url()}

    # -- the cases ---------------------------------------------------------------------------------

    def ask(self) -> list[str]:
        """For each dispute sent here that it has not asked about yet: ask the deal's buyer and seller for their books
        (one request each, through the stage). Returns the deals asked about now."""
        asked = []
        with _ASKING:  # the window's ask-on-arrival loop and ard_case's own ask never send a request twice
            for deal_id, _f in wire.pending(self.home, ADJUDICATOR, "dispute"):
                if wire.path(self.home, ADJUDICATOR, deal_id, "asked").is_file():
                    continue
                parties = json.loads(wire.path(self.home, ADJUDICATOR, deal_id, "parties").read_text())
                for side in ("buyer", "seller"):
                    wire.send_json(self.home, parties[side], deal_id, "adjrequest", request_for(deal_id))
                wire.send_json(self.home, ADJUDICATOR, deal_id, "asked", {"at": _now(), **parties})
                asked.append(deal_id)
        return asked

    def cases(self) -> list[dict]:
        """Each dispute sent here: its deal, the parties, when they were asked, the answers that came back, the ruling."""
        out = []
        for deal_id, f in wire.pending(self.home, ADJUDICATOR, "dispute"):
            asked_f = wire.path(self.home, ADJUDICATOR, deal_id, "asked")
            parties = json.loads(wire.path(self.home, ADJUDICATOR, deal_id, "parties").read_text())
            answers = {}
            for side in ("buyer", "seller"):
                a = wire.path(self.home, ADJUDICATOR, deal_id, f"answer-{side}")
                if a.is_file():
                    answers[side] = {"file": a, "at": _mtime(a)}
            ruling = wire.path(self.home, ADJUDICATOR, deal_id, "ruling")
            out.append({"deal_id": deal_id, "dispute": f, "parties": parties, "answers": answers,
                        "asked_at": json.loads(asked_f.read_text())["at"] if asked_f.is_file() else "",
                        "ruling": json.loads(ruling.read_text()) if ruling.is_file() else None})
        return out

    def gather(self, seconds: float = 30) -> list[dict]:
        """Ask about each new dispute, then wait up to ``seconds`` for both sides of every open case to answer. Returns the
        cases as they stand."""
        self.ask()
        stop = time.monotonic() + seconds
        while True:
            cases = self.cases()
            if time.monotonic() >= stop or all(len(c["answers"]) == 2 or c["ruling"] for c in cases):
                return cases
            time.sleep(1)

    def rule(self, case: dict, row: str, value: str, against: str) -> dict:
        """Record the presenter's ruling with ``deal ruling`` over the answers that came back, final for the row. The same
        ruling again seals nothing and writes the file again with the receipts the shelf holds by then."""
        p = self.party
        args = ["ruling", "--deal", case["deal_id"], "--row", row, "--value", value, "--against", against, "--final",
                "--dispute", str(case["dispute"])]
        for side in ("buyer", "seller"):
            if side in case["answers"]:
                args += ["--answer", str(case["answers"][side]["file"])]
        out = p.tmp("ruling.json")
        try:
            done = p.run(*args, "--out", out)
        except pt.Refused as exc:
            raise AdjudicatorError(str(exc)) from None
        record = {"ruling": done.get("ruling", ""), "sealed": done.get("sealed"), "row": row, "value": value,
                  "against": against, "file": out, "books": done.get("books", {})}
        wire.send_json(self.home, ADJUDICATOR, case["deal_id"], "ruling", record)
        return record

    def stamp(self, case: dict, seconds: float = 12, later: float = LATER_S) -> bool:
        """Take a checkpoint now (on demand) so the witness stamps the ruling, write the ruling file again with the
        receipt, and hand it to both parties. True when the stamp was delivered within ``seconds`` (never without a
        witness); the ruling goes to the parties either way. A stamp the witness did not take in time (it answers
        slowly under load, evidencebook-skills#307) keeps being taken in the background for up to ``later`` seconds,
        and the ruling goes to both parties again with its receipt when it is: each party then records its time
        (flow.enter_rulings takes a ruling file that arrives again)."""
        p = self.party
        stamped = False
        if pt.witnessed():
            try:
                p.wait_checkpoint(seconds)
                stamped = True
            except pt.Refused:
                pass
        self._send_ruling(case)
        name = f"ruling-stamp-{case['deal_id'][5:13]}"
        if pt.witnessed() and not stamped and later > 0 and not any(t.name == name and t.is_alive() for t in LATER):
            def go() -> None:
                try:
                    p.wait_checkpoint(later)
                except pt.Refused:
                    return
                self._send_ruling(case)
            t = threading.Thread(target=go, name=name, daemon=True)  # one per deal at a time
            t.start()
            LATER.append(t)
        return stamped

    def _send_ruling(self, case: dict) -> None:
        """Write the ruling file again (with the receipts the shelf holds by then) and hand it to both parties. Under
        the adjudicator party's lock, so a background resend and a ruling made in the window never write the same
        wire files at once (wire.send writes through one temporary path per file)."""
        record = case["ruling"]
        with self.party._lock:
            again = self.rule(case, record["row"], record["value"], record["against"])
            for side in ("buyer", "seller"):
                wire.send(self.home, case["parties"][side], case["deal_id"], "ruling", again["file"])

    def entries(self, case: dict) -> list[dict]:
        """Whether each party entered the ruling, from the copies they sent back after entering it
        (``deal ruling entries``)."""
        args = ["ruling", "entries", "--deal", case["deal_id"], "--ruling", case["ruling"]["ruling"]]
        sent = 0
        for side in ("buyer", "seller"):
            book = wire.path(self.home, ADJUDICATOR, case["deal_id"], f"book-{side}")
            proof = wire.path(self.home, ADJUDICATOR, case["deal_id"], f"proof-{side}")
            if book.is_file():
                args += ["--copy", str(book)] + (["--proof", str(proof)] if proof.is_file() else [])
                sent += 1
        if not sent:
            return []
        return self.party.run(*args)["entries"]


# -- what a party does with the adjudicator ---------------------------------------------------------

def send_dispute(home: Path, dispute_file: Path, deal_id: str, buyer: str, seller: str) -> None:
    """A party hands its dispute to the adjudicator, with who the deal's buyer and seller are on the stage."""
    wire.send_json(home, ADJUDICATOR, deal_id, "parties", {"buyer": buyer, "seller": seller})
    wire.send(home, ADJUDICATOR, deal_id, "dispute", dispute_file)


def answer_requests(home: Path, p: pt.Party, me: str, side: str, say) -> list[str]:
    """Answer each request the adjudicator sent this party, in full (``deal respond``): its whole deal book and the copy it
    holds of the other side's. ``side`` is this party's side (``buyer`` or ``seller``). The requester is the adjudicator key
    the stage publishes; capsulectl answers only when that key is the adjudicator the deal's agreement names (the request
    itself carries no signature). Returns the deals answered now."""
    done = []
    for deal_id, f in wire.pending(home, me, "adjrequest"):
        mark = p.dir / "handled" / f"{deal_id}.adjanswer"
        if mark.exists():
            continue
        out = p.tmp("answer.json")
        # An answer rests on a checkpoint, as a report does, and the records it carries are timed only by a stamp the
        # witness took before it was made. So it waits for a taken stamp, retried on later rounds, for up to
        # ANSWER_WAIT_S after the request first came; past that it goes anyway (its records then read untimed), so a
        # witness that keeps failing never leaves the adjudicator without an answer.
        first = p.dir / "handled" / f"{deal_id}.adjrequest-seen"
        if not first.exists():
            first.parent.mkdir(exist_ok=True)
            first.write_text(str(time.time()))
        try:
            p.wait_checkpoint(12)
        except pt.Refused:
            if time.time() - float(first.read_text() or 0) < ANSWER_WAIT_S:
                continue  # stamped again on the next round
            say(f"the adjudicator's request for deal {deal_id[5:13]}: {pt.WITNESS_NAME} took no stamp in "
                f"{ANSWER_WAIT_S} s; answered without one (its records read untimed)")
        try:
            got = p.run("respond", "--request", str(f), "--requester", named_key(home), "--output", out)
        except pt.Refused as exc:
            if "after its last checkpoint" not in str(exc):
                raise
            continue  # a record sealed since the stamp: stamped again on the next round
        if got.get("outcome") != "artifact":
            p.log(f"the adjudicator's request for deal {deal_id}: deal respond said {json.dumps(got)}")
            say(f"the adjudicator's request for deal {deal_id[5:13]} was not answered: capsulectl refused it for this "
                "party's books, so it is not tried again")
            mark.parent.mkdir(exist_ok=True)
            mark.touch()  # a refusal is final for that request: it is not tried again every round
            continue
        wire.send(home, ADJUDICATOR, deal_id, f"answer-{side}", out)
        mark.parent.mkdir(exist_ok=True)
        mark.touch()
        done.append(deal_id)
        say(f"the adjudicator asked for this party's books of deal {deal_id[5:13]}: sent in full (its own book and the "
            "copy it holds of the other side's)")
    return done


def send_book(home: Path, p: pt.Party, deal_id: str, side: str, say) -> Path:
    """After entering a ruling, send the adjudicator this party's copy (``deal report --share adjudicator``) so it can read
    the entry (``deal ruling entries``), with the stamp proof of the checkpoint it rests on. Returns the copy sent."""
    copy = p.bundle(deal_id, "adjudicator", "the deal's adjudicator", wait=30)
    wire.send(home, ADJUDICATOR, deal_id, f"book-{side}", copy)
    proof = p.proof(deal_id, copy)
    wire.send(home, ADJUDICATOR, deal_id, f"proof-{side}", proof)
    say("this party's book, with the ruling entered, sent to the adjudicator"
        + ("" if _receipts(proof) or not pt.witnessed() else
           f"; its time-stamp follows once {pt.WITNESS_NAME} has taken it"))
    return copy


#: How often a party looks for the witness's receipt of a book it sent without one (send_proof_once_witnessed).
PROOF_EVERY_S = 20


def _receipts(proof: Path) -> bool:
    try:
        return bool(json.loads(Path(proof).read_text()).get("witness_receipts"))
    except (OSError, ValueError):
        return False


def send_proof_once_witnessed(home: Path, p: pt.Party, deal_id: str, copy: Path, side: str, say) -> Path | str | None:
    """For a book sent before the witness took the stamp it rests on, at most every :data:`PROOF_EVERY_S`: deliver
    pending stamps (``deal tick``), make that copy's stamp proof again and, once it carries the witness's receipt, send it
    to the adjudicator, so ``deal ruling entries`` shows the entry time-stamped (evidencebook-skills#328). A proof is
    always of its own copy (capsulectl binds them). When the book has changed since (a later statement or ruling file),
    no later stamp covers the old copy, so a new copy is made and, once its own proof carries a receipt, both go again.

    Returns the copy whose time-stamped proof was sent, :data:`GAVE_UP` once after :data:`PROOF_GIVE_UP_S` (said, and
    not tried again by this process), or None when there is nothing new this round."""
    mark = p.dir / "handled" / f"{deal_id}.proof-tried"
    now = time.time()
    if mark.exists():
        if now - mark.stat().st_mtime < PROOF_EVERY_S:
            return None
        first = float(mark.read_text() or now)
    else:
        mark.parent.mkdir(exist_ok=True)
        first = now
    mark.write_text(str(first))
    if (p.dir, deal_id) in _GAVE_UP:
        return None
    if now - first > PROOF_GIVE_UP_S:
        # not a delivery: nothing is noted, so a reopened window (a new process, the mark cleared) tries again
        p.log(f"deal {deal_id}: no witness receipt for this party's book after {PROOF_GIVE_UP_S} s; stopped trying")
        _GAVE_UP.add((p.dir, deal_id))
        mark.unlink(missing_ok=True)
        say(f"this party's book of deal {deal_id[5:13]}: {pt.WITNESS_NAME} has not time-stamped it in "
            f"{PROOF_GIVE_UP_S // 60} minutes; the ruling is entered, its entry not time-stamped. Reopening this window "
            "tries again.")
        return GAVE_UP
    p.tick()
    for c in ([copy] if copy.is_file() else []) + [None]:
        if c is None:  # the book changed since that copy: a new one, on the checkpoints there are
            try:
                c = p.bundle(deal_id, "adjudicator", "the deal's adjudicator")
            except pt.Refused:
                return None  # a record after its last checkpoint: the next tick covers it
        proof = p.proof(deal_id, c)
        if _receipts(proof):
            # the book and its own proof go together every time, so a retry after a half-sent pair never leaves the
            # adjudicator one copy's proof beside another copy's book
            wire.send(home, ADJUDICATOR, deal_id, f"book-{side}", c)
            wire.send(home, ADJUDICATOR, deal_id, f"proof-{side}", proof)
            say(f"this party's book of deal {deal_id[5:13]}, with the ruling entered, is now time-stamped by "
                f"{pt.WITNESS_NAME}; sent to the adjudicator")
            return c
    return None


#: How long a party keeps looking for its book's witness receipt (send_proof_once_witnessed).
PROOF_GIVE_UP_S = 900
#: send_proof_once_witnessed stopped looking, in this process (:data:`_GAVE_UP`).
GAVE_UP = "gave up"
_GAVE_UP: set[tuple[Path, str]] = set()
