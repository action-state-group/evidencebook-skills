#!/usr/bin/env python3
"""Compile a pack source or a report spec to an Evidence Contract, and publish it.

SEAMS ruling 1: authors write `pack-source.yaml` (or a report-spec/v1 YAML);
what is pinned and published is the compiled Evidence Contract, and a Result
cites it by `contract_ref` (`<id>@<version>`). The output is one Evidence
Contract v0 document (agent-action-capsule spec/interop-profile-v0.md §11.3,
the schema pinned there as EC: capsule-engine
`capsule_engine/schemas/evidence-contract-v0.json`, vendored by digest at
tests/fixtures/capsule-engine/evidence-contract-v0.json). It carries only
members EC v0 defines: `id`, `version` and one requirement per row.

  - `id` is the pack's `pack_id` (a report spec's `id`) and `version` its
    `pack_version` (`version`), so `contract_ref` is the value compiled.json,
    scripts/report_spec.py and every Result v0 here already carry.
  - A requirement's `id` is the row's `requirement_ref`: `<check>.<criterion>`
    for a pack, the claim id for a report spec.
  - A pack row's `tier` is its criterion's `requirement_tier`, `must_have` or
    `informational` (default `must_have`, as every criterion decides in
    rollup.all_required_met): whether the row decides the overall answer.
    A report-spec row carries none. It is not the clause's judged/recomputed
    `tier`, which the contract states as `mode` and `evidence_rule`.
  - A pack check that names an `article` is a native obligation citing it; any
    other row is a native outcome.
  - A judged row's `evidence_rule` is exactly what the judge is asked
    (pack_compile.judge_claim, after the pack's own switches), plus the
    answers it may give and the evidence it reads. A recomputed row names the
    fold that answers it; a report-spec row carries its computation.

Wording that only presents a row (titles, plain summaries, findings) is not in
the contract; it belongs to the pack's wording.

A published contract is immutable: `publish` writes `contracts/<id>/<version>.json`
and refuses to replace a published file with different bytes, so a changed row
needs a new version. Older versions stay, so a Result citing one can still find
it. The bytes are a fixed pretty-print, and compiling is byte-stable;
`contract_digest` is SHA-256 over the JCS form (interop profile §11.3.7).

    python3 scripts/evidence_contract.py compile packs/eu-ai-act-obligations/pack-source.yaml
    python3 scripts/evidence_contract.py compile scripts/specs/tau2-airline-no-judge.yaml
    python3 scripts/evidence_contract.py publish packs/eu-ai-act-obligations/pack-source.yaml
"""
import argparse
import hashlib
import json
import pathlib
import re
import sys

import rfc8785
import yaml

import pack_compile
import report_spec
from run_daily import effective_claim, effective_tier

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONTRACTS_DIR = ROOT / "contracts"

# EC forward_verdict: no row here can be checked before the session runs. A
# judged row also needs a model, as capsule-engine's packs state it
# (UNAVAILABLE-MODEL-REQUIRED with MODEL-ASSISTED); a recomputed row needs only
# the session's records (UNAVAILABLE-STATE-REQUIRED with DETERMINISTIC).
FORWARD_JUDGED = "UNAVAILABLE-MODEL-REQUIRED"
FORWARD_RECOMPUTED = "UNAVAILABLE-STATE-REQUIRED"

_ANSWERS = ("Answers: met; not_met; not_evaluable when the evidence does not show either way.")
_ANSWERS_WITH_OUT_OF_SCOPE = (
    "Answers: met; not_met; not_evaluable when the evidence does not show either way; "
    "out_of_scope when the situation this asks about did not come up, which excludes the session "
    "as not applicable and is never met or not_met.")

# report-spec/v1's fail-closed reading (scripts/report_spec.py, evaluate_group).
_REPORT_SPEC_RULES = (
    "Evaluated once per group_by value of the first source's rows. A row that cannot be read, an expression "
    "reading a field the row does not carry, or a sum over a value that is not a finite number makes the "
    "answer not_evaluable, never met; readable sources with no rows to check are never met.")

# Path segments of a published contract's file: no empty, dot or dot-dot
# segment can escape contracts/.
_SEGMENT = re.compile(r"\A(?!\.{1,2}\Z)[^/\\\s@]+\Z")


class ContractError(ValueError):
    """The input cannot compile to an Evidence Contract, or a publish would
    change a published one."""


def _answers(out_of_scope):
    return _ANSWERS_WITH_OUT_OF_SCOPE if out_of_scope else _ANSWERS


# The judge prompt speaks to the model ("passed to you as text"); the contract
# states the same evidence in the third person.
_SECOND_PERSON = ("passed to you as text", "supplied to the judge as text")


