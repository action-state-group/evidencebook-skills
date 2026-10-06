"""Unit tests for scripts/report_spec.py's pure functions: get_path, the three
source extractors (case rows are exercised indirectly through
build_report_from_records's own plumbing in the fresh-env e2e, not here --
select_case_rows is a thin capsulectl-I/O wrapper, same carve-out
tests/test_rollup_day.py makes for collect_reports()), compute_metric,
evaluate_group, and build_report_from_records over an in-memory rows_by_name
(no capsulectl, no book -- the engine's own contract-building and claim
evaluation, isolated from I/O).
"""
import datetime
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

from report_spec import (ReportSpecError, apply_field_projections, build_documents,  # noqa: E402
                          compute_metric, contract_ref, evaluate_group, extract_flatten_rows,
                          extract_tool_result_rows, get_path, render_title, safe_filename,
                          select_record_rows)
from safe_expr import ExprError  # noqa: E402


class ApplyFieldProjections(unittest.TestCase):
    def test_plain_dotted_path(self):
        row = {}
        apply_field_projections(row, {"peer": {"id": "peer-a"}}, {"peer_id": "peer.id"})
        self.assertEqual(row["peer_id"], "peer-a")

    def test_join_reads_back_already_projected_fields_in_declaration_order(self):
        row = {"day": "2026-09-23"}
        apply_field_projections(row, {"peer": {"id": "peer-a"}},
                                 {"peer_id": "peer.id", "peer_day": {"join": ["peer_id", "day"]}})
        self.assertEqual(row["peer_day"], "peer-a/2026-09-23")

    def test_join_custom_separator(self):
        row = {"day": "2026-09-23"}
        apply_field_projections(row, {"peer": {"id": "peer-a"}},
                                 {"peer_id": "peer.id", "peer_day": {"join": ["peer_id", "day"], "sep": "|"}})
        self.assertEqual(row["peer_day"], "peer-a|2026-09-23")

    def test_unsupported_projection_shape_fails_closed(self):
        with self.assertRaises(ReportSpecError):
            apply_field_projections({}, {}, {"x": 42})


class SelectRecordRows(unittest.TestCase):
    """select_record_rows is the kind: record source's own capsulectl-I/O
    wrapper (list_capsules/payload), same carve-out as select_case_rows gets
    from this file's own module docstring -- exercised here with
    list_capsules/payload monkeypatched (mesh-llm's real export format does
    not exist yet, so there is no live book this can run against), not
    through a real capsulectl process."""

    ENTRIES = [
        {"capsule_id": "cap1", "appended_at": "2026-09-23T10:00:00Z"},
        {"capsule_id": "cap2", "appended_at": "2026-09-23T11:00:00Z"},
        {"capsule_id": "cap3", "appended_at": "2026-09-24T10:00:00Z"},
    ]
    BODIES = {
        "cap1": {"record_type": "mesh-settlement-exchange/v1", "peer": {"id": "peer-a"}, "served": 10},
        "cap2": {"record_type": "something-else/v1", "peer": {"id": "peer-a"}, "served": 99},
        "cap3": {"record_type": "mesh-settlement-exchange/v1", "peer": {"id": "peer-b"}, "served": 5},
    }

    def _select(self, **kwargs):
        with mock.patch("report_spec.list_capsules", return_value=self.ENTRIES), \
             mock.patch("report_spec.payload", side_effect=lambda ctl, prof, cid: self.BODIES[cid]):
            return select_record_rows("capsulectl", "profile", **kwargs)

    def test_only_matching_record_type_is_selected(self):
        rows = self._select(match={"record_type": "mesh-settlement-exchange/v1"})
        self.assertEqual({r["__capsule_id"] for r in rows}, {"cap1", "cap3"})

    def test_fields_are_projected_by_dotted_path(self):
        rows = self._select(match={"record_type": "mesh-settlement-exchange/v1"},
                             fields={"peer_id": "peer.id", "served": "served"})
        by_capsule = {r["__capsule_id"]: r for r in rows}
        self.assertEqual(by_capsule["cap1"]["peer_id"], "peer-a")
        self.assertEqual(by_capsule["cap1"]["served"], 10)
        self.assertEqual(by_capsule["cap3"]["peer_id"], "peer-b")

    def test_date_range_is_applied(self):
        rows = self._select(match={"record_type": "mesh-settlement-exchange/v1"},
                             date_from=datetime.date(2026, 9, 24))
        self.assertEqual({r["__capsule_id"] for r in rows}, {"cap3"})

    def test_no_match_selects_nothing(self):
        rows = self._select(match={"record_type": "nonexistent/v1"})
        self.assertEqual(rows, [])


