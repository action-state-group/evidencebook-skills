#!/usr/bin/env python3
"""A `scope.kind: live` pack source: validation, the Evidence Contract it
compiles to, and the projection to capsule-engine's pack definition.

SEAMS ruling 1: one pack format. A pack source declares `scope.kind`, `live`
(rules a guard enforces on an agent's action before it runs, capsule-engine's
`pack.yaml` packs) or `after_the_fact` (outcome and obligation rows judged over a
finished session, the rest of scripts/pack_compile.py). Absent means
`after_the_fact`, so no existing pack changes.

A live source states what capsule-engine's `pack.yaml` states, under the same
key names, and the engine's loader (`packs/loader.py` `load_pack_dir`) reads the
same file:

  pack_id, pack_version        pack_version is the contract's version; it is
                               not in the engine definition (pack_id carries it)
  obligations[]                id, statement, check, selector, default_disposition
                               (DO | ASK | NEVER, optional), re_derivability_grade,
                               measurability, evidence_instrument, mode, and for
                               `mode: judged` a judge_pin in place of a check;
                               and, for the contract only, requirement_tier
  action_semantics[]           action_type, action_class, required_fields,
                               optional_fields, field_aliases
  constraints[]                either a cited wicket: wicket_ref, digest, scope,
                               plus `check`, the check the cited wicket
                               implements, which the engine reads from the
                               wicket definition and a source has no catalog to
                               read it from; or an inline wicket definition:
                               wicket_id, check, config, semantics, scope
  folds[]                      either a cited fold (fold_ref, digest) or `file`,
                               a fold definition file relative to the source's
                               directory
  outcomes[]                   capsule-engine's Evidence Contract entries
                               (statement, evidence_rule, the verdict pair, ...)
  profiles[], proposers[],     as in pack.yaml
  scope_census, holds_integration, taxonomy
  fixtures, bootstrap          as in pack.yaml; not in the contract or the digest

A pack that declares outcomes may leave the forward triple (obligations,
action_semantics, constraints) and folds empty or absent, as the engine allows;
one that declares none needs all four.

Two outputs, because Evidence Contract v0 is a closed schema that names no check,
disposition, wicket, fold, profile or proposer:

  - `from_live` -> the contract (id = pack_id, version = pack_version). One
    requirement per obligation: its statement, and an evidence_rule stating how
    it is measured (the check, selector and disposition, or the pinned judge) in
    words. Then one per outcome, in the engine's own Evidence Contract shape
    (`EvidenceContract.canonical_dict()`) with its profile and tier stated even
    at their defaults (`outcome`, `informational`), since a contract reader
    takes an absent tier as must_have. `contract validate` accepts it.
  - `project` -> the engine's canonical pack definition and its
    `definition_digest`, computed from the source exactly as capsule-engine's
    `PackDefinition.canonical_dict()` / `definition_digest()` and
    go/pack/pack.go do (SHA-256 over the JCS bytes). An inline wicket or a fold
    file is digested as the engine digests it (`WicketDefinition` /
    `FoldDefinition.canonical_dict()`), from the same source the engine reads,
    so there is no second copy of its digest to drift. A cited wicket or fold
    digest is taken as cited; the engine loader refuses a pack whose cited
    definition has changed, so a wrong one fails there, not here.

Checks that need the engine's registries or catalogs stay with its loader, which
refuses a wrong pack: the registered check names, retired definitions, the
taxonomy pin, a caps constraint's scope against its fold, a judge pin's input
fields, and a fold's path grammar. This module checks shape and the closed
vocabularies that decide the digest or the contract. It is stricter than the
engine in two ways: it refuses a key the engine would ignore, and a fold file
outside the source's directory, which the engine would read.
"""
import hashlib
import json
import pathlib
import re

import rfc8785
import yaml

# `admission` (an admission pack, #51) is validated by scripts/admission_pack.py.
SCOPE_KINDS = ("live", "after_the_fact", "admission")
DEFAULT_SCOPE_KIND = "after_the_fact"

# capsule-engine's closed sets (packs/schema.py, compiler/vocabulary.py,
# compiler/effect_model.py, folds/definition.py), copied so a source outside
# them is refused here rather than projected to a pack the engine will not load.
DISPOSITIONS = ("DO", "ASK", "NEVER")
MEASURABILITY = ("measured", "declared_not_measured")
RE_DERIVABILITY_GRADES = ("pure_replay", "ledger_state_dependent")
REQUIREMENT_TIERS = ("must_have", "informational")
MODES = ("structural", "value", "judged", "fold_counterparty", "fold_rollup", "fold_agent", "fold_cohort")
TOPOLOGY_INVARIANT_MODES = ("structural", "value", "fold_rollup")
JUDGE_HOSTING = ("hosted", "self_hosted")
FORWARD_VERDICTS = ("DETERMINISTIC", "UNAVAILABLE-STATE-REQUIRED", "UNAVAILABLE-MODEL-REQUIRED", "REFUSED")
BACKWARD_VERDICTS = ("DETERMINISTIC", "WITH-INSTRUMENTATION", "MODEL-ASSISTED", "MANUAL", "REFUSED")
REFUSAL_REASON_CODES = ("agent_caused_resolution_undecomposable", "subjective_state_unattestable",
                        "unbounded_goal_unmonitorable")
# effect_claim -> the (forward, backward, refusal_reason_code) it must compile to,
# or None where it constrains nothing (compile_effect_claim).
EFFECT_CLAIMS = {
    "agent.caused_resolution": ("REFUSED", "REFUSED", "agent_caused_resolution_undecomposable"),
    "recommendation.acted_on": None,
    "resolution.followed_action": None,
}
EVIDENCE_PROFILES = ("outcome", "obligation", "process", "quality", "human_role", "attribution", "settlement")
EPISTEMIC_TYPES = ("observed_event", "system_of_record_fact", "producer_claim", "human_report",
                   "semantic_judgment", "derived_metric", "adjudication", "obligation_reference")
PROFILE_IDS = ("p1_external_serve", "p2_internal_assist", "p3_mediated", "p4_agent_to_agent")
PROPOSER_STATUSES = ("planned",)
ERASURE_CLASSES = ("commitment-ok", "preimage")
FIELD_REDUCERS = ("sum", "min", "max", "last")
REDUCERS = FIELD_REDUCERS + ("count",)
FILTER_OPS = ("eq", "ne", "in", "not_in", "prefix", "gt", "gte", "lt", "lte")
DERIVATION_CLASSES = ("deterministic", "model_assisted")

