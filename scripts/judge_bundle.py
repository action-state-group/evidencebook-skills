#!/usr/bin/env python3
"""Judge a whole evidence-bundle/v2 file against a compiled pack's rows
(packs/everyday-rules/pack-source.yaml, compiled by scripts/pack_compile.py),
and write one Evidence Result v0 document plus its judge sidecar.

    python3 scripts/judge_bundle.py --bundle BUNDLE.json --pack COMPILED.json \\
        --generated-at 2026-10-08T00:00:00Z --out RESULT.json [--capsule-id ID] \\
        [--rule-ids 8,9,26] [--judge-model-id jev-1.13.0]

writes RESULT.json and, next to it, RESULT.judge.json (see "Judge sidecar"
below). Without --out the Result goes to stdout and --sidecar PATH is required.

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

  contradictory        completeness that is not a mapping, an unknown
  completeness         records_mode/payloads_mode, or payloads_mode "none"
                       beside a populated disclosures map: refused as bad
                       input (exit 1) before anything is judged.
  WITHHELD bundle      completeness.payloads_mode == "none" AND no
                       "disclosures" key at all (capsule-anchor's countersign
                       `parse_bundle` rule, reused verbatim). Checked first,
                       whatever --capsule-id says. Every in-scope row:
                       not_evaluable, reason "payload withheld". No judge call
                       is made at all.
  nothing disclosed    (whole-bundle mode only) no record in the bundle has a
                       non-empty entry in `disclosures` -- a
                       selectively-disclosed bundle that disclosed nothing
                       this script can use, or every disclosed entry being
                       `{}`. Every in-scope row: not_evaluable, reason "no
                       disclosed record in this bundle". Distinct from the
                       bundle being globally WITHHELD above.
  record not found     (--capsule-id narrowing only) the named capsule_id is
                       not in `records[]`. If it IS listed in
                       completeness.missing[], the reason is "record declared
                       missing"; otherwise "record not found in bundle".
                       Every in-scope row: not_evaluable, citing the root
                       record -- never an inferred verdict.
  declared incomplete  the bundle says records are missing
                       (completeness.records_mode "declared_incomplete", or a
                       non-empty completeness.missing): never judged as if it
                       were whole, narrowed or not. Every in-scope row:
                       not_evaluable, reason "bundle declares missing
                       records", citing abstention_citation()'s record.
                       Checked after the two narrowing reasons above for a
                       target that is itself absent.
  payload withheld     (--capsule-id narrowing only) the named record exists
                       in `records[]` but has no entry (or an empty one) in
                       `disclosures`. Every in-scope row: not_evaluable,
                       reason "payload withheld".
  nothing to cite      the bundle holds neither the --capsule-id record nor
                       its root record (an empty bundle among them): refused
                       as bad input, since every Result claim cites at least
                       one record (agent-action-capsule#353).

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
that specific claim was actually judged from. The judged selection
(`judged_selection`: the rows sent, in order, and which came back out_of_scope
-- claims[] omits those) is recorded in the judge sidecar, not the Result, so a
reader holding the pack, the Result and its sidecar recomputes the pin's
prompt_template_hash and input_refs without being told which rows were asked.
A fail-closed abstention
(withheld/missing/undisclosed, above) carries no pin: no model was ever
consulted, so no judge identity is sealed on it -- only the reason. Its
evidence[] cites only the record the run was asked about: the --capsule-id
record when the bundle holds it, otherwise the bundle's root record, since
every claim cites at least one record (agent-action-capsule#353). A bundle
holding neither is refused, before the judge is consulted. A call
whose selected clauses declare no normalized action field at all cannot
seal an honest pin; run() refuses it as a BadInput, before the judge is
ever consulted, rather than invent a field name or omit the pin silently
(see build_judge_pin()).

No forbidden vocabulary: every string this script emits (rationale, reasons) is
either the judge's own answer or one of the fixed reason strings above -- checked
by tests/test_forbidden_vocabulary.py against vocab/forbidden-vocabulary.yaml.

Judge sidecar: the Result document carries only the top-level keys of the
evidence-result-v0 schema's EvidenceResult (result_version, generated_at,
claims, aggregate, view). What the judge run adds beside it goes in a sidecar
file, by default `<result>.judge.json` next to the Result (RESULT.json ->
RESULT.judge.json):

    {"spec_version": "judge-sidecar/v1",
     "result_sha256": "<sha256 hex of the exact Result bytes written>",
     "judged_selection": {"rule_ids": [...], "requirement_refs": [...],
                          "out_of_scope": [...], "allow_out_of_scope": true}}

spec_version names the format and its version in one value, as this repo's
other formats do (presentation/v1, evaluation-report/v1); a reader refuses one
it does not know. The sidecar cites its Result by digest, never by path: a
sidecar whose result_sha256 does not match the Result in hand is not that
Result's sidecar.
judged_selection.requirement_refs and .out_of_scope hold the compiled pack's
clause ids. Recomputing the pin's prompt_template_hash also needs
scripts/judges/jev_judge.py at the revision that produced the Result: the hash
folds in the judge's instruction template digest, which covers that file's own
source. An abstention document (every row not_evaluable, no judge call) gets a
sidecar too: its judged_selection is the selection asked for, not rows sent,
its out_of_scope is empty, and no claim carries a judge_pin. The sidecar is
staged before the Result is written and moved into place after it, so a
failed write never leaves a Result without its sidecar.

Exit codes: 0 on a successful run (whatever the verdicts), 1 on a malformed
request (the "bad input" cases above), 2 on a judge backend failure, 3 when the
judge answered out_of_scope on every selected row (no claim to make: a Result v0
document needs at least one; the judged selection goes to stderr). Never a
guessed verdict; never a partial document on stdout.

    JEV_JUDGE_BACKEND=mock python3 scripts/judge_bundle.py --bundle ... --pack ...
"""
import argparse
import hashlib
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "judges"))