class GetPath(unittest.TestCase):
    def test_nested_dict(self):
        self.assertEqual(get_path({"case": {"domain": "airline"}}, "case.domain"), "airline")

    def test_missing_hop_is_none(self):
        self.assertIsNone(get_path({"case": {}}, "case.domain"))
        self.assertIsNone(get_path({}, "case.domain"))

    def test_non_dict_hop_is_none_not_a_crash(self):
        self.assertIsNone(get_path({"case": "not-a-dict"}, "case.domain"))


class ExtractToolResultRows(unittest.TestCase):
    MESSAGES = [
        {"role": "assistant", "tool_calls": [{"id": "c1", "name": "cancel_reservation",
                                               "arguments": {"reservation_id": "R1"}}]},
        {"role": "tool", "tool_call_id": "c1",
         "content": '{"reservation_id": "R1", "payment_history": [{"payment_id": "p1", "amount": 100}]}'},
        {"role": "assistant", "tool_calls": [{"id": "c2", "name": "get_reservation_details"}]},
        {"role": "tool", "tool_call_id": "c2", "content": '{"reservation_id": "R1"}'},
    ]
    CASE_ROW = {"case_id": "tau2:airline:task-1:trial-0", "day": "2026-09-23",
                "tool_call_count": 2, "__capsule_id": "cap1", "__messages": MESSAGES}

    def test_only_the_named_tool_is_extracted(self):
        rows = extract_tool_result_rows([self.CASE_ROW], "cancel_reservation")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reservation_id"], "R1")
        self.assertEqual(rows[0]["payment_history"], [{"payment_id": "p1", "amount": 100}])

    def test_parent_scalars_are_carried_not_the_raw_messages(self):
        rows = extract_tool_result_rows([self.CASE_ROW], "cancel_reservation")
        self.assertEqual(rows[0]["case_id"], "tau2:airline:task-1:trial-0")
        self.assertEqual(rows[0]["day"], "2026-09-23")
        self.assertEqual(rows[0]["__capsule_id"], "cap1")
        self.assertNotIn("__messages", rows[0])

    def test_no_matching_calls_is_an_empty_list(self):
        rows = extract_tool_result_rows([self.CASE_ROW], "book_reservation")
        self.assertEqual(rows, [])

    def test_unparseable_tool_result_is_skipped(self):
        messages = [
            {"role": "assistant", "tool_calls": [{"id": "c1", "name": "cancel_reservation"}]},
            {"role": "tool", "tool_call_id": "c1", "content": "not json"},
        ]
        row = dict(self.CASE_ROW, __messages=messages)
        self.assertEqual(extract_tool_result_rows([row], "cancel_reservation"), [])


class ExtractFlattenRows(unittest.TestCase):
    def test_one_row_per_entry_carrying_parent_scalars(self):
        parent = [{"case_id": "c1", "day": "2026-09-23", "__capsule_id": "cap1",
                   "payment_history": [{"payment_id": "p1", "amount": 430},
                                       {"payment_id": "p2", "amount": -430}]}]
        rows = extract_flatten_rows(parent, "payment_history")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["case_id"], "c1")
        self.assertEqual(rows[0]["amount"], 430)
        self.assertEqual(rows[1]["amount"], -430)

    def test_offset_match_found_within_the_same_parent_list(self):
        parent = [{"__capsule_id": "cap1",
                   "payment_history": [{"payment_id": "p1", "amount": 430},
                                       {"payment_id": "p2", "amount": -430}]}]
        rows = extract_flatten_rows(parent, "payment_history", match_offsets_field="amount")
        self.assertTrue(rows[0]["__has_offset_match"])
        self.assertTrue(rows[1]["__has_offset_match"])

    def test_offset_match_never_crosses_parent_lists(self):
        # Two different reservations' payment histories must not satisfy each
        # other's offset -- same-case correlation only, scoped per parent row.
        parent = [
            {"__capsule_id": "cap1", "payment_history": [{"payment_id": "p1", "amount": 430}]},
            {"__capsule_id": "cap2", "payment_history": [{"payment_id": "p2", "amount": -430}]},
        ]
        rows = extract_flatten_rows(parent, "payment_history", match_offsets_field="amount")
        self.assertFalse(rows[0]["__has_offset_match"])
        self.assertFalse(rows[1]["__has_offset_match"])

    def test_unmatched_refund_has_no_offset_match(self):
        parent = [{"__capsule_id": "cap1", "payment_history": [{"payment_id": "p1", "amount": -50}]}]
        rows = extract_flatten_rows(parent, "payment_history", match_offsets_field="amount")
        self.assertFalse(rows[0]["__has_offset_match"])

    def test_where_filters_after_offset_match_is_computed(self):
        parent = [{"__capsule_id": "cap1",
                   "payment_history": [{"payment_id": "p1", "amount": 430},
                                       {"payment_id": "p2", "amount": -430}]}]
        rows = extract_flatten_rows(parent, "payment_history", match_offsets_field="amount", where="amount < 0")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["amount"], -430)
        self.assertTrue(rows[0]["__has_offset_match"])

    def test_non_list_field_is_skipped_not_a_crash(self):
        parent = [{"__capsule_id": "cap1", "payment_history": "not-a-list"}]
        self.assertEqual(extract_flatten_rows(parent, "payment_history"), [])

    def test_non_dict_entries_are_skipped(self):
        parent = [{"__capsule_id": "cap1", "payment_history": [1, 2, {"amount": 3}]}]
        rows = extract_flatten_rows(parent, "payment_history")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["amount"], 3)


