# The Jev judge (`scripts/judges/jev_judge.py`)

`jev_judge.py` is the `--judge-cmd` the outcomes pack runs: it judges one recorded
conversation against each judged criterion and answers `met`, `not_met`,
`not_evaluable` or (when the contract allows it and the criterion may be)
`not_applicable`. Its docstring is the full contract; this page states what a reader
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
- `instruction_template_digest`, the digest of the instruction template the judge
  actually sends (it builds its instructions in code; `{"describe": true}` on stdin
  reports the digest);
- `min_confidence_micros`, when a confidence threshold is set.

## Failure behaviour

Every failure is a refusal, never a guessed verdict: an unknown
`JEV_JUDGE_BACKEND` value (only `mock` and `jev` are accepted), a malformed request,
a backend error, an answer outside the allowed verdicts, or an answer below the
pinned `min_confidence` (recorded `not_evaluable`). `run_daily.py` runs each call
under `--judge-timeout` and treats a timeout or non-JSON output as
`evidence unavailable`.
