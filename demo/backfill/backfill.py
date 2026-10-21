#!/usr/bin/env python3
"""Backfill a tau2-bench results file into capsule-seal-request/v1 files.

    backfill.py --results <tau2 results/final/*.json> --out <dir> [--trial N]

Input is one shipped tau2 results file; output is one seal request per task — its
trial-N simulation (agent + user-simulator transcript; trial 0 unless --trial
says otherwise). It reads only the results file:
no agent run, no user simulator, no model API key, and nothing synthesized. Then
`capsulectl publish --request <file>` seals each into a Capsule and appends it to
the CLL.

Each request's bound `payload` carries the real `agent_interaction` (transcript +
tool calls, with each call's `requestor` attribution), a `case` block
(benchmark/domain/task_id/trial, plus agent_model with --case-model), and
`provenance`. The gold outcome — tau2's own `reward_info` and the task's `evaluation_criteria` — is deliberately excluded;
the judge reads the desired outcome independently from the dataset by
`payload.case.task_id`.

The domain is read from the results file. Operator/Developer are the fixed
provenance identities of this backfill tool, not per-run inputs.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts"))
from capsulectl_calls import check_agent_model  # noqa: E402

OPERATOR = "tau2-demo"
DEVELOPER = "tau2@backfill-v1"


def normalize_timestamp(value: object, simulation_id: object) -> str:
    """Whole-seconds UTC RFC3339 from the simulation's own timestamp.

    A fabricated (wall-clock) timestamp would make the content-addressed Capsule
    ID non-reproducible, so a missing or unparseable stamp is a hard error.
    """
    if not isinstance(value, str) or not value:
        raise SystemExit(f"simulation {simulation_id!r} has no usable timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise SystemExit(f"simulation {simulation_id!r} has an unparseable timestamp {value!r}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def trim_message(message: dict) -> dict:
    """Keep the interaction-bearing fields and tool-call attribution.

    Drops cost/usage/raw_data/turn bookkeeping but preserves `requestor` so an
    agent tool call is never confused with a user-simulator one.
    """
    kept: dict = {"role": message.get("role"), "content": message.get("content")}
    if message.get("tool_calls"):
        kept["tool_calls"] = [
            {"id": c.get("id"), "name": c.get("name"),
             "arguments": c.get("arguments"), "requestor": c.get("requestor")}
            for c in message["tool_calls"]
        ]
    if message.get("role") == "tool":
        kept["tool_call_id"] = message.get("id")
        kept["requestor"] = message.get("requestor")
        if message.get("error"):
            kept["error"] = message["error"]
    return kept


def case_block(domain: str, task_id: object, trial: object, agent_llm: object, with_model: bool) -> dict:
    """The sealed `case` block. With `with_model`, it also names the agent model the
    results file ran, so runs of the same task and trial by different agents are
    different cases (scripts/capsulectl_calls.case_id_of puts it in the case id)."""
    case = {"benchmark": "tau2", "domain": domain, "task_id": task_id, "trial": trial}
    if with_model:
        if not isinstance(agent_llm, str) or not agent_llm:
            raise SystemExit("--case-model: the results file names no agent_info.llm")
        try:  # checked here, before sealing: the book is append-only
            case["agent_model"] = check_agent_model(agent_llm)
        except ValueError:
            raise SystemExit(f"--case-model: agent model {agent_llm!r} can't go in a case id; it must match "
                             f"[A-Za-z0-9._-]+ (no ':' or '/'). Rename the agent_info.llm in the results "
                             f"file, or backfill without --case-model")
    return case


def build_request(sim: dict, info: dict, results_name: str, domain: str, with_model: bool = False) -> dict:
    task_id = sim["task_id"]
    trial = sim["trial"]
    case = case_block(domain, task_id, trial, (info.get("agent_info") or {}).get("llm"), with_model)
    agent = f"{case['agent_model']}:" if with_model else ""
    return {
        "spec_version": "capsule-seal-request/v1",
        "capsule": {
            "ActionID": f"urn:tau2:{domain}:{agent}task-{task_id}:trial-{trial}",
            "ActionType": "fyi",
            "Operator": OPERATOR,
            "Developer": DEVELOPER,
            "Timestamp": normalize_timestamp(sim.get("timestamp") or sim.get("start_time"), sim.get("id")),
        },
        "payload": {
            "case": case,
            "provenance": {
                "results_file": results_name,
                "agent_llm": (info.get("agent_info") or {}).get("llm"),
                "user_simulator_llm": (info.get("user_info") or {}).get("llm"),
                "simulation_id": sim.get("id"),
                "seed": sim.get("seed"),
                "termination_reason": sim.get("termination_reason"),
            },
            "agent_interaction": {"messages": [trim_message(m) for m in sim.get("messages", [])]},
        },
    }


def safe_name(task_id: object) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(task_id))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", required=True, type=pathlib.Path,
                    help="a tau2 results file (data/tau2/results/final/*.json)")
    ap.add_argument("--out", required=True, type=pathlib.Path,
                    help="output directory; one seal request per task (its run for --trial)")
    ap.add_argument("--trial", type=int, default=0,
                    help="which of each task's trials to seal (default 0; tau2's 4-trial files hold 0-3)")
    ap.add_argument("--case-model", action="store_true",
                    help="also name the agent model in each case (and so in its case id), so several "
                         "agents' runs of one task and trial can share a book")
    args = ap.parse_args(argv)
    if args.trial < 0:
        ap.error("--trial must be 0 or more")

    data = json.loads(args.results.read_text())
    sims = data.get("simulations")
    if not isinstance(sims, list) or not sims:
        raise SystemExit(f"{args.results} has no simulations[]")
    info = data.get("info", {})
    domain = (info.get("environment_info") or {}).get("domain_name")
    if not domain:
        raise SystemExit("results file has no environment_info.domain_name")

    # one interaction per task: its simulation for the chosen trial
    chosen = [s for s in sims if s.get("trial") == args.trial]
    if not chosen:
        raise SystemExit(f"{args.results} has no trial-{args.trial} simulations")

    args.out.mkdir(parents=True, exist_ok=True)
    # clear our own prior outputs so a reused dir can't leak a different/smaller run
    for stale in args.out.glob("task-*.json"):
        stale.unlink()
    # NOTE: CLL sequence is set by the publish order, which is the shell glob over these
    # filenames (lexical: task-0, task-1, task-10, …, task-2), not task_id order. Only a
    # per-case selection (by capsule/case id) is reliable; do not assume sequence == task.
    used: dict[str, int] = {}
    for sim in sorted(chosen, key=lambda s: str(s["task_id"])):
        request = build_request(sim, info, args.results.name, domain, args.case_model)
        stem = f"task-{safe_name(sim['task_id'])}"
        n = used.get(stem, 0)
        used[stem] = n + 1
        name = f"{stem}.json" if n == 0 else f"{stem}-{n}.json"
        (args.out / name).write_text(json.dumps(request, indent=2) + "\n")
    print(f"wrote {len(chosen)} seal requests (domain={domain}, one per task, trial {args.trial}) to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
