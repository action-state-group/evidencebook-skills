#!/usr/bin/env python3
"""Where the all-required rollup (scripts/rollup.py) meets the book: read every
evaluation-report/v1 capsule scripts/run_daily.py sealed for this --spec's clauses,
group by case, and for every case with every clause, compute the per-check and
all-required verdicts plus a Result v0 document (scripts/result_v0.py) -- the input
`capsulectl result build` takes.

Pack-driven: the check groupings, the full criteria set, each clause's EFFECTIVE
tier (its tier_switch applied) and the never_out_of_scope set all come from
--spec's own clauses[] and switches, never from code here.

Pin-scoped whenever a judge model id is available (--judge-model-id, or
spec["judge"]["model_id"]): a judged report counts only under the CURRENT judge pin
(scripts/judge_pin.py, recomputed here exactly as run_daily.py builds it, which
needs --judge-cmd to report its instruction template), and a recomputed report
only under the current pack_source_digest. A clause reworded but kept at the same
id is therefore never combined with an older judgment of it.

Conflicts are refused, not resolved by order: two reports under one pin for the
same case and clause with different verdicts (a re-judgment that disagrees) put
the case under "cases_conflicting" and keep it out of every rollup. Nothing is
dropped silently: every case left out of a day document is listed with its reason
in that day's "cases_skipped".

This script SEALS NOTHING: it is a read of the book plus a pure computation,
written to --out as plain files.

    python3 scripts/rollup_day.py --profile tau2 --spec demo/tau2-outcomes/compiled.json \\
        --capsulectl CTL --judge-cmd "python3 scripts/judges/jev_judge.py" \\
        --generated-at 2026-09-23T23:59:59Z --out RUN_DIR/rollup

Writes one JSON file per fully-judged case (rollup + the Result v0 document), one
Result v0 per day, and a summary.json whose per-day headline is re-derived from
each day document alone (scripts/result_v0.py:headline_from_result).
"""
import argparse
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from capsulectl_calls import EvidenceUnavailable, list_capsules, payload, run  # noqa: E402
from judge_pin import DEFAULT_JUDGE_TIMEOUT, describe_judge, pin_input  # noqa: E402
from result_v0 import (build_result_v0, build_result_v0_for_day, headline_from_result,  # noqa: E402
                       resolve_contract_ref)
from rollup import (RollupError, all_criteria_from_clauses, all_required_met,  # noqa: E402
                    checks_from_clauses, check_verdicts, never_out_of_scope_from_clauses)
from run_daily import effective_tier  # noqa: E402


