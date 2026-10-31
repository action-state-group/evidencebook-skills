#!/usr/bin/env python3
"""A `scope.kind: admission` pack source: validation and the Evidence Contract
it compiles to (admission pack profile v0, docs/admission-pack-profile-v0.md).

An admission pack is the relying party's policy over what it has received about
a counterparty, run before the act (#51; Steven's 2026-10-30 ruling: admission
uses the Terms Pack build approach and the SDK does the math). It states
thresholds only. The band, the tier, freshness, counts and denominators are the
evaluator's, capsule-engine#265 (Go `go/admission`, Rust `rust/capsule-engine`),
which is the only reader of a pack's rows. This module refuses what that loader
refuses, so a pack that passes here loads there. Nothing here evaluates a pack.

The admission design rules are held here, not trusted to the author: only
platform, own_history and operator rows decide NO; a judged row only caps a
tier; a missing input is never a silent GO; the lowest tier is the floor (no
LIMIT below it); a pack has no field a weight or score could ride in.

YAML note: PyYAML reads YAML 1.1, where a plain `NO` is the boolean false. An
outcome is written quoted ("NO"); an unquoted one reaches this module as a
boolean and is refused with that reason.
"""
import re

import rfc8785
import yaml

SCOPE_KIND = "admission"

OUTCOMES = ("GO", "ASK", "LIMIT", "NO")
MISSING_DEFAULTS = ("LIMIT", "NO")
ON_FAIL = ("NO", "LIMIT", "record")
SOURCES = ("platform", "card", "bound", "own_history", "operator", "vouch", "stake", "judged")
MAY_DECIDE_NO = ("platform", "own_history", "operator")

# The evaluator's predicates: the source each reads and the params it takes.
# The list is closed and versioned with the evaluator (capsule-engine#265).
PREDICATES = {
    "platform.attestation_not_invalid": ("platform", ()),
    "platform.owner_signed": ("platform", ()),
    "card.verified": ("card", ()),
    "card.fresh": ("card", ("max_age_s",)),
    "card.key_age": ("card", ("min_days",)),
    "card.witnessed": ("card", ()),
    "card.claims_held": ("card", ("min",)),
    "card.controller_declared": ("card", ()),
    "card.controller_trusted": ("card", ()),
    "bound.selection_verified": ("bound", ()),
    "bound.no_unanswered_dispute": ("bound", ("window_days",)),
    "own.settled": ("own_history", ("min",)),
    "own.held_halves": ("own_history", ("min",)),
    "own.no_conflicting": ("own_history", ()),
    "own.no_adverse_adjudication": ("own_history", ("window_days",)),
    "operator.not_deny_listed": ("operator", ()),
    "operator.allow_listed": ("operator", ()),
    "vouch.distinct_controllers": ("vouch", ("min",)),
    "stake.covers_deal": ("stake", ()),
    "judged": ("judged", ()),
}

ADMISSION_KEYS = {"pack_id", "pack_version", "scope", "source", "outcomes", "missing", "accept", "tiers",
                  "budget", "trust_roots", "rows"}
TRUST_ROOT_KEYS = ("controllers", "witnesses", "judges")
ROW_KEYS = {"id", "statement", "source", "check", "params", "from", "on_fail", "ask"}

PACK_ID_RE = re.compile(r"^[a-z][a-z0-9_]*/[a-z][a-z0-9_-]*/\d+\.\d+\.\d+$")
ROW_ID_RE = re.compile(r"^[a-z][a-z0-9_-]*$")

# Each threshold's bound, as the evaluator's loader holds it (capsule-engine
# go/admission paramMax): a century of seconds or days, and a count no JSON
# reader loses.
# An accept scale and a tier ceiling, bounded so a band's decade stays far
# inside an int (the loader's scaleMax and decadeMax).
SCALE_MAX = 30
DECADE_MAX = 60
PARAM_MAX = {"max_age_s": 100 * 365 * 24 * 3600, "min_days": 100 * 365, "window_days": 100 * 365,
             "min": 2 ** 53 - 1}

