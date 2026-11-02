#!/usr/bin/env python3
"""Compile a pack source into a daily-judge-and-close spec plus a report
presentation extension, so a person can change the criteria, recompile and rerun
against the same data, and select the report template the results render through.

Relationship to this repo's other two compilers:

  - `evaluation-compiler` (skills/evaluation-compiler/SKILL.md) turns a free-form value proposition
    into a new evaluation bundle from scratch, for a scenario with no existing
    Evidence Contract. A pack already names its criteria, so there is nothing to
    decompose from zero.
  - `evidence-contract-compile` (skills/evidence-contract-compile/SKILL.md) is the
    generic, agent-run prose skill that turns any validated Evidence Contract into
    the same pair of compiled skills this script writes. It says nothing about
    report templates; those are a presentation concern kept outside the contract
    and judging layer, carried as a bundle `extensions` block.

This script is NOT a generic implementation of evidence-contract-compile: it does
not compile an arbitrary contract's counterparty/join/weekly-blind-expert parts. It
is a concrete realization of that skill's clause/tier rules (one clause per judged
criterion decomposed into one axis; `tier: recomputed` rejected unless a fold
answers it; disclosure/sample_policy passed through unchanged), scoped to one
family of contract: an outcomes pack whose clauses are grouped into named
"checks" (a presentational grouping evidence-contract-compile's schema does not
have) plus a selected, switchable report template.

Input: a pack source (YAML; see packs/airline-support-outcomes/pack-source.yaml
for the worked example and field-by-field comments). Output, under --out (must be
exactly `demo/<name>`, matching the depth scripts/run_daily.py's
`--spec.resolve().parents[2]` assumes):

  - compiled.json      -- the specialised daily-judge-and-close spec, the shape
                           scripts/run_daily.py / rollup_day.py run.
  - judge-prompt.md     -- generated judge instructions, one per compiled pack.
  - axes.json           -- the outcome/checks/axes document judge-prompt.md and
                           compiled.json both refer to.
  - presentation.json   -- the bundle presentation extension for the selected
                           report.template (outcome-report/v1 or
                           eu-ai-act-compliance/v1), plus the empty
                           contract-report/v1 opt-in for the packs in
                           CONTRACT_REPORT_PACKS. scripts/wire_presentation.py
                           wires it onto the bundle for the renderer.

Deterministic: the same pack source compiles to byte-identical output every time
(no wall-clock, no randomness) -- see tests/test_pack_compile.py. Refuses an
invalid pack source before writing anything, reporting every issue found, in the
`{"valid": bool, "issues": [...]}` shape `capsulectl contract validate --json`
uses.

A pack source with `scope: {kind: live}` (absent means `after_the_fact`) is a
capsule-engine live pack; scripts/live_pack.py validates it, and `compile` writes
contract.json (the Evidence Contract) and pack-definition.json (the engine's pack
definition and its definition_digest, also printed by `project`) instead of the
four documents above; a fold `file` it names is read relative to the source's
directory, as capsule-engine reads it. A pack source with `scope: {kind: admission}` is an
admission pack (docs/admission-pack-profile-v0.md); scripts/admission_pack.py
validates it, and `compile` writes contract.json and pack-definition.json, the
pinned artifact the evaluator reads.

    python3 scripts/pack_compile.py validate packs/airline-support-outcomes/pack-source.yaml
    python3 scripts/pack_compile.py compile packs/airline-support-outcomes/pack-source.yaml \\
        --out demo/airline-support-outcomes
"""
import argparse
import hashlib
import json
import pathlib
import re
import sys

import yaml

import admission_pack
import live_pack

TIERS = {"judged", "recomputed"}
# A criterion's optional `requirement_tier` (Evidence Contract requirement `tier`):
# whether it decides the overall answer. Distinct from `tier` above (how it is checked).
REQUIREMENT_TIERS = {"must_have", "informational"}

# scripts/rollup.py's CASE_SEPARATOR, repeated here rather than imported so
# this compiler keeps no dependency on the rollup modules: a day document's
# claim id is <case_id>::<clause_id>, so no check or criterion id may carry it.
CASE_SEPARATOR = "::"

# capsule-engine's own closed vocabulary for judge_pin.input_refs (PR #96,
# "judge_pin for mode: judged obligations", `capsule_engine/packs/schema.py`'s
# `NORMALIZED_ACTION_FIELDS`, commit 9069cf70aa562b42c9983d7277ec1ce2e1e34ce5).
# Vendored as a flat constant, not imported: capsule-engine is a separate repo
# this one does not depend on at runtime, only in the cross-check test
# (tests/test_judge_pin_capsule_engine_96.py, tests/fixtures/capsule-engine/).
# A judged criterion's own `judge_input_refs` (below) must be drawn from this
# set -- the same "unregistered is a typo" doctrine this file already applies
# to TIERS/MEASURABILITY -- so a typo'd field name is refused at compile time,
# long before it would reach capsule-engine's own loader.
NORMALIZED_ACTION_FIELDS = frozenset(
    {
        "amount_minor",
        "currency",
        "target",
        "cited_mandate_capsule_id",
        "equivalence_key",
        "model_id",
        "provider",
        "rail",
        "counterparty_account_ref",
        "outgoing_content",
        "recurrence",
    }
)

# Orthogonal to tier (docs/jev-judge.md): tier is checkability (recomputed = a
# stranger can re-run it, judged = trust the model), measurability is corpus
# coverage (is the signal this row needs actually present here at all). A
# semantic row is normally measurability: measured, mode: judged -- declaring
# a judged row declared_not_measured is a category error ("this corpus carries
# no signal for it"), not a description of "we judge it instead of computing
# it deterministically".
MEASURABILITY = {"measured", "declared_not_measured"}

# Rubric switches (scripts/run_daily.py's effective_tier()/effective_claim()):
# a pack source MAY declare a top-level `switches: {flag: bool, ...}` block (passed
# through to compiled.json verbatim -- run_daily.py reads it generically, by
# whatever flag name a clause's own tier_switch/claim_switch names, never a fixed
# list here) plus, per criterion, an optional `tier_switch` ({flag, tier_when_on})
# and/or `claim_switch` ({flag, claim_when_on}) -- validated below only for shape
# and that the flag they name is actually declared in `switches`, so a typo'd flag
# can never compile to a silently-inert switch.