LIVE_KEYS = {"scope", "pack_id", "pack_version", "source", "obligations", "action_semantics",
             "constraints", "folds", "outcomes", "profiles", "proposers", "scope_census",
             "holds_integration", "taxonomy", "fixtures", "bootstrap"}
OBLIGATION_KEYS = {"id", "statement", "check", "selector", "default_disposition", "re_derivability_grade",
                   "measurability", "evidence_instrument", "mode", "judge_pin", "requirement_tier"}
JUDGE_PIN_KEYS = {"model_id", "prompt_template_hash", "schema_hash", "input_refs", "model_hosting", "model_digest"}
OUTCOME_KEYS = {"id", "statement", "evidence_rule", "forward_verdict", "backward_verdict", "window",
                "effect_claim", "refusal_reason_code", "re_derivability_grade", "declared_by",
                "evidence_mapping_by", "required_assurance_grade", "exposure_denominator_ref",
                "retention_check", "measurability", "evidence_instrument", "tier", "mode", "clause_ref",
                "clause", "profile", "epistemic_type"}
# Optional outcome strings, emitted when set (EvidenceContract.canonical_dict).
OUTCOME_TEXT_KEYS = ("effect_claim", "refusal_reason_code", "re_derivability_grade", "declared_by",
                     "evidence_mapping_by", "required_assurance_grade", "exposure_denominator_ref",
                     "retention_check")
CLAUSE_KEYS = {"instrument", "article", "as_amended_by", "paragraph", "jurisdiction", "text_snapshot_digest",
               "effective_from", "source_url", "contested"}
FOLD_KEYS = {"fold_id", "reads", "filter", "key", "window", "reduce", "emit", "derivation_class", "reversal"}

# capsule-engine's packs/schema.py PACK_ID_RE and HOLDS_INTEGRATION_VALUES: a source
# outside them is a pack the engine refuses to load, so it gets no digest here.
PACK_ID_RE = re.compile(r"^[a-z][a-z0-9_]*/[a-z][a-z0-9_]*(-[a-z0-9_]+)*/\d+\.\d+\.\d+$")
HOLDS_INTEGRATION_VALUES = ("none", "stubbed", "built")
# guards/wickets/definition.py WICKET_ID_RE and folds/definition.py FOLD_ID_RE.
DEFINITION_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*/\d+\.\d+\.\d+$")
# agent_action_capsule.canonical: a digested integer stays within the IEEE-754
# safe range, and a float is never digested.
MAX_SAFE_INTEGER = 2 ** 53 - 1

_HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")
_ISO_DATE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")


def scope_kind(source):
    """The source's scope kind, `after_the_fact` when it declares none. A value
    outside SCOPE_KINDS is returned as is, for validate_scope to refuse."""
    scope = source.get("scope") if isinstance(source, dict) else None
    if isinstance(scope, dict) and "kind" in scope:
        return scope["kind"]
    return DEFAULT_SCOPE_KIND


def is_live(source):
    return scope_kind(source) == "live"


def validate_scope(source):
    """Issues with the `scope` block, for any pack source."""
    if not isinstance(source, dict) or "scope" not in source:
        return []
    scope = source["scope"]
    if not isinstance(scope, dict):
        return ["scope must be a mapping with a kind"]
    issues = [f"scope.{k} is not a known scope field (only kind)" for k in scope if k != "kind"]
    kind = scope.get("kind")
    if kind not in SCOPE_KINDS:
        issues.append(f"scope.kind {kind!r} must be one of {list(SCOPE_KINDS)}")
    return issues


def _nonempty(v):
    return isinstance(v, str) and bool(v.strip())


def _str_list(v):
    return isinstance(v, list) and all(_nonempty(x) for x in v)


def _named(prefix, i, row, key):
    return f"{prefix}[{i}]" + (f" ({row[key]!r})" if isinstance(row, dict) and _nonempty(row.get(key)) else "")


def _unknown_keys(where, row, known, what, issues):
    for k in sorted(set(row) - known, key=str):
        issues.append(f"{where}.{k} is not {what}")


def _validate_instrument(where, inst, issues):
    if not ((isinstance(inst, dict) and inst.get("kind") == "structured_field" and _nonempty(inst.get("field"))
             and set(inst) == {"kind", "field"})
            or (isinstance(inst, dict) and inst.get("kind") == "tool_call_name" and _nonempty(inst.get("name"))
                and set(inst) == {"kind", "name"})):
        issues.append(f"{where}.evidence_instrument must be kind structured_field with a field, "
                      "or kind tool_call_name with a name")


def _validate_judge_pin(where, pin, grade, issues):
    where = f"{where}.judge_pin"
    if not isinstance(pin, dict):
        issues.append(f"{where} must be a mapping")
        return
    _unknown_keys(where, pin, JUDGE_PIN_KEYS, "a judge_pin field", issues)
    if not _nonempty(pin.get("model_id")):
        issues.append(f"{where}.model_id must be a non-empty string")
    for k in ("prompt_template_hash", "schema_hash"):
        if not (isinstance(pin.get(k), str) and _HEX64.match(pin[k])):
            issues.append(f"{where}.{k} must be 64 lowercase hex characters")
    refs = pin.get("input_refs")
    if not (_str_list(refs) and refs and len(set(refs)) == len(refs)):
        issues.append(f"{where}.input_refs must be a non-empty list of distinct normalized action fields")
    hosting = pin.get("model_hosting")
    if hosting not in JUDGE_HOSTING:
        issues.append(f"{where}.model_hosting {hosting!r} must be one of {list(JUDGE_HOSTING)}")
    if "model_digest" in pin:
        digest = pin["model_digest"]
        if not (isinstance(digest, str) and _HEX64.match(digest)) or digest == "0" * 64:
            issues.append(f"{where}.model_digest must be 64 lowercase hex characters, not all zeros; "
                          "omit it when there is no digest")
        elif hosting == "hosted":
            issues.append(f"{where} carries model_digest with model_hosting: hosted")
    if grade == "pure_replay" and (hosting == "hosted" or "model_digest" not in pin):
        issues.append(f"{where}: re_derivability_grade pure_replay needs a self_hosted judge with a model_digest")


