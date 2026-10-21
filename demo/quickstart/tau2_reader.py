#!/usr/bin/env python3
"""A reader for the quick start (docs/quickstart.md): tau2 airline logs in, capsulectl's formats out.

capsulectl holds no host-specific code. A reader like this one selects what the
host recorded and writes it in capsulectl's two input formats: the effects rows
`capsulectl book backfill run` reads (backfill-source-record/v0), and one
capsule-seal-request/v1 per conversation for `capsulectl publish`. Your own
reader does the same for your own logs.

The "host" here is a published tau2-bench results file (airline-data/). Every
conversation in it was recorded on one day. To show a book that spans months,
the reader can spread the chosen conversations over a replay schedule: each
one is moved by whole days onto its replay day, clock time kept. The replayed
time is the host time the backfill records (self-attested; no witness corroborates it),
and each case record states the replay in words and keeps the original time.
Leave --replay-from out and the original times are used unchanged.

    tau2_reader.py rows --results FILE --tasks 0,1,4 [--trial 0] \\
        [--replay-from 2025-07-01 --replay-step-days 18] --out DIR
        writes DIR/rows.jsonl (one backfill-source-record/v0 row per agent tool
        call, cursor monotonic per source in host-time order, `handoff` signal
        on transfer_to_human_agents, one horizon line per source) and
        DIR/plan.json (what was chosen and each conversation's host time).

    tau2_reader.py cases --plan DIR --import-batch B --imported-at T
        writes DIR/requests/<task>.json: one capsule-seal-request/v1 per
        conversation, provenance_mode "backfilled", source_asserted_at its host
        time, import_batch/imported_at from the backfill pass that committed its
        rows, time_rung self_attested.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backfill"))
import backfill as bf  # noqa: E402  demo/backfill: the {case, agent_interaction} builder

HANDOFF_TOOLS = {"transfer_to_human_agents"}


def jcs_digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def utc(ts: str) -> dt.datetime:
    t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    # tau2 writes no zone; read its clock times as UTC
    return t.replace(tzinfo=None) if t.tzinfo is None else t.astimezone(dt.timezone.utc).replace(tzinfo=None)


def rfc(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%S") + (f".{t.microsecond:06d}" if t.microsecond else "") + "Z"


def load(results: pathlib.Path, tasks: list[str], trial: int):
    data = json.loads(results.read_text())
    info = data["info"]
    sims = {str(s["task_id"]): s for s in data["simulations"] if s["trial"] == trial}
    missing = [t for t in tasks if t not in sims]
    if missing:
        sys.exit(f"{results.name} has no trial-{trial} run for task(s) {', '.join(missing)}")
    return info, [sims[t] for t in tasks]


def rows(a) -> None:
    tasks = [t.strip() for t in a.tasks.split(",") if t.strip()]
    info, sims = load(a.results, tasks, a.trial)
    dom, llm = info["environment_info"]["domain_name"], info["agent_info"]["llm"]
    source = f"tau2.{dom}.{llm}".lower()
    convs = []
    for i, sim in enumerate(sims):
        orig = utc(sim["timestamp"])
        shift = dt.timedelta(0)
        if a.replay_from:
            day = dt.date.fromisoformat(a.replay_from) + dt.timedelta(days=i * a.replay_step_days)
            shift = dt.datetime.combine(day, dt.time()) - dt.datetime.combine(orig.date(), dt.time())
        convs.append((sim, orig, shift))
    out_rows, cursor, plan = [], 0, []
    # the cursor follows the host's own order (host time), never a timestamp watermark
    for sim, orig, shift in sorted(convs, key=lambda c: c[1] + c[2]):
        case_id = f"tau2:{dom}:task-{sim['task_id']}:trial-{sim['trial']}"
        results = {m.get("id"): m for m in sim["messages"] if m.get("role") == "tool"}
        for msg in sim["messages"]:
            for call in msg.get("tool_calls") or []:
                if call.get("requestor") != "assistant":
                    continue
                result = results.get(call["id"])
                row = {"kind": "row", "source": source, "cursor": cursor, "id": call["id"],
                       "at": rfc(utc(msg["timestamp"]) + shift), "record_kind": "tool_call", "task": case_id,
                       "tool_call_id": call["id"], "tool": call["name"],
                       "status": "missing" if result is None else ("error" if result.get("error") else "ok"),
                       # SHA-256 of the whole row as the host stored it: the call and its result
                       "raw_digest": jcs_digest({"tool_call": call, "tool_result": result})}
                if call["name"] in HANDOFF_TOOLS:
                    row["signals"] = ["handoff"]
                out_rows.append(row)
                cursor += 1
        plan.append({"task_id": str(sim["task_id"]), "trial": sim["trial"], "case_id": case_id,
                     "original_recorded_at": sim["timestamp"], "host_time": rfc(orig + shift),
                     "shift_days": shift.days})
    if out_rows:
        out_rows.append({"kind": "horizon", "source": source, "cursor": 0, "at": out_rows[0]["at"], "limited": False})
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "rows.jsonl").write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in out_rows))
    (a.out / "plan.json").write_text(json.dumps({
        "results": str(a.results.resolve()), "trial": a.trial, "source": source,
        "replay": ({"from": a.replay_from, "step_days": a.replay_step_days} if a.replay_from else None),
        "conversations": plan}, indent=1) + "\n")
    print(json.dumps({"conversations": len(plan), "rows": len(out_rows) - (1 if out_rows else 0),
                      "source": source, "host_time_span": [plan[0]["host_time"], plan[-1]["host_time"]] if plan else []}))


def cases(a) -> None:
    plan = json.loads((a.plan / "plan.json").read_text())
    tasks = [c["task_id"] for c in plan["conversations"]]
    info, sims = load(pathlib.Path(plan["results"]), tasks, plan["trial"])
    dom = info["environment_info"]["domain_name"]
    out = a.plan / "requests"
    out.mkdir(parents=True, exist_ok=True)
    for conv, sim in zip(plan["conversations"], sims):
        req = bf.build_request(sim, info, pathlib.Path(plan["results"]).name, dom)
        prov = req["payload"]["provenance"]
        if conv["shift_days"]:
            prov["original_recorded_at"] = conv["original_recorded_at"]
            prov["replay"] = (f"Replay schedule: originally recorded {conv['original_recorded_at'][:10]}, moved "
                              f"{conv['shift_days']} days onto {conv['host_time'][:10]}, clock time kept. "
                              "The date is the replay schedule's, not when the run happened.")
        req["capsule"]["Timestamp"] = a.imported_at
        req["provenance_mode"] = {
            "mode": "backfilled",
            "source_ref": {"type": "tau2-simulation", "digest_alg": "SHA-256", "digest": jcs_digest(sim)},
            "source_asserted_at": conv["host_time"],
            "import_batch": a.import_batch,
            "imported_at": a.imported_at,
            "time_rung": "self_attested",
        }
        (out / f"task-{conv['task_id']}.json").write_text(json.dumps(req, indent=1) + "\n")
    print(json.dumps({"seal_requests": len(sims), "dir": str(out)}))


def main(argv) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("rows")
    r.add_argument("--results", type=pathlib.Path, required=True)
    r.add_argument("--tasks", required=True, help="comma-separated tau2 task ids")
    r.add_argument("--trial", type=int, default=0)
    r.add_argument("--replay-from", help="YYYY-MM-DD: spread the conversations over a replay schedule from this day")
    r.add_argument("--replay-step-days", type=int, default=1)
    r.add_argument("--out", type=pathlib.Path, required=True)
    c = sub.add_parser("cases")
    c.add_argument("--plan", type=pathlib.Path, required=True, help="the --out DIR of `rows`")
    c.add_argument("--import-batch", required=True)
    c.add_argument("--imported-at", required=True)
    a = ap.parse_args(argv)
    rows(a) if a.cmd == "rows" else cases(a)


if __name__ == "__main__":
    main(sys.argv[1:])