def _strip_strings(obj):
    """YAML's folded (`>`) block scalars keep a single trailing newline; strip
    every string leaf once, right after loading, so no field downstream has to
    remember to do it itself."""
    if isinstance(obj, str):
        return obj.strip()
    if isinstance(obj, list):
        return [_strip_strings(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _strip_strings(v) for k, v in obj.items()}
    return obj


def load_source(text):
    """A pack source's YAML text -> the mapping every other function takes. An
    after-the-fact source has its strings stripped (_strip_strings); a live one
    keeps them as written, because capsule-engine digests a pack's strings
    as they are (`statement: >` keeps its trailing newline, `>-` does not)."""
    source = yaml.safe_load(text)
    # Only a source that is after_the_fact as written is stripped: a kind that is
    # neither (" live ") is left as is and refused by validate_scope, never
    # stripped into a live source.
    return _strip_strings(source) if live_pack.scope_kind(source) == "after_the_fact" else source


def _build_outcome_report_presentation(source):
    checks = [{"id": c["id"], "question": c["question"]} for c in source["checks"]]
    criteria = []
    reason_codes = {}
    for check in source["checks"]:
        for crit in check["criteria"]:
            cid = f"{check['id']}.{crit['id']}"
            criteria.append({
                "id": cid,
                "label": crit["label"],
                "text": crit["text"],
                "tier": crit["tier"],
                "recompute_eligible": bool(crit.get("recompute_eligible", False)),
                "never_out_of_scope": bool(crit.get("never_out_of_scope", False)),
            })
            reason_codes[cid] = crit["label"]  # fallback: criterion's own label, never free-text parsing
    reason_codes.update(source.get("reason_code_overrides") or {})
    report = source["report"]
    return {
        "enabled": True,
        "percentages": bool(report.get("percentages", False)),
        "terms": {"checks": checks, "criteria": criteria},
        "reason_codes": reason_codes,
    }


def _build_eu_ai_act_presentation(source):
    """eu-ai-act-compliance/v1: a check is an OBLIGATION (one article), each
    criterion a TEST under it -- the same checks/criteria shape every other
    template reads, carrying obligation- and test-level metadata (article
    reference, plain-language summary, applicability, method, and an optional
    producer-authored finding template) that only this template's reader
    (agent-action-capsule's compliance card) consumes. Counts, never a
    percentage: there is no "resolved" concept here at all (contrast
    _build_outcome_report_presentation's percentages field, which is
    absent from this template's output on purpose)."""
    obligations = []
    for check in source["checks"]:
        rows = []
        for crit in check["criteria"]:
            row = {
                "criterion_id": f"{check['id']}.{crit['id']}",
                "name": crit.get("card_label") or crit["label"],
                "desc": crit["text"],
                "tier": crit["tier"],
            }
            if crit.get("not_evaluable_note"):
                row["not_evaluable_note"] = crit["not_evaluable_note"]
            if crit.get("finding"):
                row["finding"] = dict(crit["finding"])
            rows.append(row)
        obligations.append({
            "key": check["id"],
            "article": check["article"],
            "title": check["title"],
            "plain": check["plain"],
            "judged_terms": list(check.get("judged_terms") or []),
            "applicability": dict(check["applicability"]),
            "method": check["method"],
            "rows": rows,
        })
    return {
        "enabled": True,
        "regulation": source.get("regulation", "Regulation (EU) 2024/1689"),
        "obligations": obligations,
        "quality_protocol": dict(source.get("quality_protocol") or {}),
    }


# Each pack's name for people, which report titles use. Kept here, keyed by
# pack_id, not in the pack source: the judge pin carries pack_source_digest, a
# hash over the whole pack source, so a field there would move every pin. A pack
# with no entry compiles without a title, and reports fall back to its contract id.
PACK_TITLES = {
    "airline-support-outcomes": "Airline support outcomes",
    "eu-ai-act-obligations": "EU AI Act obligations",
    "asg/everyday-rules": "Everyday Rules",
    "inference-deals": "Inference deals",
}

# A deterministic pack names one of these instead of a judge: the module under
# scripts/evaluators/ that answers every one of its criteria from the sealed
# records, in process, with no model (scripts/report.sh runs it). Unregistered
# is a typo, as with TIERS.
EVALUATORS = frozenset({"inference_deals"})

# The cards `capsulectl book report build --card` renders (evidencebook
# report/report.go `cards`). A deterministic pack names its card directly; a
# judged pack's card follows from its report.template (wire_presentation.py).
REPORT_CARDS = frozenset({"attribution", "human_role", "obligation", "outcome", "process", "quality", "settlement"})

# AAC inference-service history profile v0 section 6.1: a period policy has
# exactly these members.
PERIOD_POLICY_KEYS = ("epoch", "length_s", "min_length_s", "floor", "suppression")

# The report-template registry: this is the "pluggable" seam. Adding a template
# means registering a builder here; selecting one no one registered is a
# validation failure (see validate_source), never a silent fallback to this one.
REPORT_TEMPLATES = {
    "outcome-report/v1": _build_outcome_report_presentation,
    "eu-ai-act-compliance/v1": _build_eu_ai_act_presentation,
}


def _validate_eu_ai_act_fields(source):
    """Extra validation for report.template == "eu-ai-act-compliance/v1" --
    the obligation/test metadata _build_eu_ai_act_presentation reads but the
    generic validate_source() above knows nothing about. Same "absent is
    never pass" discipline: a check missing its article/title/plain/
    applicability/method, or a criterion whose finding block is malformed,
    fails validation here rather than KeyError-ing during compile or (worse)
    silently shipping a presentation.json with a missing field the card
    renders as blank."""
    issues = []
    checks = source.get("checks")
    if not isinstance(checks, list):
        return issues  # the generic validator already flagged this
    for i, check in enumerate(checks):
        if not isinstance(check, dict):
            continue
        where = f"checks[{i}]"
        for key in ("article", "title", "plain", "method"):
            if not isinstance(check.get(key), str) or not check[key].strip():
                issues.append(f"{where}.{key} must be a non-empty string (eu-ai-act-compliance/v1 requires it)")
        applicability = check.get("applicability")
        if not isinstance(applicability, dict) or applicability.get("status") not in ("in_force", "future"):
            issues.append(f"{where}.applicability must be a mapping with status in_force|future")
        elif not isinstance(applicability.get("note"), str) or not applicability["note"].strip():
            issues.append(f"{where}.applicability.note must be a non-empty string")
        if "judged_terms" in check and not isinstance(check["judged_terms"], list):
            issues.append(f"{where}.judged_terms must be a list")
        criteria = check.get("criteria")
        if not isinstance(criteria, list):
            continue  # the generic validator already flagged a missing or non-list criteria
        for j, crit in enumerate(criteria):
            if not isinstance(crit, dict):
                continue
            cwhere = f"{where}.criteria[{j}]"
            finding = crit.get("finding")
            if finding is not None:
                if not isinstance(finding, dict):
                    issues.append(f"{cwhere}.finding must be a mapping")
                    continue
                for key in ("id", "severity", "recommendation", "owner_due"):
                    if not isinstance(finding.get(key), str) or not finding[key].strip():
                        issues.append(f"{cwhere}.finding.{key} must be a non-empty string")
    return issues


REPORT_TEMPLATE_EXTRA_VALIDATORS = {"eu-ai-act-compliance/v1": _validate_eu_ai_act_fields}

# The report settings a pack may carry. Anything else is refused: the report states
# outcomes, and settings that are not about presenting them (pricing a resolution,
# for one) belong to a product that consumes the report, not to the pack.
REPORT_KEYS = ("template", "percentages")

# agent-action-capsule spec/contract-report-v1.md section 1: a producer's opt-in
# to the contract-report view, wired onto the bundle as a closed empty object
# beside the pack's own report.template block (scripts/wire_presentation.py).
CONTRACT_REPORT_KEY = "contract-report/v1"

# The packs that opt in, by pack_id. Kept here rather than as a pack-source
# setting on purpose: the judge pin carries pack_source_digest, a hash over the
# whole pack source (scripts/judge_pin.py), so adding a presentation-only field
# to pack-source.yaml would move both packs' judge pins and start a new pin
# scope for work already judged. Opting in changes presentation.json only.
CONTRACT_REPORT_PACKS = frozenset({"eu-ai-act-obligations", "airline-support-outcomes"})


def _validate_deterministic(source, checks):
    """The rules a deterministic pack (one naming an `evaluator`) adds: no judge
    anywhere, every criterion recomputed by a named fold, and a reporting window
    of whole closed periods under an AAC period policy."""
    issues = []
    if source["evaluator"] not in EVALUATORS:
        issues.append(f"evaluator must be one of {sorted(EVALUATORS)}, got {source['evaluator']!r}")
    if "judge" in source or "judge_batch" in source:
        issues.append("a deterministic pack names an evaluator and no judge: drop judge/judge_batch")
    for i, check in enumerate(checks):
        for j, crit in enumerate(check.get("criteria") or [] if isinstance(check, dict) else []):
            if isinstance(crit, dict) and crit.get("tier") != "recomputed":
                issues.append(f"checks[{i}].criteria[{j}].tier must be 'recomputed' in a deterministic pack")
            if isinstance(crit, dict) and (crit.get("tier_switch") or crit.get("recompute_precheck")):
                issues.append(f"checks[{i}].criteria[{j}]: tier_switch and recompute_precheck need a judge")
    window = source.get("window")
    if not isinstance(window, dict) or set(window) != {"months", "period_policy"}:
        return issues + ["window must be exactly {months, period_policy}"]
    months = window["months"]
    if isinstance(months, bool) or not isinstance(months, int) or months < 1:
        issues.append(f"window.months must be a positive integer, got {months!r}")
    policy = window["period_policy"]
    if not isinstance(policy, dict) or set(policy) != set(PERIOD_POLICY_KEYS):
        return issues + [f"window.period_policy must have exactly {list(PERIOD_POLICY_KEYS)}"]
    for key in ("length_s", "min_length_s", "floor"):
        v = policy[key]
        if isinstance(v, bool) or not isinstance(v, int) or v < 1:
            issues.append(f"window.period_policy.{key} must be a positive integer, got {v!r}")
    if isinstance(policy["length_s"], int) and isinstance(policy["min_length_s"], int) \
            and policy["length_s"] < policy["min_length_s"]:
        issues.append("window.period_policy.length_s must be at least min_length_s")
    if policy["suppression"] != "complementary":
        issues.append("window.period_policy.suppression must be 'complementary'")
    if not isinstance(policy["epoch"], str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", policy["epoch"]):
        issues.append("window.period_policy.epoch must be an RFC 3339 UTC time like 2026-01-05T00:00:00Z")
    return issues


def validate_source(source, base_dir=None):
    """Every issue found, not just the first -- same `issues[]` convention
    evidence-contract-compile's own `capsulectl contract validate --json` uses.
    A failing validation means nothing downstream is compiled. base_dir is the
    source's directory, which a live pack's fold files are read relative to."""
    issues = []
    if not isinstance(source, dict):
        return ["pack source must be a mapping"]

    # `scope.kind` (absent means after_the_fact, which is everything below).
    scope_issues = live_pack.validate_scope(source)
    if scope_issues:
        return scope_issues
    if live_pack.is_live(source):
        return live_pack.validate_live(source, base_dir)
    if admission_pack.is_admission(source):
        return admission_pack.validate_admission(source) or admission_pack.compile_issues(source)

    def require_str(key):
        v = source.get(key)
        if not isinstance(v, str) or not v.strip():
            issues.append(f"{key} must be a non-empty string")

    for key in ("pack_id", "pack_version", "rubric_version", "outcome_statement", "resolution_rule", "counterparty"):
        require_str(key)

    # contract_ref (build_compiled_json: f"{pack_id}@{pack_version}") must match the
    # Evidence Result v0 ContractRef pattern "^[^@\\s]+@[^@\\s]+$": an "@" or whitespace
    # in either half would compile a pack that `capsulectl book result build` refuses.
    for key in ("pack_id", "pack_version"):
        v = source.get(key)
        if isinstance(v, str) and ("@" in v or re.search(r"\s", v)):
            issues.append(f"{key} must not contain '@' or whitespace (used verbatim in contract_ref: <pack_id>@<pack_version>)")

    switches = source.get("switches")
    if switches is not None:
        if not isinstance(switches, dict):
            issues.append("switches must be a mapping of flag name -> boolean")
            switches = {}
        else:
            for flag, val in switches.items():
                if not isinstance(val, bool):
                    issues.append(f"switches.{flag} must be a boolean, got {val!r}")
            if "not_applicable_verdict" in switches:
                issues.append("switches.not_applicable_verdict is a retired name: use out_of_scope_verdict "
                              "(the criterion does not apply here -- never met, never not_met)")
    else:
        switches = {}

    if "judge_batch" in source and not isinstance(source["judge_batch"], bool):
        issues.append("judge_batch must be a boolean")

    checks = source.get("checks")
    if not isinstance(checks, list) or not checks:
        issues.append("checks must be a non-empty list")
        checks = []

    seen_check_ids, seen_clause_ids, seen_rule_ids = set(), set(), set()
    for i, check in enumerate(checks):
        where = f"checks[{i}]"
        if not isinstance(check, dict):
            issues.append(f"{where} must be a mapping")
            continue
        check_id = check.get("id")
        if not isinstance(check_id, str) or not check_id.strip():
            issues.append(f"{where}.id must be a non-empty string")
            check_id = None
        elif CASE_SEPARATOR in check_id:
            issues.append(f"{where}.id {check_id!r} contains {CASE_SEPARATOR!r}, the separator a day "
                          "document's claim ids use between case id and clause id")
            check_id = None
        elif check_id in seen_check_ids:
            issues.append(f"duplicate check id: {check_id!r}")
        else:
            seen_check_ids.add(check_id)
        if not isinstance(check.get("question"), str) or not check["question"].strip():
            issues.append(f"{where}.question must be a non-empty string")

        criteria = check.get("criteria")
        if not isinstance(criteria, list) or not criteria:
            issues.append(f"{where}.criteria must be a non-empty list")
            criteria = []
        for j, crit in enumerate(criteria):
            cwhere = f"{where}.criteria[{j}]"
            if not isinstance(crit, dict):
                issues.append(f"{cwhere} must be a mapping")
                continue
            crit_id = crit.get("id")
            if not isinstance(crit_id, str) or not crit_id.strip():
                issues.append(f"{cwhere}.id must be a non-empty string")
                crit_id = None
            elif CASE_SEPARATOR in crit_id:
                # A day document's claim id is <case_id>::<clause_id>, regrouped on
                # the LAST "::" (scripts/result_v0.py:headline_from_result): a clause
                # id carrying it would split one case into two.
                issues.append(f"{cwhere}.id {crit_id!r} contains {CASE_SEPARATOR!r}, the separator a day "
                              "document's claim ids use between case id and clause id")
                crit_id = None
            for key in ("label", "text"):
                if not isinstance(crit.get(key), str) or not crit[key].strip():
                    issues.append(f"{cwhere}.{key} must be a non-empty string")
            if "requirement_tier" in crit:
                rt = crit["requirement_tier"]
                if not isinstance(rt, str) or rt not in REQUIREMENT_TIERS:
                    issues.append(f"{cwhere}.requirement_tier must be one of {sorted(REQUIREMENT_TIERS)}, got {rt!r}")
            tier = crit.get("tier")
            if tier not in TIERS:
                issues.append(f"{cwhere}.tier must be one of {sorted(TIERS)}, got {tier!r}")
            elif tier == "recomputed" and not crit.get("fold_id"):
                issues.append(
                    f"{cwhere}: tier 'recomputed' needs a fold_id naming the "
                    "capsulectl-engine fold that answers it -- a recomputed clause naming "
                    "none is rejected here rather than approximated with a judge "
                    "(skills/evidence-contract-compile/SKILL.md's own rule for this tier). "
                    "This only checks that a fold_id is named, not that it matches a real, "
                    "registered fold -- the capsulectl-engine plugin that would run one "
                    "doesn't exist yet (skills/README.md, \"Still pending\")."
                )
            if "recompute_eligible" in crit and not isinstance(crit["recompute_eligible"], bool):
                issues.append(f"{cwhere}.recompute_eligible must be a boolean")
            if "never_out_of_scope" in crit and not isinstance(crit["never_out_of_scope"], bool):
                issues.append(f"{cwhere}.never_out_of_scope must be a boolean")
            if "never_not_applicable" in crit:
                issues.append(f"{cwhere}.never_not_applicable is a retired name: use never_out_of_scope")
            # Source-rule provenance, for a pack whose criteria are rows of some
            # outside rule set (e.g. packs/everyday-rules) rather than hand-authored
            # outcome criteria: optional, generic, never airline-specific.
            if "rule_id" in crit and (not isinstance(crit["rule_id"], str) or not crit["rule_id"].strip()):
                issues.append(f"{cwhere}.rule_id must be a non-empty string")
            elif crit.get("rule_id") in seen_rule_ids:
                # Two judged clauses sharing a rule_id would collapse to one entry
                # in scripts/judge_bundle.py's select_clauses() by_rule_id lookup,
                # silently dropping whichever criterion lost the collision.
                issues.append(f"duplicate rule_id across the pack: {crit['rule_id']!r}")
            elif crit.get("rule_id"):
                seen_rule_ids.add(crit["rule_id"])
            if "measurability" in crit and crit["measurability"] not in MEASURABILITY:
                issues.append(f"{cwhere}.measurability must be one of {sorted(MEASURABILITY)}, "
                              f"got {crit['measurability']!r}")
            if "rule_half" in crit and not isinstance(crit["rule_half"], bool):
                issues.append(f"{cwhere}.rule_half must be a boolean")
            if "scope_note" in crit and (not isinstance(crit["scope_note"], str) or not crit["scope_note"].strip()):
                issues.append(f"{cwhere}.scope_note must be a non-empty string")
            # Presentation-only row text for the report card, when it must say
            # more than the label (eu-ai-act-compliance/v1 only); never judged.
            if "card_label" in crit and (not isinstance(crit["card_label"], str) or not crit["card_label"].strip()):
                issues.append(f"{cwhere}.card_label must be a non-empty string")
            # A deterministic pre-check that runs before the judge on a judged
            # criterion and may replace its verdict for a session
            # (scripts/recompute.py's RECOMPUTE_PRECHECKS, read by run_daily.py).
            # Named here, checked against the registry there, at run time.
            if "recompute_precheck" in crit:
                if not isinstance(crit["recompute_precheck"], str) or not crit["recompute_precheck"].strip():
                    issues.append(f"{cwhere}.recompute_precheck must be a non-empty string")
                elif tier != "judged":
                    issues.append(f"{cwhere}.recompute_precheck applies only to a tier 'judged' criterion")
            # What an out_of_scope answer means for this row (e.g. "the situation
            # the rule is about never came up"), compiled into the claim beside
            # met/not_met -- so a row whose met_means names a situation is never
            # answered met when that situation never arose. Only where the row
            # can be answered out_of_scope at all.
            if "out_of_scope_means" in crit:
                oos = crit["out_of_scope_means"]
                if not isinstance(oos, str) or not oos.strip():
                    issues.append(f"{cwhere}.out_of_scope_means must be a non-empty string")
                elif not switches.get("out_of_scope_verdict"):
                    issues.append(f"{cwhere}.out_of_scope_means is set but switches.out_of_scope_verdict is "
                                  "off: the judge is never offered out_of_scope")
                elif crit.get("never_out_of_scope"):
                    issues.append(f"{cwhere}.out_of_scope_means contradicts never_out_of_scope")
            # The normalized action fields this criterion's own judge prompt
            # declares it reads -- capsule-engine #96's input_refs vocabulary
            # (NORMALIZED_ACTION_FIELDS, above). Optional: a criterion whose
            # prompt reads nothing in that closed vocabulary (most of this
            # pack's rows -- see packs/everyday-rules/pack-source.yaml's own
            # note) declares none; scripts/judge_bundle.py's
            # declared_input_refs() unions whatever the clauses actually
            # judged in one call declare, and refuses to seal a judge_pin
            # when that union is empty rather than inventing a field name.
            if "judge_input_refs" in crit:
                refs = crit["judge_input_refs"]
                if not isinstance(refs, list) or not refs or not all(isinstance(r, str) for r in refs):
                    issues.append(f"{cwhere}.judge_input_refs must be a non-empty list of strings")
                else:
                    bad = sorted(set(refs) - NORMALIZED_ACTION_FIELDS)
                    if bad:
                        issues.append(f"{cwhere}.judge_input_refs names {bad!r}, not in capsule-engine's own "
                                      f"normalized action fields {sorted(NORMALIZED_ACTION_FIELDS)}")
                    if len(set(refs)) != len(refs):
                        issues.append(f"{cwhere}.judge_input_refs lists a field more than once")
            tier_switch = crit.get("tier_switch")
            if tier_switch is not None:
                if not isinstance(tier_switch, dict):
                    issues.append(f"{cwhere}.tier_switch must be a mapping")
                else:
                    flag = tier_switch.get("flag")
                    if not isinstance(flag, str) or not flag.strip():
                        issues.append(f"{cwhere}.tier_switch.flag must be a non-empty string")
                    elif flag not in switches:
                        issues.append(
                            f"{cwhere}.tier_switch.flag {flag!r} is not declared in the top-level "
                            "switches block -- a switch no one can ever turn on compiles to a silently "
                            "inert field"
                        )
                    if tier_switch.get("tier_when_on") not in TIERS:
                        issues.append(f"{cwhere}.tier_switch.tier_when_on must be one of {sorted(TIERS)}")
            claim_switch = crit.get("claim_switch")
            if claim_switch is not None:
                if not isinstance(claim_switch, dict):
                    issues.append(f"{cwhere}.claim_switch must be a mapping")
                else:
                    flag = claim_switch.get("flag")
                    if not isinstance(flag, str) or not flag.strip():
                        issues.append(f"{cwhere}.claim_switch.flag must be a non-empty string")
                    elif flag not in switches:
                        issues.append(
                            f"{cwhere}.claim_switch.flag {flag!r} is not declared in the top-level "
                            "switches block -- a switch no one can ever turn on compiles to a silently "
                            "inert field"
                        )
                    claim_when_on = claim_switch.get("claim_when_on")
                    if not isinstance(claim_when_on, str) or not claim_when_on.strip():
                        issues.append(f"{cwhere}.claim_switch.claim_when_on must be a non-empty string")
            if check_id and crit_id:
                full_id = f"{check_id}.{crit_id}"
                if full_id in seen_clause_ids:
                    issues.append(f"duplicate criterion id across the pack: {full_id!r}")
                seen_clause_ids.add(full_id)

    evaluator = source.get("evaluator")
    judge = source.get("judge")
    if evaluator is not None:
        issues.extend(_validate_deterministic(source, checks))
    elif not isinstance(judge, dict) or not isinstance(judge.get("model_id"), str) or not judge.get("model_id", "").strip():
        issues.append("judge.model_id must be a non-empty string")
    else:
        if "sampling_params" in judge and not isinstance(judge["sampling_params"], dict):
            issues.append("judge.sampling_params must be a mapping")
        min_conf = judge.get("min_confidence")
        if min_conf is not None and (isinstance(min_conf, bool) or not isinstance(min_conf, (int, float))
                                     or not 0 < min_conf <= 1):
            issues.append(f"judge.min_confidence must be a number in (0, 1], or absent; got {min_conf!r}")
        # Optional: the reference files the judge and the recompute checkers read
        # besides the conversation (scripts/run_daily.py's judge_reference_files(),
        # which re-checks the same rules at run time and defaults to tau2 airline's
        # files when a pack names none -- every pack written before this field).
        ref_files = judge.get("reference_files")
        if ref_files is not None:
            if not isinstance(ref_files, dict) or set(ref_files) != {"policy", "booking_db"}:
                issues.append("judge.reference_files must name exactly 'policy' and 'booking_db'")
            else:
                for key, value in sorted(ref_files.items()):
                    if not isinstance(value, str) or not value.strip():
                        issues.append(f"judge.reference_files.{key} must be a non-empty path")
                    elif (pathlib.PurePosixPath(value).is_absolute()
                          or ".." in pathlib.PurePosixPath(value).parts):
                        issues.append(f"judge.reference_files.{key} must be relative to the repo root "
                                      f"with no '..': {value!r}")
        # Pack-source-authored evidence description: build_judge_prompt() names exactly
        # what the judge is given here, never a hardcoded assumption (e.g. a
        # transcript, an airline policy file) -- a pack whose judge reads something
        # else entirely (a disclosed-facts bundle, no transcript at all) names its own
        # evidence and citation wording instead. All three are optional: a pack that
        # names none of them (airline's own pack-source.yaml, unchanged since before
        # these fields existed) gets _LEGACY_JUDGE_PROMPT_FIELDS' airline wording from
        # build_judge_prompt() instead -- so airline's compiled judge-prompt.md, and
        # the pin that hashes it, never move. A pack that names any of the three must
        # name all three (never a silent partial default).
        named = {k for k in ("subject", "evidence", "citation_note") if k in judge}
        if named and named != {"subject", "evidence", "citation_note"}:
            issues.append("judge.subject/evidence/citation_note must be named together or not at all "
                          f"(named only {sorted(named)!r}); omit all three to use the legacy wording")
        elif named:
            if not isinstance(judge.get("subject"), str) or not judge.get("subject", "").strip():
                issues.append("judge.subject must be a non-empty string: what the judge is given one of per "
                              "request (e.g. 'one recorded conversation', 'one disclosed evidence bundle')")
            evidence = judge.get("evidence")
            if not isinstance(evidence, list) or not evidence or not all(
                    isinstance(e, str) and e.strip() for e in evidence):
                issues.append("judge.evidence must be a non-empty list of non-empty strings naming what the "
                              "judge is given to decide from")
            if not isinstance(judge.get("citation_note"), str) or not judge.get("citation_note", "").strip():
                issues.append("judge.citation_note must be a non-empty string: what the judge should cite, "
                              "in this pack's own evidence vocabulary (turns and tool results, disclosed "
                              "bundle records, ...)")

    report = source.get("report")
    if not isinstance(report, dict):
        issues.append("report must be a mapping")
    elif evaluator is not None:
        if set(report) != {"card"} or report.get("card") not in REPORT_CARDS:
            issues.append(f"report must be exactly {{card: <one of {sorted(REPORT_CARDS)}>}} in a deterministic "
                          "pack: it has no report template")
    else:
        template = report.get("template")
        if template not in REPORT_TEMPLATES:
            issues.append(f"report.template {template!r} is not a known template; known: {sorted(REPORT_TEMPLATES)}")
        elif template in REPORT_TEMPLATE_EXTRA_VALIDATORS:
            issues.extend(REPORT_TEMPLATE_EXTRA_VALIDATORS[template](source))
        if "percentages" in report and not isinstance(report["percentages"], bool):
            issues.append("report.percentages must be a boolean")
        for key in sorted(set(report) - set(REPORT_KEYS)):
            issues.append(f"report.{key} is not a report setting (known: {list(REPORT_KEYS)}); anything "
                          "beyond presenting outcomes belongs to a product that consumes the report")

    reason_overrides = source.get("reason_code_overrides")
    if reason_overrides is not None and not isinstance(reason_overrides, dict):
        issues.append("reason_code_overrides must be a mapping")

    disclosure = source.get("disclosure")
    if disclosure is not None:
        if not isinstance(disclosure, dict):
            issues.append("disclosure must be a mapping")
        elif "suppress" in disclosure and not isinstance(disclosure["suppress"], list):
            issues.append("disclosure.suppress must be a list")

    sample_policy = source.get("sample_policy")
    if sample_policy is not None and not isinstance(sample_policy, dict):
        issues.append("sample_policy must be a mapping")

    return issues


def source_digest(source):
    """A content digest of the whole pack source -- independent of whether a
    person remembered to bump rubric_version, this changes the instant any field
    changes, so two compiled outputs are provably from different sources."""
    return hashlib.sha256(json.dumps(source, sort_keys=True, default=str).encode()).hexdigest()



def judge_claim(crit):
    """The text the judge reads for one criterion: the rule text verbatim, then,
    when the pack gives one, a single explicit question and what met / not_met
    mean for it. Rule texts are often written as obligations ("Ask when X"), so
    without the question a judge can answer two different questions -- "did X
    happen?" or "was the obligation honored?" -- and "met" then means opposite
    things. Packs without judge_question (airline) keep the plain rule text, so
    their compiled output is unchanged."""
    q = crit.get("judge_question")
    if not q:
        return crit["text"]
    parts = [crit["text"].strip(), "", "Question: " + q.strip()]
    if crit.get("met_means"):
        parts.append("Answer met when: " + crit["met_means"].strip() + ".")
    if crit.get("not_met_means"):
        parts.append("Answer not_met when: " + crit["not_met_means"].strip() + ".")
    if crit.get("out_of_scope_means"):
        parts.append("Answer out_of_scope when: " + crit["out_of_scope_means"].strip() + ".")
    if crit.get("scope_note"):
        parts.append("Scope: " + " ".join(crit["scope_note"].split()))
    return "\n".join(parts)

def build_clauses(source):
    clauses = []
    for check in source["checks"]:
        for crit in check["criteria"]:
            clause = {
                "id": f"{check['id']}.{crit['id']}",
                "check_id": check["id"],
                "check_question": check["question"],
                "label": crit["label"],
                "claim": judge_claim(crit),
                "tier": crit["tier"],
                "recompute_eligible": bool(crit.get("recompute_eligible", False)),
                "recompute_note": crit.get("recompute_note", ""),
            }
            if crit.get("never_out_of_scope"):
                clause["never_out_of_scope"] = True
            if crit.get("requirement_tier") == "informational":
                # Only the tier that changes the rollup is written; a clause without it decides.
                clause["requirement_tier"] = "informational"
            if crit.get("rule_id"):
                clause["rule_id"] = crit["rule_id"]
            if crit.get("measurability"):
                clause["measurability"] = crit["measurability"]
            if crit.get("rule_half"):
                clause["rule_half"] = True
            if crit.get("scope_note"):
                clause["scope_note"] = crit["scope_note"]
            if crit.get("recompute_precheck"):
                clause["recompute_precheck"] = crit["recompute_precheck"]
            if crit.get("judge_input_refs"):
                clause["judge_input_refs"] = list(crit["judge_input_refs"])
            if crit.get("tier_switch"):
                clause["tier_switch"] = dict(crit["tier_switch"])
            if crit.get("claim_switch"):
                clause["claim_switch"] = dict(crit["claim_switch"])
            clauses.append(clause)
    return clauses


def build_deterministic_compiled_json(source):
    """compiled.json for a pack that names an evaluator: its clauses (each with
    the fold that answers it), the window, the card, and no judge block, so no
    judge prompt, axes or judge pin exist for it. scripts/report.sh runs
    scripts/evaluators/<evaluator>.py over it."""
    clauses = build_clauses(source)
    folds = {f"{check['id']}.{crit['id']}": crit["fold_id"]
             for check in source["checks"] for crit in check["criteria"]}
    for clause in clauses:
        clause["fold_id"] = folds[clause["id"]]
    compiled = {
        "contract": f"{source['pack_id']}/v1",
        "contract_version": f"rubric-v{source['rubric_version']}",
        "contract_ref": f"{source['pack_id']}@{source['pack_version']}",
        "outcome_statement": source["outcome_statement"],
        "resolution_rule": source["resolution_rule"],
        "counterparty": source["counterparty"],
        "counterparty_note": source.get("counterparty_note", ""),
        "source": source.get("source", ""),
        "decision_note": source.get("decision_note", ""),
        "evaluator": source["evaluator"],
        "window": source["window"],
        "clauses": clauses,
        "presentation": {"card": source["report"]["card"]},
        "disclosure": source.get("disclosure") or {"suppress": []},
        "pack_source_digest": source_digest(source),
    }
    if source["pack_id"] in PACK_TITLES:
        compiled["title"] = PACK_TITLES[source["pack_id"]]
    if source.get("switches"):
        compiled["switches"] = dict(source["switches"])
    return compiled


def build_compiled_json(source, out_rel):
    clauses = build_clauses(source)
    compiled = {
        "contract": f"{source['pack_id']}/v1",
        "contract_version": f"rubric-v{source['rubric_version']}",
        "contract_ref": f"{source['pack_id']}@{source['pack_version']}",
        "outcome_statement": source["outcome_statement"],
        "resolution_rule": source["resolution_rule"],
        "counterparty": source["counterparty"],
        "counterparty_note": source.get("counterparty_note", ""),
        "source": source.get("source", ""),
        "decision_note": source.get("decision_note", ""),
        "clauses": clauses,
        "judge": {
            "prompt": f"{out_rel}/judge-prompt.md",
            "axes": f"{out_rel}/axes.json",
            "model_id": source["judge"]["model_id"],
            "sampling_params": source["judge"].get("sampling_params") or {},
        },
        "sample_policy": source.get("sample_policy") or {},
        "disclosure": source.get("disclosure") or {"suppress": []},
        "pack_source_digest": source_digest(source),
    }
    # Rubric switches: only present when the pack source declares them; a pack with
    # none compiles without the block, and scripts/run_daily.py reads an absent
    # "switches" as an empty one.
    if source["judge"].get("min_confidence") is not None:
        compiled["judge"]["min_confidence"] = source["judge"]["min_confidence"]
    if source["judge"].get("reference_files") is not None:
        compiled["judge"]["reference_files"] = dict(source["judge"]["reference_files"])
    if source["pack_id"] in PACK_TITLES:
        compiled["title"] = PACK_TITLES[source["pack_id"]]
    if source.get("switches"):
        compiled["switches"] = dict(source["switches"])
    if source.get("switches_note"):
        compiled["switches_note"] = source["switches_note"]
    if "judge_batch" in source:
        compiled["judge_batch"] = bool(source["judge_batch"])
    if source.get("judge_batch_note"):
        compiled["judge_batch_note"] = source["judge_batch_note"]
    return compiled


def build_axes_json(source):
    checks = [{"id": c["id"], "question": c["question"]} for c in source["checks"]]
    axes = []
    for check in source["checks"]:
        for crit in check["criteria"]:
            text = crit["text"].rstrip(".")
            pass_text = text[:1].lower() + text[1:] if text else text
            axes.append({"id": f"{check['id']}.{crit['id']}", "check_id": check["id"],
                         "role": "required", "pass": pass_text})
    return {
        "outcome": source["pack_id"],
        "outcome_statement": source["outcome_statement"],
        "rule": (f"all {len(axes)} axes required -- resolved only when every one passes"
                 if source["report"].get("template") != "eu-ai-act-compliance/v1"
                 else f"{len(axes)} tests, each reported as a count of sessions; no resolved roll-up"),
        "checks": checks,
        "axes": axes,
    }


def _join_evidence(evidence):
    """"a, b and c" -- the same house join style build_eval()'s callers expect
    read as prose, for any count of evidence items a pack source names."""
    if len(evidence) == 1:
        return evidence[0]
    return ", ".join(evidence[:-1]) + " and " + evidence[-1]


# What a pack source gets when it names none of judge.subject/evidence/citation_note
# -- airline-support-outcomes' own pack-source.yaml, unchanged since before these
# fields existed. The verdict bullets ride along as one set with these three: a
# pack that is transcript-shaped also gets "the transcript" wording there, never a
# generic "the evidence" that a transcript-reading judge never actually said.
# Changing any of these moves airline's judge-prompt.md, and the judge pin that
# hashes it (scripts/judge_pin.py's prompt_digest) -- see tests/test_pack_compile.py
# (AirlinePinUnchanged, CommittedOutputsAreCompilerOutput).
_LEGACY_JUDGE_SUBJECT = "one recorded conversation"
_LEGACY_JUDGE_EVIDENCE = [
    "the conversation (`agent_interaction.messages` -- customer and agent turns, tool calls and their "
    "results, in order)",
    "the airline policy (`airline-data/policy.md`, passed to you as text)",
]
_LEGACY_JUDGE_CITATION_NOTE = "Cite the specific turns and tool results you relied on."
_LEGACY_VERDICT_BULLETS = (
    "- `met` -- the transcript shows the criterion was satisfied.",
    "- `not_met` -- the transcript shows it was not.",
    "- `not_evaluable` -- the transcript does not contain enough evidence to decide either "
    "way. Use this only when the evidence genuinely is not there, not as a hedge.",
)
_GENERIC_VERDICT_BULLETS = (
    "- `met` -- the evidence shows the criterion was satisfied.",
    "- `not_met` -- the evidence shows it was not.",
    "- `not_evaluable` -- the evidence does not contain enough information to decide either "
    "way. Use this only when the evidence genuinely is not there, not as a hedge.",
)


def build_judge_prompt(source, out_rel):
    checks = source["checks"]
    n = sum(len(c["criteria"]) for c in checks)
    pack_label = f"{source['pack_id']} rubric v{source['rubric_version']}"
    resolution_rule = source["resolution_rule"]
    resolution_rule = resolution_rule[:1].upper() + resolution_rule[1:]
    judge = source["judge"]
    if "subject" in judge:
        subject, evidence, citation_note = judge["subject"], judge["evidence"], judge["citation_note"]
        verdict_bullets = _GENERIC_VERDICT_BULLETS
    else:
        subject, evidence, citation_note = _LEGACY_JUDGE_SUBJECT, _LEGACY_JUDGE_EVIDENCE, _LEGACY_JUDGE_CITATION_NOTE
        verdict_bullets = _LEGACY_VERDICT_BULLETS
    lines = [
        f"You judge {subject} against one criterion, one of the {n} that make up "
        f"{pack_label} (`{out_rel}/compiled.json`). The overall outcome these {n} exist to test: "
        f'"{source["outcome_statement"]}". {resolution_rule} -- you are answering for exactly one of '
        "them, never the whole outcome.",
        "",
        f"The {n} sit under {len(checks)} checks:",
        "",
    ]
    for check in checks:
        summary = "; ".join(c["label"][:1].lower() + c["label"][1:] for c in check["criteria"])
        summary = summary[:1].upper() + summary[1:]
        lines.append(f"- **{check['id']}** -- \"{check['question']}\" {summary}.")
    lines += [
        "",
        "Your request names one clause (`clause.id`, `clause.check_id`, `clause.claim`) from "
        f"`{out_rel}/axes.json`'s {n} axes -- judge that claim, and that claim only.",
        "",
        f"Evidence you may use: {_join_evidence(evidence)}. You are not given, "
        "and must not look for, any graded outcome or answer key.",
        "",
        "Answer with exactly one verdict:",
        "",
        *verdict_bullets,
        "",
        citation_note,
        "",
    ]
    return "\n".join(lines)


def build_presentation_json(source):
    template = source["report"]["template"]
    presentation = {template: REPORT_TEMPLATES[template](source)}
    if source.get("pack_id") in CONTRACT_REPORT_PACKS:
        # The closed empty object agent-action-capsule spec/contract-report-v1.md
        # section 1 defines: never words, data or flags, just the opt-in.
        presentation[CONTRACT_REPORT_KEY] = {}
    return presentation


def compile_pack(source, out_rel):
    """Pure: source + the output path string -> the four generated documents
    (for a deterministic pack, compiled.json and three Nones: it has no judge
    prompt, axes or presentation block). No filesystem access -- tests call
    this directly to check determinism and content without touching disk."""
    if source.get("evaluator") is not None:
        return build_deterministic_compiled_json(source), None, None, None
    return (
        build_compiled_json(source, out_rel),
        build_axes_json(source),
        build_judge_prompt(source, out_rel),
        build_presentation_json(source),
    )


def write_pack(source, out_dir, out_rel):
    compiled, axes, prompt, presentation = compile_pack(source, out_rel)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "compiled.json").write_text(json.dumps(compiled, indent=2) + "\n")
    if axes is None:
        return compiled
    (out_dir / "axes.json").write_text(json.dumps(axes, indent=2) + "\n")
    (out_dir / "judge-prompt.md").write_text(prompt)
    (out_dir / "presentation.json").write_text(json.dumps(presentation, indent=2) + "\n")
    return compiled


def write_live_pack(source, out_dir, base_dir=None):
    """A live pack compiles to its Evidence Contract and the projection to the
    engine's pack definition, not to the four after-the-fact documents."""
    import evidence_contract  # imports this module, so not at the top
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "contract.json").write_bytes(evidence_contract.to_bytes(live_pack.from_live(source)))
    (out_dir / "pack-definition.json").write_bytes(live_pack.projection_bytes(source, base_dir))


