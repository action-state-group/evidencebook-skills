# SPDX-License-Identifier: Apache-2.0
"""Sherlock2's per-role answers to Steven's 2026-11-25 run (evidencebook-skills #332, #333, #334, #336): Maya's
dispute needs her yes in a dialog; a ruling for her says what it means, refund included; a seller is told each event
in one line; no digest or key id in Maya's chat. No binary is run."""
from __future__ import annotations

import threading

import pytest

import buyer
import desktop_server as ds
import flow
import screens

from test_received import DEAL, FakeMaya, sent  # noqa: F401  (sent is a fixture)

KESTREL = buyer.Deal(deal_id="deal-fedcba9876543210", seller="kestrel", seller_key="k" * 64, price_msat=1000, offer="o",
                     rail="simulated", me="maya")


@pytest.fixture
def maya(tmp_path, monkeypatch):
    m = FakeMaya()
    m.dir = tmp_path
    s = type("S", (), {})()
    s.home, s.maya, s.deals, s.pay_lock = tmp_path, m, [KESTREL], threading.Lock()
    monkeypatch.setattr(ds, "session", lambda: s)
    monkeypatch.delenv("ARD_APPROVAL", raising=False)
    s.paid = {KESTREL.deal_id}  # the deals the seller agreed
    monkeypatch.setattr(buyer, "agreed", lambda home, deal: deal.deal_id in s.paid)
    return s


@pytest.mark.parametrize("how,words", [(ds.NO, "Maya chose Cancel"), (ds.NO_ANSWER, "Maya did not answer in time"),
                                       (ds.NOT_SHOWN, "the dialog could not be shown")])
def test_no_yes_sends_no_dispute(maya, monkeypatch, sent, how, words):  # noqa: F811
    monkeypatch.setattr(buyer, "take_delivery", lambda home, m, deal: "partial:badges_150_of_200")
    disputed = []
    monkeypatch.setattr(buyer, "dispute", lambda *a: disputed.append(a))
    monkeypatch.setattr(ds, "dialog_answer", lambda *a, **k: how)
    out = ds.ard_dispute("kestrel")
    assert f"REFUSED: {words}, so nothing was sent in Maya's name" in out
    assert disputed == [] and sent == [] and maya.maya.statements == []


@pytest.mark.parametrize("observed,record", [
    ("partial:badges_150_of_200", "Its delivery record says 150 of 200 badges were shipped."),
    (None, "Kestrel Print has sent no delivery record yet."),  # a delivery that never came can be disputed too
])
def test_her_yes_sends_the_dispute_once(maya, monkeypatch, observed, record):
    monkeypatch.setattr(buyer, "take_delivery", lambda home, m, deal: observed)
    asked, disputed = [], []

    def dispute(home, m, deal, say):
        disputed.append(deal.deal_id)
        m.note(flow.CASE, {"deal_id": deal.deal_id})
    monkeypatch.setattr(buyer, "dispute", dispute)
    monkeypatch.setattr(ds, "dialog_answer", lambda title, text, yes, no="Cancel": asked.append(text) or "yes")
    assert "Dispute raised on this deal's delivery" in ds.ard_dispute("kestrel")
    assert asked == [f"Dispute your delivery from Kestrel Print? {record} Choosing Dispute sends Kestrel Print and the "
                     "adjudicator your signed statement that the delivery was not met. It moves no money."]
    assert "already disputed" in ds.ard_dispute("kestrel")  # asked again: no second dialog, nothing sent again
    assert disputed == [KESTREL.deal_id] and len(asked) == 1


def test_a_deal_she_said_she_received_is_not_disputed(maya, monkeypatch):
    maya.maya.note(buyer.RECEIVED_SAID, {"deal_id": KESTREL.deal_id})
    monkeypatch.setattr(ds, "dialog_answer", lambda *a, **k: pytest.fail("no dialog"))
    assert "REFUSED: Maya already said she received what she paid for" in ds.ard_dispute("kestrel")


