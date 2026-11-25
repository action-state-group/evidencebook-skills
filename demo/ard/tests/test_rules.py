# SPDX-License-Identifier: Apache-2.0
"""The deal check under a person-set spending limit (rules.py): the cut of ``check_and_pay`` matches it, a stub engine
shows the blocking policy, and (with an engine that has ``guard check --limits``) the real Everyday Rules block a
second order."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
import subprocess
import sys
from datetime import datetime, timezone

import pytest

import deals
from evidencebook import deal
import goose_node as gn
import rules
import screens
from conftest import engine_only
from demo_node import DemoNode
from evidencebook import deal
from world import CURRENCY, ITEM, terms

AT = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)


def pair(tmp_path):
    maya = DemoNode.open(tmp_path / "maya", operator="ard-maya")
    alder = DemoNode.open(tmp_path / "alder", operator="ard-alder")
    for n in (maya, alder):
        n.note(gn.JOINED, {"operator": n.operator, "key_id": n.key_id})
    deals.admit(alder, maya, reason="test")
    deals.admit(maya, alder, reason="test")
    return maya, alder


def stub_engine(tmp_path, *, caps_fail_when_history: bool = True, other_fail: bool = False, rc: int = 0, err: str = "",
                verdict: str = ""):
    """A stand-in `capsule-engine`: records its argv and the limits file, answers from the input's history."""
    log = tmp_path / "engine-calls.jsonl"
    script = tmp_path / "engine"
    script.write_text(f"""#!{sys.executable}
import json, sys
argv = sys.argv[1:]
inp = json.load(sys.stdin)
limits = json.load(open(argv[argv.index("--limits") + 1])) if "--limits" in argv else None
open({str(log)!r}, "a").write(json.dumps({{"argv": argv, "limits": limits, "history": len(inp["history"]),
    "record_type": inp["record"]["agent_input"]["x-deal-v0"]["record_type"],
    "profile": inp["record"].get("counterparty_profile"), "history_profiles": [h.get("counterparty_profile") for h in inp["history"]]}}) + "\\n")
if {rc!r}:
    sys.stderr.write({err!r}); sys.exit({rc!r})
findings = []
if {caps_fail_when_history!r} and inp["history"]:
    findings.append({{"id": "r05-spending-limits#7d", "check": "caps/5.1.0", "verdict": "fail",
                     "reason": "the 7-day total with this purchase is over the 7-day limit you set", "limit": 2000, "value": 4000}})
if {other_fail!r}:
    findings.append({{"id": "r06-new-merchant", "check": "counterparty_seen_before/4.0.0", "verdict": "fail",
                     "reason": "no earlier payment to this merchant"}})
findings.append({{"id": "r05-spending-limits#per_purchase", "check": "caps/5.1.0", "verdict": "pass", "limit": 2000, "value": 2000}})
print(json.dumps({{"schema": "external-check-result/v0", "ruleset_id": "asg/everyday/0.3.8", "definition_digest": "ab" * 32,
                  "verdict": {verdict!r} or ("escalate" if len(findings) > 1 else "allow"), "tier": "recomputed",
                  "findings": findings}}))
""")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script, log


def test_the_cut_check_and_pay_is_the_reference_method_cut_at_the_payment(tmp_path):
    maya, alder = pair(tmp_path)
    chain = maya.new_deal("deal-00000000000000c1", "buyer", alder.key_id, terms(ITEM, 2000, CURRENCY, "simulated"))
    maya.open_deal(chain, chain.open(AT, "ask"))
    whole = copy.deepcopy(chain).check_and_pay(AT, "ref-1")
    cut = rules.pay_check(chain, AT) + rules.pay_after_check(chain, AT, "ref-1")
    assert [s.record_type for s in cut] == [s.record_type for s in whole] == ["check", "verdict", "approval", "action"]
    for a, b in zip(cut[:3], whole[:3]):  # the check, verdict and approval hold nothing random: byte for byte
        assert a.payload == b.payload and a.digest == b.digest
    act, ref = json.loads(cut[3].payload), json.loads(whole[3].payload)
    for j in (act, ref):
        del j["body"]["reference_commitment"]
        j["x-deal-v0"].pop("commit_alg", None)
    assert act["body"] == ref["body"] and act["x-deal-v0"]["refs"] == ref["x-deal-v0"]["refs"]
    maya.close(); alder.close()


