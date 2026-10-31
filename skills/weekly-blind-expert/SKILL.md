---
name: weekly-blind-expert
description: Cron-run, once per week. Draw a stratified sample of the week's judged cases, present them to a human blind to the judge's verdict, and seal the calibration summary and the week's Close. The human's ratings are the approval point.
---
# Weekly blind-expert audit

Compiled per contract by `evidence-contract-compile`; this file is the template the
compiler specialises, not something a customer edits by hand. Runs weekly, and
**pauses for a human** — it is the one point in the whole cron contract with a human in
the loop, and the human's ratings are the approval; this skill never fills one in on
their behalf, never infers a rating from a timeout, and never proceeds past the sample
with fewer ratings than were drawn without reporting the shortfall.

Runnable with `capsulectl` built from `capsule-cli` main.
[`../../scripts/run_weekly.py`](../../scripts/run_weekly.py) performs exactly the steps
below for one week: without the human's ratings it seals the sample manifest, writes the
blind packets and stops (exit 3); given them, it seals the ratings, the calibration summary
and the week's Close. `tests/fresh_env.sh` runs it end to end on the tau2 airline book,
with a deterministic stand-in rating the packets in place of the person.

## Verbs this skill may call, and nothing else

- `cll list` / `get` / `verify --capsule FILE` — resolve and authenticate the week's
  `evaluation-report/v1` records (those whose `period` is a day of the week) before
  sampling from them.
- Draw the sample per the contract's `sample_policy` (`weekly: N`, `stratify_by`),
  reusing the deterministic rule this repo already specifies in
  `docs/calibration-sampling-spec.md` (order each stratum by the hex of
  `SHA-256(u32be(len(seed)) || seed || report_capsule_id)`, break ties by capsule id,
  take the first `n` per stratum) — do not invent a second sampling rule for this
  skill. Seal the draw as `sample-manifest/v1` (frame, strata sizes, seed, exact rule,
  selected report ids) via `publish` **before** any human sees a case — the
  manifest is what makes the sample unable to be cherry-picked or redrawn after the
  fact.
- For each sampled report, resolve the source interaction and the same
  independently-sourced desired-outcome materials the judge used (the audited axis
  rubric, the declared criteria or evidence procedure) — transcript-blind, as the
  judge itself required. Blindness depends on the reviewer receiving the packets
  directory and nothing else: the run writes it beside, never inside, its working
  directory, which holds the report capsules with their verdicts. Assemble a packet that
  **excludes** the report's verdict,
  rationale, axis judgments and stratum label, and withholds any field the contract's
  `disclosure.suppress` list names (with digest, never silently dropped).
- Present the packet to a human expert; record their pass/fail as `human-rating/v1`
  (epistemic type `human_report`, `blind: true`), chained to the `evaluation-report/v1`
  Capsule it audits, via `publish`.
- `calibration summarize REPORTS_FILE RATINGS_FILE` — reduce the week's ratings against
  the sampled reports they audit into **agreement as k of n per judge pin**, nothing more.
  The verb returns those per-pin totals only. The sealed `calibration-summary/v1` records
  (one per judge pin, k of n **per clause**, drift 0 of 0 until a drift check is run) are
  built by `scripts/calibration_summary.py`, as `run_weekly.py` step 5 does, and checked
  against the verb's totals before anything is sealed. The drawn sample size and any
  shortfall are in the run's log, the sample manifest and the ratings, not in the record.
  See the flag below — this is a deliberate, narrower output than this repo's own
  pre-existing calibration estimators.
- `book close --period week --date DAY --counterparty BOOK_ID [--peer FILE --peer-checkpoint-key HEX]`
  — seal the week's Close, with the same counterparty and refusal rules as the daily
  skill: unilateral when no peer bundle is held.

## `calibration-summary/v1` is k-of-n only

`calibration-summary/v1` is a `derived_metric` reporting agreement as k of n per clause for
one judge pin (the record cites the pin by digest). The drawn sample size and any shortfall are
reported by the run and by the sample manifest and ratings it cites, not by this record, and nobody computes an accuracy
score from it. The estimators in `docs/calibration-sampling-spec.md` (`Â`, `p̂`, the
error rates) are marked superseded there; that document's sampling rule and blinding
rules still apply.

## Every action seals a record

`scripts/run_weekly.py` seals one `skill-action/v1` capsule each for the week's frame
read and the blind packets handed to the reviewer (their digest, never their content).
The manifest, each rating, one calibration summary per judge pin and the Close are their own
capsules. Any action run by hand seals one capsule too.
Seal it with `scripts/skill_action.py`. That is one `skill-action/v1` capsule with
digests only (inputs, stdout, argv), never contents, paths, profile or environment.
For example:

```sh
python3 scripts/skill_action.py --profile NAME --skill weekly-blind-expert --action calibration-summarize \
    --at 2026-09-27T23:59:59Z -- capsulectl calibration summarize SAMPLED.json RATINGS.json
```

`--at` fixes the capsule's timestamp, so a re-run with the same `--at` seals nothing
new. A failed action is sealed too (`outcome: failed`). If its record cannot be sealed,
the action reports `evidence unavailable` and the skill stops there. See
`docs/skill-action-capsules.md`.

## Evidence policy

Every consequential action (the sample manifest, each human rating, the calibration
summary, the week's Close) must produce a record. A seal failure stops the run before
the next consequential step and reports `evidence unavailable`; it never infers that a
rating was given, or that the week closed, from the absence of its record. If fewer
ratings come back than were drawn (a rater unavailable, a case dropped on
verification), the run reports the shortfall against the drawn sample, not a silently
smaller stated sample; a clause's `n` in the summary counts rated cases only. A week with no
sampled reports seals no summary (the schema needs a judge pin and a clause): the log
reads `drawn: 0` and `calibration_summaries: []`.

## What this skill never does

Show a rater the judge's verdict, rationale, or the case's stratum. Fabricate a rating
for an unsampled case, or for a sampled case nobody rated. Redraw or re-stratify a
sample after the manifest is sealed. Compute or publish an accuracy score, false-pass,
or false-fail rate under `calibration-summary/v1` — see the flag above. Decide the
disclosure or sample policy; both are read from the compiled resolved-spec and applied,
never chosen here.
