#!/usr/bin/env python3
"""A `scope.kind: deal` pack source: validation and what it compiles to.

A deal terms pack is a seller's terms for a sale, one row each, all recomputed
from the sale's own records by the evaluator it names (Terms Pack Studio first
demo, evidencebook-skills#117; first-demo scope section 3). The source:

    scope: {kind: deal}
    pack_id, pack_version, title, statement
    evaluator: transaction          scripts/evaluators/<evaluator>.py
    rows:
      - id            the row's name in reports
        statement     the term in the seller's words
        tier          recomputed (the only tier this evaluator has)
        check         a check of the evaluator, with its number inside the
                      row where it takes one: delivered_within_days(2)
        proves        the sale fields the row reads

No other member is accepted, so there is no pack-level knob a number could hide
in. Compiled, the pack is `compiled.json`; its `definition_digest` is the
SHA-256 over the JCS bytes of {pack_id, pack_version, rows}, so changing any
row's words or check changes the digest and a title does not. Each row also
has a `row_digest` (JCS of the row), which `terms compare` uses to say which
rows changed between two runs.
"""
import hashlib
import pathlib
import re
import sys

import rfc8785

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "evaluators"))
import transaction  # noqa: E402

SCOPE_KIND = "deal"
EVALUATORS = {"transaction": transaction}
TOP_KEYS = {"scope", "pack_id", "pack_version", "title", "statement", "evaluator", "rows"}
ROW_KEYS = {"id", "statement", "tier", "check", "proves"}
FIELDS = ("offered_price", "accepted_price", "paid_at", "delivered_at")
_ID = re.compile(r"\A[a-z][a-z0-9_]*\Z")
_VERSION = re.compile(r"\A\d+\.\d+\.\d+\Z")


def is_deal(source):
    scope = source.get("scope") if isinstance(source, dict) else None
    return isinstance(scope, dict) and scope.get("kind") == SCOPE_KIND


def _nonempty(v):
    return isinstance(v, str) and bool(v.strip())


def validate_deal(source):
    """Every issue found, as pack_compile.validate_source returns them."""
    issues = [f"{k} is not a deal pack member" for k in sorted(set(source) - TOP_KEYS, key=str)]
    for key in ("pack_id", "pack_version", "title", "statement", "evaluator"):
        if not _nonempty(source.get(key)):
            issues.append(f"{key} must be a non-empty string")
    if _nonempty(source.get("pack_id")) and not _ID.match(source["pack_id"].replace("-", "_")):
        issues.append("pack_id must be lowercase letters, digits, - and _")
    if _nonempty(source.get("pack_version")) and not _VERSION.match(source["pack_version"]):
        issues.append("pack_version must look like 0.1.0")
    if _nonempty(source.get("evaluator")) and source["evaluator"] not in EVALUATORS:
        issues.append(f"evaluator must be one of {sorted(EVALUATORS)}, got {source['evaluator']!r}")
    rows = source.get("rows")
    if not isinstance(rows, list) or not rows:
        return issues + ["rows must be a non-empty list"]
    seen = set()
    for i, row in enumerate(rows):
        where = f"rows[{i}]"
        if not isinstance(row, dict):
            issues.append(f"{where} must be a mapping")
            continue
        if _nonempty(row.get("id")):
            where += f" ({row['id']!r})"
        issues += [f"{where}.{k} is not a row member (only {sorted(ROW_KEYS)})" for k in sorted(set(row) - ROW_KEYS, key=str)]
        if not _nonempty(row.get("id")) or not _ID.match(row["id"]):
            issues.append(f"{where}.id must be lowercase letters, digits and _")
        elif row["id"] in seen:
            issues.append(f"{where}.id is used twice")
        else:
            seen.add(row["id"])
        if not _nonempty(row.get("statement")):
            issues.append(f"{where}.statement must be the term in words")
        if row.get("tier") != "recomputed":
            issues.append(f"{where}.tier must be recomputed")
        if not _nonempty(row.get("check")):
            issues.append(f"{where} has no check: every row needs one of {sorted(transaction.CHECKS)}")
        else:
            try:
                transaction.row_check(row)
            except ValueError as e:
                issues.append(str(e))
        proves = row.get("proves")
        if not isinstance(proves, list) or not proves or any(p not in FIELDS for p in proves):
            issues.append(f"{where}.proves must list fields from {list(FIELDS)}")
        elif _nonempty(row.get("check")):
            parsed = transaction.parse_check(row["check"])
            reads = transaction.READS.get(parsed[0]) if parsed else None
            if parsed and parsed[1] is not None and not re.search(rf"(?<!\d){parsed[1]}(?!\d)", str(row.get("statement"))):
                issues.append(f"{where}.statement must say {parsed[1]}, the number in its check {row['check']!r}")
            if reads and sorted(proves) != sorted(reads):
                issues.append(f"{where}.proves must be {list(reads)}, the fields {parsed[0]} reads")
    return issues


def row_digest(row):
    return hashlib.sha256(rfc8785.dumps({k: row[k] for k in sorted(ROW_KEYS)})).hexdigest()


def definition_digest(source):
    body = {"pack_id": source["pack_id"], "pack_version": source["pack_version"], "rows": source["rows"]}
    return hashlib.sha256(rfc8785.dumps(body)).hexdigest()


def compiled(source):
    return {
        "contract": f"{source['pack_id']}/v1",
        "contract_ref": f"{source['pack_id']}@{source['pack_version']}",
        "scope": SCOPE_KIND,
        "title": source["title"],
        "statement": source["statement"],
        "evaluator": source["evaluator"],
        "rows": [dict(row, row_digest=row_digest(row)) for row in source["rows"]],
        "definition_digest": definition_digest(source),
    }


def from_deal(source):
    """The Evidence Contract v0 requirements of a validated deal pack: one per
    row, its statement and how it is recomputed, in words."""
    requirements = []
    for r in source["rows"]:
        name, arg = transaction.parse_check(r["check"])
        reads = ", ".join(r["proves"])
        rule = f"Recomputed with no model from the sale's own records ({reads}) by {name}" + \
               (f" with {arg} day(s)" if arg is not None else "") + "."
        requirements.append({
            "id": r["id"], "profile": "outcome", "statement": r["statement"], "tier": "must_have",
            "evidence_rule": rule, "forward_verdict": "DETERMINISTIC", "backward_verdict": "DETERMINISTIC",
        })
    return {"id": source["pack_id"], "version": source["pack_version"], "requirements": requirements}
