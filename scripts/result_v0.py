"""Maps this contract's per-criterion evaluation-report/v1 records
(scripts/run_daily.py, one conversation) into the Evidence Result v0 document
(evidence-result-v0) `capsulectl book result build` takes as its --result input and
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

`out_of_scope`: scripts/rollup.py accepts `out_of_scope` as a criterion verdict
when the contract's out_of_scope_verdict switch is on, but it is NOT one of
Evidence Result v0's three `Verdict` values (`met`/`not_met`/`not_evaluable`,
closed enum). An out_of_scope criterion is a requirement that does not apply to
this case, which is what the Result v0 spec's NOT_APPLICABLE population exclusion
counts: excluded from the evaluated population entirely and only appearing as
`aggregate.coverage.excluded_not_applicable`, never as a claim. An out_of_scope
criterion therefore gets NO claim here: it is never folded into `met`, and never
into `not_evaluable` either -- that verdict means the requirement applies and
could not be determined, which is a different claim.

The headline re-derives from the document alone. In a day document every claim's
id is `<case_id>::<criterion_id>`; a case is resolved exactly when every one of its
claims is met (headline_from_result()). That equals scripts/rollup.py's
all_required_met for every case the document carries, because a case reaches a
document only when it has at least one evaluated claim (an all-out_of_scope
case resolves nothing and is refused here, reported by the caller instead) and a
never_out_of_scope criterion is never out_of_scope.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from rollup import RollupError, all_required_met, refuse_unknown_verdicts  # noqa: E402

CASE_SEPARATOR = "::"

_VERDICTS = ("met", "not_met", "not_evaluable")
_VERDICTS_WITH_OOS = _VERDICTS + ("out_of_scope",)


def _digest_ref(hex_digest):
    return {"digest_alg": "SHA-256", "digest": hex_digest}


def resolve_contract_ref(spec):
    """A compiled contract's contract_ref, or the "@1" placeholder fallback this
    module's docstring documents for a contract compiled before that field existed
    (e.g. demo/tau2-outcomes/compiled.json) -- never a bare, unversioned contract
    id, which the <contract_id>@<version> schema shape (read from the PR diff)
    does not accept."""
    return spec.get("contract_ref") or f"{spec['contract']}@1"


def claim_for(criterion_id, verdict, contract_ref, tier, report_digest=None, claim_id=None,
             judge_pin_digest=None, judge_pin=None, rule_id=None, source_capsule_id=None):
    """One requirement-type claim (PR #19's ClaimType default: absent == requirement)
    for one criterion. `tier` is that criterion's own tier ("judged" or
    "recomputed") from the compiled contract's clause -- required, never
    hardcoded or defaulted, so a criterion later flipped to tier: recomputed
    (scripts/pack_compile.py) is reported as what it actually is, not silently
    relabelled "judged".

    `report_digest` is the sealed evaluation-report/v1 capsule's digest for this
    criterion, when known -- cited in evidence[] but never inline. Either one
    digest (a string, every existing caller's shape) or several (a list/tuple --
    scripts/judge_bundle.py's whole-bundle mode, which judges every disclosed
    record in one request and cites every one it actually used, not just one;
    and scripts/report_spec.py's deterministic (tier: recomputed) claims over a
    GROUP of records, which cite every contributing capsule). A set is accepted
    too (ordered as given by iteration).

    `judge_pin_digest`/`judge_pin` are the model identity a judged claim carries
    (a `judged` claim needs a code/model identity, not only the policy digest a
    `recomputed` one has) -- sealed only when `tier == "judged"`, same
    rule scripts/run_daily.py's build_report() follows for its own
    evaluation-report/v1 record: a recomputed clause was never judged, and citing
    a judge's identity on it would misstate what produced the verdict. `rule_id`,
    `judge_pin_digest`, and `judge_pin` are additional keys on the claim beyond
    the vendored evidence-result-v0 schema's own fields -- named here as a known
    extension, never assumed schema-valid against that schema's own
    additionalProperties rule.

    `rule_id` is the bare source-rule number (packs/everyday-rules/pack-source.yaml's
    `rule_id`), when the compiled contract's clause carries one -- `requirement_ref`
    stays the compound `<check_id>.<criterion_id>` clause id; this is the separate,
    human-facing rule number a reader of the rule doc would recognize.

    `source_capsule_id` is that report's own citation of the case record it
    judged (evaluation-report/v1's `source_capsule_id`, always a book capsule's
    own content-addressed id, which doubles as its digest in this system) --
    appended to evidence[] after `report_digest`'s own entry (or entries), when
    both are known (in practice a report always carries both or neither), and
    not repeated when it is already one of those digests. Never fabricated:
    omitted when the report didn't carry one, and -- pathological, never the
    real shape -- it is evidence[]'s only entry if `report_digest` is absent
    while this is given. A Result is sealed only over evidence the book holds
    (capsule-cli's `book result build`), so citing the case record here is what lets
    `capsulectl disclose --attach-input-originals` later find and attach that
    case's transcript (the case capsule's own agent_input original) with no
    further, by-hand step.

    `claim_id` overrides the claim's own `id` (default: `criterion_id`) -- the
    day-level merge needs `<case_id>::<criterion_id>` so many cases' claims can
    live in one document (see build_result_v0_for_day); the per-case document
    this function was originally written for has no case collision to
    disambiguate, so its id stays the bare criterion_id, unchanged, for every
    existing caller/test.

    `verdict` is strictly `met`/`not_met`/`not_evaluable` -- Evidence Result v0's
    closed Verdict enum, which this function never widens: an `out_of_scope`
    criterion is never passed here at all (see build_result_v0's own filtering,
    and this module's docstring on why)."""
    if verdict not in _VERDICTS:
        raise RollupError(f"not a verdict: {verdict!r}")
    sufficiency = "GAP" if verdict == "not_evaluable" else "SATISFIED"
    disclosure_status = "INSUFFICIENT" if verdict == "not_evaluable" else "SATISFIED"
    if not report_digest:
        digests = []
    elif isinstance(report_digest, (list, tuple, set)):
        digests = list(report_digest)
    else:
        digests = [report_digest]
    evidence = [_digest_ref(d) for d in digests if d]
    if source_capsule_id and source_capsule_id not in digests:
        evidence.append(_digest_ref(source_capsule_id))
    claim = {
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
    if rule_id is not None:
        claim["rule_id"] = rule_id
    if tier == "judged" and judge_pin_digest is not None:
        claim["judge_pin_digest"] = judge_pin_digest
        if judge_pin is not None:
            claim["judge_pin"] = dict(judge_pin)
    return claim


def build_result_v0(case_id, criterion_verdicts, report_digests, generated_at, all_criteria, contract_ref, tiers,
                     allow_out_of_scope=False, never_out_of_scope=frozenset(), judge_pin_digests=None,
                     judge_pins=None, rule_ids=None, source_capsule_ids=None, case_scoped_ids=False):
    """criterion_verdicts: dict[criterion_id -> verdict]. report_digests: dict
    [criterion_id -> sealed evaluation-report capsule digest], may omit entries.
    `source_capsule_ids`: optional dict[criterion_id -> the case record capsule
    id that criterion's report named], may omit entries -- cited as each
    claim's second evidence[] entry (see claim_for's own docstring); never
    fabricated for a criterion this dict doesn't name.
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

    `judge_pin_digests`/`judge_pins`/`rule_ids`: optional dict[criterion_id -> ...],
    threaded straight to claim_for() for each evaluated criterion -- see its own
    docstring. All three default to omitted so an existing caller (nothing in this
    module's own tests, or scripts/rollup_day.py) that never names them gets
    exactly the claims it always has.

    allow_out_of_scope: the out_of_scope_verdict switch (off by default, so the
    document's shape is unchanged unless a caller opts in). When on, an
    out_of_scope criterion is set aside in `resolved` (all_required_met's own
    rule: it never counts toward satisfaction) and gets NO claim at all in `claims[]` -- only
    counted in `aggregate.coverage.excluded_not_applicable` -- per Evidence Result
    v0's own schema (see this module's docstring): `verdict`/`buckets` have no
    out_of_scope value to hold it in.

    case_scoped_ids: off by default (claim id = criterion id). On, each claim id is
    `<case_id>::<criterion_id>`, the scheme build_result_v0_for_day uses, so documents
    for different cases merge (merge_result_v0_documents refuses shared claim ids).

    Returns (document, resolved) -- resolved is the same all_required_met() boolean
    that produced the buckets, so a caller never has to re-derive it from the
    document to know whether this conversation resolved.

    A case on which every criterion is out_of_scope has nothing to claim (the
    schema requires at least one claim) and resolves nothing: refused with
    RollupError, for the caller to report.
    """
    if case_scoped_ids and CASE_SEPARATOR in str(case_id):
        # The same refusal build_result_v0_for_day makes: the root becomes part
        # of every claim id, and readers split it back out at CASE_SEPARATOR
        # (headline_from_result at the last, the card's parseClaimGrouping at
        # the first), so a case id holding one would be grouped two ways.
        raise RollupError(f"case id {case_id!r} contains {CASE_SEPARATOR!r}; claim ids could not be regrouped")
    resolved = all_required_met(criterion_verdicts, all_criteria, allow_out_of_scope, never_out_of_scope)
    report_digests = report_digests or {}
    source_capsule_ids = source_capsule_ids or {}
    evaluated = [cid for cid in all_criteria if criterion_verdicts[cid] != "out_of_scope"]
    if not evaluated:
        raise RollupError(f"case {case_id!r}: every criterion is out_of_scope; nothing was evaluated")
    excluded_not_applicable = len(all_criteria) - len(evaluated)
    judge_pin_digests, judge_pins, rule_ids = judge_pin_digests or {}, judge_pins or {}, rule_ids or {}
    claims = [
        claim_for(cid, criterion_verdicts[cid], contract_ref, tiers[cid], report_digests.get(cid),
                 judge_pin_digest=judge_pin_digests.get(cid), judge_pin=judge_pins.get(cid),
                 rule_id=rule_ids.get(cid), source_capsule_id=source_capsule_ids.get(cid),
                 claim_id=f"{case_id}{CASE_SEPARATOR}{cid}" if case_scoped_ids else None)
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
                             allow_out_of_scope=False, never_out_of_scope=frozenset(),
                             source_capsule_ids=None):
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

    `source_capsule_ids`: optional dict[case_id -> dict[criterion_id -> source
    capsule id]] -- the per-case, per-criterion case-record citation
    build_result_v0() takes per claim, keyed by case_id here because one day
    document spans many cases. A missing case or criterion entry just means no
    case-record citation for that claim; never fabricated. Kept as its own
    top-level parameter rather than a 5th case_rollups element so every
    existing caller/test keeps working unchanged.

    `allow_out_of_scope`: same switch build_result_v0() takes -- threaded through
    only so this function can tell a legitimate out_of_scope input verdict apart
    from a stray one (defense in depth; every real caller already filtered
    incomplete/malformed cases out before this point). An out_of_scope criterion
    gets NO claim in `claims[]` either, same rule and same schema reason as
    build_result_v0 -- see this module's docstring. Every case must pass
    all_required_met (never_out_of_scope included) and carry at least one
    evaluated criterion, or the whole call is refused: the caller filters cases
    first and reports the ones it filtered.
    """
    claims = []
    excluded_not_applicable = 0
    source_capsule_ids = source_capsule_ids or {}
    for case_id, criterion_verdicts, report_digests, tiers in case_rollups:
        missing = [c for c in all_criteria if c not in criterion_verdicts]
        if missing:
            raise RollupError(f"case {case_id!r} missing criteria: {missing!r}")
        try:
            refuse_unknown_verdicts([criterion_verdicts[c] for c in all_criteria],
                                    _VERDICTS_WITH_OOS if allow_out_of_scope else _VERDICTS)
        except RollupError as e:
            raise RollupError(f"case {case_id!r} carries unrecognized verdicts: {e}") from e
        if CASE_SEPARATOR in case_id:
            raise RollupError(f"case id {case_id!r} contains {CASE_SEPARATOR!r}; claim ids could not be regrouped")
        all_required_met(criterion_verdicts, all_criteria, allow_out_of_scope, never_out_of_scope)
        if all(criterion_verdicts[c] == "out_of_scope" for c in all_criteria):
            raise RollupError(f"case {case_id!r}: every criterion is out_of_scope; nothing was evaluated")
        report_digests = report_digests or {}
        case_sources = source_capsule_ids.get(case_id) or {}
        for cid in all_criteria:
            if criterion_verdicts[cid] == "out_of_scope":
                excluded_not_applicable += 1
                continue
            claims.append(claim_for(
                cid, criterion_verdicts[cid], contract_ref, tiers[cid], report_digests.get(cid),
                claim_id=f"{case_id}{CASE_SEPARATOR}{cid}",
                source_capsule_id=case_sources.get(cid),
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


def merge_result_v0_documents(docs, title, generated_at):
    """Combine several already-built Result v0 documents (e.g. one per day
    over a --date/--to range, from either scripts/rollup_day.py's judged path
    or scripts/report_spec.py's no-judge path -- this function does not care
    which) into ONE Result v0 document spanning all of them: `book report build`
    takes exactly one sealed Result as its bundle's root, so a multi-day
    report needs its days combined before `book result build` ever sees them, not
    multiple separate bundles.

    Concatenates every document's claims[] (fails closed -- RollupError -- if
    two documents share a claim id, which would mean two different inputs
    both computed a verdict for what the schema's own closed id space treats
    as the same claim, or if they don't all share one contract_ref, which
    would mean mixing results from two different contracts/specs into one
    document) and recomputes aggregate.buckets and
    aggregate.coverage.evaluated_population from the merged claims list
    directly, never by trusting the inputs' own buckets/evaluated_population
    verbatim -- a bug in how an input computed those can't survive into the
    merge undetected. The one exception, by necessity rather than choice:
    aggregate.coverage.excluded_not_applicable is SUMMED from the inputs'
    own values, because an out_of_scope criterion gets NO claim object at
    all (scripts/result_v0.py's own module docstring) -- there is nothing
    in claims[] for this function to recompute that count FROM. A bad
    excluded_not_applicable in one input's own aggregate does survive into
    the merge; recomputing it would need each input's original
    criterion_verdicts, which this function is never given."""
    docs = list(docs)
    if not docs:
        raise RollupError("merge_result_v0_documents needs at least one document")
    contract_refs = {c["contract_ref"] for d in docs for c in d["claims"]}
    if len(contract_refs) > 1:
        raise RollupError(f"documents carry more than one contract_ref: {sorted(contract_refs)!r}")
    claims = [c for d in docs for c in d["claims"]]
    seen = set()
    dupes = sorted({c["id"] for c in claims if c["id"] in seen or seen.add(c["id"])})
    if dupes:
        raise RollupError(f"documents share claim id(s): {dupes!r}")
    buckets = {"met": [], "not_met": [], "not_evaluable": []}
    for c in claims:
        buckets[c["verdict"]].append(c["id"])
    excluded_not_applicable = sum(d["aggregate"]["coverage"]["excluded_not_applicable"] for d in docs)
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
            "title": title,
        },
    }
