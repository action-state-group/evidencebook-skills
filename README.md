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

- [`docs/quickstart.md`](docs/quickstart.md) — the Terms Packs quick start:
  agent logs into a book, a pack, a judged and a no-judge report, then
  recording as you go.
- [`skills/`](skills/) — every skill in this repository, one directory each, with
  its `SKILL.md` and an `AGENTS.md` copy. [`skills/README.md`](skills/README.md)
  lists them.
- [`skills/evaluation-compiler/SKILL.md`](skills/evaluation-compiler/SKILL.md) — the
  compiler skill (intake, bundle generation, exercise).
- [`skills/evaluation-compiler/assets/execution.md`](skills/evaluation-compiler/assets/execution.md)
  — the per-case execution template adapted into each generated bundle.
- [`skills/evaluation-compiler/assets/aggregation.md`](skills/evaluation-compiler/assets/aggregation.md)
  — the cross-case aggregation template; adapted into a second **aggregation**
  bundle only when `cross_case_aggregation` is requested. It reduces
  `evaluation-report/v1` Capsules into one `evaluation-summary/v1` Capsule, never
  re-judging.
- [`skills/evaluation-compiler/references/capsule-cli.md`](skills/evaluation-compiler/references/capsule-cli.md)
  — the Capsule CLI contract copied verbatim into bundles.
- [`packs/`](packs/) — Terms Packs (packs): each pack's hand-editable
  `pack-source.yaml` (`airline-support-outcomes`, `eu-ai-act-obligations`,
  `everyday-rules`). `scripts/pack_compile.py` compiles one into four files:
  `compiled.json`, the contract the run scripts read; `judge-prompt.md` and
  `axes.json`, which `scripts/judge_pin.py` hashes into the judge pin; and
  `presentation.json`, the bundle presentation extension a report viewer
  renders (nothing in this repository reads it). `airline-support-outcomes` and
  `eu-ai-act-obligations` compile to `demo/<name>/` and run through the two cron
  skills; `everyday-rules` compiles to `packs/everyday-rules/compiled/` and is
  judged with `scripts/judge_bundle.py`, not the skills.
- [`contracts/`](contracts/) — published Evidence Contracts, one file per
  version at `contracts/<id>/<version>.json`. A pack source or a report spec
  stays the authoring form; `scripts/evidence_contract.py` compiles it to an
  Evidence Contract v0 document (agent-action-capsule interop profile §11.3)
  with one requirement per row, and a Result cites it by `contract_ref`
  (`<pack_id>@<pack_version>`, or a report spec's `<id>@<version>`). A
  published contract never changes: any edit that changes the compiled
  contract, a row's label or judge question included, needs a new version
  (`evidence_contract.py publish` writes it), and a CI check
  (`.github/workflows/contracts.yml`) fails a pull request that modifies or
  removes a published file.
  The contract states each row's rule, not its presentation wording.
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

# judged, EU AI Act obligations -- renders on the obligation card, with transcripts
$ scripts/report.sh --spec demo/eu-ai-act-obligations/compiled.json \
    --profile tau2 --date 2026-10-01 --out report.html --capsulectl capsulectl \
    --attach-input-originals --title "EU AI Act obligations: airline support agent"
```

Both converge on the same tail (`capsulectl book result build` → checkpoint →
`disclose` → `book report build`). On the judged path the pack's compiled
`presentation.json` block is wired onto the bundle
(`scripts/wire_presentation.py`) and picks the card: `eu-ai-act-compliance/v1`
→ `obligation`, `outcome-report/v1` → `outcome`. That block is the producer's
own text (check questions, criterion wording, obligation titles and
plain-language summaries), added after `disclose`, outside the signed records.
Its digest is not: before `result build`, `wire_presentation.py seal` pins
sha256(JCS(block)) of the block exactly as it will be wired inside the Result
as `x-presentation-digest` (`{template, digest_alg, digest}`; Result v0 is a
closed document, so the member takes the spec's `x-` extension form), and the
producer's signature over the Result covers it. No new record is added. After
`disclose` the same block is wired, refused if it doesn't match, and read back
with `wire_presentation.py label`: a block that matches is the producer's
signed wording, and a block changed by even one character afterwards reads as
"unsigned producer text". The words stay presentation, never evidence: every
verdict and count comes from the signed claims, and page wording still comes
from the renderer, never the bundle (presentation contract §6). On the outcome
card the wiring adds a `producer_note`, which the renderer shows under its own
"Producer's note · presentation text, not evidence" label; the card's own
checks and wording come from the sealed reports, not from the block. The
obligation card labels the producer's mapping itself, so its block is copied
unchanged. Known gap: the obligation card's header doesn't yet name the
obligation titles, test names, not-evaluable notes or the quality protocol as
the producer's wording, so those show with no label; that text is the
renderer's, and it is listed in #29's viewer follow-up. The renderers don't yet compare the block against the sealed digest
(issue #29's viewer follow-up), so until they do the page keeps its
"not evidence" labels. `--attach-input-originals`
carries each conversation's full transcript in the bundle (off by default: it
discloses the raw conversations, not only digests). `--date`/`--to` take a day range; more than one
day's `result-v0-*.json` is merged into one Result v0
(`scripts/merge_results.py`) before the tail runs. See
`scripts/report_spec.py`'s own module docstring for the full report-spec
shape (sources, grouping, metrics, threshold/forall claims), and
`scripts/specs/tau2-airline-no-judge.yaml` /
`scripts/specs/mesh-llm-settlement-draft.yaml` (a labelled DRAFT, pending
mesh-llm's own export format) for two worked examples. `--profile` names an
already set-up book (`tests/fresh_env_outcomes.sh` shows the steps that build one
from this repo's own tau2 demo data: `profile create`, `store init`,
`demo/backfill/backfill.py`, `seal`); `report.sh` only builds the report from it.

## Boundaries

The compiler is the only editable source of evaluation instructions. Generated
bundles are immutable outputs — fix the compiler and regenerate, never patch a
bundle. The host agent uses the Capsule CLI and ordinary tools; no helper programs,
runners, or scripts are generated. Operator-side data-prep and demonstrations (the
`demo/` folder) may live in this repo but are never copied into a bundle and are
ignored during compilation: the compiler's own `assets/` and `references/`
(under `skills/evaluation-compiler/`) are the only bundle-source material.