def _validate_obligation(i, o, checks, selectors, issues):
    where = _named("obligations", i, o, "id")
    if not isinstance(o, dict):
        issues.append(f"{where} must be a mapping")
        return
    _unknown_keys(where, o, OBLIGATION_KEYS, "a live obligation field", issues)
    for k in ("id", "statement"):
        if not _nonempty(o.get(k)):
            issues.append(f"{where}.{k} must be a non-empty string")
    disposition = o.get("default_disposition")
    if "default_disposition" in o and disposition not in DISPOSITIONS:
        issues.append(f"{where}.default_disposition {disposition!r} must be one of {list(DISPOSITIONS)}")
    grade = o.get("re_derivability_grade")
    if grade is not None and grade not in RE_DERIVABILITY_GRADES:
        issues.append(f"{where}.re_derivability_grade {grade!r} must be one of {list(RE_DERIVABILITY_GRADES)}")
    tier = o.get("requirement_tier", "must_have")
    if tier not in REQUIREMENT_TIERS:
        issues.append(f"{where}.requirement_tier {tier!r} must be one of {list(REQUIREMENT_TIERS)}")
    mode = o.get("mode", "structural")
    if mode not in MODES:
        issues.append(f"{where}.mode {mode!r} must be one of {list(MODES)}")
    measurability = o.get("measurability", "measured")
    if measurability not in MEASURABILITY:
        issues.append(f"{where}.measurability {measurability!r} must be one of {list(MEASURABILITY)}")
        return
    if mode == "judged":
        # Measured by the judge its pin names, never by a check.
        for k in ("check", "selector", "evidence_instrument"):
            if k in o:
                issues.append(f"{where} is mode: judged and also names {k}; the judge_pin measures it")
        if measurability != "measured":
            issues.append(f"{where} is mode: judged and cannot be declared_not_measured")
        if disposition == "NEVER":
            issues.append(f"{where} is mode: judged with default_disposition NEVER; a judged verdict may ASK, never NEVER")
        if "judge_pin" not in o:
            issues.append(f"{where} is mode: judged but carries no judge_pin")
        else:
            _validate_judge_pin(where, o["judge_pin"], grade, issues)
        return
    if "judge_pin" in o:
        issues.append(f"{where} carries a judge_pin but is not mode: judged")
    if measurability == "measured":
        if "evidence_instrument" in o:
            issues.append(f"{where} is measured by its check and also names an evidence_instrument")
        check = o.get("check")
        if not _nonempty(check):
            issues.append(f"{where}.check must be a non-empty string")
        elif check not in checks:
            issues.append(f"{where}.check {check!r} has no matching constraint")
        if "selector" in o and not _nonempty(o["selector"]):
            issues.append(f"{where}.selector must be a non-empty string")
        elif _nonempty(check) and check in selectors:
            # An inline wicket states its selectors; a cited one's are the engine's to check.
            named = selectors[check]
            if not named and "selector" in o:
                issues.append(f"{where}.selector {o['selector']!r}, but check {check!r} has no selectors")
            elif named and o.get("selector") not in named:
                issues.append(f"{where} cites check {check!r}, so it must name one of its selectors {sorted(named)}")
    else:
        for k in ("check", "selector"):
            if k in o:
                issues.append(f"{where} declares measurability=declared_not_measured and also names {k}={o[k]!r}")
        if not isinstance(o.get("evidence_instrument"), dict):
            issues.append(f"{where} declares measurability=declared_not_measured but no evidence_instrument")
        else:
            _validate_instrument(where, o["evidence_instrument"], issues)


def _validate_constraint(i, c, issues):
    """Issues with one constraint; returns (wicket id, check, selectors or None)."""
    ref_key = "wicket_ref" if isinstance(c, dict) and "wicket_ref" in c else "wicket_id"
    where = _named("constraints", i, c, ref_key)
    if not isinstance(c, dict):
        issues.append(f"{where} must be a mapping")
        return None
    if ref_key == "wicket_ref":
        _unknown_keys(where, c, {"wicket_ref", "check", "digest", "scope"}, "a cited constraint field", issues)
        if not (isinstance(c.get("digest"), str) and _HEX64.match(c["digest"])):
            issues.append(f"{where}.digest must be 64 lowercase hex characters")
    else:
        _unknown_keys(where, c, {"wicket_id", "check", "config", "semantics", "scope"},
                      "an inline constraint field", issues)
        if _nonempty(c.get("wicket_id")) and not DEFINITION_ID_RE.match(c["wicket_id"]):
            issues.append(f"{where}.wicket_id must be <namespace>[.<namespace>...]/<major.minor.patch>")
        if "config" in c and not isinstance(c["config"], dict):
            issues.append(f"{where}.config must be a mapping")
        if "semantics" in c and not _nonempty(c["semantics"]):
            issues.append(f"{where}.semantics must be a non-empty string")
    for k in (ref_key, "check"):
        if not _nonempty(c.get(k)):
            issues.append(f"{where}.{k} must be a non-empty string")
    if "scope" in c and not (_str_list(c["scope"]) and c["scope"]):
        issues.append(f"{where}.scope must be a non-empty list of strings")
    if c.get("check") == "caps" and "scope" not in c:
        issues.append(f"{where}: a caps constraint must declare scope")
    selectors = None
    if ref_key == "wicket_id" and isinstance(c.get("config"), dict):
        named = c["config"].get("selectors") or []
        # The engine reads a check's selectors as the names config.selectors holds.
        if isinstance(named, (dict, list)) and all(_nonempty(k) for k in named):
            selectors = set(named)
        else:
            issues.append(f"{where}.config.selectors must be a mapping or list keyed by selector name")
    return c.get(ref_key), c.get("check"), selectors


def _read_fold_file(where, rel, base_dir, issues):
    """The fold definition a `folds[].file` names, read relative to the source's
    directory, or None with the issue recorded. A file outside that directory is
    refused, although capsule-engine's loader would read it: a pack directory
    carries every file its digest depends on."""
    if base_dir is None:
        issues.append(f"{where}.file is read relative to the pack source's directory, and none was given")
        return None
    base = pathlib.Path(base_dir).resolve()
    path = (base / rel).resolve()
    if pathlib.PurePath(rel).is_absolute() or base not in path.parents:
        issues.append(f"{where}.file {rel!r} must be a path inside the pack source's directory")
        return None
    try:
        d = yaml.safe_load(path.read_text())
    except OSError:
        issues.append(f"{where}.file {rel!r} does not exist under {base}")
    except (UnicodeDecodeError, yaml.YAMLError) as e:
        issues.append(f"{where}.file {rel!r} is not valid YAML: {e}")
    else:
        if isinstance(d, dict):
            return d
        issues.append(f"{where}.file {rel!r} must hold a fold definition mapping")
    return None


