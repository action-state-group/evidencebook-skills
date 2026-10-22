"""Unit tests for scripts/rollup_day.py's pure steps: group_reports() (the
contract-scoped grouping), group_reports_by_day() (the same, grouped one level up
by the report's own `period`, for the day-level Result v0), clause_tiers()
(contract -> effective criterion tier map), rollup_case() (the per-case
combination) and day_document() (one day's Result v0 plus every case it left out). collect_reports()/collect_reports_by_day() are thin capsulectl-I/O
wrappers around the group_reports* functions and are exercised by the end-to-end
run instead (tests/fresh_env_outcomes.sh).

    python3 -m unittest discover -s tests -p 'test_*.py'
"""
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

from capsulectl_calls import EvidenceUnavailable  # noqa: E402
from result_v0 import headline_from_result, report_title  # noqa: E402
from rollup import RollupError, all_criteria_from_clauses, all_required_met, checks_from_clauses  # noqa: E402
from rollup_day import (case_tiers, clause_tiers, day_document, group_reports, group_reports_by_day,  # noqa: E402
                        partition_stale, report_determinations, require_pin_for_judged_clauses,
                        resolve_expected_pin, resolve_judge_model_id, rollup_case, safe_filename)

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
ALL_MET_WITH_DIGESTS = {c: ("met", f"{i:064x}", None) for i, c in enumerate(ALL_CRITERIA)}
CASE_A_CAPSULE = "ca" * 32  # a case record capsule id: 64 lowercase hex, like every book capsule id


class SafeFilename(unittest.TestCase):
    def test_ordinary_case_id_is_readable(self):
        self.assertEqual(safe_filename("tau2:airline:task-1:trial-0"), "tau2_airline_task-1_trial-0")

    def test_path_separators_never_survive(self):
        self.assertNotIn("/", safe_filename("../../etc/passwd"))
        self.assertNotIn("\\", safe_filename("..\\..\\windows"))


