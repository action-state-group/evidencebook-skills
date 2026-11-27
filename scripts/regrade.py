"""A person's re-grade of one judged row, sealed beside it: the `regrade` record.

The custody and record-kind profile v0 (evidencebook#116 design note, section 3)
reserves two names with this repository as producer: `judge_report` and `regrade`.
Steven's ruling Q3 (ops DECISION u647, 2026-11-26): "re-grade sits beside the judged
row, never replaces".

- `judge_report` is the clause report daily-judge-and-close already seals
  (`clause-report/v1`, and `evaluation-report/v1` before 2026-11-03, read by shape:
  scripts/clause_report.py). One record is one judged row: a case, a clause, the
  judge's verdict and rationale, and the judge pin (`judge_pin`, `judge_pin_digest`).
  The profile's rule keeps a name present in only one implementation, so no
  second name is coined and nothing is renamed. docs/judge-report-and-regrade.md
  lists the members.
- `regrade` is new. It cites the one judged row it grades by that row's capsule id
  and carries the person's grade and reason. It never supersedes the row: no reader
  changes the row's verdict, no Result v0 count reads a regrade, and calibration,
  which compares the judge with blind ratings, does not read one (a regrade is not
  blind). A row may have several regrades; each stays.

    python3 scripts/regrade.py seal --profile NAME --row CAPSULE_ID --grade not_met \\
        --reason TEXT --rater-ref REF --at 2026-11-27T00:00:00Z [--spec COMPILED.json] [--reason-sealed-ok]
    python3 scripts/regrade.py rows --profile NAME

`seal` first tells the rater that the reason is sealed for good and asks them to
confirm (`--reason-sealed-ok` when they already have). It then authenticates the
row (`get --raw`, then `verify`) before sealing, and `--at` fixes the capsule's
timestamp, so the same regrade sealed again is the same capsule.
`rows` prints every judged row that has a regrade, with the judge's grade and each
person's grade beside it, as JSON; it authenticates each regrade and its row first,
and lists any regrade it does not show, with why.
"""
import argparse
import json
import re
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from capsulectl_calls import (CapsuleDoesNotVerify, EvidenceUnavailable, UntrustedSigner,  # noqa: E402
                              list_capsules, payload, publish, run, seal_request, verify)
from clause_report import is_clause_report  # noqa: E402

REGRADE = "regrade"
URN = "urn:evidencebook-skills:regrade"
DEVELOPER = "evidencebook-skills/regrade"
GRADES = ("met", "not_met", "not_evaluable")
# Told to the rater before anything is sealed (Sherlock2's door confirmation for
# evidencebook#116 PR 9): the reason is a person's own words, and they stay for good.
REASON_NOTICE = ("Your reason is sealed with this regrade. Once sealed it cannot be edited or removed, "
                 "and it travels with the judged row.")
OUT_OF_SCOPE = "out_of_scope"
_HEX64 = re.compile(r"[0-9a-f]{64}")


class RegradeRefused(ValueError):
    """The regrade cannot be sealed as asked: the row is not a judged row, or a
    member is missing or out of range. Nothing was sealed."""


def is_judged_row(body):
    """Whether `body` is a judged row a person may re-grade: a clause report whose
    verdict a judge reached, naming the judge pin it was judged under, with the
    case, clause and verdict a reader shows. A recomputed determination was never
    judged, so it has no judge to re-grade; a malformed report is no row."""
    return (is_clause_report(body) and body.get("epistemic_type", "semantic_judgment") == "semantic_judgment"
            and isinstance(body.get("judge_pin_digest"), str) and bool(_HEX64.fullmatch(body["judge_pin_digest"]))
            and all(isinstance(body.get(k), str) and body[k].strip() for k in ("case_id", "clause_id"))
            and body.get("verdict") in GRADES + (OUT_OF_SCOPE,))


def is_regrade(body):
    return isinstance(body, dict) and body.get("record_type") == REGRADE


def _text(name, value):
    if not isinstance(value, str) or not value.strip():
        raise RegradeRefused(f"{name} must be a non-empty string")
    return value


