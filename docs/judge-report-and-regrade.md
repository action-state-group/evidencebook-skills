# Judge reports and regrades

The custody and record-kind profile v0 (the
[evidencebook#116 design note](https://github.com/action-state-group/evidencebook/issues/116#issuecomment-7202305315),
section 3) reserves two record kinds and names this repository as their producer:
`judge_report` and `regrade`. This page gives their contents. It follows Steven's
answer to the note's Q3 (ops DECISION u647, 2026-11-26): "re-grade sits beside the
judged row, never replaces". So both grades stay readable: `scripts/regrade.py rows`
shows them side by side.

## `judge_report`: the judged clause report

The profile's `judge_report` is the clause report that `daily-judge-and-close`
already seals, limited to the rows a judge decided. It is not a new record and it
is not renamed. The profile's rule keeps the name of a kind that only one
implementation writes, so no second name is coined, and nothing outside this
repository reads it.

A clause report is a `judge_report` when:

- its `record_type` is `clause-report/v1`, or `evaluation-report/v1` for a report
  sealed before 2026-11-03 that has no `cases[]` (`scripts/clause_report.py`);
- its `epistemic_type` is `semantic_judgment`; and
- it names the judge pin it was judged under (`judge_pin_digest`).

A recomputed determination, including a judged clause whose verdict came from its
recompute pre-check, has no judge, so it is not a `judge_report` and cannot be
re-graded.

One record is one judged row (`scripts/run_daily.py`, `build_report`):

| Member | What it holds |
|---|---|
| `case_id`, `clause_id` | the case and the clause judged |
| `source_capsule_id` | the case capsule the judge read |
| `verdict` | the judge's grade: `met`, `not_met`, `not_evaluable`, or `out_of_scope` where the contract allows it |
| `rationale` | the judge's reason |
| `judge_pin` | the judge's identity: `model_id`, `prompt_digest`, `axes_digest`, sampling |
| `judge_pin_digest` | the digest of `judge_pin` |
| `contract`, `contract_ref`, `pack_source_digest`, `clause_claim`, `period` | the contract, the clause wording judged against, and the day |

## `regrade`: a person's grade beside the judged row

A `regrade` is a new record. It cites one judged row and carries a person's grade
and reason. `scripts/regrade.py seal` seals it.

```json
{
  "record_type": "regrade",
  "epistemic_type": "human_report",
  "regraded_at": "2026-11-27T00:00:00Z",
  "rater_ref": "rater:expert-7",
  "row": {"type": "clause-report/v1", "digest_alg": "SHA-256",
          "digest": "<the judged row's capsule id>", "citation_purpose": "regraded_row"},
  "case_id": "<the row's case_id>",
  "clause_id": "<the row's clause_id>",
  "grade": "not_met",
  "reason": "<why the person graded it so>"
}
```

- **Beside, never in place.** A regrade has no `supersedes` link and no member that
  names a replacement. The judged row keeps its verdict, and a row may have several
  regrades. All of them stay.
- **The rater** is an opaque principal reference, never a name, as in
  `human-rating/v1`.
- **The grade** uses the row's vocabulary. `out_of_scope` is allowed only when the
  contract the row was judged under allows it. `seal` then needs `--spec`, that
  compiled contract: its `contract_ref`, and its `pack_source_digest` when the row
  has one, must match the row's, its switch `out_of_scope_verdict` must be on, and
  the clause must not be `never_out_of_scope`.
- **Refused:** a row that is not a `judge_report`, a regrade of a regrade, an empty
  reason and a missing rater. A refusal seals nothing. A row that does not verify, or
  whose signer is not trusted, also seals nothing: `seal` stops with
  `evidence unavailable`.
- **Re-runs.** `--at` fixes the capsule's timestamp, so the same regrade sealed again
  is the same capsule.
- **The reason is sealed for good.** Before sealing, `seal` tells the rater that the
  reason is sealed, cannot be edited or removed, and travels with the judged row,
  and asks them to confirm. With no terminal to answer, it seals only with
  `--reason-sealed-ok`, which says the rater has already been told.
- **Counts.** A regrade changes no Result v0 verdict or tally. Calibration
  (`weekly-blind-expert`) does not read regrades: it compares the judge with blind
  `human-rating/v1` ratings, and a regrade is not blind.

## Reading both grades

`scripts/regrade.py rows --profile NAME` prints, as JSON, each judged row that has a
regrade: the judge's verdict and judge pin under `judge`, and each regrade under
`regrades`, in log order. It verifies each regrade and its row first. A regrade it
does not show is listed under `not_shown` with the reason: it does not verify, it is
malformed, it cites no judged row in the book, or its case, clause or row type
differs from the row's. A clause report missing its case, clause, verdict or judge
pin digest is not a judged row. When `capsulectl verify` gives no verdict at all,
the read stops with `evidence unavailable` instead of calling a record unverified.
