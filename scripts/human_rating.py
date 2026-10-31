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
        "case": {"type": "evaluation-report/v1", "digest_alg": "SHA-256", "digest": report_capsule_id,
                 "citation_purpose": "rated_case"},
        "label": label,
    }


def counted_cases(selected, rated):
    """The case ids that count toward a judge's agreement: the human's rating
    and the judge's verdict are both `met` or `not_met`. `not_evaluable` and
    `out_of_scope`, on either side, are neither agreement nor disagreement, so
    they are in neither k nor n (AAC#488's reader counts the same pairs).
    `selected` is the drawn (report capsule id, evaluation-report body) list;
    `rated` the {"case_id", "rating"} list."""
    verdict_of = {body["case_id"]: body["verdict"] for _, body in selected}
    return {r["case_id"] for r in rated if r["rating"] in COUNTED and verdict_of.get(r["case_id"]) in COUNTED}
