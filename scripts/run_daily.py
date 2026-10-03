#!/usr/bin/env python3
"""Exercise script for skills/daily-judge-and-close: run one day, end to end.

It performs the skill's steps in order and calls only the verbs the skill lists:
judge pin, cll list, get, verify, publish, close. The judge is an external command
(--judge-cmd) that reads one case on stdin and prints {"verdict", "rationale"};
for every judged-tier clause this script never decides a verdict itself -- the one
exception, a clause whose effective tier is "recomputed", is its own paragraph
below. Any consequential step that produces no record stops the run with
`evidence unavailable` before the next one.

The request also carries `judge_model_id` (--judge-model-id, verbatim) so a judge
command that talks to a real, named model can refuse rather than silently seal a
judge_pin_digest (see step 1 below) that misstates which model actually judged --
--judge-model-id is operator-supplied free text, cross-checked against nothing
else in this script, so a judge that pins its own model internally (e.g. a fixed
API model string) is the only thing that can catch a mismatch.

    run_daily.py --profile tau2 --spec demo/tau2/compiled.json \\
        --judge-cmd "python3 tests/stub_judge.py" --judge-model-id stub-judge/0 \\
        --date 2026-09-16 --out RUN_DIR

Re-running a day seals nothing new: every report is published with a timestamp fixed
to the day, so the same judgment is the same capsule, and `close` returns the day's
existing Close.

Rubric switches: a compiled contract may carry a top-level "switches" dict and,
per clause, a "tier_switch" ({"flag", "tier_when_on"}) and/or "claim_switch"
({"flag", "claim_when_on"}). Every switch defaults off when the contract or the
clause doesn't mention it, which is exactly today's behaviour -- a contract that
predates switches (demo/tau2/compiled.json) is untouched. See effective_tier()/
effective_claim() below and demo/tau2-outcomes/compiled.json's own "switches" block
for what each one does.

A clause whose effective tier is "recomputed" never reaches the judge command at
all: scripts/recompute.py's registered checker runs in-process instead (see
recomputed_answer()). A contract may additionally set a top-level "judge_batch": true
to have every judged clause of one case go through the judge command in a single
call (judge_batch() below) instead of one call per clause -- a cost fix (the policy
text was being sent once per criterion, nine times per conversation). A contract that
doesn't set judge_batch keeps calling judge() once per clause, unchanged.

The judge pin (scripts/judge_pin.py) covers the model id, the compiled prompt and
axes, the sampling params, the pack source's digest and the instruction template the
judge command reports sending; a clause marked never_not_applicable is never offered
not_applicable. Every judge-cmd call runs under --judge-timeout, and an unparseable
or incomplete answer stops the run with `evidence unavailable`, never a crash.
"""

import argparse
import datetime
import json
import pathlib
import shlex
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from capsulectl_calls import (EvidenceUnavailable, committed_on, list_capsules, payload,  # noqa: E402
                              publish, run, seal_request, verify)
from judge_pin import DEFAULT_JUDGE_TIMEOUT, describe_judge, pin_input as build_pin_input  # noqa: E402
from recompute import RECOMPUTE_CHECKS  # noqa: E402

VERDICTS = {"met", "not_met", "not_evaluable"}
VERDICTS_WITH_NA = VERDICTS | {"not_applicable"}


def checked_answer(answer, valid_verdicts=VERDICTS):
    """The judge's (or checker's) answer, refused unless it carries one of the
    allowed verdicts -- VERDICTS, or VERDICTS_WITH_NA when the contract's
    not_applicable_verdict switch is on for this clause."""
    if not isinstance(answer, dict) or answer.get("verdict") not in valid_verdicts:
        raise EvidenceUnavailable(f"judge returned no valid verdict: {answer!r}")
    return answer


def effective_tier(clause, switches):
    """clause["tier"], unless the clause names a tier_switch and that flag is on in
    the contract's "switches" -- e.g. within_fare_rules_recomputed flips
    policy_compliance.within_fare_rules from judged to recomputed. Missing from
    `switches` reads as off, so a contract or clause that never mentions a
    tier_switch behaves exactly as before."""
    tier_switch = clause.get("tier_switch")
    if tier_switch and switches.get(tier_switch["flag"]):
        return tier_switch["tier_when_on"]
    return clause["tier"]


