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
             screens.DISPUTE_RAISED, screens.signed_line("Kestrel Print", "kestrel"),
             screens.signed_line("Kestrel Print", "kestrel", True), screens.sample_note("kestrel"),
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


def _pay_world(monkeypatch, check):
    """open_and_pay with every party and rail step recorded in ``calls``; the check returns ``check``."""
    calls, sealed = [], []
    monkeypatch.delenv("ARD_LIMIT_MSAT", raising=False)
    monkeypatch.setattr(buyer.limits, "unpin", lambda maya: calls.append("unpin"))
    monkeypatch.setattr(buyer, "draft_deal", lambda *a, **k: calls.append("draft") or buyer.Deal("deal-01", "alder", "k", 1000, "o"))
    monkeypatch.setattr(buyer, "send_deal", lambda *a, **k: calls.append("send"))
    monkeypatch.setattr(buyer, "cancel_draft", lambda *a, **k: calls.append("cancel"))
    monkeypatch.setattr(buyer, "check_payment", lambda *a: calls.append("check") or check)
    monkeypatch.setattr(buyer, "pay", lambda *a, **k: calls.append("pay"))

    class Rail:
        SEALED = "simulated"
        checked_invoice = staticmethod(lambda msat: calls.append("invoice") or type("I", (), {"payment_hash": "h"})())
        pay_invoice = staticmethod(lambda inv: calls.append("paid") or type("P", (), {"reference": "r"})())

    class Who:
        name = "maya"

        def sending(self, deal_id, check_id):
            pass

        def approve(self, deal_id, check, choice, said):
            sealed.append((choice, said))
    return calls, sealed, Rail, Who()


def test_nothing_reaches_the_seller_before_the_persons_yes(monkeypatch):
    # evidencebook-skills#289: the payment is checked on the unsent offer and the dialog comes first; a no sends nothing
    # (the unsent offer is cancelled), and a yes sends the offer only then
    calls, sealed, Rail, who = _pay_world(monkeypatch, {"proceed": True, "check_id": "c"})
    a = assessment("GO")
    shown = []

    def ask(answer):
        return lambda q: calls.append("ask") or shown.append(q) or answer
    assert buyer.open_and_pay(None, who, "alder", "k", a, {}, Rail, "Pay?", ask(False), print, simulated=True) is None
    assert calls == ["unpin", "draft", "invoice", "check", "ask", "cancel"]
    assert (shown[0].title, shown[0].text, shown[0].yes) == ("Approve this payment", "Pay?", "Pay")  # no card: a pass
    calls.clear()
    assert buyer.open_and_pay(None, who, "alder", "k", a, {}, Rail, "Pay?", ask(True), print, simulated=True)
    assert calls == ["unpin", "draft", "invoice", "check", "ask", "send", "paid", "pay"]
    assert sealed == []  # a check that passed needs no answer sealed


def test_a_paused_payment_shows_and_seals_the_card(monkeypatch):
    # Sherlock2's ruling on evidencebook#890 (Option A): the card the answer is sealed with is on the screen, in full
    card = "PAUSED FOR YOU\nPay 1,000 msat to Alder?"
    calls, sealed, Rail, who = _pay_world(monkeypatch, {"proceed": False, "check_id": "c", "card": card})
    shown = []
    assert buyer.open_and_pay(None, who, "alder", "k", assessment("GO"), {}, Rail, "Pay?",
                              lambda q: shown.append(q) or "yes", print, simulated=True)
    assert shown[0].text == f"Pay?\n\n{screens.CARD_HEAD}\n{card}"
    assert sealed == [("proceed", f"Approve this payment\n{shown[0].text}\nAnswer: Pay")]


def test_only_a_no_to_a_paused_payment_is_sealed(monkeypatch):
    # #239 finding 11: no answer is never sealed as a decline; a no is the person's hold
    for how, want in (("no", [("hold", "Answer: Cancel")]), ("no_answer", []), ("not_shown", []), (False, [])):
        calls, sealed, Rail, who = _pay_world(monkeypatch, {"proceed": False, "check_id": "c", "card": "C"})
        assert buyer.open_and_pay(None, who, "alder", "k", assessment("GO"), {}, Rail, "Pay?", lambda q: how, print,
                                  simulated=True) is None
        assert calls[-1] == "cancel" and "send" not in calls and "paid" not in calls
        assert [(c, s.rsplit("\n", 1)[1]) for c, s in sealed] == want


def test_a_payment_the_rules_refuse_is_not_put_to_the_person(monkeypatch):
    # a failing NEVER rule (23 to 25) denies: no dialog, nothing sealed as an answer, the unsent offer cancelled
    never = {"id": "r23-secrets-and-authentication", "check": "credential_pattern/1.0.0", "verdict": "fail",
             "reason": "the act carries a credential"}
    calls, sealed, Rail, who = _pay_world(monkeypatch, {"verdict": "deny", "proceed": False, "check_id": "c",
                                                        "rules": {"status": "evaluated", "verdict": "deny", "findings": [never]}})
    with pytest.raises(buyer.pt.Refused, match="refused by your rules, not put to you: the act carries a credential"):
        buyer.open_and_pay(None, who, "alder", "k", assessment("GO"), {}, Rail, "Pay?",
                           lambda q: pytest.fail("asked"), print, simulated=True)
    assert calls == ["unpin", "draft", "invoice", "check", "cancel"] and sealed == []