def safe_filename(case_id):
    """Same convention as demo/backfill/backfill.py's own safe_name(): case_id is
    built only from fixed literals and dataset fields (run_daily.py:99,
    demo/backfill/backfill.py:74-87) so this isn't a reachable path-traversal
    sink today, but a report body is still book-sourced data, not a trusted
    literal -- never interpolate it into a filesystem path unescaped."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", case_id)


def _in_scope(body, contract, expected_pin, expected_pack):
    """A report counts when it is an evaluation-report/v1 for this contract and,
    when scoping is on, under the current pin (a judged report) or the current
    pack source (a recomputed report, which carries no judge pin)."""
    if not isinstance(body, dict) or body.get("record_type") != "evaluation-report/v1":
        return False
    if body.get("contract") != contract:
        return False
    if "judge_pin_digest" in body:
        return expected_pin is None or body["judge_pin_digest"] == expected_pin
    return expected_pack is None or body.get("pack_source_digest") == expected_pack


def _group(capsule_bodies, contract, expected_pin, expected_pack, conflicts, key):
    """key(body) -> grouping key tuple prefix; returns nested dicts of
    {clause_id: (verdict, capsule_id)}. Two in-scope reports for one slot with the
    same verdict keep the lexicographically first capsule id (deterministic); with
    different verdicts the slot is a conflict: recorded in `conflicts`
    (case_id -> {clause_id: sorted verdicts}) when given, else RollupError."""
    slots = {}
    for capsule_id, body in capsule_bodies:
        if not _in_scope(body, contract, expected_pin, expected_pack):
            continue
        try:
            slot = key(body) + (body["case_id"], body["clause_id"])
            verdict = body["verdict"]
        except (KeyError, TypeError) as e:
            raise RollupError(f"report {capsule_id} is malformed: missing or mistyped {e}")
        slots.setdefault(slot, []).append((verdict, capsule_id))
    grouped = {}
    for slot, entries in slots.items():
        verdicts = sorted({v for v, _ in entries})
        *prefix, case_id, clause_id = slot
        if len(verdicts) > 1:
            if conflicts is None:
                raise RollupError(f"case {case_id!r} clause {clause_id!r} was judged {verdicts!r} under one pin")
            conflicts.setdefault(case_id, {})[clause_id] = verdicts
            continue
        node = grouped
        for part in prefix:
            node = node.setdefault(part, {})
        node.setdefault(case_id, {})[clause_id] = min(entries, key=lambda e: e[1])
    conflicted = set(conflicts or ())
    if conflicted:
        def prune(node, depth):
            if depth == 0:
                for case_id in conflicted:
                    node.pop(case_id, None)
                return
            for child in node.values():
                prune(child, depth - 1)
        prune(grouped, len(key({})))
    return grouped


def _no_key(body):
    return ()


def _period_key(body):
    return (body.get("period"),)


def group_reports(capsule_bodies, contract, expected_pin=None, expected_pack=None, conflicts=None):
    """Pure: case_id -> {clause_id: (verdict, capsule_id)}, over evaluation-report/v1
    bodies FOR THIS CONTRACT ONLY -- `capsule_bodies` is an iterable of
    (capsule_id, body) pairs, already read from the book by collect_reports().

    Scoped by the report's own `contract` field: a book can carry more than one
    compiled contract's reports against the same case_id, and merging their clause
    ids into one rollup would mix two contracts' verdicts under one case.

    `expected_pin`, when given, excludes any judged report whose
    `judge_pin_digest` doesn't match it, and `expected_pack` any recomputed report
    whose `pack_source_digest` doesn't: a pack recompiled with a criterion's
    wording changed but its id kept would otherwise let an older judgment share
    the current one's slot. A disagreeing re-judgment under one pin is a conflict
    (see _group), never last-writer-wins."""
    return _group(capsule_bodies, contract, expected_pin, expected_pack, conflicts, _no_key)


def collect_reports(capsulectl, profile, contract, expected_pin=None, expected_pack=None, conflicts=None):
    """case_id -> {clause_id: (verdict, capsule_id)}, over every evaluation-report/v1
    capsule the profile's book carries for this contract -- not scoped to one day: a
    case's clauses may have been judged and sealed across more than one run."""
    bodies = [(e["capsule_id"], payload(capsulectl, profile, e["capsule_id"]))
              for e in list_capsules(capsulectl, profile)]
    return group_reports(bodies, contract, expected_pin, expected_pack, conflicts), bodies


def resolve_expected_pin(capsulectl, spec, judge_model_id, judge_cmd, root, work, timeout=DEFAULT_JUDGE_TIMEOUT):
    """The current compiled spec's judge_pin_digest, built exactly as
    scripts/run_daily.py builds it (scripts/judge_pin.py) -- or None when no model
    id is available (a hand-authored contract predating judge.model_id), in which
    case the rollup runs unscoped by pin. Needs the judge command, which reports
    the instruction template it sends."""
    if not judge_model_id:
        return None
    if not judge_cmd:
        raise EvidenceUnavailable("--judge-cmd is required to recompute the judge pin "
                                  "(the pin covers the instruction template the judge reports)")
    pin_path = work / "judge-pin.json"
    pin_path.write_text(json.dumps(pin_input(spec, root, judge_model_id, describe_judge(judge_cmd, timeout))))
    return run(capsulectl, "judge", "pin", str(pin_path))["judge_pin_digest"]


def group_reports_by_day(capsule_bodies, contract, expected_pin=None, expected_pack=None, conflicts=None):
    """period ('day:YYYY-MM-DD', run_daily.py's own value) -> case_id ->
    {clause_id: (verdict, capsule_id)}, same contract, pin and conflict rules as
    group_reports(). The report records are the only source for which cases share
    a day: each carries the `period` it was sealed under."""
    return _group(capsule_bodies, contract, expected_pin, expected_pack, conflicts, _period_key)


