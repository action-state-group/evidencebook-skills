"""The week's calibration summaries, in the shape of AAC's calibration-summary/v1.

One record per judge pin (spec/judge-record-family-v1.md section 8): the pin is
cited by its digest with citation_purpose `calibrates`, and each clause carries
agreement and drift as k of n, never a rate. A reader who wants a rate divides.

Agreement is the same reading `capsulectl calibration summarize` makes: the
human's rating equals the judge's verdict on a rated case. Drift is measured
by re-judging adjudicated cases (capsule-judge's drift check), which this
weekly run does not do, so every clause reports drift 0 of 0: unmeasured, not
zero drift. The drawn sample size, the shortfall and the period are not
members of this record; they are in the sample manifest and the human-rating
records, which carry the period and are sealed beside it, and in the run's log.
"""

URN = "urn:evidencebook-skills:calibration-summary"


def calibration_summaries(selected, rated, contract, week_key, computed_at):
    """One calibration-summary/v1 body per judge pin in `selected` (a list of
    (report capsule id, evaluation-report body)), from `rated` (a list of
    {"case_id", "rating"}), in pin order. A pin's clauses are those of its
    drawn reports, so a clause drawn but not rated reports agreement 0 of 0."""
    rating_of = {r["case_id"]: r["rating"] for r in rated}
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
