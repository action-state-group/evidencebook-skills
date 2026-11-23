# SPDX-License-Identifier: Apache-2.0
"""Unit tests that need no capsulectl, Goose or network."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import airline_mcp  # noqa: E402
import evaluate  # noqa: E402
import records  # noqa: E402
import window  # noqa: E402

UTC = timezone.utc


@pytest.mark.parametrize("at,win,want", [
    (datetime(2026, 11, 30, 23, 59, 59, tzinfo=UTC), "month", "2026-11"),
    (datetime(2026, 12, 1, 0, 0, 0, tzinfo=UTC), "month", "2026-12"),
    (datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC), "year", "2026"),
    (datetime(2027, 1, 1, tzinfo=UTC), "year", "2027"),
    (datetime(2026, 11, 23, 12, tzinfo=UTC), "day", "2026-11-23"),
])
def test_window_boundaries(at, win, want):
    assert window.window_id(at, win) == want


def test_window_reads_utc_not_local_time():
    # 2026-11-30 20:00 in Chicago is already December in UTC.
    chicago = timezone(timedelta(hours=-6))
    assert window.window_id(datetime(2026, 11, 30, 20, tzinfo=chicago), "month") == "2026-12"


def test_window_refuses_naive_time_and_unknown_window():
    with pytest.raises(ValueError):
        window.window_id(datetime(2026, 11, 1), "month")
    with pytest.raises(ValueError):
        window.window_id(datetime(2026, 11, 1, tzinfo=UTC), "week")


def test_book_name():
    assert window.book_name("airline", datetime(2026, 11, 2, tzinfo=UTC), "month") == "airline-2026-11"


@pytest.mark.parametrize("text,ok", [
    ("Yes.", True), ("yes, please go ahead", True), ("Confirmed", True), ("Yes please do it", True),
    ("No, not yet", False), ("Wait, let me check", False), ("What will it cost?", False), ("", False),
    ("Yes, but change it to the 3pm flight instead", False), ("I'm not sure you should go ahead yet", False),
    ("Yes, please make the change.", True),
])
def test_confirmation(text, ok):
    assert airline_mcp.confirmed(text) is ok


def test_canonical_arguments_ignore_key_order():
    assert airline_mcp.canonical({"b": 1, "a": [1, 2]}) == airline_mcp.canonical({"a": [1, 2], "b": 1})
    assert airline_mcp.canonical({"a": 1}) != airline_mcp.canonical({"a": 2})


def test_offer_rows_are_the_rubric_checks_owed_by_the_airline():
    offer = records.offer_input("40", "ab" * 32, datetime(2026, 11, 23, 17, tzinfo=UTC))
    assert offer["to"] is None and offer["role"] == "seller"
    assert [r["id"] for r in offer["terms_rows"]["rows"]] == list(records.CHECKS)
    assert {r["owed_by"] for r in offer["terms_rows"]["rows"]} == {"seller"}
    rubric = json.loads(records.RUBRIC.read_text())
    assert {c["check_id"] for c in rubric["clauses"]} == set(records.CHECKS)
    assert offer["adjudicator"]["key_id"] == "ab" * 32
    assert offer["forums"] == ["external:tau2-evaluator"]


def test_messages_put_tool_calls_inside_the_agent_turn(tmp_path):
    turns = [
        {"role": "assistant", "content": "Hi", "at": "2026-11-23T17:00:00Z"},
        {"role": "user", "content": "Change Mei's name", "at": "2026-11-23T17:00:05Z"},
        {"role": "assistant", "content": "Done", "at": "2026-11-23T17:00:20Z"},
    ]
    (tmp_path / "transcript.json").write_text(json.dumps(turns))
    calls = [{"tool": "get_reservation_details", "arguments": {"reservation_id": "3RK2T9"}, "result": "{}",
              "kind": "read", "at": "2026-11-23T17:00:20Z"}]
    (tmp_path / "tool_calls.jsonl").write_text("\n".join(json.dumps(c) for c in calls) + "\n")
    msgs = evaluate.messages(tmp_path)
    assert [m["role"] for m in msgs] == ["assistant", "user", "assistant", "tool", "assistant"]
    assert msgs[2]["tool_calls"][0]["name"] == "get_reservation_details"
    assert msgs[3]["tool_call_id"] == msgs[2]["tool_calls"][0]["id"]


def test_rollup_needs_every_criterion():
    spec = {"clauses": [{"id": "a.1", "check_id": "a"}, {"id": "a.2", "check_id": "a"}, {"id": "b.1", "check_id": "b"}]}
    got = evaluate.rollup({"a.1": {"verdict": "met"}, "a.2": {"verdict": "not_met"}, "b.1": {"verdict": "met"}}, spec)
    assert got == {"a": "not_met", "b": "met"}
    assert evaluate.rollup({"a.1": {"verdict": "met"}}, spec)["a"] == "not_evaluable"
