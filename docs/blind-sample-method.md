# Blind human sample: the method every Terms Pack report uses

One method, reused by every Terms Pack (pack). A pack names its own numbers in
`sample_policy`; everything else here is the same for every pack. The draw rule and the
record shapes are defined in [`calibration-sampling-spec.md`](calibration-sampling-spec.md)
and run by [`../skills/weekly-blind-expert/SKILL.md`](../skills/weekly-blind-expert/SKILL.md);
this page does not restate or fork them. A report states which parts of this method it
followed; one that did not run a sample says so rather than leaving the line out.

## Sample size

**20 cases per report** for launch. The draw is stratified by the judge's verdict, so a
pack sets `sample_policy.per_stratum: 10` and the two judged strata, `met` and `not_met`,
give 20. A pack that turns on `out_of_scope` draws that stratum too, on top of the 20
(see [Out-of-scope cases](#out-of-scope-cases)). When a stratum holds fewer than 10
cases, every case in it is drawn and the report states the shortfall; the gap is never
filled from another stratum. A report that states k of n also states n.

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

**Grader: `<GRADER ROLE — to be named>`.** One person in that role grades the sample. A
model never stands in for the grader, and no rating is filled in from a timeout. The role
(and, where the report's terms allow it, the person) is recorded in each `human-rating/v1`.

The grader receives the packets directory and nothing else. A packet carries the case and
the evidence the judge had (the rule text, the disclosed facts, the criteria), never the
verdict, rationale, axis judgments, stratum or report id. The grader answers `met`,
`not_met` or `not_evaluable` for the one rule the packet names. When the pack turns on
`switches.out_of_scope_verdict` (the airline pack does), the grader may also answer
`out_of_scope`; `scripts/run_weekly.py` refuses an `out_of_scope` rating from a pack that
leaves the switch off.

## Withheld cases

A case is withheld when what the rule needs was not disclosed: the bundle's
`payloads_mode` is `none` with no disclosures, nothing in it was disclosed, or the
record named was missing or undisclosed (`scripts/judge_bundle.py`). It is recorded
`not_evaluable` with that fixed reason, no judge is called, and it is never dropped:

- the report counts withheld cases in the frame, by reason, beside the sample;
- a withheld case is outside the `met`/`not_met` strata, so it is not one of the 20 and
  is not shown to the grader;
- a field a pack's `disclosure.suppress` names is withheld from the packet by digest,
  and the packet says which field.

## Out-of-scope cases

With `switches.out_of_scope_verdict` on, the judge can answer `out_of_scope`, and those
reports are drawn and counted like any other verdict:

- **Stratified:** the draw stratifies by verdict, so `out_of_scope` reports are a stratum
  of their own, drawn by the same rule up to `per_stratum`. They are never taken from the
  `met`/`not_met` 20; at `per_stratum: 10` they add up to 10 drawn cases.
- **Counted:** each drawn `out_of_scope` case is in the drawn n and, when it is not
  rated, in the shortfall. A rating agrees with the judge only when it is the same word as
  the verdict: an `out_of_scope` report agrees only when the grader answers
  `out_of_scope`, and a `met` or `not_met` report the grader calls `out_of_scope` is
  rated and does not agree. Agreement stays one k of n per judge pin over every drawn
  stratum; `out_of_scope` is not reported apart.

## What the report states

Agreement as **k of n** per judge pin, the drawn n, the shortfall and its reasons, the
manifest's capsule id, and the grader role. Never a score, a rate presented as accuracy,
or a rating of the agent.

## Not yet run

- `scripts/run_weekly.py` draws per week. A report covering more than one week draws the
  20 over the whole report period; the script has no period argument yet.
- `run_weekly.py`'s packet is the airline shape (`PACKET_FIELDS`). A pack judged from
  disclosed facts (`everyday-rules`, through `scripts/judge_bundle.py`) needs a packet
  built from its bundle's disclosed records.
- The draw takes `per_stratum` from every verdict present, so `not_evaluable` cases
  form a stratum of their own today and are drawn too. This method does not count them
  toward the 20. (`out_of_scope` is drawn and counted as
  [Out-of-scope cases](#out-of-scope-cases) says.)