def _validate_fold_definition(where, d, issues):
    """folds/definition.py parse_definition's shape checks."""
    if not isinstance(d, dict):
        issues.append(f"{where}: a fold definition must be a mapping")
        return
    _unknown_keys(where, d, FOLD_KEYS, "a fold definition field", issues)
    if not (_nonempty(d.get("fold_id")) and DEFINITION_ID_RE.match(d["fold_id"])):
        issues.append(f"{where}.fold_id must be <namespace>[.<namespace>...]/<major.minor.patch>")
    reads = d.get("reads")
    declared = set()
    if not (isinstance(reads, list) and reads):
        issues.append(f"{where}.reads must be a non-empty list")
        reads = []
    for j, r in enumerate(reads):
        if not (isinstance(r, dict) and _nonempty(r.get("path")) and set(r) <= {"path", "erasure_class", "default"}):
            issues.append(f"{where}.reads[{j}] must be a mapping of path, erasure_class and an optional default")
            continue
        if r["path"] in declared:
            issues.append(f"{where}.reads path {r['path']!r} is declared more than once")
        declared.add(r["path"])
        if r.get("erasure_class") not in ERASURE_CLASSES:
            issues.append(f"{where}.reads[{j}].erasure_class must be one of {list(ERASURE_CLASSES)}")
    filters = d.get("filter") or []
    if not isinstance(filters, list):
        issues.append(f"{where}.filter must be a list")
        filters = []
    for j, f in enumerate(filters):
        if not (isinstance(f, dict) and set(f) == {"field", "op", "value"}):
            issues.append(f"{where}.filter[{j}] must be a mapping of field, op and value")
        elif f["op"] not in FILTER_OPS:
            issues.append(f"{where}.filter[{j}].op {f['op']!r} must be one of {list(FILTER_OPS)}")
        elif not isinstance(f["field"], str) or f["field"] not in declared:
            issues.append(f"{where}.filter[{j}].field {f['field']!r} is not declared in reads")
        elif f["op"] in ("in", "not_in") and not isinstance(f["value"], list):
            issues.append(f"{where}.filter[{j}].op {f['op']!r} needs a list value")
    if d.get("key") is not None and (not isinstance(d["key"], str) or d["key"] not in declared):
        issues.append(f"{where}.key {d['key']!r} is not declared in reads")
    window = d.get("window")
    if window is not None:
        mode = window.get("mode") if isinstance(window, dict) else None
        if not ((mode == "rolling" and _nonempty(window.get("duration")))
                or (mode == "explicit" and _nonempty(window.get("start")) and _nonempty(window.get("end")))):
            issues.append(f"{where}.window must be mode rolling with a duration, or mode explicit with a start and end")
        elif "timestamp" not in declared:
            issues.append(f"{where}.window needs 'timestamp' declared in reads")
    reduce = d.get("reduce")
    if not (isinstance(reduce, dict) and reduce.get("reducer") in REDUCERS and set(reduce) <= {"reducer", "field"}):
        issues.append(f"{where}.reduce.reducer must be one of {list(REDUCERS)}")
    elif reduce["reducer"] in FIELD_REDUCERS and (not isinstance(reduce.get("field"), str) or reduce["field"] not in declared):
        issues.append(f"{where}.reduce.field must be a field declared in reads for reducer {reduce['reducer']!r}")
    elif reduce["reducer"] not in FIELD_REDUCERS and reduce.get("field") is not None:
        issues.append(f"{where}.reduce: reducer {reduce['reducer']!r} takes no field")
    if not _nonempty(d.get("emit")):
        issues.append(f"{where}.emit must be a non-empty string")
    if d.get("derivation_class", "deterministic") not in DERIVATION_CLASSES:
        issues.append(f"{where}.derivation_class must be one of {list(DERIVATION_CLASSES)}")
    rev = d.get("reversal")
    if rev is not None:
        if not (isinstance(rev, dict) and set(rev) == {"class_field", "classes", "parent_field", "relation_field", "relation"}
                and all(isinstance(rev[k], str) and rev[k] in declared for k in ("class_field", "parent_field", "relation_field"))
                and _str_list(rev["classes"]) and rev["classes"] and rev["relation"] == "supersedes"
                and isinstance(reduce, dict) and reduce.get("reducer") == "sum"):
            issues.append(f"{where}.reversal must take back part of a sum: class_field, parent_field and "
                          "relation_field declared in reads, a non-empty classes list, and relation supersedes")


def _validate_fold(i, f, base_dir, issues):
    """Issues with one fold entry; returns its fold id, if it has one."""
    if isinstance(f, dict) and "file" in f:
        where = f"folds[{i}]"
        _unknown_keys(where, f, {"file"}, "a fold file field", issues)
        if not _nonempty(f["file"]):
            issues.append(f"{where}.file must be a non-empty string")
            return None
        d = _read_fold_file(where, f["file"], base_dir, issues)
        if d is None:
            return None
        where = f"folds[{i}] ({f['file']})"
        n = len(issues)
        _validate_fold_definition(where, d, issues)
        return d["fold_id"] if len(issues) == n else None
    where = _named("folds", i, f, "fold_ref")
    if not isinstance(f, dict):
        issues.append(f"{where} must be a mapping")
        return None
    _unknown_keys(where, f, {"fold_ref", "digest"}, "a fold field", issues)
    if not _nonempty(f.get("fold_ref")):
        issues.append(f"{where}.fold_ref must be a non-empty string")
    if not (isinstance(f.get("digest"), str) and _HEX64.match(f["digest"])):
        issues.append(f"{where}.digest must be 64 lowercase hex characters")
    return f.get("fold_ref")


def _validate_clause(where, c, issues):
    where = f"{where}.clause"
    if not isinstance(c, dict):
        issues.append(f"{where} must be a mapping")
        return
    _unknown_keys(where, c, CLAUSE_KEYS, "a clause field", issues)
    for k in ("instrument", "article"):
        if not _nonempty(c.get(k)):
            issues.append(f"{where}.{k} must be a non-empty string")
    if "as_amended_by" in c and not _str_list(c["as_amended_by"]):
        issues.append(f"{where}.as_amended_by must be a list of strings")
    for k in ("paragraph", "jurisdiction", "source_url"):
        if k in c and not isinstance(c[k], str):
            issues.append(f"{where}.{k} must be a string")
    if "text_snapshot_digest" in c and not (isinstance(c["text_snapshot_digest"], str) and _HEX64.match(c["text_snapshot_digest"])):
        issues.append(f"{where}.text_snapshot_digest must be 64 lowercase hex characters")
    if "effective_from" in c and not (isinstance(c["effective_from"], str) and _ISO_DATE.match(c["effective_from"])):
        issues.append(f"{where}.effective_from must be a date, YYYY-MM-DD")
    if "contested" in c and not isinstance(c["contested"], bool):
        issues.append(f"{where}.contested must be true or false")