# The plain scalar rule (capsule-engine go/admission plainScalars). YAML
# readers disagree on which plain scalars are strings: PyYAML (YAML 1.1) reads
# NO, 1:30 and 010 as a boolean and integers, yaml.v3 (YAML 1.2) reads 1e3 and
# 0o10 as numbers. So a pack may write a plain (unquoted) scalar only in a
# form every reader reads alike: a plain decimal integer, a dotted version
# (1.0.0), or text that starts with none of the characters numbers,
# timestamps, nulls and merges start with and is not a boolean or null word.
# Anything else is quoted.
_DECIMAL_INT = re.compile(r"^(0|-?[1-9][0-9]*)$")
_DOTTED_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_SPECIAL_LEADERS = "0123456789+-.~<"
_PLAIN_WORDS = {"y", "Y", "yes", "Yes", "YES", "n", "N", "no", "No", "NO", "on", "On", "ON", "off", "Off", "OFF",
                "true", "True", "TRUE", "false", "False", "FALSE", "null", "Null", "NULL"}


def _plain_ok(v):
    return (v == "" or bool(_DECIMAL_INT.match(v)) or bool(_DOTTED_VERSION.match(v))
            or (v[0] not in _SPECIAL_LEADERS and v not in _PLAIN_WORDS))


def text_issues(text):
    """What the evaluator's loader refuses in the YAML text itself, which the
    parsed mapping no longer shows: a plain scalar outside the plain scalar
    rule above, anchors and aliases, and explicit tags (the non-specific `!`
    aside, which yaml.v3 ignores)."""
    issues = []
    for ev in yaml.parse(text, Loader=yaml.SafeLoader):
        line = ev.start_mark.line + 1
        if isinstance(ev, yaml.AliasEvent) or getattr(ev, "anchor", None):
            issues.append(f"line {line}: anchors and aliases are not read")
        elif getattr(ev, "tag", None) not in (None, "!"):
            issues.append(f"line {line}: tags are not read")
        elif isinstance(ev, yaml.ScalarEvent) and not ev.style and not _plain_ok(ev.value):
            issues.append(f"line {line}: quote {ev.value!r}: YAML readers do not all read it as the same string")
    return issues


def is_admission(source):
    scope = source.get("scope") if isinstance(source, dict) else None
    return isinstance(scope, dict) and scope.get("kind") == SCOPE_KIND


def _nonempty(v):
    return isinstance(v, str) and bool(v.strip())


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _outcome(where, v, allowed, issues):
    """An outcome name, refusing the YAML 1.1 boolean an unquoted NO reads as."""
    if isinstance(v, bool):
        issues.append(f"{where} is the boolean {v}: write the outcome quoted (\"NO\"), "
                      "since YAML 1.1 reads a plain NO as false")
        return None
    if v not in allowed:
        issues.append(f"{where} {v!r} must be one of {list(allowed)}")
        return None
    return v