class GroupReports(unittest.TestCase):
    CONTRACT = "tau2-airline-outcomes/v1"

    def _report(self, case_id, clause_id, verdict, contract=None, judge_pin_digest=None, source_capsule_id=None):
        return {"record_type": "evaluation-report/v1", "case_id": case_id,
                "clause_id": clause_id, "verdict": verdict, "contract": contract or self.CONTRACT,
                "judge_pin_digest": judge_pin_digest, "source_capsule_id": source_capsule_id}

    def test_groups_by_case_and_clause(self):
        bodies = [
            ("cap1", self._report("case-a", "policy_compliance.confirmed_before_acting", "met")),
            ("cap2", self._report("case-a", "task_resolution.right_change", "not_met")),
            ("cap3", self._report("case-b", "policy_compliance.confirmed_before_acting", "not_evaluable")),
        ]
        grouped = group_reports(bodies, self.CONTRACT)
        self.assertEqual(grouped["case-a"]["policy_compliance.confirmed_before_acting"], ("met", "cap1", None))
        self.assertEqual(grouped["case-a"]["task_resolution.right_change"], ("not_met", "cap2", None))
        self.assertEqual(grouped["case-b"]["policy_compliance.confirmed_before_acting"],
                         ("not_evaluable", "cap3", None))

    def test_the_report_s_own_source_capsule_id_is_carried_into_the_group(self):
        # run_daily.py's build_report always names the case capsule it judged
        # as source_capsule_id -- this is what lets a claim later cite the case
        # record (result_v0.claim_for) with no by-hand step.
        bodies = [
            ("cap1", self._report("case-a", "policy_compliance.confirmed_before_acting", "met",
                                  source_capsule_id=CASE_A_CAPSULE)),
        ]
        grouped = group_reports(bodies, self.CONTRACT)
        self.assertEqual(grouped["case-a"]["policy_compliance.confirmed_before_acting"],
                         ("met", "cap1", CASE_A_CAPSULE))

    def test_a_malformed_source_capsule_id_names_the_report(self):
        clause = "policy_compliance.confirmed_before_acting"
        for bad in ({"x": 1}, "not-a-digest", "AB" * 32, 7):
            with self.subTest(bad=bad):
                bodies = [("cap-bad", self._report("case-a", clause, "met", source_capsule_id=bad))]
                with self.assertRaisesRegex(RollupError, "cap-bad"):
                    group_reports(bodies, self.CONTRACT)

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
        self.assertEqual(grouped["case-a"]["policy_compliance.confirmed_before_acting"],
                         ("not_met", "cap-new", None))

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
        self.assertEqual(group_reports(bodies, self.CONTRACT)["case-a"][clause], ("met", "cap-a", None))

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

    def _report(self, case_id, clause_id, verdict, period, contract=None, source_capsule_id=None):
        return {"record_type": "evaluation-report/v1", "case_id": case_id,
                "clause_id": clause_id, "verdict": verdict, "period": period,
                "contract": contract or self.CONTRACT, "source_capsule_id": source_capsule_id}

    def test_groups_by_period_then_case_then_clause(self):
        bodies = [
            ("cap1", self._report("case-a", "policy_compliance.confirmed_before_acting",
                                   "met", "day:2026-09-23", source_capsule_id=CASE_A_CAPSULE)),
            ("cap2", self._report("case-b", "policy_compliance.confirmed_before_acting",
                                   "not_met", "day:2026-09-24")),
        ]
        grouped = group_reports_by_day(bodies, self.CONTRACT)
        self.assertEqual(sorted(grouped), ["day:2026-09-23", "day:2026-09-24"])
        self.assertEqual(
            grouped["day:2026-09-23"]["case-a"]["policy_compliance.confirmed_before_acting"],
            ("met", "cap1", CASE_A_CAPSULE),
        )
        self.assertEqual(
            grouped["day:2026-09-24"]["case-b"]["policy_compliance.confirmed_before_acting"],
            ("not_met", "cap2", None),
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


class ResolveJudgeModelId(unittest.TestCase):
    def test_cli_flag_wins_over_the_spec(self):
        self.assertEqual(resolve_judge_model_id("jev-1.13.0", {"judge": {"model_id": "other"}}), "jev-1.13.0")

    def test_falls_back_to_the_spec_s_judge_model_id(self):
        self.assertEqual(resolve_judge_model_id(None, {"judge": {"model_id": "jev-1.13.0"}}), "jev-1.13.0")

    def test_no_judge_key_at_all_fails_closed_to_none_not_a_crash(self):
        # A hand-authored contract predating judge.model_id may carry no
        # "judge" key at all -- spec["judge"] would KeyError; this must not.
        self.assertIsNone(resolve_judge_model_id(None, {}))

    def test_a_judge_key_with_no_model_id_is_also_none(self):
        self.assertIsNone(resolve_judge_model_id(None, {"judge": {}}))

    def test_a_non_mapping_judge_is_none_not_an_attribute_error(self):
        for judge in ("jev", [], 7):
            with self.subTest(judge=judge):
                self.assertIsNone(resolve_judge_model_id(None, {"judge": judge}))


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
            resolve_expected_pin("capsulectl-should-not-run",
                                 {"judge": {"prompt": "judge-prompt.md", "axes": "axes.json"}},
                                 "jev-1.13.0", None, None, None)

    def test_a_model_id_against_a_contract_with_no_judge_section_is_refused(self):
        # --judge-model-id given, but the contract carries no judge prompt/axes
        # to pin: refused as unavailable evidence, never a KeyError, and the
        # judge command is never run.
        for spec in ({}, {"judge": {}}, {"judge": {"prompt": "judge-prompt.md"}}, {"judge": "jev"}, {"judge": []}):
            for judge_cmd in ("judge-cmd-should-not-run", None):
                with self.subTest(spec=spec, judge_cmd=judge_cmd):
                    # Checked before --judge-cmd, so the user is told the real
                    # problem first (Ethan's review of 6aa4fbb).
                    with self.assertRaisesRegex(EvidenceUnavailable, "no judge prompt and axes"):
                        resolve_expected_pin("capsulectl-should-not-run", spec, "jev-1.13.0",
                                             judge_cmd, None, None)


class RequirePinForJudgedClauses(unittest.TestCase):
    """Ethan's review of 6aa4fbb: with no `judge` section the rollup ran
    unscoped by pin, so an old pin's `met` could roll up as satisfied for the
    current contract. A contract with any judged clause now refuses."""

    JUDGED = {"clauses": [{"id": "a.one", "check_id": "a", "tier": "judged"},
                          {"id": "a.two", "check_id": "a", "tier": "recomputed"}]}
    RECOMPUTED_ONLY = {"clauses": [{"id": "a.two", "check_id": "a", "tier": "recomputed"}]}

    def test_judged_clauses_and_no_pin_is_refused(self):
        with self.assertRaisesRegex(EvidenceUnavailable, "judged clause"):
            require_pin_for_judged_clauses(self.JUDGED, None)

    def test_judged_clauses_under_a_pin_pass(self):
        require_pin_for_judged_clauses(self.JUDGED, "ab" * 32)

    def test_a_recomputed_only_contract_runs_without_a_pin(self):
        require_pin_for_judged_clauses(self.RECOMPUTED_ONLY, None)

    def test_a_tier_switch_to_recomputed_counts_as_recomputed(self):
        spec = {"switches": {"flag_x": True},
                "clauses": [{"id": "a.one", "check_id": "a", "tier": "judged",
                             "tier_switch": {"flag": "flag_x", "tier_when_on": "recomputed"}}]}
        require_pin_for_judged_clauses(spec, None)

    def test_no_judge_section_and_only_old_pin_reports_produces_no_result(self):
        # End to end through main(): a contract with no `judge` section, a
        # book holding only an older pin's judged `met`, no --judge-model-id.
        # Exit 2 with evidence_unavailable, and no Result v0 written.
        import io
        import json as _json
        import tempfile
        from contextlib import redirect_stdout
        from rollup_day import main
        with tempfile.TemporaryDirectory() as d:
            d = pathlib.Path(d)
            spec_path = d / "demo" / "x" / "compiled.json"
            spec_path.parent.mkdir(parents=True)
            spec_path.write_text(_json.dumps({"contract": "x/v1", "contract_ref": "x@0.1.0",
                                              "clauses": [{"id": "a.one", "check_id": "a", "tier": "judged"}]}))
            out = d / "out"
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(["--profile", "p", "--spec", str(spec_path), "--capsulectl", "capsulectl-should-not-run",
                           "--generated-at", "2026-10-20T00:00:00Z", "--out", str(out)])
            self.assertEqual(rc, 2, buf.getvalue())
            self.assertIn("evidence_unavailable", _json.loads(buf.getvalue()))
            self.assertEqual([p.name for p in out.rglob("*.json")], [])


class ReportTitle(unittest.TestCase):
    def test_the_pack_title_and_the_bare_day(self):
        spec = {"contract": "airline-support-outcomes/v1", "title": "Airline support outcomes"}
        self.assertEqual(report_title(spec, "2026-10-01"), "Airline support outcomes — 2026-10-01")

    def test_a_pack_with_no_title_falls_back_to_its_contract_id(self):
        self.assertEqual(report_title({"contract": "x/v1"}, "2026-10-01"), "x/v1 — 2026-10-01")


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
        verdicts = dict(ALL_MET_WITH_DIGESTS, **{"policy_compliance.old_removed_one": ("met", "ff" * 32, None)})
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
        verdicts["grounded_communication.prices_from_system"] = ("not_met", "ab" * 32, None)
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
        verdicts = dict(ALL_MET_WITH_DIGESTS, **{"extra_check.new_one": ("not_met", "ff" * 32, None)})
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

    def test_a_claim_cites_its_case_record_second_so_disclose_can_find_the_transcript(self):
        # Every report named the same case capsule (run_daily.py judges all nine
        # criteria of one case against one source capsule) -- the claim's
        # evidence[] must carry the report digest first and the case record
        # second, so capsulectl disclose --attach-input-originals, walking the
        # Result-root's citations, finds the conversation with no by-hand step.
        clause = "policy_compliance.confirmed_before_acting"
        verdicts = {cid: (v, d, "case-capsule-id") for cid, (v, d, _) in ALL_MET_WITH_DIGESTS.items()}
        out = rollup_case("tau2:airline:task-1:trial-0", verdicts, "2026-09-23T23:59:59Z",
                          CHECKS, ALL_CRITERIA, CONTRACT_REF, TIERS)
        claim = next(c for c in out["result_v0"]["claims"] if c["id"] == clause)
        self.assertEqual(claim["evidence"], [
            {"digest_alg": "SHA-256", "digest": verdicts[clause][1]},
            {"digest_alg": "SHA-256", "digest": "case-capsule-id"},
        ])

    def test_a_report_with_no_source_capsule_id_cites_only_its_own_digest(self):
        # Never fabricated: a report that didn't name a case record (e.g. a book
        # sealed before run_daily.py started setting source_capsule_id) leaves
        # the claim with only the report citation, same shape as before this
        # feature existed.
        out = rollup_case("case", ALL_MET_WITH_DIGESTS, "2026-09-23T23:59:59Z",
                          CHECKS, ALL_CRITERIA, CONTRACT_REF, TIERS)
        claim = next(c for c in out["result_v0"]["claims"]
                     if c["id"] == "policy_compliance.confirmed_before_acting")
        self.assertEqual(len(claim["evidence"]), 1)


class DayDocument(unittest.TestCase):
    PERIOD = "day:2026-09-23"

    def _day(self):
        not_met = dict(ALL_MET_WITH_DIGESTS)
        not_met["task_resolution.right_change"] = ("not_met", "f" * 64, None)
        some_na = dict(ALL_MET_WITH_DIGESTS)
        some_na["task_resolution.right_change"] = ("out_of_scope", "e" * 64, None)
        all_na = {c: ("out_of_scope", d, None) for c, (_, d, _) in ALL_MET_WITH_DIGESTS.items()}
        never_na_broken = dict(ALL_MET_WITH_DIGESTS)
        never_na_broken["task_resolution.done_in_full"] = ("out_of_scope", "d" * 64, None)
        incomplete = {c: v for c, v in list(ALL_MET_WITH_DIGESTS.items())[:3]}
        return {"case-met": ALL_MET_WITH_DIGESTS, "case-not-met": not_met, "case-some-na": some_na,
                "case-all-na": all_na, "case-never-na": never_na_broken, "case-incomplete": incomplete}

    NEVER_NA = frozenset({"task_resolution.done_in_full", "grounded_communication.no_invented_policy"})

    def test_every_left_out_case_is_reported_with_its_reason(self):
        doc, skipped = day_document(self.PERIOD, self._day(), "2026-09-23T23:59:59Z", ALL_CRITERIA,
                                    CONTRACT_REF, TIERS, True, self.NEVER_NA)
        reasons = {s["case_id"]: s["reason"] for s in skipped}
        self.assertEqual(sorted(reasons), ["case-all-na", "case-incomplete", "case-never-na"])
        self.assertIn("may never be out_of_scope", reasons["case-all-na"])
        # with no criterion marked never_out_of_scope, all-out_of_scope is still refused
        _, skipped = day_document(self.PERIOD, {"case-all-na": self._day()["case-all-na"]}, "2026-09-23T23:59:59Z",
                                  ALL_CRITERIA, CONTRACT_REF, TIERS, True)
        self.assertIn("nothing was evaluated", skipped[0]["reason"])
        self.assertIn("may never be out_of_scope", reasons["case-never-na"])
        self.assertEqual(reasons["case-incomplete"], "incomplete on this day")

    def test_the_headline_re_derives_from_the_document_alone(self):
        day = self._day()
        doc, skipped = day_document(self.PERIOD, day, "2026-09-23T23:59:59Z", ALL_CRITERIA,
                                    CONTRACT_REF, TIERS, True, self.NEVER_NA)
        left_out = {s["case_id"] for s in skipped}
        expected = sum(1 for case_id, verdicts in day.items() if case_id not in left_out
                       and all_required_met({c: v for c, (v, _, _) in verdicts.items()}, ALL_CRITERIA, True,
                                            self.NEVER_NA))
        self.assertEqual(headline_from_result(doc), {"cases": 3, "resolved": expected})
        self.assertEqual(expected, 2, "case-met and case-some-na resolve; case-not-met does not")

    def test_each_case_s_claims_cite_that_case_s_own_source_capsule(self):
        # Two cases in one day document must never cross-cite each other's case
        # record -- each case's claims carry only its own source_capsule_id.
        day = {
            "case-a": {cid: (v, d, "capsule-a") for cid, (v, d, _) in ALL_MET_WITH_DIGESTS.items()},
            "case-b": {cid: (v, d, "capsule-b") for cid, (v, d, _) in ALL_MET_WITH_DIGESTS.items()},
        }
        doc, skipped = day_document(self.PERIOD, day, "2026-09-23T23:59:59Z", ALL_CRITERIA, CONTRACT_REF, TIERS)
        self.assertEqual(skipped, [])
        clause = "policy_compliance.confirmed_before_acting"
        claim_a = next(c for c in doc["claims"] if c["id"] == f"case-a::{clause}")
        claim_b = next(c for c in doc["claims"] if c["id"] == f"case-b::{clause}")
        self.assertEqual(claim_a["evidence"][-1], {"digest_alg": "SHA-256", "digest": "capsule-a"})
        self.assertEqual(claim_b["evidence"][-1], {"digest_alg": "SHA-256", "digest": "capsule-b"})


class PerSessionTier(unittest.TestCase):
    """Ethan's review of 2032554: a judged criterion whose recompute pre-check
    decided a session was still claimed `judged` in Result v0, because the
    claim's tier came from the clause's static tier. It now comes from each
    session's own report."""

    CRIT = "policy_compliance.within_fare_rules"

    def test_report_determinations_maps_each_capsule(self):
        bodies = [("a", {"record_type": "evaluation-report/v1", "epistemic_type": "recomputed_determination"}),
                  ("b", {"record_type": "evaluation-report/v1", "epistemic_type": "semantic_judgment"}),
                  ("c", {"record_type": "evaluation-report/v1"}),
                  ("d", {"record_type": "something-else", "epistemic_type": "semantic_judgment"})]
        self.assertEqual(report_determinations(bodies),
                         {"a": "recomputed_determination", "b": "semantic_judgment"})

    def test_one_criterion_can_be_recomputed_in_one_session_and_judged_in_another(self):
        pre = dict(ALL_MET_WITH_DIGESTS, **{self.CRIT: ("not_evaluable", "a" * 64, None)})
        judged = dict(ALL_MET_WITH_DIGESTS, **{self.CRIT: ("met", "b" * 64, None)})
        determinations = {"a" * 64: "recomputed_determination", "b" * 64: "semantic_judgment"}
        self.assertEqual(case_tiers(pre, TIERS, determinations)[self.CRIT], "recomputed")
        self.assertEqual(case_tiers(judged, TIERS, determinations)[self.CRIT], "judged")
        self.assertEqual(case_tiers(judged, TIERS)[self.CRIT], "judged")  # no determinations: the static tier
        doc, skipped = day_document("day:2026-09-23", {"s-pre": pre, "s-judged": judged}, "2026-09-23T23:59:59Z",
                                    ALL_CRITERIA, CONTRACT_REF, TIERS, determinations=determinations)
        self.assertEqual(skipped, [])
        tiers = {c["id"]: c["tier"] for c in doc["claims"] if c["requirement_ref"] == self.CRIT}
        self.assertEqual(tiers, {f"s-pre::{self.CRIT}": "recomputed", f"s-judged::{self.CRIT}": "judged"})
        per_case = rollup_case("s-pre", pre, "2026-09-23T23:59:59Z", CHECKS, ALL_CRITERIA, CONTRACT_REF, TIERS,
                               determinations=determinations)
        claim = next(c for c in per_case["result_v0"]["claims"] if c["id"] == self.CRIT)
        self.assertEqual(claim["tier"], "recomputed")
        self.assertNotIn("judge_pin_digest", claim)

    def test_an_unknown_determination_is_refused_not_guessed(self):
        case = dict(ALL_MET_WITH_DIGESTS, **{self.CRIT: ("met", "c" * 64, None)})
        with self.assertRaisesRegex(RollupError, "unknown epistemic_type"):
            case_tiers(case, TIERS, {"c" * 64: "vibes"})
        doc, skipped = day_document("day:2026-09-23", {"s": case}, "2026-09-23T23:59:59Z", ALL_CRITERIA,
                                    CONTRACT_REF, TIERS, determinations={"c" * 64: "vibes"})
        self.assertIsNone(doc)
        self.assertIn("unknown epistemic_type", skipped[0]["reason"])


class PrecheckToResultV0(unittest.TestCase):
    """End to end on the compiled EU pack, pre-check to Result v0: one session
    the Art 14(4)(e) pre-check decides and one the judge decides. The same
    criterion reads `recomputed` for the first and `judged` for the second."""

    ROOT = pathlib.Path(__file__).resolve().parents[1]
    ART14E = "art14e.stop_or_handoff_on_request"

    def test_precheck_session_is_recomputed_and_the_judged_one_is_judged(self):
        sys.path.insert(0, str(self.ROOT / "scripts" / "judges"))
        from rollup import never_out_of_scope_from_clauses
        from run_daily import build_report, case_answers, effective_tier
        spec = json.loads((self.ROOT / "demo" / "eu-ai-act-obligations" / "compiled.json").read_text())
        switches = spec.get("switches") or {}
        tmp = pathlib.Path(tempfile.mkdtemp())
        judge = tmp / "judge.py"
        judge.write_text("import json, sys\nreq = json.load(sys.stdin)\n"
                         "json.dump({'answers': {c['id']: {'verdict': 'met', 'rationale': 'judge'}"
                         " for c in req['clauses']}}, sys.stdout)\n")
        sessions = {
            "s-truncated": [{"role": "assistant", "content": "Hi! How can I help you today?"},
                            {"role": "user", "content": "Cancel my trip."},
                            {"role": "assistant", "content": "Would you like me to transfer you to a human agent?"},
                            {"role": "user", "content": "Yes, please transfer me to a human agent. ###TRANSFER###"}],
            "s-judged": [{"role": "assistant", "content": "Hi! How can I help you today?"},
                         {"role": "user", "content": "Stop, don't cancel."},
                         {"role": "assistant", "content": "Okay, I won't."},
                         {"role": "user", "content": "Please transfer me to a human agent. ###TRANSFER###"}],
        }
        bodies = []
        for case_id, messages in sessions.items():
            body = {"case": {"benchmark": "tau2", "domain": "airline", "task_id": case_id, "trial": 0},
                    "agent_interaction": {"messages": messages}}
            answers, prechecked = case_answers(body, spec, switches, self.ROOT, f"{sys.executable} {judge}",
                                               "jev-1.13.0", allow_out_of_scope=True, judge_batch_mode=True)
            for clause in spec["clauses"]:
                if effective_tier(clause, switches) not in ("judged", "recomputed"):
                    continue
                cap = f"{case_id}-{clause['id']}"
                source = ("a" if case_id == "s-truncated" else "b") * 64  # the case record's capsule id
                bodies.append((cap, build_report(clause, switches, answers[clause["id"]], spec["contract"], case_id,
                                                 source, "pin-abc", "2026-09-23",
                                                 prechecked=clause["id"] in prechecked)))
        by_day = group_reports_by_day(bodies, spec["contract"])
        all_criteria = all_criteria_from_clauses(spec["clauses"])
        doc, skipped = day_document("day:2026-09-23", by_day["day:2026-09-23"], "2026-09-23T23:59:59Z",
                                    all_criteria, "eu@1", clause_tiers(spec), True,
                                    never_out_of_scope_from_clauses(spec["clauses"]),
                                    determinations=report_determinations(bodies))
        self.assertEqual(skipped, [])
        claims = {c["id"]: c for c in doc["claims"]}
        pre = claims[f"s-truncated::{self.ART14E}"]
        self.assertEqual((pre["tier"], pre["verdict"]), ("recomputed", "not_evaluable"))
        self.assertNotIn("judge_pin_digest", pre)
        self.assertEqual(claims[f"s-judged::{self.ART14E}"]["tier"], "judged")
        # every other judged row stays judged in both sessions
        other = [c for c in doc["claims"] if c["requirement_ref"] != self.ART14E
                 and clause_tiers(spec)[c["requirement_ref"]] == "judged"]
        self.assertTrue(other)
        self.assertTrue(all(c["tier"] == "judged" for c in other))


if __name__ == "__main__":
    unittest.main()
