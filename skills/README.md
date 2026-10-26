# The skills

This directory is the repository's one skill tree: every skill lives in its own
directory here, with its `SKILL.md`, a byte-identical `AGENTS.md`, and any `assets/` or
`references/` it reads. Nothing outside `skills/` is a skill. `tests/test_skill_tree.py`
holds that layout.

`evaluation-compiler` is the existing compiler, still live and still the thing generated
bundles are exercised against. The other three are its evolution and the two cron-run
skills that evolution compiles. The two cron skills run (see "Running the two cron skills").

## The skills, and where each one lives

| # | Skill | Here | Status |
|---|---|---|---|
| 0 | `evaluation-compiler` | [`evaluation-compiler/SKILL.md`](evaluation-compiler/SKILL.md), with its `assets/` and `references/` | live |
| 1 | `evidence-contract-compile` | [`evidence-contract-compile/SKILL.md`](evidence-contract-compile/SKILL.md) | drafted, unwired |
| 2 | `daily-judge-and-close` | [`daily-judge-and-close/SKILL.md`](daily-judge-and-close/SKILL.md) | runnable: `scripts/run_daily.py` |
| 3 | `weekly-blind-expert` | [`weekly-blind-expert/SKILL.md`](weekly-blind-expert/SKILL.md) | runnable: `scripts/run_weekly.py` |
| 4 | `capsulectl` (thin verb skill) | **not here** | ships with `capsule-cli` at `skills/capsulectl/`, generated from `spec.yaml` |

Skill 4 is consumed, not vendored. Nothing in this repo copies its `SKILL.md`/`AGENTS.md` or
`spec.yaml` — a customer installs `capsulectl` and gets that skill with it. Duplicating the
files here would create a second copy that drifts from the binary it describes.

## Why skills 1–3 are not `spec.yaml`-rendered

`capsule-cli` renders skills from a `skill-spec/v0` document (`skills/SKILL-SPEC.md` there), so
that `SKILL.md` and `AGENTS.md` come out byte-identical from one source. That format is scoped,
by its own text, to thin tool-calling skills:

> "A **thin, tool-calling skill** — the shape this format is for — may call verbs, validate a
> contract, request evidence, verify a bundle, or inspect a result. It never reasons about
> business meaning... Contrast a **reasoning-heavy** skill (a compiler that decomposes a value
> proposition into axes and writes new instructions) — that shape does not fit this
> schema... See `evaluation-compiler`'s `SKILL.md`."

`evidence-contract-compile` *is* that reasoning-heavy compiler (it is `evaluation-compiler`,
evolved). `daily-judge-and-close` and `weekly-blind-expert` judge, sample, and blind a human —
also reasoning, not a closed verb list. Forcing any of the three into `skill-spec/v0` would mean
either misstating their verb surface or stripping the reasoning out.

So all three are hand-authored `SKILL.md` prose, in the same voice and rigor as the
`evaluation-compiler` skill, with `AGENTS.md` a literal byte-identical copy — Claude Code and
Codex read the same text. Only skill 4 goes through `skillgen`, because only skill 4 is thin.
This is the intended pattern for reasoning-heavy skills: hand-authored `SKILL.md`, with
`AGENTS.md` a byte-identical copy.

## Running the two cron skills

Both run with `capsulectl` built from `capsule-cli` main, over a jsonl profile whose one log
is its EvidenceBook. Each has an exercise script that performs exactly the skill's steps,
calling only the verbs the skill lists:

```sh
# nightly: judge yesterday's cases, seal one report per case, seal the day's Close
python3 scripts/run_daily.py --profile NAME --spec COMPILED.json \
    --judge-cmd "PINNED_JUDGE_COMMAND" --judge-model-id MODEL_ID --date YYYY-MM-DD --out RUN_DIR
# weekly: seal the sample, then pause (exit 3) for the human's blind ratings ...
python3 scripts/run_weekly.py --profile NAME --spec COMPILED.json --date YYYY-MM-DD --out RUN_DIR
# ... and resume with them: ratings, calibration summary (k of n), the week's Close
python3 scripts/run_weekly.py --profile NAME --spec COMPILED.json --date YYYY-MM-DD --out RUN_DIR --ratings RATINGS.json
```

`COMPILED.json` is a compiled contract at `demo/<name>/compiled.json`: `run_daily.py` takes
the repository root as two directories above the spec, so a Terms Pack (pack) runs here only
when compiled with `--out demo/<name>`, for example
`python3 scripts/pack_compile.py compile packs/airline-support-outcomes/pack-source.yaml --out demo/airline-support-outcomes`.
`run_weekly.py` also needs the pack's `sample_policy` (`stratify_by`, `seed`, `per_stratum`).
`everyday-rules` does not run through these skills: it compiles to `packs/everyday-rules/compiled/`
and is judged with `scripts/judge_bundle.py`.

A run closes the previous day, since `book close` refuses a day that has not ended. The reports
a run seals are committed on the day it runs, so the judgments of day D's cases, made on
D+1, are covered by the Close for D+1. The weekly run writes the blind packets to a
directory beside its run directory; give the reviewer that directory and nothing else.

`demo/tau2/compiled.json` is the compiled spec for the tau2 airline demo. Its counterparty
is a marked sample placeholder: the demo contract has none, and `capsulectl book close` requires
the flag today. The judge is any
command that reads one case on stdin and prints `{"verdict", "rationale"}`; no model runs in
this repository. `tests/fresh_env.sh` runs both skills end to end on the tau2 airline book
from a clean machine state (a new HOME, fresh clones, `capsulectl` built from source), with
`tests/stub_judge.py` and `tests/stub_rater.py` as deterministic stand-ins for the judge and
the human, and verifies every record and bundle it produced.

Still pending: the `capsulectl-engine` plugin (`fold run --clause ID --profile NAME`) for
`tier: recomputed` clauses, so a contract with such a clause cannot run the daily skill yet.

## Record family — named here, not defined here

`contract-compile/v1`, `evaluation-report/v1`, `close/v1`, `sample-manifest/v1`,
`human-rating/v1`, `calibration-summary/v1` are referenced below by name and shape only. Their
JSON schemas belong to the judge record family spec; this repo does not define or fork a second
copy, and record names are kept in step with the monthly aggregation stage that consumes them.

## Calibration is k of n

`calibration-summary/v1` reports agreement as k of n, never a score. The estimators in
`docs/calibration-sampling-spec.md` are marked superseded there; its sampling rule stays.

## Not yet done

Retiring the older compiler and judge programs, replacing `evaluation-compiler` with
`evidence-contract-compile`, and the `capsulectl-engine` plugin for recomputed clauses.
