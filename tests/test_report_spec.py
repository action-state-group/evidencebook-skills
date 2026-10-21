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
import json
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

from report_spec import (UNREADABLE, MetricUnknown, ReportSpecError, _offset_matches, apply_field_projections,  # noqa: E402
                          build_documents, build_rows, compute_metric, contract_ref,
                          evaluate_group, extract_flatten_rows, extract_tool_result_rows,
                          get_path, load_spec, render_title, safe_filename, select_record_rows)
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

    def _one_result(self, content=None, with_result=True):
        messages = [{"role": "assistant", "tool_calls": [{"id": "c1", "name": "cancel_reservation"}]}]
        if with_result:
            messages.append({"role": "tool", "tool_call_id": "c1", "content": content})
        return extract_tool_result_rows([dict(self.CASE_ROW, __messages=messages)], "cancel_reservation")

    def test_unparseable_tool_result_is_an_unreadable_row_not_skipped(self):
        # Skipped, it read as "no cancellation" and a forall over it was met.
        for rows in (self._one_result("not json"), self._one_result('["a list"]'),
                     self._one_result(with_result=False), self._one_result("")):
            self.assertEqual(len(rows), 1)
            self.assertIn(UNREADABLE, rows[0])
            self.assertEqual(rows[0]["__capsule_id"], "cap1")
            self.assertEqual(rows[0]["day"], "2026-09-23")

    def test_a_result_setting_a_protected_field_is_unreadable_and_keeps_provenance(self):
        for field in ("__capsule_id", "day", "case_id", "__unreadable"):
            rows = self._one_result(json.dumps({"reservation_id": "R1", field: "elsewhere"}))
            self.assertIn(UNREADABLE, rows[0])
            self.assertEqual(rows[0]["__capsule_id"], "cap1")
            self.assertEqual(rows[0]["day"], "2026-09-23")
            self.assertEqual(rows[0]["case_id"], "tau2:airline:task-1:trial-0")


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

    def test_missing_or_non_list_field_is_an_unreadable_row_not_a_crash(self):
        for parent in ([{"__capsule_id": "cap1", "payment_history": "not-a-list"}],
                       [{"__capsule_id": "cap1"}],
                       [{"__capsule_id": "cap1", "payment_history": None}]):
            rows = extract_flatten_rows(parent, "payment_history")
            self.assertEqual(len(rows), 1)
            self.assertIn(UNREADABLE, rows[0])
            self.assertEqual(rows[0]["__capsule_id"], "cap1")

    def test_an_empty_list_is_no_rows_not_unreadable(self):
        self.assertEqual(extract_flatten_rows([{"__capsule_id": "cap1", "payment_history": []}],
                                              "payment_history"), [])

    def test_non_dict_entries_are_unreadable_rows(self):
        parent = [{"__capsule_id": "cap1", "payment_history": [1, 2, {"amount": 3}]}]
        rows = extract_flatten_rows(parent, "payment_history")
        self.assertEqual(len(rows), 3)
        self.assertEqual(sum(UNREADABLE in r for r in rows), 2)
        self.assertEqual(rows[2]["amount"], 3)

    def test_an_unreadable_parent_stays_unreadable(self):
        parent = [{"__capsule_id": "cap1", "day": "d1", UNREADABLE: "result missing"}]
        rows = extract_flatten_rows(parent, "payment_history")
        self.assertEqual(rows, [{"__capsule_id": "cap1", "day": "d1", UNREADABLE: "result missing"}])

    def test_a_child_entry_never_overwrites_provenance_or_grouping(self):
        for field, value in (("__capsule_id", "unrelated"), ("day", "2026-01-01"), ("case_id", "other"),
                             ("region", "eu")):
            parent = [{"__capsule_id": "cap1", "day": "d1", "case_id": "c1", "region": "us",
                       "payment_history": [{"amount": -5, field: value}]}]
            rows = extract_flatten_rows(parent, "payment_history", protected=("day", "case_id", "region"))
            self.assertEqual(len(rows), 1)
            self.assertIn(UNREADABLE, rows[0])
            self.assertEqual((rows[0]["__capsule_id"], rows[0]["day"], rows[0]["case_id"], rows[0]["region"]),
                             ("cap1", "d1", "c1", "us"))

    def test_an_entry_the_where_cannot_decide_is_kept_unreadable(self):
        parent = [{"__capsule_id": "cap1", "payment_history": [{"payment_id": "p1"}, {"amount": 5}]}]
        rows = extract_flatten_rows(parent, "payment_history", where="amount < 0")
        self.assertEqual(len(rows), 1)
        self.assertIn(UNREADABLE, rows[0])

    def test_two_refunds_of_the_same_amount_do_not_both_match_one_charge(self):
        # claude-security finding, this job (CWE-697): the offset-match used
        # to be a pure existence check, so two -100 refunds against a single
        # +100 charge both independently "found" it and both read as matched.
        # Only one may actually be legitimately offset by that one charge.
        parent = [{"__capsule_id": "cap1",
                   "payment_history": [{"payment_id": "p1", "amount": 100},
                                       {"payment_id": "p2", "amount": -100},
                                       {"payment_id": "p3", "amount": -100}]}]
        rows = extract_flatten_rows(parent, "payment_history", match_offsets_field="amount")
        matched = [r["__has_offset_match"] for r in rows]
        self.assertEqual(matched.count(True), 2)  # the one charge + the one refund it covers
        self.assertEqual(matched.count(False), 1)  # the second, unmatched refund

    def test_two_charges_and_two_refunds_all_pair_off(self):
        parent = [{"__capsule_id": "cap1",
                   "payment_history": [{"amount": 100}, {"amount": 50},
                                       {"amount": -100}, {"amount": -50}]}]
        rows = extract_flatten_rows(parent, "payment_history", match_offsets_field="amount")
        self.assertTrue(all(r["__has_offset_match"] for r in rows))

    def test_non_numeric_amount_never_matches_and_never_crashes(self):
        parent = [{"__capsule_id": "cap1",
                   "payment_history": [{"amount": "n/a"}, {"amount": -100}]}]
        rows = extract_flatten_rows(parent, "payment_history", match_offsets_field="amount")
        self.assertEqual([r["__has_offset_match"] for r in rows], [False, False])


