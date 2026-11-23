# tau² live: an airline support case, sealed as it happens

A live role-play between two agents on the tau² airline benchmark, recorded on the
`x-deal-v1` deal profile, cut into window books, carried on OpenTelemetry spans by
reference, judged by a separate evaluator under its own key, and reported at two
disclosure levels that both verify. Tracking issue: evidencebook-skills#219.

- **Live, not replayed.** A Goose agent plays a fictional airline's customer service with
  tau²'s policy and its 14 airline tools (tau2-bench, MIT). A second Goose session plays the
  customer from one tau² scenario. `roleplay.py` relays the turns and seals each one as it is
  said. Nothing comes from tau²'s shipped transcripts.
- **One case, one deal.** The airline offers to a customer who keeps no records of its own
  (`to: null`) and agrees alone. The rows are the three checks of the tau² airline rubric
  (`demo/tau2-outcomes`), owed by the airline. Every turn is a `message` in the airline's
  journal.
- **The policy gate.** tau²'s policy needs the customer's explicit "yes" before any booking
  change. A write tool runs only after the airline's `deal check` reads the customer's sealed
  "yes". The act is then sealed as a `perform`. The "yes" is a received message, never an
  approval: an approval is the airline's own principal's word.
- **Window books.** One book per window (`month` by default; `day` and `year` via `--window`).
  A report covers one window and cites only that book.
- **OpenTelemetry.** One trace per case: a span per turn and a child span per tool call. A
  span carries only `aac.capsule_id`, set by capsule-emit's `stamp_reverse_join` while the
  span is open. The record stays in the book.
- **The evaluator signs its own verdict** in its own book, with its own key. The airline's
  journal cites it.
- **Two disclosure levels** of the airline's sealed report: its own view (`keep`) and the
  judge's copy (`adjudicator`, rows withheld). Each is checked by `capsulectl deal verify --bundle`.

## What you need

