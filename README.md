# evaluation-compiler

A Claude Code skill that compiles a natural-language **scenario + value
proposition** into evaluation **axes** and an executable **evaluation-skill
bundle**. The output is instructions for an agent, not a program: the generated
bundle's host agent selects a range of cases (a sequence range or time window),
verifies each, extracts outcomes in three isolated contexts, judges against the
axes, and publishes one evaluation Capsule per case.

The evaluation source is always a **CLL** (Capsule Ledger Log) of recorded agent
interactions, read through the Capsule CLI. A plain dataset (e.g. a customer-service
task set) is first **backfilled** into a CLL as Capsules and then evaluated the same
way.

## Contents

- [`SKILL.md`](SKILL.md) — the compiler skill (intake, bundle generation, exercise).
- [`assets/execution.md`](assets/execution.md) — the per-case execution template
  adapted into each generated bundle.
- [`assets/aggregation.md`](assets/aggregation.md) — the cross-case aggregation
  template; adapted into a second **aggregation** bundle only when
  `cross_case_aggregation` is requested. It reduces `evaluation-report/v1` Capsules
  into one `evaluation-summary/v1` Capsule, never re-judging.
- [`references/capsule-cli.md`](references/capsule-cli.md) — the Capsule CLI contract
  copied verbatim into bundles.
- [`demo/`](demo/) — a self-contained demonstration, **not** compiler input. It holds
  `demo/DEMO.md` (end-to-end reproductions: an investigation over an existing
  CLL, and a tau2 customer-service evaluation over a local SQLite CLL — compile →
  backfill → run → aggregate — plus an offline CLL checkpoint and the witness
  procedure), `demo/slides/`,
  and `demo/backfill/` (operator-side data-prep mapping shipped tau2 runs into
  seal requests). The compiler ignores this folder when compiling.

## Report from records: one command to `report.html`

`scripts/report.sh` is the single entry point for turning an already-set-up
book into a rendered report — either a **judged** report (Jev against a
compiled pack's rubric) or a **no-judge** report (every claim computed
deterministically from the sealed records themselves, via a declarative
`report-spec/v1` YAML, `scripts/report_spec.py`). `--spec`'s own content
picks the path; nothing else to choose:

```console
# no judge -- a report-spec/v1 YAML, e.g. scripts/specs/tau2-airline-no-judge.yaml
$ scripts/report.sh --spec scripts/specs/tau2-airline-no-judge.yaml \
    --profile tau2 --date 2026-10-01 --out report.html --capsulectl capsulectl

# judged -- a compiled pack contract, e.g. demo/airline-support-outcomes/compiled.json
$ scripts/report.sh --spec demo/airline-support-outcomes/compiled.json \
    --profile tau2 --date 2026-10-01 --out report.html --capsulectl capsulectl
```

Both converge on the same tail (`capsulectl result build` → checkpoint →
`disclose` → `report build`). `--date`/`--to` take a day range; more than one
day's `result-v0-*.json` is merged into one Result v0
(`scripts/merge_results.py`) before the tail runs. See
`scripts/report_spec.py`'s own module docstring for the full report-spec
shape (sources, grouping, metrics, threshold/forall claims), and
`scripts/specs/tau2-airline-no-judge.yaml` /
`scripts/specs/mesh-llm-settlement-draft.yaml` (a labelled DRAFT, pending
mesh-llm's own export format) for two worked examples. `--profile` names an
already set-up book (`scripts/outcomes_setup.sh` builds one from this repo's
own tau2 demo data); `report.sh` only builds the report from it.

## Boundaries

The compiler is the only editable source of evaluation instructions. Generated
bundles are immutable outputs — fix the compiler and regenerate, never patch a
bundle. The host agent uses the Capsule CLI and ordinary tools; no helper programs,
runners, or scripts are generated. Operator-side data-prep and demonstrations (the
`demo/` folder) may live in this repo but are never copied into a bundle and are
ignored during compilation: `assets/` and `references/` are the
only bundle-source material.