def validate_admission(source):
    issues = []
    for k in sorted(set(source) - ADMISSION_KEYS):
        issues.append(f"{k} is not an admission pack field (known: {sorted(ADMISSION_KEYS)})")
    pack_id, version = source.get("pack_id"), source.get("pack_version")
    if not isinstance(pack_id, str) or not PACK_ID_RE.match(pack_id):
        issues.append(f"pack_id {pack_id!r} must be owner/name/version")
    elif not isinstance(version, str) or not pack_id.endswith("/" + version):
        issues.append(f"pack_id {pack_id!r} must end in pack_version {version!r}")

    if "source" in source and not isinstance(source["source"], str):
        issues.append("source must be provenance text (a string)")

    outcomes = source.get("outcomes")
    if not isinstance(outcomes, list) or not outcomes:
        issues.append("outcomes must list the outcomes this pack yields")
        outcomes = []
    outcomes = [_outcome(f"outcomes[{i}]", o, OUTCOMES, issues) for i, o in enumerate(outcomes)]
    if "GO" not in outcomes:
        issues.append("outcomes must include GO")
    missing = source.get("missing")
    if missing == "GO":
        issues.append("missing must not be GO: a missing input is never a silent GO")
    elif _outcome("missing", missing, MISSING_DEFAULTS, issues) and missing not in outcomes:
        issues.append(f"missing {missing} is not in outcomes")

    accept = source.get("accept")
    bands = set()
    if not isinstance(accept, dict) or not accept:
        issues.append("accept must map at least one currency to its band unit")
    else:
        for cur, unit in accept.items():
            if not isinstance(unit, dict) or set(unit) != {"band", "scale"} \
                    or not _nonempty(unit.get("band")) or not _is_int(unit.get("scale")):
                issues.append(f"accept.{cur} must be exactly {{band: <unit>, scale: <integer>}}")
            else:
                bands.add(unit["band"])
                if not -SCALE_MAX <= unit["scale"] <= SCALE_MAX:
                    issues.append(f"accept.{cur}: scale {unit['scale']} must be from {-SCALE_MAX} to {SCALE_MAX}")

    tiers = source.get("tiers")
    tier_ids = []
    if not isinstance(tiers, list) or not tiers:
        issues.append("tiers must not be empty")
        tiers = []
    # The ceiling of the highest tier so far that names each band unit, so a
    # unit a tier skips is still compared across the gap.
    below = {}
    for i, t in enumerate(tiers):
        if not isinstance(t, dict) or set(t) - {"id", "max_decade"} or not _nonempty(t.get("id")):
            issues.append(f"tiers[{i}] must be {{id, max_decade}}")
            tier_ids.append(None)
            continue
        if t["id"] in tier_ids:
            issues.append(f"tier {t['id']!r} is listed twice")
        tier_ids.append(t["id"])
        decades = t.get("max_decade")
        if not isinstance(decades, dict) or not all(_is_int(d) for d in decades.values()):
            issues.append(f"tiers[{i}].max_decade must map band units to integer decades")
            continue
        for band, d in sorted(decades.items(), key=lambda kv: str(kv[0])):
            if not -DECADE_MAX <= d <= DECADE_MAX:
                issues.append(f"tier {t['id']}: max_decade.{band} {d} must be from {-DECADE_MAX} to {DECADE_MAX}")
            if band not in bands:
                issues.append(f"tier {t['id']}: max_decade.{band} is not a band unit in accept")
            if band in below and d <= below[band]:
                issues.append(f"tier {t['id']}: max_decade.{band} {d} does not rise above the tier below ({below[band]})")
            below[band] = d

    # A unit no tier names would leave a deal in it with no tier at all.
    for band in sorted(bands - set(below)):
        issues.append(f"accept: band unit {band} is named by no tier's max_decade")

    budget = source.get("budget")
    if not isinstance(budget, dict) or set(budget) != {"max_asks", "deadline_s"} \
            or not _is_int(budget["max_asks"]) or budget["max_asks"] < 0 \
            or not _is_int(budget["deadline_s"]) or budget["deadline_s"] <= 0:
        issues.append("budget must be exactly {max_asks: <non-negative integer>, deadline_s: <positive integer>}")

    roots = source.get("trust_roots", {})
    if not isinstance(roots, dict) or set(roots) - set(TRUST_ROOT_KEYS) \
            or not all(isinstance(v, list) and all(_nonempty(x) for x in v) for v in roots.values()):
        issues.append(f"trust_roots must map some of {list(TRUST_ROOT_KEYS)} to lists of names")

    rows = source.get("rows")
    if not isinstance(rows, list) or not rows:
        issues.append("rows must not be empty")
        rows = []
    seen = set()
    for i, r in enumerate(rows):
        where = f"rows[{i}]" + (f" ({r['id']!r})" if isinstance(r, dict) and _nonempty(r.get("id")) else "")
        if not isinstance(r, dict):
            issues.append(f"{where} must be a mapping")
            continue
        for k in sorted(set(r) - ROW_KEYS):
            issues.append(f"{where}.{k} is not a row field (known: {sorted(ROW_KEYS)})")
        rid = r.get("id")
        if not isinstance(rid, str) or not ROW_ID_RE.match(rid):
            issues.append(f"{where}.id must be lowercase letters, digits, - or _")
        elif rid in seen:
            issues.append(f"{where}.id is listed twice")
        else:
            seen.add(rid)
        if not _nonempty(r.get("statement")):
            issues.append(f"{where}.statement must be a non-empty string")
        # A field of the wrong type is reported, never hashed.
        src, check, frm = (v if isinstance(v, str) else None for v in (r.get("source"), r.get("check"), r.get("from")))
        if src not in SOURCES:
            issues.append(f"{where}.source {src!r} must be one of {list(SOURCES)}")
        params = r.get("params", {})
        if check not in PREDICATES:
            issues.append(f"{where}.check {check!r} is not an admission predicate")
        elif PREDICATES[check][0] != src:
            issues.append(f"{where}: check {check} reads {PREDICATES[check][0]}, not {src}")
        elif not isinstance(params, dict) or not all(_is_int(v) for v in params.values()):
            issues.append(f"{where}.params must map names to integers")
        else:
            for k in PREDICATES[check][1]:
                if k not in params:
                    issues.append(f"{where}: check {check} needs params.{k}")
            for k in sorted(set(params) - set(PREDICATES[check][1])):
                issues.append(f"{where}: check {check} takes no params.{k}")
            for k in sorted(set(params) & set(PREDICATES[check][1])):
                if not 0 <= params[k] <= PARAM_MAX[k]:
                    issues.append(f"{where}: params.{k} {params[k]} must be from 0 to {PARAM_MAX[k]}")
        if frm is None or frm not in tier_ids:
            issues.append(f"{where}.from {frm!r} is not a tier")
        on_fail = r.get("on_fail")
        if src == "judged":
            # A judged row caps a tier and never decides NO (D-23).
            if not isinstance(on_fail, dict) or set(on_fail) != {"cap"}:
                issues.append(f"{where}: a judged row's on_fail must be {{cap: <tier>}}")
            elif not isinstance(on_fail["cap"], str) or on_fail["cap"] not in tier_ids:
                issues.append(f"{where}: cap {on_fail['cap']!r} is not a tier")
            elif frm in tier_ids and tier_ids.index(on_fail["cap"]) >= tier_ids.index(frm):
                # A cap at or above the row's own tier could never lower one.
                issues.append(f"{where}: cap {on_fail['cap']} must be a tier below from {frm}")
            # A cap is a LIMIT: a pack that yields none would turn it into the
            # missing default, a judged row deciding NO (D-23).
            if "LIMIT" not in outcomes:
                issues.append(f"{where}: a judged row caps a tier, so LIMIT must be in outcomes")
        else:
            on_fail = _outcome(f"{where}.on_fail", on_fail, ON_FAIL, issues)
            if on_fail == "NO" and src not in MAY_DECIDE_NO:
                issues.append(f"{where}: a {src} row may not decide NO; only platform, own_history and "
                              "operator rows do")
            if on_fail == "LIMIT" and tier_ids and frm == tier_ids[0]:
                issues.append(f"{where}: a row from the lowest tier cannot LIMIT; it can decide NO or be recorded")
            if on_fail in ("NO", "LIMIT") and on_fail not in outcomes:
                issues.append(f"{where}.on_fail {on_fail} is not in outcomes")
        ask = r.get("ask")
        if ask is not None:
            # Only a LIMIT row asks (resolution step 6); an ask anywhere else
            # would never be made.
            if on_fail != "LIMIT":
                issues.append(f"{where}: only a LIMIT row may carry an ask")
            if not isinstance(ask, dict) or set(ask) != {"derivation"} or not _nonempty(ask.get("derivation")):
                issues.append(f"{where}.ask must be exactly {{derivation: <name>}}")
            if "ASK" not in outcomes:
                issues.append(f"{where} carries an ask, but ASK is not in outcomes")
    return issues


