#!/usr/bin/env python3
"""A `scope.kind: live` pack source: validation, the Evidence Contract it
compiles to, and the projection to capsule-engine's pack definition.

SEAMS ruling 1: one pack format. A pack source declares `scope.kind`, `live`
(rules a guard enforces on an agent's action before it runs, capsule-engine's
`pack.yaml` packs) or `after_the_fact` (outcome and obligation rows judged over a
finished session, the rest of scripts/pack_compile.py). Absent means
`after_the_fact`, so no existing pack changes.

A live source states what capsule-engine's `pack.yaml` states, under the same
key names:

  pack_id, pack_version        pack_version is the contract's version; it is
                               not in the engine definition (pack_id carries it)
  obligations[]                id, statement, check, selector, default_disposition
                               (DO | ASK | NEVER), re_derivability_grade,
                               measurability, evidence_instrument; and, for the
                               contract only, requirement_tier
  action_semantics[]           action_type, action_class, required_fields,
                               optional_fields, field_aliases
  constraints[]                wicket_ref, digest, scope, plus `check`: the check
                               the cited wicket implements, which the engine reads
                               from the wicket definition and a source has no
                               catalog to read it from
  folds[]                      fold_ref, digest
  holds_integration, taxonomy  as in pack.yaml
  fixtures, bootstrap          as in pack.yaml; not in the contract or the digest

Two outputs, because Evidence Contract v0 is a closed schema that names no check,
disposition, wicket or fold:

  - `from_live` -> the contract (id = pack_id, version = pack_version, one
    requirement per obligation: its statement, and an evidence_rule stating the
    check, selector and disposition in words). `contract validate` accepts it.
  - `project` -> the engine's canonical pack definition and its
    `definition_digest`, computed from the source exactly as capsule-engine's
    `PackDefinition.canonical_dict()` / `definition_digest()` and
    go/pack/pack.go do (SHA-256 over the JCS bytes). The cited wicket and fold
    digests are taken as cited; the engine loader refuses a pack whose cited
    definition has changed, so a wrong one fails there, not here.

`outcomes`, `profiles`, `proposers` and `scope_census` are not supported: no
published live pack carries them (capsule-engine go/packs, python catalog
inference/seller/everyday). A source naming them is refused rather than
projected to a digest the engine would not compute.
"""
import hashlib
import json
import re

import rfc8785

SCOPE_KINDS = ("live", "after_the_fact")
DEFAULT_SCOPE_KIND = "after_the_fact"

DISPOSITIONS = ("DO", "ASK", "NEVER")
MEASURABILITY = ("measured", "declared_not_measured")
RE_DERIVABILITY_GRADES = ("pure_replay", "ledger_state_dependent")
REQUIREMENT_TIERS = ("must_have", "informational")

LIVE_KEYS = {"scope", "pack_id", "pack_version", "source", "obligations", "action_semantics",
             "constraints", "folds", "holds_integration", "taxonomy", "fixtures", "bootstrap"}
UNSUPPORTED_KEYS = ("outcomes", "profiles", "proposers", "scope_census")
OBLIGATION_KEYS = {"id", "statement", "check", "selector", "default_disposition", "re_derivability_grade",
                   "measurability", "evidence_instrument", "requirement_tier"}

# capsule-engine's packs/schema.py PACK_ID_RE and HOLDS_INTEGRATION_VALUES: a source
# outside them is a pack the engine refuses to load, so it gets no digest here.
PACK_ID_RE = re.compile(r"^[a-z][a-z0-9_]*/[a-z][a-z0-9_]*(-[a-z0-9_]+)*/\d+\.\d+\.\d+$")
HOLDS_INTEGRATION_VALUES = ("none", "stubbed", "built")

_HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")


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


