"""The week's calibration summaries, in the shape of AAC's calibration-summary/v1.

One record per judge pin (spec/judge-record-family-v1.md section 8): the pin is
cited by its digest with citation_purpose `calibrates`, and each clause carries
agreement and drift as k of n, never a rate. A reader who wants a rate divides.

Agreement is the same reading `capsulectl calibration summarize` makes: the
human's rating equals the judge's verdict on a rated case. A case counts only
when the rating and the judge's verdict are both `met` or `not_met`
(human_rating.counted_cases); `not_evaluable` and `out_of_scope`, on either
side, are in neither k nor n. Drift is measured
by re-judging adjudicated cases (capsule-judge's drift check), which this
weekly run does not do, so every clause reports drift 0 of 0: unmeasured, not
zero drift. The drawn sample size, the shortfall and the period are not
members of this record; they are in the sample manifest, the human-rating
records (each cites the report it rates) and the run's log.
"""

from human_rating import counted_cases  # noqa: E402

URN = "urn:evidencebook-skills:calibration-summary"


def calibration_summaries(selected, rated, contract, week_key, computed_at):
    """One calibration-summary/v1 body per judge pin in `selected` (a list of
    (report capsule id, evaluation-report body)), from `rated` (a list of
    {"case_id", "rating"}), in pin order. A pin's clauses are those of its
    drawn reports, so a clause drawn but not rated reports agreement 0 of 0."""
    rating_of = {r["case_id"]: r["rating"] for r in rated if r["case_id"] in counted_cases(selected, rated)}
    pins = {}
    for _, body in selected:
        clauses = pins.setdefault(body["judge_pin_digest"], {})
        k_n = clauses.setdefault(body["clause_id"], [0, 0])
        if body["case_id"] in rating_of:
            k_n[1] += 1
            k_n[0] += rating_of[body["case_id"]] == body["verdict"]
    return [{
        "record_version": "calibration-summary/v1",
        "record_id": f"{URN}:{contract}:{week_key}:{pin[:16]}",
        "epistemic_type": "derived_metric",
        "computed_at": computed_at,
        "judge_pin": {"type": "judge_pin", "digest_alg": "SHA-256", "digest": pin, "citation_purpose": "calibrates"},
        "clauses": [{"clause_ref": clause, "agreement": {"k": k, "n": n}, "drift": {"k": 0, "n": 0}}
                    for clause, (k, n) in sorted(clauses.items())],
    } for pin, clauses in sorted(pins.items())]


def disagreement_with_verb(records, verb_pins):
    """The first way the records' per-clause k and n fail to add up to the
    verb's per-pin totals, as text, or None. A pin the verb does not list had
    no countable case and reads (0, 0) in the records: both say the same."""
    totals = {p["judge_pin_digest"]: (p["agreement_count"], p["rated_count"]) for p in verb_pins}
    for record in records:
        pin = record["judge_pin"]["digest"]
        ours = tuple(sum(c["agreement"][m] for c in record["clauses"]) for m in ("k", "n"))
        if totals.get(pin, (0, 0)) != ours:
            return f"calibration summary for pin {pin[:16]} disagrees with `calibration summarize`: {ours} against {totals.get(pin, (0, 0))}"
    return None