def test_a_failure_after_the_check_cancels_the_unsent_offer(monkeypatch):
    calls, sealed, Rail, who = _pay_world(monkeypatch, {"proceed": False, "check_id": "c", "card": "C"})

    def broken(q):
        raise RuntimeError("the dialog crashed")
    with pytest.raises(RuntimeError):
        buyer.open_and_pay(None, who, "alder", "k", assessment("GO"), {}, Rail, "Pay?", broken, print, simulated=True)
    assert calls[-1] == "cancel" and "send" not in calls


def test_the_payment_is_counted_as_sent_before_money_moves(monkeypatch):
    # capsulectl checks the rules again at `settle --sent`: a refusal there must come before the rail pays
    calls, sealed, Rail, who = _pay_world(monkeypatch, {"proceed": True, "check_id": "c"})
    who.sending = lambda deal_id, check_id: calls.append("sending")
    buyer.open_and_pay(None, who, "alder", "k", assessment("GO"), {}, Rail, "Pay?", lambda q: "yes", print, simulated=True)
    assert calls.index("sending") < calls.index("paid")


def test_a_failed_payment_is_closed_and_an_unknown_one_stays_in_flight(monkeypatch):
    # the payment is counted as sent before the rail pays: a payment the rail says failed is closed as failed, so it no
    # longer counts against the limit; any other error leaves its outcome unknown, and it stays counted
    import pay
    for error, closed in ((pay.PaymentFailed("status failed"), True), (pay.RailError("exit 1: timeout"), False)):
        calls, sealed, Rail, who = _pay_world(monkeypatch, {"proceed": True, "check_id": "c"})
        who.payment_failed = lambda deal_id, check_id: calls.append("failed")

        def boom(inv, error=error):
            raise error
        monkeypatch.setattr(Rail, "pay_invoice", staticmethod(boom))
        with pytest.raises(pay.RailError):
            buyer.open_and_pay(None, who, "alder", "k", assessment("GO"), {}, Rail, "Pay?", lambda q: "yes", print,
                               simulated=True)
        assert ("failed" in calls) is closed and "cancel" not in calls  # the offer was sent: it is not withdrawn


def test_unsetting_the_limit_removes_the_demos_checker(tmp_path):
    import limits
    ran = []
    maya = type("M", (), {"dir": tmp_path, "run": lambda self, *a: ran.append(a)})()
    limits.unpin(maya)
    assert ran == []  # no limits file of the demo's: the profile is left as it is
    (tmp_path / "spending-limit.json").write_text("{}")
    limits.unpin(maya)
    assert ran == [("profile", "update", "--rules-checker", "")] and not (tmp_path / "spending-limit.json").exists()


def test_the_terminal_shows_the_question_and_returns_its_answer(monkeypatch, capsys):
    import demo
    q = buyer.Question("This order goes over your weekly limit", "line\n\nSaved with your answer:\nCARD", "Buy anyway",
                       "Don't buy")
    run = type("R", (), {"auto": False})()
    for typed, want in (("y", "yes"), ("", "no"), ("n", "no")):
        monkeypatch.setattr("builtins.input", lambda prompt: typed)
        assert demo.Script.answer(run, q) == want
    out = capsys.readouterr().out
    assert "This order goes over your weekly limit\nline\n\nSaved with your answer:\nCARD" in out


def _rules(*findings, verdict="escalate", limit=2000):
    caps = [{"id": "r05-spending-limits#per_purchase", "check": "caps/5.1.0", "verdict": "pass", "limit": limit, "value": 1000},
            {"id": "r05-spending-limits#7d", "check": "caps/5.1.0", "verdict": "pass", "limit": limit, "value": 1000}]
    over = {f["id"]: f for f in findings}
    return {"status": "evaluated", "verdict": verdict, "findings": [over.pop(c["id"], c) for c in caps] + list(over.values())}


WEEKLY_OVER = {"id": "r05-spending-limits#7d", "check": "caps/5.1.0", "verdict": "fail", "limit": 2000, "value": 3000,
               "reason": "the 7-day total with this purchase is over the 7-day limit you set"}
ORDER_OVER = {"id": "r05-spending-limits#per_purchase", "check": "caps/5.1.0", "verdict": "fail", "limit": 2000, "value": 3000}
NEW_MERCHANT = {"id": "r06-new-merchant", "check": "counterparty_seen_before/4.0.0", "verdict": "fail",
                "reason": "no earlier payment to this merchant from this profile"}
ORDINARY = {"id": "r02-ordinary-purchase", "check": "counterparty_seen_before/4.0.0", "verdict": "fail",
            "reason": "no earlier payment to this merchant from this profile"}


