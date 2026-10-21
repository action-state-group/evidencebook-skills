# Statistical calibration of the judge via human-rated sampling

> **Superseded in part.** The estimators below (the judge accuracy `Â`, the error rates
> and the bias-corrected pass rate `p̂`) and the `calibration-summary/v1` payload they
> feed are superseded: `calibration-summary/v1` reports agreement as k of n per judge pin,
> with the drawn sample and any shortfall, and never a score (see
> `skills/weekly-blind-expert/SKILL.md`). The sampling design, the blinding rules and the
> `sample-manifest/v1` / `human-rating/v1` shapes still stand; the weekly skill uses the
> deterministic sampling rule defined here.

## Problem

Nobody labels the desired outcome for every interaction, so an evaluator that
requires per-case declared ground truth (`target_mode: declared`) is unrealistic
at volume (e.g. ~1000 interactions/week). We still want a defensible answer to
"how often does the agent fully resolve the request, and can we trust the
automated judge?"

Approach: the per-case evaluator judges **all** interactions (judge-only, no
ground truth). Humans independently rate a **sample** each period. Comparing the
human ratings to the judge's verdicts yields a *statistical* estimate of judge
quality and a bias-corrected population rate. Ground truth exists only for the
sample; the certified object is the **judge**, not each capsule.

This does not change the per-case evaluator contract. It adds two Capsule types
(`sample-manifest/v1` and `human-rating/v1`) and one aggregation, all reusing existing
mechanisms (Capsules, the `chain` link, the aggregation-bundle pattern). No new store,
table, or service.

## What is measured

The audited quantity is a single judged pass/fail per interaction. Pin it to a
named quantity up front — either the `full_resolution` axis or a defined overall
roll-up — and record that name in every rating and in the summary. Auditing an
ambiguous target corrupts the agreement number.

Two error rates, not one (they have different costs):

- **false-fail** `a = P(truth = pass | judge = fail)`
- **false-pass** `b = P(truth = fail | judge = pass)`

## Sampling design: stratify by the judge's verdict

Plain random sampling is the trap. At a ~90% judge-pass rate a random 10 is almost
all judge-`pass` cases: it pins `b` well but holds ~1 judge-`fail`, so it barely
measures `a` (and at a low pass rate the sparse direction flips). Stratifying by the
judge verdict gives usable precision for **both** error rates:

- Stratum P = reports the judge marked pass (population size `N_p`).
- Stratum F = reports the judge marked fail (population size `N_f`).
- Draw `n_p` from P and `n_f` from F (e.g. 5 + 5) by a fully specified rule: order each
  stratum ascending by the hex of
  `SHA-256( u32be(len(utf8(seed))) || utf8(seed) || utf8(report_capsule_id) )` (a 4-byte
  big-endian length prefix frames the seed unambiguously for any bytes), break ties by
  `report_capsule_id`, and take the first `n_s`. A bare seed or an unnamed hash/encoding
  is not reproducible across enumeration orders or implementations.

Record the frame, strata sizes, seed, the exact selection rule, and selected report ids
in a **sample manifest published as its own Capsule** before humans rate. Every
`human-rating/v1` references that manifest Capsule id, so calibration can resolve, verify
and check membership; being an appended Capsule it is immutable, so the sample cannot be
cherry-picked or re-drawn.

## Blinding

The rater must be able to decide the audited quantity, so the packet includes the
**same independently-sourced desired outcome the evaluator uses** — the audited axis
rubric and the declared criteria (or the evidence-derived procedure), sourced
transcript-blind — alongside the interaction transcript and permitted evidence. What
the rater must **not** see is any judge-derived field: the report's verdict, rationale,
axis judgments, or stratum label. Blind to the judge, not to the ground truth. Each
rating attests `blind: true`. This is the audit analog of the evaluator's extraction
isolation.

## Estimators

Count only **usable** ratings (drop `unsure` and verification-dropped); let `m_p`, `m_f`
be usable counts per stratum and use them — never the drawn `n_p`/`n_f` — in every
estimate:

- from F: `â = (#usable human-pass in F) / m_f`  → false-fail rate
- from P: `b̂ = (#usable human-fail in P) / m_p`  → false-pass rate

Raw sample agreement is **not** judge accuracy under disproportionate strata; report the
population-weighted judge accuracy `Â` and the bias-corrected pass rate `p̂`:

```
Â = [ N_p·(1 - b̂) + N_f·(1 - â) ] / (N_p + N_f)
p̂ = [ N_p·(1 - b̂) + N_f·â       ] / (N_p + N_f)
```