def test_the_limit_is_read_from_the_environment(monkeypatch):
    monkeypatch.delenv("ARD_LIMIT_MSAT", raising=False)
    assert rules.limit_msat() is None
    monkeypatch.setenv("ARD_LIMIT_MSAT", "2000")
    assert rules.limit_msat() == 2000
    for bad in ("0", "-5", "two thousand", "2,000"):
        monkeypatch.setenv("ARD_LIMIT_MSAT", bad)
        with pytest.raises(rules.RulesError):
            rules.limit_msat()


def test_the_limits_file_is_the_engines_policy_profile():
    assert rules.limits_profile(2000) == {"format": "policy-profile/v0", "packs": [{"pack": "asg/everyday", "parameters": {
        "caps": {"caps_minor": {"money.purchase": 2000}, "per_action_minor": {"money.purchase": 2000}}}}]}


def test_the_first_order_goes_ahead_and_the_second_is_held_for_the_persons_ok_and_a_decline_pays_nothing(tmp_path, monkeypatch):
    engine, log = stub_engine(tmp_path)
    monkeypatch.setenv("CAPSULE_ENGINE", str(engine))
    maya, alder = pair(tmp_path)
    paid, asked = [], []
    first = deals.run_deal(maya, alder, terms(ITEM, 2000, CURRENCY, "simulated"), "ask", "",
                           pay=lambda: paid.append("1") or "ref-1", limit=2000, approve=lambda o: asked.append(o) or True)
    assert paid == ["1"] and first and asked == [], "an order inside the limit is not asked about"
    with pytest.raises(rules.RuleHeld) as held:
        deals.run_deal(maya, alder, terms(ITEM, 2000, CURRENCY, "simulated"), "ask", "",
                       pay=lambda: paid.append("2") or "ref-2", limit=2000, approve=lambda o: asked.append(o) or False)
    assert paid == ["1"], "the payment is never called for a declined order"
    assert len(asked) == 1 and asked[0].held and "over the 7-day limit you set" in asked[0].reasons[0]
    assert "declined" in str(held.value) and "limit 2,000 msat" in held.value.reasons[0]
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert [c["history"] for c in calls] == [0, 1] and all(c["record_type"] == "check" for c in calls)
    assert calls[0]["argv"][:2] == ["guard", "check"] and calls[0]["limits"] == rules.limits_profile(2000)
    notes = [p for _, p in maya.notes(rules.CHECKED)]
    assert [(n["held"], n["decision"]) for n in notes] == [(False, ""), (True, "declined")] and notes[1]["limit_msat"] == 2000
    # the declined order sealed its check and nothing after it: no verdict, no approval, no act
    declined = [d for d in notes if d["held"]][0]["deal_id"]
    kinds = [json.loads(p)["x-deal-v0"]["record_type"] for p in maya.deal_payloads(declined)]
    assert kinds[-1] == "check" and "action" not in kinds
    maya.close(); alder.close()


def test_a_held_order_the_person_approves_goes_on_to_the_payment_and_the_approval_is_sealed(tmp_path, monkeypatch):
    engine, _ = stub_engine(tmp_path)
    monkeypatch.setenv("CAPSULE_ENGINE", str(engine))
    maya, alder = pair(tmp_path)
    t = terms(ITEM, 2000, CURRENCY, "simulated")
    deals.run_deal(maya, alder, t, "ask", "", pay=lambda: "ref-1", limit=2000)
    paid = []
    second = deals.run_deal(maya, alder, t, "ask", "", pay=lambda: paid.append("2") or "ref-2", limit=2000, approve=lambda o: True)
    assert paid == ["2"] and second
    notes = [p for _, p in maya.notes(rules.CHECKED)]
    assert (notes[-1]["held"], notes[-1]["decision"]) == (True, "approved")
    # no one to ask (no approve): a held order is declined
    with pytest.raises(rules.RuleHeld):
        deals.run_deal(maya, alder, t, "ask", "", pay=lambda: pytest.fail("not paid"), limit=2000)
    maya.close(); alder.close()