- macOS or Linux, [uv](https://docs.astral.sh/uv/), Go 1.24+ (only to build capsule-engine).
- [Goose](https://block.github.io/goose/) 1.59 or later, with a working provider. The demo was
  run with the `claude-acp` provider (`goose configure`). The `goose` command must be on
  `PATH`, or Goose Desktop must be installed at `/Applications/Goose.app`.
- capsulectl, its deal and book plugins, and capsule-engine (the admission decision a deal
  opens under). The commands below put them in this directory's `.tools`, so nothing outside
  it changes; the `export` line is needed in every shell you run the demo from. Use the
  `linux-amd64` or `linux-arm64` assets on Linux.

  ```sh
  cd demo/tau2-live
  V=v0.1.0-rc49
  mkdir -p .tools/bin .tools/plugins
  gh release download $V -R action-state-group/capsule-cli -p "capsulectl-$V-darwin-arm64" -O .tools/bin/capsulectl
  # The plugins come from evidencebook main until a release carries evidencebook#766 (an offer
  # to a party that keeps no records, which rc49 refuses): build them at a pinned commit.
  EB=7499da439816a66858d5c3c64793476c75a9069d
  git clone -q https://github.com/action-state-group/evidencebook.git .tools/evidencebook
  git -C .tools/evidencebook checkout -q $EB
  (cd .tools/evidencebook/capsulectl && go build -o ../../plugins/capsulectl-deal ./cmd/capsulectl-deal && go build -o ../../plugins/capsulectl-book ./cmd/capsulectl-book)
  chmod 755 .tools/plugins .tools/bin/capsulectl
  GOBIN=$PWD/.tools/bin go install github.com/action-state-group/capsule-engine/go/cmd/capsule-engine@v0.6.0
  export PATH=$PWD/.tools/bin:$PATH CAPSULECTL_PLUGIN_ROOTS=$PWD/.tools/plugins
  capsulectl plugin ls | grep -o '"name":"[a-z]*"'    # "book" and "deal"
  ```

The demo keeps its own capsulectl profiles under `state/config` (it sets `XDG_CONFIG_HOME`),
so it never touches your own profiles.

## Run it

From `demo/tau2-live`, in a shell with the `export` line above:

```sh
uv sync
uv run python roleplay.py --task 40          # one live case; prints the case directory
CASE=$(ls -dt state/cases/* | head -1)
uv run python evaluate.py "$CASE"            # the evaluator's signed verdict
uv run python report.py "$CASE"              # waits for the book's checkpoint (up to about 6 minutes)
capsulectl deal verify --bundle "$CASE/report/bundle-keep.json"          # verdict VALID
capsulectl deal verify --bundle "$CASE/report/bundle-adjudicator.json"   # verdict VALID
open "$CASE/report/report.html"
uv run python export_walkthrough.py "$CASE"  # then open walkthrough/index.html
```

`--task` takes any tau² airline task id from 0 to 49. Task 40 (a passenger name change) has
one confirmed write, so it shows the gate, the act and the span join. A live run differs each
time: the agents are models.

`report.py` waits for the book's next checkpoint, because a report rests on one. The cadence
ticks about every five minutes. Until the plugins come from a release, capsulectl prints a
warning that they are built for `0.1.0-dev`; it does not change the result. Ctrl-C during
`roleplay.py` stops the case; the turns said so far stay sealed, and the next run opens a new
case.

## The walkthrough

`walkthrough/index.html` plays one recorded case step by step: the window book, the deal, each
turn sealed with its span, the confirmation, the check and the act, the checkpoint, the
evaluator's signed verdict, the two disclosure levels, and both verify results. It reads only
`walkthrough/data.js`, which `export_walkthrough.py` writes from a case directory. The page
checks nothing itself: `capsulectl deal verify` is the check. Keys: Right and Left arrows to step,
Space to play, Home to restart.

## What this demo does not do

- **No continuity across windows.** The link from one window's book to the next, and the
  check that consecutive books cover a period, are evidencebook#689. The library's window API
  covers capsulectl-book shelves, not deal shelves, so this demo cuts its books itself in
  `window.py`, one deal profile per window.
- **No person's signature.** Every act shows `person_signature: missing`. No format exists
  yet for a person to sign an act (agent-action-capsule#627).
- **Core verify does not run the deal rule.** `capsulectl deal verify --bundle` runs core's checks
  (signatures, record identity, the checkpoint, the disclosures) and the x-deal-v1 report rule;
  that is the check this demo reports. Core `capsulectl verify --bundle` alone says INCOMPLETE on
  rc49 (`report_rule_not_checked`) and names the deal command; `report.py` keeps its result too.
- **The judge is not the rubric's pinned judge.** `evaluate.py` defaults to `goose_judge.py`:
  the model your Goose provider runs reads the conversation and the policy and answers each of
  the nine criteria with a rationale. The rubric's pinned judge (jev-1.13.0,
  `scripts/judges/jev_judge.py`) costs money per case; run it with `--judge-cmd` and
  `--judge-model-id`. `--judge mock` uses that script's mock backend, a hash with no model.
  The verdict record names whichever judge ran.
- **No counterparty copy.** The customer keeps no records of its own.
- **No collector.** Nothing reads OTel back into books (`[capsule-otel-v0]` is on hold). Spans
  carry references only.
- **The airline is fictional.** No real carrier is named. This is not a customer engagement.

## Files

| File | What it does |
|---|---|
| `roleplay.py` | Opens the case's deal and relays the two Goose sessions turn by turn, sealing each turn and tracing it. |
| `airline_mcp.py` | The airline tool server (MCP, stdio): tau²'s tools over the case's database copy, with the policy gate and the tool spans. |
| `records.py` | The airline's x-deal-v1 records through capsulectl: offer, admission, intent, agreement, messages, check, perform. |
| `window.py` | Which window book a record time falls in. The one module to replace when the library cuts window books. |
| `telemetry.py` | OpenTelemetry setup: spans as JSON lines, the reverse join. |
| `evaluate.py` | The evaluator: the repository's contract path on the case, a signed verdict in its own book, cited by the airline. |
| `report.py` | The sealed report, the two bundles, verify, and `report.html`. |
| `export_walkthrough.py`, `walkthrough/` | The walkthrough's data file and page. |
| `goose_judge.py` | The default judge command: the Goose provider's model answers each criterion. |
| `sample/task-40-2026-11-23/` | One recorded case from a run of the steps above: transcript, tool calls, spans, the evaluator's verdict, the sealed report, both bundles and their verify results, and `report.html`. `walkthrough/data.js` is exported from it. |
| `admission/pack-definition.json` | The demo admission pack: one row, the customer is not deny-listed. Demo only. |
| `tests/` | Unit tests (`uv run --group dev pytest -q tests`). |
