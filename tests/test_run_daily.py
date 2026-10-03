"""Unit tests for scripts/run_daily.py's switch resolution (effective_tier/
effective_claim), the recomputed-clause dispatch (recomputed_answer), and the
batched judge-cmd call (judge_batch), the judge-cmd failure handling, and the judge
pin's input (scripts/judge_pin.py). The capsulectl-calling parts of main() are
exercised by tests/fresh_env_outcomes.sh instead.

    python3 -m unittest discover -s tests -p 'test_*.py'
"""
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts" / "judges"))

from capsulectl_calls import EvidenceUnavailable  # noqa: E402
from judge_pin import describe_judge, pin_input  # noqa: E402
from run_daily import (build_report, checked_answer, effective_claim, effective_tier,  # noqa: E402
                       judge, judge_batch, recomputed_answer, valid_verdicts, VERDICTS, VERDICTS_WITH_NA)

ROOT = pathlib.Path(__file__).resolve().parents[1]
WITHIN_FARE_RULES = {
    "id": "policy_compliance.within_fare_rules",
    "tier": "judged",
    "claim": "No change the fare class forbids.",
    "tier_switch": {"flag": "within_fare_rules_recomputed", "tier_when_on": "recomputed"},
}
DONE_IN_FULL = {
    "id": "task_resolution.done_in_full",
    "tier": "judged",
    "claim": "Every part of the request completed; nothing left half-done.",
    "claim_switch": {"flag": "done_in_full_refusal_aware",
                      "claim_when_on": "Every part of the request was either completed or correctly refused."},
}
PLAIN_CLAUSE = {"id": "policy_compliance.confirmed_before_acting", "tier": "judged", "claim": "Explicit yes."}


class EffectiveTier(unittest.TestCase):
    def test_switch_off_keeps_the_declared_tier(self):
        self.assertEqual(effective_tier(WITHIN_FARE_RULES, {"within_fare_rules_recomputed": False}), "judged")

    def test_switch_missing_entirely_keeps_the_declared_tier(self):
        self.assertEqual(effective_tier(WITHIN_FARE_RULES, {}), "judged")

    def test_switch_on_flips_to_the_named_tier(self):
        self.assertEqual(effective_tier(WITHIN_FARE_RULES, {"within_fare_rules_recomputed": True}), "recomputed")

    def test_a_clause_with_no_tier_switch_is_unaffected_by_any_switch(self):
        self.assertEqual(effective_tier(PLAIN_CLAUSE, {"within_fare_rules_recomputed": True}), "judged")


class EffectiveClaim(unittest.TestCase):
    def test_switch_off_keeps_the_declared_claim(self):
        self.assertEqual(effective_claim(DONE_IN_FULL, {"done_in_full_refusal_aware": False}),
                          "Every part of the request completed; nothing left half-done.")

    def test_switch_on_swaps_in_the_refusal_aware_wording(self):
        self.assertEqual(effective_claim(DONE_IN_FULL, {"done_in_full_refusal_aware": True}),
                          "Every part of the request was either completed or correctly refused.")

    def test_a_clause_with_no_claim_switch_is_unaffected(self):
        self.assertEqual(effective_claim(PLAIN_CLAUSE, {"done_in_full_refusal_aware": True}), "Explicit yes.")


class CheckedAnswer(unittest.TestCase):
    def test_default_vocabulary_accepts_the_three_verdicts(self):
        for v in VERDICTS:
            self.assertEqual(checked_answer({"verdict": v})["verdict"], v)

    def test_default_vocabulary_refuses_not_applicable(self):
        with self.assertRaises(EvidenceUnavailable):
            checked_answer({"verdict": "not_applicable"})

    def test_with_na_vocabulary_accepts_not_applicable(self):
        self.assertEqual(checked_answer({"verdict": "not_applicable"}, VERDICTS_WITH_NA)["verdict"], "not_applicable")


class RecomputedAnswer(unittest.TestCase):
    CASE_PAYLOAD = {
        "case": {"benchmark": "tau2", "domain": "airline", "task_id": "1", "trial": 0},
        "agent_interaction": {"messages": [
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "name": "cancel_reservation", "arguments": {"reservation_id": "R1"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": json.dumps(
                {"reservation_id": "R1", "cabin": "economy", "insurance": "no",
                 "created_at": "2024-01-01T00:00:00", "flights": []})},
        ]},
    }

    def test_registered_clause_runs_the_checker(self):
        answer = recomputed_answer(self.CASE_PAYLOAD, WITHIN_FARE_RULES, ROOT)
        self.assertEqual(answer["verdict"], "not_met")  # 2024-01-01 is ancient next to policy.md's current time

    def test_unregistered_clause_fails_closed(self):
        unregistered = dict(WITHIN_FARE_RULES, id="task_resolution.right_change")
        with self.assertRaisesRegex(EvidenceUnavailable, "no registered checker"):
            recomputed_answer(self.CASE_PAYLOAD, unregistered, ROOT)


