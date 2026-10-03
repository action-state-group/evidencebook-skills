#!/usr/bin/env python3
"""Compile a pack source into a daily-judge-and-close spec plus a report
presentation extension, so a person can change the criteria, recompile and rerun
against the same data, and select the report template the results render through.

Relationship to this repo's other two compilers:

  - `evaluation-compiler` (the root SKILL.md) turns a free-form value proposition
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
                           report.template (today: outcome-report/v1). Nothing in
                           this repo consumes it; it records the template
                           selection and its presentation settings for the
                           renderer that draws the report.

Deterministic: the same pack source compiles to byte-identical output every time
(no wall-clock, no randomness) -- see tests/test_pack_compile.py. Refuses an
invalid pack source before writing anything, reporting every issue found, in the
`{"valid": bool, "issues": [...]}` shape `capsulectl contract validate --json`
uses.

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

TIERS = {"judged", "recomputed"}

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
                "never_not_applicable": bool(crit.get("never_not_applicable", False)),
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


# The report-template registry: this is the "pluggable" seam. Adding a template
# means registering a builder here; selecting one no one registered is a
# validation failure (see validate_source), never a silent fallback to this one.
REPORT_TEMPLATES = {"outcome-report/v1": _build_outcome_report_presentation}

# The report settings a pack may carry. Anything else is refused: the report states
# outcomes, and settings that are not about presenting them (pricing a resolution,
# for one) belong to a product that consumes the report, not to the pack.
REPORT_KEYS = ("template", "percentages")


def validate_source(source):
    """Every issue found, not just the first -- same `issues[]` convention
    evidence-contract-compile's own `capsulectl contract validate --json` uses.
    A failing validation means nothing downstream is compiled."""
    issues = []
    if not isinstance(source, dict):
        return ["pack source must be a mapping"]

    def require_str(key):
        v = source.get(key)
        if not isinstance(v, str) or not v.strip():
            issues.append(f"{key} must be a non-empty string")

    for key in ("pack_id", "pack_version", "rubric_version", "outcome_statement", "resolution_rule", "counterparty"):
        require_str(key)

    # contract_ref (build_compiled_json: f"{pack_id}@{pack_version}") must match the
    # Evidence Result v0 ContractRef pattern "^[^@\\s]+@[^@\\s]+$": an "@" or whitespace
    # in either half would compile a pack that `capsulectl result build` refuses.
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
    else:
        switches = {}

    if "judge_batch" in source and not isinstance(source["judge_batch"], bool):
        issues.append("judge_batch must be a boolean")

    checks = source.get("checks")
    if not isinstance(checks, list) or not checks:
        issues.append("checks must be a non-empty list")
        checks = []

    seen_check_ids, seen_clause_ids = set(), set()
    for i, check in enumerate(checks):
        where = f"checks[{i}]"
        if not isinstance(check, dict):
            issues.append(f"{where} must be a mapping")
            continue
        check_id = check.get("id")
        if not isinstance(check_id, str) or not check_id.strip():
            issues.append(f"{where}.id must be a non-empty string")
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
            for key in ("label", "text"):
                if not isinstance(crit.get(key), str) or not crit[key].strip():
                    issues.append(f"{cwhere}.{key} must be a non-empty string")
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
            if "never_not_applicable" in crit and not isinstance(crit["never_not_applicable"], bool):
                issues.append(f"{cwhere}.never_not_applicable must be a boolean")
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

    judge = source.get("judge")
    if not isinstance(judge, dict) or not isinstance(judge.get("model_id"), str) or not judge.get("model_id", "").strip():
        issues.append("judge.model_id must be a non-empty string")
    else:
        if "sampling_params" in judge and not isinstance(judge["sampling_params"], dict):
            issues.append("judge.sampling_params must be a mapping")
        min_conf = judge.get("min_confidence")
        if min_conf is not None and (isinstance(min_conf, bool) or not isinstance(min_conf, (int, float))
                                     or not 0 < min_conf <= 1):
            issues.append(f"judge.min_confidence must be a number in (0, 1], or absent; got {min_conf!r}")

    report = source.get("report")
    if not isinstance(report, dict):
        issues.append("report must be a mapping")
    else:
        template = report.get("template")
        if template not in REPORT_TEMPLATES:
            issues.append(f"report.template {template!r} is not a known template; known: {sorted(REPORT_TEMPLATES)}")
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


def build_clauses(source):
    clauses = []
    for check in source["checks"]:
        for crit in check["criteria"]:
            clause = {
                "id": f"{check['id']}.{crit['id']}",
                "check_id": check["id"],
                "check_question": check["question"],
                "label": crit["label"],
                "claim": crit["text"],
                "tier": crit["tier"],
                "recompute_eligible": bool(crit.get("recompute_eligible", False)),
                "recompute_note": crit.get("recompute_note", ""),
            }
            if crit.get("never_not_applicable"):
                clause["never_not_applicable"] = True
            if crit.get("tier_switch"):
                clause["tier_switch"] = dict(crit["tier_switch"])
            if crit.get("claim_switch"):
                clause["claim_switch"] = dict(crit["claim_switch"])
            clauses.append(clause)
    return clauses


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
        "rule": f"all {len(axes)} axes required -- resolved only when every one passes",
        "checks": checks,
        "axes": axes,
    }


def build_judge_prompt(source, out_rel):
    checks = source["checks"]
    n = sum(len(c["criteria"]) for c in checks)
    pack_label = f"{source['pack_id']} rubric v{source['rubric_version']}"
    resolution_rule = source["resolution_rule"]
    resolution_rule = resolution_rule[:1].upper() + resolution_rule[1:]
    lines = [
        f"You judge one recorded conversation against one criterion, one of the {n} that make up "
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
        "Evidence you may use: the conversation (`agent_interaction.messages` -- customer and "
        "agent turns, tool calls and their results, in order) and the airline policy "
        "(`airline-data/policy.md`, passed to you as text). You are not given, and must not look "
        "for, any graded outcome or answer key.",
        "",
        "Answer with exactly one verdict:",
        "",
        "- `met` -- the transcript shows the criterion was satisfied.",
        "- `not_met` -- the transcript shows it was not.",
        "- `not_evaluable` -- the transcript does not contain enough evidence to decide either "
        "way. Use this only when the evidence genuinely is not there, not as a hedge.",
        "",
        "Cite the specific turns and tool results you relied on.",
        "",
    ]
    return "\n".join(lines)


def build_presentation_json(source):
    template = source["report"]["template"]
    return {template: REPORT_TEMPLATES[template](source)}


def compile_pack(source, out_rel):
    """Pure: source + the output path string -> the four generated documents.
    No filesystem access -- tests call this directly to check determinism and
    content without touching disk."""
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
    (out_dir / "axes.json").write_text(json.dumps(axes, indent=2) + "\n")
    (out_dir / "judge-prompt.md").write_text(prompt)
    (out_dir / "presentation.json").write_text(json.dumps(presentation, indent=2) + "\n")
    return compiled


def resolve_out_dir(out_arg):
    """--out must be exactly `demo/<name>`, resolved under this repo's root:
    scripts/run_daily.py derives its own repo root as
    `args.spec.resolve().parents[2]` from wherever --spec sits, which only lands
    on the real root when the compiled spec is exactly two directories deep.
    Returns (out_dir_abs, out_rel) or raises ValueError with the reason."""
    root = pathlib.Path(__file__).resolve().parents[1]
    out_abs = (root / out_arg) if not out_arg.is_absolute() else out_arg
    try:
        out_rel = out_abs.resolve().relative_to(root).as_posix()
    except ValueError:
        raise ValueError(f"--out must be inside the repo root ({root})")
    parts = out_rel.split("/")
    if len(parts) != 2 or parts[0] != "demo":
        raise ValueError(
            f"--out must be exactly demo/<name> (got {out_rel!r}): scripts/run_daily.py resolves "
            "its repo root as --spec.resolve().parents[2], which assumes this exact depth"
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

    args = ap.parse_args(argv)
    source = _strip_strings(yaml.safe_load(args.source.read_text()))
    issues = validate_source(source)

    if args.cmd == "validate":
        print(json.dumps({"valid": not issues, "issues": issues}, indent=2))
        return 0 if not issues else 1

    if issues:
        print(json.dumps({"valid": False, "issues": issues}, indent=2))
        return 1

    try:
        out_abs, out_rel = resolve_out_dir(args.out)
    except ValueError as e:
        print(json.dumps({"valid": False, "issues": [str(e)]}, indent=2))
        return 1

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
                  ("compiled.json", "axes.json", "judge-prompt.md", "presentation.json")],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