class ComputeMetric(unittest.TestCase):
    ROWS = [{"amount": 100}, {"amount": -50}, {"amount": -30}]

    def test_count(self):
        self.assertEqual(compute_metric({"name": "n", "op": "count"}, self.ROWS), 3)

    def test_count_with_where(self):
        self.assertEqual(compute_metric({"name": "n", "op": "count", "where": "amount < 0"}, self.ROWS), 2)

    def test_sum(self):
        self.assertEqual(compute_metric({"name": "n", "op": "sum", "field": "amount"}, self.ROWS), 20)

    def test_sum_with_where_and_abs(self):
        metric = {"name": "n", "op": "sum", "field": "amount", "where": "amount < 0", "abs": True}
        self.assertEqual(compute_metric(metric, self.ROWS), 80)

    def test_sum_over_a_row_missing_the_field_treats_it_as_zero(self):
        rows = [{"amount": 10}, {"other": 1}]
        self.assertEqual(compute_metric({"name": "n", "op": "sum", "field": "amount"}, rows), 10)

    def test_unknown_op_fails_closed(self):
        with self.assertRaises(ReportSpecError):
            compute_metric({"name": "n", "op": "average"}, self.ROWS)


class EvaluateGroup(unittest.TestCase):
    SPEC = {
        "sources": [{"name": "conversations", "kind": "case"}],
        "metrics": [
            {"name": "conversation_count", "source": "conversations", "op": "count"},
            {"name": "cancellation_count", "source": "cancellations", "op": "count"},
        ],
        "claims": [
            {"id": "bounded", "kind": "threshold", "metric": "cancellation_count", "op": "<=",
             "value": "conversation_count"},
            {"id": "has_activity", "kind": "forall", "source": "conversations", "assert": "tool_call_count > 0"},
        ],
    }

    def test_threshold_met(self):
        rows_by_name = {
            "conversations": [{"day": "d1", "__capsule_id": "c1", "tool_call_count": 2},
                               {"day": "d1", "__capsule_id": "c2", "tool_call_count": 3}],
            "cancellations": [{"day": "d1", "__capsule_id": "c1"}],
        }
        verdicts, digests, metrics = evaluate_group(self.SPEC, "d1", rows_by_name, "day")
        self.assertEqual(verdicts["bounded"], "met")
        self.assertEqual(metrics, {"conversation_count": 2, "cancellation_count": 1})
        self.assertEqual(digests["bounded"], ["c1"])

    def test_threshold_not_met(self):
        rows_by_name = {
            "conversations": [{"day": "d1", "__capsule_id": "c1", "tool_call_count": 2}],
            "cancellations": [{"day": "d1", "__capsule_id": "c1"}, {"day": "d1", "__capsule_id": "c2"}],
        }
        verdicts, _, _ = evaluate_group(self.SPEC, "d1", rows_by_name, "day")
        self.assertEqual(verdicts["bounded"], "not_met")

    def test_forall_met_when_every_row_satisfies_the_assertion(self):
        rows_by_name = {
            "conversations": [{"day": "d1", "__capsule_id": "c1", "tool_call_count": 2}],
            "cancellations": [],
        }
        verdicts, _, _ = evaluate_group(self.SPEC, "d1", rows_by_name, "day")
        self.assertEqual(verdicts["has_activity"], "met")

    def test_forall_not_met_when_one_row_violates_it(self):
        rows_by_name = {
            "conversations": [{"day": "d1", "__capsule_id": "c1", "tool_call_count": 0}],
            "cancellations": [],
        }
        verdicts, digests, _ = evaluate_group(self.SPEC, "d1", rows_by_name, "day")
        self.assertEqual(verdicts["has_activity"], "not_met")
        self.assertEqual(digests["has_activity"], ["c1"])

    def test_forall_is_vacuously_met_with_no_rows(self):
        rows_by_name = {"conversations": [], "cancellations": []}
        verdicts, digests, _ = evaluate_group(self.SPEC, "d1", rows_by_name, "day")
        self.assertEqual(verdicts["has_activity"], "met")
        self.assertEqual(digests["has_activity"], [])

    def test_only_this_groups_own_rows_count(self):
        rows_by_name = {
            "conversations": [{"day": "d1", "__capsule_id": "c1", "tool_call_count": 1},
                               {"day": "d2", "__capsule_id": "c2", "tool_call_count": 1}],
            "cancellations": [],
        }
        _, _, metrics = evaluate_group(self.SPEC, "d1", rows_by_name, "day")
        self.assertEqual(metrics["conversation_count"], 1)

    def test_unknown_metric_fails_closed(self):
        spec = dict(self.SPEC, claims=[{"id": "x", "kind": "threshold", "metric": "nope", "op": "<=", "value": 1}])
        with self.assertRaises(ReportSpecError):
            evaluate_group(spec, "d1", {"conversations": []}, "day")

    def test_bad_expression_in_forall_fails_closed(self):
        spec = dict(self.SPEC, claims=[{"id": "x", "kind": "forall", "source": "conversations",
                                         "assert": "tool_call_count["}])
        with self.assertRaises(ReportSpecError):
            evaluate_group(spec, "d1", {"conversations": [{"day": "d1", "tool_call_count": 1}]}, "day")

    def test_unknown_claim_kind_fails_closed(self):
        spec = dict(self.SPEC, claims=[{"id": "x", "kind": "mystery"}])
        with self.assertRaises(ReportSpecError):
            evaluate_group(spec, "d1", {"conversations": []}, "day")


