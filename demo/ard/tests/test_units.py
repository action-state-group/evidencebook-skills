# SPDX-License-Identifier: Apache-2.0
"""The demo's own logic that needs no binary: how a /3 card's dispute tally becomes the pack's inputs, the screen's
words for a card and a decision (Sherlock2's what-check on #285), the History page's rows, and the delivery record's
words. capsulectl-deal and capsule-engine are not run here (tests/test_e2e.py runs them)."""
from __future__ import annotations

from datetime import datetime, timezone

import os

import pytest

import adjudicator as adj
import buyer
import flow
import pack as packs
import pages
import screens


def card(of=12, held=12, dnh=0, undecided=0, against=0, open_=0, for_=0, split=0, no_finding=0, withdrawn=0):
    by = {"against": against, "for": for_, "no_finding": no_finding, "open": open_, "split": split, "withdrawn": withdrawn}
    by["of"] = sum(by.values())
    return {"derivation": "standard_history/3", "outcomes": {"of": of, "held": held, "did_not_hold": dnh, "undecided": undecided},
            "bands": [{"currency": "BTC", "decade": -8, "held": held, "did_not_hold": dnh, "undecided": undecided, "of": of}],
            "disputes": {"received": {"by_outcome": by, "of": by["of"]},
                         "raised": {"by_outcome": {k: 0 for k in by}, "of": 0}}}


def assessment(verdict, reasons=(), rulings=(), cap=None, price=1000):
    return buyer.Assessment("kestrel", price, verdict, "T0" if verdict == "LIMIT" else "T2", cap, "demo/ard_admission/2.0.0",
                            "d" * 64, list(reasons), [], "r" * 64, {}, buyer.Own(rulings=list(rulings)))


def test_decided_counts_only_decided_disputes_and_split_is_not_lost():
    d = flow.decided(card(against=1, open_=2, split=1, withdrawn=1))
    assert d == {"open": 2, "of": 5, "decided": {"against": 1, "of": 2}}


def test_the_inputs_carry_the_tally_bands_and_the_own_ruling():
    ev = buyer.Evidence("kestrel", card=card(of=13, held=12, dnh=1, against=1))
    own = buyer.Own(deals=1, settled=1, rulings=[{"deal_id": "deal-0123456789abcdef", "at": "2026-11-25T10:00:00Z",
                                                  "row": "delivered", "value": "not_met", "adverse": True}])
    got = buyer.inputs(ev, 1000, own, datetime(2026, 11, 25, tzinfo=timezone.utc))
    assert got["card"]["disputes"] == {"open": 0, "of": 1, "decided": {"against": 1, "of": 1}}
    assert got["card"]["bands"] == [{"currency": "BTC", "decade": -8, "subjects": 13, "adverse": 1}]
    assert got["own"]["verdicts"] == [{"at": "2026-11-25T10:00:00Z", "adverse": True}]
    assert got["card"]["witness"] == buyer.pt.WITNESS_KEY  # filled in by the operator: no verb gives the receipt


def test_the_card_line_says_the_tally_in_words():
    # Steven's words (#272 item 4)
    assert screens.card_line(card()) == ("12 deals, every one went as agreed. Disputes others raised about it: 0 decided "
                                         "against it, of 0 decided; 0 open.")
    assert screens.card_line(card(of=13, dnh=1, against=1)) == ("13 deals, 1 didn't go as agreed. Disputes others raised "
                                                                "about it: 1 decided against it, of 1 decided; 0 open.")
    assert "0 didn't go as agreed, 1 not final yet" in screens.card_line(card(of=13, undecided=1))
    assert "did not hold" not in screens.card_line(card(of=13, dnh=1)) and "failed" not in screens.card_line(card(dnh=1))


