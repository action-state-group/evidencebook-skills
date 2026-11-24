# SPDX-License-Identifier: Apache-2.0
"""A report over a range of ended windows, with its coverage check, on released capsulectl.

    uv run python range_report.py WORK_DIR [--without-deal-answers]

The airline's windowed deal store is `deal init --window month`; a report over a range of
windows asks the holder (the airline) one answer per window and one per deal placed in it, then
checks the range is covered. capsulectl has no external clock, so a store made in real time has
only its open window. This runs on the committed fixture (range/fixture, from evidencebook#853:
two ended months, one deal placed in each), on a copy, with the released binaries only:

  deal window chain          the chain of the ended windows, each placed deal proved to extend
                             its tree at the window's close
  book request, deal window respond, book request --response
                             one answer per window and per placed deal, each pinned to the
                             digest of that window's final checkpoint or the deal's latest one
  book report derive --chain the requester's report bundle over the windows
  book report coverage       names each placed deal, or each window or deal with no answer

The recipe is evidencebook's capsulectl/cmd/window_store_cli_test.go at the commit range/fixture
cites. The Evidence Result derive signs is written here (one claim, "has-records"), as that test
does: the demo runs no evaluator on it.

Needs capsulectl with the deal and book plugins on PATH (or CAPSULECTL_PLUGIN_ROOTS).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "range" / "fixture"

# The Terms Pack the answers are derived under: one row, "has-record". Its identifier is the
# SHA-256 of the JCS of its document; for this document (strings and one integer) JCS is the
# JSON with keys sorted and no spaces.
PACK_DOCUMENT = {"pack": "window-store-pack", "version": 1, "rows": ["has-record"]}
PACK_DIGEST = hashlib.sha256(
    json.dumps(PACK_DOCUMENT, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()


class CapsulectlError(RuntimeError):
    """A capsulectl command failed; `output` is its stdout and stderr."""

    def __init__(self, args: list[str], output: str):
        super().__init__(f"capsulectl {' '.join(args)}: {output.strip()}")
        self.output = output


class Capsulectl:
    def __init__(self, config: Path):
        self.env = dict(os.environ, XDG_CONFIG_HOME=str(config))

    def run(self, *args: str) -> str:
        done = subprocess.run(["capsulectl", *args], env=self.env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if done.returncode != 0:
            raise CapsulectlError(list(args), done.stdout + done.stderr)
        return done.stdout

    def json(self, *args: str) -> dict:
        return json.loads(self.run(*args))


def trusted_keys(profile: str) -> tuple[str, str]:
    """The holder's record key and checkpoint key: the first trusted key of each in deal.yaml."""
    keys = re.findall(r"^\s*trusted_keys:\n\s*-\s*([0-9a-f]{64})", profile, re.M)
    if len(keys) != 2:
        raise ValueError("deal.yaml: expected a record key and a checkpoint key")
    return keys[0], keys[1]


def prepare(work: Path) -> tuple[Capsulectl, str, str]:
    """Copy the fixture store (chain and respond write to it), write the holder's profile with
    the store's path, and make the requester's own book (`req`) with fresh keys."""
    config = work / "config"
    profiles = config / "capsule" / "profiles"
    profiles.mkdir(parents=True)
    store = work / "store"
    shutil.copytree(FIXTURE / "store", store)
    for f in store.iterdir():
        f.chmod(0o600)  # a checkout does not keep the owner-only mode capsulectl requires of seeds
    template = (FIXTURE / "deal.yaml").read_text()
    deal_profile = profiles / "deal.yaml"
    deal_profile.write_text(template.replace("@STORE@", str(store)))
    deal_profile.chmod(0o600)  # capsulectl refuses a profile others can read
    holder_key, checkpoint_key = trusted_keys(template)

    cli = Capsulectl(config)
    public = {}
    for name in ("record", "checkpoint"):
        public[name] = cli.json("key", "generate", "--output", str(work / f"{name}.seed"))["public_key"]
    req_profile = profiles / "req.yaml"
    req_profile.write_text(
        f"name: req\ntype: jsonl\nlog_id: req\nlog: book\nnamespace: capsule\noperator: req-operator\n"
        f"connection:\n    database: {work / 'req'}\n"
        f"signing:\n    file: {work / 'record.seed'}\ntrusted_keys:\n    - {public['record']}\n"
        f"checkpoint:\n    signing:\n        file: {work / 'checkpoint.seed'}\n"
        f"    trusted_keys:\n        - {public['checkpoint']}\n"
    )
    req_profile.chmod(0o600)
    cli.run("--profile", "req", "store", "init")
    return cli, holder_key, checkpoint_key


