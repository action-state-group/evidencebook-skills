# SPDX-License-Identifier: Apache-2.0
"""The demo's adjudicator: a capsulectl-deal profile of its own (one key for its records and its checkpoints, the key every
agreement names), run by the operator, which rules with capsulectl's own verbs (evidencebook#861, design note
``docs/design/861-four-books.md``; capsulectl at the run sheet's pin):

1. A party sends it the dispute it raised (``deal dispute``'s file).
2. It asks each party for its books: a ``deal_adjudicator_copy/1`` evidence request over the deal's correlation. Each
   party's agent answers on its own with ``deal respond``: its whole deal book and the copy it holds of the other side's
   (u207, u211: full disclosure; four books).
3. No person decides (Ethan, 2026-11-26, evidencebook-skills#416: nobody sits at a screen to click Rule). Once both
   sides answered, or :data:`RULE_AFTER_S` after asking with the answer that came, ``deal ruling check`` reports whether
   the books decide the row (evidencebook ``xdealv1.DecideCase``: only the owing side's own latest signed statement
   that the row was not met decides it). When it does, ``deal ruling --decided-by RECORD --answer A [--answer B]``
   seals it over the books read (``xdealv1.GatherCase``); otherwise nothing is sealed and the case keeps the reason it
   needs a person. A side whose own book was not shown is read only from records it signed, as the other side holds
   them (u211 item 2).
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

#: The conflict determination the adjudicator's window shows with every case (ops u120: whether Action State is, or acts
#: for, a party).
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
5. When the side a ruling would go against has itself stated, in a record it signed, that the row was not met, and has
   not stated otherwise since, the adjudicator rules without a person. Otherwise it does not rule, and the case waits
   for a person.
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
#: How long after asking both sides the adjudicator rules on the answers that came, when one side has not answered
#: (Adjudicator.rule_decided): past ANSWER_WAIT_S, by which a running party answers even without a stamp.
RULE_AFTER_S = 120
#: One ruling step at a time in this process (Adjudicator.rule_decided, Adjudicator.resume).
_RULING = threading.RLock()


def epoch(at: str) -> float:
    """A ``%Y-%m-%dT%H:%M:%SZ`` time as seconds since the epoch."""
    import calendar
    return float(calendar.timegm(time.strptime(at, "%Y-%m-%dT%H:%M:%SZ")))


def case_row(case: dict) -> str:
    """The row a case's dispute is on, from the dispute record itself."""
    row = json.loads(Path(case["dispute"]).read_text()).get("record", {}).get("payload", {}).get("body", {}).get("row")
    if not row:
        raise AdjudicatorError(f"the dispute for {case['deal_id']} names no row")
    return row


def decision(home: Path, deal_id: str) -> dict | None:
    """What ``deal ruling check`` said of a case when the adjudicator last checked it, with the answers it read; None
    before then."""
    f = wire.path(home, ADJUDICATOR, deal_id, "decision")
    return json.loads(f.read_text()) if f.is_file() else None


def needs_person(d: dict | None, answers: dict) -> bool:
    """``deal ruling check`` said, on exactly these answers, that the case needs a person (a check capsulectl could not
    run is not that, and neither is a decisive one whose seal is still to come)."""
    return bool(d) and bool(d.get("needs_person")) and not d.get("retry") and \
        sorted(d.get("answers", {})) == sorted(answers)


def stamped(home: Path, deal_id: str) -> bool:
    """The witness took the stamp of the ruling on this deal and the stamped ruling went to both parties."""
    return wire.path(home, ADJUDICATOR, deal_id, "ruling-stamped").is_file()


