# SPDX-License-Identifier: Apache-2.0
"""The adjudicator rules with no person (evidencebook-skills#416): its own step checks each case with ``deal ruling
check`` and seals only what the check decides; nothing asks anyone to rule. capsulectl is faked here; the end-to-end
test runs the real one."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

import adjudicator as adj
import flow
import wire
from cast import ADJUDICATOR

DEAL = "deal-0123456789abcdef"
DECISIVE = {"row": "delivered", "against": "seller",
            "decisive": {"against": "seller", "value": "not_met", "record": "d" * 64, "record_id": "rec-1", "seq": 3,
                         "at": "2026-11-26T00:00:00Z", "timed_by": "own_stamp"}}
NEEDS = {"row": "delivered", "against": "seller",
         "needs_person": "the seller's latest statement on row delivered, in a record it signed, says met"}


class FakeParty:
    """The adjudicator's profile: records every capsulectl call and answers ``ruling check`` with ``self.check``."""

    def __init__(self, tmp: Path, check: dict):
        self.calls: list[tuple] = []
        self.check = check
        self.tmpdir = tmp
        self._lock = threading.RLock()
        self.logged: list[str] = []

    def tmp(self, name: str) -> str:
        return str(self.tmpdir / name)

    def run(self, *args):
        self.calls.append(args)
        if args[:2] == ("ruling", "check"):
            return self.check
        if args[0] == "ruling":
            Path(args[args.index("--out") + 1]).write_text("{}")
            time.sleep(0.02)  # wide enough for two threads to overlap if nothing serialised them
            return {"ruling": "r" * 64, "sealed": True, "books": {}}
        raise AssertionError(args)

    def log(self, line: str) -> None:
        self.logged.append(line)

    def wait_checkpoint(self, seconds):
        return {"state": "ticked"}

    def rulings(self) -> list[tuple]:
        return [c for c in self.calls if c[0] == "ruling" and c[1] != "check"]


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("ARD_WITNESS", "off")  # no witness unless a test names one: no background stamp threads
    return tmp_path


def setup_case(home: Path, answers=("buyer", "seller"), asked_ago: float = 5, digest: str | None = None) -> None:
    d = home / "files"
    d.mkdir(exist_ok=True)
    dispute = d / "dispute.json"
    dispute.write_text(json.dumps({"record": {"payload": {"body": {"row": "delivered"}}}}))
    wire.send_json(home, ADJUDICATOR, DEAL, "parties", {"buyer": "maya", "seller": "kestrel"})
    wire.send(home, ADJUDICATOR, DEAL, "dispute", dispute)
    at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - asked_ago))
    wire.send_json(home, ADJUDICATOR, DEAL, "asked", {"at": at, "buyer": "maya", "seller": "kestrel"})
    for side in answers:
        book = {"agreement": {"adjudicator": {"key_id": "k", "rules_digest": digest or adj.rules_digest()}}}
        wire.send_json(home, ADJUDICATOR, DEAL, f"answer-{side}", book)


def adjudicator(home: Path, monkeypatch, check: dict) -> tuple[adj.Adjudicator, FakeParty]:
    p = FakeParty(home, check)
    monkeypatch.setattr(adj.Adjudicator, "party", property(lambda self: p))
    return adj.Adjudicator(home), p


def test_a_decisive_case_is_ruled_on_the_deciding_record_and_sent_with_no_person(home, monkeypatch):
    setup_case(home)
    a, p = adjudicator(home, monkeypatch, DECISIVE)
    assert a.rule_decided() == [DEAL]
    (ruling,) = {c for c in p.rulings()}  # the first seal and the stamp's resend run the same flags
    assert ruling[ruling.index("--decided-by") + 1] == "rec-1"
    assert ruling[ruling.index("--value") + 1] == "not_met" and ruling[ruling.index("--against") + 1] == "seller"
    assert ruling.count("--answer") == 2
    for to in ("maya", "kestrel"):
        assert wire.path(home, to, DEAL, "ruling").is_file()
    case = a.cases()[0]
    assert case["ruling"]["decided_by"] == "rec-1" and case["decision"]["decisive"]["record_id"] == "rec-1"
    calls = len(p.calls)
    assert a.rule_decided() == [] and len(p.calls) == calls  # never ruled or checked again


def test_a_case_the_books_do_not_decide_is_not_ruled_and_keeps_why(home, monkeypatch):
    setup_case(home)
    a, p = adjudicator(home, monkeypatch, NEEDS)
    assert a.rule_decided() == [] and not p.rulings()
    case = a.cases()[0]
    assert case["ruling"] is None and case["decision"]["needs_person"] == NEEDS["needs_person"]
    names = flow.case_names(case)
    lines = flow.ruling_lines(flow.Case(DEAL, "delivered", decision=case["decision"]), names)
    assert lines == [f"This case needs a person: {NEEDS['needs_person']}. Nothing is ruled: no person rules cases in this demo."]
    checks = len(p.calls)
    assert a.rule_decided() == [] and len(p.calls) == checks  # the same answers are not checked every round


