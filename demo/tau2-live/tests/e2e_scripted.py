# SPDX-License-Identifier: Apache-2.0
"""End to end without Goose: a canned two-party script through the real records,
tool server class, evaluator (mock judge) and report, ending in two bundles that
capsulectl verifies.

    uv run python tests/e2e_scripted.py STATE_DIR

Needs capsulectl with the deal and book plugins, and capsule-engine, on PATH (or
CAPSULECTL_PLUGIN_ROOTS for the plugins). Exits non-zero on the first failed check.
The report step waits for the book's checkpoint tick (about five minutes).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
os.environ["JEV_JUDGE_BACKEND"] = "mock"

import airline_mcp  # noqa: E402
import evaluate  # noqa: E402
import records  # noqa: E402
import report  # noqa: E402
import telemetry  # noqa: E402

AIRLINE = HERE.parent.parent / "airline-data"


def check(cond: bool, what: str) -> None:
    print(("ok   " if cond else "FAIL ") + what, flush=True)
    if not cond:
        sys.exit(1)


def main() -> None:
    state = Path(sys.argv[1]).resolve()
    state.mkdir(parents=True, exist_ok=True)
    store = records.Store(state=state)
    task = next(t for t in json.loads((AIRLINE / "claude-3-7-sonnet-20250219_airline_default_gpt-4.1-2025-04-14_4trials.json").read_text())["tasks"] if t["id"] == "40")
    case = records.open_case(store, "40", evaluate.ensure_evaluator(store))
    shutil.copy(AIRLINE / "db.json", case.dir / "db.json")
    (case.dir / "task.json").write_text(json.dumps(task))
    tracer = telemetry.tracer("tau2-roleplay", case.dir / "spans.jsonl")
    transcript = []

    def say(role: str, text: str) -> None:
        cid = case.message("agent" if role == "assistant" else "counterparty", text)
        transcript.append({"role": role, "content": text, "at": records.utc(__import__("datetime").datetime.now(__import__("datetime").timezone.utc)), "capsule_id": cid})
        if role == "user":
            (case.dir / "last_customer.json").write_text(json.dumps({"capsule_id": cid, "text": text}))
        (case.dir / "transcript.json").write_text(json.dumps(transcript))

    airline = airline_mcp.Airline(case.dir, store)
    new_passengers = {"reservation_id": "3RK2T9", "passengers": [
        {"first_name": "Anya", "last_name": "Garcia", "dob": "1992-11-12"},
        {"first_name": "Mei", "last_name": "Garcia", "dob": "1989-12-13"}]}
    with tracer.start_as_current_span("support case scripted") :
        say("assistant", "Hi! How can I help you today?")
        say("user", "Please change Mei Lee's last name to Garcia on reservation 3RK2T9.")
        with tracer.start_as_current_span("turn 1 airline agent"):
            (case.dir / "traceparent").write_text(telemetry.traceparent())
            got = airline.call("get_reservation_details", {"reservation_id": "3RK2T9"})
            check('"3RK2T9"' in got, "a read tool runs without a confirmation")
            refused = airline.call("update_reservation_passengers", new_passengers)
            check(refused.startswith("Not done"), "a write without the customer's yes is refused")
            db = json.loads((case.dir / "db.json").read_text())
            check(db["reservations"]["3RK2T9"]["passengers"][1]["last_name"] == "Lee", "the refused write changed nothing")
            say("assistant", "I will change passenger 2 from Mei Lee to Mei Garcia (born 1989-12-13). Shall I go ahead? Please reply yes.")
        say("user", "Yes.")
        with tracer.start_as_current_span("turn 2 airline agent"):
            (case.dir / "traceparent").write_text(telemetry.traceparent())
            done = airline.call("update_reservation_passengers", new_passengers)
            check('"Garcia"' in done, "the confirmed write runs")
            say("assistant", "Done: passenger 2 is now Mei Garcia.")
        again = airline.call("update_reservation_passengers", new_passengers)
        check(again.startswith("Not done"), "one yes authorizes one write only")
        say("user", "Thanks. ###STOP###")
    telemetry.shutdown()

    calls = [json.loads(x) for x in (case.dir / "tool_calls.jsonl").read_text().splitlines()]
    acts = [c for c in calls if c.get("perform")]
    check(len(acts) == 1, "exactly one perform sealed")
    spans = [json.loads(x) for x in (case.dir / "spans.jsonl").read_text().splitlines()]
    tool_span = [s for s in spans if s["context"]["span_id"].removeprefix("0x") == acts[0]["span_id"]]
    check(len(tool_span) == 1 and tool_span[0]["attributes"].get("aac.capsule_id") == acts[0]["perform"],
          "the write's span carries the perform's capsule id")
    check(len({s["context"]["trace_id"] for s in spans}) == 1, "every span is in the case's one trace")

    result = evaluate.evaluate(store, case.dir, evaluate.MOCK_JUDGE, "jev-1.13.0 (mock backend, no model read the evidence)")
    check(set(result["checks"]) == set(records.CHECKS) and bool(result["evaluation_capsule_id"]), "the evaluator signed a verdict on the three checks")
    summary = report.build(store, case.dir)
    for level in ("keep", "adjudicator"):
        v = summary["bundles"][level]["verify"]
        check(v.get("verdict") == "VALID" and v["exit_code"] == 0, f"bundle {level}: capsulectl deal verify VALID")
    adj = summary["bundles"]["adjudicator"]["report"]
    check(adj.get("rows_state") == "withheld" and not adj.get("rows"), "the adjudicator copy withholds the rows")
    check((case.dir / "report" / "report.html").exists(), "report.html written")
    print(f"case: {case.dir}")


if __name__ == "__main__":
    main()
