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
    """A seller's agent with no binary: its log and its party's log."""

    def __init__(self, tmp_path):
        self.agent = flow.SellerAgent.__new__(flow.SellerAgent)
        a = self.agent
        a.log, a._lock, a.label, a.name, a.home = [], threading.Lock(), "Kestrel Print", "kestrel", tmp_path
        a.party = type("P", (), {"log": lambda self, line: None})()


def test_each_seller_event_is_one_line_in_its_activity(tmp_path):
    s = Seller(tmp_path).agent
    s.event("dispute received: the buyer disputed the delivery of deal 01234567")
    s.say("delivered to the buyer: 150 of 200 badges")
    assert len(s.log) == 2 and s.log[0].endswith("dispute received: the buyer disputed the delivery of deal 01234567")


def test_a_card_that_fails_its_checks_names_no_key_or_derivation(tmp_path, monkeypatch):
    """Codex's round 1: the failure lines are as plain as the success line."""
    import json
    import party as pt
    rec = {"capsule_id": "c", "key_id": "f" * 64}
    doc = {"records": [rec], "disclosures": {"c": {"agent_input": {"derivation": "standard_history/2"}}},
           "extensions": {"x-standard-history/v0": {"as_of": {"anchor": "a" * 64, "anchor_time": "2026-11-25T22:00:00Z"}}}}
    (tmp_path / "stage" / "cards").mkdir(parents=True)
    (tmp_path / "stage" / "cards" / "kestrel.json").write_text(json.dumps(doc))
    reader = type("R", (), {"tmp": lambda self, name: str(tmp_path / name), "verify": lambda self, f, report_on_fail=False: {"verdict": "VALID"}})()
    for key in ("e" * 64, "f" * 64):
        with pytest.raises(pt.Refused) as got:
            flow.fetch_card(tmp_path, reader, "kestrel", key)
        assert "…" not in str(got.value) and "standard_history" not in str(got.value) and "ffff" not in str(got.value)


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


@pytest.mark.parametrize("leg,rows", [(True, {"paid_as_agreed": "met", "delivered": "not_met"}),
                                      (False, {"delivered": "not_met"})])
def test_a_dispute_says_the_payment_was_met_only_when_it_went_through(tmp_path, monkeypatch, leg, rows):
    """Codex's round 3: a deal agreed but never paid gets no "payment met" in Maya's name."""
    m = FakeMaya()
    m.dispute = lambda deal_id, row: {"file": str(tmp_path / "d.json")}
    monkeypatch.setattr(buyer.wire, "send", lambda *a: None)
    monkeypatch.setattr(buyer.adj, "send_dispute", lambda *a, **k: None)
    if leg:
        buyer.wire.path(tmp_path, KESTREL.seller, KESTREL.deal_id, "paid").write_text("{}")
    buyer.dispute(tmp_path, m, KESTREL, lambda *_: None)
    assert m.statements == [(KESTREL.deal_id, rows)]


def test_mayas_card_check_line_is_plain(monkeypatch, tmp_path):
    """Sherlock2 on #352 (#332): "Alder's card: signed by Alder, and it checks out, as of <local time>"; the
    commitment and checkpoint words stay in her records."""
    read = flow.CardRead(card={"outcomes": {}}, anchor="a" * 64, anchor_time="2026-11-25T22:00:00Z", signer="k",
                         verdict="VALID", witness_status="withheld", file=tmp_path / "c.json")
    monkeypatch.setattr(flow, "fetch_card", lambda home, m, seller, key: read)
    m = FakeMaya()
    m.note = lambda *a, **k: {"record_id": "r"}
    ev = buyer.gather(tmp_path, m, {"id": "north", "name": "North Wind Supply", "commitment": {"key_id": "k"}})
    lines = screens.check_lines(ev)
    assert lines[0] == ("✓ History card: signed by North Wind Supply, and it checks out, as of "
                        + screens.local_time("2026-11-25T22:00:00Z", date=True))
    assert not any("commitment" in line or "checkpoint" in line or "key" in line for line in lines)


def test_the_assessment_rules_note_is_plain():
    assert screens.PACK_NOTE == "example rules for this demo, not a published set"


def test_the_search_lines_in_mayas_chat_are_plain(monkeypatch):
    """Sherlock2 on #352 (#332): "listing checks out" or "listing refused: <reason>", and no check lines."""
    import ard
    import desktop_server as ds
    kept = []
    maya = type("M", (), {"note": lambda self, *a, **k: (kept.append(a), {"record_id": f"r{len(kept)}"})[1],
                          "notes": lambda self, kind: []})()
    s = type("S", (), {"maya": maya})()
    monkeypatch.setattr(ds, "session", lambda: s)
    monkeypatch.setattr(ard, "lookup", lambda *a: [
        {"id": "north", "name": "North Wind Supply", "offer": {"price_msat": 750}, "commitment": {"key_id": "k"},
         "checks": ["the seller's signed terms are the ones the listing names, and the signature checks out"]},
        {"id": "south", "name": "South Shop", "problem": ard.NO_COMMITMENT, "detail": "no evidence-commitment/1",
         "checks": []}])
    out = ds.ard_find_sellers("200 badges by Friday")
    assert "listing checks out" in out and f"listing refused: {ard.NO_COMMITMENT}" in out and len(kept) == 2
    assert "commitment verified" not in out and "signature verifies" not in out and "REFUSED" not in out