def test_one_answer_waits_then_is_checked_and_a_later_answer_is_checked_again(home, monkeypatch):
    setup_case(home, answers=("buyer",))
    a, p = adjudicator(home, monkeypatch, NEEDS)
    assert a.rule_decided() == [] and not p.calls  # the seller may still answer
    assert a.rule_decided(now=time.time() + adj.RULE_AFTER_S) == [] and len(p.calls) == 1
    assert p.calls[0].count("--answer") == 1
    wire.send_json(home, ADJUDICATOR, DEAL, "answer-seller", {})  # the seller's answer comes late
    p.check = DECISIVE
    assert a.rule_decided() == [DEAL]
    assert p.rulings()[0].count("--answer") == 2


def test_a_resend_uses_the_answers_the_ruling_was_sealed_on(home, monkeypatch):
    """Codex's plan review: a ruling made on the buyer's answer alone is sent again on that answer, never on a seller's
    answer that came after it (capsulectl refuses a second final ruling that differs)."""
    setup_case(home, answers=("buyer",))
    a, p = adjudicator(home, monkeypatch, DECISIVE)
    assert a.rule_decided(now=time.time() + adj.RULE_AFTER_S) == [DEAL]
    wire.send_json(home, ADJUDICATOR, DEAL, "answer-seller", {})
    wire.path(home, ADJUDICATOR, DEAL, "ruling-sent").unlink()  # its send did not finish
    p.calls.clear()
    assert a.resume() == [DEAL]
    assert [c.count("--answer") for c in p.rulings()] == [1]


def test_a_ruling_not_yet_sent_is_sent_again_every_round_until_it_goes(home, monkeypatch):
    """Codex's round 1: a send that fails, or a window closed before it, is tried again on each round of the loop (not
    once per process), and marked only once it went."""
    setup_case(home)
    a, p = adjudicator(home, monkeypatch, DECISIVE)
    real = wire.send
    fails = [1, 1]

    def send(home_, to, deal_id, kind, f):
        if kind == "ruling" and fails:
            fails.pop()
            raise OSError("disk busy")
        return real(home_, to, deal_id, kind, f)
    monkeypatch.setattr(wire, "send", send)
    assert a.rule_decided() == [DEAL]  # sealed; its first send failed
    assert not wire.path(home, ADJUDICATOR, DEAL, "ruling-sent").is_file() and p.logged
    assert a.resume() == []  # fails again, and is not marked
    assert a.resume() == [DEAL]
    assert all(wire.path(home, to, DEAL, "ruling").is_file() for to in ("maya", "kestrel"))
    assert a.resume() == []  # sent: nothing more
    assert len({c for c in p.rulings()}) == 1  # one ruling, the same flags every time


def test_a_seal_that_failed_is_tried_again(home, monkeypatch):
    """Codex's round 1: a decisive check is never cached as done; a seal that failed is tried again next round."""
    setup_case(home)
    a, p = adjudicator(home, monkeypatch, DECISIVE)
    import party as pt
    real = p.run
    fails = [1]

    def run(*args):
        if args[0] == "ruling" and args[1] != "check" and fails:
            fails.pop()
            raise pt.Refused("the shelf is busy")
        return real(*args)
    p.run = run
    assert a.rule_decided() == [] and a.cases()[0]["ruling"] is None
    assert a.rule_decided() == [DEAL]


def test_a_seal_that_failed_after_sealing_is_retried_on_its_own_answers(home, monkeypatch):
    """Codex's round 2: capsulectl can seal a ruling and then fail; the retry uses the answers and deciding record the
    check decided on, not an answer that came since (capsulectl refuses a second final ruling that differs)."""
    setup_case(home, answers=("buyer",))
    a, p = adjudicator(home, monkeypatch, DECISIVE)
    import party as pt
    real = p.run
    fails = [1]

    def run(*args):
        if args[0] == "ruling" and args[1] != "check" and fails:
            fails.pop()
            p.calls.append(args)
            raise pt.Refused("sealed, but writing --out failed")
        return real(*args)
    p.run = run
    assert a.rule_decided(now=time.time() + adj.RULE_AFTER_S) == []
    wire.send_json(home, ADJUDICATOR, DEAL, "answer-seller", {})  # the seller answers late
    checks = len([c for c in p.calls if c[:2] == ("ruling", "check")])
    assert a.rule_decided() == [DEAL]
    assert len([c for c in p.calls if c[:2] == ("ruling", "check")]) == checks  # not checked again
    assert {c.count("--answer") for c in p.rulings()} == {1}  # every seal and resend on the buyer's answer alone
    assert a.cases()[0]["ruling"]["answers"].keys() == {"buyer"}