class OffsetMatches(unittest.TestCase):
    def test_simple_pair(self):
        self.assertEqual(_offset_matches([100, -100]), [True, True])

    def test_one_to_one_not_many_to_one(self):
        self.assertEqual(_offset_matches([100, -100, -100]).count(True), 2)

    def test_unmatched_entry_is_false(self):
        self.assertEqual(_offset_matches([100, -50]), [False, False])

    def test_bool_is_never_treated_as_numeric(self):
        # isinstance(True, int) is True in Python -- explicitly excluded.
        self.assertEqual(_offset_matches([True, -1]), [False, False])

    def test_empty_list(self):
        self.assertEqual(_offset_matches([]), [])


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

    def test_sum_over_a_row_missing_the_field_is_unknown_never_zero(self):
        for bad in ({"other": 1}, {"amount": None}, {"amount": ""}, {"amount": []}, {"amount": True},
                    {"amount": float("nan")}, {"amount": float("inf")}):
            with self.assertRaises(MetricUnknown, msg=repr(bad)):
                compute_metric({"name": "n", "op": "sum", "field": "amount"}, [{"amount": 10}, bad])

    def test_sum_reads_a_dotted_field(self):
        rows = [{"amount": {"msat": 10}}, {"amount": {"msat": 5}}]
        self.assertEqual(compute_metric({"name": "n", "op": "sum", "field": "amount.msat"}, rows), 15)

    def test_an_unreadable_row_makes_every_metric_unknown(self):
        rows = [{"amount": 10}, {UNREADABLE: "result missing"}]
        for metric in ({"name": "n", "op": "count"}, {"name": "n", "op": "sum", "field": "amount"}):
            with self.assertRaises(MetricUnknown):
                compute_metric(metric, rows)

    def test_a_where_over_a_missing_field_is_unknown(self):
        with self.assertRaises(MetricUnknown):
            compute_metric({"name": "n", "op": "count", "where": "status != 'void'"}, [{"amount": 1}])

    def test_count_distinct(self):
        rows = [{"case_id": "a"}, {"case_id": "a"}, {"case_id": "b"}]
        self.assertEqual(compute_metric({"name": "n", "op": "count_distinct", "field": "case_id"}, rows), 2)
        with self.assertRaises(MetricUnknown):
            compute_metric({"name": "n", "op": "count_distinct", "field": "case_id"}, [{"x": 1}])

    def test_unknown_op_fails_closed(self):
        with self.assertRaises(ReportSpecError):
            compute_metric({"name": "n", "op": "average"}, self.ROWS)

    def test_sum_over_a_non_numeric_field_fails_closed(self):
        rows = [{"amount": 10}, {"amount": "n/a"}]
        with self.assertRaises(ReportSpecError):
            compute_metric({"name": "n", "op": "sum", "field": "amount"}, rows)


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
        # both sides of `cancellation_count <= conversation_count` are cited
        self.assertEqual(digests["bounded"], ["c1", "c2"])

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

    def test_a_claim_over_no_rows_is_not_evaluable_never_vacuously_met(self):
        # A claim citing no record can't be recomputed from the disclosure.
        rows_by_name = {"conversations": [], "cancellations": []}
        reasons = {}
        verdicts, digests, _ = evaluate_group(self.SPEC, "d1", rows_by_name, "day", reasons)
        self.assertEqual(verdicts["has_activity"], "not_evaluable")
        self.assertEqual(verdicts["bounded"], "not_evaluable")
        self.assertEqual(digests["has_activity"], [])
        self.assertIn("has_activity", reasons)

    def test_a_forall_over_an_unreadable_tool_result_is_not_evaluable_not_met(self):
        spec = dict(self.SPEC, claims=[{"id": "refunded", "kind": "forall", "source": "cancellations",
                                         "assert": "refunded == True"}])
        rows_by_name = {"conversations": [{"day": "d1", "__capsule_id": "c1", "tool_call_count": 1}],
                        "cancellations": [{"day": "d1", "__capsule_id": "c1", UNREADABLE: "result not JSON"}]}
        reasons = {}
        verdicts, digests, _ = evaluate_group(spec, "d1", rows_by_name, "day", reasons)
        self.assertEqual(verdicts["refunded"], "not_evaluable")
        self.assertEqual(digests["refunded"], ["c1"])
        self.assertIn("unreadable", reasons["refunded"])

    def test_a_forall_reading_a_missing_field_is_not_evaluable(self):
        spec = dict(self.SPEC, claims=[{"id": "ok", "kind": "forall", "source": "conversations",
                                         "assert": "status != 'failed'"}])
        rows_by_name = {"conversations": [{"day": "d1", "__capsule_id": "c1"}], "cancellations": []}
        verdicts, _, _ = evaluate_group(spec, "d1", rows_by_name, "day")
        self.assertEqual(verdicts["ok"], "not_evaluable")

    def test_a_threshold_over_an_unknown_sum_is_not_evaluable_never_met(self):
        spec = {"sources": [{"name": "x", "kind": "record"}],
                "metrics": [{"name": "paid", "source": "x", "op": "sum", "field": "amount_msat"}],
                "claims": [{"id": "under_limit", "kind": "threshold", "metric": "paid", "op": "<=", "value": 100}]}
        rows_by_name = {"x": [{"day": "d1", "__capsule_id": "a", "amount_msat": 10},
                              {"day": "d1", "__capsule_id": "b"}]}
        verdicts, digests, metrics = evaluate_group(spec, "d1", rows_by_name, "day")
        self.assertEqual(verdicts["under_limit"], "not_evaluable")
        self.assertIsNone(metrics["paid"])
        self.assertEqual(digests["under_limit"], ["a", "b"])

    def test_a_threshold_whose_value_side_is_unknown_is_not_evaluable(self):
        spec = dict(self.SPEC, metrics=[
            {"name": "conversation_count", "source": "conversations", "op": "count"},
            {"name": "cancellation_count", "source": "cancellations", "op": "count"}])
        rows_by_name = {"conversations": [{"day": "d1", "__capsule_id": "c1", UNREADABLE: "bad"}],
                        "cancellations": [{"day": "d1", "__capsule_id": "c1"}]}
        verdicts, _, _ = evaluate_group(spec, "d1", rows_by_name, "day")
        self.assertEqual(verdicts["bounded"], "not_evaluable")

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

    def test_threshold_claim_digests_exclude_rows_the_metrics_own_where_filtered_out(self):
        # desk-review finding: a threshold claim over a `where`-filtered metric
        # must cite only the rows the metric actually aggregated, not every row
        # of that source in the group -- the module's own docstring promises
        # claims "cite the capsule ids of the records it was computed from."
        spec = {
            "sources": [{"name": "exchanges", "kind": "record"}],
            "metrics": [
                {"name": "served_count", "source": "exchanges", "op": "count",
                 "where": "direction == 'served'"},
                {"name": "all_count", "source": "exchanges", "op": "count"},
            ],
            "claims": [{"id": "bounded", "kind": "threshold", "metric": "served_count", "op": "<=",
                        "value": "all_count"}],
        }
        rows_by_name = {
            "exchanges": [
                {"day": "d1", "__capsule_id": "served-1", "direction": "served"},
                {"day": "d1", "__capsule_id": "consumed-1", "direction": "consumed"},
            ],
        }
        # The left side cites only the served row its where kept; the right
        # side (all_count) cites every exchange it counted. Both are cited, so
        # the disclosure can recompute `served_count <= all_count`.
        _, digests, _ = evaluate_group(spec, "d1", rows_by_name, "day")
        self.assertEqual(digests["bounded"], ["consumed-1", "served-1"])
        spec_left_only = dict(spec, claims=[{"id": "small", "kind": "threshold", "metric": "served_count",
                                              "op": "<=", "value": 5}])
        _, digests, _ = evaluate_group(spec_left_only, "d1", rows_by_name, "day")
        self.assertEqual(digests["small"], ["served-1"])

    def test_a_misspelled_metric_source_fails_closed_not_silently_zero(self):
        # desk-review finding: group_rows.get(m["source"], []) let a typo'd
        # source name silently compute over zero rows -- indistinguishable
        # from a real "no data" finding. Every other name reference in this
        # engine (from:, claim source/metric, claim kind) already fails closed.
        spec = dict(self.SPEC, metrics=[{"name": "x", "source": "conversaton", "op": "count"}])
        with self.assertRaisesRegex(ReportSpecError, "unknown source"):
            evaluate_group(spec, "d1", {"conversations": []}, "day")

    def test_an_unknown_forall_source_fails_closed(self):
        spec = dict(self.SPEC, claims=[{"id": "x", "kind": "forall", "source": "nope", "assert": "True"}])
        with self.assertRaisesRegex(ReportSpecError, "unknown source"):
            evaluate_group(spec, "d1", {"conversations": []}, "day")

    def test_division_by_zero_in_a_threshold_value_expression_fails_closed(self):
        spec = {
            "sources": [{"name": "conversations", "kind": "case"}],
            "metrics": [
                {"name": "total", "source": "conversations", "op": "count"},
                {"name": "zero", "source": "conversations", "op": "count", "where": "False"},
            ],
            "claims": [{"id": "x", "kind": "threshold", "metric": "total", "op": "<=",
                        "value": "total / zero"}],
        }
        rows_by_name = {"conversations": [{"day": "d1", "__capsule_id": "c1"}]}
        with self.assertRaises(ReportSpecError):
            evaluate_group(spec, "d1", rows_by_name, "day")

    def test_a_bad_where_clause_on_a_metric_fails_closed_with_context(self):
        spec = dict(self.SPEC, metrics=[{"name": "x", "source": "conversations", "op": "count",
                                          "where": "tool_call_count["}])
        with self.assertRaisesRegex(ReportSpecError, "where"):
            evaluate_group(spec, "d1", {"conversations": [{"day": "d1"}]}, "day")


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
        name = safe_filename("../../etc/passwd")
        self.assertTrue(name.startswith(".._.._etc_passwd-"))
        self.assertNotIn("/", name)

    def test_keys_that_escape_alike_never_share_a_file(self):
        self.assertNotEqual(safe_filename("peer/a"), safe_filename("peer_a"))
        self.assertEqual(safe_filename("peer_a"), "peer_a")

    def test_ordinary_group_key_is_readable(self):
        self.assertEqual(safe_filename("2026-09-23"), "2026-09-23")