def effective_claim(clause, switches):
    """clause["claim"], unless the clause names a claim_switch and that flag is on --
    e.g. done_in_full_refusal_aware swaps in wording that counts a policy-correct
    refusal as done in full. Same off-by-default rule as effective_tier()."""
    claim_switch = clause.get("claim_switch")
    if claim_switch and switches.get(claim_switch["flag"]):
        return claim_switch["claim_when_on"]
    return clause["claim"]


def _judge_request(case_payload, spec_root, judge_model_id, allow_not_applicable, min_confidence=None):
    request = {"case": case_payload["case"], "agent_interaction": case_payload["agent_interaction"],
               "policy": str(spec_root / "airline-data" / "policy.md"),
               "booking_db": str(spec_root / "airline-data" / "db.json"),
               "judge_model_id": judge_model_id, "allow_not_applicable": allow_not_applicable}
    if min_confidence is not None:
        request["min_confidence"] = min_confidence
    return request


def valid_verdicts(clause, allow_not_applicable):
    """VERDICTS, plus not_applicable when the switch is on and the clause may be
    not applicable at all (never_not_applicable clauses may not)."""
    if allow_not_applicable and not clause.get("never_not_applicable"):
        return VERDICTS_WITH_NA
    return VERDICTS


def _call_judge(cmd, request, timeout):
    """One judge-cmd call under a timeout; any failure -- non-zero exit, timeout,
    output that is not JSON -- is EvidenceUnavailable, never a crash."""
    try:
        proc = subprocess.run(shlex.split(cmd), input=json.dumps(request), capture_output=True, text=True,
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        raise EvidenceUnavailable(f"judge did not answer within {timeout}s")
    except OSError as e:
        raise EvidenceUnavailable(f"judge command could not run: {e}")
    if proc.returncode != 0:
        raise EvidenceUnavailable(f"judge exited {proc.returncode}: {proc.stderr.strip()}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise EvidenceUnavailable(f"judge output is not JSON: {e}")


def judge(cmd, case_payload, clause, spec_root, judge_model_id, allow_not_applicable=False,
          min_confidence=None, timeout=DEFAULT_JUDGE_TIMEOUT):
    """Judge exactly one clause with one judge-cmd call. What demo/tau2/compiled.json
    (tests/stub_judge.py) and any contract without "judge_batch": true uses."""
    request = dict(_judge_request(case_payload, spec_root, judge_model_id, allow_not_applicable, min_confidence),
                   clause=clause)
    return checked_answer(_call_judge(cmd, request, timeout), valid_verdicts(clause, allow_not_applicable))


def judge_batch(cmd, case_payload, clauses, spec_root, judge_model_id, allow_not_applicable=False,
                min_confidence=None, timeout=DEFAULT_JUDGE_TIMEOUT):
    """Judge every clause in `clauses` with ONE judge-cmd call: one conversation,
    one policy text, one request. clause_id -> checked answer, one entry per
    clause passed in -- a judge command that drops or invents a clause id fails
    this closed via checked_answer(), same as a bad single-clause answer would."""
    request = dict(_judge_request(case_payload, spec_root, judge_model_id, allow_not_applicable, min_confidence),
                   clauses=clauses)
    parsed = _call_judge(cmd, request, timeout)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("answers"), dict):
        raise EvidenceUnavailable(f"judge returned no valid batch answers: {parsed!r}")
    return {clause["id"]: checked_answer(parsed["answers"].get(clause["id"]),
                                         valid_verdicts(clause, allow_not_applicable))
            for clause in clauses}


def recomputed_answer(case_payload, clause, spec_root):
    """Run the registered deterministic checker for a tier:recomputed clause.
    Refuses -- fails the run closed -- for a clause that names no registered
    checker, rather than inventing one: skills/daily-judge-and-close/SKILL.md's
    own rule for a fold with no registered implementation, applied here since the
    capsulectl-engine fold plugin itself doesn't exist yet."""
    checker = RECOMPUTE_CHECKS.get(clause["id"])
    if checker is None:
        raise EvidenceUnavailable(f"clause {clause['id']!r} is tier 'recomputed' but names no registered checker")
    request = {"clause": clause, "case": case_payload["case"],
               "agent_interaction": case_payload["agent_interaction"],
               "policy": str(spec_root / "airline-data" / "policy.md"),
               "booking_db": str(spec_root / "airline-data" / "db.json")}
    return checked_answer(checker(request))


def build_report(clause, switches, answer, contract, case_id, capsule_id, pin, day,
                 contract_ref=None, judge_pin=None, pack_source_digest=None):
    """The evaluation-report/v1 body for one clause -- pure, no I/O. `judge_pin_digest`
    is sealed only for a tier judged clause: a recomputed one was never judged, and
    citing the pinned judge's digest on it would misstate which model (none) actually
    produced the verdict, exactly the misattribution this module's own docstring warns
    about for a stale --judge-model-id.
    `clause_claim` always records the exact wording actually judged against, so a
    claim_switch flip is visible on the record itself, not just inferable from the day
    it was sealed.

    `contract_ref` (the compiled contract's `<contract_id>@<version>`, the same value
    every Result v0 claim names) and `judge_pin` (the exact `capsulectl judge pin`
    input -- model_id, prompt_digest, axes_digest, sampling_params -- whose JSON-DIGEST
    IS `judge_pin_digest`) are sealed on the record when given, so a reader of the
    disclosed report can see WHICH model, prompt and axes the pin names and recompute
    the digest from them, instead of being handed an opaque hash. `period` is the
    judged window, `day:<YYYY-MM-DD>`. `judge_pin` follows the same rule as the
    digest: never on a recomputed clause."""
    tier = effective_tier(clause, switches)
    report = {"record_type": "evaluation-report/v1",
              "contract": contract, "clause_id": clause["id"], "case_id": case_id,
              "source_capsule_id": capsule_id,
              "verdict": answer["verdict"], "rationale": answer.get("rationale", ""),
              "period": f"day:{day}",
              "clause_claim": effective_claim(clause, switches)}
    if contract_ref is not None:
        report["contract_ref"] = contract_ref
    if pack_source_digest is not None:
        report["pack_source_digest"] = pack_source_digest
    if tier == "judged":
        report["epistemic_type"] = "semantic_judgment"
        report["judge_pin_digest"] = pin
        if judge_pin is not None:
            report["judge_pin"] = dict(judge_pin)
    else:
        report["epistemic_type"] = "recomputed_determination"
        checker = RECOMPUTE_CHECKS[clause["id"]]
        report["checker_ref"] = f"{checker.__module__}.{checker.__qualname__}"
    return report


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--spec", required=True, type=pathlib.Path)
    ap.add_argument("--judge-cmd", required=True)
    ap.add_argument("--judge-model-id", required=True, help="the pinned judge's model id, as the judge command reports it")
    ap.add_argument("--date", required=True, help="the day to judge and close, YYYY-MM-DD (UTC)")
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("--capsulectl", default="capsulectl")
    ap.add_argument("--judge-timeout", type=int, default=DEFAULT_JUDGE_TIMEOUT,
                    help="seconds one judge-cmd call may take before the run stops with evidence unavailable")
    args = ap.parse_args(argv)

    root = args.spec.resolve().parents[2]
    spec = json.loads(args.spec.read_text())
    switches = spec.get("switches") or {}
    allow_not_applicable = bool(switches.get("not_applicable_verdict"))
    judge_batch_mode = bool(spec.get("judge_batch"))
    min_confidence = (spec.get("judge") or {}).get("min_confidence")
    day = datetime.date.fromisoformat(args.date)
    out = args.out / f"day-{day}"
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)
    ctl, profile = args.capsulectl, args.profile
    operator = run(ctl, "profile", "show", profile)["Operator"]
    log = {"skill": "daily-judge-and-close", "day": str(day), "profile": profile}

    try:
        # 1. Resolve the pinned judge before judging anything.
        pin_input = build_pin_input(spec, root, args.judge_model_id,
                                    describe_judge(args.judge_cmd, args.judge_timeout))
        (work / "judge-pin.json").write_text(json.dumps(pin_input))
        pin = run(ctl, "judge", "pin", str(work / "judge-pin.json"))["judge_pin_digest"]
        log["judge_pin_digest"] = pin

        # 2. Read the day's range: the cases the book committed that day.
        cases = []
        for entry in list_capsules(ctl, profile):
            if not committed_on(entry, day):
                continue
            body = payload(ctl, profile, entry["capsule_id"])
            if isinstance(body, dict) and isinstance(body.get("case"), dict):
                cases.append((entry["capsule_id"], body))
        log["cases"] = len(cases)

        # 3-4. Authenticate each case, judge/recompute it per clause, seal the report.
        reports, verdicts = [], {}
        stamp = f"{day}T23:59:59Z"
        for capsule_id, body in cases:
            verify(ctl, profile, capsule_id, work)
            c = body["case"]
            case_id = f"{c['benchmark']}:{c['domain']}:task-{c['task_id']}:trial-{c['trial']}"

            judged_clauses, recomputed_clauses = [], []
            for clause in spec["clauses"]:
                tier = effective_tier(clause, switches)
                if tier == "judged":
                    judged_clauses.append(dict(clause, claim=effective_claim(clause, switches)))
                elif tier == "recomputed":
                    recomputed_clauses.append(clause)
                # any other tier: skipped, same as today's `continue`

            answers = {clause["id"]: recomputed_answer(body, clause, root) for clause in recomputed_clauses}
            if judged_clauses:
                if judge_batch_mode:
                    answers.update(judge_batch(args.judge_cmd, body, judged_clauses, root,
                                                args.judge_model_id, allow_not_applicable,
                                                min_confidence, args.judge_timeout))
                else:
                    for clause in judged_clauses:
                        answers[clause["id"]] = judge(args.judge_cmd, body, clause, root,
                                                       args.judge_model_id, allow_not_applicable,
                                                       min_confidence, args.judge_timeout)

            for clause in spec["clauses"]:
                if clause["id"] not in answers:
                    continue  # tier skipped above
                answer = answers[clause["id"]]
                report = build_report(clause, switches, answer, spec["contract"],
                                       case_id, capsule_id, pin, day,
                                       contract_ref=spec.get("contract_ref"), judge_pin=pin_input,
                                       pack_source_digest=spec.get("pack_source_digest"))
                rid = publish(ctl, profile, seal_request(
                    f"urn:evidencebook-skills:evaluation-report:{case_id}:{clause['id']}", operator,
                    "evidencebook-skills/daily-judge-and-close", stamp, report), work, f"report-{capsule_id[:16]}")
                reports.append(rid)
                verdicts[answer["verdict"]] = verdicts.get(answer["verdict"], 0) + 1
        log["reports"] = reports
        log["verdicts"] = verdicts

        # 5. Seal the day's Close. No peer bundle is held: it is unilateral.
        close_args = ["close", "--profile", profile, "--period", "day", "--date", str(day),
                      "--counterparty", spec["counterparty"]]
        capsule_out, bundle_out = out / "close.json", out / "close-bundle.json"
        if not capsule_out.exists():
            close_args += ["--capsule-out", str(capsule_out), "--bundle-out", str(bundle_out)]
        closed = run(ctl, *close_args)
        log["close"] = {"record_id": closed["record_id"], "already_closed": closed["already_closed"],
                        "unilateral": not closed.get("peer_bundle"),
                        "window": [closed["reconciliation"]["from_seq"], closed["reconciliation"]["to_seq"]],
                        "capsule": str(capsule_out), "bundle": str(bundle_out)}
    except (KeyError, TypeError) as e:
        log["evidence_unavailable"] = f"malformed case, report or spec: missing or mistyped {e}"
        print(json.dumps(log, indent=2))
        return 2
    except EvidenceUnavailable as e:
        log["evidence_unavailable"] = str(e)
        print(json.dumps(log, indent=2))
        return 2
    (out / "run.json").write_text(json.dumps(log, indent=2))
    print(json.dumps(log, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
