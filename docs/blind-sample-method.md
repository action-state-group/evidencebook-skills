# Blind human sample: the method every Terms Pack report uses

One method, reused by every Terms Pack (pack). A pack names its own numbers in
`sample_policy`; everything else here is the same for every pack. The draw rule and the
record shapes are defined in [`calibration-sampling-spec.md`](calibration-sampling-spec.md)
and run by [`../skills/weekly-blind-expert/SKILL.md`](../skills/weekly-blind-expert/SKILL.md);
this page does not restate or fork them. A report states which parts of this method it
followed; one that did not run a sample says so rather than leaving the line out.

## Sample size

**20 cases per report** for launch: 10 per stratum from the two judged strata, `met`
and `not_met`, which needs `sample_policy.per_stratum: 10`. `airline-support-outcomes` and
`eu-ai-act-obligations` set 3 today, and `everyday-rules` sets none (see [Not yet run](#not-yet-run)). The draw is stratified by the judge's verdict
and takes `per_stratum` from every verdict present, so `not_evaluable` and
`out_of_scope` reports are strata of their own and are drawn on top of the `met` and
`not_met` cases (see [Withheld cases](#withheld-cases) and
[Out-of-scope cases](#out-of-scope-cases)). When a stratum holds fewer than
`per_stratum` cases, every case in it is drawn and the report states the shortfall; the
gap is never filled from another stratum. A report that states k of n also states n.

## Draw

1. Fix the frame: every `evaluation-report/v1` the report covers, each verified before
   it counts.
2. Draw per stratum by the rule in `calibration-sampling-spec.md`: order by the hex of
   `SHA-256(u32be(len(seed)) || seed || report_capsule_id)`, ties by capsule id, take
   the first `per_stratum`. The seed is the pack's `sample_policy.seed`.
3. Seal the draw as `sample-manifest/v1` (frame size, strata sizes, seed, rule, selected
   report ids) **before** anyone sees a case. A sample that is redrawn after the manifest
   is sealed is a second sample, and the report states both.

## Who grades

**Grader: a blind expert.** One person grades the sample, blind to the judge's verdict. A
model never stands in for the grader, and no rating is filled in from a timeout. "Expert"
claims a qualification, so each report states in its text what makes the grader an expert
for that pack (for example, "airline support lead" or "EU AI Act counsel"). Each
`human-rating/v1` is to record the role in `rater.role`, the person in `rater.id` where
the report's terms allow it, and the qualification beside them; no sealed record carries
any of them yet (see [Not yet run](#not-yet-run)).

The grader receives the packets directory and nothing else. A packet carries the case and
the evidence the judge had (the rule text, the disclosed facts, the criteria), never the
verdict, rationale, axis judgments, stratum or report id. The grader answers `met`,
`not_met` or `not_evaluable` for the one rule the packet names. When the pack turns on
`switches.out_of_scope_verdict` (all three packs on main do), the grader may also answer
`out_of_scope`, except on a criterion marked `never_out_of_scope`. `scripts/run_weekly.py`
refuses an `out_of_scope` rating from a pack that leaves the switch off, or on a
`never_out_of_scope` criterion even with the switch on, and one refused rating refuses
the whole ratings file: no `human-rating/v1` is sealed, and no calibration summary or Close
is built. (The read frame, the sample manifest and the blind-packets record are already
sealed by then, and a refusal does not remove them.) In the airline pack those criteria are
`task_resolution.done_in_full` and `grounded_communication.no_invented_policy`; a grader
answers `met`, `not_met` or `not_evaluable` there.

## Withheld cases

A case is withheld when what the rule needs was not disclosed: the bundle's
`payloads_mode` is `none` with no disclosures, nothing in it was disclosed, or the
record named was missing or undisclosed (`scripts/judge_bundle.py`). It is recorded
`not_evaluable` with that fixed reason, no judge is called, and it is never dropped. The
report counts withheld cases in the frame, by reason, beside the sample.

`not_evaluable` reports, withheld or answered so by the judge, are counted today the way
`scripts/run_weekly.py` and `capsulectl calibration summarize` count them:

- **Drawn:** they are a stratum of their own, drawn by the same rule up to `per_stratum`,
  on top of the `met`/`not_met` cases.
- **Shown:** each drawn one gets a packet, so the grader sees it.
- **Counted:** each is in the drawn n and, when it is not rated, in the shortfall. Once
  rated, it is in the n of the k of n for its judge pin, and it agrees only when the
  grader answers `not_evaluable`.

## Out-of-scope cases

With `switches.out_of_scope_verdict` on, the judge can answer `out_of_scope`, and those
reports are drawn and counted like any other verdict:

- **Stratified:** the draw stratifies by verdict, so `out_of_scope` reports are a stratum
  of their own, drawn by the same rule up to `per_stratum` (3 today in `airline-support-outcomes` and
  `eu-ai-act-obligations`, 10 at launch; `everyday-rules` sets none). They
  are never taken from the `met`/`not_met` cases; they are drawn on top of them.
- **Counted:** each drawn `out_of_scope` case is in the drawn n and, when it is not
  rated, in the shortfall. A rating agrees with the judge only when it is the same word as
  the verdict: an `out_of_scope` report agrees only when the grader answers
  `out_of_scope`, and a `met` or `not_met` report the grader calls `out_of_scope` is
  rated and does not agree. Agreement stays one k of n per judge pin over the rated cases
  of every drawn stratum, `not_evaluable` included; no stratum is reported apart.

## What the report states

Agreement as **k of n** per judge pin (n is the rated cases for that pin), the drawn n,
the shortfall and its reasons, the manifest's capsule id, and the grader's role and
qualification (in its text until a record carries them; see [Not yet run](#not-yet-run)).
Never a score, a rate presented as accuracy, or a rating of the agent.

## Not yet run

- `scripts/run_weekly.py` draws per week. A report covering more than one week draws the
  20 over the whole report period; the script has no period argument yet.
- `run_weekly.py`'s packet is the airline shape (`PACKET_FIELDS`). A pack judged from
  disclosed facts (`everyday-rules`, through `scripts/judge_bundle.py`) needs a packet
  built from its bundle's disclosed records.
- `airline-support-outcomes` and `eu-ai-act-obligations` set `sample_policy.per_stratum: 3`;
  `everyday-rules` sets none (below). The 20-case method needs 10
  per stratum. Raising it is a separate pack change, because it moves the judge pin.
- `everyday-rules`' compiled `sample_policy` is `{}`, so `run_weekly.py` stops with a
  `KeyError` on that pack rather than a clean refusal.
- The 20 is meant to be `met` and `not_met` only. Today `not_evaluable` reports are drawn,
  shown and counted as [Withheld cases](#withheld-cases) says, so a report states k of n
  with them in it until the runner leaves them out.
- No sealed record holds the grader's role or qualification yet. The spec's
  `human-rating/v1` has `rater.role` and `rater.id`, but `run_weekly.py` doesn't seal
  `rater`. No record shape has a field for the qualification, and
  `calibration-summary/v1` carries neither. Until they do, a report states the role and
  qualification in its text, and no sealed record backs them.
- `blind_packet()` does not apply `disclosure.suppress` yet (only `pack_compile.py`
  checks the list), so a pack with suppressed fields can't hand out today's packets as
  they are.