def test_two_open_deals_with_one_seller_are_asked_which(maya, monkeypatch):
    other = buyer.Deal(deal_id="deal-1111111111111111", seller="kestrel", seller_key="k" * 64, price_msat=1000,
                       offer="o", rail="simulated", me="maya")
    maya.deals.append(other)
    maya.paid.add(other.deal_id)
    monkeypatch.setattr(ds, "dialog_answer", lambda *a, **k: pytest.fail("no dialog"))
    assert "ask her which, then pass it as deal" in ds.ard_dispute("kestrel")
    maya.maya.note(flow.CASE, {"deal_id": other.deal_id})  # one of them already disputed: still never a guess
    assert "ask her which, then pass it as deal" in ds.ard_dispute("kestrel")


def test_an_offer_never_paid_is_no_deal_to_dispute(maya, monkeypatch):
    """Claude's round 1: a withdrawn offer comes back from her notes on reopening; it opens no dialog."""
    withdrawn = buyer.Deal(deal_id="deal-2222222222222222", seller="kestrel", seller_key="k" * 64, price_msat=1000,
                           offer="o", rail="simulated", me="maya")
    maya.deals[:] = [withdrawn]
    monkeypatch.setattr(ds, "dialog_answer", lambda *a, **k: pytest.fail("no dialog"))
    assert ("REFUSED: Maya has no deal with Kestrel Print that it agreed to in this run, so there is nothing to dispute"
            in ds.ard_dispute("kestrel"))
    maya.deals.append(KESTREL)  # with a paid one too, the paid one is the only choice, and the dialog names it
    monkeypatch.setattr(buyer, "take_delivery", lambda home, m, deal: None)
    asked = []
    monkeypatch.setattr(ds, "dialog_answer", lambda title, text, yes, no="Cancel": asked.append(text) or "no")
    ds.ard_dispute("kestrel")
    assert asked[0].startswith("Dispute your delivery from Kestrel Print (deal fedcba98)?")


RULED = {"rows": [{"id": "paid_as_agreed", "status": "agreed"},
                  {"id": "delivered", "status": "ruled", "ruling": {"value": "not_met", "against": "seller"}}]}


def test_a_ruling_for_her_says_the_outcome_and_no_refund():
    assert screens.ruled_for_buyer(RULED, "Kestrel Print") == [
        "Ruled for you: delivery not met, against Kestrel Print. No refund: this deal was agreed as not refundable."]
    against_her = {"rows": [{"id": "delivered", "status": "ruled", "ruling": {"value": "not_met", "against": "buyer"}}]}
    assert screens.ruled_for_buyer(against_her, "Kestrel Print") == []  # never "for you" when it is not
    assert screens.ruled_for_buyer({"rows": [{"id": "delivered", "status": "agreed"}]}, "Kestrel Print") == []


class Seller:
    """A seller's agent with no binary: its log, its party's log, a notification hook."""

    def __init__(self, tmp_path, notify=None):
        self.agent = flow.SellerAgent.__new__(flow.SellerAgent)
        a = self.agent
        a.log, a._lock, a.label, a.name, a.home = [], threading.Lock(), "Kestrel Print", "kestrel", tmp_path
        a.party = type("P", (), {"log": lambda self, line: None})()
        if notify is not None:
            a.notify = notify


def test_each_seller_event_is_one_line_and_a_notification(tmp_path):
    shown = []
    s = Seller(tmp_path, notify=lambda label, line: shown.append((label, line))).agent
    s.event("dispute received: the buyer disputed the delivery of deal 01234567")
    s.say("delivered to the buyer: 150 of 200 badges")  # activity, not one of the four events: no notification
    assert len(s.log) == 2 and shown == [("Kestrel Print", "dispute received: the buyer disputed the delivery of deal "
                                                           "01234567")]


def test_a_failing_notification_never_stops_the_seller(tmp_path):
    def broken(label, line):
        raise OSError("no osascript")
    s = Seller(tmp_path, notify=broken).agent
    s.event("paid: the buyer says it paid 1,000 msat")
    assert s.log[-1].endswith("paid: the buyer says it paid 1,000 msat")


def test_a_notification_that_fails_after_it_started_is_logged(tmp_path, monkeypatch):
    """Codex's round 1: osascript that starts and then exits non-zero is logged, never waited on by the seller."""
    monkeypatch.setenv("ARD_HOME", str(tmp_path))
    monkeypatch.setattr(ds, "ROLE", "kestrel")

    class Run:
        returncode = 1

        def __init__(self, *a, **k):
            pass

        def communicate(self, timeout=None):
            return "", "execution error: not allowed"
    monkeypatch.setattr(ds.subprocess, "Popen", Run)
    threads = []
    real = ds.threading.Thread

    def capture(target, daemon):
        t = real(target=target, daemon=daemon)
        threads.append(t)
        return t
    monkeypatch.setattr(ds.threading, "Thread", capture)
    ds.notify("Kestrel Print", "paid: the buyer says it paid 1,000 msat")
    for t in threads:
        t.join(5)
    assert "notification not shown (osascript exit 1): execution error: not allowed" in \
        (tmp_path / "kestrel" / "agent.log").read_text()


