"""The two-case fixtures `terms test` runs: for every row of a pack, one case where
the row is met and one where it is not met (Terms Pack Studio PRD v5 section 15
item 1).

A deal pack needs no file: its evaluator (scripts/evaluators/transaction.py) builds
the two cases of each check itself, the one kind `terms test` can run. Any other kind has `fixtures/two-case.json`
next to its pack-source.yaml:

    {"pack": <pack_id>,
     "cases": [{"row": <row id>, "case": "met" | "not_met", "input": {...}}, ...]}

`input` is what that kind's evaluator reads for the row (an admission pack's
evaluator input, an evaluator pack's `records` and `date`, a report or conduct
pack's disclosed facts). The test checks the
file against the pack: every row has exactly one case of each name, and no case
names a row the pack does not have. It evaluates a case through scripts/studio/case_eval.py: an admission pack's by a
capsule-engine binary, an evaluator pack's by that evaluator over the records
the case's `input` carries. Live packs (capsule-engine#286) and judged rows (a pinned
judge and a model key) are not run, so those cases are reported `evaluated: false`
and never as passed.
The two cases of a row must differ, or the pair says nothing.
"""
import json
import pathlib

import pack_schema

CASES = ("met", "not_met")
FILE = pathlib.Path("fixtures") / "two-case.json"

FILE_SCHEMA = {
    "type": "object",
    "properties": {
        "pack": {"type": "string", "minLength": 1},
        "cases": {"type": "array", "minItems": 1, "items": {
            "type": "object",
            "properties": {"row": {"type": "string", "minLength": 1}, "case": {"enum": list(CASES)},
                           "input": {"type": "object", "minProperties": 1}},
            "required": ["row", "case", "input"], "additionalProperties": False}},
    },
    "required": ["pack", "cases"], "additionalProperties": False,
}


def row_ids(source):
    """The ids a pack's cases may name, by kind. A report or conduct row is
    `<check id>.<criterion id>`, the id its clause has in the compiled pack."""
    kind = pack_schema.kind_of(source)
    if kind in ("deal", "admission"):
        return [r["id"] for r in source["rows"]]
    if kind == "live":
        return [o["id"] for o in (source.get("obligations") or []) + (source.get("outcomes") or [])]
    return [f"{c['id']}.{cr['id']}" for c in source["checks"] for cr in c["criteria"]]


def pack_id_of(source):
    return source["pack_id"]


def read_cases(src, source):
    """(cases, issues): the cases of the pack's fixture file, and what is wrong with it."""
    path = pathlib.Path(src).parent / FILE
    try:
        doc = json.loads(path.read_text())
    except OSError:
        return [], [f"{path} is missing: every row needs a met and a not_met case"]
    except ValueError as e:
        return [], [f"{path} is not JSON: {e}"]
    import jsonschema  # not at import: the other terms verbs need no schema library
    issues = [f"{path}: {'.'.join(str(p) for p in e.absolute_path) or 'file'}: {e.message}"
              for e in jsonschema.Draft202012Validator(FILE_SCHEMA).iter_errors(doc)]
    if issues:
        return [], issues
    if doc["pack"] != pack_id_of(source):
        issues.append(f"{path}: pack {doc['pack']!r} is not this pack, {pack_id_of(source)!r}")
    rows = row_ids(source)
    seen = {}
    for c in doc["cases"]:
        if c["row"] not in rows:
            issues.append(f"{path}: case for {c['row']!r}, which is not a row of this pack")
        elif (c["row"], c["case"]) in seen:
            issues.append(f"{path}: row {c['row']!r} has two {c['case']} cases")
        seen[(c["row"], c["case"])] = c
    for r in rows:
        if (r, "met") in seen and (r, "not_met") in seen and seen[(r, "met")]["input"] == seen[(r, "not_met")]["input"]:
            issues.append(f"{path}: row {r!r} has the same input in its met and not_met cases")
        for name in CASES:
            if (r, name) not in seen:
                issues.append(f"{path}: row {r!r} has no {name} case")
    return ([] if issues else doc["cases"]), issues
