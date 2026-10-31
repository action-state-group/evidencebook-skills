"""The weekly run's calibration summaries validate against AAC's calibration-summary/v1.

tests/fixtures/calibration-summary-v1.json is a byte copy of agent-action-capsule's
`schemas/judge/calibration-summary-v1.json` at commit `1456285979bd759b7828fd3ccc4a24296074e552`
(main when #74 was fixed), SHA-256 `2801e9e3865b756c8d73a5b7bb75c840db2d07c41626f11863ef9c16d48c752f`.
The schema cannot say k <= n; spec section 8 makes a verifier check it, so the test does.
"""
import hashlib
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import jsonschema  # noqa: E402

from calibration_summary import calibration_summaries  # noqa: E402

SCHEMA_PATH = pathlib.Path(__file__).resolve().parent / "fixtures" / "calibration-summary-v1.json"
SCHEMA_SHA256 = "2801e9e3865b756c8d73a5b7bb75c840db2d07c41626f11863ef9c16d48c752f"
PIN_A, PIN_B = "ab" * 32, "cd" * 32
NOW = "2026-10-25T23:59:59Z"


def report(case, clause, verdict, pin=PIN_A):
    return (f"capsule-{case}", {"case_id": case, "clause_id": clause, "verdict": verdict, "judge_pin_digest": pin})


SELECTED = [report("c1", "a.one", "met"), report("c2", "a.one", "not_met"), report("c3", "a.two", "met"),
            report("c4", "a.two", "met", PIN_B)]


def summaries(rated):
    return calibration_summaries(SELECTED, rated, "contract@1.0.0", "2026-W43", NOW)


class CalibrationSummaryMatchesSchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = SCHEMA_PATH.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == SCHEMA_SHA256, "the schema copy is not the pinned AAC file"
        cls.validator = jsonschema.Draft202012Validator(json.loads(raw), format_checker=jsonschema.FormatChecker())

    def assert_valid(self, record):
        errors = sorted(self.validator.iter_errors(record), key=str)
        self.assertEqual(errors, [], [e.message for e in errors])
        for clause in record["clauses"]:
            for member in ("agreement", "drift"):
                self.assertLessEqual(clause[member]["k"], clause[member]["n"], f"{clause['clause_ref']} {member}")

    def test_every_record_validates_and_k_does_not_exceed_n(self):
        rated = [{"case_id": "c1", "rating": "met"}, {"case_id": "c2", "rating": "met"},
                 {"case_id": "c3", "rating": "not_met"}, {"case_id": "c4", "rating": "met"}]
        records = summaries(rated)
        self.assertEqual(len(records), 2, "one record per judge pin")
        for record in records:
            self.assert_valid(record)

    def test_agreement_is_counted_per_clause_and_pin(self):
        rated = [{"case_id": "c1", "rating": "met"}, {"case_id": "c2", "rating": "met"},
                 {"case_id": "c3", "rating": "not_met"}, {"case_id": "c4", "rating": "met"}]
        a, b = summaries(rated)
        self.assertEqual(a["judge_pin"], {"type": "judge_pin", "digest_alg": "SHA-256", "digest": PIN_A,
                                          "citation_purpose": "calibrates"})
        self.assertEqual([(c["clause_ref"], c["agreement"]) for c in a["clauses"]],
                         [("a.one", {"k": 1, "n": 2}), ("a.two", {"k": 0, "n": 1})])
        self.assertEqual([(c["clause_ref"], c["agreement"]) for c in b["clauses"]], [("a.two", {"k": 1, "n": 1})])

    def test_a_drawn_case_without_a_rating_is_not_in_n(self):
        a, _ = summaries([{"case_id": "c1", "rating": "met"}])
        self.assert_valid(a)
        self.assertEqual([(c["clause_ref"], c["agreement"]) for c in a["clauses"]],
                         [("a.one", {"k": 1, "n": 1}), ("a.two", {"k": 0, "n": 0})])

    def test_drift_is_unmeasured_not_zero_drift(self):
        for record in summaries([{"case_id": "c1", "rating": "met"}]):
            self.assertTrue(all(c["drift"] == {"k": 0, "n": 0} for c in record["clauses"]))

    def test_no_rate_and_no_member_the_schema_lacks(self):
        for record in summaries([{"case_id": "c1", "rating": "met"}]):
            self.assertEqual(set(record), {"record_version", "record_id", "epistemic_type", "computed_at", "judge_pin", "clauses"})
            self.assertFalse([k for c in record["clauses"] for m in ("agreement", "drift") for k in c[m]
                              if k not in ("k", "n")], "k and n only, never a rate")

    def test_not_evaluable_and_out_of_scope_ratings_are_in_neither_k_nor_n(self):
        rated = [{"case_id": "c1", "rating": "met"}, {"case_id": "c2", "rating": "not_evaluable"},
                 {"case_id": "c3", "rating": "out_of_scope"}]
        a, _ = summaries(rated)
        self.assertEqual([(c["clause_ref"], c["agreement"]) for c in a["clauses"]],
                         [("a.one", {"k": 1, "n": 1}), ("a.two", {"k": 0, "n": 0})])

    def test_an_empty_sample_seals_no_summary(self):
        self.assertEqual(calibration_summaries([], [], "contract@1.0.0", "2026-W43", NOW), [])

    def test_record_ids_are_unique_per_pin_and_week(self):
        a, b = summaries([])
        self.assertNotEqual(a["record_id"], b["record_id"])
        self.assertIn("2026-W43", a["record_id"])
        self.assertEqual(a["record_id"], calibration_summaries(SELECTED, [], "contract@1.0.0", "2026-W43", NOW)[0]["record_id"])


if __name__ == "__main__":
    unittest.main()