def _validate_obligation(i, o, checks, issues):
    where = f"obligations[{i}]" + (f" ({o['id']!r})" if isinstance(o, dict) and _nonempty(o.get("id")) else "")
    if not isinstance(o, dict):
        issues.append(f"{where} must be a mapping")
        return
    for k in sorted(set(o) - OBLIGATION_KEYS):
        issues.append(f"{where}.{k} is not a live obligation field")
    for k in ("id", "statement"):
        if not _nonempty(o.get(k)):
            issues.append(f"{where}.{k} must be a non-empty string")
    if o.get("default_disposition") not in DISPOSITIONS:
        issues.append(f"{where}.default_disposition {o.get('default_disposition')!r} must be one of {list(DISPOSITIONS)}")
    grade = o.get("re_derivability_grade")
    if grade is not None and grade not in RE_DERIVABILITY_GRADES:
        issues.append(f"{where}.re_derivability_grade {grade!r} must be one of {list(RE_DERIVABILITY_GRADES)}")
    tier = o.get("requirement_tier", "must_have")
    if tier not in REQUIREMENT_TIERS:
        issues.append(f"{where}.requirement_tier {tier!r} must be one of {list(REQUIREMENT_TIERS)}")
    measurability = o.get("measurability", "measured")
    if measurability not in MEASURABILITY:
        issues.append(f"{where}.measurability {measurability!r} must be one of {list(MEASURABILITY)}")
    elif measurability == "measured":
        if "evidence_instrument" in o:
            issues.append(f"{where} is measured by its check and also names an evidence_instrument")
        if not _nonempty(o.get("check")):
            issues.append(f"{where}.check must be a non-empty string")
        elif o["check"] not in checks:
            issues.append(f"{where}.check {o['check']!r} has no matching constraint")
        if "selector" in o and not _nonempty(o["selector"]):
            issues.append(f"{where}.selector must be a non-empty string")
    else:
        for k in ("check", "selector"):
            if k in o:
                issues.append(f"{where} declares measurability=declared_not_measured and also names {k}={o[k]!r}")
        inst = o.get("evidence_instrument")
        if not isinstance(inst, dict):
            issues.append(f"{where} declares measurability=declared_not_measured but no evidence_instrument")
        elif not ((inst.get("kind") == "structured_field" and _nonempty(inst.get("field")) and set(inst) == {"kind", "field"})
                  or (inst.get("kind") == "tool_call_name" and _nonempty(inst.get("name")) and set(inst) == {"kind", "name"})):
            issues.append(f"{where}.evidence_instrument must be kind structured_field with a field, "
                          "or kind tool_call_name with a name")


def validate_live(source):
    """Every issue found in a live pack source (the scope block's own issues come
    from validate_scope)."""
    issues = []
    for k in sorted(set(source) - LIVE_KEYS):
        issues.append(f"{k} is not a live pack field" + (" (not supported yet)" if k in UNSUPPORTED_KEYS else ""))
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

    constraints = source.get("constraints")
    checks = set()
    if not isinstance(constraints, list) or not constraints:
        issues.append("constraints must be a non-empty list")
        constraints = []
    for i, c in enumerate(constraints):
        where = f"constraints[{i}]" + (f" ({c['wicket_ref']!r})" if isinstance(c, dict) and _nonempty(c.get("wicket_ref")) else "")
        if not isinstance(c, dict):
            issues.append(f"{where} must be a mapping")
            continue
        for k in sorted(set(c) - {"wicket_ref", "check", "digest", "scope"}):
            issues.append(f"{where}.{k} is not a constraint field")
        for k in ("wicket_ref", "check"):
            if not _nonempty(c.get(k)):
                issues.append(f"{where}.{k} must be a non-empty string")
        if not (isinstance(c.get("digest"), str) and _HEX64.match(c["digest"])):
            issues.append(f"{where}.digest must be 64 lowercase hex characters")
        if "scope" in c and not _str_list(c["scope"]):
            issues.append(f"{where}.scope must be a list of strings")
        if c.get("check") == "caps" and "scope" not in c:
            issues.append(f"{where}: a caps constraint must declare scope")
        if _nonempty(c.get("check")):
            checks.add(c["check"])

    obligations = source.get("obligations")
    if not isinstance(obligations, list) or not obligations:
        issues.append("obligations must be a non-empty list")
        obligations = []
    seen = set()
    for i, o in enumerate(obligations):
        _validate_obligation(i, o, checks, issues)
        oid = o.get("id") if isinstance(o, dict) else None
        if _nonempty(oid):
            if oid in seen:
                issues.append(f"duplicate obligation id: {oid!r}")
            seen.add(oid)

    semantics = source.get("action_semantics")
    if not isinstance(semantics, list) or not semantics:
        issues.append("action_semantics must be a non-empty list")
        semantics = []
    for i, a in enumerate(semantics):
        where = f"action_semantics[{i}]" + (f" ({a['action_type']!r})" if isinstance(a, dict) and _nonempty(a.get("action_type")) else "")
        if not isinstance(a, dict):
            issues.append(f"{where} must be a mapping")
            continue
        for k in sorted(set(a) - {"action_type", "action_class", "required_fields", "optional_fields", "field_aliases"}):
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

    folds = source.get("folds")
    if not isinstance(folds, list) or not folds:
        issues.append("folds must be a non-empty list")
        folds = []
    for i, f in enumerate(folds):
        where = f"folds[{i}]" + (f" ({f['fold_ref']!r})" if isinstance(f, dict) and _nonempty(f.get("fold_ref")) else "")
        if not isinstance(f, dict):
            issues.append(f"{where} must be a mapping")
            continue
        for k in sorted(set(f) - {"fold_ref", "digest"}):
            issues.append(f"{where}.{k} is not a fold field")
        if not _nonempty(f.get("fold_ref")):
            issues.append(f"{where}.fold_ref must be a non-empty string")
        if not (isinstance(f.get("digest"), str) and _HEX64.match(f["digest"])):
            issues.append(f"{where}.digest must be 64 lowercase hex characters")

    if source.get("holds_integration", "none") not in HOLDS_INTEGRATION_VALUES:
        issues.append(f"holds_integration {source['holds_integration']!r} must be one of {list(HOLDS_INTEGRATION_VALUES)}")
    tax = source.get("taxonomy")
    if tax is not None:
        if not (isinstance(tax, dict) and set(tax) == {"taxonomy_version", "digest"}
                and _nonempty(tax["taxonomy_version"]) and _nonempty(tax["digest"])):
            issues.append("taxonomy must be a mapping of taxonomy_version and digest, both non-empty strings")
    return issues


