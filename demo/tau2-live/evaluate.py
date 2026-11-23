# SPDX-License-Identifier: Apache-2.0
"""The evaluator: judge one case on the tau2 airline rubric and sign the verdict itself.

    uv run python evaluate.py CASE_DIR [--judge-cmd ... --judge-model-id ...]

The evaluator is its own party with its own key and book (u534: each judge signs
its own verdict under its own key). It reads the case's transcript and tool log,
runs the repository's existing contract path on them (scripts/run_daily.py's
case_answers over demo/tau2-outcomes/compiled.json: the judge for judged clauses,
scripts/recompute.py's checkers where the contract asks), rolls the nine criteria
up into the three checks, and publishes one signed verdict record in its own book.
The airline's journal then cites that record by its capsule id: the airline holds
the verdict, it does not restate it as its own.

The default judge is goose_judge.py: the model Goose is configured with reads the
case. It is not the rubric's pinned judge (jev-1.13.0), which costs money per call
(``--judge-cmd`` runs it). ``--judge mock`` uses jev_judge.py's mock backend, a hash
of the request with no model. The verdict record names whichever judge ran.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import records

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
SPEC = REPO / "demo" / "tau2-outcomes" / "compiled.json"
sys.path.insert(0, str(REPO / "scripts"))

MOCK_JUDGE = f"{sys.executable} {REPO / 'scripts' / 'judges' / 'jev_judge.py'}"
GOOSE_JUDGE = f"{sys.executable} {HERE / 'goose_judge.py'}"
EVALUATOR = "tau2-evaluator"


def ensure_evaluator(store: records.Store) -> str:
    """The evaluator's book profile (its own keys), made on first use; returns its public key."""
    meta = store.state / "evaluator" / "evaluator.json"
    if meta.exists():
        return json.loads(meta.read_text())["public_key"]
    d = store.state / "evaluator"
    d.mkdir(parents=True, exist_ok=True)
    key = store.run("key", "generate", "--output", str(d / "signing.seed"))
    ckey = store.run("key", "generate", "--output", str(d / "checkpoint.seed"))
    store.run("profile", "create", "--name", EVALUATOR, "--type", "jsonl", "--jsonl-path", str(d / "store"),
              "--namespace", "tau2", "--log-id", "tau2-evaluator-log", "--log", "book", "--operator", EVALUATOR,
              "--signing-key-file", str(d / "signing.seed"), "--trusted-key", key["public_key"],
              "--checkpoint-signing-key-file", str(d / "checkpoint.seed"),
              "--checkpoint-trusted-key", ckey["public_key"])
    store.run("store", "init", profile=EVALUATOR)
    meta.write_text(json.dumps({"profile": EVALUATOR, "public_key": key["public_key"]}))
    return key["public_key"]


def messages(case_dir: Path) -> list[dict]:
    """The case as tau2 messages (the shape demo/backfill/backfill.py seals): the
    conversation turns and the airline agent's tool calls, in time order."""
    turns = json.loads((case_dir / "transcript.json").read_text())
    calls_path = case_dir / "tool_calls.jsonl"
    calls = [json.loads(line) for line in calls_path.read_text().splitlines()] if calls_path.exists() else []
    # Order by the nanosecond clock both writers record (at_ns); a case written before
    # that field existed falls back to the second, with a tool call ahead of a turn
    # sealed in the same second (a call happens during the turn it ends).
    def key(e, kind):
        return (e.get("at_ns") or 0, e["at"], -kind)
    events = [(key(t, 0), 0, i, t) for i, t in enumerate(turns)] + [(key(c, 1), 1, i, c) for i, c in enumerate(calls)]
    out: list[dict] = []
    for _, kind, i, e in sorted(events, key=lambda x: (x[0], x[2])):
        if kind == 0:
            out.append({"role": e["role"], "content": e["content"]})
            continue
        call_id = f"call-{i}"
        out.append({"role": "assistant", "content": None,
                    "tool_calls": [{"id": call_id, "name": e["tool"], "arguments": e["arguments"], "requestor": "assistant"}]})
        tool_msg = {"role": "tool", "content": e.get("result") or e.get("error") or e.get("gate"),
                    "tool_call_id": call_id, "requestor": "assistant"}
        if e.get("error"):
            tool_msg["error"] = True
        out.append(tool_msg)
    return out