def test_deal_2_reads_no_from_her_own_ruling_and_the_card_is_not_a_second_strike():
    ev = buyer.Evidence("kestrel", card=card(of=13, dnh=1, against=1))
    ruled = {"deal_id": "deal-0123456789abcdef", "at": "2026-11-25T10:00:00Z", "adverse": True}
    line = screens.decision_line(assessment("NO", ["adverse-adjudication", "disputes-against"], [ruled]), ev)
    assert line.startswith("NO: you hold a ruling against this seller (deal 01234567, delivery not met, ruled 2026-11-25).")
    assert "Your rules block a seller you hold a ruling against for 180 days." in line
    assert line.endswith("Its card also counts 1 dispute decided against it, of 1 decided; the card does not say which deal.")


def test_a_second_buyer_sees_limit_from_the_card_alone():
    ev = buyer.Evidence("kestrel", card=card(of=13, dnh=1, against=1))
    line = screens.decision_line(assessment("LIMIT", ["disputes-against"], cap=10), ev)
    assert line == ("LIMIT: a dispute about this seller was decided against it (1 of 1 decided); this pack limits any lost "
                    "dispute. At this limit the pack allows deals under 10 msat only, so no deal opens at 1,000 msat.")


def test_no_line_a_person_reads_names_the_demo():
    lines = [screens.ADJUDICATOR_INDEPENDENCE, screens.WITNESS_LINE, screens.rule_question("deal-0123456789abcdef", "delivered", "Kestrel Print"),
             screens.DISPUTE_RAISED, screens.signed_line("Kestrel Print"), screens.signed_line("Kestrel Print", True),
             pages.WITNESS_NOTE, adj.RULES_TEXT]
    assert not [s for s in lines if "demo" in s.lower()]


def test_the_ruling_question_scopes_the_challenge():
    q = screens.rule_question("deal-0123456789abcdef", "delivered", "Kestrel Print")
    assert "not met, against Kestrel Print" in q and "not independent of the parties" in q
    assert "Either side may challenge it within 7 days. A challenge is recorded beside the ruling and never replaces it." in q


def test_the_delivery_record_in_words():
    assert buyer.shipped("partial:badges_150_of_200") == "150 of 200 badges"
    assert buyer.shipped("delivered:badges_200_of_200") == "200 of 200 badges"
    assert buyer._observed({"agent_input": {"body": {"act": "delivered", "observed": "partial:badges_150_of_200"}}}) == \
        "partial:badges_150_of_200"


def test_a_history_row_says_capsulectls_statuses_and_derives_no_outcome():
    deal = {"deal": "ab" * 32, "agreed_at": "2026-11-25T09:00:00Z", "role": "provided",
            "amount": {"value": "1", "assetCode": "BTC", "assetScale": 8}, "happened": "stamped_by_both",
            "rows": [{"owed_by": "counterparty", "status": "agreed", "value": "met"},
                     {"owed_by": "holder", "status": "ruled", "value": "not_met"}]}
    view = pages.history_input([deal], name="Kestrel Print", built_at="2026-11-25T10:00:00Z", witnessed=None)
    row = view["rows"][0]
    assert row["asked"] == "Sold" and row["money"] == "from 1 sat (its value band)"
    assert row["outcome"] == "this party's row: ruled, not met; the other party's row: met"
    assert "held" not in row["outcome"] and row["witness"] == {"state": "none"}
    assert pages.labels(card(of=13, dnh=1, against=1), witnessed=False) == [screens.card_line(card(of=13, dnh=1, against=1))]


@pytest.mark.skipif(not os.environ.get("CAPSULE_ENGINE"), reason="CAPSULE_ENGINE names the evaluator")
def test_a_card_with_no_dispute_tally_limits_and_a_lost_dispute_limits():
    """The demo pack 2.0.0 under capsule-engine: a verified card that carries no dispute tally is not read as clean, and
    one lost dispute limits (Steven's #280 rule); never NO from the card."""
    p = packs.starting()
    now = datetime(2026, 11, 25, tzinfo=timezone.utc)
    clean = buyer.inputs(buyer.Evidence("alder", card=card()), 1000, buyer.Own(), now)
    no_tally = buyer.inputs(buyer.Evidence("alder", card=card()), 1000, buyer.Own(), now)
    no_tally["card"]["disputes"].pop("decided")
    lost = buyer.inputs(buyer.Evidence("kestrel", card=card(of=13, dnh=1, against=1)), 1000, buyer.Own(), now)
    clean["card"].update(first_checkpoint_at="2026-11-24T00:00:00Z", latest_checkpoint_at="2026-11-24T23:00:00Z")
    for d in (no_tally, lost):
        d["card"].update(first_checkpoint_at="2026-11-24T00:00:00Z", latest_checkpoint_at="2026-11-24T23:00:00Z")
    assert buyer.pt.decide(p.path, clean)["verdict"] == "GO"
    for d in (no_tally, lost):
        got = buyer.pt.decide(p.path, d)
        assert got["verdict"] == "LIMIT", got
        row = next(r for r in got["rows"] if r["row"] == "disputes-against")
        assert row["result"] in ("fail", "not_read"), row