Intervals (target 95% *simultaneous* coverage): use a **Wilson score interval** per
stratum proportion from `m_p`/`m_f` (non-degenerate at 0/1, unlike a Wald plug-in, which
collapses to a false zero-width CI). Both stratum intervals are used at once, so take
each at the Bonferroni level `97.5%` for a ≥95% joint interval. Apply the fpc as
`mid ± fpc·h` (Wilson midpoint/half-width, `fpc = sqrt((N_s-m_s)/(N_s-1))`), then combine
by monotonicity — `p̂` and `Â` differ: `p̂` up in `â` / down in `b̂` (`p̂_L`=`b̂_U,â_L`;
`p̂_U`=`b̂_L,â_U`), while `Â` is **down in both** (`Â_L`=`b̂_U,â_U`; `Â_U`=`b̂_L,â_L`).
Degenerate strata (before the fpc): `N_s=0` absent; `m_s=0` unestimated (partial bounds,
not 0); `m_s=N_s` census (incl. `N_s=1`) → exact `[x_s/N_s, x_s/N_s]`.

Precision reality: a single period is coarse (`m=10`, 10/10 → 95% Wilson CI ≈ [72%,
100%]). Treat each period as one point on a **control chart**. Pooling periods into a
tighter number requires an explicit weighted multi-period estimator under stable strata
weights and judge behaviour — do not assert a fixed pooled precision from a period count
alone; keep drift detection separate from pooling.

## Capsule: `sample-manifest/v1`

The sampling skill publishes one manifest Capsule per period before rating, sealed and
read back like any Capsule (`ActionType=fyi`; standalone, no `chain`). Payload:

- `spec_version: sample-manifest/v1`
- `period_window`, `cohort` (shared `axes` digest, evaluated subject/model/config,
  dataset revision), `audited_quantity`
- `N_p`, `N_f`, `n_p`, `n_f`
- `seed` and `selection_rule` (the exact rule string, e.g. the SHA-256 length-prefixed
  ordering above)
- `selected`: the chosen report Capsule IDs per stratum (`{ "judge_pass": [...], "judge_fail": [...] }`)

Calibration resolves this Capsule (every rating references it), verifies it, and checks
its `period_window`, `cohort`, `audited_quantity`, strata sizes, `seed` and
`selection_rule` against the run before trusting `selected` as the membership set — not
just the envelope. A mismatch is a verification error.

## Capsule: `human-rating/v1`

One Capsule per human rating, appended to the same CLL, chained to the
`evaluation-report/v1` Capsule it audits (reuse of the `chain` mechanism — see
`skills/evaluation-compiler/references/capsule-cli.md`), forming the provenance
chain interaction ← report ← rating. The sampling skill sets the chain parent to the report; the **rater sees the
full packet defined in "Blinding"** (the interaction plus the independently-sourced
desired-outcome materials) and none of the judge-derived report fields, so the rating
audits exactly one verdict while staying blind to the judge. The chain link is also the
calibration join — no identity re-derivation needed.

Request `capsule` (PascalCase `emit.Input`; `assurance`/`ledger_mode` are derived,
not caller-set):

```jsonc
{
  "spec_version": "capsule-seal-request/v1",
  "capsule": {
    "ActionID": "urn:human-rating:<scenario>:<simulation_id>:<rater>:<run>",
    "ActionType": "fyi",
    "Operator": "<audit-program identity>",
    "Developer": "<rating-tool identity>",
    "Timestamp": "<UTC>",
    "Chain": {
      "ParentCapsuleID": "<evaluation-report capsule_id being audited>",
      "Relation": "io.evaluation.human_rates"
    }
  },
  "payload": {
    "spec_version": "human-rating/v1",
    "subject": { "case_id": "...", "simulation_id": "..." },
    "rated_quantity": "full_resolution",
    "verdict": "pass",            // pass | fail | unsure
    "blind": true,
    "rater": { "role": "...", "id": "..." },
    "sampling": {
      "frame_window": "2026-09-01T00:00Z/2026-09-08T00:00Z",
      "stratum": "judge_pass",    // judge_pass | judge_fail
      "audited_report_capsule_id": "<evaluation-report capsule_id>",
      "sample_manifest_capsule_id": "<required — the manifest Capsule this sample belongs to>"
    },
    "rationale": "optional",
    "cutoff": "<UTC>"
  }
}
```

Notes:
- The chain `parent_capsule_id` is the audited report; the calibration join is the
  chain link itself, so the confusion cell is unambiguous even if the judge is re-run.
  `subject` still records the case/trial for cohort checks and must match the report.
- `unsure` (and verification-dropped) ratings are excluded from **both** numerator and
  denominator — they are not in the usable counts `m_p`/`m_f` — and reported as nonresponse.

## Sampling-and-rating bundle