def out_of_scope_allowed(row, spec):
    """Whether the contract the row was judged under let its judge answer
    `out_of_scope` for the row's clause: the compiled spec's switch
    `out_of_scope_verdict` is on and the clause is not `never_out_of_scope`
    (scripts/run_daily.py valid_verdicts). The row does not carry either, so the
    spec must be the one it was judged under: the row's `contract_ref`, and its
    `pack_source_digest` when it has one, must equal the spec's. A row that names
    no contract_ref cannot show which contract it was judged under, so it is
    refused here."""
    if spec is None:
        return False
    if not row.get("contract_ref") or row.get("contract_ref") != spec.get("contract_ref"):
        return False
    if "pack_source_digest" in row and row["pack_source_digest"] != spec.get("pack_source_digest"):
        return False
    clause = next((c for c in spec.get("clauses") or () if c.get("id") == row.get("clause_id")), None)
    if clause is None or clause.get("never_out_of_scope"):
        return False
    return bool((spec.get("switches") or {}).get("out_of_scope_verdict"))


def regrade_record(row_capsule_id, row, grade, reason, rater_ref, regraded_at, spec=None):
    """The `regrade` body for one judged row -- pure, no I/O. `row` is the judged
    row's sealed payload; its capsule id is `row_capsule_id`. `spec` is the
    compiled contract the row was judged under, needed only for `out_of_scope`."""
    if is_regrade(row):
        raise RegradeRefused("a regrade grades a judged row, not another regrade")
    if not is_judged_row(row):
        raise RegradeRefused("the row is not a judged clause report (a recomputed determination has no judge to re-grade)")
    if grade == OUT_OF_SCOPE:
        if not out_of_scope_allowed(row, spec):
            raise RegradeRefused("out_of_scope needs --spec, the compiled contract the row was judged under "
                                 "(same contract_ref and pack_source_digest), with the switch out_of_scope_verdict on "
                                 "and the clause not never_out_of_scope")
    elif grade not in GRADES:
        raise RegradeRefused(f"grade must be one of {', '.join(GRADES + (OUT_OF_SCOPE,))}, got {grade!r}")
    rater_ref = _text("rater_ref", rater_ref)
    if rater_ref != rater_ref.strip():
        raise RegradeRefused("rater_ref must have no surrounding spaces")
    return {
        "record_type": REGRADE,
        "epistemic_type": "human_report",
        "regraded_at": _text("regraded_at", regraded_at),
        "rater_ref": rater_ref,
        "row": {"type": row["record_type"], "digest_alg": "SHA-256", "digest": _text("row capsule id", row_capsule_id),
                "citation_purpose": "regraded_row"},
        "case_id": _text("the row's case_id", row.get("case_id")),
        "clause_id": _text("the row's clause_id", row.get("clause_id")),
        "grade": grade,
        "reason": _text("reason", reason),
    }


def _well_formed(body):
    """Whether a `regrade` body has the members a reader relies on, each of the right kind."""
    row = body.get("row")
    return (isinstance(row, dict) and row.get("citation_purpose") == "regraded_row"
            and row.get("digest_alg") == "SHA-256" and isinstance(row.get("digest"), str)
            and body.get("epistemic_type") == "human_report"
            and body.get("grade") in GRADES + (OUT_OF_SCOPE,)
            and all(isinstance(body.get(k), str) and body[k].strip()
                    for k in ("reason", "rater_ref", "regraded_at", "case_id", "clause_id")))


def rows_with_regrades(entries, check):
    """Pair each judged row with the regrades that cite it. `entries` is
    [(capsule_id, payload)] in log order; `check(capsule_id)` authenticates one
    capsule and raises CapsuleDoesNotVerify or UntrustedSigner when it does not.
    Any other EvidenceUnavailable (a verifier that gave no verdict) propagates: the
    read stops, rather than reporting a record as unverified. Returns one item per regraded row: the row's own verdict as
    the judge sealed it, and every regrade of it in log order, each authenticated
    with its row before it is placed beside it. A regrade never changes `judge`.

    A regrade is left out of `rows` and listed under `not_shown`, with why, when
    it is malformed, cites no judged row in `entries`, names a case or clause or
    row type its row does not have, or when it or its row does not verify."""
    rows = {cid: body for cid, body in entries if is_judged_row(body)}
    beside, not_shown, checked = {}, [], {}

    def ok(cid):
        if cid not in checked:
            try:
                check(cid)
                checked[cid] = None
            except (CapsuleDoesNotVerify, UntrustedSigner) as e:
                checked[cid] = str(e)
        return checked[cid]

    for cid, body in entries:
        if not is_regrade(body):
            continue
        if not _well_formed(body):
            not_shown.append({"capsule_id": cid, "why": "malformed regrade"})
            continue
        digest = body["row"]["digest"]
        row = rows.get(digest)
        if row is None:
            not_shown.append({"capsule_id": cid, "why": "cites no judged row in this book"})
            continue
        if (row["case_id"], row["clause_id"], row["record_type"]) != (body["case_id"], body["clause_id"],
                                                                      body["row"].get("type")):
            not_shown.append({"capsule_id": cid, "why": "case, clause or row type differs from its row"})
            continue
        failed = ok(cid) or ok(digest)
        if failed:
            not_shown.append({"capsule_id": cid, "why": f"does not verify: {failed}"})
            continue
        beside.setdefault(digest, []).append({
            "capsule_id": cid, "grade": body["grade"], "reason": body["reason"],
            "rater_ref": body["rater_ref"], "regraded_at": body["regraded_at"]})
    out = []
    for digest, regrades in beside.items():
        row = rows[digest]
        out.append({"row": digest, "case_id": row["case_id"], "clause_id": row["clause_id"],
                    "period": row.get("period"),
                    "judge": {"verdict": row.get("verdict"), "judge_pin_digest": row.get("judge_pin_digest")},
                    "regrades": regrades})
    return {"rows": out, "not_shown": not_shown}


