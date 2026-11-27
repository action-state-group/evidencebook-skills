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
import report  # noqa: E402

UTC = timezone.utc


class FakeStore(records.Store):
    """A store whose capsulectl answers come from a canned `deal window list`."""

    def run(self, *args, profile=None):
        assert args == ("deal", "window", "list") and profile == self.holder
        return {"window": "month", "windows": [
            {"label": "2026-10", "closed": True, "placed": ["deal/aaa"]},
            {"label": "2026-11", "closed": False, "placed": ["deal/bbb", "deal/ccc"]},
            {"label": "2026-12", "closed": False, "placed": []}]}


def test_a_case_window_is_read_from_the_window_list(tmp_path):
    store = FakeStore(state=tmp_path)
    assert store.window_of("deal/aaa") == "2026-10"
    assert store.window_of("deal/ccc") == "2026-11"


def test_a_deal_book_placed_in_no_window_is_refused(tmp_path):
    with pytest.raises(records.RecordError, match="placed in no window"):
        FakeStore(state=tmp_path).window_of("deal/zzz")


def test_the_store_window_must_be_one_capsulectl_takes(tmp_path):
    with pytest.raises(ValueError, match="window must be one of"):
        records.Store(state=tmp_path, window="fortnight").book()


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


def test_a_window_that_differs_from_the_existing_store_is_refused(tmp_path):
    (tmp_path / "books" / "airline").mkdir(parents=True)
    (tmp_path / "books" / "airline" / "deal.db").write_text("")
    assert FakeStore(state=tmp_path, window="month").book() == "airline"
    with pytest.raises(records.RecordError, match="has window 'month', fixed"):
        FakeStore(state=tmp_path, window="day").book()


class TickStore(records.Store):
    """A store whose `deal tick` answers are canned, recording each call."""

    def __init__(self, answers, **kw):
        super().__init__(**kw)
        self.answers, self.calls = list(answers), []

    def run(self, *args, profile=None):
        self.calls.append(args)
        return self.answers.pop(0)


def test_a_due_tick_is_cut_at_once_with_no_wait(tmp_path):
    store = TickStore([{"state": "ticked", "tick": 2}], state=tmp_path)
    assert report.wait_for_checkpoint(store, "airline") == {"state": "ticked", "tick": 2}
    assert store.calls == [("deal", "tick")]


def test_a_tick_not_yet_due_is_waited_for_just_past_its_due_time(tmp_path):
    due = (datetime.now(UTC) + timedelta(seconds=40)).strftime("%Y-%m-%dT%H:%M:%SZ")
    store = TickStore([{"state": "not_due", "due": due}, {"state": "ticked", "tick": 2}], state=tmp_path)
    assert report.wait_for_checkpoint(store, "airline")["state"] == "ticked"
    assert store.calls[0] == ("deal", "tick")
    flag, window = store.calls[1][2:]
    assert flag == "--wait-up-to" and 40 <= int(window.removesuffix("s")) <= 42


def test_a_due_time_already_past_waits_only_the_margin(tmp_path):
    store = TickStore([{"state": "not_due", "due": "2020-01-01T00:00:00Z"}, {"state": "ticked"}], state=tmp_path)
    report.wait_for_checkpoint(store, "airline")
    assert store.calls[1] == ("deal", "tick", "--wait-up-to", "2s")


class InitStore(records.Store):
    """A store whose `deal init` writes a profile file, as capsulectl does."""

    def run(self, *args, profile=None):
        if args[:2] == ("deal", "init"):
            path = self.state / "config" / "capsule" / "profiles" / f"{profile}.yaml"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("name: airline\n")
            (self.state / "books" / "airline").mkdir(parents=True, exist_ok=True)
            (self.state / "books" / "airline" / "deal.db").write_text("")
        return {"window": self.window}


@pytest.mark.parametrize("cadence, block", [
    (None, ""),
    ("1m", "cadence:\n    interval: 1m\n    jitter: 0s\n"),
])
def test_a_store_cadence_is_written_into_its_profile_when_created(tmp_path, cadence, block):
    InitStore(state=tmp_path, cadence=cadence).book()
    profile = tmp_path / "config" / "capsule" / "profiles" / "airline.yaml"
    assert profile.read_text() == "name: airline\n" + block
    InitStore(state=tmp_path, cadence="2m").book()  # an existing store keeps its cadence
    assert profile.read_text() == "name: airline\n" + block