def test_a_pack_ask_that_is_not_the_limit_is_not_held(tmp_path, monkeypatch):
    engine, _ = stub_engine(tmp_path, caps_fail_when_history=False, other_fail=True)
    monkeypatch.setenv("CAPSULE_ENGINE", str(engine))
    maya, alder = pair(tmp_path)
    chain = maya.new_deal("deal-00000000000000a5", "buyer", alder.key_id, terms(ITEM, 2000, CURRENCY, "simulated"))
    maya.open_deal(chain, chain.open(AT, "ask"))
    outcome = rules.gate(maya, chain, 2000, AT)
    assert outcome.held is False and outcome.asks == ["no earlier payment to this merchant"] and outcome.verdict == "escalate"
    maya.close(); alder.close()


def test_an_engine_without_the_limits_flag_is_named_and_nothing_is_paid(tmp_path, monkeypatch):
    engine, _ = stub_engine(tmp_path, rc=2, err="usage: capsule-engine guard check [--pack ID] < external-check-input.json\n")
    monkeypatch.setenv("CAPSULE_ENGINE", str(engine))
    maya, alder = pair(tmp_path)
    paid = []
    with pytest.raises(rules.RulesError, match="capsule-engine#314"):
        deals.run_deal(maya, alder, terms(ITEM, 2000, CURRENCY, "simulated"), "ask", "",
                       pay=lambda: paid.append("1") or "ref-1", limit=2000)
    assert paid == []
    maya.close(); alder.close()


def has_limits_flag() -> bool:
    path = os.environ.get("CAPSULE_ENGINE")
    if not path:
        return False
    run = subprocess.run([path, "guard", "check", "--limits", "/nonexistent"], input="", capture_output=True, text=True, timeout=30)
    return "usage" not in run.stderr and "--limits" not in run.stderr


@engine_only
@pytest.mark.skipif(not has_limits_flag(), reason="CAPSULE_ENGINE has no `guard check --limits` (capsule-engine#314)")
def test_the_real_everyday_rules_block_the_second_order_over_the_limit(tmp_path):
    maya, alder = pair(tmp_path)
    t = terms(ITEM, 2000, CURRENCY, "simulated")
    deals.run_deal(maya, alder, t, "ask", "", pay=lambda: "ref-1", limit=2000)
    with pytest.raises(rules.RuleHeld) as held:
        deals.run_deal(maya, alder, t, "ask", "", pay=lambda: pytest.fail("a declined order is not paid"), limit=2000,
                       approve=lambda o: False)
    assert "limit you set" in held.value.reasons[0] and "2,000" in held.value.reasons[0] and "4,000" in held.value.reasons[0]
    maya.close(); alder.close()