def write_admission_pack(source, out_dir):
    """An admission pack compiles to its Evidence Contract and pack-definition.json,
    the pinned artifact capsule-engine#265's evaluator reads (JCS bytes, cited by
    pack_id and their SHA-256)."""
    import evidence_contract  # imports this module, so not at the top
    out_dir.mkdir(parents=True, exist_ok=True)
    # Both are built before either is written, so a failure leaves no half.
    contract = evidence_contract.to_bytes(admission_pack.from_admission(source))
    pinned = admission_pack.compiled_bytes(source)
    (out_dir / "contract.json").write_bytes(contract)
    (out_dir / "pack-definition.json").write_bytes(pinned)


def resolve_out_dir(out_arg):
    """--out must resolve inside this repo's root. A path under `demo/` must be
    exactly `demo/<name>` (two segments): scripts/run_daily.py derives its own repo
    root as `args.spec.resolve().parents[2]` from wherever --spec sits, which only
    lands on the real root at that exact depth -- a pack compiled for run_daily.py
    keeps that constraint. A pack compiled anywhere else carries no such depth rule:
    nothing outside demo/ derives a repo root from the compiled spec's own path
    (scripts/judge_bundle.py, for one, takes --pack as a plain path and never
    does that derivation), so a pack that is not airline's -- and not meant for
    run_daily.py at all -- compiles to wherever its own source names, e.g.
    packs/everyday-rules/compiled/.
    Returns (out_dir_abs, out_rel) or raises ValueError with the reason."""
    root = pathlib.Path(__file__).resolve().parents[1]
    out_abs = (root / out_arg) if not out_arg.is_absolute() else out_arg
    try:
        out_rel = out_abs.resolve().relative_to(root).as_posix()
    except ValueError:
        raise ValueError(f"--out must be inside the repo root ({root})")
    if out_rel == ".":
        raise ValueError(f"--out must not be the repo root itself ({root}): a compiled pack's four files "
                         "would land directly among the repo's own top-level files")
    parts = out_rel.split("/")
    if parts[0] == "demo" and len(parts) != 2:
        raise ValueError(
            f"a demo/ pack's --out must be exactly demo/<name> (got {out_rel!r}): scripts/run_daily.py "
            "resolves its repo root as --spec.resolve().parents[2], which assumes this exact depth"
        )
    if len(parts) < 2:
        raise ValueError(
            f"--out must be at least two path segments deep (got {out_rel!r}): write_pack() always writes "
            "its four files directly into --out, so a single top-level segment would write them straight "
            "into (and over anything already in) one of this repo's own top-level directories"
        )
    return out_abs, out_rel


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_validate = sub.add_parser("validate", help="validate a pack source; reports issues[] without compiling")
    p_validate.add_argument("source", type=pathlib.Path)

    p_compile = sub.add_parser("compile", help="validate, then compile a pack source")
    p_compile.add_argument("source", type=pathlib.Path)
    p_compile.add_argument("--out", type=pathlib.Path, required=True)

    p_project = sub.add_parser("project", help="a live pack: print the capsule-engine pack definition and its definition_digest")
    p_project.add_argument("source", type=pathlib.Path)

    args = ap.parse_args(argv)
    text = args.source.read_text()
    source = load_source(text)
    issues = validate_source(source, args.source.parent)
    if admission_pack.is_admission(source):
        issues = admission_pack.text_issues(text) + issues

    if args.cmd == "validate":
        print(json.dumps({"valid": not issues, "issues": issues}, indent=2))
        return 0 if not issues else 1

    if issues:
        print(json.dumps({"valid": False, "issues": issues}, indent=2))
        return 1

    if args.cmd == "project":
        if not live_pack.is_live(source):
            print(json.dumps({"valid": False, "issues": ["project needs a pack source with scope.kind: live"]}, indent=2))
            return 1
        sys.stdout.buffer.write(live_pack.projection_bytes(source, args.source.parent))
        return 0

    try:
        out_abs, out_rel = resolve_out_dir(args.out)
    except ValueError as e:
        print(json.dumps({"valid": False, "issues": [str(e)]}, indent=2))
        return 1

    if live_pack.is_live(source):
        write_live_pack(source, out_abs, args.source.parent)
        print(json.dumps({
            "valid": True,
            "pack_id": source["pack_id"],
            "pack_version": source["pack_version"],
            "scope": "live",
            "out": out_rel,
            "files": [f"{out_rel}/contract.json", f"{out_rel}/pack-definition.json"],
        }, indent=2))
        return 0

    if admission_pack.is_admission(source):
        write_admission_pack(source, out_abs)
        print(json.dumps({
            "valid": True,
            "pack_id": source["pack_id"],
            "pack_version": source["pack_version"],
            "scope": "admission",
            "out": out_rel,
            "files": [f"{out_rel}/contract.json", f"{out_rel}/pack-definition.json"],
            "definition_digest": hashlib.sha256(admission_pack.compiled_bytes(source)).hexdigest(),
        }, indent=2))
        return 0

    compiled = write_pack(source, out_abs, out_rel)
    print(json.dumps({
        "valid": True,
        "pack_id": source["pack_id"],
        "pack_version": source["pack_version"],
        "rubric_version": source["rubric_version"],
        "contract": compiled["contract"],
        "contract_ref": compiled["contract_ref"],
        "pack_source_digest": compiled["pack_source_digest"],
        "clauses": len(compiled["clauses"]),
        "out": out_rel,
        "files": [f"{out_rel}/{name}" for name in
                  (("compiled.json",) if source.get("evaluator") is not None else
                   ("compiled.json", "axes.json", "judge-prompt.md", "presentation.json"))],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