def test_the_held_order_question_has_a_layout_for_each_hold():
    import limits
    cases = {
        "weekly only": ([WEEKLY_OVER], "This order goes over your weekly limit",
                        ["Spent this week: 2,000 msat", "With this order: 3,000 msat", "Your weekly limit: 2,000 msat"]),
        "per-order only": ([ORDER_OVER], "This order goes over your per-order limit",
                           ["This order: 3,000 msat", "Your per-order limit: 2,000 msat"]),
        "both limits": ([WEEKLY_OVER, ORDER_OVER], screens.HELD_TITLE,
                        ["Over your per-order limit: this order 3,000 msat, limit 2,000 msat",
                         "Over your weekly limit: 3,000 msat with this order, limit 2,000 msat"]),
        "another rule only": ([NEW_MERCHANT, ORDINARY], screens.HELD_TITLE,
                              ["No earlier payment to this merchant from this profile"]),
        "a limit and another rule": ([WEEKLY_OVER, NEW_MERCHANT], screens.HELD_TITLE,
                                     ["Over your weekly limit: 3,000 msat with this order, limit 2,000 msat",
                                      "No earlier payment to this merchant from this profile"]),
    }
    for name, (findings, title, lines) in cases.items():
        held = limits.read({"verdict": "pause", "rules": _rules(*findings)}, 2000)
        got_title, text = screens.hold_question("badges", 1000, held.limits, held.reasons, held.over_limit, "Alder")
        assert got_title == title, name
        body = text.split("\n")
        assert body[0] == "badges from Alder for 1,000 msat. Nothing has been paid yet.", name
        assert body[1:-1] == lines, name  # every reason, and a DO rule (r02) is not one
        assert body[-1] == screens.HELD_FOOT == "Your answer is saved on the receipt.", name


def test_the_limit_is_read_from_the_sealed_check():
    import limits
    assert limits.read({"verdict": "pass", "rules": _rules(verdict="allow")}, 2000) is None  # within the limit
    # a deny the counterparty's History alone caused: capsulectl asks (pause), so it is a hold
    assert limits.read({"verdict": "pause", "rules": _rules(NEW_MERCHANT, verdict="deny")}, 2000).reasons == [
        "no earlier payment to this merchant from this profile"]
    assert limits.read({"rules": {"status": "not_configured"}}, None) is None  # no limit set
    with pytest.raises(limits.LimitError, match="was not checked"):
        limits.read({"rules": {"status": "not_evaluated", "reason": "the rules checker refused the record"}}, 2000)
    with pytest.raises(limits.LimitError, match="did not apply your spending limit"):
        limits.read({"verdict": "pass", "rules": _rules(verdict="allow", limit=50000)}, 2000)  # the pack's own figure: the file was not read


def test_a_reason_reads_amounts_with_commas_and_units():
    import limits
    # Steven's 2026-11-24 run, #272 item 1: never a bare "2000"
    assert limits.words({"id": "r22-unusual-counterparty-behaviour", "check": "upfront_amount/1.1.0", "verdict": "fail",
                         "reason": "the up-front amount 2000 is above the share limit (25%)"}) == \
        "the up-front amount 2,000 msat is above the share limit"
    assert limits.words(NEW_MERCHANT) == "no earlier payment to this merchant from this profile"
    assert limits.words({"id": "r27-x", "verdict": "fail", "reason": "r27 in 7 days"}) == "r27 in 7 days"


def test_the_limit_comes_from_the_environment(monkeypatch):
    import limits
    monkeypatch.delenv("ARD_LIMIT_MSAT", raising=False)
    assert limits.limit_msat() is None
    monkeypatch.setenv("ARD_LIMIT_MSAT", "2000")
    assert limits.limit_msat() == 2000
    for bad in ("0", "-5", "2k"):
        monkeypatch.setenv("ARD_LIMIT_MSAT", bad)
        with pytest.raises(limits.LimitError):
            limits.limit_msat()
    assert limits.limits_profile(2000) == {"format": "policy-profile/v0", "packs": [{"pack": "asg/everyday", "parameters": {
        "caps": {"caps_minor": {"money.purchase": 2000}, "per_action_minor": {"money.purchase": 2000}}}}]}


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

        def intent(self, *a, **k):
            return "i" * 64
    with pytest.raises(buyer.pt.Refused, match="the offer is withdrawn, nothing was paid"):
        buyer.open_deal(tmp_path, Maya(), "alder", "k", assessment("GO"), {}, lambda *_: None, me="maya")
    assert wire.pending(tmp_path, "alder", "offer") == [] and wire.pending(tmp_path, "alder", "from") == []


# -- stamps on demand (#297) -------------------------------------------------------------------------------------------

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


def _receipt(iat: int) -> str:
    """A COSE_Sign1 witness receipt whose protected header carries CWT claims {6: iat} (label 15)."""
    import base64
    protected = bytes([0xa2, 0x01, 0x26, 0x0f, 0xa1, 0x06, 0x1a]) + iat.to_bytes(4, "big")
    sign1 = bytes([0xd2, 0x84, 0x40 + len(protected)]) + protected + bytes([0xa0, 0xf6, 0x41, 0x00])
    return base64.b64encode(sign1).decode()


def test_the_witness_time_is_the_receipts_own_iat():
    import receipt
    hosted = {"ts_url": "https://witness.agentactioncapsule.org", "receipt": _receipt(1795620316)}
    other = {"ts_url": "https://other.example", "receipt": _receipt(1795600000)}
    assert receipt.witness_time({"witness_receipts": [other, hosted]}) == "2026-11-25T15:25:16Z"
    assert receipt.witness_time({"witness_receipts": [other]}) == ""  # never another witness's time
    assert receipt.witness_time({"witness_receipts": []}) == ""


