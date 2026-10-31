"""One blind human rating, in the shape of AAC's human-rating/v1.

spec/judge-record-family-v1.md section 5: the record cites the one case rated
(citation_purpose `rated_case`) and carries the label. The citation's digest is
the audited evaluation-report's capsule id, so the rating is pinned to the very
report it rates: without that pin every criterion claim matches and every rating
reads not_recomputable. The rater is an opaque principal reference
(`rater_ref`), never a name. The period and the sample manifest are not members
of this record; the sample manifest lists the report ids it drew and the report
is the case.
"""

URN = "urn:evidencebook-skills:human-rating"
COUNTED = ("met", "not_met")


def human_rating_record(case_id, week_key, report_capsule_id, label, rater_ref, rated_at):
    return {
        "record_version": "human-rating/v1",
        "record_id": f"{URN}:{case_id}:{week_key}",
        "epistemic_type": "human_report",
        "rated_at": rated_at,
        "blind": True,
        "rater_ref": rater_ref,
        "case": {"type": "evaluation-report", "digest_alg": "SHA-256", "digest": report_capsule_id,
                 "citation_purpose": "rated_case"},
        "label": label,
    }


def counted(rated):
    """The ratings that count toward a judge's agreement: `met` and `not_met`.
    `not_evaluable` and `out_of_scope` are ratings but not agreement or
    disagreement, so they are in neither k nor n."""
    return [r for r in rated if r["rating"] in COUNTED]