def _selector_text(o):
    return f" (selector {o['selector']})" if o.get("selector") else ""


def _evidence_rule(o):
    if o.get("measurability") == "declared_not_measured":
        inst = o["evidence_instrument"]
        what = inst["field"] if inst["kind"] == "structured_field" else inst["name"]
        return (f"Declared, not measured: no check evaluates this yet. The input it needs is {inst['kind']} {what!r}, "
                "not recorded on an action today.")
    return (f"Deterministic: the guard's {o['check']} check{_selector_text(o)} evaluates this over the action's "
            f"normalized fields. Default disposition when it fails: {o['default_disposition']}.")


def from_live(source):
    """A validated live pack source -> the Evidence Contract v0 document."""
    requirements = []
    for o in source["obligations"]:
        declared = o.get("measurability") == "declared_not_measured"
        req = {
            "id": o["id"],
            "profile": "outcome",
            "statement": o["statement"],
            "tier": o.get("requirement_tier", "must_have"),
            "evidence_rule": _evidence_rule(o),
            "forward_verdict": "UNAVAILABLE-STATE-REQUIRED" if declared else "DETERMINISTIC",
            "backward_verdict": "DETERMINISTIC",
        }
        if o.get("re_derivability_grade"):
            req["re_derivability_grade"] = o["re_derivability_grade"]
        if declared:
            req["measurability"] = "declared_not_measured"
            req["evidence_instrument"] = dict(o["evidence_instrument"])
        requirements.append(req)
    return {"id": source["pack_id"], "version": source["pack_version"], "requirements": requirements}


def canonical_definition(source):
    """capsule-engine's `PackDefinition.canonical_dict()` for this source (the
    keys it emits only when set, emitted only when set)."""
    obligations = []
    for o in source["obligations"]:
        m = {"id": o["id"], "statement": o["statement"]}
        declared = o.get("measurability") == "declared_not_measured"
        if not declared:
            m["check"] = o["check"]
            if o.get("selector"):
                m["selector"] = o["selector"]
        if o.get("re_derivability_grade"):
            m["re_derivability_grade"] = o["re_derivability_grade"]
        m["default_disposition"] = o["default_disposition"]
        if declared:
            m["measurability"] = "declared_not_measured"
            m["evidence_instrument"] = dict(o["evidence_instrument"])
        obligations.append(m)
    semantics = []
    for a in source["action_semantics"]:
        m = {"action_type": a["action_type"], "action_class": a["action_class"],
             "required_fields": list(a["required_fields"])}
        if a.get("optional_fields"):
            m["optional_fields"] = list(a["optional_fields"])
        if a.get("field_aliases"):
            m["field_aliases"] = dict(sorted(a["field_aliases"].items()))
        semantics.append(m)
    constraints = []
    for c in source["constraints"]:
        m = {"wicket_id": c["wicket_ref"], "check": c["check"], "digest": c["digest"]}
        if c.get("scope") is not None:
            m["scope"] = list(c["scope"])
        constraints.append(m)
    out = {
        "pack_id": source["pack_id"],
        "obligations": obligations,
        "action_semantics": semantics,
        "constraints": constraints,
        "folds": [{"fold_id": f["fold_ref"], "digest": f["digest"]} for f in source["folds"]],
        "holds_integration": source.get("holds_integration", "none"),
    }
    if source.get("taxonomy"):
        out["taxonomy"] = dict(source["taxonomy"])
    return out


def project(source):
    """A validated live pack source -> {"pack_id", "definition": canonical dict,
    "definition_digest"}: the digest capsule-engine computes for the same pack."""
    definition = canonical_definition(source)
    digest = hashlib.sha256(rfc8785.dumps(definition)).hexdigest()
    return {"pack_id": source["pack_id"], "definition_digest": digest, "definition": definition}


def projection_bytes(source):
    return (json.dumps(project(source), indent=2, ensure_ascii=False) + "\n").encode()