def result_for(evidence_ids: list[str]) -> dict:
    """The requester's Evidence Result: one claim whose evidence is the answers' records."""
    evidence = [{"digest": i, "digest_alg": "SHA-256"} for i in evidence_ids]
    claim = {
        "id": "has-records", "contract_ref": "ec:window-store-pack@1", "requirement_ref": "has-record",
        "tier": "recomputed", "grade": "self-attested", "sufficiency": "SATISFIED", "verdict": "met",
        "evidence": evidence, "proofs": [],
        "presentation": {"kind": "disclosure", "status": "SATISFIED", "evidence": evidence},
    }
    return {
        "result_version": "evidence-result-v0", "generated_at": "2026-11-24T00:00:00Z", "claims": [claim],
        "aggregate": {
            "buckets": {"met": ["has-records"], "not_met": [], "not_evaluable": []},
            "coverage": {"evaluated_population": 1, "excluded_not_applicable": 0, "unknown_count": 0},
        },
    }


def range_report(work: Path, *, answer_deals: bool = True) -> dict:
    """Run the chain, the answers, the derive and the coverage check on the fixture store.

    Returns the chain, the answers' record ids by name, the bundle path (None when derive
    refused) with derive's refusal text, and `book report coverage`'s output (None without a bundle).
    """
    work.mkdir(parents=True, exist_ok=True)
    cli, holder_key, checkpoint_key = prepare(work)
    chain_file = work / "chain.json"
    cli.run("--profile", "deal", "deal", "window", "chain", "--from", "2026-09", "--to", "2026-10", "--out", str(chain_file))
    chain = json.loads(chain_file.read_text())

    # One pin per window and per placed deal: the window's final checkpoint, the deal's latest.
    pins: list[tuple[str, bytes]] = []
    for w in chain["windows"]:
        pins.append((f"window-{w['label']}", base64.b64decode(w["final_checkpoint"])))
        for d in w.get("deals") or []:
            pins.append((f"deal-{w['label']}", base64.b64decode(d["latest"])))

    pack = work / "pack.json"
    pack.write_text(json.dumps({"document": PACK_DOCUMENT, "recipients": ["req"], "forms": ["full_history"],
                                "fields": ["record_type", "committed_at"]}))
    answers: dict[str, str] = {}
    for name, pin in pins:
        request = work / f"{name}.json"
        request.write_text(json.dumps({"subject": {"full_history": None},
                                       "coverage": {"expected_pin": hashlib.sha256(pin).hexdigest()},
                                       "derivation": PACK_DIGEST}))
        sent = cli.json("book", "request", "--profile", "req", "--request", str(request), "--responder", "deal",
                        "--output", str(work / f"{name}.sent"))
        cli.run("--profile", "deal", "deal", "window", "respond", "--request", str(work / f"{name}.sent"),
                "--requester", "req", "--output", str(work / f"{name}.reply"), "--pack", str(pack))
        recorded = cli.json("book", "request", "--profile", "req", "--for", sent["record_id"],
                            "--response", str(work / f"{name}.reply"), "--responder-key", holder_key,
                            "--responder-checkpoint-key", checkpoint_key)
        answers[name] = recorded["record_id"]

    sent_answers = [n for n in answers if answer_deals or n.startswith("window-")]
    bundle = work / "bundle.json"
    derive = ["book", "report", "derive", "--profile", "req", "--chain", str(chain_file), "--pack", PACK_DIGEST,
              "--out", str(bundle)]
    for n in sent_answers:
        derive += ["--response", answers[n]]
    result = work / "result.json"
    result.write_text(json.dumps(result_for([answers[n] for n in sent_answers])))
    out = {"chain": chain, "answers": answers, "bundle": None, "derive_refusal": None, "coverage": None}
    try:
        cli.run(*derive, "--result", str(result))
    except CapsulectlError as err:
        out["derive_refusal"] = err.output
        return out
    out["bundle"] = bundle
    out["coverage"] = cli.json("book", "report", "coverage", "--bundle", str(bundle),
                               "--holder-checkpoint-key", checkpoint_key)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("work", type=Path, help="an empty or new directory for the copy of the store and the bundle")
    ap.add_argument("--without-deal-answers", action="store_true",
                    help="answer the windows only: derive names each placed deal with no answer and writes nothing")
    args = ap.parse_args()
    if args.work.exists() and any(args.work.iterdir()):
        sys.exit(f"{args.work} is not empty")
    out = range_report(args.work.resolve(), answer_deals=not args.without_deal_answers)
    print(f"chain: {len(out['chain']['windows'])} windows, {out['chain']['from']} to {out['chain']['to']}")
    if out["bundle"] is None:
        print("derive refused (no bundle written):", out["derive_refusal"].strip().splitlines()[-1])
        sys.exit(1)
    cov = out["coverage"]
    print("covered:", cov["covered"])
    for line in cov["deals"]:
        print("  ", line)
    print("bundle:", out["bundle"])


if __name__ == "__main__":
    main()
