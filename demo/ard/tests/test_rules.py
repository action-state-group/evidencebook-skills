# SPDX-License-Identifier: Apache-2.0
"""The deal check under a person-set spending limit (rules.py): the cut of ``check_and_pay`` matches it, a stub engine
shows the blocking policy, and (with an engine that has ``guard check --limits``) the real Everyday Rules block a
second order."""
from __future__ import annotations

import copy
import json
import os
import stat
import subprocess
import sys
from datetime import datetime, timezone

import pytest

import deals
import goose_node as gn
import rules
from conftest import engine_only
from demo_node import DemoNode
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


def stub_engine(tmp_path, *, caps_fail_when_history: bool = True, other_fail: bool = False, rc: int = 0, err: str = ""):
    """A stand-in `capsule-engine`: records its argv and the limits file, answers from the input's history."""
    log = tmp_path / "engine-calls.jsonl"
    script = tmp_path / "engine"
    script.write_text(f"""#!{sys.executable}
import json, sys
argv = sys.argv[1:]
inp = json.load(sys.stdin)
limits = json.load(open(argv[argv.index("--limits") + 1])) if "--limits" in argv else None
open({str(log)!r}, "a").write(json.dumps({{"argv": argv, "limits": limits, "history": len(inp["history"]),
    "record_type": inp["record"]["agent_input"]["x-deal-v0"]["record_type"]}}) + "\\n")
if {rc!r}:
    sys.stderr.write({err!r}); sys.exit({rc!r})
findings = []
if {caps_fail_when_history!r} and inp["history"]:
    findings.append({{"id": "r05-spending-caps", "check": "caps/5.1.0", "verdict": "fail",
                     "reason": "the 7-day total with this purchase is over the 7-day limit you set", "limit": 2000, "value": 4000}})
if {other_fail!r}:
    findings.append({{"id": "r06-new-merchant", "check": "counterparty_seen_before/4.0.0", "verdict": "fail",
                     "reason": "no earlier payment to this merchant"}})
print(json.dumps({{"schema": "external-check-result/v0", "ruleset_id": "asg/everyday/0.3.8", "definition_digest": "00",
                  "verdict": "escalate" if findings else "allow", "tier": "recomputed", "findings": findings}}))
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


def test_the_first_order_goes_ahead_and_the_second_is_blocked_before_any_payment(tmp_path, monkeypatch):
    engine, log = stub_engine(tmp_path)
    monkeypatch.setenv("CAPSULE_ENGINE", str(engine))
    maya, alder = pair(tmp_path)
    paid = []
    first = deals.run_deal(maya, alder, terms(ITEM, 2000, CURRENCY, "simulated"), "ask", "",
                           pay=lambda: paid.append("1") or "ref-1", limit=2000)
    assert paid == ["1"] and first
    with pytest.raises(rules.RuleBlocked) as blocked:
        deals.run_deal(maya, alder, terms(ITEM, 2000, CURRENCY, "simulated"), "ask", "",
                       pay=lambda: paid.append("2") or "ref-2", limit=2000)
    assert paid == ["1"], "the payment is never called for a blocked order"
    assert "over the 7-day limit you set" in str(blocked.value) and "limit 2,000 msat" in blocked.value.reasons[0]
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert [c["history"] for c in calls] == [0, 1] and all(c["record_type"] == "check" for c in calls)
    assert calls[0]["argv"][:2] == ["guard", "check"] and calls[0]["limits"] == rules.limits_profile(2000)
    notes = [p for _, p in maya.notes(rules.CHECKED)]
    assert [n["blocked"] for n in notes] == [False, True] and notes[1]["limit_msat"] == 2000
    # the blocked order sealed its check and nothing after it: no verdict, no approval, no act
    blocked_deal = [d for d in notes if d["blocked"]][0]["deal_id"]
    kinds = [json.loads(p)["x-deal-v0"]["record_type"] for p in maya.deal_payloads(blocked_deal)]
    assert kinds[-1] == "check" and "action" not in kinds
    maya.close(); alder.close()


def test_a_pack_ask_that_is_not_the_limit_does_not_block(tmp_path, monkeypatch):
    engine, _ = stub_engine(tmp_path, caps_fail_when_history=False, other_fail=True)
    monkeypatch.setenv("CAPSULE_ENGINE", str(engine))
    maya, alder = pair(tmp_path)
    chain = maya.new_deal("deal-00000000000000a5", "buyer", alder.key_id, terms(ITEM, 2000, CURRENCY, "simulated"))
    maya.open_deal(chain, chain.open(AT, "ask"))
    outcome = rules.gate(maya, chain, 2000, AT)
    assert outcome.blocked is False and outcome.asks == ["no earlier payment to this merchant"] and outcome.verdict == "escalate"
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
    with pytest.raises(rules.RuleBlocked) as blocked:
        deals.run_deal(maya, alder, t, "ask", "", pay=lambda: pytest.fail("a blocked order is not paid"), limit=2000)
    assert "limit you set" in blocked.value.reasons[0] and "2,000" in blocked.value.reasons[0] and "4,000" in blocked.value.reasons[0]
    maya.close(); alder.close()