from capsulectl_calls import EvidenceUnavailable  # noqa: E402
import instrument_pin  # noqa: E402
import jev_judge  # noqa: E402
from result_v0 import build_result_v0, report_title  # noqa: E402
from rollup import RollupError  # noqa: E402

BUNDLE_KIND = "evidence-bundle/v2"
# The judge sidecar's format id and version (see "Judge sidecar" above). A
# public format: any change to its keys or their meaning is a new version.
JUDGE_SIDECAR_VERSION = "judge-sidecar/v1"

REASON_PAYLOAD_WITHHELD = "payload withheld"
REASON_RECORD_DECLARED_MISSING = "record declared missing"
REASON_RECORD_NOT_FOUND = "record not found in bundle"
REASON_NOTHING_DISCLOSED = "no disclosed record in this bundle"
REASON_NOT_SELECTED = "not judged in this run: outside the --rule-ids selection"
REASON_BUNDLE_INCOMPLETE = "bundle declares missing records"

RECORDS_MODES = ("complete", "declared_incomplete")
PAYLOADS_MODES = ("none", "selected", "all")


class BadInput(Exception):
    """Malformed input -- refused before anything is judged."""


class JudgeBackendFailure(Exception):
    """The judge backend itself failed (not a malformed request)."""


class NothingApplied(Exception):
    """The judge answered out_of_scope on every selected row: there is no claim
    to put in a Result v0 document (its claims[] needs at least one). The
    judge's own answer, not bad input; `selection` is judged_selection()."""

    def __init__(self, selection):
        super().__init__(f"every selected row was judged out_of_scope: {selection['requirement_refs']}")
        self.selection = selection


def load_json(path, what):
    try:
        return json.loads(pathlib.Path(path).read_text())
    except OSError as e:
        raise BadInput(f"cannot read {what} {path!r}: {e}")
    except json.JSONDecodeError as e:
        raise BadInput(f"{what} {path!r} is not valid JSON: {e}")


def check_pack(pack, where):
    """Every clause this script will read carries the fields it reads: an id, a
    claim and a check_id (request_clauses() sends all three to the judge)."""
    if not isinstance(pack, dict) or not isinstance(pack.get("clauses"), list) or not pack["clauses"]:
        raise BadInput(f"pack {where!r} carries no clauses -- not a compiled pack")
    for clause in pack["clauses"]:
        if not isinstance(clause, dict) or not clause.get("id") or not clause.get("claim"):
            raise BadInput(f"pack {where!r} carries a clause with no id/claim: {clause!r}")
        if not isinstance(clause.get("check_id"), str) or not clause["check_id"]:
            raise BadInput(f"pack {where!r} carries a clause with no check_id: {clause['id']!r}")
    return pack


def load_pack(path):
    return check_pack(load_json(path, "pack"), path)


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


