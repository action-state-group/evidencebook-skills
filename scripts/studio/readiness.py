"""The field census and the readiness table of a Terms Pack workspace (Terms Pack
Studio PRD v5 section 5 "Readiness", evidencebook-skills#127).

`census(sales)` counts, for every field path in a dataset, how many records fill
it. `readiness(...)` gives each term one of five statuses; the table is plain
JSON, the one the chat and the Studio page both draw:

    checkable now         the pack can decide it from fields the dataset carries
    needs examples        a judged term: LABELS_NEEDED labelled sales are asked for, and a deal pack
                          has no judged tier to run them, so it stays here
    needs a field         the dataset lacks a field the term reads; the field is named
    needs the other side  decided from the counterparty's own record
    not this pack's concern  conduct or another pack's subject

A term is a row of the pack (`in_pack: true`, checked when published), or a candidate
listed in candidates.json (`in_pack: false`: a term the deal evaluator cannot run, kept
so the table says why, never checked). Dropping a row, or deleting a candidate from
candidates.json, removes the term from the table. labels.json maps a term id to
[{"deal_id": ..., "met": true|false}], one entry per labelled sale.
"""
import json
import pathlib
import re
import sys

_SCRIPTS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_SCRIPTS / "evaluators"))

import transaction  # noqa: E402

LABELS_NEEDED = 4  # PRD v5 section 6: four labelled rows per judged term
STATUSES = ("checkable now", "needs examples", "needs a field", "needs the other side",
            "not this pack's concern")

# Proposed for every dataset: the deal evaluator's three checks (scripts/evaluators/transaction.py).
PROPOSED_ROWS = (
    {"id": "paid_before_delivered", "statement": "The buyer paid before the goods were delivered.",
     "tier": "recomputed", "check": "paid_before_delivered", "proves": ["paid_at", "delivered_at"]},
    {"id": "delivered_within_days", "statement": "The goods were delivered within 2 days of payment.",
     "tier": "recomputed", "check": "delivered_within_days(2)", "proves": ["paid_at", "delivered_at"]},
    {"id": "price_as_offered", "statement": "The price was the price offered.",
     "tier": "recomputed", "check": "price_as_offered", "proves": ["offered_price", "accepted_price"]},
)

# Terms a seller often wants that no deal row can state; kept in the table with the reason.
PROPOSED_CANDIDATES = (
    {"id": "matched_description", "statement": "The goods were as described.", "tier": "judged",
     "reads": [], "side": "own"},
    {"id": "buyer_confirmed_receipt", "statement": "The buyer confirmed they received the goods.",
     "tier": "recomputed", "reads": ["buyer_confirmed_at"], "side": "other"},
    {"id": "my_agent_stayed_within_authority", "statement": "My agent offered only what I authorized.",
     "tier": "judged", "reads": [], "side": "own", "scope": "conduct"},
)


def _filled(v):
    return v is not None and v != "" and v != [] and v != {}


_NAME = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]{0,39}\Z")


def _walk(prefix, value, found):
    """Add each filled leaf path of one record to `found`; a list contributes its elements under `path[]`.
    A key that is not a short field name (an email, a long id: data held in a key) is written `*`.
    A short key that holds data still passes: the census names fields, and a dataset should not keep values in keys."""
    if isinstance(value, dict):
        for k in sorted(value, key=str):
            name = str(k) if _NAME.match(str(k)) else "*"
            _walk(f"{prefix}.{name}" if prefix else name, value[k], found)
    elif isinstance(value, list) and value and all(isinstance(x, (dict, list)) for x in value):
        for x in value:
            _walk(f"{prefix}[]", x, found)
    elif _filled(value):
        found.add(prefix)


