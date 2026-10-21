# Sampling and expert-rating execution

The agent executing a generated **sampling-and-rating** skill owns this workflow.
It runs only after per-case evaluation reports exist: its input is
`evaluation-report/v1` Capsules, and its output is one `human-rating/v1` Capsule
per expert rating. Use Capsule CLI commands from `capsule-cli.md` and ordinary
file operations. Do not create runners, helper programs, scripts or Makefiles. Do
not edit the generated bundle; corrections belong in the compiler and require
regeneration.

This skill does not judge and does not compute the calibration. It draws a sample
of already-judged cases, obtains an **independent human pass/fail** for each, and
records those ratings as Capsules for the calibration skill to reduce. The human
is the ground truth for the sample; the judge is what the sample audits.

## Fix the audited quantity

Every rating audits one named pass/fail quantity recorded in `resolved-spec.json` as the
calibration target (e.g. `full_resolution`): a single named axis, a named outcome's
aggregate, or the case aggregate. It must resolve to `pass`/`fail` on every report — an
aggregate target therefore requires the within-case `aggregation` not be `none`. Use the
same quantity for the whole sample and record it on every rating. Do not mix quantities in
one period.

## Select the population and stratify

Resolve the runtime profile and the period window. Enumerate the CLL, accept only
`evaluation-report/v1` Capsules from this bundle's cohort (matching `axes` digest,
evaluated subject and dataset revision), verify each Capsule's identity, producer
signature and bound payload, and deduplicate by the case/trial key. This frozen,
verified set is the population.

Partition the population by the judge's verdict on the audited quantity that
`resolved-spec.json` records — the named axis's `status` in the report's `axis_judgments`,
the named outcome's aggregate, or the case aggregate; read that same quantity from every
report:
- stratum **P** = reports the judge marked `pass` (size `N_p`);
- stratum **F** = reports the judge marked `fail` (size `N_f`).

Random sampling wastes effort: at a high judge-pass rate a random draw is almost all
judge-`pass` cases, so it pins the false-*pass* rate `b̂` well but barely measures the
false-*fail* rate `â` (too few judge-`fail` cases) — and at a low pass rate the sparse
direction flips. Stratifying by verdict gives usable precision for **both** conditional
error rates for the same human effort, whatever the base rate. Reports whose audited
quantity is `unjudgeable`/`not_applicable` form their own excluded stratum — record them;
do not force them into P or F.

## Draw the sample

Draw `n_p` from P and `n_f` from F (sizes are runtime inputs) by a **fully specified,
reproducible** rule, not an unspecified RNG. Within each stratum, order the reports
ascending by the hex of `SHA-256( u32be(len(utf8(seed))) || utf8(seed) || utf8(report_capsule_id) )`
— a 4-byte big-endian length prefix on the seed frames the two fields unambiguously for
any seed bytes (a bare delimiter fails if the seed contains it) — break ties by
`report_capsule_id`, and take the first `n_s`. Naming the hash, byte encoding, framing,
order and tie-break is load-bearing: a bare seed, a different hash, or ambiguous
concatenation would select different reports. Sample each report at most once.

Before any rating, publish a **`sample-manifest/v1`** Capsule for the period, sealed and
read back like any Capsule (`ActionType=fyi`, standalone). Its payload records the
`period_window`, `cohort` (shared `axes` digest, evaluated subject/model/config, dataset
revision), `audited_quantity`, `N_p`/`N_f`, `n_p`/`n_f`, the `seed`, the exact
`selection_rule`, and `selected` — the chosen report Capsule IDs per stratum. Every
`human-rating/v1` for the period references this manifest Capsule's id, giving the
calibration bundle a defined, verifiable route to resolve it and check each rating's
report against the frozen selected set. The manifest is a Capsule, not a loose digest, so
the reducer can always reach the selection; being an appended Capsule it is immutable and
auditable. Immutability records the draw but does not by itself preregister it, so fix the
`seed` and per-stratum sizes **before** inspecting any verdict — derive the seed
deterministically from immutable period/cohort inputs (or a prior sealed commitment) rather
than choosing it freely — and treat a second manifest for the same period and cohort as a
rejected replacement, not a re-draw.

## Assemble the rater packet, present blind, capture ratings

The expert must be able to decide the audited quantity, so give them the **same
independently-sourced desired outcome the evaluator used**, never just the transcript.
For each sampled report, assemble a rater packet:
- resolve the source **interaction** Capsule (the report's chain parent / `source_selection`),
  `get` and `verify` it, and include its authenticated transcript and permitted evidence;
- reuse from `axes.json` the rubric(s) that define the audited quantity — the single
  axis's rubric, or, for an outcome or case aggregate, every constituent axis rubric plus
  the aggregation rule needed to reproduce that `pass`/`fail` — together with the
  desired-outcome materials via `references/source.md`: for a `declared` target, the case's
  declared criteria read by case id; for an `evidence_derived` target, the independent
  evidence **pinned to the exact evidence IDs, revisions and cutoff the audited report
  recorded** (not re-gathered from a mutable source, so rater and judge assess the same
  desired outcome; if later-established truth is used deliberately, label it a distinct
  calibration target) — sourced transcript-blind exactly as the evaluator sources them;
- **exclude every judge-derived field**: the report's verdict, rationale, axis judgments,
  and the stratum label. The rater is blind to the judge, not to the ground-truth criteria.

Present the packet and capture the expert's `pass`/`fail` (allow an explicit `unsure`)
and optional rationale. A rating produced while the rater could see the judge output is
not independent; discard it and re-rate blind, or record the exposure as a limitation
rather than count it.

Never synthesize a rating, infer it from the judge, or fill an unrated sample slot
with a model verdict. A missing rater means the sample is incomplete, reported as
such — not completed by the agent.

## Publish and verify each rating

Create a new rating identity per expert rating. Write a `human-rating/v1` payload
holding: the audited quantity, the `pass`/`fail`/`unsure` verdict, rater identity
and role, a blind attestation, the audited `evaluation-report/v1` Capsule id, the
subject case/trial identity (matching that report), the sample manifest reference,
and any rationale.

Prepare a `capsule-seal-request/v1` request as specified in `capsule-cli.md`. Chain
the rating to the report it audits: add a `Chain` block whose `ParentCapsuleID` is
that `evaluation-report/v1` Capsule id and whose `Relation` is
`io.evaluation.human_rates` (`ledger_mode: chained` is derived, not caller-set). This
makes each rating audit exactly one verdict, so the calibration join is the chain
link itself. Call `capsulectl publish`, then get the returned Capsule, verify its
identity/signature/trust and bound payload, confirm the `chain` parent resolves to
the intended report in the same CLL, and read back its sequence. Publication runs a
store-level check that the parent report exists, so rate only reports already
appended.

Keep run data outside the distributed bundle. Report the sample manifest, the rated
and unrated slots per stratum, and the published rating Capsule IDs/sequences.