def completeness_of(bundle):
    """bundle.completeness, checked: a mapping (absent reads as {}), records_mode
    and payloads_mode each absent or a known value, missing absent or a list,
    and never payloads_mode "none" beside a populated disclosures map -- a
    bundle that says it disclosed no payloads and then discloses some
    contradicts itself, and which half to believe is not this script's call."""
    completeness = bundle.get("completeness")
    if completeness is None:
        completeness = {}
    if not isinstance(completeness, dict):
        raise BadInput(f"bundle.completeness must be a mapping, got {type(completeness).__name__}")
    for key, known in (("records_mode", RECORDS_MODES), ("payloads_mode", PAYLOADS_MODES)):
        if key in completeness and completeness[key] not in known:
            raise BadInput(f"bundle.completeness.{key} {completeness[key]!r} is not one of {list(known)}")
    if "missing" in completeness and not isinstance(completeness["missing"], list):
        raise BadInput("bundle.completeness.missing must be a list")
    if completeness.get("payloads_mode") == "none" and bundle.get("disclosures"):
        raise BadInput("bundle.completeness.payloads_mode is \"none\" but bundle.disclosures discloses "
                       "payloads: the bundle contradicts itself")
    return completeness


def declares_incomplete(bundle):
    """True when the bundle itself says records are missing: records_mode
    "declared_incomplete", or a non-empty completeness.missing. Such a bundle is
    never judged as if it were whole -- a missing record may be exactly the one
    a rule turns on."""
    completeness = completeness_of(bundle)
    return completeness.get("records_mode") == "declared_incomplete" or bool(completeness.get("missing"))


def is_withheld(bundle):
    """capsule-anchor's countersign `parse_bundle` rule, reused verbatim: a bundle
    is WITHHELD when completeness.payloads_mode is "none" and it carries no
    `disclosures` key at all (not merely an empty one -- key absence is the
    signal)."""
    return completeness_of(bundle).get("payloads_mode") == "none" and "disclosures" not in bundle


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
    missing = completeness_of(bundle).get("missing") or []
    reason = REASON_RECORD_DECLARED_MISSING if capsule_id in missing else REASON_RECORD_NOT_FOUND
    return None, reason


def not_evaluable_answers(clauses, reason):
    return {c["id"]: {"verdict": "not_evaluable", "rationale": reason} for c in clauses}


ALLOW_OUT_OF_SCOPE = True


def abstention_citation(bundle, capsule_id):
    """The one record a not_evaluable claim without a judged read cites: every
    Result claim cites at least one record (agent-action-capsule#353). A
    --capsule-id run cites the record it was asked about when the bundle holds
    it; otherwise the claim cites the bundle's root record. None when the bundle
    holds neither, so there is nothing honest to cite."""
    held = {r.get("capsule_id") for r in _bundle_records(bundle) if isinstance(r, dict)}
    if capsule_id and capsule_id in held:
        return capsule_id
    root = bundle.get("root")
    return root if isinstance(root, str) and root in held else None


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

    if declares_incomplete(bundle):
        return not_evaluable_answers(clauses, REASON_BUNDLE_INCOMPLETE), [], False

    if capsule_id:
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
    """The Result v0 document alone; run_judged() also returns the judged
    selection that goes in the judge sidecar."""
    document, _selection = run_judged(pack, bundle, rule_ids, capsule_id, judge_model_id, generated_at,
                                      backend=backend)
    return document