class JudgeBatch(unittest.TestCase):
    """judge_batch() builds one request carrying every clause and parses the judge
    command's {"answers": {...}} reply -- exercised here against a stand-in
    judge-cmd (not jev_judge.py itself; that is tests/test_jev_judge.py's job)."""

    CASE_PAYLOAD = {"case": {"task_id": "1"}, "agent_interaction": {"messages": [{"role": "user", "content": "hi"}]}}
    CLAUSES = [dict(PLAIN_CLAUSE), dict(WITHIN_FARE_RULES, tier_switch=None)]

    def _fake_judge_cmd(self, answers):
        script = ROOT / "tests" / "_fake_batch_judge.py"
        script.write_text(
            "import json, sys\n"
            f"answers = {answers!r}\n"
            "req = json.load(sys.stdin)\n"
            "json.dump({'answers': {c['id']: answers[c['id']] for c in req['clauses']}}, sys.stdout)\n"
        )
        self.addCleanup(script.unlink)
        return f"{sys.executable} {script}"

    def test_one_call_returns_one_checked_answer_per_clause(self):
        cmd = self._fake_judge_cmd({c["id"]: {"verdict": "met", "rationale": "ok"} for c in self.CLAUSES})
        answers = judge_batch(cmd, self.CASE_PAYLOAD, self.CLAUSES, ROOT, "jev-1.13.0")
        self.assertEqual(set(answers), {c["id"] for c in self.CLAUSES})
        self.assertTrue(all(a["verdict"] == "met" for a in answers.values()))

    def test_a_missing_clause_in_the_reply_fails_closed(self):
        incomplete = {self.CLAUSES[0]["id"]: {"verdict": "met", "rationale": "ok"},
                      self.CLAUSES[1]["id"]: None}
        cmd = self._fake_judge_cmd(incomplete)
        with self.assertRaises(EvidenceUnavailable):
            judge_batch(cmd, self.CASE_PAYLOAD, self.CLAUSES, ROOT, "jev-1.13.0")

    def test_not_applicable_is_refused_unless_allowed(self):
        cmd = self._fake_judge_cmd({c["id"]: {"verdict": "not_applicable", "rationale": "n/a"} for c in self.CLAUSES})
        with self.assertRaises(EvidenceUnavailable):
            judge_batch(cmd, self.CASE_PAYLOAD, self.CLAUSES, ROOT, "jev-1.13.0", allow_not_applicable=False)
        answers = judge_batch(cmd, self.CASE_PAYLOAD, self.CLAUSES, ROOT, "jev-1.13.0", allow_not_applicable=True)
        self.assertTrue(all(a["verdict"] == "not_applicable" for a in answers.values()))


class BuildReport(unittest.TestCase):
    """build_report(): a recomputed
    clause's report must never carry judge_pin_digest (no judge ran it), and every
    report should record the exact claim wording it was judged against."""

    ANSWER = {"verdict": "not_met", "rationale": "because"}

    def test_a_judged_clause_carries_the_judge_pin(self):
        report = build_report(PLAIN_CLAUSE, {}, self.ANSWER, "contract/v1", "case-1", "cap-1", "pin-abc", "2026-10-01")
        self.assertEqual(report["epistemic_type"], "semantic_judgment")
        self.assertEqual(report["judge_pin_digest"], "pin-abc")
        self.assertNotIn("checker_ref", report)
        self.assertEqual(report["clause_claim"], PLAIN_CLAUSE["claim"])

    def test_a_recomputed_clause_never_carries_the_judge_pin(self):
        report = build_report(WITHIN_FARE_RULES, {"within_fare_rules_recomputed": True}, self.ANSWER,
                               "contract/v1", "case-1", "cap-1", "pin-abc", "2026-10-01")
        self.assertEqual(report["epistemic_type"], "recomputed_determination")
        self.assertNotIn("judge_pin_digest", report)
        self.assertIn("recompute.check_within_fare_rules", report["checker_ref"])

    def test_a_claim_switch_is_visible_on_the_sealed_report(self):
        report = build_report(DONE_IN_FULL, {"done_in_full_refusal_aware": True}, self.ANSWER,
                               "contract/v1", "case-1", "cap-1", "pin-abc", "2026-10-01")
        self.assertEqual(report["clause_claim"], DONE_IN_FULL["claim_switch"]["claim_when_on"])

    PIN_INPUT = {"model_id": "jev-1.13.0", "prompt_digest": "aa" * 32, "axes_digest": "bb" * 32,
                 "sampling_params": {"temperature": 0}}

    def test_a_judged_report_carries_the_period_contract_ref_and_pin_components(self):
        report = build_report(PLAIN_CLAUSE, {}, self.ANSWER, "contract/v1", "case-1", "cap-1", "pin-abc",
                              "2026-09-23", contract_ref="contract@1.4.0", judge_pin=self.PIN_INPUT)
        self.assertEqual(report["period"], "day:2026-09-23")
        self.assertEqual(report["contract_ref"], "contract@1.4.0")
        self.assertEqual(report["judge_pin"], self.PIN_INPUT)
        self.assertIsNot(report["judge_pin"], self.PIN_INPUT, "a copy, never the caller's dict")

    def test_a_recomputed_report_never_carries_pin_components(self):
        report = build_report(WITHIN_FARE_RULES, {"within_fare_rules_recomputed": True}, self.ANSWER,
                              "contract/v1", "case-1", "cap-1", "pin-abc", "2026-09-23",
                              contract_ref="contract@1.4.0", judge_pin=self.PIN_INPUT)
        self.assertNotIn("judge_pin", report)
        self.assertEqual(report["contract_ref"], "contract@1.4.0")

    def test_omitted_contract_ref_and_pin_leave_the_report_unchanged(self):
        report = build_report(PLAIN_CLAUSE, {}, self.ANSWER, "contract/v1", "case-1", "cap-1", "pin-abc", "2026-09-23")
        self.assertNotIn("contract_ref", report)
        self.assertNotIn("judge_pin", report)