def test_the_adjudicators_request_is_the_wire_form(monkeypatch):
    # min_freshness is a bare time on the wire (AAC's evidence request); an object there is refused as request_malformed
    r = adj.request_for("deal-0123456789abcdef")
    assert r["derivation"] == "deal_adjudicator_copy/1" and r["subject"] == {"correlation": "deal-0123456789abcdef"}
    assert r["coverage"] == {"min_freshness": "2020-01-01T00:00:00Z"} and len(r["nonce"]) == 32


def _answer(tmp_path, side, own, held):
    import json
    f = tmp_path / f"answer-{side}.json"
    book = {"records": {str(i): r for i, r in enumerate(own)}, "received": {"records": {str(i): r for i, r in enumerate(held)}}}
    f.write_text(json.dumps({"request": {}, "bundle": {"extensions": {"x-deal-v1": {"book": book}}}, "facts": {}}))
    return f


def test_a_case_reads_the_silent_sellers_own_record_from_the_buyers_held_copy(tmp_path):
    import json
    perform = {"payload": {"body": {"act": "delivered", "observed": "partial:badges_150_of_200"}}}
    stmt = {"payload": {"body": {"statements": [{"row": "delivered", "value": "not_met"}]}}}
    dispute = tmp_path / "d.json"
    dispute.write_text(json.dumps({"record": {"payload": {"body": {"row": "delivered"}}}}))
    case = {"deal_id": "deal-0123456789abcdef", "dispute": dispute, "asked_at": "2026-11-25T10:00:00Z", "ruling": None,
            "parties": {"buyer": "maya", "seller": "kestrel"},
            "answers": {"buyer": {"file": _answer(tmp_path, "buyer", [stmt], [perform]), "at": "2026-11-25T10:00:05Z"}}}
    names = flow.case_names(case)
    c = flow.case_view(case, names)
    assert c.row == "delivered" and c.answered == {"buyer": "2026-11-25T10:00:05Z"}
    assert c.deciding == ["Maya's statement on the row: not met",
                          "Kestrel Print's own signed delivery record: 150 of 200 badges"]
    lines = flow.case_lines(c, names)
    assert ("  Kestrel Print: no answer yet (its own copy of its book not received; its records here come from the copy "
            "Maya holds)") in lines
    c.signed.discard("seller")
    assert "  Kestrel Print: no answer yet" in flow.case_lines(c, names)
    assert not [x for x in lines if "demo" in x.lower()]
    c.ruling = {"against": "seller", "value": "not_met", "ruling": "ab" * 32}
    assert flow.case_lines(c, names)[-1] == "  ruling recorded: not met, against Kestrel Print (ruling abababab…)"


