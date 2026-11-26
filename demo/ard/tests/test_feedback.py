# SPDX-License-Identifier: Apache-2.0
"""Steven's 2026-11-25 run with a slow witness (evidencebook-skills#326-#329): the adjudicator asks for books as soon as
a dispute arrives; no raw error reaches a chat; the ruling's entries say which record lacks a stamp; the chat receipt
reads the witness time the way the page does. No binary is run here."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

import adjudicator as adj
import flow
import party as pt
import receipt
import screens
import wire

DEAL = "deal-0123456789abcdef"


@pytest.fixture(autouse=True)
def _fresh_proof_tries():
    """Each test is its own process as far as the proof's pace and deadline go."""
    adj._PROOF_TRIES.clear()
    adj._NEW_COPY.clear()
    yield
    adj._PROOF_TRIES.clear()
    adj._NEW_COPY.clear()


# -- #327: one plain line, said once ---------------------------------------------------------------

def test_a_failure_reads_as_one_plain_line_and_never_carries_raw_output():
    slow = screens.trying_again("entering the adjudicator's ruling", pt.WitnessSlow("Action State's witness took no "
                                                                                     "stamp within 29 s"))
    other = screens.trying_again("entering the adjudicator's ruling",
                                 pt.Refused('maya: no checkpoint in 29 s (last: {"cadence_log": []})'))
    assert slow == ("entering the adjudicator's ruling: waiting for Action State's witness, which is slow or not answering; "
                    "trying again")
    assert other == ("entering the adjudicator's ruling: not done yet (the reason is in this party's log, agent.log); "
                     "trying again")
    assert "{" not in slow + other and "consent" not in slow + other


def test_a_step_that_keeps_failing_says_so_once_until_something_else_happens():
    failing: set[str] = set()
    line = screens.trying_again("x", pt.WitnessSlow("slow"))
    assert screens.once_per_failure(failing, line) is True
    assert screens.once_per_failure(failing, line) is False  # the next round, or the next request: not again
    assert screens.once_per_failure(failing, "the ruling entered") is True
    assert screens.once_per_failure(failing, line) is True  # it came back after progress: said again


def test_a_seller_says_a_repeated_failure_once():
    agent = flow.SellerAgent.__new__(flow.SellerAgent)
    agent.log, agent._lock = [], threading.Lock()
    agent.party = type("P", (), {"log": lambda self, line: None})()
    for _ in range(3):
        agent.failed("publishing this seller's History card", pt.WitnessSlow("slow"))
    assert len(agent.log) == 1 and "{" not in agent.log[0]


def test_a_wait_the_witness_does_not_answer_raises_plain_words_and_logs_the_tick(tmp_path, monkeypatch):
    monkeypatch.setenv("ARD_WITNESS", "public")
    clock = [0.0]
    monkeypatch.setattr(pt.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(pt.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + s))
    p = pt.Party.__new__(pt.Party)
    p.name, p.dir = "maya", tmp_path

    def untaken():
        clock[0] += 5
        return {"state": "ticked", "checkpoint": 1, "delivered": [], "cadence_log": ["x"]}
    p.stamp = untaken
    with pytest.raises(pt.WitnessSlow) as got:
        p.wait_checkpoint(12)
    assert str(got.value) == "Action State's witness took no stamp within 12 s"
    assert "cadence_log" in (tmp_path / "agent.log").read_text()  # the raw tick is in the party's own log


def test_a_report_goes_once_the_stamp_is_cut_even_if_the_witness_has_not_taken_it(tmp_path):
    """Claude's plan review: the book needs only the checkpoint, not the witness's receipt of it."""
    p = pt.Party.__new__(pt.Party)
    p.name, p.dir, calls = "kestrel", tmp_path, []

    def run(*args):
        calls.append(args[0])
        if calls.count("report") == 1:
            raise pt.Refused("a record sealed after its last checkpoint")
        return {}
    p.run = run
    p.tmp = lambda name: str(tmp_path / name)

    def slow(seconds, say=None):
        calls.append("stamp")
        raise pt.WitnessSlow("slow")
    p.wait_checkpoint = slow
    assert p.bundle(DEAL, "adjudicator", wait=30).name.endswith("adjudicator-copy.json")
    assert calls == ["report", "stamp", "report"]