def _judged_evidence(source):
    """What the judge reads: the pack's judge.subject/evidence, or the default
    build_judge_prompt uses when a pack names neither."""
    judge = source["judge"]
    if "subject" in judge:
        return judge["subject"], judge["evidence"]
    return (pack_compile._LEGACY_JUDGE_SUBJECT,
            [e.replace(*_SECOND_PERSON) for e in pack_compile._LEGACY_JUDGE_EVIDENCE])


def from_pack(source):
    """A validated pack source (pack_compile.validate_source) -> the contract."""
    issues = pack_compile.validate_source(source)
    if isinstance(source, dict) and any(isinstance(c, dict) and "article" in c for c in source.get("checks") or []):
        # A check citing an article compiles to an obligation whose clause names
        # the instrument and the article (EC clauseSpec: both non-empty text).
        if not isinstance(source.get("regulation"), str) or not source["regulation"].strip():
            issues.append("regulation must be a non-empty string when a check cites an article")
        for i, check in enumerate(source["checks"]):
            if isinstance(check, dict) and "article" in check and (
                    not isinstance(check["article"], str) or not check["article"].strip()):
                issues.append(f"checks[{i}].article must be a non-empty string")
    if issues:
        raise ContractError("pack source is invalid: " + "; ".join(issues))
    switches = source.get("switches") or {}
    out_of_scope = bool(switches.get("out_of_scope_verdict"))
    subject, evidence = _judged_evidence(source)
    scope = f"Judged on {subject}, from {pack_compile._join_evidence(evidence)}."
    clauses = {c["id"]: c for c in pack_compile.build_clauses(source)}
    requirements = []
    for check in source["checks"]:
        for crit in check["criteria"]:
            clause = clauses[f"{check['id']}.{crit['id']}"]
            checkability = effective_tier(clause, switches)
            req = {"id": clause["id"]}
            if "article" in check:
                req["profile"] = "obligation"
            else:
                req["profile"] = "outcome"
            req["statement"] = crit["label"]
            # EC requirement `tier`: whether the row decides the overall answer.
            # Always written, so a reader never infers it; an unmarked criterion
            # decides, as in rollup.all_required_met. Not the judged/recomputed
            # `tier` of a clause, which is `checkability` here.
            req["tier"] = crit.get("requirement_tier", "must_have")
            oos = out_of_scope and not crit.get("never_out_of_scope")
            if checkability == "judged":
                parts = [effective_claim(clause, switches), "", scope, _answers(oos)]
                if crit.get("recompute_precheck"):
                    parts.append(f"A deterministic pre-check, {crit['recompute_precheck']}, runs before "
                                 "the judge and may decide the row for a session.")
                req["evidence_rule"] = "\n".join(parts)
                req["forward_verdict"] = FORWARD_JUDGED
                req["backward_verdict"] = "MODEL-ASSISTED"
                req["mode"] = "judged"
            else:
                fold = crit.get("fold_id")
                rule = [effective_claim(clause, switches), ""]
                rule.append(f"Recomputed by fold {fold}." if fold else "Recomputed from the session's records.")
                # A checker's answer is held to met/not_met/not_evaluable
                # (run_daily.recomputed_answer); out_of_scope is a judge answer only.
                rule.append(_answers(False))
                req["evidence_rule"] = "\n".join(rule)
                req["forward_verdict"] = FORWARD_RECOMPUTED
                req["backward_verdict"] = "DETERMINISTIC"
            if crit.get("measurability"):
                req["measurability"] = crit["measurability"]
            if req["profile"] == "obligation":
                req["clause"] = {"instrument": source["regulation"], "article": check["article"]}
            requirements.append(req)
    return _contract(source["pack_id"], source["pack_version"], requirements)


def _referenced_metrics(claim, metrics):
    names = [claim["metric"]] if claim.get("metric") else []
    value = claim.get("value")
    if isinstance(value, str):
        try:
            names += report_spec._expr_names(value)
        except report_spec.ReportSpecError as e:
            raise ContractError(f"claim {claim['id']!r}: {e}") from e
    out = []
    for n in names:
        if n not in metrics:
            raise ContractError(f"claim {claim['id']!r} reads metric {n!r}, which the spec does not define")
        if n not in out:
            out.append(n)
    return out


def _source_chain(name, sources):
    chain, seen = [], set()
    while name is not None and name not in seen:
        if name not in sources:
            raise ContractError(f"source {name!r} is not defined in the spec")
        seen.add(name)
        chain.append(name)
        name = sources[name].get("from")
    return list(reversed(chain))