def rollup(answers: dict, spec: dict) -> dict:
    """Each check is met only when every one of its criteria is met (the rubric's rule)."""
    checks: dict[str, str] = {}
    for clause in spec["clauses"]:
        verdict = answers.get(clause["id"], {}).get("verdict", "not_evaluable")
        prev = checks.get(clause["check_id"], "met")
        checks[clause["check_id"]] = prev if verdict == "met" else ("not_met" if verdict == "not_met" or prev == "not_met" else verdict)
    return checks


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluate(store: records.Store, case_dir: Path, judge_cmd: str, judge_model_id: str) -> dict:
    import run_daily

    spec = json.loads(SPEC.read_text())
    meta = json.loads((case_dir / "case.json").read_text())
    task = json.loads((case_dir / "task.json").read_text())
    body = {"case": {"benchmark": "tau2", "domain": "airline", "task_id": str(task["id"]), "trial": 0},
            "agent_interaction": {"messages": messages(case_dir)}}
    answers, prechecked = run_daily.case_answers(body, spec, spec.get("switches") or {}, REPO, judge_cmd, judge_model_id,
                                                 judge_batch_mode=bool(spec.get("judge_batch")))
    checks = rollup(answers, spec)
    now = datetime.now(timezone.utc)
    ensure_evaluator(store)
    request = {"spec_version": "capsule-seal-request/v1",
               "capsule": {"ActionID": f"urn:tau2-live:evaluation:{meta['deal_id']}", "ActionType": "fyi",
                           "Operator": EVALUATOR, "Developer": "tau2-live-evaluate@0.1.0", "Timestamp": records.utc(now)},
               "payload": {"type": "tau2-evaluation/v0",
                           "about": {"holder": store.holder, "book": meta["book"], "deal_id": meta["deal_id"],
                                     "task_id": str(task["id"]),
                                     "transcript_sha256": sha256(case_dir / "transcript.json"),
                                     "tool_calls_sha256": sha256(case_dir / "tool_calls.jsonl") if (case_dir / "tool_calls.jsonl").exists() else None},
                           "rubric": {"contract": spec["contract"], "contract_version": spec["contract_version"],
                                      "compiled_sha256": sha256(SPEC)},
                           "judge": {"model_id": judge_model_id, "recomputed": sorted(prechecked)},
                           "checks": checks,
                           "criteria": {k: {"verdict": v.get("verdict"), "rationale": v.get("rationale")}
                                        for k, v in sorted(answers.items())}}}
    req_path = case_dir / "evaluation-request.json"
    req_path.write_text(json.dumps(request, indent=1))
    published = store.run("publish", "--request", str(req_path), profile=EVALUATOR)
    capsule_id = published.get("capsule_id") or published.get("record", {}).get("capsule_id")
    if not capsule_id:
        raise records.RecordError(f"publish returned no capsule id: {published}")
    case = records.load_case(store, case_dir)
    cite = case.write("evaluation-cite.json", {"about": "the evaluator's signed verdict on this case",
                                              "source": "evaluator_verdict",
                                              "detail": f"tau2-evaluator verdict record {capsule_id}, signed by the evaluator's own key"})
    cited = store.run("deal", "note", "--deal", case.deal_id, "--kind", "evidence", "--input", str(cite), profile=case.book)
    result = {"evaluation_capsule_id": capsule_id, "checks": checks, "criteria": request["payload"]["criteria"],
              "judge_model_id": judge_model_id, "cited_by": cited.get("capsule_id")}
    (case_dir / "evaluation.json").write_text(json.dumps(result, indent=1))
    return result


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("case_dir", type=Path)
    p.add_argument("--state", type=Path, default=HERE / "state")
    p.add_argument("--judge", choices=("goose", "mock"), default="goose",
                   help="goose: a model through Goose reads the case (default); mock: jev_judge.py's hash, no model")
    p.add_argument("--judge-cmd", default=None, help="any run_daily.py judge command instead (with --judge-model-id)")
    p.add_argument("--judge-model-id", default=None)
    p.add_argument("--allow-incomplete", action="store_true", help="evaluate a case whose role-play did not complete")
    a = p.parse_args()
    records.require_complete(a.case_dir.resolve(), a.allow_incomplete)
    if a.judge_cmd:
        if not a.judge_model_id:
            p.error("--judge-cmd needs --judge-model-id")
        judge_cmd, model_id = a.judge_cmd, a.judge_model_id
    elif a.judge == "goose":
        import goose_judge
        judge_cmd, model_id = GOOSE_JUDGE, goose_judge.MODEL_ID
    else:
        os.environ["JEV_JUDGE_BACKEND"] = "mock"
        judge_cmd, model_id = MOCK_JUDGE, None
    if model_id is None:
        sys.path.insert(0, str(REPO / "scripts" / "judges"))
        import jev_judge
        model_id = jev_judge.sealed_model_id(jev_judge.PINNED_MODEL)
    print(json.dumps(evaluate(records.Store(state=a.state.resolve()), a.case_dir.resolve(), judge_cmd, model_id), indent=1))


if __name__ == "__main__":
    main()