def test_only_acts_in_the_last_seven_days_are_the_history_and_any_failure_of_the_check_is_a_rules_error(tmp_path, monkeypatch):
    from datetime import timedelta

    engine, _ = stub_engine(tmp_path, caps_fail_when_history=False)
    monkeypatch.setenv("CAPSULE_ENGINE", str(engine))
    maya, alder = pair(tmp_path)
    t = terms(ITEM, 2000, CURRENCY, "simulated")
    first = deals.run_deal(maya, alder, t, "ask", "", pay=lambda: "ref-1", limit=2000)
    assert len(rules._paid_acts(maya, "deal-0000000000000000")) == 1
    assert rules._paid_acts(maya, first) == [], "the checked deal's own acts are not history"
    assert rules._paid_acts(maya, "deal-0000000000000000", now=datetime.now(timezone.utc) + timedelta(days=8)) == []
    # an engine that is not there, or answers with something else, is a RulesError (nothing is paid)
    monkeypatch.setenv("CAPSULE_ENGINE", str(tmp_path / "missing"))
    with pytest.raises(rules.RulesError, match="could not run"):
        deals.run_deal(maya, alder, t, "ask", "", pay=lambda: pytest.fail("not paid"), limit=2000)
    garbage = tmp_path / "garbage"
    garbage.write_text(f"#!{sys.executable}\nimport sys; sys.stdin.read(); print('not json')\n")
    garbage.chmod(garbage.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("CAPSULE_ENGINE", str(garbage))
    with pytest.raises(rules.RulesError, match="could not run"):
        deals.run_deal(maya, alder, t, "ask", "", pay=lambda: pytest.fail("not paid"), limit=2000)
    maya.close(); alder.close()


# -- #261: the deal's own records say what the rules said and who approved ----------------------------------------

def _records(node, deal_id: str) -> dict:
    """The deal's x-deal-v0 records by type (the last of each), checked by evidencebook's x-deal-v0 profile checker."""
    payloads = [json.loads(p) for p in node.deal_payloads(deal_id)]
    checker = gn._profile_checker()
    for p in payloads:
        checker.check_record(p)
    checker.check_chain(payloads)
    return {p["x-deal-v0"]["record_type"]: p for p in payloads}


def _local(node, deal_id: str, kind: str) -> dict:
    """The local (unshared) side of the deal's last ``kind`` record: the openings this party keeps."""
    book = node.shelf.open(f"deal/{deal_id}")
    payloads = node.deal_payloads(deal_id)
    i = max(i for i, p in enumerate(payloads) if json.loads(p)["x-deal-v0"]["record_type"] == kind)
    return json.loads(book.opening(book.records()[i].record_id, deal.LOCAL_FIELD).text)


def test_a_held_order_the_person_approves_seals_the_rules_escalation_and_their_approve_click(tmp_path, monkeypatch):
    engine, _ = stub_engine(tmp_path)
    monkeypatch.setenv("CAPSULE_ENGINE", str(engine))
    maya, alder = pair(tmp_path)
    t = terms(ITEM, 2000, CURRENCY, "simulated")
    pay_click = rules.Answer("Pay Alder Print Co. 2,000 msat on the simulated rail: no money moves.", "Pay")
    deals.run_deal(maya, alder, t, "ask", "", pay=lambda: "ref-1", limit=2000, clicked=pay_click)
    second = deals.run_deal(maya, alder, t, "ask", "", pay=lambda: "ref-2", limit=2000, approve=lambda o: True,
                            clicked=pay_click)
    r = _records(maya, second)
    verdict, approval = r["verdict"]["body"], r["approval"]["body"]
    assert verdict["result"] == "pause" and verdict["options"] == ["hold", "proceed"]
    assert verdict["differences"] == [{"question": "safety", "rule": "rules_escalate", "field": "r05_spending_limits_7d"}]
    rs = verdict["rules"]
    assert (rs["status"], rs["verdict"], rs["ruleset_id"], rs["tier"]) == ("evaluated", "escalate", "asg/everyday/0.3.8", "recomputed")
    assert rs["definition_digest"] == "ab" * 32 and rs["checker_sha256"] == hashlib.sha256(engine.read_bytes()).hexdigest()
    assert rs["history"] == {"days": 7, "acts": 1, "complete": True}
    assert all(set(f) <= set(rules.SEALED_FINDING) for f in rs["findings"]), "the engine's words are not sealed"
    assert {"id": "r05-spending-limits#7d", "check": "caps/5.1.0", "verdict": "fail", "limit": 2000, "value": 4000} in rs["findings"]
    # the Approve click answers the hold: the person's words, committed, the opening kept in Maya's own local record
    assert approval["approver"] == "user" and approval["choice"] == "proceed"
    local = _local(maya, second, "approval")
    assert local["said"] == screens.rules_ask(["the 7-day total with this purchase is over the 7-day limit you set "
                                               "(limit 2,000 msat, this order would bring it to 4,000 msat)"]) + "\nAnswer: Approve"
    assert approval["said_commitment"] == deal.commit_text(local["nonces"]["said"], local["said"])
    maya.close(); alder.close()


def test_the_pay_click_with_no_limit_is_the_persons_approval_and_the_rules_stay_not_configured(tmp_path):
    maya, alder = pair(tmp_path)
    click = rules.Answer("Pay Alder Print Co. 2,000 msat on the simulated rail: no money moves.", "Pay")
    deal_id = deals.run_deal(maya, alder, terms(ITEM, 2000, CURRENCY, "simulated"), "ask", "", pay=lambda: "ref-1",
                             clicked=click)
    r = _records(maya, deal_id)
    assert r["verdict"]["body"]["result"] == "pass" and r["verdict"]["body"]["rules"] == {"status": "not_configured"}
    assert r["approval"]["body"]["approver"] == "user"
    assert _local(maya, deal_id, "approval")["said"] == click.shown + "\nAnswer: Pay"
    maya.close(); alder.close()


def test_with_no_limit_and_no_click_the_records_are_todays(tmp_path):
    maya, alder = pair(tmp_path)
    deal_id = deals.run_deal(maya, alder, terms(ITEM, 2000, CURRENCY, "simulated"), "ask", "", pay=lambda: "ref-1")
    r = _records(maya, deal_id)
    assert r["verdict"]["body"]["rules"] == {"status": "not_configured"} and r["approval"]["body"] == {
        "choice": "proceed", "proceed": True, "approver": "standing_intent"}
    maya.close(); alder.close()


def test_a_pack_ask_pauses_the_check_and_the_pay_click_answers_it(tmp_path, monkeypatch):
    """The real Everyday Rules escalate the first order too (a new merchant, a payment that cannot be undone): that is a
    pause, answered by the person's Pay click; with no click (the gate off, tests only) it is the agent card's answer,
    since standing intent approves only a pass."""
    engine, _ = stub_engine(tmp_path, caps_fail_when_history=False, other_fail=True)
    monkeypatch.setenv("CAPSULE_ENGINE", str(engine))
    maya, alder = pair(tmp_path)
    t = terms(ITEM, 2000, CURRENCY, "simulated")
    click = rules.Answer("Pay Alder Print Co. 2,000 msat on the simulated rail: no money moves.", "Pay")
    clicked = _records(maya, deals.run_deal(maya, alder, t, "ask", "", pay=lambda: "ref-1", limit=2000, clicked=click))
    assert clicked["verdict"]["body"]["result"] == "pause" and clicked["approval"]["body"]["approver"] == "user"
    assert clicked["verdict"]["body"]["differences"] == [{"question": "safety", "rule": "rules_escalate", "field": "r06_new_merchant"}]
    unclicked = _records(maya, deals.run_deal(maya, alder, t, "ask", "", pay=lambda: "ref-2", limit=2000))
    assert unclicked["approval"]["body"] == {"choice": "proceed", "proceed": True, "approver": "agent_card"}
    maya.close(); alder.close()


def test_an_allow_is_a_passing_check_with_the_rules_evaluated(tmp_path, monkeypatch):
    engine, _ = stub_engine(tmp_path, caps_fail_when_history=False)
    monkeypatch.setenv("CAPSULE_ENGINE", str(engine))
    maya, alder = pair(tmp_path)
    r = _records(maya, deals.run_deal(maya, alder, terms(ITEM, 2000, CURRENCY, "simulated"), "ask", "", pay=lambda: "ref-1",
                                      limit=2000))
    assert r["verdict"]["body"]["result"] == "pass" and r["verdict"]["body"]["rules"]["verdict"] == "allow"
    assert r["verdict"]["body"]["differences"] == [] and r["approval"]["body"]["approver"] == "standing_intent"
    maya.close(); alder.close()


def test_a_deny_pays_nothing(tmp_path, monkeypatch):
    engine, _ = stub_engine(tmp_path, caps_fail_when_history=False, other_fail=True, verdict="deny")
    monkeypatch.setenv("CAPSULE_ENGINE", str(engine))
    maya, alder = pair(tmp_path)
    with pytest.raises(rules.RulesError, match="deny"):
        deals.run_deal(maya, alder, terms(ITEM, 2000, CURRENCY, "simulated"), "ask", "", pay=lambda: pytest.fail("not paid"),
                       limit=2000, approve=lambda o: True)
    maya.close(); alder.close()


def test_a_history_cut_at_the_cap_is_sealed_as_not_complete(tmp_path, monkeypatch):
    engine, _ = stub_engine(tmp_path, caps_fail_when_history=False)
    monkeypatch.setenv("CAPSULE_ENGINE", str(engine))
    monkeypatch.setattr(rules, "MAX_HISTORY", 0)
    maya, alder = pair(tmp_path)
    t = terms(ITEM, 2000, CURRENCY, "simulated")
    deals.run_deal(maya, alder, t, "ask", "", pay=lambda: "ref-1", limit=2000)
    second = deals.run_deal(maya, alder, t, "ask", "", pay=lambda: "ref-2", limit=2000)
    assert _records(maya, second)["verdict"]["body"]["rules"]["history"] == {"days": 7, "acts": 0, "complete": False}
    maya.close(); alder.close()


def test_the_approve_dialog_s_own_words_are_the_ones_committed(tmp_path, monkeypatch):
    """#265 review: the hold callback returns the Answer it showed, so the commitment is to the dialog's words (the
    dialog replaces a double quote, which AppleScript cannot carry), not to a rebuilt text."""
    engine, _ = stub_engine(tmp_path)
    monkeypatch.setenv("CAPSULE_ENGINE", str(engine))
    maya, alder = pair(tmp_path)
    t = terms(ITEM, 2000, CURRENCY, "simulated")
    deals.run_deal(maya, alder, t, "ask", "", pay=lambda: "ref-1", limit=2000)
    shown = rules.Answer("the words the dialog showed, with 'quotes'", "Approve")
    second = deals.run_deal(maya, alder, t, "ask", "", pay=lambda: "ref-2", limit=2000, approve=lambda o: shown)
    assert _local(maya, second, "approval")["said"] == shown.said()
    maya.close(); alder.close()


def test_a_deny_is_a_refusal_not_a_check_that_could_not_run(tmp_path, monkeypatch):
    engine, _ = stub_engine(tmp_path, caps_fail_when_history=False, other_fail=True, verdict="deny")
    monkeypatch.setenv("CAPSULE_ENGINE", str(engine))
    maya, alder = pair(tmp_path)
    with pytest.raises(rules.RulesRefused):
        deals.run_deal(maya, alder, terms(ITEM, 2000, CURRENCY, "simulated"), "ask", "", pay=lambda: pytest.fail("not paid"),
                       limit=2000)
    maya.close(); alder.close()


def test_the_seller_is_sent_keyed_per_profile_so_one_seller_is_the_same_across_deals(tmp_path, monkeypatch):
    engine, log = stub_engine(tmp_path)
    monkeypatch.setenv("CAPSULE_ENGINE", str(engine))
    maya, alder = pair(tmp_path)
    t = terms(ITEM, 2000, CURRENCY, "simulated")
    deals.run_deal(maya, alder, t, "ask", "", pay=lambda: "ref-1", limit=2000)
    deals.run_deal(maya, alder, t, "ask", "", pay=lambda: "ref-2", limit=2000, approve=lambda o: True)
    first, second = [json.loads(line) for line in log.read_text().splitlines()]
    block = maya.profile_payee(alder.key_id)
    assert block["fp_alg"] == "hmac-sha256-profile-key" and len(block["ids"]["payee"]) == 64
    assert first["profile"] == second["profile"] == block, "the same seller, the same fingerprint in every deal"
    assert second["history_profiles"] == [block], "the earlier paid act names the seller the same way"
    assert maya.profile_payee(alder.key_id) != maya.profile_payee(maya.key_id), "another seller is another fingerprint"
    # the profile key itself never reaches the engine or the sealed note: only the fingerprint does
    secret = deal.profile_key(maya._store_secret).hex()
    sealed = json.dumps([p for _, p in maya.notes(rules.CHECKED)])
    assert secret not in log.read_text() and secret not in sealed and "payee-fp:" not in sealed
    maya.close(); alder.close()


def test_a_seller_id_that_cannot_be_fingerprinted_is_a_rules_error_and_nothing_is_paid(tmp_path, monkeypatch):
    engine, _ = stub_engine(tmp_path)
    monkeypatch.setenv("CAPSULE_ENGINE", str(engine))
    maya, alder = pair(tmp_path)

    def refuse(peer):
        raise deal.NotNormalizable()

    monkeypatch.setattr(maya, "profile_payee", refuse)
    with pytest.raises(rules.RulesError, match="could not run"):
        deals.run_deal(maya, alder, terms(ITEM, 2000, CURRENCY, "simulated"), "ask", "",
                       pay=lambda: pytest.fail("not paid"), limit=2000)
    maya.close(); alder.close()


def test_every_finding_the_engine_returns_is_kept_and_sealed_in_the_note(tmp_path, monkeypatch):
    engine, _ = stub_engine(tmp_path, caps_fail_when_history=False, other_fail=True)
    monkeypatch.setenv("CAPSULE_ENGINE", str(engine))
    maya, alder = pair(tmp_path)
    chain = maya.new_deal("deal-00000000000000a6", "buyer", alder.key_id, terms(ITEM, 2000, CURRENCY, "simulated"))
    maya.open_deal(chain, chain.open(AT, "ask"))
    outcome = rules.gate(maya, chain, 2000, AT)
    assert [(f["id"], f["verdict"]) for f in outcome.findings] == [
        ("r06-new-merchant", "fail"), ("r05-spending-limits#per_purchase", "pass")], "a passing finding is kept too"
    note = [p for _, p in maya.notes(rules.CHECKED)][-1]
    assert note["findings"] == outcome.findings and note["asks"] == ["no earlier payment to this merchant"]
    maya.close(); alder.close()


@engine_only
@pytest.mark.skipif(not has_limits_flag(), reason="CAPSULE_ENGINE has no `guard check --limits` (capsule-engine#314)")
def test_the_real_rules_know_a_seller_paid_before_and_flag_the_repeated_payment(tmp_path):
    maya, alder = pair(tmp_path)
    t = terms(ITEM, 2000, CURRENCY, "simulated")
    # the person's Pay click (#261): an act no one approved is not a decide Capsule, so it does not count as a payment made
    deals.run_deal(maya, alder, t, "ask", "", pay=lambda: "ref-1", limit=5000, clicked=rules.Answer("Pay 2000?", "Pay"))
    chain = maya.new_deal("deal-00000000000000b2", "buyer", alder.key_id, t)
    maya.open_deal(chain, chain.open(AT, "ask"))
    outcome = rules.gate(maya, chain, 5000, AT)
    by_id = {f["id"]: f["verdict"] for f in outcome.findings}
    assert by_id["r02-ordinary-purchase"] == "pass" and by_id["r06-new-merchant"] == "pass", "a seller paid before is not new"
    assert by_id["r27-no-commitment-beyond-task-bounds"] == "fail", "the same act in another deal is flagged"
    assert by_id["r08-non-refundable-or-hard-to-undo"] == "fail" and outcome.held is False
    maya.close(); alder.close()
