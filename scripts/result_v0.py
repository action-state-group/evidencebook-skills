"""Maps this contract's per-criterion evaluation-report/v1 records
(scripts/run_daily.py, one conversation) into the Evidence Result v0 document
(evidence-result-v0) `capsulectl result build` takes as its --result input and
validates against its vendored schema. Written to match that schema exactly.

Known, flagged gaps against the schema:
  - `proofs` is always [] here. A real inclusion proof or receipt digest comes from
    the book; this judge/rollup seam produces none.
  - `grade` is always "self-attested": these are our own book's judge verdicts,
    never witnessed or countersigned by any other party.
  - `sufficiency` maps met/not_met -> SATISFIED, not_evaluable -> GAP, per the
    schema's Claim.allOf rule (sufficiency SATISFIED <-> verdict in {met,
    not_met}; otherwise verdict MUST be not_evaluable).
  - `contract_ref` is the compiled contract's own `contract_ref` field when present
    (scripts/pack_compile.py writes "<pack_id>@<pack_version>"); a hand-authored
    contract without one (demo/tau2-outcomes/compiled.json) falls back to a "@1"
    placeholder suffix on the contract id.

`not_applicable`: scripts/rollup.py accepts `not_applicable` as a criterion verdict
when the contract's not_applicable_verdict switch is on, but it is NOT one of
Evidence Result v0's three `Verdict` values (`met`/`not_met`/`not_evaluable`,
closed enum). Per the Result v0 spec, `not_applicable` is excluded from the
evaluated population entirely and only appears as
`aggregate.coverage.excluded_not_applicable`, never as a claim. A not_applicable
criterion therefore gets NO claim here, and is never folded into `met`.

The headline re-derives from the document alone. In a day document every claim's
id is `<case_id>::<criterion_id>`; a case is resolved exactly when every one of its
claims is met (headline_from_result()). That equals scripts/rollup.py's
all_required_met for every case the document carries, because a case reaches a
document only when it has at least one evaluated claim (an all-not_applicable
case resolves nothing and is refused here, reported by the caller instead) and a
never_not_applicable criterion is never not_applicable.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from rollup import RollupError, all_required_met  # noqa: E402

CASE_SEPARATOR = "::"

_VERDICTS = ("met", "not_met", "not_evaluable")
_VERDICTS_WITH_NA = _VERDICTS + ("not_applicable",)


def _digest_ref(hex_digest):
    return {"digest_alg": "SHA-256", "digest": hex_digest}


def resolve_contract_ref(spec):
    """A compiled contract's contract_ref, or the "@1" placeholder fallback this
    module's docstring documents for a contract compiled before that field existed
    (e.g. demo/tau2-outcomes/compiled.json) -- never a bare, unversioned contract
    id, which the <contract_id>@<version> schema shape (read from the PR diff)
    does not accept."""
    return spec.get("contract_ref") or f"{spec['contract']}@1"


def claim_for(criterion_id, verdict, contract_ref, tier, report_digest=None, claim_id=None):
    """One requirement-type claim (PR #19's ClaimType default: absent == requirement)
    for one criterion. `tier` is that criterion's own tier ("judged" or
    "recomputed") from the compiled contract's clause -- required, never
    hardcoded or defaulted, so a criterion later flipped to tier: recomputed
    (scripts/pack_compile.py) is reported as what it actually is, not silently
    relabelled "judged".

    `report_digest` is the sealed evaluation-report/v1 capsule's digest for this
    criterion, when known -- cited in evidence[] but never inline.

    `claim_id` overrides the claim's own `id` (default: `criterion_id`) -- the
    day-level merge needs `<case_id>::<criterion_id>` so many cases' claims can
    live in one document (see build_result_v0_for_day); the per-case document
    this function was originally written for has no case collision to
    disambiguate, so its id stays the bare criterion_id, unchanged, for every
    existing caller/test.

    `verdict` is strictly `met`/`not_met`/`not_evaluable` -- Evidence Result v0's
    closed Verdict enum, which this function never widens: a `not_applicable`
    criterion is never passed here at all (see build_result_v0's own filtering,
    and this module's docstring on why)."""
    if verdict not in _VERDICTS:
        raise RollupError(f"not a verdict: {verdict!r}")
    sufficiency = "GAP" if verdict == "not_evaluable" else "SATISFIED"
    disclosure_status = "INSUFFICIENT" if verdict == "not_evaluable" else "SATISFIED"
    evidence = [_digest_ref(report_digest)] if report_digest else []
    return {
        "id": claim_id if claim_id is not None else criterion_id,
        "contract_ref": contract_ref,
        "requirement_ref": criterion_id,
        "tier": tier,
        "grade": "self-attested",
        "sufficiency": sufficiency,
        "verdict": verdict,
        "evidence": evidence,
        "proofs": [],
        "presentation": {"kind": "disclosure", "status": disclosure_status, "evidence": evidence},
    }


def build_result_v0(case_id, criterion_verdicts, report_digests, generated_at, all_criteria, contract_ref, tiers,
                     allow_not_applicable=False, never_not_applicable=frozenset()):
    """criterion_verdicts: dict[criterion_id -> verdict]. report_digests: dict
    [criterion_id -> sealed evaluation-report capsule digest], may omit entries.
    `all_criteria`: tuple of every criterion id the compiled contract defines
    (scripts/rollup.py:all_criteria_from_clauses) -- pack-driven, not a fixed nine.
    `contract_ref` is the compiled contract's own contract_ref, passed straight
    through to every claim. `tiers`: dict[criterion_id -> tier], each
    criterion's own tier from the compiled contract's clause -- required for
    every id in all_criteria; a missing entry is a caller bug (KeyError), not a
    defaulted-to-"judged" guess. Delegates its shape check to
    rollup.all_required_met -- exactly that contract's known criteria, nothing
    missing, nothing unrecognized -- so a malformed call fails closed here too,
    not just in the rollup.

    allow_not_applicable: the not_applicable_verdict switch (off by default, so the
    document's shape is unchanged unless a caller opts in). When on, a
    not_applicable criterion still counts as passing in `resolved`
    (all_required_met's own rule) but gets NO claim at all in `claims[]` -- only
    counted in `aggregate.coverage.excluded_not_applicable` -- per Evidence Result
    v0's own schema (see this module's docstring): `verdict`/`buckets` have no
    not_applicable value to hold it in.

    Returns (document, resolved) -- resolved is the same all_required_met() boolean
    that produced the buckets, so a caller never has to re-derive it from the
    document to know whether this conversation resolved.

    A case on which every criterion is not_applicable has nothing to claim (the
    schema requires at least one claim) and resolves nothing: refused with
    RollupError, for the caller to report.
    """
    resolved = all_required_met(criterion_verdicts, all_criteria, allow_not_applicable, never_not_applicable)
    report_digests = report_digests or {}
    evaluated = [cid for cid in all_criteria if criterion_verdicts[cid] != "not_applicable"]
    if not evaluated:
        raise RollupError(f"case {case_id!r}: every criterion is not_applicable; nothing was evaluated")
    excluded_not_applicable = len(all_criteria) - len(evaluated)
    claims = [
        claim_for(cid, criterion_verdicts[cid], contract_ref, tiers[cid], report_digests.get(cid))
        for cid in evaluated
    ]
    buckets = {"met": [], "not_met": [], "not_evaluable": []}
    for c in claims:
        buckets[c["verdict"]].append(c["id"])
    document = {
        "result_version": "evidence-result-v0",
        "generated_at": generated_at,
        "claims": claims,
        "aggregate": {
            "coverage": {
                "evaluated_population": len(claims),
                "excluded_not_applicable": excluded_not_applicable,
                "unknown_count": 0,
            },
            "buckets": buckets,
        },
        "view": {
            "spec_version": "presentation/v1",
            "title": f"Outcome result -- {case_id}",
        },
    }
    return document, resolved


def build_result_v0_for_day(period, case_rollups, generated_at, all_criteria, contract_ref,
                             allow_not_applicable=False, never_not_applicable=frozenset()):
    """One Result v0 document spanning every complete case judged for one day/
    period: an outcome report renders from a single Result root, so a
    conversation's criteria live beside every other conversation's in one document
    rather than in one Result per case.

    `case_rollups`: iterable of (case_id, criterion_verdicts, report_digests, tiers)
    -- already-grouped, already-complete cases against `all_criteria`; a caller
    that hands in an incomplete case gets RollupError, same fail-closed rule as
    every other rollup here. `all_criteria`/`contract_ref` are the same pack-driven
    values scripts/rollup_day.py derives from --spec once, never a fixed nine or a
    hardcoded ref. Each claim's `id` is `<case_id>::<criterion_id>` so one document
    can hold every case's claims without collision, and so headline_from_result()
    can regroup them; `requirement_ref` stays the bare criterion_id.

    `allow_not_applicable`: same switch build_result_v0() takes -- threaded through
    only so this function can tell a legitimate not_applicable input verdict apart
    from a stray one (defense in depth; every real caller already filtered
    incomplete/malformed cases out before this point). A not_applicable criterion
    gets NO claim in `claims[]` either, same rule and same schema reason as
    build_result_v0 -- see this module's docstring. Every case must pass
    all_required_met (never_not_applicable included) and carry at least one
    evaluated criterion, or the whole call is refused: the caller filters cases
    first and reports the ones it filtered.
    """
    claims = []
    excluded_not_applicable = 0
    for case_id, criterion_verdicts, report_digests, tiers in case_rollups:
        missing = [c for c in all_criteria if c not in criterion_verdicts]
        if missing:
            raise RollupError(f"case {case_id!r} missing criteria: {missing!r}")
        bad = [c for c in all_criteria
               if criterion_verdicts[c] not in (_VERDICTS_WITH_NA if allow_not_applicable else _VERDICTS)]
        if bad:
            raise RollupError(f"case {case_id!r} carries unrecognized verdicts for {bad!r}")
        if CASE_SEPARATOR in case_id:
            raise RollupError(f"case id {case_id!r} contains {CASE_SEPARATOR!r}; claim ids could not be regrouped")
        all_required_met(criterion_verdicts, all_criteria, allow_not_applicable, never_not_applicable)
        if all(criterion_verdicts[c] == "not_applicable" for c in all_criteria):
            raise RollupError(f"case {case_id!r}: every criterion is not_applicable; nothing was evaluated")
        report_digests = report_digests or {}
        for cid in all_criteria:
            if criterion_verdicts[cid] == "not_applicable":
                excluded_not_applicable += 1
                continue
            claims.append(claim_for(
                cid, criterion_verdicts[cid], contract_ref, tiers[cid], report_digests.get(cid),
                claim_id=f"{case_id}{CASE_SEPARATOR}{cid}",
            ))
    buckets = {"met": [], "not_met": [], "not_evaluable": []}
    for c in claims:
        buckets[c["verdict"]].append(c["id"])
    return {
        "result_version": "evidence-result-v0",
        "generated_at": generated_at,
        "claims": claims,
        "aggregate": {
            "coverage": {
                "evaluated_population": len(claims),
                "excluded_not_applicable": excluded_not_applicable,
                "unknown_count": 0,
            },
            "buckets": buckets,
        },
        "view": {
            "spec_version": "presentation/v1",
            "title": f"Outcome result -- {period}",
        },
    }


def headline_from_result(document):
    """The headline, from a day document alone: {"cases", "resolved"}. Claims are
    regrouped by the `<case_id>::` prefix of their id; a case is resolved exactly
    when every one of its claims is met."""
    by_case = {}
    for claim in document["claims"]:
        case_id, sep, _ = claim["id"].rpartition(CASE_SEPARATOR)
        if not sep:
            raise RollupError(f"claim id {claim['id']!r} names no case (expected <case_id>{CASE_SEPARATOR}<criterion>)")
        by_case.setdefault(case_id, []).append(claim["verdict"])
    return {"cases": len(by_case),
            "resolved": sum(1 for verdicts in by_case.values() if all(v == "met" for v in verdicts))}
