# SPDX-License-Identifier: Apache-2.0
"""Steven's 2026-11-25 run with a slow witness (evidencebook-skills#326-#329): the adjudicator asks for books as soon as
a dispute arrives; no raw error reaches a chat; the ruling's entries say which record lacks a stamp; the chat receipt
reads the witness time the way the page does. No binary is run here."""
from __future__ import annotations

import json
import threading
import time

import pytest

import adjudicator as adj
import flow
import party as pt
import receipt
import screens
import wire

DEAL = "deal-0123456789abcdef"


# -- #327: one plain line, said once ---------------------------------------------------------------

def test_a_failure_reads_as_one_plain_line_and_never_carries_raw_output():
    slow = screens.trying_again("entering the adjudicator's ruling", pt.WitnessSlow("Action State's witness took no "
                                                                                     "stamp within 29 s"))
    other = screens.trying_again("entering the adjudicator's ruling",
                                 pt.Refused('maya: no checkpoint in 29 s (last: {"cadence_log": []})'))
    assert slow == ("entering the adjudicator's ruling: waiting for Action State's witness, which is slow to answer; "
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
    assert lines[2] == "  Maya: has not sent its book back yet"


def test_no_book_back_yet_says_so():
    assert flow.entry_lines(DEAL, [], NAMES) == [
        "deal 01234567: no party has sent its book back yet, so neither the ruling's time-stamp nor its entry can be read "
        "from them"]


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
    assert said[1].endswith("waiting for Action State's witness, which is slow to answer; trying again")
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
    assert adj.send_proof_once_witnessed(tmp_path, P(), DEAL, copy, "buyer", lambda *_: None) is False
    assert adj.send_proof_once_witnessed(tmp_path, P(), DEAL, copy, "buyer", lambda *_: None) is False
    assert ticks == [1]  # throttled: not every round
    import os
    os.utime(tmp_path / "handled" / f"{DEAL}.proof-tried", (0, 0))  # PROOF_EVERY_S later
    receipts[0] = [{"receipt": "r"}]
    said = []
    assert adj.send_proof_once_witnessed(tmp_path, P(), DEAL, copy, "buyer", said.append) is True
    assert sent == ["proof-buyer"] and "now time-stamped" in said[0]


# -- #329: the chat receipt's witness line ---------------------------------------------------------

@pytest.mark.parametrize("witnessed,want", [
    ({"status": "verified", "witness": "Action State's witness", "at": "2026-11-25T22:41:33Z"},
     "  Time-stamped by Action State's witness at {t}, as capsulectl verify reported on Maya's own book."),
    ({"status": "withheld", "reason": "no witness receipt is held for this checkpoint yet"},
     "  Not time-stamped yet: Action State's witness has not taken Maya's latest stamp; ask again in a minute."),
    (None, "  Not time-stamped yet: Action State's witness has not taken Maya's latest stamp; ask again in a minute."),
    ({"status": "failed", "reason": "the stamp proof does not verify"},
     "  Not time-stamped: capsulectl verify could not check Action State's witness's receipt for Maya's own book."),
])
def test_the_chat_receipt_says_the_witness_time_as_verify_reported_it(monkeypatch, witnessed, want):
    monkeypatch.setenv("ARD_WITNESS", "public")
    assert receipt.witness_line(witnessed, "Maya") == want.format(t=screens.local_time("2026-11-25T22:41:33Z", date=True))


@pytest.mark.parametrize("verdict,half,expect", [
    ("VALID", {"status": "verified"}, "  Signed by both sides: the other side's half verifies (capsulectl deal verify)."),
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
            ext["witnessed"] = {"status": "withheld"}
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