def from_report_spec(spec):
    """A report-spec/v1 that report_spec.load_spec accepted -> the contract. Every
    row is recomputed: `evidence_rule` is the claim's computation, as JCS text
    of the claim and the metrics and sources it reads, so a third party can
    recompute it from the same records."""
    sources = {s["name"]: s for s in spec["sources"]}
    metrics = {m["name"]: m for m in spec.get("metrics") or []}
    requirements = []
    for claim in spec["claims"]:
        cid = claim.get("id")
        if not isinstance(cid, str) or not cid.strip():
            raise ContractError("every claim needs a non-empty id")
        if not isinstance(claim.get("description"), str) or not claim["description"].strip():
            raise ContractError(f"claim {cid!r} needs a description: it is the requirement's statement")
        used_metrics = _referenced_metrics(claim, metrics)
        # The first source decides which groups exist (report_spec.build_documents),
        # so every claim reads it.
        roots = [spec["sources"][0]["name"]] + [metrics[m]["source"] for m in used_metrics]
        if claim.get("source"):
            roots.append(claim["source"])
        used_sources = []
        for root in roots:
            for s in _source_chain(root, sources):
                if s not in used_sources:
                    used_sources.append(s)
        computation = {
            "group_by": spec.get("group_by", "day"),
            "claim": {k: v for k, v in claim.items() if k != "description"},
            "metrics": [metrics[m] for m in used_metrics],
            "sources": [sources[s] for s in used_sources],
        }
        rule = (f"report-spec/v1 computation, recomputed from the records: "
                f"{rfc8785.dumps(computation).decode()}\n{_REPORT_SPEC_RULES}\n"
                f"{_answers(report_spec.out_of_scope_allowed(spec, claim))}")
        requirements.append({
            "id": cid,
            "profile": "outcome",
            "statement": " ".join(claim["description"].split()),
            "evidence_rule": rule,
            "forward_verdict": FORWARD_RECOMPUTED,
            "backward_verdict": "DETERMINISTIC",
            "mode": "value",
        })
    return _contract(str(spec["id"]), str(spec["version"]), requirements)


def _contract(id_, version, requirements):
    """The document, refused when two requirements share an id: a verifier
    must not evaluate such a contract (interop profile §11.3.7, P-47)."""
    ids = [r["id"] for r in requirements]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise ContractError(f"requirement ids must be unique within a contract: {dupes}")
    return {"id": id_, "version": version, "requirements": requirements}


def contract_ref(contract):
    return f"{contract['id']}@{contract['version']}"


def to_bytes(contract):
    """The published bytes: a fixed pretty-print, member order as compiled."""
    return (json.dumps(contract, indent=2, ensure_ascii=False) + "\n").encode()


def contract_digest(contract):
    """SHA-256 over UTF-8 of JCS of the whole document (interop profile §11.3.7)."""
    return hashlib.sha256(rfc8785.dumps(contract)).hexdigest()


def published_path(contract, root=CONTRACTS_DIR):
    segments = contract["id"].split("/") + [contract["version"]]
    for seg in segments:
        if not _SEGMENT.match(seg):
            raise ContractError(f"{contract_ref(contract)!r} cannot name a published file: segment {seg!r}")
    return root.joinpath(*segments[:-1], segments[-1] + ".json")


def publish(contract, root=CONTRACTS_DIR):
    """Write the contract at contracts/<id>/<version>.json. Writing the same
    bytes again is a no-op; different bytes under a published id@version are
    refused (bump the version)."""
    path = published_path(contract, root)
    data = to_bytes(contract)
    if path.exists():
        if path.read_bytes() == data:
            return path, False
        raise ContractError(f"{contract_ref(contract)} is already published at {path} with different "
                            "content; a published contract is immutable: bump the version")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path, True


def load_input(path):
    """A pack source or a report spec, by its own shape."""
    doc = yaml.safe_load(pathlib.Path(path).read_text())
    if isinstance(doc, dict) and doc.get("spec_version") == "report-spec/v1":
        try:  # the runner's own checks first, so a contract never states a spec the runner refuses
            spec = report_spec.load_spec(path)
        except report_spec.ReportSpecError as e:
            raise ContractError(str(e)) from e
        return from_report_spec(spec)
    if isinstance(doc, dict) and "pack_id" in doc:
        return from_pack(pack_compile._strip_strings(doc))
    raise ContractError(f"{path}: neither a pack source (pack_id) nor a report-spec/v1")


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, text in (("compile", "print the contract"), ("publish", "write contracts/<id>/<version>.json")):
        p = sub.add_parser(name, help=text)
        p.add_argument("source", type=pathlib.Path, help="a pack-source.yaml or a report-spec/v1 YAML")
    args = ap.parse_args(argv)
    try:
        contract = load_input(args.source)
        if args.cmd == "compile":
            sys.stdout.buffer.write(to_bytes(contract))
            return 0
        path, written = publish(contract)
    except ContractError as e:
        print(json.dumps({"error": str(e)}, indent=2))
        return 1
    print(json.dumps({"contract_ref": contract_ref(contract), "contract_digest": contract_digest(contract),
                      "path": path.relative_to(ROOT).as_posix(), "written": written}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
