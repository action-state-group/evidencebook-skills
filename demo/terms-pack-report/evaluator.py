#!/usr/bin/env python3
"""Runs a Terms Pack over what a holder answered, and writes the Evidence Result v0.

    capsulectl book result derived-inputs --profile NAME --response ID > inputs.json
    python3 evaluator.py --pack pack.json --inputs inputs.json > result.json

The pack is the compiled definition the auditor named by its digest; each clause
carries its own rule, so the terms the holder answered under are the terms this
runs, and a pack whose digest is not the one the holder answered under is refused.
The two rule kinds are this pack's own (a Terms Pack's rule vocabulary is the pack's
to define); scripts/report_spec.py's `forall` reads records of the auditor's own book,
which is not what a derived answer is. Every claim cites exactly the holder's response record (the id
`derived-inputs` prints as `response`), which is what `capsulectl book report
derive` requires. Stdlib only. No model is called.

The rows are what the holder attested: each row's digest was checked in the
holder's log at a signed checkpoint (`proven`), the values are the holder's word,
and no proof shows that no row was left out. So every claim carries claim_for's
default grade, `self-attested`, which tests/test_terms_pack_report.py pins.
"""
import argparse
import datetime
import hashlib
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts"))
from result_v0 import build_result_v0  # noqa: E402


def _path(row, dotted):
    """The value at a dotted path of a row, or (None, False) when a step is missing."""
    value = row.get("fields")
    for name in dotted.split("."):
        if not isinstance(value, dict) or name not in value:
            return None, False
        value = value[name]
    return value, True


def canonical_digest(pack):
    """The SHA-256 a requester names for a Terms Pack: over its canonical JSON (RFC 8785). That is
    json.dumps with sorted keys and no spaces for a document that is ASCII and holds no float, which is
    all this accepts; anything else is refused here rather than hashed to a digest the holder's
    book would not compute."""
    def check(value):
        if isinstance(value, float):
            raise ValueError("the pack holds a float; its canonical form is not computed here")
        if isinstance(value, str) and not value.isascii():
            raise ValueError("the pack holds non-ASCII text; its canonical form is not computed here")
        if isinstance(value, dict):
            for key, member in value.items():
                check(key)
                check(member)
        elif isinstance(value, list):
            for member in value:
                check(member)

    check(pack)
    return hashlib.sha256(json.dumps(pack, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def decide(rule, records):
    """met / not_met / not_evaluable for one clause rule over the answered rows. not_met outranks
    not_evaluable, which outranks met, as everywhere in this repository's rollups. A row that
    names no record type cannot be sorted into the rule's kind of record, a path that is not there
    cannot be read, and neither reads as not_met: the holder's answer does not say."""
    rows, unclassified = [], False
    for r in records:
        fields = r.get("fields")
        kind = fields.get("record_type") if isinstance(fields, dict) else None
        if not isinstance(kind, str):
            unclassified = True
        elif kind == rule["record_type"]:
            rows.append(r)
    if rule["kind"] == "any_record":
        return "met" if rows else "not_evaluable"
    if rule["kind"] == "every_record_empty":
        if not rows:
            return "not_evaluable"
        verdict = "not_evaluable" if unclassified else "met"
        for row in rows:
            for path in rule["paths"]:
                value, present = _path(row, path)
                if not present or not isinstance(value, list):
                    verdict = "not_evaluable" if verdict == "met" else verdict
                elif value:
                    return "not_met"
        return verdict
    raise ValueError(f"unknown rule kind {rule['kind']!r}")


def evaluate(pack, inputs, generated_at):
    missing = [k for k in ("derivation", "response", "records") if k not in inputs]
    if missing:
        raise ValueError(f"inputs carry no {missing}: is this a `book result derived-inputs` document?")
    if not inputs.get("proven"):
        raise ValueError("the holder's answer carries no proofs; this evaluator does not report over unproven inputs")
    if canonical_digest(pack) != inputs["derivation"]:
        raise ValueError("this pack is not the one the holder answered under: its digest is "
                         f"{canonical_digest(pack)}, the answer is for {inputs['derivation']}")
    ids = [c["id"] for c in pack["clauses"]]
    verdicts = {c["id"]: decide(c["rule"], inputs["records"]) for c in pack["clauses"]}
    document, _ = build_result_v0(
        "goose", verdicts, {cid: inputs["response"] for cid in ids}, generated_at, tuple(ids),
        pack["contract_ref"], {cid: "recomputed" for cid in ids})
    document["view"]["title"] = pack["title"]
    return document


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pack", required=True)
    ap.add_argument("--inputs", required=True)
    ap.add_argument("--generated-at", default=None, help="RFC 3339 time; default now (UTC)")
    args = ap.parse_args()
    pack = json.loads(pathlib.Path(args.pack).read_text())
    inputs = json.loads(pathlib.Path(args.inputs).read_text())
    now = args.generated_at or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    json.dump(evaluate(pack, inputs, now), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
