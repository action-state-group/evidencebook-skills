"""Thin helpers the two exercise scripts share: call capsulectl, read its JSON."""

import datetime
import hashlib
import json
import pathlib
import re
import subprocess

_FRACTIONAL_SECONDS = re.compile(r"\.(\d+)")


def parse_rfc3339(timestamp):
    """capsulectl stamps appended_at with Go's RFC3339Nano, which trims trailing
    zeros from the fractional seconds -- so the digit count varies record to
    record (".39222" as readily as ".781403"). Python's fromisoformat before 3.11
    only accepts exactly 0, 3 or 6 fractional digits and raises on anything else
    (seen in practice: a Close capsule's real wall-clock append time, 5 digits,
    crashed a second daily-judge-and-close run that lists every published capsule
    including it). Pad or truncate to 6 digits so any valid RFC3339 timestamp
    parses, whatever the producer trimmed."""
    ts = timestamp.replace("Z", "+00:00")
    m = _FRACTIONAL_SECONDS.search(ts)
    if m:
        frac = (m.group(1) + "000000")[:6]
        ts = ts[:m.start()] + "." + frac + ts[m.end():]
    return datetime.datetime.fromisoformat(ts)


class EvidenceUnavailable(Exception):
    """A consequential step produced no record. The run stops at this step."""


def run(capsulectl, *args, check=True):
    """Run one capsulectl verb and return its JSON result (or None)."""
    proc = subprocess.run([capsulectl, *args], capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise EvidenceUnavailable(f"capsulectl {args[0]} exited {proc.returncode}: {proc.stderr.strip()}")
    out = proc.stdout.strip()
    return json.loads(out) if out else None


def sha256_file(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def list_capsules(capsulectl, profile):
    """Every log entry that records a capsule, in log order, paging through."""
    entries, after = [], 0
    while True:
        page = run(capsulectl, "cll", "list", "--profile", profile, "--after", str(after), "--limit", "1000")
        batch = page.get("entries") or []
        if not batch:
            return entries
        entries.extend(batch)
        after = page["next_after"]


def payload(capsulectl, profile, capsule_id):
    """The decoded payload of one stored capsule (readable `get`)."""
    record = run(capsulectl, "get", "--profile", profile, "--capsule-id", capsule_id)
    for artifact in record.get("artifacts") or []:
        if artifact.get("name") == "payload":
            return artifact.get("content")
    return None


def verify(capsulectl, profile, capsule_id, workdir):
    """Authenticate one stored capsule before acting on it: get --raw, then verify."""
    path = pathlib.Path(workdir) / f"{capsule_id}.json"
    if not path.exists():
        run(capsulectl, "get", "--profile", profile, "--capsule-id", capsule_id, "--raw", "--output", str(path))
    result = subprocess.run([capsulectl, "verify", "--profile", profile, "--capsule", str(path)], capture_output=True, text=True)
    if result.returncode != 0:
        raise EvidenceUnavailable(f"capsule {capsule_id} does not verify: {result.stderr.strip()}")


def committed_on(entry, day):
    return parse_rfc3339(entry["appended_at"]).date() == day


def case_id_of(case):
    """The one case_id convention every reader of a sealed tau2 case shares
    (scripts/run_daily.py, scripts/rollup_day.py's per-case output filenames,
    scripts/report_spec.py's own case rows) -- demo/backfill/backfill.py's own
    `case` block shape (benchmark/domain/task_id/trial), never redefined
    per-caller."""
    return f"{case['benchmark']}:{case['domain']}:task-{case['task_id']}:trial-{case['trial']}"


def publish(capsulectl, profile, request, workdir, name):
    """Seal one record into the book. The request's Timestamp is fixed by the
    caller, so publishing the same record again returns the same capsule."""
    path = pathlib.Path(workdir) / f"{name}.request.json"
    path.write_text(json.dumps(request, sort_keys=True))
    return run(capsulectl, "publish", "--profile", profile, "--request", str(path))["capsule_id"]


def seal_request(action_id, operator, developer, timestamp, body):
    return {
        "spec_version": "capsule-seal-request/v1",
        "capsule": {"ActionID": action_id, "ActionType": "fyi", "Operator": operator,
                    "Developer": developer, "Timestamp": timestamp},
        "payload": body,
    }