class JudgeCallFailures(unittest.TestCase):
    """Every judge-cmd failure is EvidenceUnavailable: a timeout, output that is not
    JSON, a missing answer -- never a crash."""

    CASE_PAYLOAD = {"case": {"task_id": "1"}, "agent_interaction": {"messages": [{"role": "user", "content": "hi"}]}}

    def _cmd(self, body):
        script = ROOT / "tests" / "_fake_failing_judge.py"
        script.write_text(body)
        self.addCleanup(script.unlink)
        return f"{sys.executable} {script}"

    def test_a_judge_that_hangs_is_stopped_by_the_timeout(self):
        cmd = self._cmd("import time\ntime.sleep(30)\n")
        with self.assertRaisesRegex(EvidenceUnavailable, "within 1s"):
            judge(cmd, self.CASE_PAYLOAD, dict(PLAIN_CLAUSE), ROOT, "jev-1.13.0", timeout=1)

    def test_output_that_is_not_json_is_evidence_unavailable(self):
        cmd = self._cmd("print('not json')\n")
        with self.assertRaisesRegex(EvidenceUnavailable, "not JSON"):
            judge(cmd, self.CASE_PAYLOAD, dict(PLAIN_CLAUSE), ROOT, "jev-1.13.0")
        with self.assertRaisesRegex(EvidenceUnavailable, "not JSON"):
            judge_batch(cmd, self.CASE_PAYLOAD, [dict(PLAIN_CLAUSE)], ROOT, "jev-1.13.0")

    def test_a_never_not_applicable_clause_refuses_not_applicable_even_when_allowed(self):
        clause = dict(PLAIN_CLAUSE, never_not_applicable=True)
        self.assertEqual(valid_verdicts(clause, True), VERDICTS)
        self.assertIn("not_applicable", valid_verdicts(dict(PLAIN_CLAUSE), True))


class PinInput(unittest.TestCase):
    """scripts/judge_pin.py: the pin moves with the pack source, the instruction
    template and the confidence threshold."""

    def _spec(self, **judge_extra):
        return {"pack_source_digest": "a" * 64,
                "judge": dict({"prompt": "demo/airline-support-outcomes/judge-prompt.md",
                               "axes": "demo/airline-support-outcomes/axes.json",
                               "sampling_params": {"temperature": 0}}, **judge_extra)}

    def test_the_pin_input_carries_every_component(self):
        pin = pin_input(self._spec(min_confidence=0.8), ROOT, "jev-1.13.0", "b" * 64)
        self.assertEqual(pin["sampling_params"], {"temperature": 0, "pack_source_digest": "a" * 64,
                                                  "instruction_template_digest": "b" * 64,
                                                  "min_confidence_micros": 800000})
        self.assertEqual(len(pin["prompt_digest"]), 64)

    def test_each_component_moves_the_pin_input(self):
        base = pin_input(self._spec(), ROOT, "jev-1.13.0", "b" * 64)
        self.assertNotEqual(pin_input(dict(self._spec(), pack_source_digest="c" * 64), ROOT, "jev-1.13.0", "b" * 64),
                            base)
        self.assertNotEqual(pin_input(self._spec(), ROOT, "jev-1.13.0", "d" * 64), base)
        self.assertNotEqual(pin_input(self._spec(min_confidence=0.5), ROOT, "jev-1.13.0", "b" * 64), base)

    def test_a_reserved_sampling_key_is_refused(self):
        spec = self._spec()
        spec["judge"]["sampling_params"]["pack_source_digest"] = "x"
        with self.assertRaises(EvidenceUnavailable):
            pin_input(spec, ROOT, "jev-1.13.0", "b" * 64)

    def test_describe_judge_reads_the_digest_and_fails_closed_without_one(self):
        self.assertEqual(len(describe_judge(f"{sys.executable} {ROOT / 'tests' / 'stub_judge.py'}")), 64)
        self.assertEqual(describe_judge(f"{sys.executable} {ROOT / 'scripts' / 'judges' / 'jev_judge.py'}"),
                         __import__("jev_judge").instruction_template_digest())
        script = ROOT / "tests" / "_fake_mute_judge.py"
        script.write_text("print('{}')\n")
        self.addCleanup(script.unlink)
        with self.assertRaisesRegex(EvidenceUnavailable, "instruction_template_digest"):
            describe_judge(f"{sys.executable} {script}")


if __name__ == "__main__":
    unittest.main()
