#!/usr/bin/env python3
"""Judge a whole evidence-bundle/v2 file against a compiled pack's rows
(packs/everyday-rules/pack-source.yaml, compiled by scripts/pack_compile.py),
and print one Evidence Result v0 document.

    python3 scripts/judge_bundle.py --bundle BUNDLE.json --pack COMPILED.json \\
        --generated-at 2026-10-08T00:00:00Z [--capsule-id ID] [--rule-ids 8,9,26] \\
        [--judge-model-id jev-1.13.0]

Bundle shape (evidence-bundle/v2 -- capsule-cli's `internal/cli/bundle.go`,
`AssembleBundle`): a top-level object with `bundle_kind`, `records` (a list of
capsule objects, each self-addressed by its own `capsule_id`), `completeness`
(`records_mode`, `payloads_mode`, `missing`), an optional `disclosures` object
keyed by `capsule_id` (present only when the bundle was assembled with
`--payloads all|selected`), and an optional `extensions` object -- deal-wide
context riding alongside the per-record disclosures, not scoped to any one
record. Confirmed real: `capsulectl deal report --bundle out.json` (capsule-cli
main, `internal/cli/deal_report.go`'s `dealReportBundle`) emits exactly this
shape, with `extensions["x-deal-v0"]` and every deal step's own disclosed
payload carrying a `x-deal-v0` sub-block (`internal/cli/assets/x-deal-v0.schema.json`)
under its own `disclosures[capsule_id]` entry -- run end to end against the
`skills/deal/demo/jet-ski` fixture (open, 4 notes, check, an unapproved act,
then `deal report`): a real 10-record bundle, not a hand-built stand-in.

By default (no --capsule-id) this script judges the WHOLE bundle: every
disclosed record's payload, plus the bundle's own `extensions` block, go to
the judge together as one batched request's shared disclosed_facts -- the
judge decides each row from whatever of the deal it was actually given, same
as a real `capsulectl deal` bundle discloses more than one record at once
(roughly 8 action records plus the deal's x-deal-v0 extension, not one).
`evidence[]` on a judged claim cites every record capsule_id that actually
contributed facts, not an arbitrary single one.

--capsule-id narrows the judged per-record facts to one specific record (for
focusing on one step, or re-judging after a later disclosure) -- never the
only way to call this script. The bundle's `extensions` still ride along
even when narrowed: they describe the deal as a whole, not any one record,
so there is no single record's worth of them to narrow to.

Fail-closed rules, never inferred:

  WITHHELD bundle      completeness.payloads_mode == "none" AND no
                       "disclosures" key at all (capsule-anchor's countersign
                       `parse_bundle` rule, reused verbatim). Checked first,
                       whatever --capsule-id says. Every in-scope row:
                       not_evaluable, reason "payload withheld". No judge call
                       is made at all.
  nothing disclosed    (whole-bundle mode only) no record in the bundle has a
                       non-empty entry in `disclosures` -- an empty bundle, a
                       selectively-disclosed bundle that disclosed nothing
                       this script can use, or every disclosed entry being
                       `{}`. Every in-scope row: not_evaluable, reason "no
                       disclosed record in this bundle". Distinct from the
                       bundle being globally WITHHELD above.
  record not found     (--capsule-id narrowing only) the named capsule_id is
                       not in `records[]`. If it IS listed in
                       completeness.missing[], the reason is "record declared
                       missing"; otherwise "record not found in bundle".
                       Every in-scope row: not_evaluable -- never a hard
                       refusal, and never an inferred verdict.
  payload withheld     (--capsule-id narrowing only) the named record exists
                       in `records[]` but has no entry (or an empty one) in
                       `disclosures`. Every in-scope row: not_evaluable,
                       reason "payload withheld".

Only when none of the above applies does this script call the real (or mock)
judge: one jev_judge.judge_many() call, "disclosed_facts" mode
(scripts/judges/jev_judge.py) -- transcript-blind, every in-scope row sharing
the same batched request's shared state, same cost-fix packs/airline-support-outcomes
uses for one conversation's criteria.

Every claim the judge actually ran on carries judge_pin_digest/judge_pin (the
judged-instrument pin, scripts/instrument_pin.py: model_id,
prompt_template_hash, schema_hash, input_refs and model_hosting -- matching
capsule-engine PR #96's own judge_pin key set -- a `judged` claim names its
model and what it actually read, not only a policy digest) and cites every
bundle record it was actually judged from (evidence[] -- each record's own
capsule_id, the same self-addressing the bundle itself uses). The pin's own
input_refs is a DIFFERENT set: the normalized action fields (capsule-engine
#96's own closed vocabulary) ANY judged clause in this call declares its
prompt reads (declared_input_refs(), below -- the UNION of every selected
clause's own packs/everyday-rules/pack-source.yaml `judge_input_refs`, never
a record or capsule_id). This is scoped to the whole batched call, not to
one claim alone: judge_batch's one shared jev_judge.judge_many() request
(every in-scope clause sharing the same disclosed_facts in one call) seals
one pin, so every claim from that call carries the identical pin -- a claim
for a clause that itself declares no judge_input_refs still carries the
batch's pin, same as it was decided from the batch's one shared request, not
a request of its own. A reader of the pin alone learns what kind of fact
THIS CALL's shared judge request could read from, across every clause
batched into it; evidence[] on each claim itself still says WHICH record
that specific claim was actually judged from. A fail-closed abstention
(withheld/missing/undisclosed, above) carries neither: no model was ever
consulted, so no judge identity is sealed on it -- only the reason. A call
whose selected clauses declare no normalized action field at all cannot
seal an honest pin; run() refuses it as a BadInput, before the judge is
ever consulted, rather than invent a field name or omit the pin silently
(see build_judge_pin()).

No forbidden vocabulary: every string this script emits (rationale, reasons) is
either the judge's own answer or one of the fixed reason strings above -- checked
by tests/test_forbidden_vocabulary.py against vocab/forbidden-vocabulary.yaml.

Exit codes: 0 on a successful run (whatever the verdicts), 1 on a malformed
request (the "bad input" cases above), 2 on a judge backend failure. Never a
guessed verdict; never a partial document on stdout.

    JEV_JUDGE_BACKEND=mock python3 scripts/judge_bundle.py --bundle ... --pack ...
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "judges"))

from capsulectl_calls import EvidenceUnavailable  # noqa: E402
import instrument_pin  # noqa: E402
import jev_judge  # noqa: E402
from result_v0 import build_result_v0  # noqa: E402
from rollup import RollupError  # noqa: E402

BUNDLE_KIND = "evidence-bundle/v2"

REASON_PAYLOAD_WITHHELD = "payload withheld"
REASON_RECORD_DECLARED_MISSING = "record declared missing"
REASON_RECORD_NOT_FOUND = "record not found in bundle"
REASON_NOTHING_DISCLOSED = "no disclosed record in this bundle"


class BadInput(Exception):
    """Malformed input -- refused before anything is judged."""


class JudgeBackendFailure(Exception):
    """The judge backend itself failed (not a malformed request)."""


def load_json(path, what):
    try:
        return json.loads(pathlib.Path(path).read_text())
    except OSError as e:
        raise BadInput(f"cannot read {what} {path!r}: {e}")
    except json.JSONDecodeError as e:
        raise BadInput(f"{what} {path!r} is not valid JSON: {e}")


def load_pack(path):
    pack = load_json(path, "pack")
    if not isinstance(pack, dict) or not isinstance(pack.get("clauses"), list) or not pack["clauses"]:
        raise BadInput(f"pack {path!r} carries no clauses -- not a compiled pack")
    for clause in pack["clauses"]:
        if not isinstance(clause, dict) or not clause.get("id") or not clause.get("claim"):
            raise BadInput(f"pack {path!r} carries a clause with no id/claim: {clause!r}")
    return pack


def select_clauses(pack, rule_ids):
    """Every tier:judged clause, or the --rule-ids subset of them (matched against
    each clause's own `rule_id`, packs/pack_compile.py's pass-through field --
    never the compound clause id, which is an implementation detail of how the
    pack groups its checks). Refuses a requested rule id that names no clause at
    all, rather than silently judging fewer rows than asked for; refuses a
    repeated rule id too, rather than silently judging (and claiming) the same
    row twice. An empty (but not None) rule_ids -- e.g. a malformed --rule-ids
    "," on the CLI -- is refused the same way, rather than silently judging
    zero rows and only surfacing as a confusing judge-backend failure later."""
    judged = [c for c in pack["clauses"] if c.get("tier") == "judged"]
    if rule_ids is None:
        return judged
    if not rule_ids:
        raise BadInput("--rule-ids named no rule id at all")
    wanted = set(rule_ids)
    by_rule_id = {c["rule_id"]: c for c in judged if c.get("rule_id")}
    unknown = sorted(wanted - set(by_rule_id))
    if unknown:
        raise BadInput(f"--rule-ids names rule(s) this pack has no judged clause for: {unknown!r}")
    duplicates = sorted({r for r in rule_ids if rule_ids.count(r) > 1})
    if duplicates:
        raise BadInput(f"--rule-ids repeats rule(s) {duplicates!r}; each rule_id must be named at most once")
    return [by_rule_id[r] for r in rule_ids]


def load_bundle(path):
    bundle = load_json(path, "bundle")
    if not isinstance(bundle, dict) or bundle.get("bundle_kind") != BUNDLE_KIND:
        raise BadInput(f"bundle {path!r} is not a {BUNDLE_KIND} bundle "
                       f"(bundle_kind={bundle.get('bundle_kind') if isinstance(bundle, dict) else None!r})")
    return bundle


def is_withheld(bundle):
    """capsule-anchor's countersign `parse_bundle` rule, reused verbatim: a bundle
    is WITHHELD when completeness.payloads_mode is "none" and it carries no
    `disclosures` key at all (not merely an empty one -- key absence is the
    signal)."""
    completeness = bundle.get("completeness") or {}
    return completeness.get("payloads_mode") == "none" and "disclosures" not in bundle


def _bundle_records(bundle):
    records = bundle.get("records")
    if not isinstance(records, list):
        raise BadInput("bundle.records must be a list")
    return records


def _bundle_disclosures(bundle):
    disclosures = bundle.get("disclosures")
    if disclosures is not None and not isinstance(disclosures, dict):
        raise BadInput("bundle.disclosures must be a mapping")
    return disclosures or {}


def disclosed_records(bundle):
    """{capsule_id: facts} for every record in bundle.records[] that is both
    self-addressed (carries its own non-empty capsule_id) and meaningfully
    disclosed (a non-empty entry in bundle.disclosures) -- the whole-bundle
    default's "every disclosed record". A record with no capsule_id, no
    disclosure entry, or an explicitly-disclosed-but-empty ({}) one
    contributes nothing: this is never "every record", only every one this
    script can actually read something from."""
    disclosures = _bundle_disclosures(bundle)
    out = {}
    for r in _bundle_records(bundle):
        if not isinstance(r, dict):
            continue
        cid = r.get("capsule_id")
        if not cid:
            continue
        facts = disclosures.get(cid)
        if facts:
            out[cid] = facts
    return out


def resolve_target(bundle, capsule_id):
    """(record_or_None, reason_or_None). Only called when --capsule-id narrows
    to one specific record. reason is set exactly when record is None:
    REASON_RECORD_DECLARED_MISSING if completeness.missing[] names the target,
    REASON_RECORD_NOT_FOUND otherwise."""
    records = _bundle_records(bundle)
    record = next((r for r in records if isinstance(r, dict) and r.get("capsule_id") == capsule_id), None)
    if record is not None:
        return record, None
    missing = (bundle.get("completeness") or {}).get("missing") or []
    reason = REASON_RECORD_DECLARED_MISSING if capsule_id in missing else REASON_RECORD_NOT_FOUND
    return None, reason


def not_evaluable_answers(clauses, reason):
    return {c["id"]: {"verdict": "not_evaluable", "rationale": reason} for c in clauses}


ALLOW_OUT_OF_SCOPE = True


def request_clauses(clauses):
    """The clause objects one judge_many() request carries: exactly what
    build_judge_pin() hashes, so the pin covers the questions the judge was
    actually sent."""
    return [{"id": c["id"], "check_id": c["check_id"], "claim": c["claim"],
             "never_out_of_scope": c.get("never_out_of_scope", False)} for c in clauses]


def judge_bundle(bundle, clauses, capsule_id, judge_model_id, backend=None):
    """The fail-closed decision tree: withheld bundle first (whatever
    --capsule-id says), then -- narrowed to one record or not -- a
    missing/undisclosed/empty record, then (only then) an actual judge call.
    Returns (answers, target_ids, actually_judged): target_ids is the sorted
    list of record capsule_ids the facts actually came from (empty on every
    fail-closed abstention path -- no model was ever consulted, so no claim
    from this call may carry a judge_pin_digest -- see run())."""
    if is_withheld(bundle):
        return not_evaluable_answers(clauses, REASON_PAYLOAD_WITHHELD), [], False

    if capsule_id:
        record, reason = resolve_target(bundle, capsule_id)
        if record is None:
            return not_evaluable_answers(clauses, reason), [], False
        facts = _bundle_disclosures(bundle).get(capsule_id) or None
        if facts is None:
            return not_evaluable_answers(clauses, REASON_PAYLOAD_WITHHELD), [], False
        facts_by_id = {capsule_id: facts}
    else:
        facts_by_id = disclosed_records(bundle)
        if not facts_by_id:
            return not_evaluable_answers(clauses, REASON_NOTHING_DISCLOSED), [], False

    target_ids = sorted(facts_by_id)
    request = {
        "clauses": request_clauses(clauses),
        "disclosed_facts": {"records": facts_by_id, "extensions": bundle.get("extensions") or {}},
        "judge_model_id": judge_model_id,
        "allow_out_of_scope": ALLOW_OUT_OF_SCOPE,
    }
    try:
        answers = jev_judge.judge_many(request, backend=backend)
    except jev_judge.JudgeError as e:
        raise JudgeBackendFailure(str(e))
    return answers, target_ids, True


def declared_input_refs(clauses):
    """The judge_pin.input_refs for a batch of clauses actually being judged
    together: the union of each clause's own `judge_input_refs` (packs/
    everyday-rules/pack-source.yaml, passed through by scripts/pack_compile.py
    onto the compiled clause) -- the normalized action fields (capsule-engine
    PR #96's own closed vocabulary) that clause's own judge prompt declares it
    reads. Sorted, deduplicated; empty when no clause in this batch declares
    one (select_clauses()'s own --rule-ids subsetting can produce this)."""
    refs = set()
    for c in clauses:
        refs.update(c.get("judge_input_refs") or ())
    return sorted(refs)


def build_judge_pin(judge_model_id, input_refs, clauses):
    """The judged-instrument pin (instrument_pin.build_pin) for a batch of
    disclosed_facts-mode rows: the model id this call used, the digest of the
    prompt the judge is sent for these clauses -- the instruction template plus
    each clause's compiled question (jev_judge.compiled_prompt_digest), never
    the evidence -- and of the answer schema it must return, input_refs
    (declared_input_refs() above -- never a record or capsule_id), and
    model_hosting (always "hosted" -- jev_judge.MODEL_HOSTING)."""
    prompt_template_hash = jev_judge.compiled_prompt_digest(
        request_clauses(clauses), ALLOW_OUT_OF_SCOPE, mode="disclosed_facts")
    schema_hash = jev_judge.answer_schema_digest()
    return instrument_pin.build_pin(
        judge_model_id, prompt_template_hash, schema_hash, input_refs, jev_judge.MODEL_HOSTING
    )


def run(pack, bundle, rule_ids, capsule_id, judge_model_id, generated_at, backend=None):
    """Everything between "have a loaded pack and bundle" and "have a Result v0
    document": pulled out of main() so a test can inject a mock backend without
    going through the CLI/JEV_JUDGE_BACKEND environment seam, the same way
    tests/test_jev_judge.py calls jev_judge.judge()/judge_many() directly. Raises
    BadInput/RollupError/EvidenceUnavailable/OSError for bad input, JudgeBackendFailure
    for a judge backend failure -- main() is the only place that catches them."""
    clauses = select_clauses(pack, rule_ids)
    # A pure function of the pack and this --rule-ids selection, independent of
    # the bundle: refused here, before the judge is ever consulted (never after
    # paying for a real call only to discard its answer) -- same fail-closed-
    # before-the-irreversible-step rule every other refusal in this module
    # follows.
    input_refs = declared_input_refs(clauses)
    if not input_refs:
        raise BadInput(
            f"no clause selected by rule_ids={rule_ids!r} declares judge_input_refs "
            f"(capsule-engine's own normalized action-field vocabulary for "
            f"judge_pin.input_refs) -- cannot seal a judge_pin for this call"
        )
    answers, target_ids, actually_judged = judge_bundle(bundle, clauses, capsule_id, judge_model_id, backend=backend)

    all_criteria = tuple(c["id"] for c in clauses)
    criterion_verdicts = {cid: answers[cid]["verdict"] for cid in all_criteria}
    tiers = {cid: "judged" for cid in all_criteria}
    rationales = {cid: answers[cid].get("rationale", "") for cid in all_criteria}
    rule_ids_by_clause = {c["id"]: c["rule_id"] for c in clauses if c.get("rule_id")}
    if actually_judged:
        # A fail-closed abstention cites only its reason (never a record it did
        # not actually read) and carries no judge_pin_digest: that field asserts
        # a named model actually produced this verdict, never sealed when no
        # model was ever consulted.
        report_digests = {cid: target_ids for cid in all_criteria}
        pin, pin_digest = build_judge_pin(judge_model_id, input_refs, clauses)
        judge_pin_digests = {cid: pin_digest for cid in all_criteria}
        judge_pins = {cid: pin for cid in all_criteria}
    else:
        report_digests, judge_pin_digests, judge_pins = {}, {}, {}

    document, _ = build_result_v0(
        case_id=bundle.get("root") or (target_ids[0] if target_ids else "unknown-bundle"),
        criterion_verdicts=criterion_verdicts,
        report_digests=report_digests,
        generated_at=generated_at,
        all_criteria=all_criteria,
        contract_ref=pack.get("contract_ref"),
        tiers=tiers,
        allow_out_of_scope=True,
        judge_pin_digests=judge_pin_digests,
        judge_pins=judge_pins,
        rule_ids=rule_ids_by_clause,
        case_scoped_ids=True,
    )
    for claim in document["claims"]:
        claim["rationale"] = rationales.get(claim["requirement_ref"], "")
    return document


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bundle", required=True, type=pathlib.Path)
    ap.add_argument("--pack", required=True, type=pathlib.Path, help="a compiled pack (compiled.json)")
    ap.add_argument("--generated-at", required=True, help="ISO-8601 timestamp sealed as the document's generated_at")
    ap.add_argument("--capsule-id", default=None,
                    help="narrow to one bundle record (optional; default: every disclosed record in the bundle)")
    ap.add_argument("--rule-ids", default=None, help="comma-separated rule_id subset to judge (default: every judged row)")
    ap.add_argument("--judge-model-id", default=None, help="defaults to the judge this script pins (jev_judge.PINNED_MODEL)")
    ap.add_argument("--out", type=pathlib.Path, default=None, help="write the Result v0 document here (default: stdout)")
    args = ap.parse_args(argv)

    judge_model_id = args.judge_model_id or jev_judge.PINNED_MODEL
    rule_ids = [r.strip() for r in args.rule_ids.split(",") if r.strip()] if args.rule_ids else None

    try:
        pack = load_pack(args.pack)
        bundle = load_bundle(args.bundle)
        document = run(pack, bundle, rule_ids, args.capsule_id, judge_model_id, args.generated_at)
    except (BadInput, RollupError, EvidenceUnavailable, OSError) as e:
        print(f"bad input: {e}", file=sys.stderr)
        return 1
    except JudgeBackendFailure as e:
        print(f"judge backend failure: {e}", file=sys.stderr)
        return 2

    out_text = json.dumps(document, indent=2) + "\n"
    if args.out:
        args.out.write_text(out_text)
    else:
        sys.stdout.write(out_text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