def _rules_digests(files: list[Path]) -> set[str]:
    """Every adjudicator ``rules_digest`` the agreements in these answer files name."""
    found: set[str] = set()

    def walk(v) -> None:
        if isinstance(v, dict):
            if isinstance(v.get("rules_digest"), str) and "key_id" in v:
                found.add(v["rules_digest"])
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    for f in files:
        try:
            walk(json.loads(f.read_text()))
        except (OSError, ValueError):
            continue
    return found


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
                        "ruling": json.loads(ruling.read_text()) if ruling.is_file() else None,
                        "decision": decision(self.home, deal_id)})
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

    def check(self, case: dict, answers: dict[str, str]) -> dict:
        """What evidencebook's rule says of the case over these answers (``deal ruling check``, which seals nothing):
        ``decisive`` (against, value, the deciding record) or ``needs_person`` with the reason."""
        args = ["ruling", "check", "--deal", case["deal_id"], "--row", case_row(case), "--dispute", str(case["dispute"])]
        for side in ("buyer", "seller"):
            if side in answers:
                args += ["--answer", answers[side]]
        return self.party.run(*args)

    def rule(self, case: dict, row: str, value: str, against: str, decided_by: str = "",
             answers: dict[str, str] | None = None) -> dict:
        """Record the ruling with ``deal ruling`` over ``answers`` (by default the answers that came back), final for the
        row; with ``decided_by``, only as ``deal ruling check`` decides it on that record. The same ruling again seals
        nothing and writes the file again with the receipts the shelf holds by then. The record keeps the answers and
        the deciding record it was sealed on, so a resend never reads an answer that came later."""
        p = self.party
        if answers is None:
            answers = {side: str(a["file"]) for side, a in case["answers"].items()}
        args = ["ruling", "--deal", case["deal_id"], "--row", row, "--value", value, "--against", against, "--final",
                "--dispute", str(case["dispute"])]
        for side in ("buyer", "seller"):
            if side in answers:
                args += ["--answer", answers[side]]
        if decided_by:
            args += ["--decided-by", decided_by]
        out = p.tmp("ruling.json")
        try:
            done = p.run(*args, "--out", out)
        except pt.Refused as exc:
            raise AdjudicatorError(str(exc)) from None
        record = {"ruling": done.get("ruling", ""), "sealed": done.get("sealed"), "row": row, "value": value,
                  "against": against, "file": out, "books": done.get("books", {}), "answers": answers,
                  "decided_by": decided_by}
        wire.send_json(self.home, ADJUDICATOR, case["deal_id"], "ruling", record)
        return record

    def rule_decided(self, now: float | None = None) -> list[str]:
        """The adjudicator's own step, with no person: for each case not ruled yet whose answers are in (both sides, or
        the ones that came within :data:`RULE_AFTER_S` of asking), ask ``deal ruling check`` and, when it decides the
        row, seal the ruling on the deciding record, take its stamp and send it to both parties. A case the check does
        not decide keeps the reason (:func:`decision`) and is checked again when another answer arrives. Under one lock
        and on the case read again inside it, so the window's loop and a terminal run never seal twice. Returns the
        deals ruled now."""
        now = time.time() if now is None else now
        ruled = []
        with _RULING:
            for case in self.cases():
                if case["ruling"] or not case["answers"] or not case["asked_at"]:
                    continue
                waited = now - epoch(case["asked_at"])
                if len(case["answers"]) < 2 and waited < RULE_AFTER_S:
                    continue
                answers = {side: str(a["file"]) for side, a in case["answers"].items()}
                before = decision(self.home, case["deal_id"])
                if before and before.get("decisive"):
                    # a decisive check whose seal did not finish (capsulectl may have sealed it before it failed): it
                    # is tried again on the answers and the deciding record it was decided on, never on an answer
                    # that came since, since capsulectl refuses a second final ruling that differs
                    d, answers = before, before["answers"]
                elif needs_person(before, answers):
                    continue  # the check did not decide on these answers: wait for another
                else:
                    d = self._decide(case, answers)
                    wire.send_json(self.home, ADJUDICATOR, case["deal_id"], "decision", {**d, "answers": answers})
                if not d.get("decisive"):
                    continue
                k = d["decisive"]
                try:  # a seal that fails is tried again next round: a decisive check is never cached as done
                    r = self.rule(case, case_row(case), k["value"], k["against"], decided_by=k["record_id"],
                                  answers=answers)
                except AdjudicatorError as exc:
                    self.party.log(f"sealing the ruling on {case['deal_id']}: {exc}")
                    continue
                ruled.append(case["deal_id"])
                try:
                    self.stamp({**case, "ruling": r})
                except Exception as exc:  # noqa: BLE001: sent again by resume() on the next round
                    self.party.log(f"sending the ruling on {case['deal_id']}: {exc!r}")
        return ruled

    def _decide(self, case: dict, answers: dict[str, str]) -> dict:
        """``deal ruling check``, unless the deal's agreement names rules other than the ones published now (a home
        made before the rules changed): no ruling without a person is made under rules the agreement does not name."""
        named = _rules_digests([Path(f) for f in answers.values()])
        if named and named != {rules_digest()}:
            return {"needs_person": "the deal's agreement names older adjudicator rules than the ones published now; "
                                    "reset this home and seed it again"}
        try:
            return self.check(case, answers)
        except pt.Refused as exc:
            self.party.log(f"deal ruling check on {case['deal_id']}: {exc!r}")
            return {"needs_person": f"capsulectl could not check the case: {exc}", "retry": True}  # tried next round

    def resume(self) -> list[str]:
        """Every round of the window's loop, for each ruling sealed earlier, sealing nothing new: a ruling not yet sent
        to both parties (the send failed, or the window closed first) is sent again, and a ruling whose stamp the
        witness has not taken is stamped again in the background (:meth:`_stamp_later`) whenever no stamp is under way,
        so this window keeps asking for as long as it is open. Each is marked only once it has succeeded. Returns the
        deals sent again now."""
        done = []
        with _RULING:
            for case in self.cases():
                if not case["ruling"]:
                    continue
                if not wire.path(self.home, ADJUDICATOR, case["deal_id"], "ruling-sent").is_file():
                    try:
                        self._send_ruling(case, False)
                        done.append(case["deal_id"])
                    except Exception as exc:  # noqa: BLE001: tried again on the next round
                        self.party.log(f"sending the ruling on {case['deal_id']} again: {exc!r}")
                if pt.witnessed() and not stamped(self.home, case["deal_id"]):
                    self._stamp_later(case, LATER_S)
        return done

    def stamp(self, case: dict, seconds: float = 12, later: float = LATER_S) -> bool:
        """Take a checkpoint now (on demand) so the witness stamps the ruling, write the ruling file again with the
        receipt, and hand it to both parties. True when the stamp was delivered within ``seconds`` (never without a
        witness); the ruling goes to the parties either way. A stamp the witness did not take in time (it answers
        slowly under load, evidencebook-skills#307) keeps being taken in the background for up to ``later`` seconds,
        and the ruling goes to both parties again with its receipt when it is: each party then records its time
        (flow.enter_rulings takes a ruling file that arrives again). A delivered stamp is marked, so a window opened
        again does not send it once more (:meth:`resume`)."""
        p = self.party
        stamped = False
        if pt.witnessed():
            try:
                p.wait_checkpoint(seconds)
                stamped = True
            except pt.Refused:
                pass
        self._send_ruling(case, stamped)
        if pt.witnessed() and not stamped and later > 0:
            self._stamp_later(case, later)
        return stamped

    def _stamp_later(self, case: dict, later: float) -> None:
        """Keep taking the ruling's stamp in the background for up to ``later`` seconds, one thread per deal at a time,
        and send the ruling again with its receipt once it is taken."""
        name = f"ruling-stamp-{case['deal_id'][5:13]}"
        if any(t.name == name and t.is_alive() for t in LATER):
            return
        p = self.party

        def go() -> None:
            try:
                p.wait_checkpoint(later)
                self._send_ruling(case, True)
            except Exception as exc:  # noqa: BLE001: resume() starts another on a later round
                p.log(f"stamping the ruling on {case['deal_id']}: {exc!r}")
        t = threading.Thread(target=go, name=name, daemon=True)
        t.start()
        LATER.append(t)

    def _send_ruling(self, case: dict, stamped: bool) -> None:
        """Write the ruling file again (with the receipts the shelf holds by then), over the answers it was sealed on,
        and hand it to both parties. Under the adjudicator party's lock, so a background resend and a ruling made in
        the window never write the same wire files at once (wire.send writes through one temporary path per file)."""
        record = case["ruling"]
        with self.party._lock:
            again = self.rule(case, record["row"], record["value"], record["against"],
                              decided_by=record.get("decided_by", ""), answers=record.get("answers"))
            for side in ("buyer", "seller"):
                wire.send(self.home, case["parties"][side], case["deal_id"], "ruling", again["file"])
            wire.send_json(self.home, ADJUDICATOR, case["deal_id"], "ruling-sent", {"at": _now()})
            if stamped:
                wire.send_json(self.home, ADJUDICATOR, case["deal_id"], "ruling-stamped", {"at": _now()})

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
            say(f"the adjudicator's request for deal {deal_id[5:13]} was not answered: this party's records refused it for this "
                "party's books, so it is not tried again")
            mark.parent.mkdir(exist_ok=True)
            mark.touch()  # a refusal is final for that request: it is not tried again every round
            continue
        wire.send(home, ADJUDICATOR, deal_id, f"answer-{side}", out)
        mark.parent.mkdir(exist_ok=True)
        mark.touch()
        done.append(deal_id)
        say(books_sent_line(deal_id))
    return done