COMPILED_FORMAT = "admission-pack/v0"


def compile_pack(source):
    """A validated admission pack source -> pack-definition.json, the pinned
    artifact: its pack_id and the SHA-256 of these bytes are what a decision
    cites. The evaluator (capsule-engine#265, Go and Rust) reads only these
    bytes, never the YAML, so PyYAML here is the one YAML reader there is.
    Optional fields are written out (params {}, every trust_roots list), so
    the evaluator has no default to apply."""
    roots = source.get("trust_roots") or {}
    doc = {
        "format": COMPILED_FORMAT,
        "pack_id": source["pack_id"],
        "pack_version": source["pack_version"],
        "outcomes": list(source["outcomes"]),
        "missing": source["missing"],
        "accept": {cur: {"band": u["band"], "scale": u["scale"]} for cur, u in source["accept"].items()},
        "tiers": [{"id": t["id"], "max_decade": dict(t["max_decade"])} for t in source["tiers"]],
        "budget": {"max_asks": source["budget"]["max_asks"], "deadline_s": source["budget"]["deadline_s"]},
        "trust_roots": {k: list(roots.get(k, [])) for k in TRUST_ROOT_KEYS},
        "rows": [],
    }
    if "source" in source:
        doc["source"] = source["source"]
    for r in source["rows"]:
        row = {"id": r["id"], "statement": r["statement"], "source": r["source"], "check": r["check"],
               "params": dict(r.get("params") or {}), "from": r["from"],
               "on_fail": dict(r["on_fail"]) if isinstance(r["on_fail"], dict) else r["on_fail"]}
        if r.get("ask") is not None:
            row["ask"] = {"derivation": r["ask"]["derivation"]}
        doc["rows"].append(row)
    return doc