def clause_tiers(spec):
    """clause_id -> EFFECTIVE tier, from the compiled contract: a clause's
    tier_switch applies when its flag is on (run_daily.effective_tier, the same
    function that decided whether the clause was judged or recomputed), so a claim
    never says "judged" for a clause whose report was recomputed."""
    switches = spec.get("switches") or {}
    return {clause["id"]: effective_tier(clause, switches) for clause in spec["clauses"]}


def partition_stale(clause_verdicts, all_criteria):
    """Split a case's {clause_id: (verdict, capsule_id)} into (current, stale).
    `stale` is every clause id the current contract no longer defines --
    necessarily left over from an earlier compiled version of this same
    contract id (a pack recompiled with a criterion removed or renamed,
    scripts/pack_compile.py's `contract` id stays stable across a
    pack_version/rubric_version bump by design). Dropped from the rollup here,
    never silently merged into it, and never a reason to refuse the case
    forever either -- the caller records what was dropped rather than hiding
    it or raising "unrecognized criteria" on every future run."""
    stale = sorted(c for c in clause_verdicts if c not in all_criteria)
    current = {c: v for c, v in clause_verdicts.items() if c in all_criteria}
    return current, stale


def rollup_case(case_id, clause_verdicts, generated_at, checks, all_criteria, contract_ref, tiers,
                allow_out_of_scope=False, never_out_of_scope=frozenset()):
    verdicts = {cid: v for cid, (v, _) in clause_verdicts.items()}
    digests = {cid: cap_id for cid, (_, cap_id) in clause_verdicts.items()}
    check_results = check_verdicts(verdicts, checks, allow_out_of_scope)
    resolved = all_required_met(verdicts, all_criteria, allow_out_of_scope, never_out_of_scope)
    result_v0, resolved_again = build_result_v0(case_id, verdicts, digests, generated_at, all_criteria, contract_ref,
                                                 tiers, allow_out_of_scope, never_out_of_scope)
    assert resolved == resolved_again  # same rollup, computed twice on purpose: must agree
    return {
        "case_id": case_id,
        "criterion_verdicts": verdicts,
        "check_verdicts": check_results,
        "resolved": resolved,
        "result_v0": result_v0,
    }