Generated before the calibration bundle (ratings must exist before they are reduced).
Its host agent reads the period's `evaluation-report/v1` Capsules, stratifies by the
judge verdict on `rated_quantity`, draws the reproducible per-stratum sample (canonical
hash ordering + digested manifest above), and for each sampled report resolves and
verifies the source interaction and assembles the rater packet (interaction + the
independently-sourced desired-outcome materials, minus every judge-derived field). It
captures each expert pass/fail and publishes a `human-rating/v1` Capsule chained to the
audited report. It never judges and never fabricates a rating for an unrated slot. This
is the one calibration-flow skill that resolves source interactions; the calibration
bundle below stays reports-and-ratings-only.

## Calibration aggregation bundle

A sibling of the existing aggregation bundle. It reduces `evaluation-report/v1`
(the judged population) together with `human-rating/v1` (the audit sample) over a
period; it never re-judges, never creates ratings, and never re-opens source
interactions.

Resources (mirrors the aggregate bundle):
- `SKILL.md` — purpose, runtime inputs (`profile`, period window, `rated_quantity`),
  and the reduce-then-publish steps. It does **not** draw samples — that is the
  sampling bundle's job; calibration only consumes the ratings that already exist.
- `references/calibration.md` — adapted from a new `assets/calibration.md`
  (`skills/evaluation-compiler/assets/calibration.md`).
- `references/capsule-cli.md` — copied as usual (`capsulectl` stays a host prereq).

Steps:
1. Select over the window: all `evaluation-report/v1` (population, with judge
   verdict on `rated_quantity`) and all `human-rating/v1` (sample).
2. `verify` each consumed Capsule, and verify each rating's complete binding to its
   report: `chain.relation == io.evaluation.human_rates`, `chain.parent_capsule_id`
   resolves to a cohort report, payload `audited_report_capsule_id` equals that parent,
   `subject` matches, the recorded stratum matches the report's judge verdict, and the
   audited report is a member of the verified sample manifest for the period. Any failure
   (including a rating for a report outside the frozen sample) drops the rating as a
   verification error, not a silent skip.
3. Join each rating to its report through the verified chain parent (never by
   interaction identity); build the confusion matrix per stratum from blind human
   `verdict` vs judge verdict, using usable counts `m_p`/`m_f`.
4. Compute `â`, `b̂`, judge accuracy `Â`, and the bias-corrected `p̂`, each with a Wilson
   + fpc interval; compare to prior window(s) for drift.
5. Publish one `calibration-summary/v1` Capsule back into the same CLL.

### `calibration-summary/v1` payload

- calibration identity; period window; scenario; shared `axes` digest;
  `rated_quantity`.
- sampling design: `N_p`, `N_f`, drawn `n_p`/`n_f`, usable `m_p`/`m_f`, method
  (`stratified_by_verdict`), seed / `sample_manifest_capsule_id` (digested), blinding attested.
- confusion matrix: counts of (judge, human) ∈ {pass, fail} per stratum;
  `unsure`/excluded counts reported as nonresponse.
- estimates: `false_pass_rate` `b̂`±CI, `false_fail_rate` `â`±CI, `judge_accuracy` `Â`±CI,
  `corrected_pass_rate` `p̂`±CI, and raw sample `agreement` labelled descriptive-only
  (decimal strings — AAC digests reject floats).
- drift: deltas vs prior window(s) and a threshold flag.
- verification references for every consumed report and rating; limitations
  (small-n caveats, excluded ratings, zero-denominator strata).

## Compiler surface

- Per-case evaluator: **unchanged** (judge-only; no ground truth per case).
- New `cross_case_aggregation` value `calibration` (alongside `none`/`rate`/
  `all_required`/`native`). When selected, the compiler generates **two** extra
  bundles beyond the per-case evaluator:
  1. a **sampling-and-rating** bundle (`<scenario>-sample/`) — reads the period's
     reports, stratifies by judge verdict, draws a seeded sample, presents each
     sampled interaction to a human expert blind to the judge verdict, and
     publishes a `human-rating/v1` Capsule chained to the audited report;
  2. a **calibration** bundle (`<scenario>-calibrate/`) — reduces the reports and
     ratings into `calibration-summary/v1`.
- New `assets/sampling.md` and `assets/calibration.md` under
  `skills/evaluation-compiler/`, referenced the way `assets/aggregation.md` is.
  `resolved-spec.json` records the audited quantity and sampling design so both
  skills agree.
- `human-rating/v1` is created only by the sampling-and-rating skill's
  human-in-the-loop step — never by the compiler, the evaluator, or a model
  standing in for the expert. The ratings must exist before calibration can reduce
  them, so the two skills run in that order.

## What this does not solve

- It certifies the judge and yields an aggregate rate ± CI; it does **not**
  produce trustworthy per-case ground truth for the unsampled interactions. Their
  per-case reports remain judge-derived and are labeled as such.
- It reduces the *cost* of ground truth (fewer cases rated), not the isolation
  question: how the desired outcome is defined for those human ratings is still a
  separate decision (human judgment here, vs derived state+policy).