def books_sent_line(deal_id: str) -> str:
    """A party's books going to the adjudicator, as its activity says it (an event, evidencebook-skills#336)."""
    return (f"the adjudicator asked for this party's books of deal {deal_id[5:13]}: sent in full (its own book and the "
            "copy it holds of the other side's)")


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
    no later stamp covers the old copy, so one new copy is made, once per process (a shared copy seals a disclose
    record, so a copy every round would keep changing the book), and, once its own proof carries a receipt, both go.

    Returns the copy whose time-stamped proof was sent, :data:`GAVE_UP` once after :data:`PROOF_GIVE_UP_S` (said, and
    not tried again by this process), or None when there is nothing new this round. The pace and the deadline are this
    process's own (:data:`_PROOF_TRIES`): a reopened window is a new process and starts again, with nothing on disk to
    carry an old deadline over."""
    key, now = (p.dir, deal_id), time.time()
    first, last = _PROOF_TRIES.get(key, (now, 0.0))
    copy = _NEW_COPY.get(key, copy)
    if first is None or now - last < PROOF_EVERY_S:  # gave up in this process, or tried less than PROOF_EVERY_S ago
        return None
    if now - first > PROOF_GIVE_UP_S:
        _PROOF_TRIES[key] = (None, now)
        p.log(f"deal {deal_id}: this party's time-stamped book not sent to the adjudicator in {PROOF_GIVE_UP_S} s; "
              "stopped trying")
        say(f"this party's book of deal {deal_id[5:13]}: its time-stamp could not be sent to the adjudicator in "
            f"{PROOF_GIVE_UP_S // 60} minutes; the ruling is entered. Reopening this window tries again.")
        return GAVE_UP
    _PROOF_TRIES[key] = (first, now)
    p.tick()
    for c in ([copy] if copy.is_file() else []) + ([None] if key not in _NEW_COPY else []):
        if c is None:  # the book changed since that copy: one new copy, on the checkpoints there are
            try:
                c = p.bundle(deal_id, "adjudicator", "the deal's adjudicator")
            except pt.Refused:
                return None  # a record after its last checkpoint: the next tick covers it
            _NEW_COPY[key] = c
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
#: send_proof_once_witnessed stopped looking, in this process.
GAVE_UP = "gave up"
#: Per party folder and deal: when this process first tried, and when it last tried (first None: it gave up).
_PROOF_TRIES: dict[tuple[Path, str], tuple[float | None, float]] = {}
#: Per party folder and deal: the one new copy this process made (send_proof_once_witnessed), tried from then on.
_NEW_COPY: dict[tuple[Path, str], Path] = {}
