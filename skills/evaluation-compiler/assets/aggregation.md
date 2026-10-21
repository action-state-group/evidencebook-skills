# Cross-case aggregation execution

The agent executing a generated **aggregation** skill owns this workflow. It runs
only after per-case evaluation reports exist: its input is `evaluation-report/v1`
Capsules, never source interactions. Use Capsule CLI commands from
`capsule-cli.md` and ordinary file operations. Do not create runners, helper
programs, scripts or Makefiles. Do not edit the generated bundle; corrections
belong in the compiler and require regeneration.

Aggregation reduces many completed judgments into one summary; it never re-judges.
The per-case `aggregate` inside each report is the within-case roll-up across that
run's axes. This skill produces the orthogonal **cross-case** roll-up across many
runs and publishes it as a new `evaluation-summary/v1` Capsule.

## Select and verify the reports

Resolve the runtime profile and the requested range or append-time window. Enumerate
CLL pages and freeze the exact selected entries. Get each Capsule and verify its
identity, trusted producer signature and bound payload before reading its judgments.
A failed or missing required verification is an execution error that drops that report
from the set with an explicit reason; it is not counted as any axis status.

Accept only `evaluation-report/v1` Capsules. Skip and record any other spec version,
and skip a report produced by a different bundle (different `axes` digest) rather than
mixing incomparable axes into one rate.

A shared `axes` digest makes the questions comparable but does not by itself make the
cases one cohort. Establish and enforce a **cohort**: the contributing reports must
describe the same evaluated subject (system/model/config) and dataset revision — read
those from each report's subject/source identity and reject or explicitly group mixed
cohorts rather than blending them into one rate. Deduplicate by a unique **case/trial
key** (e.g. `case.task_id` + `case.trial`): if the same case/trial appears in more than
one report, keep one deterministically (e.g. the highest-sequence report) or reject the
set — never count a case twice. Freeze the contributing set: report Capsule IDs, their
sequences, the shared `axes` digest, the cohort identity, and three distinct counts:
the report count, the unique case/trial count (after dedup), and the unique case count
(e.g. a tau2 4-trial run backfilled per trial has more case/trial reports than tasks).

## Reduce the judgments

Read each report's `axis_judgments` only. Do not re-open the source interactions,
re-extract outcomes, or import raw source data — the reports are the evidence. Each
judgment also carries an `outcome_id` grouping it under an outcome, but cross-case
reduction is **per-axis** over the shared `axes` regardless, so the grouping and the
reports' per-outcome aggregates do not change these counts.

For every axis in the shared `axes`:
- Count `pass`, `fail`, `unjudgeable` and `not_applicable` across the contributing
  reports.
- The applicable denominator excludes `not_applicable`. `pass_rate = pass /
  (pass + fail + unjudgeable)`. `unjudgeable` never counts as `pass`; report it
  explicitly so an unresolved check cannot inflate the rate.

Then compute the cross-case roll-up named by `cross_case_aggregation`. This policy is
**independent of the within-case `aggregation`**: reduce from each report's
`axis_judgments` (and, for `native`, its recorded native result) directly — never from
the report's within-case `aggregate`, which is `null` whenever the per-case policy was
`none`.
- `rate` — the per-axis pass rates above, with no single overall number.
- `all_required` — the fraction of contributing cases that pass, reconstructed here from
  each report's flat `axis_judgments` into the two-level within-case rule (never from the
  stored `aggregate`, so it still works when the per-case policy was `none`): group the
  judgments by `outcome_id`, drop `not_applicable` axes, and mark each **required** outcome
  a pass only if its remaining required axes are a **nonempty** set that are all `pass`
  (any `fail` or `unjudgeable` fails the outcome; a required outcome with no applicable
  required axis is not a pass). The case passes only if its **required** outcomes are a
  nonempty set that all pass; axes of optional outcomes do not affect the case result. The
  shared `axes` metadata supplies each axis's `outcome_id` and the `role` of every axis and
  outcome.
- `native` — the benchmark's resolved scoring contract (e.g. tau2 `pass^k`), applied to
  the native result recorded in each report, grouped by the case/trial key so the
  benchmark's task/trial semantics are preserved; do not invent a substitute score.
  `native` requires every contributing report to carry that native result; if the
  per-case reports do not record it, `native` is unavailable and the compiler must
  reject the configuration rather than emit an undefined score.

Record the same three counts (report count, unique case/trial count, unique case count),
the dropped/skipped reports with reasons, and any axis whose applicable denominator is
zero (reported, not silently passed).

## Publish and verify the summary

Create a new aggregation identity for this run. Record the aggregation bundle's
instructional-file digests, the shared `axes` digest, and the CLI digest, plus the
source store/namespace/log, the frozen contributing report set and the resolved
`cross_case_aggregation` policy. These identify the reducer that produced this
summary; never manufacture historical provenance.

Write one `evaluation-summary/v1` JSON payload holding: aggregation identity, source
selection (store/log and contributing report Capsule IDs + sequences), bundle
provenance, the shared axes digest, per-axis counts and rates, the resolved roll-up,
the dropped/skipped reports, verification references and limitations.

Prepare a `capsule-seal-request/v1` request as specified in `capsule-cli.md`; AAC
digest inputs reject floating-point numbers, so encode rates and any decimal metadata
as decimal strings. Call `capsulectl publish`, then get the returned summary Capsule,
verify its identity/signature/trust and bound payload, and read back its sequence from
the target CLL. A summary reduces many reports, so it binds them through the enumerated
contributing report Capsule IDs/sequences in its source selection (and composed members
where the store records them), not through a single-parent `chain` block; the single-parent
`chain` links a per-case report to the one source interaction it evaluated. The summary is
itself an appended, checkpointable, witnessable Capsule.
Keep run data outside the distributed bundle. Report the summary Capsule ID/sequence,
the contributing set, and any dropped reports or zero-denominator axes.
