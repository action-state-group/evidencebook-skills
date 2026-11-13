# Zero to a verified outcome report

One binary (`capsulectl`) with its `capsulectl-book` plugin, a pack a person
can edit and recompile, and one command (`scripts/report.sh`) that judges a
day's recorded conversations against that pack's rubric, seals the result and
renders it. The output, an **outcome report**, is a
self-contained **`report.html`** you open offline in any browser; the sealed
bytes are verified in your browser, with nothing server-side to trust. This page builds it
from nothing, using only released binaries and one named commit of this
repository.

## Versions this page was run on

| Piece | Version | Where |
| --- | --- | --- |
| `capsulectl` | `v0.1.0-rc31` | [capsule-cli releases](https://github.com/action-state-group/capsule-cli/releases/tag/v0.1.0-rc31) |
| `capsulectl-book` plugin | `v0.1.0-rc31` | [evidencebook release `capsulectl/v0.1.0-rc31`](https://github.com/action-state-group/evidencebook/releases/tag/capsulectl%2Fv0.1.0-rc31) |
| `evidencebook-skills` (pack compiler, `report.sh`, skill scripts) | commit `97d72d0` | this repository; it has no tags |

`capsulectl` and the plugin must be the same release: `plugin install` refuses
a mismatch. `capsulectl v0.1.0-rc32` is out, but no plugin is built for it
yet, so this page pins the matching rc31 pair. When a newer pair exists, use
it (the commands do not change) and re-check that step 6's report says
`"verification":"pass"`.

## Prerequisites

The commands below use `darwin-arm64` (Apple silicon). On another platform,
replace `darwin-arm64` with `linux-amd64` or `linux-arm64` in every download
and checksum command.

`go` (to build one test fixture in step 5), `python3` with `venv`, `git`, `jq`,
`gh` for the downloads. The only non-stdlib Python package is
`jevals`, which step 2 installs into its own virtualenv.

## 1. Install `capsulectl` and the book plugin

Download both binaries for your platform (`darwin-arm64`, `linux-amd64` or
`linux-arm64`), check them against the release's `SHA256SUMS`, and install the
plugin:

```console
$ gh release download v0.1.0-rc31 --repo action-state-group/capsule-cli \
    -p 'capsulectl-v0.1.0-rc31-darwin-arm64' -p SHA256SUMS
$ grep darwin-arm64 SHA256SUMS | shasum -a 256 -c
$ mkdir -p ~/.local/bin && export PATH="$HOME/.local/bin:$PATH"
$ install -m 0755 capsulectl-v0.1.0-rc31-darwin-arm64 ~/.local/bin/capsulectl
$ gh release download capsulectl/v0.1.0-rc31 --repo action-state-group/evidencebook \
    -p 'capsulectl-book-v0.1.0-rc31-darwin-arm64' -p SHA256SUMS --clobber
$ grep darwin-arm64 SHA256SUMS | shasum -a 256 -c
$ install -m 0755 capsulectl-book-v0.1.0-rc31-darwin-arm64 ./capsulectl-book
$ capsulectl plugin install ./capsulectl-book
```

`plugin install` prints `"version_check":"matches capsulectl v0.1.0-rc31"`.
The release notes of each give a `gh attestation verify` command to check the
build attestation too. `capsulectl book --help` now lists the book verbs
(`book result build`, `book report build`, ...) that `report.sh` calls.

## 2. Get the skill and pack

```console
$ git clone https://github.com/action-state-group/evidencebook-skills.git
$ cd evidencebook-skills
$ git checkout 97d72d0
$ python3 -m venv .venv && . .venv/bin/activate
$ pip install --quiet jevals
```

Steps 2 onward all run from inside this checkout. Stay there:
`capsulectl profile create` records its key-file paths exactly as given, so
generating keys in one directory and sealing from another breaks the profile
(seal fails with "invalid input or profile configuration").

`jevals` is how `scripts/judges/jev_judge.py` talks to Jev, and how the mock
backend below stands in for it with no key and no network call.

A person who wants different criteria edits
`packs/airline-support-outcomes/pack-source.yaml` (tier, wording, the
`not_applicable_verdict` / `within_fare_rules_recomputed` /
`done_in_full_refusal_aware` switches, the report template) and recompiles it.
`--out` names the `demo/<pack>` directory the compiler writes into:

```console
$ python3 scripts/pack_compile.py compile packs/airline-support-outcomes/pack-source.yaml \
    --out demo/airline-support-outcomes
```

Recompiling the unmodified pack source reproduces the committed `demo/` files
byte for byte. That is the whole edit-and-rerun loop.

## 3. Set the Jev key (real runs only)

Skip this step for the mock path below. For a real run against Jev (the
hosted judge model service this pack's rubric runs on), set the key you got
from Jev onboarding, and never commit it:

```console
$ export TYPESAFE_API_KEY=<your-jev-api-key>
```

and add `--judge-backend live` to the `report.sh` call in step 6. Without a Jev key, an `OPENROUTER_API_KEY` reaches TypeSafe's `jev-1.13` through OpenRouter (served by TypeSafe; OpenRouter does not pin the patch build). Conversations then pass through OpenRouter as well as TypeSafe, without zero data retention.

## 4. Set up a book

```console
$ capsulectl key generate --output producer.seed > producer.json
$ capsulectl key generate --output checkpoint.seed > checkpoint.json
$ capsulectl profile create --name tau2 --type jsonl --jsonl-path ./store \
    --namespace tau2 --log-id tau2-airline --log book --operator tau2-demo \
    --signing-key-file producer.seed --trusted-key "$(jq -r .public_key producer.json)" \
    --checkpoint-signing-key-file checkpoint.seed --checkpoint-trusted-key "$(jq -r .public_key checkpoint.json)"
$ capsulectl store init --profile tau2
```

## 5. Seal the 50 tau2 scenarios

This uses the full 50-case trial-0 set from the shipped `claude-3-7-sonnet`
tau2 airline results file. A real producer seals its own agent interactions
here instead. `capsulectl seal` writes a sealed artifact; `tests/bookfixture`
(this repo's test fixture) places the sealed cases in the book at an exact
time, which is how step 6's `--date` finds them. It is its own Go module, so
build it from inside its directory:

```console
$ (cd tests/bookfixture && go build -o ../../bookfixture .)
$ python3 demo/backfill/backfill.py \
    --results airline-data/claude-3-7-sonnet-20250219_airline_default_gpt-4.1-2025-04-14_4trials.json \
    --out ./requests
$ mkdir -p ./cases
$ for request in $(ls ./requests/task-*.json | sort | head -n 50); do
    capsulectl seal --profile tau2 --request "$request" --output "./cases/$(basename "$request")"
  done
$ DAY=$(python3 -c 'import datetime as d; t=d.date.today(); m=t-d.timedelta(days=t.weekday()+7); print(m+d.timedelta(days=2))')
$ ./bookfixture seed --store ./store --log-id tau2-airline --operator tau2-demo --namespace tau2 \
    --signing-key-file producer.seed --checkpoint-key-file checkpoint.seed \
    --at "${DAY}T12:00:00Z" ./cases/*.json
$ capsulectl book cll list --profile tau2 --limit 1000 | jq '[.entries[] | select(.record_type=="published_capsule")] | length'
50
```

`$DAY` is the previous ISO week's Wednesday: a day that has ended.

## 6. Judge, roll up, seal and render, in one command

`scripts/report.sh` runs `run_daily.py` (nine criteria per case,
one judge request per conversation), `rollup_day.py`, `capsulectl book result
build`, a fresh checkpoint, `disclose`, and `book report build`. Mock backend,
no key, no network call:

```console
$ scripts/report.sh --spec demo/airline-support-outcomes/compiled.json \
    --profile tau2 --date "$DAY" --out report.html --capsulectl capsulectl \
    --attach-input-originals
```

Run it once per book and day. `run_daily.py` closes the day it judges, and a
second run of the same day, by hand or through `report.sh`, stops with
`missing or mistyped 'reconciliation'`. To judge again, redo steps 4 and 5 for
a fresh book.

The last lines show `"verification":"pass"`, `"verdict":"VALID"` and
`"unsupported_claims":0`. That checks the evidence chain, not the judging:
on the mock backend the verdicts are a deterministic hash of each request, so
the page's met / not-met numbers are placeholders and resolve no conversation.
Swap in a key (step 3) for real verdicts. **`report.html` lands at the `--out` path**: here
`./report.html` inside your checkout. Open it in any browser. It is
self-contained (the viewer runtime, including its WebCrypto verification, is
embedded) and it **verifies offline**, with no server and no network call.
`report.sh --help` documents `--title`, `--seal` (writes the page's own digest
into the book and checks it back) and the other options.

## 7. What `--attach-input-originals` does

It is opt-in: it passes the same flag to `capsulectl disclose`, which reads
each published capsule's retained input original from the book's **artifact
store**, checks it against the capsule's `agent_input_digest`, and carries it
in the bundle (extension `capsulectl/agent-input-originals/v1`). The Result v0
that `rollup_day.py` writes cites each conversation's case record beside its
reports, so the page's drill-down shows each conversation's full transcript.
Leave the flag off and the bundle carries digests only: the page then shows
verdicts and evidence but no transcripts. The flag discloses the raw
conversations, not just their digests; use it only when that is intended.

## 8. What the page shows

Every term the page prints (pack, version, criteria and their wording) is read
from the sealed claims and reports, or marked "not stated". The pack's
`presentation.json` block (wording of the questions and criteria) is the
producer's text, carried outside the signed records; the sealed Result pins
its SHA-256, so a block changed after sealing reads as unsigned producer text.
Verdicts and counts always come from the signed claims.

## What this page does not cover

- **A real Jev run.** The commands above use the mock backend, whose verdicts
  are a deterministic hash of the request, so the mock report resolves no
  conversations. Swap in a key per step 3 for real verdicts.
- **Judge accuracy.** Against a 15-conversation expert-rated set, the judge
  (`jev-1.13.0`, this rubric) returned 6 false passes; see
  [`jev-judge.md`](jev-judge.md). A judged `met` is the judge's reading, not
  ground truth.
- **A tagged `evidencebook-skills`.** This repository has no tags or release
  process, so the pin above is a commit. When it tags a release, pin to that.