def compiled_bytes(source):
    """pack-definition.json's bytes: RFC 8785 JCS, no trailing newline."""
    return rfc8785.dumps(compile_pack(source))


def _evidence_rule(r):
    params = ", ".join(f"{k} {v}" for k, v in sorted((r.get("params") or {}).items()))
    rule = f"admission check {r['check']}" + (f" ({params})" if params else "")
    rule += f", from tier {r['from']}"
    on_fail = r["on_fail"]
    if isinstance(on_fail, dict):
        rule += f"; a failure caps the tier at {on_fail['cap']}"
    elif on_fail == "record":
        rule += "; recorded, deciding nothing"
    else:
        rule += f"; a failure gives {on_fail}"
    if r.get("ask"):
        rule += f"; asks for {r['ask']['derivation']}"
    return rule


def from_admission(source):
    """A validated admission pack source -> the Evidence Contract v0 document:
    one requirement per row, its statement and its rule in words."""
    # A row is read before the act, from what was received: a recomputed row
    # needs nothing more; a judged row needs a model (evidence_contract.py's
    # FORWARD_JUDGED with MODEL-ASSISTED).
    requirements = []
    for r in source["rows"]:
        judged = r["source"] == "judged"
        requirements.append({
            "id": r["id"],
            "profile": "outcome",
            "statement": r["statement"],
            "tier": "must_have",
            "evidence_rule": _evidence_rule(r),
            "forward_verdict": "UNAVAILABLE-MODEL-REQUIRED" if judged else "DETERMINISTIC",
            "backward_verdict": "MODEL-ASSISTED" if judged else "DETERMINISTIC",
        })
    return {"id": source["pack_id"], "version": source["pack_version"], "requirements": requirements}