def _validate_outcome(i, o, issues):
    """loader.py _parse_outcomes' checks on one outcome."""
    where = _named("outcomes", i, o, "id")
    if not isinstance(o, dict):
        issues.append(f"{where} must be a mapping")
        return
    _unknown_keys(where, o, OUTCOME_KEYS, "an outcome field", issues)
    for k in ("id", "statement", "evidence_rule"):
        if not _nonempty(o.get(k)):
            issues.append(f"{where}.{k} must be a non-empty string")
    for k in OUTCOME_TEXT_KEYS + ("clause_ref",):
        if k in o and not _nonempty(o[k]):
            issues.append(f"{where}.{k} must be a non-empty string")
    fwd, bwd = o.get("forward_verdict"), o.get("backward_verdict")
    if fwd not in FORWARD_VERDICTS:
        issues.append(f"{where}.forward_verdict {fwd!r} must be one of {list(FORWARD_VERDICTS)}")
    if bwd not in BACKWARD_VERDICTS:
        issues.append(f"{where}.backward_verdict {bwd!r} must be one of {list(BACKWARD_VERDICTS)}")
    claim = o.get("effect_claim")
    if _nonempty(claim) and claim not in EFFECT_CLAIMS:
        issues.append(f"{where}.effect_claim {claim!r} must be one of {sorted(EFFECT_CLAIMS)}")
    elif _nonempty(claim) and EFFECT_CLAIMS[claim] and (fwd, bwd) != EFFECT_CLAIMS[claim][:2]:
        issues.append(f"{where}.effect_claim {claim!r} must compile to forward_verdict/backward_verdict "
                      f"{EFFECT_CLAIMS[claim][0]}/{EFFECT_CLAIMS[claim][1]}")
    if "REFUSED" in (fwd, bwd) and _refusal_reason(o) not in REFUSAL_REASON_CODES:
        issues.append(f"{where} is REFUSED and needs a refusal_reason_code, one of {list(REFUSAL_REASON_CODES)}")
    window = o.get("window")
    if window is not None and not (isinstance(window, dict) and set(window) <= {"duration", "cure", "grace"}
                                   and _nonempty(window.get("duration"))
                                   and all(window.get(k) is None or isinstance(window[k], str) for k in ("cure", "grace"))):
        issues.append(f"{where}.window must be a mapping of a duration and optional cure and grace strings")
    grade = o.get("re_derivability_grade")
    if grade is not None and grade not in RE_DERIVABILITY_GRADES:
        issues.append(f"{where}.re_derivability_grade {grade!r} must be one of {list(RE_DERIVABILITY_GRADES)}")
    measurability = o.get("measurability", "measured")
    if measurability not in MEASURABILITY:
        issues.append(f"{where}.measurability {measurability!r} must be one of {list(MEASURABILITY)}")
    if measurability == "declared_not_measured" and "evidence_instrument" not in o:
        issues.append(f"{where} declares measurability=declared_not_measured but no evidence_instrument")
    if "evidence_instrument" in o:
        _validate_instrument(where, o["evidence_instrument"], issues)
    for k, allowed in (("tier", REQUIREMENT_TIERS), ("mode", MODES), ("profile", EVIDENCE_PROFILES),
                       ("epistemic_type", EPISTEMIC_TYPES)):
        if k in o and o[k] not in allowed:
            issues.append(f"{where}.{k} {o[k]!r} must be one of {list(allowed)}")
    if "clause" in o:
        _validate_clause(where, o["clause"], issues)
    elif o.get("profile") == "obligation":
        issues.append(f"{where} is profile obligation and needs a clause")


def _validate_profiles(profiles, outcomes, issues):
    if not isinstance(profiles, list):
        issues.append("profiles must be a list")
        return
    modes = {o["id"]: o.get("mode", "structural") for o in outcomes if isinstance(o, dict) and _nonempty(o.get("id"))}
    seen = set()
    for i, p in enumerate(profiles):
        where = _named("profiles", i, p, "profile_id")
        if not isinstance(p, dict):
            issues.append(f"{where} must be a mapping")
            continue
        _unknown_keys(where, p, {"profile_id", "counterparty_binding", "overrides"}, "a profile field", issues)
        pid = p.get("profile_id")
        if pid not in PROFILE_IDS:
            issues.append(f"{where}.profile_id {pid!r} must be one of {list(PROFILE_IDS)}")
        elif pid in seen:
            issues.append(f"duplicate profile_id: {pid!r}")
        seen.add(pid)
        b = p.get("counterparty_binding")
        if not (isinstance(b, dict) and set(b) <= {"direct", "ultimate"} and _nonempty(b.get("direct"))
                and ("ultimate" not in b or _nonempty(b["ultimate"]))):
            issues.append(f"{where}.counterparty_binding must name a direct and an optional ultimate counterparty")
        overrides = p.get("overrides")
        if overrides is None:
            continue
        if not isinstance(overrides, list):
            issues.append(f"{where}.overrides must be a list")
            continue
        named = set()
        for j, ov in enumerate(overrides):
            ow = f"{where}.overrides[{j}]"
            if not (isinstance(ov, dict) and set(ov) <= {"outcome_id", "applies", "tier"} and _nonempty(ov.get("outcome_id"))):
                issues.append(f"{ow} must be a mapping of outcome_id and an optional applies and tier")
                continue
            oid = ov["outcome_id"]
            if oid in named:
                issues.append(f"{ow}: outcome_id {oid!r} is overridden more than once")
            named.add(oid)
            if oid not in modes:
                issues.append(f"{ow}.outcome_id {oid!r} is not one of this pack's outcomes")
            elif modes[oid] in TOPOLOGY_INVARIANT_MODES:
                issues.append(f"{ow}: outcome {oid!r} is mode {modes[oid]!r}, which no profile may override")
            if "applies" in ov and not isinstance(ov["applies"], bool):
                issues.append(f"{ow}.applies must be true or false")
            if "tier" in ov and ov["tier"] not in REQUIREMENT_TIERS:
                issues.append(f"{ow}.tier {ov['tier']!r} must be one of {list(REQUIREMENT_TIERS)}")


