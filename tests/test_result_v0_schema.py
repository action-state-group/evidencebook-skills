"""Results built by scripts/result_v0.py validate against AAC's evidence-result-v0 schema.

tests/fixtures/evidence-result-v0.json is a byte copy of agent-action-capsule's
`schemas/evidence-result-v0.json` at commit `4ed9a4c65c34a9d5f6eaa30c0aeeda7a77ca92a8` (the claim members `reason`,
section 4.4, and `subject_bundle`, section 4.5), SHA-256 `d15ea64525e71f3e4d21fe90c0db76184590b1449aa5b62a42eff544a17cb7c8`. Section 8a
admits a claim member outside the schema's own set only when its name begins with `x-`;
the judge pin and rule id ride in `x-judge-pin` (producer-private content).
"""
import copy
import hashlib
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import jsonschema  # noqa: E402

from result_v0 import build_result_v0  # noqa: E402
from rollup import all_criteria_from_clauses  # noqa: E402

SCHEMA_PATH = pathlib.Path(__file__).resolve().parent / "fixtures" / "evidence-result-v0.json"
SCHEMA_SHA256 = "d15ea64525e71f3e4d21fe90c0db76184590b1449aa5b62a42eff544a17cb7c8"
GENERATED_AT = "2026-10-26T00:00:00Z"
PIN = {"model_id": "example-judge-1", "model_hosting": "hosted", "input_refs": ["amount_minor"],
       "prompt_template_hash": "bf" * 32, "schema_hash": "df" * 32}


def build(tiers):
    clauses = [{"id": "a.one", "check_id": "a"}, {"id": "a.two", "check_id": "a"}]
    criteria = all_criteria_from_clauses(clauses)
    document, _ = build_result_v0(
        "case-1", {c: "met" for c in criteria}, {c: "cd" * 32 for c in criteria}, GENERATED_AT, criteria,
        "contract@1.0.0", tiers, judge_pin_digests={"a.one": "ab" * 32}, judge_pins={"a.one": PIN},
        rule_ids={"a.one": "9", "a.two": "10"})
    return document


class ResultMatchesSchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = SCHEMA_PATH.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == SCHEMA_SHA256
        cls.validator = jsonschema.Draft202012Validator(json.loads(raw))

    def errors(self, document):
        return [e.message for e in self.validator.iter_errors(document)]

    def test_a_judged_and_a_recomputed_claim_validate(self):
        document = build({"a.one": "judged", "a.two": "recomputed"})
        self.assertEqual(self.errors(document), [])
        one, two = document["claims"]
        self.assertEqual(one["x-judge-pin"], {"rule_id": "9", "pin_digest": "ab" * 32, "pin": PIN})
        self.assertEqual(two["x-judge-pin"], {"rule_id": "10"})
        for claim in document["claims"]:
            for bare in ("rule_id", "judge_pin_digest", "judge_pin"):
                self.assertNotIn(bare, claim)

    def test_a_bare_rule_id_or_pin_key_is_refused_by_the_schema(self):
        for bare, value in (("rule_id", "9"), ("judge_pin_digest", "ab" * 32), ("judge_pin", PIN)):
            document = copy.deepcopy(build({"a.one": "judged", "a.two": "recomputed"}))
            document["claims"][0][bare] = value
            self.assertTrue(self.errors(document), bare)


if __name__ == "__main__":
    unittest.main()