@pytest.mark.parametrize("verdict,half,receipts,expect", [
    ("VALID", {"status": "verified"}, 1, ["  Signed by both sides: the other side's half verifies (capsulectl deal verify).",
                                          "  Time-stamped by Action State's witness at " + screens.local_time("2026-11-25T15:25:16Z", date=True) + "."]),
    ("VALID", None, 0, ["  The other side's half is not in this copy.",
                        "  Not time-stamped yet: the next checkpoint sends it to Action State's witness."]),
    ("INVALID", {"status": "verified"}, 1, ["  This copy did not verify (capsulectl deal verify: INVALID).",
                                            "  Time-stamped by Action State's witness at " + screens.local_time("2026-11-25T15:25:16Z", date=True) + "."]),
])
def test_signed_by_both_only_when_the_whole_copy_verifies(tmp_path, verdict, half, receipts, expect):
    # Sherlock2's what-confirmation on #242: "Signed by both sides" only when deal verify passes on the whole copy;
    # "Time-stamped" only with a named witness's receipt for the checkpoint the copy rests on, at the witness's time
    import json
    import receipt

    class P:
        def bundle(self, deal_id):
            return tmp_path / "copy.json"

        def verify(self, copy):
            return {"verdict": verdict, "extensions": [{"counterparty_half": half}] if half else []}

        def tmp(self, name):
            return str(tmp_path / name)

        def run(self, *args):
            out = args[args.index("--out") + 1]
            Path(out).write_text(json.dumps({"witness_receipts": [{"ts_url": "https://witness.agentactioncapsule.org",
                                                                   "receipt": _receipt(1795620316)}] * receipts}))
            return {"named_witness_receipts": receipts}
    from pathlib import Path
    assert receipt.proof_lines(P(), "deal-0123456789abcdef") == expect


def test_a_sellers_card_says_its_first_deals_are_sample_history():
    from cast import SAMPLE_DEALS
    for seller, label in (("alder", "Alder Print Co."), ("kestrel", "Kestrel Print")):
        for line in (screens.signed_line(label, seller), screens.signed_line(label, seller, True)):
            assert line.endswith(f"Its first {SAMPLE_DEALS[seller]} deals are sample history the operator made before "
                                 "this run.")
        assert pages.labels(card(), witnessed=True, sample=seller)[-1] == screens.sample_note(seller)
    assert not any("sample history" in x for x in pages.labels(card(), witnessed=True))  # a buyer's card has none


def test_the_sellers_sample_histories_differ_and_neither_falls_below_the_packs_band_minimum():
    """#317 (Steven's ruling): the two cards give a choice, a deeper history against a lower price; Kestrel keeps at
    least the band-history row's k, so its 1,000 msat deal is not limited before deal 1."""
    import yaml

    from cast import SAMPLE_DEALS
    rows = yaml.safe_load((packs.HERE / "pack" / "pack-source.yaml").read_text())["rows"]
    k = next(r for r in rows if r["id"] == "band-history")["params"]["k"]
    assert SAMPLE_DEALS["alder"] > SAMPLE_DEALS["kestrel"] >= k


def test_the_ruling_dialog_takes_the_challenge_window_from_the_adjudicator():
    import adjudicator as adj
    assert f"within {adj.CHALLENGE_DAYS} days" in screens.rule_question("deal-0123456789abcdef", "delivered", "Kestrel Print")


def test_the_receipt_page_is_capsulectls_own(monkeypatch, tmp_path):
    import json
    # #242: the receipt page is `capsulectl deal report --html` (evidencebook#935), with the hosted witness's directory so
    # it says the witness time capsulectl verified; a deal's newest records wait for the checkpoint that covers them
    import receipt
    monkeypatch.setattr(receipt.pages, "home", lambda: tmp_path)
    from pathlib import Path

    class P:
        name = "maya"

        def __init__(self, refusals):
            self.refusals, self.calls, self.waits = list(refusals), [], 0

        def write(self, name, content):
            path = tmp_path / name
            path.write_text(json.dumps(content))
            return str(path)

        def run(self, *args):
            self.calls.append(args)
            if self.refusals:
                raise buyer.pt.Refused(self.refusals.pop(0))
            Path(args[args.index("--html") + 1]).write_text("<html>page</html>")
            return {}

        def wait_checkpoint(self, seconds, say=None):
            self.waits += 1
            return {}
    p = P([])
    page = receipt.receipt_page(p, "Maya", "deal-0123456789abcdef", rail="simulated", seller=False)
    assert page.read_text() == "<html>page</html>"
    assert p.waits == 1, "it stamps and waits for the witness before drawing"
    args = p.calls[0]
    assert args[:4] == ("report", "--deal", "deal-0123456789abcdef", "--html")
    directory = json.loads(Path(args[args.index("--witness-directory") + 1]).read_text())
    assert directory == buyer.pt.witness_directory()

    with pytest.raises(receipt.ReceiptError, match="disk full"):
        receipt.receipt_page(P(["disk full"]), "Maya", "deal-0123456789abcdef", rail="simulated", seller=False)

    class NoWitness(P):
        def wait_checkpoint(self, seconds, say=None):
            raise buyer.pt.Refused("no checkpoint the witness took in time")
    # the witness not taking the stamp in time still draws the page, which then has no witness line
    late = NoWitness([])
    assert receipt.receipt_page(late, "Maya", "deal-0123456789abcdef", rail="simulated", seller=False).exists()
    # and a refusal after that is the receipt's own error
    with pytest.raises(receipt.ReceiptError, match="records after its last checkpoint"):
        receipt.receipt_page(NoWitness(["your deal book of deal-0123456789abcdef has records after its last checkpoint"]),
                             "Maya", "deal-0123456789abcdef", rail="simulated", seller=False)