# -- #326: asked on arrival, once ------------------------------------------------------------------

def test_the_adjudicator_asks_each_side_once_however_many_callers_ask(tmp_path, monkeypatch):
    home = tmp_path
    wire.send_json(home, adj.ADJUDICATOR, DEAL, "parties", {"buyer": "maya", "seller": "kestrel"})
    (tmp_path / "d.json").write_text("{}")
    wire.send(home, adj.ADJUDICATOR, DEAL, "dispute", tmp_path / "d.json")
    sent = []
    real = wire.send_json

    def slow_send(h, to, deal_id, kind, doc):
        if kind == "adjrequest":
            sent.append(to)
            time.sleep(0.05)  # widen the window between the check and the mark
        return real(h, to, deal_id, kind, doc)
    monkeypatch.setattr(adj.wire, "send_json", slow_send)
    a = adj.Adjudicator(home)
    threads = [threading.Thread(target=a.ask) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(sent) == ["kestrel", "maya"]


def test_the_adjudicators_window_asks_without_anyone_opening_the_case(monkeypatch):
    ds = pytest.importorskip("desktop_server")
    asked = []

    class Stop(Exception):
        pass
    monkeypatch.setattr(ds.adj.Adjudicator, "ask", lambda self: asked.append(1) or [])

    def sleep(s):
        if len(asked) >= 2:
            raise Stop
    monkeypatch.setattr(ds.time, "sleep", sleep)
    with pytest.raises(Stop):
        ds._ask_on_arrival()
    assert len(asked) == 2


# -- #328: which record lacks a stamp ----------------------------------------------------------------

NAMES = {"buyer": "Maya", "seller": "Kestrel Print"}


def test_the_entries_say_the_rulings_stamp_then_each_partys_entry():
    lines = flow.entry_lines(DEAL, [
        {"party": "buyer", "state": "entered", "ruling_witnessed_at": "2026-11-25T22:25:00Z"},
        {"party": "seller", "state": "entered_unwitnessed", "ruling_witnessed_at": "2026-11-25T22:25:00Z"}], NAMES)
    assert lines[0].startswith("deal 01234567: the ruling was time-stamped by Action State's witness at ")
    assert lines[1] == "  Maya: entered it; the entry is time-stamped by Action State's witness"
    assert lines[2].startswith("  Kestrel Print: entered it; the entry is not time-stamped yet")


@pytest.mark.parametrize("row,want", [
    ({"party": "seller", "state": "not_entered", "checkpoint_at": "2026-11-25T22:30:00Z"},
     "  Kestrel Print: had not entered it as of its book's checkpoint at "),
    ({"party": "seller", "state": "not_shown"}, "  Kestrel Print: its book does not show it entered yet (the ruling has "
                                               "no time-stamp yet to compare with)"),
    ({"party": "seller", "state": "something_new", "words": "capsulectl's words"}, "  Kestrel Print: capsulectl's words"),
])
def test_every_entry_state_stays_apart(row, want):
    lines = flow.entry_lines(DEAL, [row], NAMES)
    assert lines[0] == "deal 01234567: the ruling is not time-stamped yet (Action State's witness has not taken its stamp)"
    assert lines[1].startswith(want)
    assert lines[2] == "  Maya: has not sent their book back yet"


def test_no_book_back_yet_says_so():
    assert flow.entry_lines(DEAL, [], NAMES) == [
        "deal 01234567: no party has sent its book back yet; the ruling's time-stamp and each entry show once one has"]


class Book:
    """A party for enter_rulings: its notes, receive and log, no binary."""

    def __init__(self, tmp_path, receive_fails=0):
        self.name, self.dir, self._notes, self.logged = "maya", tmp_path, [], []
        self.receive_fails = receive_fails

    def notes(self, kind):
        return [n for n in self._notes if n["kind"] == kind]

    def note(self, kind, statement, **_):
        self._notes.append({"kind": kind, "statement": statement})

    def tmp(self, name):
        return str(self.dir / name)

    def receive(self, file, out=""):
        if self.receive_fails:
            self.receive_fails -= 1
            raise pt.Refused("receive failed")
        return {"stamped_at": ""}

    def log(self, line):
        self.logged.append(line)


def test_the_ruling_stays_entered_when_its_book_waits_for_the_witness(tmp_path, monkeypatch):
    monkeypatch.setenv("ARD_WITNESS", "public")
    ruling = tmp_path / "ruling.json"
    ruling.write_text("{}")
    monkeypatch.setattr(flow.wire, "pending", lambda home, me, kind: [(DEAL, ruling)])
    monkeypatch.setattr(flow.wire, "send", lambda *a: None)
    fails = [1]

    def send_book(home, p, deal_id, side, say):
        if fails[0]:
            fails[0] -= 1
            raise pt.WitnessSlow("slow")
        return tmp_path / "copy.json"
    monkeypatch.setattr(flow.adj, "send_book", send_book)
    proofs = []
    monkeypatch.setattr(flow.adj, "send_proof_once_witnessed",
                        lambda home, p, deal_id, copy, side, say: proofs.append(copy) or True)
    p, said = Book(tmp_path), []
    flow.enter_rulings(tmp_path, p, "buyer", "kestrel", said.append)
    assert said[0].startswith("the adjudicator's ruling on deal 01234567 entered")
    assert said[1].endswith("waiting for Action State's witness, which is slow or not answering; trying again")
    assert not p.notes(flow.BOOK_SENT)
    flow.enter_rulings(tmp_path, p, "buyer", "kestrel", said.append)  # the next round: the book goes
    assert p.notes(flow.BOOK_SENT)[0]["statement"]["copy"] == str(tmp_path / "copy.json")
    flow.enter_rulings(tmp_path, p, "buyer", "kestrel", said.append)  # then its stamp, for that same copy
    assert proofs == [tmp_path / "copy.json"] and p.notes(flow.PROOF_SENT)
    flow.enter_rulings(tmp_path, p, "buyer", "kestrel", said.append)
    assert len(proofs) == 1  # sent once


def test_a_late_ruling_file_that_failed_to_be_taken_is_taken_next_round(tmp_path, monkeypatch):
    """Codex's plan review: the mark is set only after the file is taken."""
    monkeypatch.setenv("ARD_WITNESS", "public")
    ruling = tmp_path / "ruling.json"
    ruling.write_text("{}")
    monkeypatch.setattr(flow.wire, "pending", lambda home, me, kind: [(DEAL, ruling)])
    p = Book(tmp_path, receive_fails=1)
    p.note(flow.RULING_ENTERED, {"deal_id": DEAL, "stamped_at": ""})
    p.note(flow.BOOK_SENT, {"deal_id": DEAL, "copy": ""})
    with pytest.raises(pt.Refused):
        flow.enter_rulings(tmp_path, p, "buyer", "kestrel", lambda *_: None)
    assert not (tmp_path / "handled" / f"{DEAL}.ruling-seen").exists()
    flow.enter_rulings(tmp_path, p, "buyer", "kestrel", lambda *_: None)
    assert (tmp_path / "handled" / f"{DEAL}.ruling-seen").stat().st_mtime == ruling.stat().st_mtime


def test_a_stamp_proof_goes_again_only_once_it_carries_the_receipt(tmp_path, monkeypatch):
    copy = tmp_path / "copy.json"
    copy.write_text("{}")
    sent, receipts, ticks = [], [[]], []

    class P:
        dir = tmp_path

        def tick(self):
            ticks.append(1)

        def proof(self, deal_id, c):
            assert c == copy  # always the copy already sent
            out = tmp_path / "proof.json"
            out.write_text(json.dumps({"stamp_proof": {}, "witness_receipts": receipts[0]}))
            return out
    monkeypatch.setattr(adj.wire, "send", lambda home, to, deal_id, kind, f: sent.append(kind))
    clock = [1000.0]
    monkeypatch.setattr(adj.time, "time", lambda: clock[0])
    P.bundle = lambda self, deal_id, share, to: (_ for _ in ()).throw(pt.Refused("after its last checkpoint"))
    assert adj.send_proof_once_witnessed(tmp_path, P(), DEAL, copy, "buyer", lambda *_: None) is None
    assert adj.send_proof_once_witnessed(tmp_path, P(), DEAL, copy, "buyer", lambda *_: None) is None
    assert ticks == [1]  # throttled: not every round
    clock[0] += adj.PROOF_EVERY_S
    receipts[0] = [{"receipt": "r"}]
    said = []
    assert adj.send_proof_once_witnessed(tmp_path, P(), DEAL, copy, "buyer", said.append) == copy
    assert sent == ["book-buyer", "proof-buyer"] and "now time-stamped" in said[0]


def test_a_changed_book_goes_again_with_a_time_stamped_copy_and_the_search_ends(tmp_path, monkeypatch):
    """Claude's round 1: the old copy's checkpoint never gets a receipt once the book changed; a new copy does."""
    old, new = tmp_path / "old.json", tmp_path / "new.json"
    old.write_text("{}")
    new.write_text("{}")
    sent = []

    class P:
        dir = tmp_path

        def tick(self):
            pass

        def bundle(self, deal_id, share, to):
            return new

        def proof(self, deal_id, c):
            out = tmp_path / f"proof-{c.stem}.json"
            out.write_text(json.dumps({"stamp_proof": {}, "witness_receipts": [{"r": 1}] if c == new else []}))
            return out

        def log(self, line):
            pass
    monkeypatch.setattr(adj.wire, "send", lambda home, to, deal_id, kind, f: sent.append((kind, Path(f).name)))
    clock = [1000.0]
    monkeypatch.setattr(adj.time, "time", lambda: clock[0])
    assert adj.send_proof_once_witnessed(tmp_path, P(), DEAL, old, "seller", lambda *_: None) == new
    assert sent == [("book-seller", "new.json"), ("proof-seller", "proof-new.json")]
    clock[0] += adj.PROOF_GIVE_UP_S + 1
    said = []
    assert adj.send_proof_once_witnessed(tmp_path, P(), DEAL, old, "seller", said.append) == adj.GAVE_UP
    assert said == ["this party's book of deal 01234567: its time-stamp could not be sent to the adjudicator in 15 "
                    "minutes; the ruling is entered. Reopening this window tries again."]
    clock[0] += adj.PROOF_EVERY_S
    assert adj.send_proof_once_witnessed(tmp_path, P(), DEAL, old, "seller", said.append) is None  # not this process
    assert not (tmp_path / "handled").exists()  # nothing on disk carries the deadline over


def test_a_reopened_window_tries_again_however_long_after(tmp_path, monkeypatch):
    """Codex's and Claude's round 3: a give-up never makes the next process give up at once."""
    ticks = []

    class P:
        dir = tmp_path

        def tick(self):
            ticks.append(1)

        def bundle(self, deal_id, share, to):
            raise pt.Refused("after its last checkpoint")

        def proof(self, deal_id, c):
            out = tmp_path / "proof.json"
            out.write_text(json.dumps({"stamp_proof": {}, "witness_receipts": []}))
            return out

        def log(self, line):
            pass
    clock = [1000.0]
    monkeypatch.setattr(adj.time, "time", lambda: clock[0])
    copy = tmp_path / "c.json"
    copy.write_text("{}")
    adj.send_proof_once_witnessed(tmp_path, P(), DEAL, copy, "buyer", lambda *_: None)
    clock[0] += adj.PROOF_GIVE_UP_S + 1
    assert adj.send_proof_once_witnessed(tmp_path, P(), DEAL, copy, "buyer", lambda *_: None) == adj.GAVE_UP
    for _ in range(3):  # the old process's later rounds
        clock[0] += adj.PROOF_EVERY_S
        assert adj.send_proof_once_witnessed(tmp_path, P(), DEAL, copy, "buyer", lambda *_: None) is None
    adj._PROOF_TRIES.clear()  # the window reopened: a new process
    clock[0] += 2 * adj.PROOF_GIVE_UP_S
    before = len(ticks)
    assert adj.send_proof_once_witnessed(tmp_path, P(), DEAL, copy, "buyer", lambda *_: None) is None
    assert len(ticks) == before + 1  # it tried, not gave up


def test_a_book_noted_before_this_change_is_proved_from_the_adjudicators_copy(tmp_path, monkeypatch):
    """Codex's round 1: a BOOK_SENT note with no copy uses the book the adjudicator holds."""
    monkeypatch.setenv("ARD_WITNESS", "public")
    ruling = tmp_path / "ruling.json"
    ruling.write_text("{}")
    monkeypatch.setattr(flow.wire, "pending", lambda home, me, kind: [(DEAL, ruling)])
    got = []
    monkeypatch.setattr(flow.adj, "send_proof_once_witnessed",
                        lambda home, p, deal_id, copy, side, say: got.append(copy) or None)
    p = Book(tmp_path)
    p.note(flow.RULING_ENTERED, {"deal_id": DEAL, "stamped_at": "2026-11-25T22:25:00Z"})
    p.note(flow.BOOK_SENT, {"deal_id": DEAL})
    flow.enter_rulings(tmp_path, p, "buyer", "kestrel", lambda *_: None)
    assert got == [wire.path(tmp_path, adj.ADJUDICATOR, DEAL, "book-buyer")]


def test_a_proof_step_that_fails_is_named_as_itself_not_as_entering_the_ruling(tmp_path, monkeypatch):
    monkeypatch.setenv("ARD_WITNESS", "public")
    ruling = tmp_path / "ruling.json"
    ruling.write_text("{}")
    monkeypatch.setattr(flow.wire, "pending", lambda home, me, kind: [(DEAL, ruling)])
    monkeypatch.setattr(flow.adj, "send_proof_once_witnessed",
                        lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    p, said = Book(tmp_path), []
    p.note(flow.RULING_ENTERED, {"deal_id": DEAL, "stamped_at": "2026-11-25T22:25:00Z"})
    p.note(flow.BOOK_SENT, {"deal_id": DEAL, "copy": str(tmp_path / "c.json")})
    flow.enter_rulings(tmp_path, p, "buyer", "kestrel", said.append)
    assert said == ["sending the adjudicator this party's book's time-stamp: not done yet (the reason is in this "
                    "party's log, agent.log); trying again"]
    assert "disk full" in p.logged[0]


def test_a_local_checkpoint_failure_is_not_called_a_slow_witness(tmp_path, monkeypatch):
    """Codex's round 1: only a checkpoint cut and not taken is the witness's."""
    monkeypatch.setenv("ARD_WITNESS", "public")
    clock = [0.0]
    monkeypatch.setattr(pt.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(pt.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + s))
    p = pt.Party.__new__(pt.Party)
    p.name, p.dir = "maya", tmp_path

    def broken():
        clock[0] += 5
        raise pt.Refused("local profile is invalid")
    p.stamp = broken
    with pytest.raises(pt.Refused) as got:
        p.wait_checkpoint(12)
    assert not isinstance(got.value, pt.WitnessSlow) and str(got.value) == "local profile is invalid"


def test_a_late_ruling_whose_note_failed_is_taken_again(tmp_path, monkeypatch):
    """Codex's round 1: the mark moves only after the stamp's note is kept."""
    monkeypatch.setenv("ARD_WITNESS", "public")
    ruling = tmp_path / "ruling.json"
    ruling.write_text("{}")
    monkeypatch.setattr(flow.wire, "pending", lambda home, me, kind: [(DEAL, ruling)])
    p = Book(tmp_path)
    p.receive = lambda file, out="": {"stamped_at": "2026-11-25T22:25:00Z"}
    p.note(flow.RULING_ENTERED, {"deal_id": DEAL, "stamped_at": ""})
    p.note(flow.BOOK_SENT, {"deal_id": DEAL, "copy": ""})
    p.note(flow.PROOF_SENT, {"deal_id": DEAL})
    real, fails = p.note, [1]

    def note(kind, statement, **kw):
        if kind == flow.RULING_STAMPED and fails[0]:
            fails[0] -= 1
            raise OSError("store busy")
        return real(kind, statement, **kw)
    p.note = note
    with pytest.raises(OSError):
        flow.enter_rulings(tmp_path, p, "buyer", "kestrel", lambda *_: None)
    flow.enter_rulings(tmp_path, p, "buyer", "kestrel", lambda *_: None)
    assert p.notes(flow.RULING_STAMPED)


def test_the_adjudicators_window_starts_its_ask_loop_when_it_opens(tmp_path, monkeypatch):
    """Codex's round 1: opening the adjudicator's window starts the loop, with no ard_case call."""
    ds = pytest.importorskip("desktop_server")
    started = []
    monkeypatch.setattr(ds, "_seller_lock", None)
    monkeypatch.setattr(ds, "_lock", lambda role: object())
    monkeypatch.setattr(ds.stage, "ensure_stage", lambda home: None)
    monkeypatch.setenv("ARD_HOME", str(tmp_path))

    class T:
        def __init__(self, target, daemon):
            started.append(target)

        def start(self):
            pass
    monkeypatch.setattr(ds.threading, "Thread", T)
    ds._adjudicator()
    assert started == [ds._ask_on_arrival]


def test_a_seller_loop_keeps_running_after_a_step_fails(tmp_path):
    """Codex's round 1: a failure inside the real loop is one plain line and the loop goes on."""
    agent = flow.SellerAgent.__new__(flow.SellerAgent)
    agent.log, agent._lock, agent._stop = [], threading.Lock(), threading.Event()
    agent.party = type("P", (), {"log": lambda self, line: None})()
    rounds = []

    def boom():
        rounds.append(1)
        if len(rounds) >= 3:
            agent._stop.set()
        raise pt.Refused('no checkpoint (last: {"cadence_log": []})')
    for name in ("_offers", "_agreements", "_payments", "_statements", "_disputes", "_requests", "_rulings", "_named"):
        setattr(agent, name, lambda: None)
    agent._offers = boom
    agent.republish = lambda now=False: (_ for _ in ()).throw(RuntimeError("card"))
    agent._loop()
    assert len(rounds) == 3 and all("{" not in line for line in agent.log)
    assert any("taking the buyer's offer: not done yet" in line for line in agent.log)
    assert any("publishing this seller's History card: not done yet" in line for line in agent.log)


@pytest.mark.parametrize("text,plain", [('no checkpoint (last: {"a": 1})', True), ("Maya disputed this delivery", False)])
def test_a_tool_refusal_with_raw_output_is_one_plain_line(tmp_path, monkeypatch, text, plain):
    ds = pytest.importorskip("desktop_server")
    monkeypatch.setenv("ARD_HOME", str(tmp_path))
    out = ds._refusal(pt.Refused(text))
    assert (out != text) is plain and "{" not in out


# -- #329: the chat receipt's witness line ---------------------------------------------------------

@pytest.mark.parametrize("witnessed,want", [
    ({"status": "verified", "witness": "Action State's witness", "at": "2026-11-25T22:41:33Z"},
     "  Time-stamped by Action State's witness at {t}, as checked on Maya's own book."),
    ({"status": "withheld", "reason": "no witness receipt is held for this checkpoint yet"},
     "  Not time-stamped yet: Action State's witness has not taken Maya's latest stamp; ask again in a minute."),
    ({"status": "withheld", "reason": "no receipt verifies under the witness directory"},
     "  No witness time: capsulectl verify reported none it could check for Maya's own book."),
    ({"status": "verified", "witness": "Action State's witness"},
     "  Time-stamped by Action State's witness, as checked on Maya's own book."),
    (None, "  No witness time: capsulectl verify reported none it could check for Maya's own book."),
    ({"status": "withheld"}, "  No witness time: capsulectl verify reported none it could check for Maya's own book."),
    ({"status": "failed", "reason": "the stamp proof does not verify"},
     "  No witness time: capsulectl verify could not check Action State's witness's receipt for Maya's own book."),
])
def test_the_chat_receipt_says_the_witness_time_as_verify_reported_it(monkeypatch, witnessed, want):
    monkeypatch.setenv("ARD_WITNESS", "public")
    assert receipt.witness_line(witnessed, "Maya") == want.format(t=screens.local_time("2026-11-25T22:41:33Z", date=True))


@pytest.mark.parametrize("verdict,half,expect", [
    ("VALID", {"status": "verified"}, "  Signed by both sides: the other side's signed agreement checks out on Maya's own "
                                      "book. It covers their agreement only, not anything after it."),
    ("VALID", None, "  The other side's half is not in this copy."),
    ("INVALID", {"status": "verified"}, "  This copy did not verify (capsulectl deal verify: INVALID)."),
])
def test_the_chat_receipt_waits_as_the_page_does_and_verifies_its_copy_with_its_proof(tmp_path, monkeypatch, verdict,
                                                                                      half, expect):
    monkeypatch.setenv("ARD_WITNESS", "public")
    calls = []

    class P:
        def wait_checkpoint(self, seconds):
            calls.append(("wait", seconds))
            raise pt.WitnessSlow("slow")  # the receipt still goes, saying only what verify reports

        def bundle(self, deal_id):
            calls.append("bundle")
            return tmp_path / "copy.json"

        def proof(self, deal_id, copy):
            calls.append(("proof", copy))
            return tmp_path / "proof.json"

        def verify(self, copy, proof=None):
            calls.append(("verify", copy, proof))
            ext = {"counterparty_half": half} if half else {}
            ext["witnessed"] = {"status": "withheld", "reason": "no witness receipt is held for this checkpoint yet"}
            return {"verdict": verdict, "extensions": [ext]}
    lines = receipt.proof_lines(P(), DEAL, "Maya")
    assert calls == [("wait", receipt.PAGE_WAIT_S), "bundle", ("proof", tmp_path / "copy.json"),
                     ("verify", tmp_path / "copy.json", tmp_path / "proof.json")]
    assert lines == [expect, "  Not time-stamped yet: Action State's witness has not taken Maya's latest stamp; ask "
                             "again in a minute."]


def test_a_receipt_not_ready_says_so_plainly_and_logs_why(tmp_path, monkeypatch):
    monkeypatch.setenv("ARD_WITNESS", "off")
    logged = []

    class P:
        def bundle(self, deal_id):
            raise pt.Refused('report: a record sealed after its last checkpoint {"x": 1}')

        def log(self, line):
            logged.append(line)
    assert receipt.proof_lines(P(), DEAL, "Maya") == ["  This copy is not ready to check yet; ask again in a minute."]
    assert "after its last checkpoint" in logged[0]


def test_a_half_sent_book_and_proof_go_again_as_a_pair(tmp_path, monkeypatch):
    """Codex's round 2: a retry after the proof failed to go sends the chosen copy's book beside its own proof."""
    old = tmp_path / "old.json"
    old.write_text("{}")
    sent, fail = [], [1]

    class P:
        dir = tmp_path

        def tick(self):
            pass

        def proof(self, deal_id, c):
            out = tmp_path / "proof.json"
            out.write_text(json.dumps({"stamp_proof": {}, "witness_receipts": [{"r": 1}]}))
            return out

        def log(self, line):
            pass

    def send(home, to, deal_id, kind, f):
        if kind.startswith("proof") and fail[0]:
            fail[0] -= 1
            raise OSError("disk full")
        sent.append(kind)
    monkeypatch.setattr(adj.wire, "send", send)
    clock = [1000.0]
    monkeypatch.setattr(adj.time, "time", lambda: clock[0])
    with pytest.raises(OSError):
        adj.send_proof_once_witnessed(tmp_path, P(), DEAL, old, "buyer", lambda *_: None)
    clock[0] += adj.PROOF_EVERY_S
    assert adj.send_proof_once_witnessed(tmp_path, P(), DEAL, old, "buyer", lambda *_: None) == old
    assert sent == ["book-buyer", "book-buyer", "proof-buyer"]


def test_giving_up_is_not_noted_as_sent_and_a_note_failure_is_the_proof_steps_own(tmp_path, monkeypatch):
    monkeypatch.setenv("ARD_WITNESS", "public")
    ruling = tmp_path / "ruling.json"
    ruling.write_text("{}")
    monkeypatch.setattr(flow.wire, "pending", lambda home, me, kind: [(DEAL, ruling)])
    answers = [adj.GAVE_UP, tmp_path / "c.json"]
    monkeypatch.setattr(flow.adj, "send_proof_once_witnessed", lambda *a: answers.pop(0))
    p, said = Book(tmp_path), []
    p.note(flow.RULING_ENTERED, {"deal_id": DEAL, "stamped_at": "2026-11-25T22:25:00Z"})
    p.note(flow.BOOK_SENT, {"deal_id": DEAL, "copy": str(tmp_path / "c.json")})
    flow.enter_rulings(tmp_path, p, "buyer", "kestrel", said.append)
    assert not p.notes(flow.PROOF_SENT)
    real = p.note
    p.note = lambda kind, st, **kw: (_ for _ in ()).throw(OSError("store busy")) if kind == flow.PROOF_SENT else real(kind, st)
    flow.enter_rulings(tmp_path, p, "buyer", "kestrel", said.append)
    assert said[-1].startswith("sending the adjudicator this party's book's time-stamp: not done yet")


def test_a_wrapped_refusal_with_raw_output_is_plain_too(tmp_path, monkeypatch):
    """Codex's round 2: ard_rule wraps capsulectl's refusal in a RuntimeError."""
    ds = pytest.importorskip("desktop_server")
    monkeypatch.setenv("ARD_HOME", str(tmp_path))
    out = ds._refusal(RuntimeError('capsulectl refused the ruling: {"error": "x"}'))
    assert out == "this step was refused (the reason is in this party's log, agent.log)"


def test_a_new_copy_is_made_once_not_every_round(tmp_path, monkeypatch):
    """A shared copy seals a disclose record: a copy every round would keep changing the book (the slow-witness e2e)."""
    old = tmp_path / "old.json"
    old.write_text("{}")
    made, proved = [], []

    class P:
        dir = tmp_path

        def tick(self):
            pass

        def bundle(self, deal_id, share, to):
            c = tmp_path / f"new{len(made)}.json"
            c.write_text("{}")
            made.append(c)
            return c

        def proof(self, deal_id, c):
            proved.append(c.name)
            out = tmp_path / "proof.json"
            out.write_text(json.dumps({"stamp_proof": {}, "witness_receipts": []}))
            return out
    clock = [1000.0]
    monkeypatch.setattr(adj.time, "time", lambda: clock[0])
    for _ in range(4):
        assert adj.send_proof_once_witnessed(tmp_path, P(), DEAL, old, "seller", lambda *_: None) is None
        clock[0] += adj.PROOF_EVERY_S
    assert len(made) == 1 and proved == ["old.json", "new0.json", "new0.json", "new0.json", "new0.json"]


def test_an_unknown_entry_state_shows_capsulectls_words_and_never_raw_output():
    """Sherlock2's acceptance nit on #347: the fallback line for a state this demo does not know carries no raw output."""
    lines = flow.entry_lines(DEAL, [{"party": "seller", "state": "something_new", "words": "entered, as read"},
                                    {"party": "buyer", "state": "other_new"}], NAMES)
    assert "  Kestrel Print: entered, as read" in lines and "  Maya: other_new" in lines
    assert not any("{" in line or "}" in line for line in lines)
