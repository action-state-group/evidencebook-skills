---
name: daily-judge-and-close
description: Cron-run, once per day. Judge the day's cases against a compiled contract's clauses and seal the day's Close. No human in this loop; a failed seal stops the run and reports evidence unavailable.
---
# Daily judge-and-close

Compiled per contract by `evidence-contract-compile`; this file is the template the
compiler specialises, not something a customer edits by hand. Runs unattended, nightly.
There is no approval point in this loop by design — every judgment is pinned and every
seal either succeeds or the run stops and says so; nothing here waits on a human.

Runnable with `capsulectl` built from `capsule-cli` main, over a jsonl profile (whose one
log is its evidence book). [`../../scripts/run_daily.py`](../../scripts/run_daily.py)
performs exactly the steps below for one day, and `tests/fresh_env.sh` runs it end to end
on the tau2 airline book. Still pending: the `capsulectl-engine` plugin, so a contract with a
`tier: recomputed` clause cannot run yet (the tau2 demo contract has none).

## Verbs this skill may call, and nothing else

- `cll list --profile NAME` — read the day's range: the capsules the book committed on
  the day (`appended_at`, UTC), of which the cases are those whose payload carries a
  `case`. Re-running a day seals nothing new: each report's capsule is built with a
  timestamp fixed to the day, so the same judgment is the same capsule, and `book close`
  returns the day's existing Close (`already_closed: true`).
- `get` / `verify --capsule FILE` — resolve and authenticate each case before acting on
  it (`get --raw --output FILE`, then `verify`). Never act on an unverified record.
- `plugin ls` then `capsulectl-engine fold run --clause ID --profile NAME` (plugin, not
  built yet) — for every clause this contract marked `tier: recomputed`, run the
  registered fold. No model runs for these clauses; the fold's own verdict
  (`established`/`failed`/`not present`) is final.
- `judge pin FILE` — resolve the pinned judge (model id, prompt digest, axes digest,
  sampling) before judging anything. A day's judgments all cite the same pin; a pin that
  changed mid-day is a compile-time error, not something this skill silently absorbs.
- the pinned judge itself, over each case citing acts and method by digest — for every
  clause this contract marked `tier: judged`. The judge proposes a verdict (`met`/`not_met`/
  `not_evaluable`); this skill never overrides it and never infers a verdict for a case
  the judge could not reach. A deployment points the run at its pinned judge; tests use a
  deterministic stand-in that says it is one.
- `publish --request FILE` — seal one `evaluation-report/v1` per case per judged clause
  (epistemic type `semantic_judgment`), citing the source case capsule and the judge pin.
- `book close --period day --date DAY --counterparty BOOK_ID [--peer FILE --peer-checkpoint-key HEX]`
  — seal the day's Close. `capsulectl` requires a counterparty: the one the contract
  names. With no peer bundle held, the Close is unilateral (every correlated exchange in
  it reads `INSUFFICIENT`) and the run log says so; it is not a lesser Close, it is an
  honest one for a single-party contract. A contract with no counterparty passes the
  compiled placeholder (`capsulectl book close` requires the flag today) and never invents a
  party. `book close` refuses a day that has not ended, so a run closes the previous day: the
  reports a run seals are committed on the day it runs, so the judgments of day D's
  cases, made on D+1, are covered by the Close for D+1, sealed by the next run. `book close` also refuses a
  book whose times are displaced by a clock jump, and a day whose exchanges were pinned
  into the next; report the refusal verbatim as `evidence unavailable` for the Close and
  never work around it.
- `reconcile --period day --counterparty BOOK_ID --peer FILE --peer-checkpoint-key HEX` —
  when the contract names a counterparty book, resolve the six states (MATCHED, A_ONLY,
  B_ONLY, CONFLICTING, INSUFFICIENT, UNRESOLVED) from the counterparty's held bundle.
  **Never a live query against the counterparty** — reconcile reads only what each side
  has already sealed and held. A day with an INSUFFICIENT count is reported as exactly
  that, never rounded up to MATCHED or silently dropped from the day's tally.

## Every action seals a record

Each report and the Close are the records of the judging and closing they did. Any
other action, such as `judge pin` run on its own or a roll-up, seals one capsule.
Seal it with `scripts/skill_action.py`. That is one `skill-action/v1` capsule with
digests only (inputs, stdout, argv), never contents, paths, profile or environment.
For example:

```sh
python3 scripts/skill_action.py --profile NAME --skill daily-judge-and-close --action judge-pin \
    --at 2026-09-23T23:59:59Z --input pin_input=PIN.json -- capsulectl judge pin PIN.json
```

`--at` fixes the capsule's timestamp, so a re-run with the same `--at` seals nothing
new. A failed action is sealed too (`outcome: failed`). If its record cannot be sealed,
the action reports `evidence unavailable` and the skill stops there. See
`docs/skill-action-capsules.md`.

## Evidence policy

Every consequential action here (a fold result committed, a judgment sealed, a Close
sealed) must produce a record. If a seal fails at any step, this skill reports
`evidence unavailable` for that step, stops before the next consequential action for
the same case or clause, and does not infer that the underlying action — the fold
result, the judgment, the day itself — failed to occur just because its record could
not be made. A partial day (some clauses sealed, one seal failed) is reported as
exactly that: which clauses closed, which did not, and why.

## What this skill never does

Invent a fold for a `recomputed` clause that names no registered fold — that is a
compile-time rejection in `evidence-contract-compile`, not something this skill papers
over at run time. Judge a `recomputed` clause, or fold-check a `judged` one — the tier
is fixed at compile time. Reconcile against a live counterparty query. Re-open or
re-judge a case a prior day already sealed a report for. Decide the disclosure policy —
it reads `payloads`/`suppress` from its compiled resolved-spec and passes it through to
whatever later builds a bundle; it never chooses what to withhold.
