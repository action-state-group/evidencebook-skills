# SPDX-License-Identifier: Apache-2.0
"""evidencebook-skills#457: each fact an agent said with no tool line behind it is now in a tool's own output. The
dispute keeps her statement apart from the seller's count; the History cards say they say nothing of her limit; a
reopened seller window lists its deals from its own records; the delivered count comes from each side's own records.
No binary is run."""
from __future__ import annotations

import json
import os

import buyer
import desktop_server as ds
import flow
import screens
import wire

from test_roles import KESTREL, Seller, maya  # noqa: F401  (maya is a fixture)
from test_received import sent  # noqa: F401  (sent is a fixture)


def test_her_dispute_says_not_met_and_the_count_is_the_sellers_record(maya, monkeypatch, sent):  # noqa: F811
    monkeypatch.setattr(buyer, "take_delivery", lambda home, m, deal: "partial:badges_150_of_200")
    monkeypatch.setattr(buyer, "dispute", lambda *a: None)
    monkeypatch.setattr(ds, "dialog_answer", lambda *a, **k: "yes")
    out = ds.ard_dispute("kestrel")
    assert ("Your signed statement says the delivery was not met; it gives no count. The count, 150 of 200 badges "
            "shipped, is Kestrel Print's own delivery record.") in out, out


def test_a_record_that_arrives_while_the_dialog_waits_is_named(maya, monkeypatch, sent):  # noqa: F811
    """Codex on #464: the count is read again after her answer, not from before the dialog."""
    records = iter([None, "partial:badges_150_of_200"])
    monkeypatch.setattr(buyer, "take_delivery", lambda home, m, deal: next(records))
    monkeypatch.setattr(buyer, "dispute", lambda *a: None)
    monkeypatch.setattr(ds, "dialog_answer", lambda *a, **k: "yes")
    out = ds.ard_dispute("kestrel")
    assert "The count, 150 of 200 badges shipped, is Kestrel Print's own delivery record." in out, out


def test_a_dispute_with_no_delivery_record_names_no_count(maya, monkeypatch, sent):  # noqa: F811
    """Codex's plan review: a dispute before any delivery record is allowed, and its answer invents no count."""
    monkeypatch.setattr(buyer, "take_delivery", lambda home, m, deal: None)
    monkeypatch.setattr(buyer, "dispute", lambda *a: None)
    monkeypatch.setattr(ds, "dialog_answer", lambda *a, **k: "yes")
    out = ds.ard_dispute("kestrel")
    assert ("Your signed statement says the delivery was not met; it gives no count. Kestrel Print has sent no "
            "delivery record yet.") in out, out
    assert "of 200" not in out


def test_the_cards_say_they_say_nothing_of_her_limit(tmp_path, monkeypatch):
    """F13: "Both prices are within your 3,000 msat limit", said beside the cards from no tool line."""
    s = type("S", (), {})()
    s.home, s.maya, s.evidence = tmp_path, object(), {}
    s.entries = [{"id": "kestrel", "name": "Kestrel Print"}]
    monkeypatch.setattr(ds, "session", lambda: s)
    monkeypatch.setattr(buyer, "gather", lambda home, m, e: buyer.Evidence("kestrel"))
    monkeypatch.setattr(screens, "check_lines", lambda ev: ["no card"])
    monkeypatch.setattr(ds.limits, "sealed", lambda m: 3000)
    out = ds.ard_show_history()
    assert ds.CARDS_NO_LIMIT in out and "the assessment says whether each price fits it" in out
    monkeypatch.setattr(ds.limits, "sealed", lambda m: None)  # no limit yet: nothing about one
    assert ds.CARDS_NO_LIMIT not in ds.ard_show_history()


# -- the delivered count and a reopened seller window, from each party's own records ---------------------

ACT = {"record": {"payload": {"body": {"act": "delivered", "observed": "partial:badges_150_of_200",
                                       "statements": [{"row": "delivered", "value": "not_met"}]}}}}


class Party:
    """A seller's party with its own folder and no binary."""

    def __init__(self, d):
        self.dir, self._notes = d, []

    def notes(self, kind=""):
        return [n for n in self._notes if not kind or n["type"] == kind]

    def log(self, line):
        pass


def _mark(party, deal_id, kind, at, value=""):
    f = party.dir / "handled" / f"{deal_id}.{kind}"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(value)
    os.utime(f, (at, at))


def test_the_delivery_record_from_the_sellers_own_file_or_her_copy(tmp_path):
    p = Party(tmp_path / "kestrel")
    assert flow.delivery_record(p, KESTREL.deal_id) is None  # none held: no count, no ground
    act = tmp_path / "act.json"
    act.write_text(json.dumps(ACT))
    _mark(p, KESTREL.deal_id, "act", 1, str(act))
    assert flow.delivery_record(p, KESTREL.deal_id) == flow.DeliveryRecord("150 of 200 badges", True)
    her = Party(tmp_path / "maya")
    # her kept note alone gives the count, never a statement
    her._notes.append({"type": flow.DELIVERED_SEEN,
                       "statement": {"deal_id": KESTREL.deal_id, "observed": "partial:badges_150_of_200"}})
    assert flow.delivery_record(her, KESTREL.deal_id) == flow.DeliveryRecord("150 of 200 badges", False)
    # the record itself, as it reached her: what it states too
    wire.write_atomic(wire.path(tmp_path, "maya", KESTREL.deal_id, "act"), json.dumps(ACT).encode())
    assert flow.delivery_record(her, KESTREL.deal_id) == flow.DeliveryRecord("150 of 200 badges", True)
    full = {"record": {"payload": {"body": {"act": "delivered", "observed": "delivered:badges_200_of_200",
                                            "statements": []}}}}
    wire.write_atomic(wire.path(tmp_path, "maya", "deal-1111111111111111", "act"), json.dumps(full).encode())
    assert flow.delivery_record(her, "deal-1111111111111111") == flow.DeliveryRecord("200 of 200 badges", False)
    assert flow.delivery_record(her, "deal-2222222222222222") is None