def test_the_demo_imports_no_python_receipt_module():
    # evidencebook-skills#270 item 1, capsule-viewer#383: the receipt page is capsulectl's, drawn with capsule-viewer's Go
    # receipt package; no demo file (the windows' scripts and the tests included) names the Python package, so neither a
    # plain nor a dynamic import of it is left
    from pathlib import Path
    here, me = Path(__file__).resolve().parents[1], Path(__file__).resolve()
    files = [f for f in here.rglob("*.py") if "vendor" not in f.relative_to(here).parts and f != me]
    assert here / "receipt.py" in files and here / "goose" / "open-windows.py" in files
    assert [f.name for f in files if "capsule_viewer" in f.read_text()] == []


def test_times_show_in_local_time_with_the_zone(monkeypatch):
    # run finding F7 (2026-11-25): a person reads local time; the records keep UTC
    import time
    try:
        with monkeypatch.context() as m:
            m.setenv("TZ", "America/Chicago")
            time.tzset()
            assert screens.local_time("2026-11-25T18:16:32Z") == "12:16:32 CST"
            assert screens.local_time("2026-11-25T18:16:32Z", date=True) == "2026-11-25 12:16:32 CST"
            assert screens.local_time("not a time") == "not a time"
    finally:
        time.tzset()  # after the context put TZ back, so later tests see the restored zone


def _receipt_without_time() -> str:
    """A COSE_Sign1 witness receipt whose protected header carries no CWT claims, so no iat."""
    import base64
    protected = bytes([0xa1, 0x01, 0x26])
    return base64.b64encode(bytes([0xd2, 0x84, 0x40 + len(protected)]) + protected + bytes([0xa0, 0xf6, 0x41, 0x00])).decode()


def test_a_stamped_receipt_without_a_time_still_says_time_stamped(tmp_path):
    # Codex on #305: a receipt that verifies (named_witness_receipts >= 1) but states no iat was stamped; the line must
    # not say "Not time-stamped yet"
    import json
    import receipt

    class P:
        def bundle(self, deal_id):
            return tmp_path / "copy.json"

        def verify(self, copy):
            return {"verdict": "VALID", "extensions": []}

        def tmp(self, name):
            return str(tmp_path / name)

        def run(self, *args):
            out = args[args.index("--out") + 1]
            Path(out).write_text(json.dumps({"witness_receipts": [{"ts_url": "https://witness.agentactioncapsule.org",
                                                                   "receipt": _receipt_without_time()}]}))
            return {"named_witness_receipts": 1}
    from pathlib import Path
    assert receipt.proof_lines(P(), "deal-0123456789abcdef")[-1] == \
        "  Time-stamped by Action State's witness; its receipt states no time."


@pytest.mark.parametrize("raw", [
    b"",                              # empty
    b"\xd2",                          # a tag with nothing after it
    b"\xd2\x84\x4b\xa2\x01",          # a byte string shorter than its length
    b"\xd2\x84\x1a\x01",              # an integer shorter than its size
    b"\x81" * 200 + b"\x00",          # nested too deep
    b"\xd2\x84\x63\xff\xfe\xfd",      # text that is not UTF-8
    b"\xd2\x9f",                      # an indefinite-length array
    b"\xd2\x84\x01\x02\x03\x04",      # the first member is not a byte string
    # a time no clock can show: CWT claims {6: 2**64 - 1}
    b"\xd2\x84\x4d\xa1\x0f\xa1\x06\x1b" + b"\xff" * 8 + b"\xa0\xf6\x41\x00",
])
def test_a_receipt_this_reader_cannot_read_gives_no_time_and_no_error(raw):
    import base64
    import receipt
    hosted = {"ts_url": "https://witness.agentactioncapsule.org", "receipt": base64.b64encode(raw).decode()}
    assert receipt.witness_time({"witness_receipts": [hosted]}) == ""


@pytest.mark.parametrize("role,noted", [("kestrel", True), ("maya", False)])
def test_a_sellers_card_in_words_says_its_first_deals_are_sample_history(monkeypatch, role, noted):
    # the stand-in on #305: screens.sample_note(seller) is said wherever a seller's card is shown, in words as on its page
    import desktop_server as ds

    class P:
        def stamp(self):
            pass

        def card_bundle(self, shared):
            return None
    monkeypatch.setattr(ds, "ROLE", role)
    monkeypatch.setattr(ds, "_own", lambda: (P(), "Kestrel Print" if role == "kestrel" else "Maya"))
    monkeypatch.setattr(ds.flow, "read_card", lambda b: (card(of=13), {"anchor_time": "2026-11-25T18:16:32Z"}, None))
    out = ds.ard_show_card()
    if noted:
        assert screens.sample_note("kestrel") in out, out  # this seller's own count, not the other's
    else:
        assert "sample history" not in out, out


