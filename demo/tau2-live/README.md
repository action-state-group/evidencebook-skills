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
  judge's copy (`adjudicator`, rows withheld). Each is checked by `capsulectl verify --bundle`.

## What you need

- macOS or Linux, [uv](https://docs.astral.sh/uv/), Go 1.24+ (only to build capsule-engine).
- [Goose](https://block.github.io/goose/) 1.59 or later, with a working provider. The demo was
  run with the `claude-acp` provider (`goose configure`). The `goose` command must be on
  `PATH`, or Goose Desktop must be installed at `/Applications/Goose.app`.
- capsulectl and its two plugins, from their releases:

  ```sh
  V=v0.1.0-rc49
  gh release download $V -R action-state-group/capsule-cli -p "capsulectl-$V-darwin-arm64" -O capsulectl
  gh release download capsulectl/$V -R action-state-group/evidencebook -p "capsulectl-deal-$V-darwin-arm64" -O capsulectl-deal
  gh release download capsulectl/$V -R action-state-group/evidencebook -p "capsulectl-book-$V-darwin-arm64" -O capsulectl-book
  chmod +x capsulectl capsulectl-deal capsulectl-book
  mv capsulectl ~/.local/bin/   # any directory on PATH
  capsulectl plugin install ./capsulectl-deal
  capsulectl plugin install ./capsulectl-book
  ```

- capsule-engine, for the admission decision a deal opens under:

  ```sh
  GOBIN=~/.local/bin go install github.com/action-state-group/capsule-engine/go/cmd/capsule-engine@go/v0.6.0
  ```

The demo keeps its own capsulectl profiles under `state/config` (it sets `XDG_CONFIG_HOME`),
so it never touches your own profiles.

## Run it

From this directory:

```sh
uv sync
uv run python roleplay.py --task 40          # one live case; prints the case directory
CASE=$(ls -dt state/cases/* | head -1)
uv run python evaluate.py "$CASE"            # the evaluator's signed verdict
uv run python report.py "$CASE"              # waits for the book's checkpoint (up to about 6 minutes)
capsulectl verify --bundle "$CASE/report/bundle-keep.json"
capsulectl verify --bundle "$CASE/report/bundle-adjudicator.json"
open "$CASE/report/report.html"
uv run python export_walkthrough.py "$CASE"  # then open walkthrough/index.html
```

`--task` takes any tau² airline task id from 0 to 49. Task 40 (a passenger name change) has
one confirmed write, so it shows the gate, the act and the span join. A live run differs each
time: the agents are models.

`report.py` waits for the book's next checkpoint, because a report rests on one. The cadence
ticks about every five minutes.

## The walkthrough

`walkthrough/index.html` plays one recorded case step by step: the window book, the deal, each
turn sealed with its span, the confirmation, the check and the act, the checkpoint, the
evaluator's signed verdict, the two disclosure levels, and both verify results. It reads only
`walkthrough/data.js`, which `export_walkthrough.py` writes from a case directory. The page
checks nothing itself: `capsulectl verify` is the check. Keys: Right and Left arrows to step,
Space to play, Home to restart.

## What this demo does not do

- **No continuity across windows.** The link from one window's book to the next, and the
  check that consecutive books cover a period, are evidencebook#689. The library's window API
  covers capsulectl-book shelves, not deal shelves, so this demo cuts its books itself in
  `window.py`, one deal profile per window.
- **No person's signature.** Every act shows `person_signature: missing`. No format exists
  yet for a person to sign an act (agent-action-capsule#627).
- **Deal checks are not in core verify.** `capsulectl verify --bundle` reports the `x-deal-v1`
  extension as `uninterpreted`. VALID means the generic checks passed: signatures, record
  identity, the checkpoint and the disclosures.
- **The default judge is a mock.** `evaluate.py` uses `scripts/judges/jev_judge.py` with
  `JEV_JUDGE_BACKEND=mock`. Its verdicts are a hash of the request: reproducible, and
  meaningless about the conversation. The verdict record names that judge. A real judge
  (`--judge-cmd` without the mock, with a TypeSafe or OpenRouter key) costs money per case.
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
| `admission/pack-definition.json` | The demo admission pack: one row, the customer is not deny-listed. Demo only. |
| `tests/` | Unit tests (`uv run --group dev pytest -q tests`). |
