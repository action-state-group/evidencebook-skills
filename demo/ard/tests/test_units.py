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


def card(of=24, held=24, dnh=0, undecided=0, against=0, open_=0, for_=0, split=0, no_finding=0, withdrawn=0):
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
    ev = buyer.Evidence("kestrel", card=card(of=25, held=24, dnh=1, against=1))
    own = buyer.Own(deals=1, settled=1, rulings=[{"deal_id": "deal-0123456789abcdef", "at": "2026-11-25T10:00:00Z",
                                                  "row": "delivered", "value": "not_met", "adverse": True}])
    got = buyer.inputs(ev, 1000, own, datetime(2026, 11, 25, tzinfo=timezone.utc))
    assert got["card"]["disputes"] == {"open": 0, "of": 1, "decided": {"against": 1, "of": 1}}
    assert got["card"]["bands"] == [{"currency": "BTC", "decade": -8, "subjects": 25, "adverse": 1}]
    assert got["own"]["verdicts"] == [{"at": "2026-11-25T10:00:00Z", "adverse": True}]
    assert got["card"]["witness"] == buyer.pt.WITNESS_KEY  # filled in by the operator: no verb gives the receipt


def test_the_card_line_says_the_tally_in_words():
    # Steven's words (#272 item 4)
    assert screens.card_line(card()) == ("24 deals, every one went as agreed. Disputes others raised about it: 0 decided "
                                         "against it, of 0 decided; 0 open.")
    assert screens.card_line(card(of=25, dnh=1, against=1)) == ("25 deals, 1 didn't go as agreed. Disputes others raised "
                                                                "about it: 1 decided against it, of 1 decided; 0 open.")
    assert "0 didn't go as agreed, 1 not final yet" in screens.card_line(card(of=25, undecided=1))
    assert "did not hold" not in screens.card_line(card(of=25, dnh=1)) and "failed" not in screens.card_line(card(dnh=1))


def test_deal_2_reads_no_from_her_own_ruling_and_the_card_is_not_a_second_strike():
    ev = buyer.Evidence("kestrel", card=card(of=25, dnh=1, against=1))
    ruled = {"deal_id": "deal-0123456789abcdef", "at": "2026-11-25T10:00:00Z", "adverse": True}
    line = screens.decision_line(assessment("NO", ["adverse-adjudication", "disputes-against"], [ruled]), ev)
    assert line.startswith("NO: you hold a ruling against this seller (deal 01234567, delivery not met, ruled 2026-11-25).")
    assert "Your rules block a seller you hold a ruling against for 180 days." in line
    assert line.endswith("Its card also counts 1 dispute decided against it, of 1 decided; the card does not say which deal.")


def test_a_second_buyer_sees_limit_from_the_card_alone():
    ev = buyer.Evidence("kestrel", card=card(of=25, dnh=1, against=1))
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
    assert pages.labels(card(of=25, dnh=1, against=1), witnessed=False) == [screens.card_line(card(of=25, dnh=1, against=1))]


@pytest.mark.skipif(not os.environ.get("CAPSULE_ENGINE"), reason="CAPSULE_ENGINE names the evaluator")
def test_a_card_with_no_dispute_tally_limits_and_a_lost_dispute_limits():
    """The demo pack 2.0.0 under capsule-engine: a verified card that carries no dispute tally is not read as clean, and
    one lost dispute limits (Steven's #280 rule); never NO from the card."""
    p = packs.starting()
    now = datetime(2026, 11, 25, tzinfo=timezone.utc)
    clean = buyer.inputs(buyer.Evidence("alder", card=card()), 1000, buyer.Own(), now)
    no_tally = buyer.inputs(buyer.Evidence("alder", card=card()), 1000, buyer.Own(), now)
    no_tally["card"]["disputes"].pop("decided")
    lost = buyer.inputs(buyer.Evidence("kestrel", card=card(of=25, dnh=1, against=1)), 1000, buyer.Own(), now)
    clean["card"].update(first_checkpoint_at="2026-11-24T00:00:00Z", latest_checkpoint_at="2026-11-24T23:00:00Z")
    for d in (no_tally, lost):
        d["card"].update(first_checkpoint_at="2026-11-24T00:00:00Z", latest_checkpoint_at="2026-11-24T23:00:00Z")
    assert buyer.pt.decide(p.path, clean)["verdict"] == "GO"
    for d in (no_tally, lost):
        got = buyer.pt.decide(p.path, d)
        assert got["verdict"] == "LIMIT", got
        row = next(r for r in got["rows"] if r["row"] == "disputes-against")
        assert row["result"] in ("fail", "not_read"), row