def test_the_tool_timeout_covers_the_longest_call():
    # the stand-in on #305: ard_pay waits for the dialog, the seller's agree, the payment and the delivery; Goose must
    # not cut it off after the money has moved
    import importlib.util
    import desktop_server as ds
    import pay
    spec = importlib.util.spec_from_file_location("open_windows", __import__("pathlib").Path(__file__).parent.parent / "goose" / "open-windows.py")
    ow = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ow)
    assert ow.TOOL_TIMEOUT_S > ds.DIALOG_GIVE_UP_S + 20 + 2 * flow.WAIT_S + pay.INVOICE_WAIT_S + pay.PAY_WAIT_S


def test_a_ruling_stamp_the_witness_took_late_is_sent_again(monkeypatch):
    """#307: a stamp the witness did not take within the foreground bound goes on in the background, and the ruling is
    sent to both parties again once it is taken; a stamp taken in time is sent once."""
    import party as pt

    monkeypatch.setenv("ARD_WITNESS", "public")
    tries = []

    class P:
        def wait_checkpoint(self, seconds):
            tries.append(seconds)
            if len(tries) == 1:
                raise pt.Refused("no checkpoint in 12 s")
            return {"state": "ticked"}
    sent = []
    monkeypatch.setattr(adj.Adjudicator, "party", property(lambda self: P()))
    monkeypatch.setattr(adj.Adjudicator, "_send_ruling", lambda self, case: sent.append(case["deal_id"]))
    case = {"deal_id": "deal-0123456789abcdef", "ruling": {}, "parties": {}}
    assert adj.Adjudicator("home").stamp(case, seconds=12, later=60) is False
    adj.LATER[-1].join(5)
    assert tries == [12, 60] and sent == [case["deal_id"]] * 2
    tries[:] = [0]  # the next wait succeeds at once
    sent.clear()
    assert adj.Adjudicator("home").stamp(case) is True and sent == [case["deal_id"]]


def test_ruling_resends_never_overlap(monkeypatch):
    """#308 review: a background resend and a ruling made in the window write the same wire files; _send_ruling runs
    them one at a time under the adjudicator party's lock."""
    import threading
    import time

    lock, inside, most = threading.RLock(), [0], [0]

    class P:
        _lock = lock
    monkeypatch.setattr(adj.Adjudicator, "party", property(lambda self: P()))

    def rule(self, case, row, value, against):
        inside[0] += 1
        most[0] = max(most[0], inside[0])
        time.sleep(0.05)
        inside[0] -= 1
        return {"file": "ruling.json"}
    monkeypatch.setattr(adj.Adjudicator, "rule", rule)
    monkeypatch.setattr(adj.wire, "send", lambda *a: None)
    case = {"deal_id": "deal-0123456789abcdef", "ruling": {"row": "r", "value": "v", "against": "a"},
            "parties": {"buyer": "maya", "seller": "kestrel"}}
    a = adj.Adjudicator("home")
    threads = [threading.Thread(target=a._send_ruling, args=(case,)) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert most[0] == 1


@pytest.mark.parametrize("wait", [True, False])
def test_a_closing_run_lets_both_sides_take_a_stamped_ruling(monkeypatch, wait):
    """#308 review: a ruling sent again with its stamp, while the run went on or as it closes, is taken by Maya and by
    each seller before the run stops; an interrupted run (wait=False) skips that and still stops everything."""
    import demo

    took, stopped = [], []

    class Agent:
        def stop(self, take_rulings=False):
            if take_rulings:
                took.append("seller")
            stopped.append("seller")
    s = demo.Script.__new__(demo.Script)
    s.home, s.maya, s.agents = "home", object(), {"kestrel": Agent(), "alder": Agent()}
    s.stage = type("St", (), {"close": lambda self: stopped.append("stage")})()
    monkeypatch.setattr(demo.adj, "LATER", [])  # the background stamp already finished
    monkeypatch.setattr(demo.buyer, "deals_from_notes", lambda m: [type("D", (), {"seller": "kestrel"})()])
    monkeypatch.setattr(demo.flow, "enter_rulings", lambda home, p, side, other, say: took.append(f"maya:{other}"))
    s.close(wait=wait)
    assert took == (["maya:kestrel", "seller", "seller"] if wait else [])
    assert stopped == ["seller", "seller", "stage"]


def test_a_stopping_seller_takes_its_rulings_only_after_its_loop_ends(monkeypatch):
    """#308 review: the closing run's last ruling step never runs alongside the agent's own loop."""
    import threading
    import time

    events = []
    agent = flow.SellerAgent.__new__(flow.SellerAgent)
    agent._stop, agent.log, agent._lock = threading.Event(), [], threading.Lock()
    agent.party = type("P", (), {"close": lambda self: events.append("close")})()

    def loop():
        while not agent._stop.is_set():
            time.sleep(0.01)
        time.sleep(0.05)
        events.append("loop ended")
    agent.threads = [threading.Thread(target=loop)]
    agent.threads[0].start()
    monkeypatch.setattr(flow.SellerAgent, "_rulings", lambda self: events.append("rulings"))
    agent.stop(take_rulings=True)
    assert events == ["loop ended", "rulings", "close"]

def test_the_go_line_names_the_amount_not_the_tier_id():
    # PM, 2026-11-25 (#293): a person cannot act on "T2"; the amount comes from the pack's ceiling for the tier
    line = screens.decision_line(assessment("GO", price=2000), None, 10_000)  # T2: under 10,000 msat (pack-source.yaml)
    assert line == "GO: 2,000 msat is within this pack's limit for it (allows deals under 10,000 msat)"
    assert "T2" not in line


def test_the_operator_note_names_each_unchecked_input_and_no_demo():
    # PM's words, settled against #176 (Ethan, 2026-11-18: no "demo" a person sees or an agent can repeat)
    assert screens.OPERATOR_NOTE == (
        "Some inputs were set by the operator and not checked: which marketplace the seller is on, the list of sellers "
        "this pack accepts, who time-stamps the seller's card, and who controls the seller's key.")
    assert "demo" not in screens.OPERATOR_NOTE.lower() and not hasattr(screens, "CLAIMS_NOTE")  # the pack has no such row


def test_the_buyer_skill_carries_pms_lines_on_counts_recommendations_and_limits():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[3] / "skills" / "buy-with-evidence" / "SKILL.md").read_text()
    flat = " ".join(text.split())
    for line in ("never guess a higher or lower number, and never call them failures",
                 "Recommend a seller only after you have assessed every seller that passed its checks",
                 "Nothing in the assessment checks quantity or delivery date: never offer to check them before the payment",
                 "Call the card time-stamped only when the screen says its receipt verifies; otherwise say its time-stamp is "
                 "not checked here.",
                 'Repeat a limit as the tool gives it, never shortened ("at or over", "under")',
                 "The person's budget stays with you: use it only in the assessment and at the pick; the deadline is "
                 "theirs to judge."):
        assert line in flat, line


