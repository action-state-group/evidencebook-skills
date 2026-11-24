# SPDX-License-Identifier: Apache-2.0
"""Run one live tau2 airline support case between two Goose agents, sealed as it happens.

    uv run python roleplay.py --task 0

The airline agent is Goose with the airline tool server (airline_mcp.py) and the
tau2 airline policy; the customer is a second Goose session given tau2's user
simulation guidelines and one task's scenario, with no tools. This script relays
each message from one to the other, turn by turn, and seals every turn in the
airline's journal as it is said. Nothing is replayed from tau2's shipped runs.

Goose's ACP providers drop the system prompt, so each role's instructions go in
its session's first message. Both sessions run with ``--no-profile``: only the
extensions named here, none of the user's own.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import evaluate
import records
import telemetry

HERE = Path(__file__).resolve().parent
AIRLINE = HERE.parent.parent / "airline-data"
SCENARIOS = AIRLINE / "claude-3-7-sonnet-20250219_airline_default_gpt-4.1-2025-04-14_4trials.json"
GOOSE_APP = "/Applications/Goose.app/Contents/Resources/bin/goose"
STOP_TOKENS = ("###STOP###", "###TRANSFER###", "###OUT-OF-SCOPE###")
GREETING = "Hi! How can I help you today?"
CURRENT_CASE: list[Path] = []  # the case this run opened, for the exit status

AIRLINE_BRIEF = """You are the customer service agent of a fictional airline. Follow the airline policy below exactly.
Use only the airline tools you have (the ones named get_*, search_*, update_*, book_*, cancel_*, send_*, list_*, calculate, transfer_*) and no other tool.
You talk with one customer; each message I send you is the customer's message, and your reply is sent to them as it is.
Before any action that changes the booking database: first call the write tool with the exact arguments you intend. It changes nothing yet and records the action as pending. Read that exact action to the customer and ask for an explicit "yes". After they say yes, call the same tool again with exactly the same arguments. A yes authorizes only the action it answered, once.
Reply in English, in plain text, one message at a time.

<policy>
{policy}
</policy>

The customer's first message follows.

{first}"""

CUSTOMER_BRIEF = """{guidelines}

<scenario>
{scenario}
</scenario>

Reply in English with only your next message to the agent, nothing else. The agent's first message follows.

{first}"""


def goose_bin() -> str:
    found = shutil.which("goose")
    if found:
        return found
    if Path(GOOSE_APP).exists():
        return GOOSE_APP
    sys.exit("goose not found: install Goose (https://block.github.io/goose/) or put it on PATH")


def last_text(output: str) -> str:
    """The assistant's final text from ``goose run --output-format json``."""
    start = output.find("{")
    data = json.loads(output[start:])
    for msg in reversed(data.get("messages", [])):
        if msg.get("role") == "assistant":
            texts = [c.get("text", "") for c in msg.get("content", []) if c.get("type") == "text"]
            if any(t.strip() for t in texts):
                return "\n".join(t for t in texts if t.strip()).strip()
    raise RuntimeError("goose returned no assistant text")


class Session:
    """One Goose session, resumed by name on every turn."""

    def __init__(self, name: str, root: Path, extension: str | None = None, max_turns: int = 25):
        self.name, self.root, self.extension, self.max_turns = name, root, extension, max_turns
        self.started = False

    def say(self, text: str) -> str:
        cmd = [goose_bin(), "run", "--no-profile", "--name", self.name, "-t", text,
               "--output-format", "json", "--max-turns", str(self.max_turns)]
        if self.started:
            cmd.append("--resume")  # the resumed session keeps its extension
        elif self.extension:
            cmd += ["--with-extension", self.extension]
        env = dict(os.environ, GOOSE_MODE="auto")
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL,
                              cwd=self.root, timeout=900)
        if proc.returncode != 0:
            raise RuntimeError(f"goose ({self.name}) exited {proc.returncode}: {(proc.stderr + proc.stdout)[-2000:]}")
        self.started = True
        return last_text(proc.stdout)


def scenario(task_id: str) -> tuple[dict, str]:
    data = json.loads(SCENARIOS.read_text())
    task = next((t for t in data["tasks"] if str(t["id"]) == str(task_id)), None)
    if task is None:
        sys.exit(f"no tau2 airline task {task_id} in {SCENARIOS.name}")
    return task, data["info"]["user_info"]["global_simulation_guidelines"]