def test_a_card_that_fails_its_checks_names_no_key_or_derivation(tmp_path, monkeypatch):
    """Codex's round 1: the failure lines are as plain as the success line."""
    import json
    import party as pt
    rec = {"capsule_id": "c", "key_id": "f" * 64}
    doc = {"records": [rec], "disclosures": {"c": {"agent_input": {"derivation": "standard_history/2"}}},
           "extensions": {"x-standard-history/v0": {"as_of": {"anchor": "a" * 64, "anchor_time": "2026-11-25T22:00:00Z"}}}}
    (tmp_path / "stage" / "cards").mkdir(parents=True)
    (tmp_path / "stage" / "cards" / "kestrel.json").write_text(json.dumps(doc))
    reader = type("R", (), {"tmp": lambda self, name: str(tmp_path / name), "verify": lambda self, f: {"verdict": "VALID"}})()
    for key in ("e" * 64, "f" * 64):
        with pytest.raises(pt.Refused) as got:
            flow.fetch_card(tmp_path, reader, "kestrel", key)
        assert "…" not in str(got.value) and "standard_history" not in str(got.value) and "ffff" not in str(got.value)


def test_the_notification_names_the_sellers_agent_and_the_operator_not_the_demo():
    title = ds.notification_title("Kestrel Print")
    assert title == "Kestrel Print's agent (run by the operator)" and "demo" not in title.lower()


def test_the_deal_agreed_line_reads_the_offer_kept(tmp_path):
    import json
    s = Seller(tmp_path).agent
    f = flow.wire.path(tmp_path, "kestrel", KESTREL.deal_id, "offer")
    f.write_text(json.dumps({"agent_input": {"body": {"terms": {"item": "200 conference badges"},
                                                      "terms_rows": {"rows": [{"owed": {"amount_minor": 1000}}]}}}}))
    assert s._terms(KESTREL.deal_id) == "1,000 msat for 200 conference badges"
    assert s._terms("deal-0000000000000000") == "the buyer's order"


def test_no_key_id_or_digest_in_the_check_lines():
    ev = buyer.Evidence("kestrel")
    ev.ok("commitment", "its signature verifies, and it is the one the seller's entry names")
    line = screens.check_lines(ev)[0]
    assert "…" not in line and "digest" not in line


def test_a_deal_is_agreed_once_the_sellers_agreement_reached_her(tmp_path):
    """Codex's round 2: a paid deal whose payer leg never reached the seller is still hers to dispute."""
    assert not buyer.agreed(tmp_path, KESTREL)
    f = buyer.wire.path(tmp_path, "maya", KESTREL.deal_id, "agree")
    f.write_text("{}")
    assert buyer.agreed(tmp_path, KESTREL) and not buyer.paid(tmp_path, KESTREL)


def test_a_notification_that_hangs_is_killed_and_reaped(tmp_path, monkeypatch):
    monkeypatch.setenv("ARD_HOME", str(tmp_path))
    monkeypatch.setattr(ds, "ROLE", "kestrel")
    calls = []

    class Run:
        returncode = None

        def __init__(self, *a, **k):
            pass

        def communicate(self, timeout=None):
            calls.append(timeout)
            if timeout:
                raise ds.subprocess.TimeoutExpired("osascript", timeout)
            return "", ""

        def kill(self):
            calls.append("kill")
    monkeypatch.setattr(ds.subprocess, "Popen", Run)
    threads = []
    real = ds.threading.Thread
    monkeypatch.setattr(ds.threading, "Thread", lambda target, daemon: threads.append(real(target=target, daemon=daemon))
                        or threads[-1])
    ds.notify("Kestrel Print", "paid")
    for t in threads:
        t.join(5)
    assert calls == [30, "kill", None] and "did not finish in 30 s" in (tmp_path / "kestrel" / "agent.log").read_text()