def day_document(period, day_cases, generated_at, all_criteria, contract_ref, tiers,
                 allow_out_of_scope=False, never_out_of_scope=frozenset()):
    """Pure: one day's Result v0 over every case that can be rolled up, plus the
    list of cases left out and why -- nothing is dropped silently. Returns
    (document or None, skipped)."""
    case_rollups, skipped = [], []
    for case_id, clause_verdicts in sorted(day_cases.items()):
        current, stale = partition_stale(clause_verdicts, all_criteria)
        missing = [c for c in all_criteria if c not in current]
        if missing:
            skipped.append({"case_id": case_id, "reason": "incomplete on this day", "missing": missing})
            continue
        verdicts = {cid: v for cid, (v, _) in current.items()}
        digests = {cid: cap_id for cid, (_, cap_id) in current.items()}
        try:
            build_result_v0_for_day(period, [(case_id, verdicts, digests, tiers)], generated_at, all_criteria,
                                    contract_ref, allow_out_of_scope, never_out_of_scope)
        except RollupError as e:
            skipped.append({"case_id": case_id, "reason": str(e)})
            continue
        case_rollups.append((case_id, verdicts, digests, tiers))
    if not case_rollups:
        return None, skipped
    return build_result_v0_for_day(period, case_rollups, generated_at, all_criteria, contract_ref,
                                   allow_out_of_scope, never_out_of_scope), skipped


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--spec", required=True, type=pathlib.Path,
                     help="the compiled contract (e.g. demo/tau2-outcomes/compiled.json) -- its "
                          "spec['contract'] id scopes which reports this rollup combines, and its "
                          "clauses[] define the check groupings and full criteria set")
    ap.add_argument("--capsulectl", default="capsulectl")
    ap.add_argument("--generated-at", required=True, help="RFC3339 timestamp for the Result v0 documents (never fabricated wall-clock; caller supplies it)")
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("--judge-cmd", default=None,
                    help="the judge command run_daily.py used; asked to describe its instruction template so "
                         "the judge pin can be recomputed (required whenever a judge model id is available)")
    ap.add_argument("--judge-timeout", type=int, default=DEFAULT_JUDGE_TIMEOUT)
    ap.add_argument("--judge-model-id", default=None,
                     help="the pinned judge's model id, as given to run_daily.py --judge-model-id. "
                          "Defaults to spec['judge']['model_id'] when present (every "
                          "scripts/pack_compile.py-compiled contract carries one). When neither is "
                          "available, the rollup is not pin-scoped: reports are combined by contract "
                          "and clause id alone, as before this flag existed.")
    args = ap.parse_args(argv)

    spec = json.loads(args.spec.read_text())
    root = args.spec.resolve().parents[2]
    contract = spec["contract"]
    contract_ref = resolve_contract_ref(spec)
    checks = checks_from_clauses(spec["clauses"])
    all_criteria = all_criteria_from_clauses(spec["clauses"])
    tiers = clause_tiers(spec)
    never_oos = never_out_of_scope_from_clauses(spec["clauses"])
    allow_out_of_scope = bool((spec.get("switches") or {}).get("out_of_scope_verdict"))
    args.out.mkdir(parents=True, exist_ok=True)
    work = args.out / "work"
    work.mkdir(parents=True, exist_ok=True)

    judge_model_id = args.judge_model_id or spec["judge"].get("model_id")
    expected_pack = spec.get("pack_source_digest")
    conflicts = {}
    try:
        expected_pin = resolve_expected_pin(args.capsulectl, spec, judge_model_id, args.judge_cmd, root, work,
                                            args.judge_timeout)
        by_case, bodies = collect_reports(args.capsulectl, args.profile, contract, expected_pin, expected_pack,
                                          conflicts)
        by_day = group_reports_by_day(bodies, contract, expected_pin, expected_pack, conflicts)
    except (EvidenceUnavailable, RollupError) as e:
        print(json.dumps({"evidence_unavailable": str(e)}, indent=2))
        return 2

    complete, incomplete = [], []
    for case_id, clause_verdicts in sorted(by_case.items()):
        current, stale = partition_stale(clause_verdicts, all_criteria)
        missing = [c for c in all_criteria if c not in current]
        if missing:
            entry = {"case_id": case_id, "missing": missing, "have": sorted(current)}
            if stale:
                entry["stale_criteria_ignored"] = stale
            incomplete.append(entry)
            continue
        try:
            case_rollup = rollup_case(case_id, current, args.generated_at, checks, all_criteria, contract_ref, tiers,
                                      allow_out_of_scope, never_oos)
        except RollupError as e:
            incomplete.append({"case_id": case_id, "error": str(e)})
            continue
        if stale:
            case_rollup["stale_criteria_ignored"] = stale
        (args.out / f"{safe_filename(case_id)}.json").write_text(json.dumps(case_rollup, indent=2))
        complete.append({"case_id": case_id, "resolved": case_rollup["resolved"]})

    # One Result v0 per day/period, over every case that day that rolls up, beside
    # the per-case documents above. Built from the same sealed reports and tiers.
    day_results = []
    for period, day_cases in sorted(by_day.items(), key=lambda kv: (kv[0] is None, kv[0])):
        day_doc, skipped = day_document(period, day_cases, args.generated_at, all_criteria, contract_ref, tiers,
                                        allow_out_of_scope, never_oos)
        entry = {"period": period, "cases_skipped": skipped}
        if day_doc is not None:
            day_label = period.split(":", 1)[1] if period and ":" in period else (period or "unknown-period")
            out_path = args.out / f"result-v0-{safe_filename(day_label)}.json"
            out_path.write_text(json.dumps(day_doc, indent=2))
            entry.update(cases=headline_from_result(day_doc)["cases"], claims=len(day_doc["claims"]),
                         headline=headline_from_result(day_doc), out=str(out_path))
        day_results.append(entry)

    summary = {
        "cases_judged": len(by_case),
        "cases_resolved": sum(1 for c in complete if c["resolved"]),
        "cases_complete": len(complete),
        "cases_incomplete": incomplete,
        "cases_conflicting": [{"case_id": c, "clauses": v} for c, v in sorted(conflicts.items())],
        "day_results": day_results,
        "judge_pin_digest": expected_pin,
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
