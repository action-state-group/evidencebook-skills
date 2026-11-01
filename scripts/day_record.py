"""What a day section's case columns and the timeline lanes draw (evidencebook-skills#95; split
from evidencebook#241 items 5-8, Sherlock2: pack members, as in #89), as a `day_record` key beside
`subject_history` in the day Result's pack-namespaced `x-<pack_id>` member. Not AAC vocabulary.

    "x-airline-support-outcomes": {
      "day_record": {
        "judged_at": "2026-10-30T02:00:00Z",
        "cases": {"<case_id>": {"request_labels": [...], "usd_band": "e+1",
                                "terms": [{"id": "<clause id>", "tier": "must_have", "verdict": "met"}]}},
        "spans": [{"lane": "routed_action", "case_id": "<case_id>", "start": "...", "end": "..."}],
        "lane_totals": {"routed_action": 2, "incident_flag": 0}}}

`request_labels` and `usd_band` come from the same functions as subject_history's, so the two
agree; neither carries transcript text. `terms` follow the contract's clause order: the verdict is
the case's claim, `out_of_scope` where the criterion has no claim, and the tier is the clause's
`requirement_tier` (`must_have` when unmarked, as scripts/evidence_contract.py writes it).
`spans` are the start and end of a routed action or an incident flag that the caller read from the
records (this repo holds none): validated, never inferred. `lane_totals` count the spans per lane.
`judged_at` is the run's own time, the caller's --generated-at.
"""
import datetime
import re

from rollup import RollupError
from subject_history import request_labels, usd_band

LANES = ("routed_action", "incident_flag")
REQUIREMENT_TIERS = ("must_have", "informational")
CASE_SEPARATOR = "::"


_RFC3339 = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|[+-]\d\d:\d\d)")


def rfc3339(value, what):
    """The parsed instant of an RFC 3339 timestamp (a UTC offset is required); RollupError otherwise."""
    if not isinstance(value, str) or not _RFC3339.fullmatch(value):
        raise RollupError(f"{what} must be an RFC 3339 timestamp with a UTC offset, got {value!r}")
    try:
        return datetime.datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        raise RollupError(f"{what} must be an RFC 3339 timestamp with a UTC offset, got {value!r}") from None


def check_spans(spans, known_cases):
    """The validated spans, in the order given. Each is {lane, case_id, start, end}; the case is one
    this report carries and the end is not before the start."""
    if not isinstance(spans, list):
        raise RollupError("spans must be a list of {lane, case_id, start, end} objects")
    out = []
    for i, s in enumerate(spans):
        if not isinstance(s, dict) or set(s) != {"lane", "case_id", "start", "end"}:
            raise RollupError(f"span {i}: must have exactly lane, case_id, start and end")
        if s["lane"] not in LANES:
            raise RollupError(f"span {i}: lane must be one of {LANES}, got {s['lane']!r}")
        if s["case_id"] not in known_cases:
            raise RollupError(f"span {i}: case {s['case_id']!r} is not in this report")
        if rfc3339(s["end"], f"span {i} end") < rfc3339(s["start"], f"span {i} start"):
            raise RollupError(f"span {i}: end is before start")
        out.append({k: s[k] for k in ("lane", "case_id", "start", "end")})
    return out


def case_terms(claims, case_id, clauses):
    """The terms of one case: the contract's clauses in order, each with the case's claim verdict."""
    verdicts = {c["requirement_ref"]: c["verdict"] for c in claims if c["id"] == f"{case_id}{CASE_SEPARATOR}{c['requirement_ref']}"}
    terms = []
    for clause in clauses:
        tier = clause.get("requirement_tier", "must_have")
        if tier not in REQUIREMENT_TIERS:
            raise RollupError(f"clause {clause['id']!r}: requirement_tier {tier!r} is not one of {REQUIREMENT_TIERS}")
        terms.append({"id": clause["id"], "tier": tier, "verdict": verdicts.get(clause["id"], "out_of_scope")})
    return terms


def build_day_record(generated_at, claims, clauses, conversations, spans=None, known_cases=None):
    """The `day_record` value for one day: `claims` are the day Result's, `clauses` the compiled
    contract's, `conversations` case_id -> agent_interaction messages for the day's cases.
    `spans` are the caller's (see check_spans); `known_cases` every case the report carries."""
    rfc3339(generated_at, "judged_at")
    known = set(known_cases if known_cases is not None else conversations)
    checked = check_spans(spans or [], known)
    cases = {}
    for case_id, messages in sorted(conversations.items()):
        entry = {"request_labels": request_labels(messages)}
        band = usd_band(messages)
        if band:
            entry["usd_band"] = band
        entry["terms"] = case_terms(claims, case_id, clauses)
        cases[case_id] = entry
    day_cases = set(conversations)
    spans_here = [s for s in checked if s["case_id"] in day_cases]
    return {"judged_at": generated_at, "cases": cases, "spans": spans_here,
            "lane_totals": {lane: sum(1 for s in spans_here if s["lane"] == lane) for lane in LANES}}


def merge_day_records(records):
    """Several days' `day_record` values into one: cases and spans joined (a case twice is refused)
    and totals recounted. `judged_at` is a day's own run time and is not carried."""
    cases, spans = {}, []
    for r in records:
        dupes = sorted(set(cases) & set(r["cases"]))
        if dupes:
            raise RollupError(f"day records carry case(s) twice: {dupes!r}")
        cases.update(r["cases"])
        spans.extend(r["spans"])
    return {"cases": dict(sorted(cases.items())), "spans": spans,
            "lane_totals": {lane: sum(1 for s in spans if s["lane"] == lane) for lane in LANES}}