def run(args: argparse.Namespace) -> Path:
    store = records.Store(state=args.state.resolve(), window=args.window)
    store.state.mkdir(parents=True, exist_ok=True)
    task, guidelines = scenario(args.task)
    judge_key = evaluate.ensure_evaluator(store)  # the evaluator's own key, never the airline's (u534)
    case = records.open_case(store, str(args.task), judge_key)
    CURRENT_CASE.append(case.dir)
    shutil.copy(AIRLINE / "db.json", case.dir / "db.json")
    (case.dir / "task.json").write_text(json.dumps(task, indent=1))
    tracer = telemetry.tracer("tau2-roleplay", case.dir / "spans.jsonl")
    transcript: list[dict] = []
    q = shlex.quote  # Goose reads the extension as '[name:]ENV=value ... command args'
    env = {"TAU2_CASE_DIR": str(case.dir), "TAU2_STATE": str(store.state)}
    env.update({k: os.environ[k] for k in ("PATH", "CAPSULECTL_PLUGIN_ROOTS") if os.environ.get(k)})
    server = ("airline:" + " ".join(f"{k}={q(v)}" for k, v in env.items()) + " " +
              " ".join(q(x) for x in (shutil.which("uv") or "uv", "run", "--project", str(HERE), "python", str(HERE / "airline_mcp.py"))))
    agent = Session(f"{case.dir.name}-airline", case.dir, extension=server)
    customer = Session(f"{case.dir.name}-customer", case.dir, max_turns=1)

    def seal(role: str, text: str) -> str:
        now = datetime.now(timezone.utc)
        capsule_id = case.message("agent" if role == "assistant" else "counterparty", text, now)
        at_ns = time.time_ns()
        transcript.append({"role": role, "content": text, "at": records.utc(now), "at_ns": at_ns, "capsule_id": capsule_id})
        if role == "user":
            (case.dir / "last_customer.json").write_text(json.dumps({"capsule_id": capsule_id, "text": text, "at_ns": at_ns}))
        (case.dir / "transcript.json").write_text(json.dumps(transcript, indent=1))
        print(f"[{role}] {text}\n", flush=True)
        return capsule_id

    with tracer.start_as_current_span(f"support case tau2 airline task {args.task}") as root:
        root.set_attribute("tau2.task_id", str(args.task))
        root.set_attribute("deal.id", case.deal_id)
        root.set_attribute("evidencebook.book", case.book)
        root.set_attribute("evidencebook.window", case.window)
        with tracer.start_as_current_span("turn 0 airline greeting") as span:
            telemetry.stamp(span, seal("assistant", GREETING))
        reply = customer.say(CUSTOMER_BRIEF.format(guidelines=guidelines, scenario=json.dumps(task["user_scenario"]["instructions"], indent=1), first=GREETING))
        for turn in range(1, args.max_turns + 1):
            with tracer.start_as_current_span(f"turn {turn} customer") as span:
                telemetry.stamp(span, seal("user", reply))
            if any(tok in reply for tok in STOP_TOKENS):
                break
            with tracer.start_as_current_span(f"turn {turn} airline agent") as span:
                first = turn == 1
                text = AIRLINE_BRIEF.format(policy=(AIRLINE / "policy.md").read_text(), first=reply) if first else reply
                # Goose starts the tool server as its own process, so the server
                # reads the current turn's trace context from this file.
                (case.dir / "traceparent").write_text(telemetry.traceparent())
                answer = agent.say(text)
                telemetry.stamp(span, seal("assistant", answer))
            reply = customer.say(answer)
    telemetry.shutdown()
    records.set_status(case.dir, "complete")
    print(f"case: {case.dir}")
    return case.dir


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--task", default="0", help="tau2 airline task id (0-49)")
    p.add_argument("--state", type=Path, default=HERE / "state", help="where the demo keeps books and cases")
    p.add_argument("--window", default="month", choices=records.WINDOWS)
    p.add_argument("--max-turns", type=int, default=20)
    try:
        run(p.parse_args())
    except (KeyboardInterrupt, RuntimeError, subprocess.TimeoutExpired, records.RecordError) as err:
        # Every turn said so far is already sealed; the case is marked as not complete,
        # so evaluate.py and report.py refuse it unless told otherwise.
        status = "stopped" if isinstance(err, KeyboardInterrupt) else "error"
        if CURRENT_CASE:
            records.set_status(CURRENT_CASE[0], status, None if status == "stopped" else str(err))
        print(f"\n{status}: {'' if status == 'stopped' else str(err)[-500:] + chr(10)}"
              f"the turns said so far stay sealed in {CURRENT_CASE[0] if CURRENT_CASE else 'the case directory'}; "
              "the next run opens a new case", file=sys.stderr)
        sys.exit(130 if status == "stopped" else 1)


if __name__ == "__main__":
    main()
