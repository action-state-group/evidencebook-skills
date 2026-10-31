"""The weekly run's human ratings validate against AAC's human-rating/v1.

tests/fixtures/human-rating-v1.json is a byte copy of agent-action-capsule's
`schemas/judge/human-rating-v1.json` at commit `1456285979bd759b7828fd3ccc4a24296074e552`,
SHA-256 `b34799cb9ba3ad6099906fd51d8337bff26457453438498ed99e1387684bd5d7`.
"""
import hashlib
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import jsonschema  # noqa: E402

from human_rating import counted, human_rating_record  # noqa: E402

SCHEMA_PATH = pathlib.Path(__file__).resolve().parent / "fixtures" / "human-rating-v1.json"
SCHEMA_SHA256 = "b34799cb9ba3ad6099906fd51d8337bff26457453438498ed99e1387684bd5d7"
REPORT = "ab" * 32


class HumanRatingMatchesSchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = SCHEMA_PATH.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == SCHEMA_SHA256, "the schema copy is not the pinned AAC file"
        cls.validator = jsonschema.Draft202012Validator(json.loads(raw), format_checker=jsonschema.FormatChecker())

    def record(self, label="met"):
        return human_rating_record("case-1", "2026-W43", REPORT, label, "rater:expert-7", "2026-10-25T23:59:59Z")

    def test_every_label_validates(self):
        for label in ("met", "not_met", "not_evaluable", "out_of_scope"):
            errors = sorted(self.validator.iter_errors(self.record(label)), key=str)
            self.assertEqual(errors, [], [e.message for e in errors])

    def test_the_case_is_pinned_to_the_audited_report(self):
        record = self.record()
        self.assertEqual(record["case"], {"type": "evaluation-report", "digest_alg": "SHA-256", "digest": REPORT,
                                          "citation_purpose": "rated_case"})
        self.assertTrue(record["blind"])
        self.assertEqual(record["rater_ref"], "rater:expert-7")

    def test_no_member_the_schema_lacks(self):
        self.assertEqual(set(self.record()), {"record_version", "record_id", "epistemic_type", "rated_at", "blind",
                                              "rater_ref", "case", "label"})

    def test_only_met_and_not_met_are_counted(self):
        rated = [{"case_id": c, "rating": r} for c, r in
                 (("a", "met"), ("b", "not_met"), ("c", "not_evaluable"), ("d", "out_of_scope"))]
        self.assertEqual([r["case_id"] for r in counted(rated)], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
