"""Unit tests for scripts/rollup_day.py's pure steps: group_reports() (the
contract-scoped grouping), group_reports_by_day() (the same, grouped one level up
by the report's own `period`, for the day-level Result v0), clause_tiers()
(contract -> effective criterion tier map), rollup_case() (the per-case
combination) and day_document() (one day's Result v0 plus every case it left out). collect_reports()/collect_reports_by_day() are thin capsulectl-I/O
wrappers around the group_reports* functions and are exercised by the end-to-end
run instead (tests/fresh_env_outcomes.sh).

    python3 -m unittest discover -s tests -p 'test_*.py'
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

from capsulectl_calls import EvidenceUnavailable  # noqa: E402
from result_v0 import headline_from_result  # noqa: E402
from rollup import RollupError, all_criteria_from_clauses, all_required_met, checks_from_clauses  # noqa: E402
from rollup_day import (clause_tiers, day_document, group_reports, group_reports_by_day,  # noqa: E402
                        partition_stale, resolve_expected_pin, rollup_case, safe_filename)

CLAUSES = [
    {"id": "policy_compliance.confirmed_before_acting", "check_id": "policy_compliance", "tier": "judged"},
    {"id": "policy_compliance.within_fare_rules", "check_id": "policy_compliance", "tier": "judged"},
    {"id": "policy_compliance.no_unrequested_actions", "check_id": "policy_compliance", "tier": "judged"},
    {"id": "task_resolution.right_reservation", "check_id": "task_resolution", "tier": "judged"},
    {"id": "task_resolution.right_change", "check_id": "task_resolution", "tier": "judged"},
    {"id": "task_resolution.done_in_full", "check_id": "task_resolution", "tier": "judged"},
    {"id": "grounded_communication.prices_from_system", "check_id": "grounded_communication", "tier": "recomputed"},
    {"id": "grounded_communication.refunds_match_payment_records", "check_id": "grounded_communication", "tier": "judged"},
    {"id": "grounded_communication.no_invented_policy", "check_id": "grounded_communication", "tier": "judged"},
]
CHECKS = checks_from_clauses(CLAUSES)
ALL_CRITERIA = all_criteria_from_clauses(CLAUSES)
TIERS = {c["id"]: c["tier"] for c in CLAUSES}
CONTRACT_REF = "airline-support-outcomes@1.3.0"
ALL_MET_WITH_DIGESTS = {c: ("met", f"{i:064x}") for i, c in enumerate(ALL_CRITERIA)}


class SafeFilename(unittest.TestCase):
    def test_ordinary_case_id_is_readable(self):
        self.assertEqual(safe_filename("tau2:airline:task-1:trial-0"), "tau2_airline_task-1_trial-0")

    def test_path_separators_never_survive(self):
        self.assertNotIn("/", safe_filename("../../etc/passwd"))
        self.assertNotIn("\\", safe_filename("..\\..\\windows"))


class GroupReports(unittest.TestCase):
    CONTRACT = "tau2-airline-outcomes/v1"

    def _report(self, case_id, clause_id, verdict, contract=None, judge_pin_digest=None):
        return {"record_type": "evaluation-report/v1", "case_id": case_id,
                "clause_id": clause_id, "verdict": verdict, "contract": contract or self.CONTRACT,
                "judge_pin_digest": judge_pin_digest}

    def test_groups_by_case_and_clause(self):
        bodies = [
            ("cap1", self._report("case-a", "policy_compliance.confirmed_before_acting", "met")),
            ("cap2", self._report("case-a", "task_resolution.right_change", "not_met")),
            ("cap3", self._report("case-b", "policy_compliance.confirmed_before_acting", "not_evaluable")),
        ]
        grouped = group_reports(bodies, self.CONTRACT)
        self.assertEqual(grouped["case-a"]["policy_compliance.confirmed_before_acting"], ("met", "cap1"))
        self.assertEqual(grouped["case-a"]["task_resolution.right_change"], ("not_met", "cap2"))
        self.assertEqual(grouped["case-b"]["policy_compliance.confirmed_before_acting"], ("not_evaluable", "cap3"))

    def test_a_different_contracts_reports_never_mix_into_the_same_case(self):
        # Same case_id, same clause_id, two different contracts (e.g. the original
        # demo/tau2/compiled.json vs demo/tau2-outcomes/compiled.json, or a future
        # rubric-v3.3 recompile reusing an id) -- without this scoping, the second
        # report would silently overwrite or merge with the first under one case.
        bodies = [
            ("cap1", self._report("tau2:airline:task-1:trial-0", "policy-followed", "met",
                                   contract="tau2-airline-policy/v1")),
            ("cap2", self._report("tau2:airline:task-1:trial-0", "policy_compliance.confirmed_before_acting",
                                   "not_met", contract=self.CONTRACT)),
        ]
        grouped = group_reports(bodies, self.CONTRACT)
        self.assertEqual(list(grouped["tau2:airline:task-1:trial-0"]),
                          ["policy_compliance.confirmed_before_acting"])

    def test_a_reworded_criterion_s_old_pin_report_is_never_mixed_with_the_current_pin(self):
        # Same contract, same clause id, kept across a recompile that only
        # reworded the criterion (not removed/renamed it) -- so partition_stale
        # would never catch this, since the id didn't change. Only the pin
        # distinguishes an old judgment from a current one for the same clause.
        bodies = [
            ("cap-old", self._report("case-a", "policy_compliance.confirmed_before_acting", "met",
                                      judge_pin_digest="old-pin")),
            ("cap-new", self._report("case-a", "policy_compliance.confirmed_before_acting", "not_met",
                                      judge_pin_digest="new-pin")),
        ]
        grouped = group_reports(bodies, self.CONTRACT, expected_pin="new-pin")
        self.assertEqual(grouped["case-a"]["policy_compliance.confirmed_before_acting"], ("not_met", "cap-new"))

    def test_a_disagreeing_rejudgment_under_one_pin_is_a_conflict_never_last_wins(self):
        clause = "policy_compliance.confirmed_before_acting"
        bodies = [
            ("cap-1", self._report("case-a", clause, "not_met", judge_pin_digest="pin")),
            ("cap-2", self._report("case-a", clause, "met", judge_pin_digest="pin")),
            ("cap-3", self._report("case-b", clause, "met", judge_pin_digest="pin")),
        ]
        with self.assertRaisesRegex(RollupError, "judged \\['met', 'not_met'\\] under one pin"):
            group_reports(bodies, self.CONTRACT, expected_pin="pin")
        conflicts = {}
        grouped = group_reports(bodies, self.CONTRACT, expected_pin="pin", conflicts=conflicts)
        self.assertEqual(conflicts, {"case-a": {clause: ["met", "not_met"]}})
        self.assertNotIn("case-a", grouped, "a conflicting case is kept out of the rollup")
        self.assertIn("case-b", grouped)
        # and out of the day grouping too, given the same conflicts record
        by_day = group_reports_by_day([(c, dict(b, period="day:2026-09-23")) for c, b in bodies],
                                      self.CONTRACT, expected_pin="pin", conflicts=conflicts)
        self.assertEqual(sorted(by_day["day:2026-09-23"]), ["case-b"])

    def test_an_agreeing_duplicate_keeps_the_first_capsule_id(self):
        clause = "policy_compliance.confirmed_before_acting"
        bodies = [("cap-b", self._report("case-a", clause, "met")), ("cap-a", self._report("case-a", clause, "met"))]
        self.assertEqual(group_reports(bodies, self.CONTRACT)["case-a"][clause], ("met", "cap-a"))

    def test_a_recomputed_report_is_scoped_by_pack_source_digest(self):
        # A recomputed report carries no judge pin; it counts only under the
        # current pack source, never silently from an earlier compile.
        clause = "policy_compliance.within_fare_rules"
        current = {"record_type": "evaluation-report/v1", "case_id": "case-a", "clause_id": clause,
                   "verdict": "met", "contract": self.CONTRACT, "pack_source_digest": "pack-now"}
        old = dict(current, verdict="not_met", case_id="case-b", pack_source_digest="pack-then")
        grouped = group_reports([("c1", current), ("c2", old)], self.CONTRACT, expected_pin="pin",
                                expected_pack="pack-now")
        self.assertEqual(sorted(grouped), ["case-a"])

    def test_a_malformed_report_is_a_clean_refusal(self):
        body = {"record_type": "evaluation-report/v1", "contract": self.CONTRACT, "verdict": "met"}
        with self.assertRaisesRegex(RollupError, "report cap1 is malformed"):
            group_reports([("cap1", body)], self.CONTRACT)

    def test_non_report_capsules_are_ignored(self):
        bodies = [("cap1", {"record_type": "published_capsule", "case": {}}),
                  ("cap2", None)]
        self.assertEqual(group_reports(bodies, self.CONTRACT), {})


class GroupReportsByDay(unittest.TestCase):
    CONTRACT = "tau2-airline-outcomes/v1"

    def _report(self, case_id, clause_id, verdict, period, contract=None):
        return {"record_type": "evaluation-report/v1", "case_id": case_id,
                "clause_id": clause_id, "verdict": verdict, "period": period,
                "contract": contract or self.CONTRACT}

    def test_groups_by_period_then_case_then_clause(self):
        bodies = [
            ("cap1", self._report("case-a", "policy_compliance.confirmed_before_acting",
                                   "met", "day:2026-09-23")),
            ("cap2", self._report("case-b", "policy_compliance.confirmed_before_acting",
                                   "not_met", "day:2026-09-24")),
        ]
        grouped = group_reports_by_day(bodies, self.CONTRACT)
        self.assertEqual(sorted(grouped), ["day:2026-09-23", "day:2026-09-24"])
        self.assertEqual(
            grouped["day:2026-09-23"]["case-a"]["policy_compliance.confirmed_before_acting"],
            ("met", "cap1"),
        )
        self.assertEqual(
            grouped["day:2026-09-24"]["case-b"]["policy_compliance.confirmed_before_acting"],
            ("not_met", "cap2"),
        )

    def test_a_different_contracts_reports_never_mix_into_the_same_day(self):
        bodies = [
            ("cap1", self._report("tau2:airline:task-1:trial-0", "policy-followed",
                                   "met", "day:2026-09-23", contract="tau2-airline-policy/v1")),
            ("cap2", self._report("tau2:airline:task-1:trial-0",
                                   "policy_compliance.confirmed_before_acting",
                                   "not_met", "day:2026-09-23")),
        ]
        grouped = group_reports_by_day(bodies, self.CONTRACT)
        self.assertEqual(
            list(grouped["day:2026-09-23"]["tau2:airline:task-1:trial-0"]),
            ["policy_compliance.confirmed_before_acting"],
        )

    def test_non_report_capsules_are_ignored(self):
        bodies = [("cap1", {"record_type": "published_capsule", "case": {}}),
                  ("cap2", None)]
        self.assertEqual(group_reports_by_day(bodies, self.CONTRACT), {})


class ClauseTiers(unittest.TestCase):
    def test_honours_tier_switch(self):
        clause = {"id": "policy_compliance.within_fare_rules", "tier": "judged",
                  "tier_switch": {"flag": "within_fare_rules_recomputed", "tier_when_on": "recomputed"}}
        off = {"clauses": [clause], "switches": {"within_fare_rules_recomputed": False}}
        on = {"clauses": [clause], "switches": {"within_fare_rules_recomputed": True}}
        self.assertEqual(clause_tiers(off)[clause["id"]], "judged")
        self.assertEqual(clause_tiers(on)[clause["id"]], "recomputed")

    def test_reads_tier_per_clause_id(self):
        spec = {"clauses": [
            {"id": "policy_compliance.confirmed_before_acting", "tier": "judged"},
            {"id": "grounded_communication.prices_from_system", "tier": "recomputed"},
        ]}
        tiers = clause_tiers(spec)
        self.assertEqual(tiers["policy_compliance.confirmed_before_acting"], "judged")
        self.assertEqual(tiers["grounded_communication.prices_from_system"], "recomputed")


class ResolveExpectedPin(unittest.TestCase):
    def test_no_model_id_means_no_pin_scoping(self):
        # Never calls capsulectl at all when there's no model id to pin against
        # -- a hand-authored contract predating judge.model_id (e.g.
        # demo/tau2-outcomes/compiled.json) must not crash or shell out here.
        self.assertIsNone(resolve_expected_pin("capsulectl-should-not-run", {}, None, None, None, None))
        self.assertIsNone(resolve_expected_pin("capsulectl-should-not-run", {}, "", None, None, None))

    def test_a_model_id_without_a_judge_cmd_is_refused(self):
        # The pin covers the instruction template the judge reports; without the
        # judge command it cannot be recomputed, so the rollup refuses.
        with self.assertRaisesRegex(EvidenceUnavailable, "--judge-cmd is required"):
            resolve_expected_pin("capsulectl-should-not-run", {"judge": {}}, "jev-1.13.0", None, None, None)


class PartitionStale(unittest.TestCase):
    def test_nothing_stale_when_every_clause_is_current(self):
        current, stale = partition_stale(ALL_MET_WITH_DIGESTS, ALL_CRITERIA)
        self.assertEqual(stale, [])
        self.assertEqual(set(current), set(ALL_CRITERIA))

    def test_a_criterion_removed_by_recompile_is_set_aside_not_merged(self):
        # Simulates a book carrying reports from two compiled versions of the
        # same contract id: v1 judged a now-removed criterion
        # ("policy_compliance.old_removed_one"); v2 (this test's ALL_CRITERIA)
        # never defines it. It must never appear in `current` (which rollup_case
        # treats as this case's full verdict set) and must be reported, not
        # silently dropped.
        verdicts = dict(ALL_MET_WITH_DIGESTS, **{"policy_compliance.old_removed_one": ("met", "ff" * 32)})
        current, stale = partition_stale(verdicts, ALL_CRITERIA)
        self.assertEqual(stale, ["policy_compliance.old_removed_one"])
        self.assertNotIn("policy_compliance.old_removed_one", current)
        self.assertEqual(set(current), set(ALL_CRITERIA))


class RollupCase(unittest.TestCase):
    def test_all_nine_met_is_resolved_and_carries_digests(self):
        out = rollup_case("tau2:airline:task-1:trial-0", ALL_MET_WITH_DIGESTS, "2026-09-23T23:59:59Z",
                           CHECKS, ALL_CRITERIA, CONTRACT_REF, TIERS)
        self.assertTrue(out["resolved"])
        self.assertEqual(len(out["criterion_verdicts"]), 9)
        self.assertEqual(out["result_v0"]["result_version"], "evidence-result-v0")
        claim = out["result_v0"]["claims"][0]
        self.assertTrue(claim["evidence"])
        self.assertEqual(claim["contract_ref"], CONTRACT_REF)

    def test_one_not_met_is_not_resolved(self):
        verdicts = dict(ALL_MET_WITH_DIGESTS)
        verdicts["grounded_communication.prices_from_system"] = ("not_met", "ab" * 32)
        out = rollup_case("case", verdicts, "2026-09-23T23:59:59Z", CHECKS, ALL_CRITERIA, CONTRACT_REF, TIERS)
        self.assertFalse(out["resolved"])
        self.assertEqual(out["check_verdicts"]["grounded_communication"], "not_met")
        self.assertEqual(out["check_verdicts"]["policy_compliance"], "met")

    def test_a_recompiled_pack_with_a_tenth_criterion_rolls_up_on_its_own_shape(self):
        # Proves rollup_case() doesn't secretly assume nine: add a tenth clause to a
        # fresh check and confirm it participates in both the check verdict and the
        # all-required rollup.
        clauses = CLAUSES + [{"id": "extra_check.new_one", "check_id": "extra_check", "tier": "judged"}]
        checks = checks_from_clauses(clauses)
        all_criteria = all_criteria_from_clauses(clauses)
        tiers = dict(TIERS, **{"extra_check.new_one": "judged"})
        verdicts = dict(ALL_MET_WITH_DIGESTS, **{"extra_check.new_one": ("not_met", "ff" * 32)})
        out = rollup_case("case", verdicts, "2026-09-23T23:59:59Z", checks, all_criteria, CONTRACT_REF, tiers)
        self.assertFalse(out["resolved"])
        self.assertEqual(out["check_verdicts"]["extra_check"], "not_met")
        self.assertEqual(len(out["result_v0"]["claims"]), 10)

    def test_each_claim_reports_its_own_criterion_s_tier(self):
        out = rollup_case("case", ALL_MET_WITH_DIGESTS, "2026-09-23T23:59:59Z",
                           CHECKS, ALL_CRITERIA, CONTRACT_REF, TIERS)
        recomputed = next(c for c in out["result_v0"]["claims"]
                           if c["id"] == "grounded_communication.prices_from_system")
        self.assertEqual(recomputed["tier"], "recomputed")
        judged = next(c for c in out["result_v0"]["claims"]
                      if c["id"] == "policy_compliance.confirmed_before_acting")
        self.assertEqual(judged["tier"], "judged")


class DayDocument(unittest.TestCase):
    PERIOD = "day:2026-09-23"

    def _day(self):
        not_met = dict(ALL_MET_WITH_DIGESTS)
        not_met["task_resolution.right_change"] = ("not_met", "f" * 64)
        some_na = dict(ALL_MET_WITH_DIGESTS)
        some_na["task_resolution.right_change"] = ("not_applicable", "e" * 64)
        all_na = {c: ("not_applicable", d) for c, (_, d) in ALL_MET_WITH_DIGESTS.items()}
        never_na_broken = dict(ALL_MET_WITH_DIGESTS)
        never_na_broken["task_resolution.done_in_full"] = ("not_applicable", "d" * 64)
        incomplete = {c: v for c, v in list(ALL_MET_WITH_DIGESTS.items())[:3]}
        return {"case-met": ALL_MET_WITH_DIGESTS, "case-not-met": not_met, "case-some-na": some_na,
                "case-all-na": all_na, "case-never-na": never_na_broken, "case-incomplete": incomplete}

    NEVER_NA = frozenset({"task_resolution.done_in_full", "grounded_communication.no_invented_policy"})

    def test_every_left_out_case_is_reported_with_its_reason(self):
        doc, skipped = day_document(self.PERIOD, self._day(), "2026-09-23T23:59:59Z", ALL_CRITERIA,
                                    CONTRACT_REF, TIERS, True, self.NEVER_NA)
        reasons = {s["case_id"]: s["reason"] for s in skipped}
        self.assertEqual(sorted(reasons), ["case-all-na", "case-incomplete", "case-never-na"])
        self.assertIn("may never be not_applicable", reasons["case-all-na"])
        # with no criterion marked never_not_applicable, all-N/A is still refused
        _, skipped = day_document(self.PERIOD, {"case-all-na": self._day()["case-all-na"]}, "2026-09-23T23:59:59Z",
                                  ALL_CRITERIA, CONTRACT_REF, TIERS, True)
        self.assertIn("nothing was evaluated", skipped[0]["reason"])
        self.assertIn("may never be not_applicable", reasons["case-never-na"])
        self.assertEqual(reasons["case-incomplete"], "incomplete on this day")

    def test_the_headline_re_derives_from_the_document_alone(self):
        day = self._day()
        doc, skipped = day_document(self.PERIOD, day, "2026-09-23T23:59:59Z", ALL_CRITERIA,
                                    CONTRACT_REF, TIERS, True, self.NEVER_NA)
        left_out = {s["case_id"] for s in skipped}
        expected = sum(1 for case_id, verdicts in day.items() if case_id not in left_out
                       and all_required_met({c: v for c, (v, _) in verdicts.items()}, ALL_CRITERIA, True,
                                            self.NEVER_NA))
        self.assertEqual(headline_from_result(doc), {"cases": 3, "resolved": expected})
        self.assertEqual(expected, 2, "case-met and case-some-na resolve; case-not-met does not")


if __name__ == "__main__":
    unittest.main()
