"""Unit tests for scripts/result_v0.py's internal shape and consistency only.

These do NOT validate against the Evidence Result v0 JSON Schema or `capsulectl
result build`'s Go checker. They check that this module's own output is internally
consistent with the schema's allOf rules (sufficiency <-> verdict; buckets partition
every claim exactly once) and that it fails closed the same way scripts/rollup.py
does.

    python3 -m unittest discover -s tests -p 'test_*.py'
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

from result_v0 import build_result_v0, build_result_v0_for_day, claim_for, resolve_contract_ref  # noqa: E402
from rollup import RollupError, all_criteria_from_clauses  # noqa: E402

CLAUSES = [
    {"id": "policy_compliance.confirmed_before_acting", "check_id": "policy_compliance"},
    {"id": "policy_compliance.within_fare_rules", "check_id": "policy_compliance"},
    {"id": "policy_compliance.no_unrequested_actions", "check_id": "policy_compliance"},
    {"id": "task_resolution.right_reservation", "check_id": "task_resolution"},
    {"id": "task_resolution.right_change", "check_id": "task_resolution"},
    {"id": "task_resolution.done_in_full", "check_id": "task_resolution"},
    {"id": "grounded_communication.prices_from_system", "check_id": "grounded_communication"},
    {"id": "grounded_communication.refunds_match_payment_records", "check_id": "grounded_communication"},
    {"id": "grounded_communication.no_invented_policy", "check_id": "grounded_communication"},
]
ALL_CRITERIA = all_criteria_from_clauses(CLAUSES)
CONTRACT_REF = "airline-support-outcomes@1.3.0"
ALL_MET = {c: "met" for c in ALL_CRITERIA}
ALL_JUDGED = {c: "judged" for c in ALL_CRITERIA}


class ResolveContractRef(unittest.TestCase):
    def test_uses_the_spec_s_own_contract_ref_when_present(self):
        spec = {"contract": "airline-support-outcomes/v1", "contract_ref": "airline-support-outcomes@1.3.0"}
        self.assertEqual(resolve_contract_ref(spec), "airline-support-outcomes@1.3.0")

    def test_falls_back_to_an_at_1_placeholder_with_no_contract_ref_field(self):
        # demo/tau2-outcomes/compiled.json's own shape: hand-authored before
        # contract_ref existed. The fallback must still be schema-shaped
        # (<contract_id>@<version>), never a bare, unversioned contract id.
        spec = {"contract": "tau2-airline-outcomes/v1"}
        self.assertEqual(resolve_contract_ref(spec), "tau2-airline-outcomes/v1@1")

    def test_falls_back_when_contract_ref_is_explicitly_null(self):
        spec = {"contract": "tau2-airline-outcomes/v1", "contract_ref": None}
        self.assertEqual(resolve_contract_ref(spec), "tau2-airline-outcomes/v1@1")


class ClaimFor(unittest.TestCase):
    def test_met_is_satisfied_sufficiency(self):
        c = claim_for("policy_compliance.confirmed_before_acting", "met", CONTRACT_REF, "judged", "ab" * 32)
        self.assertEqual(c["sufficiency"], "SATISFIED")
        self.assertEqual(c["verdict"], "met")
        self.assertEqual(c["contract_ref"], CONTRACT_REF)

    def test_not_met_is_also_satisfied_sufficiency(self):
        c = claim_for("policy_compliance.confirmed_before_acting", "not_met", CONTRACT_REF, "judged", "ab" * 32)
        self.assertEqual(c["sufficiency"], "SATISFIED")

    def test_not_evaluable_is_never_satisfied_sufficiency(self):
        c = claim_for("policy_compliance.confirmed_before_acting", "not_evaluable", CONTRACT_REF, "judged", None)
        self.assertNotEqual(c["sufficiency"], "SATISFIED")
        self.assertEqual(c["verdict"], "not_evaluable")

    def test_no_claim_carries_a_reconcile_or_close_body(self):
        # ClaimType absent == "requirement" (PR #19's binding rule): neither key present.
        c = claim_for("policy_compliance.confirmed_before_acting", "met", CONTRACT_REF, "judged", "ab" * 32)
        self.assertNotIn("reconcile", c)
        self.assertNotIn("close", c)
        self.assertNotIn("type", c)

    def test_evidence_is_absent_without_a_digest_never_invented(self):
        c = claim_for("policy_compliance.confirmed_before_acting", "not_evaluable", CONTRACT_REF, "judged", None)
        self.assertEqual(c["evidence"], [])

    def test_bad_verdict_is_refused(self):
        with self.assertRaisesRegex(RollupError, "not a verdict"):
            claim_for("x", "maybe", CONTRACT_REF, "judged", None)

    def test_tier_is_reported_as_given_never_hardcoded_to_judged(self):
        # tier is a required parameter, never a silent "judged" default -- a
        # criterion later flipped to tier: recomputed (scripts/pack_compile.py)
        # is reported as what it actually is.
        c = claim_for("grounded_communication.prices_from_system", "met", CONTRACT_REF, "recomputed", None)
        self.assertEqual(c["tier"], "recomputed")
        judged = claim_for("policy_compliance.confirmed_before_acting", "met", CONTRACT_REF, "judged", None)
        self.assertEqual(judged["tier"], "judged")

    def test_claim_id_override_for_the_day_level_merge(self):
        c = claim_for("policy_compliance.confirmed_before_acting", "met", CONTRACT_REF, "judged", None,
                       claim_id="tau2:airline:task-1:trial-0::policy_compliance.confirmed_before_acting")
        self.assertEqual(c["id"], "tau2:airline:task-1:trial-0::policy_compliance.confirmed_before_acting")
        # requirement_ref always stays the bare criterion id, even when id is overridden
        self.assertEqual(c["requirement_ref"], "policy_compliance.confirmed_before_acting")


class BuildResultV0(unittest.TestCase):
    def test_all_nine_met_resolves_and_buckets_all_nine_as_met(self):
        doc, resolved = build_result_v0("tau2:airline:task-1:trial-0", ALL_MET, {}, "2026-09-30T00:00:00Z",
                                         ALL_CRITERIA, CONTRACT_REF, ALL_JUDGED)
        self.assertTrue(resolved)
        self.assertEqual(len(doc["claims"]), 9)
        self.assertEqual(sorted(doc["aggregate"]["buckets"]["met"]), sorted(ALL_CRITERIA))
        self.assertEqual(doc["aggregate"]["buckets"]["not_met"], [])
        self.assertEqual(doc["aggregate"]["buckets"]["not_evaluable"], [])
        self.assertEqual(doc["aggregate"]["coverage"]["evaluated_population"], 9)
        self.assertEqual(doc["result_version"], "evidence-result-v0")
        self.assertEqual(doc["claims"][0]["contract_ref"], CONTRACT_REF)

    def test_buckets_partition_every_claim_exactly_once(self):
        verdicts = dict(ALL_MET, **{
            "grounded_communication.prices_from_system": "not_met",
            "task_resolution.done_in_full": "not_evaluable",
        })
        doc, resolved = build_result_v0("case", verdicts, {}, "2026-09-30T00:00:00Z",
                                         ALL_CRITERIA, CONTRACT_REF, ALL_JUDGED)
        self.assertFalse(resolved)
        all_bucketed = doc["aggregate"]["buckets"]["met"] + doc["aggregate"]["buckets"]["not_met"] + doc["aggregate"]["buckets"]["not_evaluable"]
        self.assertEqual(sorted(all_bucketed), sorted(ALL_CRITERIA))
        self.assertEqual(len(all_bucketed), len(set(all_bucketed)))  # exactly once each

    def test_missing_criterion_is_refused_not_silently_resolved(self):
        verdicts = dict(ALL_MET)
        del verdicts["policy_compliance.no_unrequested_actions"]
        with self.assertRaisesRegex(RollupError, "missing criteria"):
            build_result_v0("case", verdicts, {}, "2026-09-30T00:00:00Z", ALL_CRITERIA, CONTRACT_REF, ALL_JUDGED)

    def test_evidence_cites_the_report_digest_when_given(self):
        digests = {"policy_compliance.confirmed_before_acting": "ab" * 32}
        doc, _ = build_result_v0("case", ALL_MET, digests, "2026-09-30T00:00:00Z",
                                  ALL_CRITERIA, CONTRACT_REF, ALL_JUDGED)
        claim = next(c for c in doc["claims"] if c["id"] == "policy_compliance.confirmed_before_acting")
        self.assertEqual(claim["evidence"], [{"digest_alg": "SHA-256", "digest": "ab" * 32}])
        other = next(c for c in doc["claims"] if c["id"] != "policy_compliance.confirmed_before_acting")
        self.assertEqual(other["evidence"], [])

    def test_tiers_flow_from_the_supplied_map_per_criterion(self):
        tiers = {c: "judged" for c in ALL_CRITERIA}
        tiers["grounded_communication.prices_from_system"] = "recomputed"
        doc, _ = build_result_v0("case", ALL_MET, {}, "2026-09-30T00:00:00Z", ALL_CRITERIA, CONTRACT_REF, tiers)
        recomputed = next(c for c in doc["claims"] if c["id"] == "grounded_communication.prices_from_system")
        self.assertEqual(recomputed["tier"], "recomputed")
        judged = next(c for c in doc["claims"] if c["id"] == "policy_compliance.confirmed_before_acting")
        self.assertEqual(judged["tier"], "judged")

    def test_a_different_pack_shape_builds_its_own_contract_ref_and_count(self):
        clauses = [{"id": "a.one", "check_id": "a"}, {"id": "a.two", "check_id": "a"}]
        all_criteria = all_criteria_from_clauses(clauses)
        verdicts = {"a.one": "met", "a.two": "met"}
        doc, resolved = build_result_v0("case", verdicts, {}, "2026-09-30T00:00:00Z",
                                         all_criteria, "some-other-pack@1.0.0", {"a.one": "judged", "a.two": "judged"})
        self.assertTrue(resolved)
        self.assertEqual(len(doc["claims"]), 2)
        self.assertTrue(all(c["contract_ref"] == "some-other-pack@1.0.0" for c in doc["claims"]))


class BuildResultV0ForDay(unittest.TestCase):
    TIERS = {c: "judged" for c in ALL_CRITERIA}

    def test_merges_every_complete_cases_claims_into_one_document(self):
        case_rollups = [
            ("case-a", ALL_MET, {}, self.TIERS),
            ("case-b", ALL_MET, {}, self.TIERS),
        ]
        doc = build_result_v0_for_day("day:2026-09-23", case_rollups, "2026-09-23T23:59:59Z",
                                       ALL_CRITERIA, CONTRACT_REF)
        self.assertEqual(len(doc["claims"]), 18)
        ids = {c["id"] for c in doc["claims"]}
        self.assertIn("case-a::policy_compliance.confirmed_before_acting", ids)
        self.assertIn("case-b::policy_compliance.confirmed_before_acting", ids)
        # requirement_ref stays the bare criterion id, so per-criterion grouping
        # works the same as on a per-case document
        self.assertTrue(all(c["requirement_ref"] in ALL_CRITERIA for c in doc["claims"]))
        self.assertEqual(doc["aggregate"]["coverage"]["evaluated_population"], 18)
        self.assertEqual(sorted(doc["aggregate"]["buckets"]["met"]), sorted(ids))

    def test_buckets_still_partition_every_claim_exactly_once_across_cases(self):
        mixed = dict(self.TIERS)
        verdicts_b = dict(ALL_MET, **{"task_resolution.done_in_full": "not_met"})
        case_rollups = [
            ("case-a", ALL_MET, {}, self.TIERS),
            ("case-b", verdicts_b, {}, mixed),
        ]
        doc = build_result_v0_for_day("day:2026-09-23", case_rollups, "2026-09-23T23:59:59Z",
                                       ALL_CRITERIA, CONTRACT_REF)
        all_bucketed = (doc["aggregate"]["buckets"]["met"] + doc["aggregate"]["buckets"]["not_met"]
                        + doc["aggregate"]["buckets"]["not_evaluable"])
        self.assertEqual(len(all_bucketed), 18)
        self.assertEqual(len(all_bucketed), len(set(all_bucketed)))
        self.assertIn("case-b::task_resolution.done_in_full", doc["aggregate"]["buckets"]["not_met"])

    def test_an_incomplete_case_is_refused_not_silently_dropped(self):
        incomplete = dict(ALL_MET)
        del incomplete["task_resolution.done_in_full"]
        case_rollups = [("case-a", incomplete, {}, self.TIERS)]
        with self.assertRaisesRegex(RollupError, "missing criteria"):
            build_result_v0_for_day("day:2026-09-23", case_rollups, "2026-09-23T23:59:59Z",
                                     ALL_CRITERIA, CONTRACT_REF)

    def test_tier_per_case_claim_comes_from_the_tiers_map_not_hard_coded(self):
        tiers = dict(self.TIERS, **{"grounded_communication.prices_from_system": "recomputed"})
        case_rollups = [("case-a", ALL_MET, {}, tiers)]
        doc = build_result_v0_for_day("day:2026-09-23", case_rollups, "2026-09-23T23:59:59Z",
                                       ALL_CRITERIA, CONTRACT_REF)
        claim = next(c for c in doc["claims"]
                     if c["id"] == "case-a::grounded_communication.prices_from_system")
        self.assertEqual(claim["tier"], "recomputed")

    def test_out_of_scope_criteria_get_no_claim_at_all_across_cases(self):
        verdicts_a = dict(ALL_MET, **{"task_resolution.right_change": "out_of_scope"})
        case_rollups = [("case-a", verdicts_a, {}, self.TIERS), ("case-b", ALL_MET, {}, self.TIERS)]
        doc = build_result_v0_for_day("day:2026-09-23", case_rollups, "2026-09-23T23:59:59Z",
                                       ALL_CRITERIA, CONTRACT_REF, allow_out_of_scope=True)
        self.assertEqual(len(doc["claims"]), 17)  # 8 + 9, not 9 + 9
        claim_ids = {c["id"] for c in doc["claims"]}
        self.assertNotIn("case-a::task_resolution.right_change", claim_ids)
        self.assertIn("case-b::task_resolution.right_change", claim_ids)
        self.assertEqual(doc["aggregate"]["coverage"]["excluded_not_applicable"], 1)
        self.assertEqual(set(doc["aggregate"]["buckets"]), {"met", "not_met", "not_evaluable"})


class OutOfScopeSwitch(unittest.TestCase):
    """Evidence Result v0's Verdict enum is closed to met/not_met/not_evaluable
    (agent-action-capsule's spec/evidence-result-v0.md: "not_applicable has no
    verdict counterpart at all -- it is excluded from the evaluated population
    entirely and only appears as aggregate.coverage.excluded_not_applicable,
    never as a claim"). An out_of_scope criterion -- one that does not apply to
    this case -- is that population exclusion. claim_for() never accepts it,
    with or without the switch -- build_result_v0/build_result_v0_for_day filter an out_of_scope
    criterion out before claim_for is ever called for it."""

    def test_claim_for_never_accepts_out_of_scope(self):
        with self.assertRaisesRegex(RollupError, "not a verdict"):
            claim_for("x", "out_of_scope", CONTRACT_REF, "judged")

    def test_out_of_scope_criteria_get_no_claim_at_all_not_a_bucket(self):
        verdicts = dict(ALL_MET, **{"task_resolution.right_change": "out_of_scope",
                                     "grounded_communication.refunds_match_payment_records": "out_of_scope"})
        doc, resolved = build_result_v0("case", verdicts, {}, "2026-09-30T00:00:00Z",
                                         ALL_CRITERIA, CONTRACT_REF, ALL_JUDGED, allow_out_of_scope=True)
        self.assertTrue(resolved)  # every criterion that applies is met; the two out_of_scope are set aside
        self.assertEqual(len(doc["claims"]), 7)  # nine minus the two out_of_scope
        claim_ids = {c["id"] for c in doc["claims"]}
        self.assertNotIn("task_resolution.right_change", claim_ids)
        self.assertNotIn("grounded_communication.refunds_match_payment_records", claim_ids)
        self.assertEqual(set(doc["aggregate"]["buckets"]), {"met", "not_met", "not_evaluable"})
        self.assertNotIn("task_resolution.right_change", doc["aggregate"]["buckets"]["met"])
        self.assertEqual(doc["aggregate"]["coverage"]["excluded_not_applicable"], 2)
        self.assertEqual(doc["aggregate"]["coverage"]["evaluated_population"], 7)

    def test_out_of_scope_never_becomes_a_not_evaluable_claim(self):
        verdicts = dict(ALL_MET, **{"task_resolution.right_change": "out_of_scope"})
        doc, _ = build_result_v0("case", verdicts, {}, "2026-09-30T00:00:00Z",
                                 ALL_CRITERIA, CONTRACT_REF, ALL_JUDGED, allow_out_of_scope=True)
        self.assertEqual(doc["aggregate"]["buckets"]["not_evaluable"], [])
        self.assertEqual(doc["aggregate"]["coverage"]["unknown_count"], 0)
        self.assertFalse(any(c["verdict"] == "not_evaluable" or c["sufficiency"] == "GAP" for c in doc["claims"]))
        day = build_result_v0_for_day("day:2026-09-30", [("case-a", verdicts, {}, ALL_JUDGED)],
                                      "2026-09-30T00:00:00Z", ALL_CRITERIA, CONTRACT_REF, allow_out_of_scope=True)
        self.assertEqual(day["aggregate"]["buckets"]["not_evaluable"], [])

    def test_not_applicable_is_refused_as_an_input_verdict(self):
        verdicts = dict(ALL_MET, **{"task_resolution.right_change": "not_applicable"})
        with self.assertRaisesRegex(RollupError, "not_applicable is not an adjudicator verdict"):
            build_result_v0("case", verdicts, {}, "2026-09-30T00:00:00Z", ALL_CRITERIA, CONTRACT_REF, ALL_JUDGED,
                            allow_out_of_scope=True)
        with self.assertRaisesRegex(RollupError, "not_applicable is not an adjudicator verdict"):
            build_result_v0_for_day("day:2026-09-30", [("case-a", verdicts, {}, ALL_JUDGED)], "2026-09-30T00:00:00Z",
                                    ALL_CRITERIA, CONTRACT_REF, allow_out_of_scope=True)
        with self.assertRaisesRegex(RollupError, "not a verdict"):
            claim_for("x", "not_applicable", CONTRACT_REF, "judged")

    def test_without_the_switch_the_same_verdicts_are_refused(self):
        verdicts = dict(ALL_MET, **{"task_resolution.right_change": "out_of_scope"})
        with self.assertRaisesRegex(RollupError, "not a verdict"):
            build_result_v0("case", verdicts, {}, "2026-09-30T00:00:00Z", ALL_CRITERIA, CONTRACT_REF, ALL_JUDGED)


if __name__ == "__main__":
    unittest.main()
