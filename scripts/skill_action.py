#!/usr/bin/env python3
"""Run one skill action and seal a skill-action/v1 capsule for it.

The exercise scripts (run_daily.py, run_weekly.py) seal their own steps. This is
for the actions a skill runs by hand from its SKILL.md: install, discover, map,
`contract validate`, `book result build`, and any other step. It runs the command,
passes its stdout and stderr through unchanged, and seals one record of it with
`capsulectl publish` (scripts/capsulectl_calls.py: skill_action_record).

    skill_action.py --profile NAME --skill evidence-contract-compile --action contract-validate \\
        --input contract=CONTRACT.yaml --input schema=SCHEMA.json \\
        -- capsulectl contract validate CONTRACT.yaml --schema SCHEMA.json --json

The record carries digests only: of each --input file, of the command's stdout,
and of its argv. It never carries file contents, paths, the profile or the
environment. Role names that name secret material (key, seed, token, ...) are
refused, and so are input files that look like key material.

--at is required: the capsule's timestamp is part of what it commits, so a
wall-clock default would mint a new capsule on every re-run. Pass the same --at
to re-run an action and the same capsule comes back (nothing new is sealed).

A failed command is sealed too (`outcome: failed`), and this script exits with
the command's own exit status. If the record cannot be sealed, it prints
`evidence unavailable` and exits 2 whatever the command did: an action with no
record stops the run.
"""

import argparse
import hashlib
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from capsulectl_calls import EvidenceUnavailable, run, sha256_file  # noqa: E402
from skill_record import emit_skill_action, json_digest, skill_action_record  # noqa: E402

KEY_MATERIAL_SUFFIXES = (".seed", ".key", ".pem", ".p12", ".pfx", ".env")


def parse_input(spec):
    role, sep, path = spec.partition("=")
    if not sep or not role or not path:
        raise EvidenceUnavailable(f"--input must be ROLE=PATH, got {spec!r}")
    p = pathlib.Path(path)
    if p.name.startswith(".env") or p.suffix.lower() in KEY_MATERIAL_SUFFIXES:
        raise EvidenceUnavailable(f"--input {role}: refusing a key-material file ({p.name})")
    if not p.is_file():
        raise EvidenceUnavailable(f"--input {role}: not a file: {path}")
    return role, sha256_file(p)


def main(argv):
    if "--" not in argv:
        print("usage: skill_action.py [options] -- COMMAND [ARGS...]", file=sys.stderr)
        return 2
    split = argv.index("--")
    own, command = argv[:split], argv[split + 1:]
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--skill", required=True)
    ap.add_argument("--action", required=True)
    ap.add_argument("--input", action="append", default=[], metavar="ROLE=PATH")
    ap.add_argument("--at", required=True,
                    help="RFC3339 UTC timestamp for the capsule; the same --at on a re-run seals the same capsule")
    ap.add_argument("--work", type=pathlib.Path, default=pathlib.Path(".skill-actions"),
                    help="where the exact seal request is kept before publishing")
    ap.add_argument("--capsulectl", default="capsulectl")
    args = ap.parse_args(own)
    if not command:
        ap.error("no command after --")

    try:
        inputs = [parse_input(spec) for spec in args.input]
        operator = run(args.capsulectl, "profile", "show", args.profile)["Operator"]
    except EvidenceUnavailable as e:
        print(f"evidence unavailable: {e}", file=sys.stderr)
        return 2

    try:
        proc = subprocess.run(command, capture_output=True)
        code, stdout = proc.returncode, proc.stdout
        sys.stderr.buffer.write(proc.stderr)
    except OSError as e:
        code, stdout = 127, b""
        print(f"skill_action.py: {command[0]}: {e}", file=sys.stderr)
    sys.stdout.buffer.write(stdout)
    sys.stdout.flush()

    try:
        record = skill_action_record(
            args.skill, args.action, inputs=inputs,
            output_digest=hashlib.sha256(stdout).hexdigest(),
            outcome="ok" if code == 0 else "failed", exit_code=code,
            argv_digest=json_digest(command))
        args.work.mkdir(parents=True, exist_ok=True)
        capsule_id = emit_skill_action(args.capsulectl, args.profile, args.work, operator,
                                       args.at, record)
    except (EvidenceUnavailable, OSError) as e:
        print(f"evidence unavailable: {args.skill} {args.action}: {e}", file=sys.stderr)
        return 2
    print(f"skill-action {args.skill} {args.action}: {capsule_id}", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