def _validate_proposers(proposers, issues):
    if not isinstance(proposers, list):
        issues.append("proposers must be a list")
        return
    for i, p in enumerate(proposers):
        where = _named("proposers", i, p, "id")
        if not isinstance(p, dict):
            issues.append(f"{where} must be a mapping")
            continue
        _unknown_keys(where, p, {"id", "fold_id", "strategy", "status"}, "a proposer field", issues)
        for k in ("id", "fold_id", "strategy"):
            if not _nonempty(p.get(k)):
                issues.append(f"{where}.{k} must be a non-empty string")
        if p.get("status", "planned") not in PROPOSER_STATUSES:
            issues.append(f"{where}.status {p['status']!r} must be one of {list(PROPOSER_STATUSES)}")


def _validate_scope_census(c, issues):
    def count(k, low):
        v = c.get(k)
        return isinstance(v, int) and not isinstance(v, bool) and v >= low
    if not (isinstance(c, dict) and set(c) == {"document_digest", "n", "m", "review_by"}
            and _nonempty(c["document_digest"]) and _nonempty(c["review_by"])
            and count("n", 0) and count("m", 1) and c["n"] <= c["m"]):
        issues.append("scope_census must be a mapping of document_digest, n, m and review_by, with 0 <= n <= m and m >= 1")


def _undigestable(v, path):
    """Issues for each value in a body the engine refuses to digest: a float, an
    integer outside the IEEE-754 safe range, a mapping key that is not a
    string, or a value JSON cannot carry (an unquoted YAML date or timestamp)."""
    if v is None or isinstance(v, (bool, str)):
        return []
    if isinstance(v, float) or (isinstance(v, int) and abs(v) > MAX_SAFE_INTEGER):
        return [f"{path} is a float or an integer beyond 2^53-1, which capsule-engine does not digest"]
    if isinstance(v, int):
        return []
    if isinstance(v, dict):
        return [i for k, x in v.items()
                for i in ([f"{path} has a key {k!r} that is not a string, which capsule-engine does not digest"]
                          if not isinstance(k, str) else _undigestable(x, f"{path}.{k}"))]
    if isinstance(v, list):
        return [i for j, x in enumerate(v) for i in _undigestable(x, f"{path}[{j}]")]
    return [f"{path} is a {type(v).__name__}, not a JSON value (quote it to make it a string), "
            "which capsule-engine does not digest"]


def _forward_list(source, key, has_outcomes, issues):
    """One of the forward lists (or folds): a non-empty list, unless the pack
    declares outcomes, when it may be empty or absent."""
    v = source.get(key)
    if has_outcomes and (v is None or v == []):
        return []
    if not isinstance(v, list) or not v:
        issues.append(f"{key} must be a non-empty list" + (" (or empty, in a pack that declares outcomes)" if has_outcomes else ""))
        return []
    return v


def validate_live(source, base_dir=None):
    """Every issue found in a live pack source (the scope block's own issues come
    from validate_scope). base_dir is the source's directory, which a fold
    `file` is read relative to."""
    issues = []
    for k in sorted(set(source) - LIVE_KEYS, key=str):
        issues.append(f"{k} is not a live pack field")
    for k in ("pack_id", "pack_version"):
        v = source.get(k)
        if not _nonempty(v):
            issues.append(f"{k} must be a non-empty string")
        elif "@" in v or re.search(r"\s", v):
            issues.append(f"{k} must not contain '@' or whitespace (used verbatim in contract_ref: <pack_id>@<pack_version>)")

    pack_id, pack_version = source.get("pack_id"), source.get("pack_version")
    if _nonempty(pack_id) and not PACK_ID_RE.match(pack_id):
        issues.append(f"pack_id {pack_id!r} must be <owner>/<name>/<major.minor.patch>, as capsule-engine's PACK_ID_RE requires")
    elif _nonempty(pack_id) and _nonempty(pack_version) and pack_version != pack_id.rsplit("/", 1)[1]:
        issues.append(f"pack_version {pack_version!r} must equal the version in pack_id {pack_id!r}: "
                      "the digest is the engine's for that pack_id, and the contract cites pack_version")

    outcomes = source.get("outcomes")
    if outcomes is None:
        outcomes = []
    elif not isinstance(outcomes, list):
        issues.append("outcomes must be a list")
        outcomes = []
    has_outcomes = bool(outcomes)

    checks, selectors, wickets = set(), {}, set()
    for i, c in enumerate(_forward_list(source, "constraints", has_outcomes, issues)):
        found = _validate_constraint(i, c, issues)
        if found is None:
            continue
        wicket, check, named = found
        if _nonempty(wicket):
            if wicket in wickets:
                issues.append(f"duplicate constraint wicket: {wicket!r}")
            wickets.add(wicket)
        if _nonempty(check):
            checks.add(check)
            if named is not None:
                selectors[check] = selectors.get(check, set()) | named
    # A check that any cited wicket implements has selectors only the engine can see.
    for c in source.get("constraints") or ():
        if isinstance(c, dict) and "wicket_ref" in c:
            selectors.pop(c.get("check"), None)

    seen = set()
    for i, o in enumerate(_forward_list(source, "obligations", has_outcomes, issues)):
        _validate_obligation(i, o, checks, selectors, issues)
        oid = o.get("id") if isinstance(o, dict) else None
        if _nonempty(oid):
            if oid in seen:
                issues.append(f"duplicate obligation id: {oid!r}")
            seen.add(oid)

    for i, a in enumerate(_forward_list(source, "action_semantics", has_outcomes, issues)):
        where = _named("action_semantics", i, a, "action_type")
        if not isinstance(a, dict):
            issues.append(f"{where} must be a mapping")
            continue
        for k in sorted(set(a) - {"action_type", "action_class", "required_fields", "optional_fields", "field_aliases"}, key=str):
            issues.append(f"{where}.{k} is not an action_semantics field")
        for k in ("action_type", "action_class"):
            if not _nonempty(a.get(k)):
                issues.append(f"{where}.{k} must be a non-empty string")
        if not _str_list(a.get("required_fields")):
            issues.append(f"{where}.required_fields must be a list of strings")
        if "optional_fields" in a and not _str_list(a["optional_fields"]):
            issues.append(f"{where}.optional_fields must be a list of strings")
        aliases = a.get("field_aliases")
        if aliases is not None and not (isinstance(aliases, dict) and all(_nonempty(k) and _nonempty(v) for k, v in aliases.items())):
            issues.append(f"{where}.field_aliases must be a mapping of string to string")

    folds = set()
    for i, f in enumerate(_forward_list(source, "folds", has_outcomes, issues)):
        fold_id = _validate_fold(i, f, base_dir, issues)
        if _nonempty(fold_id):
            if fold_id in folds:
                issues.append(f"duplicate fold: {fold_id!r}")
            folds.add(fold_id)

    ids = set()
    for i, o in enumerate(outcomes):
        _validate_outcome(i, o, issues)
        oid = o.get("id") if isinstance(o, dict) else None
        if _nonempty(oid):
            if oid in ids:
                issues.append(f"duplicate outcome id: {oid!r}")
            elif oid in seen:
                issues.append(f"outcome id {oid!r} is also an obligation id; each is one requirement of the contract")
            ids.add(oid)
    if "profiles" in source:
        _validate_profiles(source["profiles"], outcomes, issues)
    if "proposers" in source:
        _validate_proposers(source["proposers"], issues)
    if "scope_census" in source:
        _validate_scope_census(source["scope_census"], issues)

    if source.get("holds_integration", "none") not in HOLDS_INTEGRATION_VALUES:
        issues.append(f"holds_integration {source['holds_integration']!r} must be one of {list(HOLDS_INTEGRATION_VALUES)}")
    tax = source.get("taxonomy")
    if tax is not None:
        if not (isinstance(tax, dict) and set(tax) == {"taxonomy_version", "digest"}
                and _nonempty(tax["taxonomy_version"]) and _nonempty(tax["digest"])):
            issues.append("taxonomy must be a mapping of taxonomy_version and digest, both non-empty strings")
    if not issues:
        # Each body the engine digests: each inline wicket and fold file, which
        # enter the pack definition only by their own digests, then (once those
        # can be digested) the definition itself.
        bodies = [(f"constraints[{i}]", _wicket_body(c)) for i, c in enumerate(source.get("constraints") or ())
                  if "wicket_ref" not in c]
        bodies += [(f"folds[{i}] ({f['file']})", _fold_body(f, base_dir)) for i, f in enumerate(source.get("folds") or ())
                   if "file" in f]
        issues = [i for where, body in bodies for i in _undigestable(body, where)]
        issues = issues or _undigestable(canonical_definition(source, base_dir), "definition")
    return issues


