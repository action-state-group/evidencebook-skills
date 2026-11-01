"""scripts/day_record.py: the span, case-column and run-time fields (evidencebook-skills#95).
Synthetic data only."""
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import jsonschema  # noqa: E402

import day_record as dr  # noqa: E402
from result_v0 import build_result_v0_for_day, merge_result_v0_documents  # noqa: E402
from rollup import RollupError, all_criteria_from_clauses  # noqa: E402
from subject_history import build_subject_history, extension_name  # noqa: E402

SCHEMA = pathlib.Path(__file__).resolve().parent / "fixtures" / "evidence-result-v0.json"
PACK = "airline-support-outcomes"
CLAUSES = [{"id": "a.one", "check_id": "a"}, {"id": "a.two", "check_id": "a", "requirement_tier": "must_have"},
           {"id": "b.three", "check_id": "b"}]
CONVO = [{"role": "assistant", "tool_calls": [{"id": "c1", "name": "cancel_reservation", "arguments": {}}]},
         {"role": "tool", "tool_call_id": "c1", "content": json.dumps({"payment_history": [{"amount": 430}]})}]
SPANS = [{"lane": "routed_action", "case_id": "t-1", "start": "2026-10-30T01:00:00Z", "end": "2026-10-30T01:07:30Z"},
         {"lane": "incident_flag", "case_id": "t-2", "start": "2026-10-30T02:00:00+00:00", "end": "2026-10-30T02:00:00Z"}]
AT = "2026-10-30T02:00:00Z"


def day(cases, member, verdicts=None):
    crit = all_criteria_from_clauses(CLAUSES)
    rollups = [(c, dict({k: "met" for k in crit}, **(verdicts or {}).get(c, {})), {k: "ab" * 32 for k in crit},
                {k: "judged" for k in crit}) for c in cases]
    doc = build_result_v0_for_day("d", rollups, AT, crit, "c@1", allow_out_of_scope=True)
    doc[extension_name(PACK)] = member
    return doc


def record(cases, verdicts=None, spans=None, known=None):
    claims = day(cases, {}, verdicts)["claims"]
    return dr.build_day_record(AT, claims, CLAUSES, {c: CONVO for c in cases}, spans, known_cases=known)


class Build(unittest.TestCase):
    def test_cases_carry_label_band_and_terms_in_clause_order(self):
        rec = record(["t-1"], {"t-1": {"a.two": "not_met", "b.three": "out_of_scope"}})
        entry = rec["cases"]["t-1"]
        self.assertEqual((entry["request_labels"], entry["usd_band"]), (["cancellation"], "e+2"))
        self.assertEqual(entry["terms"], [{"id": "a.one", "tier": "must_have", "verdict": "met"},
                                          {"id": "a.two", "tier": "must_have", "verdict": "not_met"},
                                          {"id": "b.three", "tier": "must_have", "verdict": "out_of_scope"}])
        self.assertEqual(rec["judged_at"], AT)

    def test_spans_and_lane_totals(self):
        rec = record(["t-1", "t-2"], spans=SPANS)
        self.assertEqual(rec["spans"], SPANS)
        self.assertEqual(rec["lane_totals"], {"routed_action": 1, "incident_flag": 1})

    def test_a_span_on_another_days_case_is_left_to_that_day(self):
        rec = record(["t-1"], spans=SPANS, known={"t-1", "t-2"})
        self.assertEqual([s["case_id"] for s in rec["spans"]], ["t-1"])
        self.assertEqual(rec["lane_totals"], {"routed_action": 1, "incident_flag": 0})

    def test_informational_tier_comes_from_the_clause(self):
        clauses = [dict(CLAUSES[0], requirement_tier="informational")]
        claims = day(["t-1"], {})["claims"]
        self.assertEqual(dr.case_terms(claims, "t-1", clauses)[0]["tier"], "informational")
        with self.assertRaises(RollupError):
            dr.case_terms(claims, "t-1", [dict(CLAUSES[0], requirement_tier="optional")])

    def test_bad_inputs_are_refused(self):
        bad = [
            {"lane": "other", **{k: SPANS[0][k] for k in ("case_id", "start", "end")}},
            dict(SPANS[0], case_id="t-9"),
            dict(SPANS[0], end="2026-10-30T00:59:59Z"),
            dict(SPANS[0], start="2026-10-30 01:00"),
            dict(SPANS[0], start="2026-10-30T01:00:00"),
            dict(SPANS[0], end=None),
            {k: v for k, v in SPANS[0].items() if k != "end"},
            dict(SPANS[0], extra=1),
        ]
        for span in bad:
            with self.subTest(span=span), self.assertRaises(RollupError):
                record(["t-1"], spans=[span])
        with self.assertRaises(RollupError):
            record(["t-1"], spans=SPANS[0])
        for stamp in (None, "yesterday", "2026-10-30"):
            with self.subTest(stamp=stamp), self.assertRaises(RollupError):
                dr.build_day_record(stamp, [], CLAUSES, {})

    def test_no_transcript_text_is_written(self):
        convo = CONVO + [{"role": "user", "content": "synthetic secret sentence"}]
        rec = dr.build_day_record(AT, day(["t-1"], {})["claims"], CLAUSES, {"t-1": convo})
        self.assertNotIn("secret", json.dumps(rec))


class OnTheResult(unittest.TestCase):
    def test_day_and_merged_documents_validate_and_totals_recount(self):
        validator = jsonschema.Draft202012Validator(json.loads(SCHEMA.read_bytes()))
        known = {"t-1", "t-2"}
        docs = [day([c], {"day_record": record([c], spans=SPANS, known=known)}) for c in ("t-1", "t-2")]
        for d in docs:
            self.assertEqual([e.message for e in validator.iter_errors(d)], [])
        merged = merge_result_v0_documents(docs, "t", AT)
        self.assertEqual([e.message for e in validator.iter_errors(merged)], [])
        rec = merged[extension_name(PACK)]["day_record"]
        self.assertEqual(sorted(rec["cases"]), ["t-1", "t-2"])
        self.assertEqual(rec["lane_totals"], {"routed_action": 1, "incident_flag": 1})
        self.assertNotIn("judged_at", rec)

    def test_merge_carries_both_sections_and_needs_each_on_every_day(self):
        both = lambda c: {"day_record": record([c]), **build_subject_history(PACK, "shared", {c: CONVO}, None, b"s" * 32,  # noqa: E731
                                                                              share_id="synthetic-share")}
        merged = merge_result_v0_documents([day(["t-1"], both("t-1")), day(["t-2"], both("t-2"))], "t", AT)
        self.assertEqual(sorted(merged[extension_name(PACK)]), ["day_record", "subject_history"])
        with self.assertRaises(RollupError):
            merge_result_v0_documents([day(["t-1"], both("t-1")), day(["t-2"], {"day_record": record(["t-2"])})], "t", AT)
        with self.assertRaises(RollupError):
            merge_result_v0_documents([day(["t-1"], {"day_record": record(["t-1"])}), day(["t-2"], {})], "t", AT)
        with self.assertRaises(RollupError):
            merge_result_v0_documents([day(["t-1"], {"day_record": record(["t-1"])}),
                                       day(["t-1"], {"day_record": record(["t-1"])})], "t", AT)


if __name__ == "__main__":
    unittest.main()