class BuildRowsToolResultKindValidation(unittest.TestCase):
    """desk-review finding: a `tool_result` source chained off a non-`case`
    `from:` used to silently yield zero rows forever (no __messages field to
    read) instead of failing closed."""

    def test_tool_result_from_a_record_source_fails_closed(self):
        spec = {
            "sources": [
                {"name": "exchanges", "kind": "record"},
                {"name": "calls", "kind": "tool_result", "from": "exchanges", "tool_name": "x"},
            ],
        }
        with mock.patch("report_spec.select_record_rows", return_value=[{"day": "d1", "__capsule_id": "c1"}]):
            with self.assertRaisesRegex(ReportSpecError, "kind: case"):
                build_rows(spec, "capsulectl", "profile")

    def test_tool_result_from_a_case_source_is_accepted(self):
        spec = {
            "sources": [
                {"name": "conversations", "kind": "case"},
                {"name": "calls", "kind": "tool_result", "from": "conversations", "tool_name": "x"},
            ],
        }
        with mock.patch("report_spec.select_case_rows",
                         return_value=[{"day": "d1", "__capsule_id": "c1", "__messages": []}]):
            rows = build_rows(spec, "capsulectl", "profile")
        self.assertEqual(rows["calls"], [])


class LoadSpec(unittest.TestCase):
    def _write(self, tmp_path, text):
        path = tmp_path / "spec.yaml"
        path.write_text(text)
        return path

    def test_missing_required_keys_fail_closed(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="test-load-spec-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        path = self._write(tmp, "spec_version: report-spec/v1\nid: x\nversion: 1\n")
        with self.assertRaisesRegex(ReportSpecError, "missing or empty required key"):
            load_spec(path)

    def test_non_mapping_yaml_fails_closed(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="test-load-spec-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        path = self._write(tmp, "- a\n- b\n")
        with self.assertRaisesRegex(ReportSpecError, "must be a YAML mapping"):
            load_spec(path)

    def test_a_complete_spec_loads(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="test-load-spec-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        path = self._write(tmp, """
spec_version: report-spec/v1
id: x
version: 1
sources: [{name: conversations, kind: case}]
claims: [{id: has_activity, kind: forall, source: conversations, assert: "True"}]
""")
        spec = load_spec(path)
        self.assertEqual(spec["id"], "x")

    def test_a_metric_named_title_or_period_is_refused_at_load(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="test-load-spec-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        for name in ("title", "period"):
            path = self._write(tmp, f"""
spec_version: report-spec/v1
id: x
version: 1
sources: [{{name: conversations, kind: case}}]
metrics: [{{name: {name}, source: conversations, op: count}}]
claims: [{{id: has_activity, kind: forall, source: conversations, assert: "True"}}]
""")
            with self.assertRaisesRegex(ReportSpecError, "reserved"):
                load_spec(path)


class Tau2NoJudgeSpec(unittest.TestCase):
    """scripts/specs/tau2-airline-no-judge.yaml over hand-built rows."""
    SPEC = load_spec(pathlib.Path(__file__).resolve().parents[1] / "scripts/specs/tau2-airline-no-judge.yaml")

    def _rows(self, cancels):
        conversations = [{"case_id": "c1", "day": "d1", "__capsule_id": "k1", "tool_call_count": 3},
                         {"case_id": "c2", "day": "d1", "__capsule_id": "k2", "tool_call_count": 1}]
        cancel_results = [dict(c, case_id="c1", day="d1", __capsule_id="k1") for c in cancels]
        refund_entries = extract_flatten_rows(cancel_results, "payment_history", "amount", "amount < 0")
        return {"conversations": conversations, "cancel_results": cancel_results,
                "refund_entries": refund_entries}

    def test_one_conversation_cancelling_two_reservations_still_meets_the_bound(self):
        cancels = [{"reservation_id": r, "payment_history": [{"amount": 100}, {"amount": -100}]}
                   for r in ("R1", "R2")]
        verdicts, _, metrics = evaluate_group(self.SPEC, "d1", self._rows(cancels), "day")
        self.assertEqual(metrics["cancellation_count"], 2)
        self.assertEqual(metrics["cancelling_conversation_count"], 1)
        self.assertEqual(verdicts["cancellation_volume_bounded"], "met")
        self.assertEqual(verdicts["refund_amount_matches_payment_record"], "met")

    def test_a_cancellation_with_no_payment_history_is_not_evaluable_never_met(self):
        verdicts, _, metrics = evaluate_group(self.SPEC, "d1", self._rows([{"reservation_id": "R1"}]), "day")
        self.assertEqual(verdicts["refund_amount_matches_payment_record"], "not_evaluable")
        self.assertIsNone(metrics["total_refunded"])

    def test_title_shows_unknown_for_an_unknown_metric(self):
        _, _, metrics = evaluate_group(self.SPEC, "d1", self._rows([{"reservation_id": "R1"}]), "day")
        self.assertIn("unknown refunds", render_title(self.SPEC, "d1", metrics))


if __name__ == "__main__":
    unittest.main()