def test_the_stamp_is_taken_again_while_the_window_is_open(home, monkeypatch):
    """Codex's round 1: once a background stamp has given up, the next round starts another, so the window keeps
    asking for as long as it is open, as it says; one thread per deal at a time."""
    import party as pt
    setup_case(home)
    a, p = adjudicator(home, monkeypatch, DECISIVE)
    monkeypatch.setenv("ARD_WITNESS", "public")
    tries = []
    gate = threading.Event()

    def wait_checkpoint(seconds):
        tries.append(seconds)
        if len(tries) <= 2:
            raise pt.Refused("no checkpoint")
        gate.wait(5)
        return {"state": "ticked"}
    p.wait_checkpoint = wait_checkpoint
    assert a.rule_decided() == [DEAL]  # the foreground stamp and the first background one fail
    adj.LATER[-1].join(5)
    assert not adj.stamped(home, DEAL)
    a.resume()  # a new background stamp, which waits
    a.resume()  # one already under way: no second
    assert tries.count(adj.LATER_S) == 2
    gate.set()
    adj.LATER[-1].join(5)
    assert adj.stamped(home, DEAL)


def test_a_case_whose_decisive_check_has_no_seal_yet_is_waited_on():
    """Codex's round 1: ard_case waits for a decisive check's seal; only a needs-person result ends the wait."""
    answers = {"buyer": "a", "seller": "b"}
    assert adj.needs_person({**NEEDS, "answers": answers}, answers)
    assert not adj.needs_person({**DECISIVE, "answers": answers}, answers)
    assert not adj.needs_person({**NEEDS, "answers": answers, "retry": True}, answers)
    assert not adj.needs_person({**NEEDS, "answers": {"buyer": "a"}}, answers)


def test_a_stamp_taken_is_marked(home, monkeypatch):
    setup_case(home)
    a, p = adjudicator(home, monkeypatch, DECISIVE)
    monkeypatch.setenv("ARD_WITNESS", "public")
    assert a.rule_decided() == [DEAL]
    assert adj.stamped(home, DEAL)


def test_an_agreement_under_other_rules_is_not_ruled_without_a_person(home, monkeypatch):
    """Codex's plan review: a home made before the rules changed names the old rules' digest; no ruling without a
    person is made under rules the agreement does not name."""
    setup_case(home, digest="0" * 64)
    a, p = adjudicator(home, monkeypatch, DECISIVE)
    assert a.rule_decided() == [] and not p.calls
    assert "names older adjudicator rules" in a.cases()[0]["decision"]["needs_person"]


def test_a_check_capsulectl_could_not_run_is_tried_again(home, monkeypatch):
    setup_case(home)
    a, p = adjudicator(home, monkeypatch, DECISIVE)
    import party as pt
    real = p.run
    fails = [1]

    def run(*args):
        if args[:2] == ("ruling", "check") and fails:
            fails.pop()
            raise pt.Refused("busy")
        return real(*args)
    p.run = run
    assert a.rule_decided() == []
    assert a.cases()[0]["decision"]["retry"]
    assert a.rule_decided() == [DEAL]


def test_two_ruling_steps_at_once_seal_once(home, monkeypatch):
    """Codex's plan review: the window's loop and a terminal run never seal one case twice."""
    setup_case(home)
    a, p = adjudicator(home, monkeypatch, DECISIVE)
    monkeypatch.setenv("ARD_WITNESS", "off")
    got: list[list[str]] = []
    threads = [threading.Thread(target=lambda: got.append(a.rule_decided())) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert sorted(got) == [[], [], [], [DEAL]]
    assert len([c for c in p.calls if c[:2] == ("ruling", "check")]) == 1


def test_the_ruling_and_why_in_sherlock2s_words():
    names = {"buyer": "Maya", "seller": "Kestrel Print"}
    c = flow.Case(DEAL, "delivered", ruling={"ruling": "r" * 64, "value": "not_met", "against": "seller",
                                             "decided_by": "rec-1"},
                  decision=DECISIVE, observed={"rec-1": "150 of 200 badges"})
    assert flow.ruling_lines(c, names)[0] == (
        "Ruled without a person: Kestrel Print stated in its own signed record that the delivery was not met (its record "
        "says 150 of 200 badges). Against Kestrel Print. Either side may challenge it within 7 days. A challenge is "
        "recorded beside the ruling and never replaces it.")
    waiting = flow.ruling_lines(flow.Case(DEAL, "delivered"), names)
    assert waiting[0].startswith("Not ruled yet: ")


def test_the_adjudicator_window_has_no_ruling_tool_and_its_case_tool_seals_nothing(home, monkeypatch):
    """No tool opens a Rule dialog or records a ruling: the window's loop is the only writer (#416)."""
    ds = pytest.importorskip("desktop_server")
    src = Path(ds.__file__).read_text()
    assert "def ard_rule" not in src and "Rule on this case" not in src
    monkeypatch.setenv("ARD_HOME", str(home))
    setup_case(home)
    a, p = adjudicator(home, monkeypatch, DECISIVE)
    monkeypatch.setattr(ds, "_adjudicator", lambda: a)
    monkeypatch.setattr(ds, "CASE_WAIT_S", 0)
    monkeypatch.setattr(adj.Adjudicator, "gather", lambda self, seconds=30: self.cases())
    monkeypatch.setattr(flow, "case_view", lambda raw, names: flow.Case(DEAL, "delivered", decision=raw["decision"]))
    out = ds.ard_case()
    assert "REFUSED" not in out and "not independent of the parties" in out and "Not ruled yet" in out, out
    assert not p.calls  # it neither checked nor sealed anything