class BuildDocuments(unittest.TestCase):
    SPEC = {
        "id": "test-spec", "version": 1, "title": "Test report",
        "sources": [{"name": "conversations", "kind": "case"}],
        "metrics": [{"name": "conversation_count", "source": "conversations", "op": "count"}],
        "claims": [{"id": "has_activity", "kind": "forall", "source": "conversations",
                    "assert": "tool_call_count > 0"}],
    }
    ROWS = {
        "conversations": [
            {"day": "2026-09-23", "__capsule_id": "c1", "tool_call_count": 2},
            {"day": "2026-09-23", "__capsule_id": "c2", "tool_call_count": 3},
            {"day": "2026-09-24", "__capsule_id": "c3", "tool_call_count": 0},
        ],
    }

    def test_one_document_per_day_calling_the_real_result_v0_builder(self):
        docs, group_results = build_documents(self.SPEC, self.ROWS, "2026-09-25T00:00:00Z")
        self.assertEqual(set(docs), {"2026-09-23", "2026-09-24"})
        doc = docs["2026-09-23"]
        self.assertEqual(doc["result_version"], "evidence-result-v0")
        self.assertEqual(len(doc["claims"]), 1)
        claim = doc["claims"][0]
        self.assertEqual(claim["verdict"], "met")
        self.assertEqual(claim["tier"], "recomputed")
        self.assertEqual(claim["contract_ref"], "test-spec@1")
        self.assertEqual(claim["requirement_ref"], "has_activity")

    def test_a_violating_day_is_not_met(self):
        docs, _ = build_documents(self.SPEC, self.ROWS, "2026-09-25T00:00:00Z")
        self.assertEqual(docs["2026-09-24"]["claims"][0]["verdict"], "not_met")

    def test_title_and_metrics_are_recorded(self):
        docs, group_results = build_documents(self.SPEC, self.ROWS, "2026-09-25T00:00:00Z")
        self.assertIn("Test report", docs["2026-09-23"]["view"]["title"])
        by_day = {g["day"]: g for g in group_results}
        self.assertEqual(by_day["2026-09-23"]["metrics"]["conversation_count"], 2)
        self.assertEqual(by_day["2026-09-24"]["metrics"]["conversation_count"], 1)


class ContractRef(unittest.TestCase):
    def test_id_and_version_joined(self):
        self.assertEqual(contract_ref({"id": "tau2-airline-no-judge", "version": 1}), "tau2-airline-no-judge@1")


class RenderTitle(unittest.TestCase):
    def test_default_title_with_no_template(self):
        self.assertEqual(render_title({"id": "x", "title": "Tau2 report"}, "2026-09-23", {}),
                          "Tau2 report -- 2026-09-23")

    def test_template_fills_in_metrics(self):
        spec = {"id": "x", "title": "Tau2 report",
                "presentation": {"title_template": "{title} ({period}): {conversation_count} conversations"}}
        self.assertEqual(render_title(spec, "2026-09-23", {"conversation_count": 5}),
                          "Tau2 report (2026-09-23): 5 conversations")


class SafeFilename(unittest.TestCase):
    def test_path_separators_never_survive(self):
        self.assertEqual(safe_filename("../../etc/passwd"), ".._.._etc_passwd")

    def test_ordinary_group_key_is_readable(self):
        self.assertEqual(safe_filename("2026-09-23"), "2026-09-23")


if __name__ == "__main__":
    unittest.main()
