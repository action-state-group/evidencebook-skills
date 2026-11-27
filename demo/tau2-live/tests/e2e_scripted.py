# SPDX-License-Identifier: Apache-2.0
"""End to end without Goose: a canned two-party script through the real records,
tool server (in process and over MCP stdio), evaluator (mock judge) and report,
ending in two bundles that capsulectl deal verify accepts.

    uv run python tests/e2e_scripted.py STATE_DIR

Needs capsulectl with the deal and book plugins, and capsule-engine, on PATH (or
CAPSULECTL_PLUGIN_ROOTS for the plugins). Exits non-zero on the first failed check.
The store ticks every minute (records.Store cadence), so the report step waits at most
a minute for its checkpoint, not the five of capsulectl's default cadence (#427).
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
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
SCENARIOS = AIRLINE / "claude-3-7-sonnet-20250219_airline_default_gpt-4.1-2025-04-14_4trials.json"


def check(cond: bool, what: str) -> None:
    print(("ok   " if cond else "FAIL ") + what, flush=True)
    if not cond:
        sys.exit(1)


async def over_stdio(store: records.Store, case_dir: Path) -> None:
    """The real server process, as Goose starts it, through an MCP client."""
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    env = dict(os.environ, TAU2_CASE_DIR=str(case_dir), TAU2_STATE=str(store.state))
    params = StdioServerParameters(command=sys.executable, args=[str(HERE / "airline_mcp.py")], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            check(len(tools.tools) == 14, "over stdio: the server lists tau2's 14 airline tools")
            got = await session.call_tool("get_user_details", {"user_id": "anya_garcia_5901"})
            check('"anya_garcia_5901"' in got.content[0].text, "over stdio: a read tool answers")


def main() -> None:
    state = Path(sys.argv[1]).resolve()
    state.mkdir(parents=True, exist_ok=True)
    store = records.Store(state=state, cadence="1m")
    task = next(t for t in json.loads(SCENARIOS.read_text())["tasks"] if t["id"] == "40")
    case = records.open_case(store, "40", evaluate.ensure_evaluator(store))
    meta = json.loads((case.dir / "case.json").read_text())
    month = meta["window"]  # read once: the run spans minutes and may cross a month end
    windows = store.run("deal", "window", "list", profile=case.book)
    check(windows["window"] == "month" and [w["label"] for w in windows["windows"]] == [month],
          "one store, split by month: its one window is the case's window")
    check(meta["deal_book"] in windows["windows"][0]["placed"],
          "the case's deal book is placed in the window case.json names, read from deal window list")
    shutil.copy(AIRLINE / "db.json", case.dir / "db.json")
    (case.dir / "task.json").write_text(json.dumps(task))
    tracer = telemetry.tracer("tau2-roleplay", case.dir / "spans.jsonl")
    transcript = []

    def say(role: str, text: str) -> None:
        cid = case.message("agent" if role == "assistant" else "counterparty", text)
        at_ns = time.time_ns()
        transcript.append({"role": role, "content": text, "at": records.utc(datetime.now(timezone.utc)),
                           "at_ns": at_ns, "capsule_id": cid})
        if role == "user":
            (case.dir / "last_customer.json").write_text(json.dumps({"capsule_id": cid, "text": text, "at_ns": at_ns}))
        (case.dir / "transcript.json").write_text(json.dumps(transcript))

    def lee(db_path: Path) -> str:
        return json.loads(db_path.read_text())["reservations"]["3RK2T9"]["passengers"][1]["last_name"]

    airline = airline_mcp.Airline(case.dir, store)
    rename = {"reservation_id": "3RK2T9", "passengers": [
        {"first_name": "Anya", "last_name": "Garcia", "dob": "1992-11-12"},
        {"first_name": "Mei", "last_name": "Garcia", "dob": "1989-12-13"}]}
    other = {"reservation_id": "3RK2T9", "passengers": [
        {"first_name": "Anya", "last_name": "Garcia", "dob": "1992-11-12"},
        {"first_name": "Mei", "last_name": "Smith", "dob": "1989-12-13"}]}
    with tracer.start_as_current_span("support case scripted"):
        say("assistant", "Hi! How can I help you today?")
        say("user", "Yes, please change Mei Lee's last name to Garcia on reservation 3RK2T9.")
        with tracer.start_as_current_span("turn 1 airline agent"):
            (case.dir / "traceparent").write_text(telemetry.traceparent())
            got = airline.call("get_reservation_details", {"reservation_id": "3RK2T9"})
            check('"3RK2T9"' in got, "a read tool runs without a confirmation")
            proposed = airline.call("update_reservation_passengers", rename)
            check(proposed.startswith("Not done yet"), "the first write call only proposes the action")
            check(lee(case.dir / "db.json") == "Lee", "a proposal changes nothing")
            again = airline.call("update_reservation_passengers", rename)
            check(again.startswith("Not done yet"), "a yes sealed before the proposal does not authorize it")
            say("assistant", "I will change passenger 2 from Mei Lee to Mei Garcia (born 1989-12-13). Shall I go ahead?")
        say("user", "Yes, but make it Smith instead.")
        with tracer.start_as_current_span("turn 2 airline agent"):
            (case.dir / "traceparent").write_text(telemetry.traceparent())
            hedged = airline.call("update_reservation_passengers", rename)
            check(hedged.startswith("Not done yet") and lee(case.dir / "db.json") == "Lee", "a hedged yes authorizes nothing")
            say("assistant", "To confirm: passenger 2 becomes Mei Garcia. Reply yes to go ahead.")
        say("user", "Yes.")
        with tracer.start_as_current_span("turn 3 airline agent"):
            (case.dir / "traceparent").write_text(telemetry.traceparent())
            swapped = airline.call("update_reservation_passengers", other)
            check(swapped.startswith("Not done yet") and lee(case.dir / "db.json") == "Lee",
                  "a yes to one action does not authorize a different one")
            say("assistant", "Sorry, to confirm once more: passenger 2 becomes Mei Garcia. Reply yes.")
        say("user", "Yes.")
        with tracer.start_as_current_span("turn 4 airline agent"):
            (case.dir / "traceparent").write_text(telemetry.traceparent())
            proposed = airline.call("update_reservation_passengers", rename)
            check(proposed.startswith("Not done yet"), "the agent re-proposes the action it means")
            say("assistant", "Passenger 2 becomes Mei Garcia, born 1989-12-13. Shall I go ahead?")
        say("user", "Yes.")
        with tracer.start_as_current_span("turn 5 airline agent"):
            (case.dir / "traceparent").write_text(telemetry.traceparent())
            done = airline.call("update_reservation_passengers", rename)
            check('"Garcia"' in done and lee(case.dir / "db.json") == "Garcia", "the confirmed write runs")
            twice = airline.call("update_reservation_passengers", rename)
            check(twice.startswith("Not done yet"), "one yes authorizes one write only")
            say("assistant", "Done: passenger 2 is now Mei Garcia.")
        say("user", "Thanks. ###STOP###")
    telemetry.shutdown()
    asyncio.run(over_stdio(store, case.dir))
    records.set_status(case.dir, "complete")

    calls = [json.loads(x) for x in (case.dir / "tool_calls.jsonl").read_text().splitlines()]
    acts = [c for c in calls if c.get("perform")]
    check(len(acts) == 1, "exactly one perform sealed")
    check(acts[0].get("person_signature") == "missing", "the act shows person_signature: missing (agent-action-capsule#627)")
    perform_file = sorted(case.dir.glob("perform-*.json"))
    check(len(perform_file) == 1, "one perform file written")
    spans = [json.loads(x) for x in (case.dir / "spans.jsonl").read_text().splitlines()]
    tool_span = [s for s in spans if s["context"]["span_id"].removeprefix("0x") == acts[0]["span_id"]]
    check(len(tool_span) == 1 and tool_span[0]["attributes"].get("aac.capsule_id") == acts[0]["perform"],
          "the write's span carries the perform's capsule id")
    check(len({s["context"]["trace_id"] for s in spans}) == 1, "every span is in the case's one trace")

    result = evaluate.evaluate(store, case.dir, evaluate.MOCK_JUDGE, "jev-1.13.0 (mock backend, no model read the evidence)")
    check(set(result["checks"]) == set(records.CHECKS) and bool(result["evaluation_capsule_id"]),
          "the evaluator signed a verdict on the three checks")
    summary = report.build(store, case.dir)
    for level in ("keep", "adjudicator"):
        v = summary["bundles"][level]["verify"]
        check(v.get("verdict") == "VALID" and v["exit_code"] == 0, f"bundle {level}: capsulectl deal verify VALID")
    adj = summary["bundles"]["adjudicator"]["report"]
    check(adj.get("rows_state") == "withheld" and not adj.get("rows"), "the adjudicator copy withholds the rows")
    keep_rows = summary["bundles"]["keep"]["report"].get("rows") or []
    check({r.get("status") for r in keep_rows} == {"not_due"}, "the airline's rows are not yet due")
    check((case.dir / "report" / "report.html").exists(), "report.html written")
    rolled = store.run("deal", "window", "roll", profile=case.book)
    check(rolled["current"]["label"] >= month, "deal window roll opens no window before the case's")
    # The chain covers ended windows only, and capsulectl has no external clock to end one in a
    # real-time run (evidencebook#852 tracks a fixture): the CLI refuses a range on an open window.
    chain = store.capsulectl, "--profile", case.book, "deal", "window", "chain", "--from", month, "--to", month, "--out", str(case.dir / "chain.json")
    refused = subprocess.run(chain, capture_output=True, text=True, env=store.env(), stdin=subprocess.DEVNULL)
    # capsulectl suppresses the reason in its output ("operation failed ... sensitive details
    # suppressed"), so the check pairs the refusal with the window list showing the window open.
    check(refused.returncode != 0 and not (case.dir / "chain.json").exists() and not windows["windows"][0]["closed"],
          "deal window chain refuses a range that ends on an open window")
    print(f"case: {case.dir}")


if __name__ == "__main__":
    main()