def _refusal_reason(o):
    """An outcome's refusal_reason_code, or the one its effect_claim compiles to."""
    if o.get("refusal_reason_code") is not None:
        return o["refusal_reason_code"]
    claim = o.get("effect_claim")
    compiled = EFFECT_CLAIMS.get(claim) if isinstance(claim, str) else None
    return compiled[2] if compiled else None


def _selector_text(o):
    return f" (selector {o['selector']})" if o.get("selector") else ""


def _disposition_text(o):
    if "default_disposition" in o:
        return f"Default disposition when it fails: {o['default_disposition']}."
    return "It declares no default disposition."


def _evidence_rule(o):
    if o.get("mode") == "judged":
        pin = o["judge_pin"]
        return (f"Judged: the {pin['model_hosting']} model {pin['model_id']!r} answers this from the action's "
                f"{', '.join(pin['input_refs'])}, with its prompt template and answer schema pinned by hash. "
                + _disposition_text(o))
    if o.get("measurability") == "declared_not_measured":
        inst = o["evidence_instrument"]
        what = inst["field"] if inst["kind"] == "structured_field" else inst["name"]
        return (f"Declared, not measured: no check evaluates this yet. The input it needs is {inst['kind']} {what!r}, "
                "not recorded on an action today.")
    return (f"Deterministic: the guard's {o['check']} check{_selector_text(o)} evaluates this over the action's "
            f"normalized fields. " + _disposition_text(o))


def _obligation_requirement(o):
    declared = o.get("measurability") == "declared_not_measured"
    judged = o.get("mode") == "judged"
    req = {
        "id": o["id"],
        "profile": "outcome",
        "statement": o["statement"],
        "tier": o.get("requirement_tier", "must_have"),
        "evidence_rule": _evidence_rule(o),
        "forward_verdict": ("UNAVAILABLE-STATE-REQUIRED" if declared
                            else "UNAVAILABLE-MODEL-REQUIRED" if judged else "DETERMINISTIC"),
        "backward_verdict": "MODEL-ASSISTED" if judged else "DETERMINISTIC",
    }
    if o.get("re_derivability_grade"):
        req["re_derivability_grade"] = o["re_derivability_grade"]
    if declared:
        req["measurability"] = "declared_not_measured"
        req["evidence_instrument"] = dict(o["evidence_instrument"])
    if o.get("mode", "structural") != "structural":
        req["mode"] = o["mode"]
    return req


def _outcome_requirement(o):
    req = _canonical_outcome(o)
    req["profile"] = o.get("profile", "outcome")
    req["tier"] = o.get("tier", "informational")
    return req


def from_live(source):
    """A validated live pack source -> the Evidence Contract v0 document."""
    requirements = [_obligation_requirement(o) for o in source.get("obligations") or ()]
    requirements += [_outcome_requirement(o) for o in source.get("outcomes") or ()]
    return {"id": source["pack_id"], "version": source["pack_version"], "requirements": requirements}


def _canonical_judge_pin(pin):
    out = {k: pin[k] for k in ("model_id", "prompt_template_hash", "schema_hash", "model_hosting")}
    out["input_refs"] = list(pin["input_refs"])
    if "model_digest" in pin:
        out["model_digest"] = pin["model_digest"]
    return out


def _canonical_obligation(o):
    """packs/schema.py PackDefinition.canonical_dict()'s entry for one obligation."""
    m = {"id": o["id"], "statement": o["statement"]}
    declared = o.get("measurability") == "declared_not_measured"
    judged = o.get("mode") == "judged"
    if not (declared or judged):
        m["check"] = o["check"]
        if o.get("selector"):
            m["selector"] = o["selector"]
    if o.get("re_derivability_grade"):
        m["re_derivability_grade"] = o["re_derivability_grade"]
    if o.get("default_disposition"):
        m["default_disposition"] = o["default_disposition"]
    if declared:
        m["measurability"] = "declared_not_measured"
        m["evidence_instrument"] = dict(o["evidence_instrument"])
    if o.get("mode", "structural") != "structural":
        m["mode"] = o["mode"]
    if judged:
        m["judge_pin"] = _canonical_judge_pin(o["judge_pin"])
    return m


def _canonical_clause(c):
    """packs/schema.py ClauseSpec.to_dict()."""
    out = {"instrument": c["instrument"], "article": c["article"]}
    if c.get("as_amended_by"):
        out["as_amended_by"] = list(c["as_amended_by"])
    for k in ("paragraph", "jurisdiction", "text_snapshot_digest", "effective_from", "source_url"):
        if c.get(k) is not None:
            out[k] = c[k]
    if c.get("contested"):
        out["contested"] = True
    return out