def test_nothing_reaches_the_seller_before_the_persons_yes(monkeypatch):
    # evidencebook-skills#289: the dialog comes first; a no sends nothing, and a yes opens the deal only then
    calls = []
    monkeypatch.setattr(buyer, "open_deal", lambda *a, **k: calls.append("open") or buyer.Deal("deal-01", "alder", "k", 1, "o"))
    monkeypatch.setattr(buyer, "check_payment", lambda *a: calls.append("check") or {"proceed": True, "check_id": "c"})
    monkeypatch.setattr(buyer, "pay", lambda *a, **k: calls.append("pay"))

    class Rail:
        SEALED = "simulated"
        checked_invoice = staticmethod(lambda msat: calls.append("invoice") or type("I", (), {"payment_hash": "h"})())
        pay_invoice = staticmethod(lambda inv: calls.append("paid") or type("P", (), {"reference": "r"})())
    who = type("M", (), {"name": "maya"})()
    a = assessment("GO")

    def ask(answer):
        return lambda text: calls.append("ask") or answer
    assert buyer.open_and_pay(None, who, "alder", "k", a, {}, Rail, "Pay?", ask(False), print, simulated=True) is None
    assert calls == ["ask"]
    calls.clear()
    assert buyer.open_and_pay(None, who, "alder", "k", a, {}, Rail, "Pay?", ask(True), print, simulated=True)
    assert calls == ["ask", "open", "invoice", "check", "paid", "pay"]


def test_an_offer_the_seller_did_not_answer_is_withdrawn(monkeypatch, tmp_path):
    # a seller window opened later must not agree to a deal nobody pays (its card would count it undecided)
    import wire
    monkeypatch.setattr(flow, "WAIT_S", 0)

    class Maya:
        name = "maya"

        def offer(self, *a, **k):
            f = tmp_path / "offer.json"
            f.write_text("{}")
            return {"deal_id": "deal-0123456789abcdef", "offer": "o" * 64, "file": str(f)}

        def note(self, *a, **k):
            return {"record_id": "r"}
    with pytest.raises(buyer.pt.Refused, match="the offer is withdrawn, nothing was paid"):
        buyer.open_deal(tmp_path, Maya(), "alder", "k", assessment("GO"), {}, lambda *_: None, me="maya")
    assert wire.pending(tmp_path, "alder", "offer") == [] and wire.pending(tmp_path, "alder", "from") == []


# -- stamps on demand (#297) -------------------------------------------------------------------------------------------

def test_taken_means_the_witness_took_the_newest_checkpoint(monkeypatch):
    import party as pt

    monkeypatch.setenv("ARD_WITNESS", "public")
    assert pt.taken({"state": "ticked", "checkpoint": 9, "delivered": [9], "pending": [{"checkpoint": 4}]})
    assert not pt.taken({"state": "ticked", "checkpoint": 9, "delivered": [4], "pending": [{"checkpoint": 9}]})
    assert not pt.taken({"state": "ticked", "checkpoint": 9})  # no delivery list: not taken
    assert not pt.taken({"state": "not_due", "delivered": [9]})
    assert not pt.taken({"error": "refused"})
    assert pt.taken({"state": "ticked", "checkpoint": 9, "witness": "not_configured"})
    monkeypatch.setenv("ARD_WITNESS", "off")
    assert pt.taken({"state": "ticked", "checkpoint": 9})


def test_add_witness_names_the_hosted_witness_once(tmp_path, monkeypatch):
    import party as pt

    monkeypatch.setenv("ARD_WITNESS", "public")
    p = pt.Party(tmp_path, "seller")
    prof = p.dir / ".config" / "capsule" / "profiles" / f"{p.profile}.yaml"
    prof.parent.mkdir(parents=True)
    prof.write_text("name: x\ncheckpoint:\n    signing:\n        file: k\ncadence:\n  interval: 1m\n")
    p.add_witness()
    p.add_witness()
    text = prof.read_text()
    assert text.count(f"endpoint: {pt.WITNESS_URL}") == 1 and text.count(f"public_key: {pt.WITNESS_KEY}") == 1
    assert text.index("checkpoint:") < text.index("endpoint:") < text.index("signing:")
    prof.write_text("name: x\n")
    with pytest.raises(pt.Refused):
        p.add_witness()