def census(records):
    """{"records": N, "evaluable": {check: n}, "fields": [{"field", "filled", "rate"}]}: each field path
    and how many of the records fill it (a null, "", [] or {} is not filled; a field no record fills is
    not listed), and per check of the deal evaluator how many sales it can decide. A field filled in one
    sale and its partner in another, or a value of the wrong type, decides none. The count does not
    depend on a row's words or number, so editing a row never makes it stale."""
    counts = {}
    for rec in records:
        found = set()
        _walk("", rec, found)
        for path in found:
            counts[path] = counts.get(path, 0) + 1
    n = len(records)
    evaluable = {}
    for name, (fold, takes_arg) in transaction.CHECKS.items():
        evaluable[name] = sum(1 for rec in records
                              if isinstance(rec, dict) and fold(rec, 1 if takes_arg else None) != "not_evaluable")
    return {"records": n, "evaluable": evaluable, "fields": [
        {"field": f, "filled": c, "rate": round(c / n, 4) if n else 0.0} for f, c in sorted(counts.items())]}


def propose_candidates():
    return [dict(c) for c in PROPOSED_CANDIDATES]


def _row_term(row):
    parsed = transaction.parse_check(row.get("check"))
    return {"id": row["id"], "statement": row["statement"], "tier": row["tier"], "reads": list(row["proves"]),
            "side": "own", "from": "pack", "check": parsed[0] if parsed else None}


def terms_of(source, candidates):
    """The pack's rows, then the candidates no row has the id of."""
    rows = [_row_term(r) for r in source.get("rows") or []]
    have = {t["id"] for t in rows}
    return rows + [dict(c, **{"from": "candidate"}) for c in candidates if c["id"] not in have]


def status_of(term, filled_fields, label_count, evaluable=None, records=0):
    """(status, detail, fields to add) of one term; `fields` is non-empty only for "needs a field"."""
    if term.get("scope") == "conduct":
        return "not this pack's concern", "how your own agent behaves belongs in your private conduct pack, which is kept for you and is never meant for a buyer", []
    if term.get("side") == "other":
        return "needs the other side", "only the buyer's own signed record can decide it; a field in your sales records is your account of it, not theirs", []
    missing = [f for f in term["reads"] if f not in filled_fields]
    if missing:
        return "needs a field", f"no record fills {', '.join(missing)}", missing
    if evaluable == 0:
        return ("needs a field",
                f"no sale carries {' and '.join(term['reads'])} together, each in a form the check can read",
                list(term["reads"]))
    if term["tier"] == "judged":
        if label_count < LABELS_NEEDED:
            return "needs examples", f"{label_count} of {LABELS_NEEDED} sales labelled", []
        return "needs examples", f"{label_count} labelled; a deal pack has no judged tier to run them yet", []
    if evaluable is not None:
        return "checkable now", f"decides {evaluable} of {records} sales", []
    return "checkable now", "decided from the sale's own records", []


def labelled(labels, term_id):
    """How many distinct sales are labelled for a term: entries {"deal_id": ..., "met": true|false}."""
    entries = labels.get(term_id)
    if not isinstance(entries, list):
        return 0
    return len({e["deal_id"] for e in entries
                if isinstance(e, dict) and isinstance(e.get("deal_id"), str) and isinstance(e.get("met"), bool)})


def readiness(source, census_doc, candidates, labels):
    """The readiness table: one entry per term, and the count of each status."""
    filled = {f["field"] for f in census_doc["fields"]}
    rate = {f["field"]: f["rate"] for f in census_doc["fields"]}
    evaluable = census_doc.get("evaluable") or {}
    entries = []
    for t in terms_of(source, candidates):
        status, detail, fields = status_of(t, filled, labelled(labels, t["id"]), evaluable.get(t.get("check")),
                                           census_doc["records"])
        entries.append({"term": t["id"], "statement": t["statement"], "in_pack": t["from"] == "pack",
                        "status": status, "detail": detail, "reads": t["reads"], "missing_fields": fields,
                        "filled_rate": {f: rate.get(f, 0.0) for f in t["reads"]}})
    counts = {s: sum(1 for e in entries if e["status"] == s) for s in STATUSES}
    return {"pack_id": source["pack_id"], "pack_version": source["pack_version"],
            "records": census_doc["records"], "terms": entries, "counts": counts}


def read_json(path, default):
    """The file's JSON, or `default` when the file is absent. A file that exists and is not JSON raises
    ValueError: an empty table made from a broken file would be a false state."""
    try:
        text = path.read_text()
    except FileNotFoundError:
        return default
    return json.loads(text)