def test_a_reopened_seller_window_lists_its_deals_from_its_own_records(tmp_path):
    """Re-entry (alder-final.txt:61: "no deal, payment, delivery or dispute yet"): each event from the record that shows
    it, at that record's time; a deal only offered is not "agreed by both"; a held delivery says held; the sample history
    (no offer this agent took) is not listed."""
    s = Seller(tmp_path).agent
    s.party = Party(tmp_path / "kestrel")
    home, ruled, offered, held = tmp_path, KESTREL.deal_id, "deal-2222222222222222", "deal-3333333333333333"
    s._terms = lambda deal_id: "1,000 msat for 200 conference badges"
    act = tmp_path / "act.json"
    act.write_text(json.dumps(ACT))
    for deal_id, at in ((ruled, 100), (held, 300)):
        _mark(s.party, deal_id, "offer", at)
        _mark(s.party, deal_id, "agree", at + 1)
        _mark(s.party, deal_id, "paid-kept", at + 2)
        ref = json.dumps({"amount_msat": 1000, "simulated": True}).encode()
        wire.write_atomic(wire.path(home, "kestrel", deal_id, "ref"), ref)
    _mark(s.party, ruled, "act", 103, str(act))
    wire.write_atomic(wire.path(home, "maya", ruled, "act"), b"{}")  # the record reached her wire
    _mark(s.party, held, "act", 302, str(act))  # sealed, but never sent: no delivered line (Codex on #464)
    _mark(s.party, ruled, "dispute", 104)
    _mark(s.party, ruled, "adjanswer", 105)
    wire.write_atomic(wire.path(home, flow.adj.ADJUDICATOR, ruled, "answer-seller"), b"{}")
    _mark(s.party, held, "held", 303)
    _mark(s.party, offered, "offer", 200)  # the buyer's agreement never came back
    lines = s.earlier()
    words = [line.split("  ", 1)[1] for line in lines]
    assert words == [
        "deal agreed: 1,000 msat for 200 conference badges, signed by both (deal fedcba98)",
        "paid: the buyer says it paid 1,000 msat (simulated rail: no money moved)",
        "delivered to the buyer: 150 of 200 badges (this seller's delivery record says so, and states the delivery "
        "not met)",
        "dispute received: the buyer disputed the delivery of deal fedcba98; the adjudicator asks for this seller's "
        "books, which this seller answers in full",
        "the adjudicator asked for this party's books of deal fedcba98: sent in full (its own book and the copy it holds "
        "of the other side's)",
        "deal agreed: 1,000 msat for 200 conference badges, signed by both (deal 33333333)",
        "paid: the buyer says it paid 1,000 msat (simulated rail: no money moved)",
        "the delivery was held by this seller's own check",
    ], lines
    assert lines[0].startswith(flow._clock(101))


def test_a_reopened_window_marks_where_its_own_lines_start(tmp_path, monkeypatch):
    """#457's hand run: after re-entry Kestrel's agent called the new "advertised" line "later than the current time"."""
    monkeypatch.setattr(flow.SellerAgent, "earlier", lambda self: ["10:00:47 CST  deal agreed: …"])
    for step in ("advertise", "wait_sample_held", "republish"):
        monkeypatch.setattr(flow.SellerAgent, step, lambda self, *a, **k: None)
    monkeypatch.setattr(flow.pt.Party, "exists", property(lambda self: True))
    s = flow.SellerAgent(tmp_path, "kestrel", start=False)
    assert s.log[0] == "10:00:47 CST  deal agreed: …" and s.log[1].endswith(flow.REOPENED)
    monkeypatch.setattr(flow.SellerAgent, "earlier", lambda self: [])
    assert flow.SellerAgent(tmp_path, "kestrel", start=False).log == []  # a first window: no such line


def test_a_new_seller_window_on_a_fresh_home_lists_nothing_earlier(tmp_path):
    s = Seller(tmp_path).agent
    s.party = Party(tmp_path / "alder")
    assert s.earlier() == []


def test_the_ruling_line_in_the_sellers_window_names_its_own_count(tmp_path, monkeypatch):
    """Sherlock2 on #457: "The adjudicator ruled against you: delivery not met (150 of 200 badges delivered). Action
    State's witness time-stamped it at …"; Kestrel's agent had said the witness ruled, for not delivering."""
    from test_roles import AGAINST_SELLER, STAMPED

    class P(Party):
        def report(self, deal_id):
            return {"report": AGAINST_SELLER}

        def card_bundle(self, shared):
            return "card.json"
    s = Seller(tmp_path).agent
    s.party = P(tmp_path / "kestrel")
    s.party._notes.append({"type": flow.RULING_ENTERED, "statement": {"deal_id": KESTREL.deal_id, "stamped_at": STAMPED}})
    act = tmp_path / "act.json"
    act.write_text(json.dumps(ACT))
    _mark(s.party, KESTREL.deal_id, "act", 1, str(act))
    monkeypatch.setattr(ds, "seller", lambda: s)
    monkeypatch.setattr(flow, "read_card", lambda f: ({"outcomes": {"of": 11, "did_not_hold": 1}}, None, None))
    out = ds.ard_seller_activity()
    assert (f"ruling on deal fedcba98: The adjudicator ruled against you on your own signed statement that the delivery "
            f"was not met (150 of 200 badges delivered). Action State's witness time-stamped it at "
            f"{screens.local_time(STAMPED, date=True)}.") in out