def test_a_seller_agent_waits_for_the_minute_its_sample_deals_count_held(tmp_path, monkeypatch):
    import time

    from cast import HELD_FROM

    slept = []
    monkeypatch.setattr(time, "sleep", slept.append)
    agent = flow.SellerAgent.__new__(flow.SellerAgent)
    agent.home, agent.label, agent.log = tmp_path, "Kestrel Print", []
    agent._lock = __import__("threading").Lock()
    agent.wait_sample_held()  # no seed file: no wait
    (tmp_path / HELD_FROM).write_text(str(int(time.time()) - 5))
    agent.wait_sample_held()  # past: no wait
    assert slept == []
    (tmp_path / HELD_FROM).write_text(str(int(time.time()) + 30))
    agent.wait_sample_held()
    assert len(slept) == 1 and 25 < slept[0] <= 31


def test_a_sample_deals_window_ends_at_the_seeds_whole_second():
    """seed.sample_deal hands offer ``window_end - int(now)`` seconds; offer writes now plus that, cut to the second:
    the deal's window ends exactly at window_end (or a second later), never before the seed's own check."""
    from datetime import timedelta

    import party as pt

    window_end = 1_795_620_090
    for frac in (0.0, 0.2, 0.7, 0.999):
        now = datetime.fromtimestamp(1_795_620_010 + frac, tz=timezone.utc)
        left = window_end - int(now.timestamp())
        end = datetime.strptime(pt._iso(now + timedelta(seconds=left)), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        assert end.timestamp() == window_end, frac


def test_a_stamp_is_tried_again_only_with_time_left(monkeypatch):
    import party as pt

    monkeypatch.setenv("ARD_WITNESS", "public")
    clock = [0.0]
    monkeypatch.setattr(pt.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(pt.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + s))
    p = pt.Party.__new__(pt.Party)
    p.name, tries = "x", []

    def slow_refused():
        tries.append(clock[0])
        clock[0] += 5  # each try takes 5 s and the witness does not take it
        return {"state": "ticked", "checkpoint": 1, "delivered": []}
    p.stamp = slow_refused
    with pytest.raises(pt.Refused):
        p.wait_checkpoint(12)
    assert tries == [0.0, 6.0] and clock[0] == 12.0  # a third try (at 12 s) would not end by the bound
    clock[0], tries[:] = 0.0, []

    def slower():
        tries.append(clock[0])
        clock[0] += 6
        return {"state": "ticked", "checkpoint": 1, "delivered": []}
    p.stamp = slower
    with pytest.raises(pt.Refused):
        p.wait_checkpoint(12)
    assert tries == [0.0]  # after a 6 s try and the pause, 5 s are left: no second try


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_seed_whose_seller_worker_dies_says_so_and_writes_no_held_file(tmp_path, monkeypatch):
    """A seller is done only when its worker says so: a stream thread that fails to start (any way out but success)
    stops the seed, with no HELD_FROM file and no 'made' line (Codex on #301, 43a34ef)."""
    import threading

    import party as pt
    import seed
    from cast import HELD_FROM, SELLERS

    class Fake:
        def __init__(self, name):
            self.name = name

        def card_bundle(self, shared):
            raise pt.Refused("no card yet")

        def deals(self):
            return []

        def add_witness(self):
            pass

        def stamp(self):
            return {"state": "ticked", "checkpoint": 1, "delivered": [1], "pending": []}

        def close(self):
            pass

    monkeypatch.setattr(seed, "parties", lambda home: {n: Fake(n) for n in (*SELLERS, "maya", *(f"sample-buyer-{s}" for s in SELLERS))})
    monkeypatch.setattr(seed.adj.Adjudicator, "named", lambda self: {})
    monkeypatch.setattr(seed, "sample_deal", lambda *a: "deal")
    real_start, failed = threading.Thread.start, []

    def start(self):
        # Only a deal stream's start fails, the first one whichever seller's it is: the seed's own threads start.
        if getattr(self, "_target", None) is not None and self._target.__name__ == "stream" and not failed:
            failed.append(self)
            raise RuntimeError("can't start new thread")
        return real_start(self)
    monkeypatch.setattr(threading.Thread, "start", start)
    said = []
    with pytest.raises(SystemExit, match="did not finish"):
        seed.seed(tmp_path, say=said.append)
    assert failed and not (tmp_path / HELD_FROM).exists() and not any("made and stamped" in s for s in said)