def test_a_stamp_wait_counts_only_a_checkpoint_it_cut(monkeypatch):
    """main's red ard-demo (16636e5): any checkpoint this wait cut that the witness took covers the records sealed before
    the wait; a checkpoint taken before the wait (an older number) never counts, and one left pending is no failure."""
    import party as pt

    monkeypatch.setenv("ARD_WITNESS", "public")
    w = pt.StampWait()
    assert not w.add({"state": "ticked", "checkpoint": 109, "delivered": [100], "pending": [{"checkpoint": 109}]})
    assert w.first == 109  # 100 was cut before this wait: it covers none of the new records
    assert not w.add({"error": "refused"})
    assert w.add({"state": "ticked", "checkpoint": 110, "delivered": [109], "pending": [{"checkpoint": 110}]})
    w2 = pt.StampWait()
    assert not w2.add({"state": "not_due", "delivered": [109]})  # cut nothing: nothing of this wait was taken
    assert w2.first is None
    monkeypatch.setenv("ARD_WITNESS", "off")
    assert pt.StampWait().add({"state": "ticked", "checkpoint": 3})


def test_an_answer_waits_for_a_taken_stamp_then_goes_without_one(tmp_path, monkeypatch):
    """An answer waits for a stamp the witness took, so the records it carries are timed (main's ard-demo after #315:
    the silent-seller e2e read untimed records); past ANSWER_WAIT_S it goes without one, so a failing witness never
    leaves the adjudicator without an answer (#308's CI: 'no 2 answers' after 300 s)."""
    import party as pt

    sent = []

    class P:
        name = "maya"
        dir = tmp_path

        def wait_checkpoint(self, seconds):
            raise pt.Refused("no checkpoint in 12 s")

        def tmp(self, name):
            return str(tmp_path / name)

        def run(self, *args):
            assert args[0] == "respond"
            return {"outcome": "artifact"}
    monkeypatch.setattr(adj.wire, "pending", lambda home, me, kind: [("deal-0123456789abcdef", tmp_path / "req.json")])
    monkeypatch.setattr(adj, "named_key", lambda home: "k")
    monkeypatch.setattr(adj.wire, "send", lambda home, to, deal_id, kind, f: sent.append(kind))
    clock = [1000.0]
    monkeypatch.setattr(adj.time, "time", lambda: clock[0])
    # within ANSWER_WAIT_S of the request: no answer yet, so the records it would carry get their time first
    assert adj.answer_requests(tmp_path, P(), "maya", "buyer", lambda *_: None) == [] and sent == []
    clock[0] += adj.ANSWER_WAIT_S + 1  # past it: answered without a stamp, never left unanswered
    said = []
    assert adj.answer_requests(tmp_path, P(), "maya", "buyer", said.append) == ["deal-0123456789abcdef"]
    assert sent == ["answer-buyer"] and any("answered without one" in x for x in said)