def _canonical_outcome(o):
    """packs/schema.py EvidenceContract.canonical_dict(): each optional field
    omitted at its default."""
    out = {k: o[k] for k in ("id", "statement", "evidence_rule", "forward_verdict", "backward_verdict")}
    if o.get("window"):
        w = o["window"]
        out["window"] = {"duration": w["duration"], "cure": w.get("cure"), "grace": w.get("grace")}
    for k in OUTCOME_TEXT_KEYS:
        v = _refusal_reason(o) if k == "refusal_reason_code" else o.get(k)
        if v:
            out[k] = v
    for k, default in (("measurability", "measured"), ("tier", "informational"), ("mode", "structural")):
        if o.get(k, default) != default:
            out[k] = o[k]
    if o.get("evidence_instrument") is not None:
        out["evidence_instrument"] = dict(o["evidence_instrument"])
    if o.get("clause_ref"):
        out["clause_ref"] = o["clause_ref"]
    if o.get("clause") is not None:
        out["clause"] = _canonical_clause(o["clause"])
    if o.get("profile", "outcome") != "outcome":
        out["profile"] = o["profile"]
    if o.get("epistemic_type") is not None:
        out["epistemic_type"] = o["epistemic_type"]
    return out


def _canonical_profile(p):
    """packs/schema.py TopologyProfile.canonical_dict()."""
    b = p["counterparty_binding"]
    overrides = []
    for ov in sorted(p.get("overrides") or (), key=lambda ov: ov["outcome_id"]):
        m = {"outcome_id": ov["outcome_id"]}
        if not ov.get("applies", True):
            m["applies"] = False
        if ov.get("tier") is not None:
            m["tier"] = ov["tier"]
        overrides.append(m)
    return {"profile_id": p["profile_id"],
            "counterparty_binding": {"direct": b["direct"], "ultimate": b.get("ultimate", b["direct"])},
            "overrides": overrides}


def _digest(obj):
    return hashlib.sha256(rfc8785.dumps(obj)).hexdigest()


def _wicket_body(c):
    """guards/wickets/definition.py WicketDefinition.canonical_dict() for an
    inline constraint."""
    body = {"wicket_id": c["wicket_id"], "check": c["check"], "config": c.get("config") or {}}
    if c.get("semantics") is not None:
        body["semantics"] = c["semantics"]
    return body


def _canonical_fold_definition(d):
    """folds/definition.py FoldDefinition.canonical_dict(), which leaves out
    derivation_class."""
    out = {
        "fold_id": d["fold_id"],
        "reads": [{"path": r["path"], "erasure_class": r["erasure_class"],
                   **({"default": r["default"]} if "default" in r else {})} for r in d["reads"]],
        "reduce": {"reducer": d["reduce"]["reducer"],
                   **({"field": d["reduce"]["field"]} if d["reduce"].get("field") else {})},
        "emit": d["emit"],
    }
    if d.get("filter"):
        out["filter"] = [{"field": f["field"], "op": f["op"], "value": f["value"]} for f in d["filter"]]
    if d.get("key") is not None:
        out["key"] = d["key"]
    if d.get("window") is not None:
        w = d["window"]
        keys = ("duration",) if w["mode"] == "rolling" else ("start", "end")
        out["window"] = {"mode": w["mode"], **{k: w[k] for k in keys}}
    if d.get("reversal") is not None:
        r = d["reversal"]
        out["reversal"] = {"class_field": r["class_field"], "classes": list(r["classes"]),
                           "parent_field": r["parent_field"], "relation_field": r["relation_field"],
                           "relation": r["relation"]}
    return out


def _fold_body(f, base_dir):
    """The canonical definition a fold file holds."""
    return _canonical_fold_definition(yaml.safe_load((pathlib.Path(base_dir) / f["file"]).read_text()))


def _canonical_fold(f, base_dir):
    if "file" not in f:
        return {"fold_id": f["fold_ref"], "digest": f["digest"]}
    body = _fold_body(f, base_dir)
    return {"fold_id": body["fold_id"], "digest": _digest(body)}


def canonical_definition(source, base_dir=None):
    """capsule-engine's `PackDefinition.canonical_dict()` for this source (the
    keys it emits only when set, emitted only when set)."""
    semantics = []
    for a in source.get("action_semantics") or ():
        m = {"action_type": a["action_type"], "action_class": a["action_class"],
             "required_fields": list(a["required_fields"])}
        if a.get("optional_fields"):
            m["optional_fields"] = list(a["optional_fields"])
        if a.get("field_aliases"):
            m["field_aliases"] = dict(sorted(a["field_aliases"].items()))
        semantics.append(m)
    constraints = []
    for c in source.get("constraints") or ():
        if "wicket_ref" in c:
            m = {"wicket_id": c["wicket_ref"], "check": c["check"], "digest": c["digest"]}
        else:
            m = {"wicket_id": c["wicket_id"], "check": c["check"], "digest": _digest(_wicket_body(c))}
        if c.get("scope") is not None:
            m["scope"] = list(c["scope"])
        constraints.append(m)
    out = {
        "pack_id": source["pack_id"],
        "obligations": [_canonical_obligation(o) for o in source.get("obligations") or ()],
        "action_semantics": semantics,
        "constraints": constraints,
        "folds": [_canonical_fold(f, base_dir) for f in source.get("folds") or ()],
        "holds_integration": source.get("holds_integration", "none"),
    }
    if source.get("proposers"):
        out["proposers"] = [{"id": p["id"], "fold_id": p["fold_id"], "strategy": p["strategy"],
                             "status": p.get("status", "planned")} for p in source["proposers"]]
    if source.get("outcomes"):
        out["outcomes"] = [_canonical_outcome(o) for o in source["outcomes"]]
    if source.get("scope_census"):
        out["scope_census"] = {k: source["scope_census"][k] for k in ("document_digest", "n", "m", "review_by")}
    if source.get("profiles"):
        out["profiles"] = [_canonical_profile(p) for p in sorted(source["profiles"], key=lambda p: p["profile_id"])]
    if source.get("taxonomy"):
        out["taxonomy"] = dict(source["taxonomy"])
    return out


def project(source, base_dir=None):
    """A validated live pack source -> {"pack_id", "definition": canonical dict,
    "definition_digest"}: the digest capsule-engine computes for the same pack."""
    definition = canonical_definition(source, base_dir)
    return {"pack_id": source["pack_id"], "definition_digest": _digest(definition), "definition": definition}


def projection_bytes(source, base_dir=None):
    return (json.dumps(project(source, base_dir), indent=2, ensure_ascii=False) + "\n").encode()
