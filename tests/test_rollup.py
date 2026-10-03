"""Unit tests for scripts/rollup.py's pure combine/check/all-required logic.

    python3 -m unittest discover -s tests -p 'test_*.py'
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

from rollup import (RollupError, all_criteria_from_clauses, all_required_met,  # noqa: E402
                    checks_from_clauses, check_verdicts, combine, never_not_applicable_from_clauses)

# A nine-criteria, three-check fixture (the airline pack's own shape) -- plain data, not
# imported from any compiled contract, so these tests stay pure and don't depend on
# pack_compile.py's output.
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
CHECKS = checks_from_clauses(CLAUSES)
ALL_CRITERIA = all_criteria_from_clauses(CLAUSES)
ALL_MET = {c: "met" for c in ALL_CRITERIA}

# A differently-shaped fixture (two checks, two criteria each) -- proves the rollup
# is actually pack-driven, not secretly still hardcoded to nine criteria / three
# checks: this is what the edit-criteria-and-recompile loop depends on.
SMALL_CLAUSES = [
    {"id": "a.one", "check_id": "a"},
    {"id": "a.two", "check_id": "a"},
    {"id": "b.one", "check_id": "b"},
    {"id": "b.two", "check_id": "b"},
]
SMALL_CHECKS = checks_from_clauses(SMALL_CLAUSES)
SMALL_ALL_CRITERIA = all_criteria_from_clauses(SMALL_CLAUSES)


class Combine(unittest.TestCase):
    def test_all_met_is_met(self):
        self.assertEqual(combine(["met", "met", "met"]), "met")

    def test_any_not_met_wins_over_everything(self):
        self.assertEqual(combine(["met", "not_met", "not_evaluable"]), "not_met")

    def test_not_evaluable_beats_met_when_no_not_met(self):
        self.assertEqual(combine(["met", "not_evaluable"]), "not_evaluable")

    def test_empty_is_refused(self):
        with self.assertRaisesRegex(RollupError, "at least one"):
            combine([])

    def test_not_a_verdict_is_refused(self):
        with self.assertRaisesRegex(RollupError, "not a verdict"):
            combine(["met", "maybe"])


class ChecksFromClauses(unittest.TestCase):
    def test_groups_by_check_id_in_first_seen_order(self):
        self.assertEqual(CHECKS["policy_compliance"],
                          ("policy_compliance.confirmed_before_acting",
                           "policy_compliance.within_fare_rules",
                           "policy_compliance.no_unrequested_actions"))

    def test_all_criteria_is_every_clause_id_in_order(self):
        self.assertEqual(ALL_CRITERIA[0], "policy_compliance.confirmed_before_acting")
        self.assertEqual(len(ALL_CRITERIA), 9)

    def test_a_different_shape_is_not_coerced_to_nine(self):
        self.assertEqual(SMALL_CHECKS, {"a": ("a.one", "a.two"), "b": ("b.one", "b.two")})
        self.assertEqual(SMALL_ALL_CRITERIA, ("a.one", "a.two", "b.one", "b.two"))


class CheckVerdicts(unittest.TestCase):
    def test_all_nine_met_gives_three_met_checks(self):
        self.assertEqual(
            check_verdicts(ALL_MET, CHECKS),
            {"policy_compliance": "met", "task_resolution": "met", "grounded_communication": "met"},
        )

    def test_one_not_met_criterion_fails_only_its_own_check(self):
        verdicts = dict(ALL_MET, **{"grounded_communication.prices_from_system": "not_met"})
        result = check_verdicts(verdicts, CHECKS)
        self.assertEqual(result["grounded_communication"], "not_met")
        self.assertEqual(result["policy_compliance"], "met")
        self.assertEqual(result["task_resolution"], "met")

    def test_missing_criterion_is_refused_not_silently_passed(self):
        verdicts = dict(ALL_MET)
        del verdicts["task_resolution.done_in_full"]
        with self.assertRaisesRegex(RollupError, "missing criteria"):
            check_verdicts(verdicts, CHECKS)

    def test_a_smaller_pack_rolls_up_on_its_own_shape(self):
        verdicts = {"a.one": "met", "a.two": "met", "b.one": "met", "b.two": "not_met"}
        self.assertEqual(check_verdicts(verdicts, SMALL_CHECKS), {"a": "met", "b": "not_met"})


class AllRequiredMet(unittest.TestCase):
    def test_all_nine_met_is_resolved(self):
        self.assertTrue(all_required_met(ALL_MET, ALL_CRITERIA))

    def test_one_not_met_is_not_resolved(self):
        verdicts = dict(ALL_MET, **{"policy_compliance.within_fare_rules": "not_met"})
        self.assertFalse(all_required_met(verdicts, ALL_CRITERIA))

    def test_one_not_evaluable_is_not_resolved(self):
        verdicts = dict(ALL_MET, **{"task_resolution.right_change": "not_evaluable"})
        self.assertFalse(all_required_met(verdicts, ALL_CRITERIA))

    def test_missing_criterion_is_refused(self):
        verdicts = dict(ALL_MET)
        del verdicts["grounded_communication.no_invented_policy"]
        with self.assertRaisesRegex(RollupError, "missing criteria"):
            all_required_met(verdicts, ALL_CRITERIA)

    def test_unrecognized_criterion_is_refused(self):
        verdicts = dict(ALL_MET, **{"not_a_real_criterion": "met"})
        with self.assertRaisesRegex(RollupError, "unrecognized criteria"):
            all_required_met(verdicts, ALL_CRITERIA)

    def test_a_smaller_pack_resolves_on_its_own_shape(self):
        self.assertTrue(all_required_met({"a.one": "met", "a.two": "met", "b.one": "met", "b.two": "met"},
                                          SMALL_ALL_CRITERIA))
        self.assertFalse(all_required_met({"a.one": "met", "a.two": "met", "b.one": "met", "b.two": "not_met"},
                                           SMALL_ALL_CRITERIA))


class NotApplicableSwitch(unittest.TestCase):
    """The not_applicable_verdict switch: off by default (every call above never
    passes allow_not_applicable, so "not_applicable" stays an unrecognized verdict
    there), on here -- passes beside a met, never resolves on its own, and never
    gets silently relabelled "met" in the caller's own criterion_verdicts."""

    def test_not_applicable_is_refused_when_the_switch_is_off(self):
        with self.assertRaisesRegex(RollupError, "not a verdict"):
            combine(["met", "not_applicable"])

    def test_not_applicable_counts_as_passing_when_allowed(self):
        self.assertEqual(combine(["met", "not_applicable"], allow_not_applicable=True), "met")

    def test_all_not_applicable_is_never_met(self):
        # Nothing was checked: the combination is not_applicable, and a
        # conversation on which every criterion is not_applicable is NOT resolved.
        self.assertEqual(combine(["not_applicable", "not_applicable"], allow_not_applicable=True), "not_applicable")
        all_na = {c: "not_applicable" for c in ALL_CRITERIA}
        self.assertFalse(all_required_met(all_na, ALL_CRITERIA, allow_not_applicable=True))

    def test_a_never_not_applicable_criterion_judged_not_applicable_is_refused(self):
        never = never_not_applicable_from_clauses(
            [dict(c, never_not_applicable=True) if c["id"] in ("task_resolution.done_in_full",
                                                                 "grounded_communication.no_invented_policy")
             else c for c in CLAUSES])
        self.assertEqual(never, {"task_resolution.done_in_full", "grounded_communication.no_invented_policy"})
        verdicts = dict(ALL_MET, **{"task_resolution.done_in_full": "not_applicable"})
        with self.assertRaisesRegex(RollupError, "may never be not_applicable"):
            all_required_met(verdicts, ALL_CRITERIA, allow_not_applicable=True, never_not_applicable=never)
        # the same verdicts resolve when no criterion is marked
        self.assertTrue(all_required_met(verdicts, ALL_CRITERIA, allow_not_applicable=True))

    def test_not_met_still_beats_not_applicable(self):
        self.assertEqual(combine(["not_met", "not_applicable"], allow_not_applicable=True), "not_met")

    def test_not_evaluable_still_beats_not_applicable(self):
        self.assertEqual(combine(["not_evaluable", "not_applicable"], allow_not_applicable=True), "not_evaluable")

    def test_all_required_met_passes_with_not_applicable_criteria_when_allowed(self):
        verdicts = dict(ALL_MET, **{"task_resolution.right_change": "not_applicable",
                                     "grounded_communication.refunds_match_payment_records": "not_applicable"})
        self.assertTrue(all_required_met(verdicts, ALL_CRITERIA, allow_not_applicable=True))
        # and still refused as an unrecognized verdict when the switch is off
        with self.assertRaisesRegex(RollupError, "not a verdict"):
            all_required_met(verdicts, ALL_CRITERIA)

    def test_check_verdicts_reports_not_applicable_criteria_without_folding_to_met(self):
        verdicts = dict(ALL_MET, **{"task_resolution.right_change": "not_applicable"})
        checks = check_verdicts(verdicts, CHECKS, allow_not_applicable=True)
        self.assertEqual(checks["task_resolution"], "met")  # the check as a whole still passes
        self.assertEqual(verdicts["task_resolution.right_change"], "not_applicable")  # never rewritten


if __name__ == "__main__":
    unittest.main()
