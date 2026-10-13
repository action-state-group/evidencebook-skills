"""Unit tests for scripts/rollup.py's pure combine/check/all-required logic.

    python3 -m unittest discover -s tests -p 'test_*.py'
"""
import itertools
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

from rollup import (OUT_OF_SCOPE, VERDICTS_WITH_OOS, RollupError, all_criteria_from_clauses,  # noqa: E402
                    all_required_met, checks_from_clauses, check_verdicts, combine,
                    never_out_of_scope_from_clauses)

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


class OutOfScopeSwitch(unittest.TestCase):
    """The out_of_scope_verdict switch: off by default (every call above never
    passes allow_out_of_scope, so "out_of_scope" stays an unrecognized verdict
    there), on here -- set aside beside a met (never counted as met), never
    resolves on its own, and never gets silently relabelled "met" in the
    caller's own criterion_verdicts."""

    def test_out_of_scope_is_refused_when_the_switch_is_off(self):
        with self.assertRaisesRegex(RollupError, "not a verdict"):
            combine(["met", "out_of_scope"])

    def test_out_of_scope_is_set_aside_beside_a_met_when_allowed(self):
        # "met" here is the met criterion's own verdict; the out_of_scope one adds nothing to it
        self.assertEqual(combine(["met", "out_of_scope"], allow_out_of_scope=True), "met")

    def test_all_out_of_scope_is_never_met(self):
        # Nothing was checked: the combination is out_of_scope, and a
        # conversation on which every criterion is out_of_scope is NOT resolved.
        self.assertEqual(combine(["out_of_scope", "out_of_scope"], allow_out_of_scope=True), "out_of_scope")
        all_oos = {c: "out_of_scope" for c in ALL_CRITERIA}
        self.assertFalse(all_required_met(all_oos, ALL_CRITERIA, allow_out_of_scope=True))

    def test_a_never_out_of_scope_criterion_judged_out_of_scope_is_refused(self):
        never = never_out_of_scope_from_clauses(
            [dict(c, never_out_of_scope=True) if c["id"] in ("task_resolution.done_in_full",
                                                                 "grounded_communication.no_invented_policy")
             else c for c in CLAUSES])
        self.assertEqual(never, {"task_resolution.done_in_full", "grounded_communication.no_invented_policy"})
        verdicts = dict(ALL_MET, **{"task_resolution.done_in_full": "out_of_scope"})
        with self.assertRaisesRegex(RollupError, "may never be out_of_scope"):
            all_required_met(verdicts, ALL_CRITERIA, allow_out_of_scope=True, never_out_of_scope=never)
        # the same verdicts resolve when no criterion is marked
        self.assertTrue(all_required_met(verdicts, ALL_CRITERIA, allow_out_of_scope=True))

    def test_not_met_still_beats_out_of_scope(self):
        self.assertEqual(combine(["not_met", "out_of_scope"], allow_out_of_scope=True), "not_met")

    def test_not_evaluable_still_beats_out_of_scope(self):
        self.assertEqual(combine(["not_evaluable", "out_of_scope"], allow_out_of_scope=True), "not_evaluable")

    def test_all_required_met_resolves_over_the_criteria_that_apply_when_allowed(self):
        verdicts = dict(ALL_MET, **{"task_resolution.right_change": "out_of_scope",
                                     "grounded_communication.refunds_match_payment_records": "out_of_scope"})
        self.assertTrue(all_required_met(verdicts, ALL_CRITERIA, allow_out_of_scope=True))
        # and still refused as an unrecognized verdict when the switch is off
        with self.assertRaisesRegex(RollupError, "not a verdict"):
            all_required_met(verdicts, ALL_CRITERIA)

    def test_check_verdicts_reports_out_of_scope_criteria_without_folding_to_met(self):
        verdicts = dict(ALL_MET, **{"task_resolution.right_change": "out_of_scope"})
        checks = check_verdicts(verdicts, CHECKS, allow_out_of_scope=True)
        self.assertEqual(checks["task_resolution"], "met")  # its two criteria that apply are met
        self.assertEqual(verdicts["task_resolution.right_change"], "out_of_scope")  # never rewritten


class OutOfScopeNeverSatisfies(unittest.TestCase):
    """out_of_scope means the criterion does not apply to this case: neither met
    nor not_met. It never counts toward satisfying anything -- not a criterion, not
    a check, not all_required_met -- and it is never folded into not_evaluable
    (which means the criterion applies and could not be determined)."""

    SMALL = ("a", "b", "c")

    def test_out_of_scope_never_counts_toward_satisfaction(self):
        # Every assignment of the four verdicts to three criteria: the case resolves
        # exactly when at least one criterion is actually met and every criterion
        # that is not out_of_scope is met. An out_of_scope verdict is never counted
        # as the met, so swapping any met for out_of_scope can only lose a resolve.
        for combo in itertools.product(VERDICTS_WITH_OOS, repeat=len(self.SMALL)):
            verdicts = dict(zip(self.SMALL, combo))
            resolved = all_required_met(verdicts, self.SMALL, allow_out_of_scope=True)
            with self.subTest(verdicts=verdicts):
                self.assertEqual(resolved, combo.count("met") >= 1
                                 and combo.count("met") + combo.count(OUT_OF_SCOPE) == len(combo))
                if combine(combo, allow_out_of_scope=True) == "met":
                    self.assertIn("met", combo)
                for i, v in enumerate(combo):
                    if v == "met":
                        swapped = dict(verdicts, **{self.SMALL[i]: OUT_OF_SCOPE})
                        self.assertLessEqual(all_required_met(swapped, self.SMALL, allow_out_of_scope=True), resolved)
                if not resolved:
                    for i, v in enumerate(combo):
                        if v != "met":
                            swapped = dict(verdicts, **{self.SMALL[i]: OUT_OF_SCOPE})
                            if any(w not in ("met", OUT_OF_SCOPE) for j, w in enumerate(combo) if j != i):
                                self.assertFalse(all_required_met(swapped, self.SMALL, allow_out_of_scope=True))

    def test_a_check_with_no_criterion_that_applies_is_never_met(self):
        verdicts = dict(ALL_MET, **{c: "out_of_scope" for c in CHECKS["task_resolution"]})
        checks = check_verdicts(verdicts, CHECKS, allow_out_of_scope=True)
        self.assertEqual(checks["task_resolution"], "out_of_scope")

    def test_out_of_scope_is_never_aliased_to_not_evaluable(self):
        # combine() yields not_evaluable only when a not_evaluable was put in: no
        # out_of_scope, in any mix, ever turns into one.
        for combo in itertools.product(VERDICTS_WITH_OOS, repeat=3):
            with self.subTest(combo=combo):
                if combine(combo, allow_out_of_scope=True) == "not_evaluable":
                    self.assertIn("not_evaluable", combo)
        self.assertEqual(combine([OUT_OF_SCOPE], allow_out_of_scope=True), OUT_OF_SCOPE)

    def test_not_applicable_is_refused_as_a_verdict_by_name(self):
        for allow in (False, True):
            with self.subTest(allow_out_of_scope=allow):
                with self.assertRaisesRegex(RollupError, "not_applicable is not an adjudicator verdict"):
                    combine(["met", "not_applicable"], allow_out_of_scope=allow)
                with self.assertRaisesRegex(RollupError, "not_applicable is not an adjudicator verdict"):
                    all_required_met(dict(ALL_MET, **{"task_resolution.right_change": "not_applicable"}),
                                     ALL_CRITERIA, allow_out_of_scope=allow)


if __name__ == "__main__":
    unittest.main()