# -- the seller's ruling line (evidencebook-skills#360) -------------------------------------------------

AGAINST_SELLER = RULED  # the adjudicator found the delivery not met, against the seller
FOR_SELLER = {"rows": [{"id": "paid_as_agreed", "status": "agreed"},
                       {"id": "delivered", "status": "ruled", "ruling": {"value": "met", "against": "buyer"}}]}


STAMPED = "2026-11-26T05:49:28Z"


def test_a_ruling_against_the_seller_says_the_witness_time_and_no_refund():
    at = screens.local_time(STAMPED, date=True)  # this Mac's zone, as every time the windows show
    assert screens.ruled_for_seller(AGAINST_SELLER, STAMPED) == [
        f"Ruled against you: delivery not met. Time-stamped by Action State's witness at {at}. No refund: this "
        "deal was agreed as not refundable."]
    # the remedy is the one Maya's card shows for the same ruling
    assert screens.ruled_for_buyer(AGAINST_SELLER, "Kestrel Print")[0].endswith(screens.NO_REFUND)


def test_a_ruling_not_stamped_yet_says_so_and_never_a_time():
    assert screens.ruled_for_seller(AGAINST_SELLER, "") == [
        "Ruled against you: delivery not met. Not time-stamped by Action State's witness yet. No refund: this "
        "deal was agreed as not refundable."]


def test_a_ruling_for_the_seller_says_so_with_no_refund_line():
    assert screens.ruled_for_seller(FOR_SELLER, STAMPED) == [
        f"Ruled for you: delivery met. Time-stamped by Action State's witness at "
        f"{screens.local_time(STAMPED, date=True)}."]
    assert screens.ruled_for_seller({"rows": [{"id": "delivered", "status": "agreed"}]}, "") == []
    neither = {"rows": [{"id": "delivered", "status": "ruled", "ruling": {"value": "met", "against": "no one"}}]}
    assert screens.ruled_for_seller(neither, "") == [
        "Ruled: delivery met. Not time-stamped by Action State's witness yet."]  # never "for" or "against" it then


class Notes:
    def __init__(self, notes):
        self._notes = notes

    def notes(self, kind):
        return [{"statement": s} for k, s in self._notes if k == kind]


def test_a_stamp_that_came_after_the_entry_is_the_rulings_time():
    p = Notes([(flow.RULING_ENTERED, {"deal_id": "deal-a", "stamped_at": ""}),
               (flow.RULING_ENTERED, {"deal_id": "deal-b", "stamped_at": "2026-11-26T05:49:28Z"}),
               (flow.RULING_STAMPED, {"deal_id": "deal-a", "stamped_at": "2026-11-26T05:50:31Z"})])
    assert flow.rulings_entered(p) == {"deal-a": "2026-11-26T05:50:31Z", "deal-b": "2026-11-26T05:49:28Z"}
    assert flow.rulings_entered(Notes([(flow.RULING_ENTERED, {"deal_id": "deal-c", "stamped_at": ""})])) == {"deal-c": ""}


def test_seller_activity_shows_each_ruling_line_and_one_report_failure_hides_nothing(tmp_path, monkeypatch):
    """Codex's plan review: a report that fails for one deal still shows the other ruling and the card."""
    import party as pt
    logged = []

    class Party(Notes):
        def report(self, deal_id):
            if deal_id == "deal-1111111111111111":
                raise pt.Refused("not ready")
            return {"report": AGAINST_SELLER}

        def log(self, line):
            logged.append(line)

        def card_bundle(self, shared):
            return "card.json"
    s = Seller(tmp_path).agent
    s.party = Party([(flow.RULING_ENTERED, {"deal_id": "deal-1111111111111111", "stamped_at": ""}),
                     (flow.RULING_ENTERED, {"deal_id": "deal-fedcba9876543210", "stamped_at": ""})])
    s.say("the adjudicator's ruling on deal fedcba98 entered in this party's records")
    monkeypatch.setattr(ds, "seller", lambda: s)
    monkeypatch.setattr(flow, "read_card", lambda f: ({"outcomes": {"of": 11, "did_not_hold": 1}}, None, None))
    out = ds.ard_seller_activity()
    assert "ruling on deal 11111111: its report is not ready yet; ask again in a minute." in out
    assert ("ruling on deal fedcba98: Ruled against you: delivery not met. Not time-stamped by Action State's "
            "witness yet. No refund: this deal was agreed as not refundable.") in out
    assert "now: 11 deals, 1 didn't go as agreed." in out
    assert logged and "not ready" in logged[0]
    # Codex's PR review: a stamp that comes back after the entry shows on the next ask
    s.party._notes.append((flow.RULING_STAMPED, {"deal_id": "deal-fedcba9876543210", "stamped_at": STAMPED}))
    assert (f"ruling on deal fedcba98: Ruled against you: delivery not met. Time-stamped by Action State's "
            f"witness at {screens.local_time(STAMPED, date=True)}. No refund: this deal was agreed as not refundable."
            ) in ds.ard_seller_activity()