def told(reason, stdin=None, stderr=None):
    """Tell the rater, before anything is sealed, that the reason is sealed for
    good, and ask them to confirm. Only a terminal can answer: with no terminal
    the answer is no, so an unattended run must pass --reason-sealed-ok."""
    stdin, stderr = stdin or sys.stdin, stderr or sys.stderr
    print(REASON_NOTICE, file=stderr)
    print(f"Reason: {reason}", file=stderr)
    if not stdin.isatty():
        return False
    print("Seal it? [y/N] ", end="", file=stderr, flush=True)
    return stdin.readline().strip().lower() in ("y", "yes")


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="verb", required=True)
    s = sub.add_parser("seal", help="seal one regrade of a judged row")
    s.add_argument("--profile", required=True)
    s.add_argument("--row", required=True, help="the judged row's capsule id")
    s.add_argument("--grade", required=True, help="met, not_met or not_evaluable; out_of_scope only with --spec")
    s.add_argument("--reason", required=True)
    s.add_argument("--rater-ref", required=True, help="an opaque principal reference, never a name")
    s.add_argument("--at", required=True, help="the regrade's time, fixed into the capsule (RFC 3339, UTC)")
    s.add_argument("--spec", type=pathlib.Path,
                   help="the compiled contract the row was judged under; needed only for the grade out_of_scope")
    s.add_argument("--reason-sealed-ok", action="store_true",
                   help="the rater has been told that the reason is sealed, cannot be edited and travels with the row; "
                        "without it, seal asks on a terminal and refuses otherwise")
    s.add_argument("--capsulectl", default="capsulectl")
    r = sub.add_parser("rows", help="print each regraded row with the judge's grade and the regrades beside it")
    r.add_argument("--profile", required=True)
    r.add_argument("--capsulectl", default="capsulectl")
    args = ap.parse_args(argv)
    ctl, profile = args.capsulectl, args.profile
    try:
        if args.verb == "rows":
            entries = [(e["capsule_id"], payload(ctl, profile, e["capsule_id"])) for e in list_capsules(ctl, profile)]
            with tempfile.TemporaryDirectory() as work:
                shown = rows_with_regrades(entries, lambda cid: verify(ctl, profile, cid, work))
            print(json.dumps(shown, indent=2, sort_keys=True))
            return 0
        if not args.reason_sealed_ok and not told(args.reason):
            print("regrade not sealed: the rater did not confirm that the reason is sealed "
                  "(answer y, or pass --reason-sealed-ok)", file=sys.stderr)
            return 2
        with tempfile.TemporaryDirectory() as work:
            verify(ctl, profile, args.row, work)
            row = payload(ctl, profile, args.row)
            spec = json.loads(args.spec.read_text()) if args.spec else None
            body = regrade_record(args.row, row, args.grade, args.reason, args.rater_ref, args.at, spec=spec)
            operator = run(ctl, "profile", "show", profile)["Operator"]
            action_id = f"{URN}:{body['case_id']}:{body['clause_id']}:{args.row}:{args.rater_ref}"
            capsule_id = publish(ctl, profile, seal_request(action_id, operator, DEVELOPER, args.at, body),
                                 work, "regrade")
    except RegradeRefused as e:
        print(f"regrade refused: {e}", file=sys.stderr)
        return 2
    except EvidenceUnavailable as e:
        print(f"evidence unavailable: {e}", file=sys.stderr)
        return 1
    print(json.dumps({"capsule_id": capsule_id, "row": args.row, "grade": body["grade"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
