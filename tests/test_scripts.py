"""Unit tests for the exercise scripts' pure logic (no capsulectl, no book).

    python3 -m unittest discover -s tests -p 'test_*.py'
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import datetime  # noqa: E402

from capsulectl_calls import EvidenceUnavailable, committed_on, parse_rfc3339  # noqa: E402
from run_daily import checked_answer  # noqa: E402
from run_weekly import PACKET_FIELDS, blind_packet, checked_ratings, is_judged, week_frame  # noqa: E402

REPORT = {"record_type": "evaluation-report/v1", "case_id": "tau2:airline:task-1:trial-0",
          "clause_id": "policy-followed", "verdict": "met", "rationale": "the agent refunded correctly",
          "judge_pin_digest": "ab" * 32, "stratum": "met", "source_capsule_id": "cd" * 32}
CASE = {"case": {"task_id": "1"}, "agent_interaction": {"messages": [{"role": "user", "content": "cancel"}]}}


class BlindPacket(unittest.TestCase):
    def test_carries_only_the_whitelisted_fields(self):
        packet = blind_packet(REPORT, CASE)
        self.assertEqual(tuple(packet), PACKET_FIELDS)
        for leaked in ("verdict", "rationale", "judge_pin_digest", "stratum", "source_capsule_id", "record_type"):
            self.assertNotIn(leaked, packet)

    def test_reference_files_default_to_airline_and_follow_the_contract(self):
        packet = blind_packet(REPORT, CASE)
        self.assertEqual((packet["policy"], packet["booking_db"]), ("airline-data/policy.md", "airline-data/db.json"))
        named = {"policy": "data/p.md", "booking_db": "data/db.json"}
        packet = blind_packet(REPORT, CASE, named)
        self.assertEqual((packet["policy"], packet["booking_db"]), ("data/p.md", "data/db.json"))

    def test_no_value_of_the_report_but_its_case_and_clause_reaches_the_packet(self):
        packet = blind_packet(REPORT, CASE)
        leaked = {REPORT["verdict"], REPORT["rationale"], REPORT["judge_pin_digest"], REPORT["source_capsule_id"]}
        self.assertFalse(leaked & {v for v in packet.values() if isinstance(v, str)})


class JudgedFrame(unittest.TestCase):
    def test_a_judged_report_is_in_the_frame(self):
        self.assertTrue(is_judged({"record_type": "evaluation-report/v1", "judge_pin_digest": "ab" * 32}))

    def test_a_recomputed_report_has_no_judge_pin_and_is_not(self):
        self.assertFalse(is_judged({"record_type": "evaluation-report/v1"}))
        self.assertFalse(is_judged({"record_type": "evaluation-report/v1", "judge_pin_digest": ""}))


class WeekFrame(unittest.TestCase):
    DAYS = {"2026-10-19", "2026-10-20"}
    BODIES = {
        "judged": {"record_type": "evaluation-report/v1", "period": "day:2026-10-19", "judge_pin_digest": "ab" * 32},
        "recomputed": {"record_type": "evaluation-report/v1", "period": "day:2026-10-19"},
        "other-week": {"record_type": "evaluation-report/v1", "period": "day:2026-09-01", "judge_pin_digest": "ab" * 32},
        "not-a-report": {"record_type": "sample-manifest/v1", "period": "day:2026-10-19"},
        "judged-2": {"record_type": "evaluation-report/v1", "period": "day:2026-10-20", "judge_pin_digest": "cd" * 32},
    }

    def run_frame(self):
        checked = []
        reports, unjudged = week_frame([{"capsule_id": k} for k in self.BODIES], self.BODIES.__getitem__, checked.append, self.DAYS)
        return reports, unjudged, checked

    def test_only_the_weeks_judged_reports_are_in_the_frame_and_verified(self):
        reports, _, checked = self.run_frame()
        self.assertEqual([rid for rid, _ in reports], ["judged", "judged-2"])
        self.assertEqual(checked, ["judged", "judged-2"], "an unjudged report is never verified")

    def test_unjudged_reports_of_the_week_are_counted_not_dropped_silently(self):
        _, unjudged, _ = self.run_frame()
        self.assertEqual(unjudged, 1, "only the week's unjudged report counts, not another week's or another record type")


class CheckedRatings(unittest.TestCase):
    SAMPLE = {"a", "b"}

    def test_a_rating_with_no_rater_ref_anywhere_is_refused_before_any_is_sealed(self):
        ratings = [{"case_id": "a", "rating": "met", "rater_ref": "r:1"}, {"case_id": "b", "rating": "met"}]
        with self.assertRaisesRegex(ValueError, "no usable rater_ref"):
            checked_ratings(ratings, self.SAMPLE)

    def test_the_flag_fills_in_for_a_rating_with_none_and_a_rating_own_ref_wins(self):
        got = checked_ratings([{"case_id": "a", "rating": "met", "rater_ref": "r:own"}, {"case_id": "b", "rating": "met"}],
                              self.SAMPLE, rater_ref="r:flag")
        self.assertEqual([r["rater_ref"] for r in got], ["r:own", "r:flag"])

    def test_a_blank_padded_or_non_string_rater_ref_is_refused_not_replaced_by_the_flag(self):
        for bad in ("", "  ", " r:1 ", 0, None, ["r:1"]):
            with self.assertRaisesRegex(ValueError, "no usable rater_ref"):
                checked_ratings([{"case_id": "a", "rating": "met", "rater_ref": bad}], self.SAMPLE, rater_ref="r:flag")

    def test_one_rating_per_sampled_case_passes(self):
        ratings = [{"case_id": "a", "rating": "met"}, {"case_id": "b", "rating": "not_met"}]
        self.assertEqual(checked_ratings(ratings, self.SAMPLE, rater_ref="r:1"), [{**r, "rater_ref": "r:1"} for r in ratings])

    def test_fewer_ratings_than_drawn_pass_and_leave_a_shortfall(self):
        self.assertEqual(len(checked_ratings([{"case_id": "a", "rating": "met"}], self.SAMPLE, rater_ref="r:1")), 1)

    def test_a_second_rating_for_one_case_is_refused(self):
        with self.assertRaisesRegex(ValueError, "more than one rating"):
            checked_ratings([{"case_id": "a", "rating": "met"}, {"case_id": "a", "rating": "not_met"}], self.SAMPLE, rater_ref="r:1")

    def test_a_rating_outside_the_sample_is_refused(self):
        with self.assertRaisesRegex(ValueError, "outside the sample"):
            checked_ratings([{"case_id": "z", "rating": "met"}], self.SAMPLE)

    def test_a_rating_that_is_not_a_verdict_is_refused(self):
        with self.assertRaisesRegex(ValueError, "not one of met, not_evaluable, not_met"):
            checked_ratings([{"case_id": "a", "rating": "yes"}], self.SAMPLE)

    def test_out_of_scope_is_refused_unless_the_contract_allows_it(self):
        with self.assertRaisesRegex(ValueError, "not one of met, not_evaluable, not_met$"):
            checked_ratings([{"case_id": "a", "rating": "out_of_scope"}], self.SAMPLE)

    def test_out_of_scope_is_refused_on_a_never_out_of_scope_clause_even_with_the_switch_on(self):
        # "b"'s sampled report is on a clause marked never_out_of_scope: the
        # judge could never answer it, so the rating would be sealed and count
        # against the judge as a disagreement.
        with self.assertRaisesRegex(ValueError, "'b' is not one of met, not_evaluable, not_met$"):
            checked_ratings([{"case_id": "b", "rating": "out_of_scope"}], self.SAMPLE,
                            allow_out_of_scope=True, never_out_of_scope_cases={"b"}, rater_ref="r:1")
        ratings = [{"case_id": "a", "rating": "out_of_scope"}, {"case_id": "b", "rating": "met"}]
        self.assertEqual(checked_ratings(ratings, self.SAMPLE, allow_out_of_scope=True,
                                         never_out_of_scope_cases={"b"}, rater_ref="r:1"),
                         [{**r, "rater_ref": "r:1"} for r in ratings])

    def test_out_of_scope_is_a_rating_when_the_contract_allows_it(self):
        ratings = [{"case_id": "a", "rating": "out_of_scope"}, {"case_id": "b", "rating": "met"}]
        self.assertEqual(checked_ratings(ratings, self.SAMPLE, allow_out_of_scope=True, rater_ref="r:1"), [{**r, "rater_ref": "r:1"} for r in ratings])
        with self.assertRaisesRegex(ValueError, "not one of met, not_evaluable, not_met, out_of_scope"):
            checked_ratings([{"case_id": "a", "rating": "yes"}], self.SAMPLE, allow_out_of_scope=True)


class ParseRfc3339(unittest.TestCase):
    """capsulectl's real appended_at timestamps carry Go's trailing-zero-trimmed
    fractional seconds -- any digit count, not just the 3 or 6 Python's
    fromisoformat (pre-3.11) accepts. Found via tests/fresh_env_outcomes.sh's 50-case
    run: a Close capsule's real wall-clock append time (5 fractional digits)
    crashed a second daily-judge-and-close run."""

    def test_no_fraction_parses(self):
        self.assertEqual(parse_rfc3339("2026-09-23T12:00:00Z").date(), datetime.date(2026, 9, 23))

    def test_six_digit_fraction_parses(self):
        self.assertEqual(parse_rfc3339("2026-09-30T23:12:51.781403Z").date(), datetime.date(2026, 9, 30))

    def test_five_digit_fraction_parses(self):
        self.assertEqual(parse_rfc3339("2026-09-30T23:21:38.01987+00:00").date(), datetime.date(2026, 9, 30))

    def test_one_digit_fraction_parses(self):
        self.assertEqual(parse_rfc3339("2026-09-30T23:12:54.3Z").date(), datetime.date(2026, 9, 30))

    def test_committed_on_uses_the_same_tolerant_parse(self):
        entry = {"appended_at": "2026-09-30T23:21:38.01987+00:00"}
        self.assertTrue(committed_on(entry, datetime.date(2026, 9, 30)))
        self.assertFalse(committed_on(entry, datetime.date(2026, 9, 29)))


class CheckedAnswer(unittest.TestCase):
    def test_each_verdict_passes(self):
        for verdict in ("met", "not_met", "not_evaluable"):
            self.assertEqual(checked_answer({"verdict": verdict})["verdict"], verdict)

    def test_anything_else_is_refused(self):
        for answer in ({"verdict": "pass"}, {}, None, "met"):
            with self.assertRaises(EvidenceUnavailable):
                checked_answer(answer)


if __name__ == "__main__":
    unittest.main()


class CitedTestsExist(unittest.TestCase):
    """A script, skill or doc that points a reader at a test file names one
    that exists: scripts/pack_compile.py once cited a
    tests/test_judge_pin_airline.py that never did."""

    def test_every_cited_test_file_exists(self):
        import re
        root = pathlib.Path(__file__).resolve().parents[1]
        cited = set()
        for base in ("scripts", "skills", "docs"):
            for path in (root / base).rglob("*"):
                if path.suffix in (".py", ".md", ".sh") and path.is_file():
                    cited.update(re.findall(r"tests/[A-Za-z0-9_./-]+\.(?:py|sh)", path.read_text()))
        self.assertTrue(cited)
        self.assertEqual(sorted(c for c in cited if not (root / c).exists()), [])
