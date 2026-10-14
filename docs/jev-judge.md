# The Jev judge (`scripts/judges/jev_judge.py`)

`jev_judge.py` is the `--judge-cmd` the outcomes pack runs: it judges one recorded
conversation against each judged criterion and answers `met`, `not_met`,
`not_evaluable` or (when the contract allows it and the criterion may be)
`out_of_scope`. Its docstring is the full contract; this page states what a reader
of its verdicts needs to know.

## Calibration

Against a 15-conversation set rated by a human expert, the judge (`jev-1.13.0`, the
nine-criterion rubric) returned **6 false passes**: it answered `met` where the
expert's rating was not met. A judged `met` is the judge's reading of the
transcript, not ground truth. The weekly blind expert pass
(`skills/weekly-blind-expert`) exists to keep measuring this; criteria marked
`recompute_eligible` in the pack are the candidates for a deterministic check that
takes the judge out of the loop.

## What the pin covers

The judge pin (`scripts/judge_pin.py`) sealed on every judged report covers:

- the model id and sampling params;
- the compiled `judge-prompt.md` and `axes.json`;
- `pack_source_digest`, the digest of the whole pack source, so a criterion edit or a
  rubric-switch flip moves the pin;
- `instruction_template_digest`, the digest of what the judge sends besides the
  clause wording and the evidence values: the instruction template, the answer
  options, the out_of_scope paragraph, and the state layout -- the source of the
  function that builds the request's sample, of the `state()` function that lays
  it out, and of every module whose extractors compute a state field
  (`scripts/airline_facts.py` for transcript mode). It builds its instructions in
  code; `{"describe": true}` on stdin reports the digest. Source, not behaviour,
  is hashed, so any edit to those functions or that module (a comment included)
  moves the pin;
- `min_confidence_micros`, when a confidence threshold is set.

The model id in a pin names the real model only when the real backend answered.
Under `JEV_JUDGE_BACKEND=mock` the judge refuses a `--judge-model-id` that does not
say it is the mock (`run_daily.py` seals that id before the judge answers), and
`scripts/judge_bundle.py` stamps the backend onto the id it seals, e.g.
`jev-1.13.0 (mock backend, no model read the evidence)`.

## Failure behaviour

Every failure is a refusal, never a guessed verdict: an unknown
`JEV_JUDGE_BACKEND` value (only `mock` and `jev` are accepted), a malformed request,
a backend error, an answer outside the allowed verdicts, or an answer below the
pinned `min_confidence` (recorded `not_evaluable`). `run_daily.py` runs each call
under `--judge-timeout` and treats a timeout or non-JSON output as
`evidence unavailable`.