def test_an_answer_goes_at_once_when_its_stamp_is_taken_and_once_only(tmp_path, monkeypatch):
    """The normal path, and recovery inside ANSWER_WAIT_S: a stamp the witness took lets the answer go that round,
    with no 'without one' line; a round that failed first, then one that succeeded, answers once."""
    import party as pt

    sent, ok = [], [False]

    class P:
        name = "maya"
        dir = tmp_path

        def wait_checkpoint(self, seconds):
            if not ok[0]:
                raise pt.Refused("no checkpoint in 12 s")
            return {"state": "ticked"}

        def tmp(self, name):
            return str(tmp_path / name)

        def run(self, *args):
            return {"outcome": "artifact"}
    pending = [("deal-0123456789abcdef", tmp_path / "req.json")]
    monkeypatch.setattr(adj.wire, "pending", lambda home, me, kind: pending)
    monkeypatch.setattr(adj, "named_key", lambda home: "k")
    monkeypatch.setattr(adj.wire, "send", lambda home, to, deal_id, kind, f: sent.append(kind))
    clock = [1000.0]
    monkeypatch.setattr(adj.time, "time", lambda: clock[0])
    said = []
    assert adj.answer_requests(tmp_path, P(), "maya", "buyer", said.append) == []  # the witness failed: not yet
    first = (tmp_path / "handled" / "deal-0123456789abcdef.adjrequest-seen").read_text()
    clock[0] += 10
    ok[0] = True
    assert adj.answer_requests(tmp_path, P(), "maya", "buyer", said.append) == ["deal-0123456789abcdef"]
    assert (tmp_path / "handled" / "deal-0123456789abcdef.adjrequest-seen").read_text() == first  # kept from round 1
    assert adj.answer_requests(tmp_path, P(), "maya", "buyer", said.append) == []  # answered once only
    assert sent == ["answer-buyer"] and not any("without one" in x for x in said)


@pytest.mark.parametrize("counts,refused", [({"alder": 15, "kestrel": 10}, False), ({"alder": 16, "kestrel": 10}, True),
                                            ({"alder": 15, "kestrel": 11}, True)])
def test_a_seeded_home_is_refused_only_past_each_sellers_own_count(tmp_path, monkeypatch, counts, refused):
    """#319 review: a home whose cards count each seller's own sample deals is left as it is; one deal more on either
    (a run's deal) is refused with the reset message."""
    import seed
    from cast import HELD_FROM

    class Fake:
        def __init__(self, name):
            self.name = name

        def card_bundle(self, shared):
            return self.name

        def close(self):
            pass
    monkeypatch.setattr(seed, "parties", lambda home: {n: Fake(n) for n in ("maya", "alder", "kestrel")})
    monkeypatch.setattr(seed.adj.Adjudicator, "named", lambda self: {})
    monkeypatch.setattr(seed.flow, "read_card", lambda name: (card(of=counts[name], held=counts[name]), {}, None))
    (tmp_path / HELD_FROM).write_text("0")
    said = []
    if refused:
        with pytest.raises(SystemExit, match="already counts deals of a run"):
            seed.seed(tmp_path, say=said.append)
    else:
        seed.seed(tmp_path, say=said.append)
        assert said == ["already seeded: the sample history is made and stamped"]



def test_the_viewer_drift_check_fails_only_when_the_vendored_copy_is_behind():
    # evidencebook-skills#316: a vendored History script older than capsule-viewer's newest ts/v* release fails CI
    import viewer_drift
    tags = ["abc\trefs/tags/ts/v0.25.0", "def\trefs/tags/ts/v0.27.2", "def\trefs/tags/ts/v0.27.2^{}", "x\trefs/tags/go/v0.30.0",
            "y\trefs/tags/ts/v0.27.10"]
    assert viewer_drift.newest(tags) == "0.27.10"
    assert viewer_drift.behind("0.27.2", tags) == "0.27.10"
    assert viewer_drift.behind("0.27.10", tags) is None
    assert viewer_drift.behind("0.25.0", ["refs/tags/ts/v0.25.0"]) is None
    assert viewer_drift.behind("0.25.0", []) is None
    assert viewer_drift.vendored_version() == pages.VIEWER.removeprefix("capsule-viewer-") == "0.27.2"


@pytest.mark.parametrize("result,want,said", [
    ("abc\trefs/tags/ts/v0.27.2\n", 0, "is the newest release (0.27.2)"),
    ("abc\trefs/tags/ts/v0.27.2\nabd\trefs/tags/ts/v0.28.0\n", 1, "0.28.0 is released"),
    ("", 2, "no ts/vX.Y.Z release tag found"),
    ("abc\trefs/tags/go/v0.30.0\n", 2, "no ts/vX.Y.Z release tag found"),
    ("error", 2, "Could not resolve host"),
    ("timeout", 2, "cannot read capsule-viewer's releases"),
])
def test_the_viewer_drift_command_exits_by_what_it_could_compare(monkeypatch, capsys, result, want, said):
    # #320 review: the check passes only after comparing with a release it found; no network is a failure, not a pass
    import subprocess
    import viewer_drift

    def run(*args, **kwargs):
        if result == "error":
            raise subprocess.CalledProcessError(128, args[0], stderr="Could not resolve host")
        if result == "timeout":
            raise subprocess.TimeoutExpired(args[0], 60)
        return subprocess.CompletedProcess(args[0], 0, stdout=result)
    monkeypatch.setattr(viewer_drift.subprocess, "run", run)
    monkeypatch.setattr(viewer_drift, "vendored_version", lambda: "0.27.2")
    assert viewer_drift.main() == want
    out = capsys.readouterr()
    assert said in out.out + out.err