def run_judged(pack, bundle, rule_ids, capsule_id, judge_model_id, generated_at, backend=None):
    """Everything between "have a loaded pack and bundle" and "have a Result v0
    document and its judged selection" (returned as a pair; the selection goes
    in the judge sidecar, never on the document): pulled out of main() so a
    test can inject a mock backend without
    going through the CLI/JEV_JUDGE_BACKEND environment seam, the same way
    tests/test_jev_judge.py calls jev_judge.judge()/judge_many() directly. Raises
    BadInput/RollupError/EvidenceUnavailable/OSError for bad input, JudgeBackendFailure
    for a judge backend failure -- main() is the only place that catches them."""
    check_pack(pack, pack.get("contract_ref") if isinstance(pack, dict) else None)
    completeness_of(bundle)
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
    # A --rule-ids run judges some of the pack's rules. Every judged rule it
    # did NOT select still gets a claim, not_evaluable with its reason: the
    # outcome card renders against the whole pack's presentation and reads a
    # rule with no claim as not_applicable, so a one-rule run would otherwise
    # read as the whole pack passing. Selected clauses come first, in the
    # order asked for; the rest follow in pack order.
    selected_ids = [c["id"] for c in clauses]
    unselected = [c for c in select_clauses(pack, None) if c["id"] not in set(selected_ids)]
    # Those claims, and any fail-closed abstention, cite abstention_citation():
    # checked here, before the judge (and its cost) is ever consulted.
    citation = abstention_citation(bundle, capsule_id)
    no_citation = BadInput("the bundle holds neither the --capsule-id record nor its root record, "
                           "so a not_evaluable claim has no record to cite")
    if unselected and citation is None:
        raise no_citation
    # A pin over a stand-in backend's answer names the stand-in, never only the
    # operator's (real-looking) model id: jev_judge.sealed_model_id().
    judge_model_id = jev_judge.sealed_model_id(judge_model_id, backend)
    answers, target_ids, actually_judged = judge_bundle(bundle, clauses, capsule_id, judge_model_id, backend=backend)
    if not actually_judged and citation is None:
        raise no_citation
    answers = dict(answers)
    answers.update(not_evaluable_answers(unselected, REASON_NOT_SELECTED))
    all_clauses = list(clauses) + unselected

    all_criteria = tuple(c["id"] for c in all_clauses)
    criterion_verdicts = {cid: answers[cid]["verdict"] for cid in all_criteria}
    if actually_judged and all(criterion_verdicts[cid] == "out_of_scope" for cid in selected_ids):
        # Known only once the judge has answered -- no row of this pack is
        # never_out_of_scope, so no selection can rule it out beforehand. Only
        # the selected rows count: the not_evaluable claims for rules outside
        # --rule-ids say nothing was judged there, not that anything applied.
        raise NothingApplied(judged_selection(clauses, criterion_verdicts))
    tiers = {cid: "judged" for cid in all_criteria}
    rationales = {cid: answers[cid].get("rationale", "") for cid in all_criteria}
    rule_ids_by_clause = {c["id"]: c["rule_id"] for c in all_clauses if c.get("rule_id")}
    # Every claim cites at least one record (Evidence Result v0 section 1,
    # agent-action-capsule#353). A fail-closed abstention, and a rule outside
    # the --rule-ids selection, cites the record the run was asked about
    # (abstention_citation), which claims nothing about records the judge
    # never read. It carries no judge_pin_digest: that field asserts a named
    # model actually produced this verdict, never sealed when no model was
    # consulted. Only the selected clauses of a judged run cite the records
    # they read, and carry the pin.
    abstained = [cid for cid in all_criteria if not (actually_judged and cid in selected_ids)]
    report_digests = {cid: [citation] for cid in abstained}
    if actually_judged:
        report_digests.update({cid: target_ids for cid in selected_ids})
        pin, pin_digest = build_judge_pin(judge_model_id, input_refs, clauses)
        judge_pin_digests = {cid: pin_digest for cid in selected_ids}
        judge_pins = {cid: pin for cid in selected_ids}
    else:
        judge_pin_digests, judge_pins = {}, {}

    # The case id scopes every claim id (<case_id>::<criterion>). A run
    # narrowed by --capsule-id is scoped to that record too, so two narrowed
    # runs on one bundle never share claim ids and their results merge.
    root = bundle.get("root") or (target_ids[0] if target_ids else "unknown-bundle")
    case_id = f"{root}/{capsule_id}" if capsule_id else root

    document, _ = build_result_v0(
        case_id=case_id,
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
    document["view"]["title"] = report_title(pack, case_id)
    return document, judged_selection(clauses, criterion_verdicts)


def judged_selection(clauses, criterion_verdicts):
    """What this call put in front of the judge, recorded in the judge sidecar: the
    selected rows (rule_ids and requirement_refs, in the order sent) and which
    of them came back out_of_scope. claims[] omits an out_of_scope row (Result
    v0 has no such verdict), yet the pin's prompt_template_hash and input_refs
    cover every row sent; with this, a reader holding the pack, the document and
    its sidecar recomputes both (select the pack's clauses by requirement_ref,
    then jev_judge.compiled_prompt_digest(request_clauses(...),
    allow_out_of_scope, "disclosed_facts") and declared_input_refs(...)). Not a
    key of the Result document: evidence-result-v0's EvidenceResult admits no
    key beyond its own (judge_sidecar())."""
    return {
        "rule_ids": [c.get("rule_id") for c in clauses],
        "requirement_refs": [c["id"] for c in clauses],
        "out_of_scope": [c["id"] for c in clauses if criterion_verdicts.get(c["id"]) == "out_of_scope"],
        "allow_out_of_scope": ALLOW_OUT_OF_SCOPE,
    }


def sidecar_path_for(result_path):
    """`<result>.judge.json` next to the Result: RESULT.json -> RESULT.judge.json,
    any other name gets .judge.json appended."""
    name = result_path.name
    stem = name[:-len(".json")] if name.endswith(".json") else name
    return result_path.with_name(stem + ".judge.json")


def judge_sidecar(result_bytes, selection):
    """The judge sidecar for one Result: what the run judged, citing the Result
    by the sha256 of the exact bytes written."""
    return {
        "spec_version": JUDGE_SIDECAR_VERSION,
        "result_sha256": hashlib.sha256(result_bytes).hexdigest(),
        "judged_selection": selection,
    }


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bundle", required=True, type=pathlib.Path)
    ap.add_argument("--pack", required=True, type=pathlib.Path, help="a compiled pack (compiled.json)")
    ap.add_argument("--generated-at", required=True, help="ISO-8601 timestamp sealed as the document's generated_at")
    ap.add_argument("--capsule-id", default=None,
                    help="narrow to one bundle record (optional; default: every disclosed record in the bundle); "
                         "claim ids are then scoped to <root>/<capsule-id>, so narrowed runs on one bundle merge")
    ap.add_argument("--rule-ids", default=None,
                    help="comma-separated rule_id subset to judge (default: every judged row); the pack's other "
                         "judged rules are claimed not_evaluable, so a partial run never reads as a full pass")
    ap.add_argument("--judge-model-id", default=None, help="defaults to the judge this script pins (jev_judge.PINNED_MODEL)")
    ap.add_argument("--out", type=pathlib.Path, default=None, help="write the Result v0 document here (default: stdout)")
    ap.add_argument("--sidecar", type=pathlib.Path, default=None,
                    help="write the judge sidecar here (default: <out>.judge.json next to --out; "
                         "required when the Result goes to stdout)")
    args = ap.parse_args(argv)
    if args.out is None and args.sidecar is None:
        # Refused before the judge is consulted: a Result on stdout with no
        # sidecar would drop the judged selection the pin is recomputed from.
        print("bad input: the Result goes to stdout, so --sidecar PATH is required for its judge sidecar",
              file=sys.stderr)
        return 1
    sidecar_path = args.sidecar or sidecar_path_for(args.out)
    # Both refused before the judge is consulted: a sidecar written over its own
    # Result would leave a sidecar citing bytes that no longer exist, and a
    # missing directory would fail only after the Result was written.
    if args.out is not None and sidecar_path.resolve() == args.out.resolve():
        print("bad input: --sidecar names the same file as --out; the sidecar would overwrite its Result",
              file=sys.stderr)
        return 1
    for path in ([args.out] if args.out is not None else []) + [sidecar_path]:
        if not path.resolve().parent.is_dir():
            print(f"bad input: no directory to write {path} into", file=sys.stderr)
            return 1

    judge_model_id = args.judge_model_id or jev_judge.PINNED_MODEL
    rule_ids = [r.strip() for r in args.rule_ids.split(",") if r.strip()] if args.rule_ids else None

    try:
        pack = load_pack(args.pack)
        bundle = load_bundle(args.bundle)
        document, selection = run_judged(pack, bundle, rule_ids, args.capsule_id, judge_model_id,
                                         args.generated_at)
    except jev_judge.JudgeError as e:  # e.g. an unknown JEV_JUDGE_BACKEND, before any call
        print(f"judge backend failure: {e}", file=sys.stderr)
        return 2
    except (BadInput, RollupError, EvidenceUnavailable, OSError) as e:
        print(f"bad input: {e}", file=sys.stderr)
        return 1
    except JudgeBackendFailure as e:
        print(f"judge backend failure: {e}", file=sys.stderr)
        return 2
    except NothingApplied as e:
        print(f"nothing applied: {e}", file=sys.stderr)
        print(json.dumps({"judged_selection": e.selection}, indent=2), file=sys.stderr)
        return 3

    out_text = json.dumps(document, indent=2) + "\n"
    out_bytes = out_text.encode("utf-8")
    sidecar_text = json.dumps(judge_sidecar(out_bytes, selection), indent=2) + "\n"
    # The sidecar is staged beside its final path before the Result goes out,
    # so a write failure never leaves a Result without its sidecar on disk.
    staged = sidecar_path.with_name(f".{sidecar_path.name}.{os.getpid()}.tmp")
    try:
        staged.write_text(sidecar_text)
        if args.out:
            args.out.write_bytes(out_bytes)
        else:
            sys.stdout.write(out_text)
            sys.stdout.flush()
        os.replace(staged, sidecar_path)
    except OSError as e:
        staged.unlink(missing_ok=True)
        print(f"bad input: could not write the Result and its sidecar: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
