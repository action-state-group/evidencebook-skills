# Terms Packs quick start

You have months of agent logs. This page turns them into an evidence book,
checks them against a Terms Pack, and gives you a report page anyone can
open offline. Then it shows what changes when your agent records as it goes.

The example is the public tau2-bench airline set: customer-support
conversations between an agent and a simulated customer, with every tool
call the agent made. The two packs are **Airline support outcomes** (did the
agent resolve the request, within policy) and **EU AI Act obligations** (ten
obligations a single conversation can show).

1. [Install](#1-install)
2. [Logs into a book](#2-logs-into-a-book)
3. [Pick or define a pack](#3-pick-or-define-a-pack)
4. [A report with no judge, today](#4-a-report-with-no-judge-today)
5. [Judge, from the next UTC day](#5-judge-from-the-next-utc-day)
6. [Go live](#6-go-live)

Every command on this page was run top to bottom in an empty directory
against capsulectl `v0.1.0-rc18` (the GitHub release, checksums verified)
and Python packages from PyPI. Output shown is from that run, trimmed. Where
a step needed something the run did not have, the page says so.

You need `curl`, `git`, `jq`, Python 3.11 or later, and bash 4 or later
(`scripts/report.sh` uses it; on macOS, `brew install bash`).

## 1. Install

Work in an empty directory. `QS` names it for the rest of the page.

```sh
mkdir quickstart && cd quickstart && export QS=$PWD
```

Download capsulectl and its book plugin, and check both against the
release's `SHA256SUMS`:

```sh
V=v0.1.0-rc18
OS=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m); case $ARCH in x86_64) ARCH=amd64;; aarch64) ARCH=arm64;; esac
U=https://github.com/action-state-group/capsule-cli/releases/download/$V
curl -fsSLO $U/SHA256SUMS
curl -fsSLO $U/capsulectl-$V-$OS-$ARCH
curl -fsSLO $U/capsulectl-$V-plugin-book-$OS-$ARCH
shasum -a 256 -c --ignore-missing SHA256SUMS    # on Linux: sha256sum -c --ignore-missing SHA256SUMS
```

```
capsulectl-v0.1.0-rc18-darwin-arm64: OK
capsulectl-v0.1.0-rc18-plugin-book-darwin-arm64: OK
```

The release also carries a Sigstore bundle. This page checks only the
checksums.

```sh
mkdir -p bin
install -m 755 capsulectl-$V-$OS-$ARCH bin/capsulectl
install -m 755 capsulectl-$V-plugin-book-$OS-$ARCH bin/capsulectl-book
export PATH=$QS/bin:$PATH
capsulectl --version
capsulectl plugin install bin/capsulectl-book | jq -r .version_check
```

```
capsulectl v0.1.0-rc18 (commit 459aea37ad313c21d07ccb00391b60b33910abef)
matches capsulectl v0.1.0-rc18
```

Get the packs and scripts, and a Python environment with the three packages
they use:

```sh
git clone -q https://github.com/action-state-group/evidencebook-skills.git
python3 -m venv venv && . venv/bin/activate
pip install -q pyyaml rfc8785 jevals==0.1.4
```

Make a book. A book is an append-only log on your disk. Its records are
signed with a key you hold, and its checkpoints with a second key. The
profile stores the key paths as given, so give them in full:

```sh
capsulectl key generate --output $QS/producer.seed > $QS/producer.json
capsulectl key generate --output $QS/checkpoint.seed > $QS/checkpoint.json
capsulectl profile create --name airline --type jsonl --jsonl-path $QS/store \
  --namespace tau2 --log-id airline-support --operator tau2-demo \
  --signing-key-file $QS/producer.seed --trusted-key "$(jq -r .public_key $QS/producer.json)" \
  --checkpoint-signing-key-file $QS/checkpoint.seed \
  --checkpoint-trusted-key "$(jq -r .public_key $QS/checkpoint.json)" > /dev/null
capsulectl store init --profile airline
```

```
{"log_id":"airline-support","spec_version":"capsule-cli-result/v1","status":"initialized"}
```

## 2. Logs into a book

Your logs hold two kinds of thing, and the book takes each in its own form:

- **Tool calls**, the effects your agent had. `capsulectl book backfill run`
  reads them as `backfill-source-record/v0` lines: one row per call, with the
  host's own id, a monotonic cursor, the time the host says it happened, the
  tool name, a status, and a digest of the whole row as you stored it. There
  is no field for message text or argument values.
- **Conversations**, what a judge reads. Each one becomes a case record
  through `capsulectl publish`.

capsulectl has no code for any particular host. A small reader turns your
logs into those two formats. `demo/quickstart/tau2_reader.py` is the reader
for tau2; write the same thing for your own store.

Every tau2 run was recorded on one day. To show a book that spans three
months, the reader spreads six conversations over a replay schedule from
July to September 2025: each one is moved by whole days, clock time kept.
That replayed time is the host time the book records, and each case record
says so in words. Leave `--replay-from` out and your logs keep their own
times.

```sh
cd evidencebook-skills
python3 demo/quickstart/tau2_reader.py rows \
  --results airline-data/claude-3-7-sonnet-20250219_airline_default_gpt-4.1-2025-04-14_4trials.json \
  --tasks 0,1,4,7,9,19 --replay-from 2025-07-01 --replay-step-days 18 --out $QS/logs
head -1 $QS/logs/rows.jsonl
```

```
{"conversations": 6, "rows": 43, "source": "tau2.airline.claude-3-7-sonnet-20250219", "host_time_span": ["2025-07-01T16:06:22.634243Z", "2025-09-29T16:10:18.540248Z"]}
{"kind":"row","source":"tau2.airline.claude-3-7-sonnet-20250219","cursor":0,"id":"toolu_01HwogveKQVZBrHv53sg37Wr","at":"2025-07-01T16:06:01.095106Z","record_kind":"tool_call","task":"tau2:airline:task-0:trial-0","tool_call_id":"toolu_01HwogveKQVZBrHv53sg37Wr","tool":"get_reservation_details","status":"ok","raw_digest":"23aecdff…"}
```

Import the rows. Each pass commits one import record that names what it
read, where the next pass starts, and any gap:

```sh
capsulectl book backfill run --profile airline --source $QS/logs/rows.jsonl > $QS/pass1.json
jq -r .summary $QS/pass1.json
```

```
Digested 43 new host records (Tier A) and retained 9 as backfilled Capsules (Tier B; 0 already retained, 0 re-read rows verified); 0 refused, 0 anomalies, 0 gaps declared. Effects only: these say what the host recorded, not what was charged and not who approved it. Detectability of absence, not prevention.
```

Every row is committed by digest (Tier A). The rows near a consequential
signal, here the `handoff` on `transfer_to_human_agents`, are also kept as
records of their own (Tier B) so they can be shown later. The pass exits 0
when clean and 3 when it declares a gap, a refused row or an anomaly.

Now the conversations. Each case record carries `provenance_mode`
`backfilled`, the host's time as `source_asserted_at`, and the pass that
imported it:

```sh
python3 demo/quickstart/tau2_reader.py cases --plan $QS/logs \
  --import-batch "$(jq -r .import_batch $QS/pass1.json)" \
  --imported-at "$(jq -r .imported_at $QS/pass1.json)"
jq .provenance_mode $QS/logs/requests/task-1.json
for r in $QS/logs/requests/*.json; do capsulectl publish --profile airline --request "$r" > /dev/null; done
capsulectl cll checkpoint create --profile airline | jq -c '{checkpoint, indexed_sequence}'
```

```
{"seal_requests": 6, "dir": "…/quickstart/logs/requests"}
{
  "mode": "backfilled",
  "source_ref": {
    "type": "tau2-simulation",
    "digest_alg": "SHA-256",
    "digest": "f405b2996f6431e316b2bde41233a0b31e14edac4a58434f47911e68bc365185"
  },
  "source_asserted_at": "2025-07-19T16:06:37.787845Z",
  "import_batch": "backfill:2026-10-21T03:46:43Z#1",
  "imported_at": "2026-10-21T03:46:43Z",
  "time_rung": "self_attested"
}
{"checkpoint":34,"indexed_sequence":18}
```

`time_rung` is `self_attested` and stays that way: nothing independent
corroborates a time your own logs state. The book also records when each
record was appended, which is today.

## 3. Pick or define a pack

A Terms Pack is one versioned file, `pack-source.yaml`, that you edit by
hand. It holds checks, each with criteria (the rows a record is judged
against), and each row has a tier:

- `recomputed`: a deterministic check over the record itself. Same input,
  same answer, no model.
- `judged`: a question a pinned judge answers from the conversation.

It also names the judge (model id and sampling parameters) and the report
template the results render through.

| Pack | File | Rows |
|---|---|---|
| Airline support outcomes | `packs/airline-support-outcomes/pack-source.yaml` | nine criteria under three checks, all judged by default |
| EU AI Act obligations | `packs/eu-ai-act-obligations/pack-source.yaml` | ten obligations; two rows recomputed, the rest judged |

```sh
grep -n "tier: recomputed" -B10 packs/eu-ai-act-obligations/pack-source.yaml | grep "label:"
```

```
282-        label: "AI disclosure before the first substantive turn"
369-        label: "Allowed-action rules (compiled)"
```

To define your own, copy a pack and change it. This copy turns one judged
row into a recomputed one. The outcomes pack has a switch that replaces the
judge's answer on "Within fare rules" with a deterministic check of the
cancellation, basic-economy and certificate rules against the tool calls:

```sh
mkdir -p packs/my-airline-pack
sed -e 's/^pack_id: airline-support-outcomes/pack_id: my-airline-pack/' \
    -e 's/within_fare_rules_recomputed: false/within_fare_rules_recomputed: true/' \
    packs/airline-support-outcomes/pack-source.yaml > packs/my-airline-pack/pack-source.yaml
python3 scripts/pack_compile.py validate packs/my-airline-pack/pack-source.yaml
python3 scripts/pack_compile.py compile packs/my-airline-pack/pack-source.yaml --out demo/my-airline-pack
```

```
{
  "valid": true,
  "issues": []
}
{
  "valid": true,
  "pack_id": "my-airline-pack",
  "pack_version": "1.5.0",
  "rubric_version": "3.3",
  "contract": "my-airline-pack/v1",
  "contract_ref": "my-airline-pack@1.5.0",
  "pack_source_digest": "c4df5e73e02f5858d2136aa6549adb4347fee1087720fa69fef25c4aa333333f",
  "clauses": 9,
  "out": "demo/my-airline-pack",
  "files": [
    "demo/my-airline-pack/compiled.json",
    "demo/my-airline-pack/axes.json",
    "demo/my-airline-pack/judge-prompt.md",
    "demo/my-airline-pack/presentation.json"
  ]
}
```

`compiled.json` is the contract the judge runs, `judge-prompt.md` the
judge's instructions, and `presentation.json` the words the report card
uses. The same pack source compiles to the same bytes every time.

## 4. A report with no judge, today

A spec with no judged rows needs no judge call. A `report-spec/v1` file
computes every claim from the sealed records. This one counts
conversations, cancellations and refunds, and checks that every refund
offsets a charge in the same reservation's payment history.

`scripts/report.sh` runs the chain for one spec over one or more days of
the book (by the day records were appended):

1. compute the claims and write an Evidence Result;
2. `capsulectl book result build`: seal the Result into the book;
3. cut a checkpoint and `capsulectl disclose` a bundle rooted at the Result;
4. `capsulectl book report build`: verify the bundle and write the page.

```sh
DAY=$(date -u +%F)
scripts/report.sh --spec scripts/specs/tau2-airline-no-judge.yaml --profile airline \
  --date $DAY --out $QS/no-judge.html --work $QS/run-no-judge --capsulectl $QS/bin/capsulectl \
  > $QS/no-judge.log
grep -A1 "book result build" $QS/no-judge.log | tail -1 | jq -c '{claims, contract_ref, checkpoint}'
grep -A1 "book report build: render" $QS/no-judge.log | tail -1 | jq -c '{card, claims, verdict, verification, page}'
```

```
{"claims":3,"contract_ref":"tau2-airline-no-judge@1","checkpoint":21}
{"card":"outcome","claims":3,"verdict":"VALID","verification":"pass","page":"written"}
```

**What `book result build` checks.** Before sealing, it checks the Result
against the evidence-result-v0 schema, recomputes every headline count from
the claims, and resolves every cited record in the book. Nothing is sealed
when a check fails. It does not re-decide any claim: each verdict is sealed
as the producer stated it.

**What `book report build` checks.** It writes the page only when
`capsulectl verify --bundle` would call the bundle VALID, which includes
each record's signature and the checkpoint's signature. Run that check
yourself on the bundle `report.sh` disclosed. Each run writes into its own
directory under `--work`, and `--work/last-run` points at the newest:

```sh
capsulectl verify --bundle $QS/run-no-judge/last-run/bundle.json | jq -c '{verdict, checkpoint: .checkpoint.status, producer_signatures: .producer_signatures.status, witnesses: .witnesses.status}'
```

```
{"verdict":"VALID","checkpoint":"pass","producer_signatures":"pass","witnesses":"withheld"}
```

`witnesses` is `withheld` because no witness directory was given and this
book sent nothing to a witness.

**Reading the page.** Open `$QS/no-judge.html` in a browser. Nothing is
fetched; the bundle is inside the page, and the page re-checks it before it
shows anything. This run's page opens with:

```
Tau2 airline support -- report from records, no judge -- 2026-10-21: 6 conversations, 6 cancellations, 7 refunds totaling $8101, 43 tool calls
Bundle verification passed
```

Then each claim, its verdict, its tier (`recomputed`) and its grade
(`self-attested`), and three blocks that say who stands behind what:

- **Provenance**: the Result record's id, when it was sealed, and where it
  sits in the log.
- **Receipts**: any transparency-service receipt the bundle carries. Here:
  "self-witnessed: no transparency-service receipt".
- **Checked on this page** and **Not checked on this page**. The page
  checks each record against its capsule id, the required fields, that every
  cited record is present, that no record is missing from the stretch of log
  the file covers, and each disclosed value against its digest. It does not
  check the checkpoint's signature or each record's producer signature, and
  none of its checks says who produced the records or that this file is the
  latest copy. `capsulectl verify --bundle`, above, covers the signatures.

## 5. Judge, from the next UTC day

A judged report closes whole UTC days, and a day can be closed only once it
has ended. Records you put in the book today are judged from 00:00 UTC
tomorrow. Run this section then, from the directory that holds
`quickstart/`.

`report.sh` runs the same chain as in step 4, with a judge in front:
`scripts/run_daily.py` judges every conversation the book took in that day,
seals one `evaluation-report/v1` record per criterion and seals the day's
Close; `scripts/rollup_day.py` rolls the day up into the Evidence Result.

**The judge pin.** Before judging, `run_daily.py` computes a pin with
`capsulectl judge pin`: a digest over the judge's model id, the compiled
judge prompt and axes, the sampling parameters, the pack source's own
digest, the instruction template the judge sends, and `min_confidence` when
set. Every judgment is sealed under it, and the rollup counts only
judgments made under the pin of the pack you pass. Change any field in
`pack-source.yaml` and the pin moves, so earlier judgments stop counting
until you judge again. The pin names the model by its id; it does not show
that the model behind that id is unchanged.

**The judge.** The packs use Jev (`jevals` on PyPI), pinned to
`jev-1.13.0`. A live call needs your key in `TYPESAFE_API_KEY` and
`--judge-backend live`. Without a key, `--judge-backend mock` runs the same
chain with placeholder verdicts, and the sealed reports and the page then
name the model as "(mock backend, no model read the conversation)".
Recomputed rows are real either way. This page's run judged live.

```sh
# the next UTC day, from the directory that holds quickstart/
cd quickstart && export QS=$PWD PATH=$PWD/bin:$PATH && . venv/bin/activate && cd evidencebook-skills
# export TYPESAFE_API_KEY=...    your Jev key
DAY=$(capsulectl cll list --profile airline --limit 1000 | jq -r '[.entries[].appended_at[:10]] | min')
scripts/report.sh --spec demo/airline-support-outcomes/compiled.json --profile airline \
  --date $DAY --out $QS/outcomes.html --work $QS/run-outcomes --capsulectl $QS/bin/capsulectl \
  --judge-backend live > $QS/outcomes.log
jq -c '{cases, reports: (.reports | length), verdicts, judge_pin_digest}' $QS/run-outcomes/last-run/runs/day-$DAY/run.json
jq -r '.claims[] | select(.requirement_ref == "policy_compliance.within_fare_rules") | "\(.id)  \(.tier)  \(.verdict)"' \
  $QS/run-outcomes/last-run/rollup/result-v0-$DAY.json
grep -A1 "book report build: render" $QS/outcomes.log | tail -1 | jq -c '{card, claims, verdict, verification, page}'
```

What live verdicts look like, as a **pre-recorded sample, not from this
page's run**: a live hosted Jev run on 2026-10-17 judged the same
conversation (task 1, trial 0, claude-3-7-sonnet agent) against an earlier
compile of the outcomes pack. Each answer is a verdict and the judge's
confidence:

```
policy_compliance.confirmed_before_acting              met  0.97
policy_compliance.within_fare_rules                    met  0.56
policy_compliance.no_unrequested_actions               met  0.83
task_resolution.right_reservation                      met  0.93
task_resolution.right_change                           met  0.60
task_resolution.done_in_full                           met  0.52
grounded_communication.prices_from_system              met  0.85
grounded_communication.refunds_match_payment_records   met  0.91
grounded_communication.no_invented_policy              met  0.51
```

In that conversation the agent cancelled a reservation about 29 hours after
it was booked, outside the 24-hour window, and the judge took the agent's
word for it. That is what the switch in step 3 is for. Your pack, with
"Within fare rules" recomputed:

```sh
scripts/report.sh --spec demo/my-airline-pack/compiled.json --profile airline \
  --date $DAY --out $QS/my-pack.html --work $QS/run-my-pack --capsulectl $QS/bin/capsulectl \
  --judge-backend live > $QS/my-pack.log
jq -r '.claims[] | select(.requirement_ref == "policy_compliance.within_fare_rules") | "\(.id)  \(.tier)  \(.verdict)"' \
  $QS/run-my-pack/last-run/rollup/result-v0-$DAY.json
```

And the EU AI Act pack. `--attach-input-originals` puts each conversation's
full transcript in the bundle so the page can show it. It is off by default
because it discloses the conversations themselves, not only their digests:

```sh
scripts/report.sh --spec demo/eu-ai-act-obligations/compiled.json --profile airline \
  --date $DAY --out $QS/eu.html --work $QS/run-eu --capsulectl $QS/bin/capsulectl \
  --judge-backend live --attach-input-originals \
  --title "EU AI Act obligations: airline support agent" > $QS/eu.log
grep -A1 "book report build: render" $QS/eu.log | tail -1 | jq -c '{card, claims, verdict, verification, page}'
```

### Adjudication on or off

There is no single on/off flag. What gets adjudicated follows from the spec
you pass and the tier of each row:

- **On.** A compiled pack with judged rows: `report.sh` sends each judged
  row to the pinned judge, the one the pack names, through `--judge-cmd`
  (default `scripts/judges/jev_judge.py`) with `--judge-backend live`. To
  use your own judge, pass your command as `--judge-cmd`; the pin then
  covers the instruction template that command reports.
- **Off for a whole report.** Pass a `report-spec/v1` file instead of a
  compiled pack, as in step 4. `report.sh` picks the no-judge path from the
  spec's own content.
- **Off for one row.** Give it `tier: recomputed`, or turn on its
  `tier_switch` flag as in step 3. The compiler accepts that only for a row
  that has a deterministic check. A pack has no setting that skips a judged
  row and keeps it in the report.

`--judge-backend mock` does not turn adjudication off: the judged rows are
still sealed, with placeholder verdicts. To see which rows of a compiled
pack go to the judge, read each row's effective tier the way
`run_daily.py` does:

```sh
python3 -c 'import json, sys; sys.path.insert(0, "scripts"); import run_daily as rd; spec = json.load(open(sys.argv[1])); sw = spec.get("switches") or {}; [print("%-10s %s" % (rd.effective_tier(c, sw), c["id"])) for c in spec["clauses"]]' demo/my-airline-pack/compiled.json
```

**Reading a judged card.** `$QS/outcomes.html` reads at two levels:

- **The summary**: the pack and version, the period (each backfilled
  conversation is dated by its own "source says" time, which the card marks
  as self-attested), and the counts: conversations resolved, missed, and
  criterion judgments that did not apply. The page recomputes every count
  from the claims and the records they cite.
- **The detail**: open a count to see its conversations. Under "Why
  conversations missed", each criterion lists the conversations that missed
  it.

Below that, three blocks say who stands behind the numbers:

- **The judge** ("What ran"): the contract and version, the judge model id,
  the judge pin digest, and the prompt and axes digests.
- **The witness** ("Receipts"): here, "self-witnessed: no
  transparency-service receipt".
- **The verification** ("Checked on this page" and "Not checked on this
  page"), as in step 4.

The EU AI Act page uses the obligation card, which the pack selects. By
the pack's own rule it reports no resolved roll-up and no overall
compliance percentage: each test is a count of sessions met, not met or not
evaluable.

**Changing the words.** The words on a card come from the pack: check
questions, criterion labels and text, obligation titles. Edit them in
`pack-source.yaml` and compile again; no code changes. The compiled
`presentation.json` is added to the bundle after it is disclosed, but its
digest is not: `report.sh` pins it inside the Result before sealing
(`x-presentation-digest`), so the producer's signature covers the wording,
and a block changed afterwards reads as unsigned producer text. The words
are still the producer's, not evidence: every verdict and count comes from
the signed claims.
Changing any field moves the judge pin (above), so judge again after a
wording change. `--title` sets the page title. In `v0.1.0-rc18` the two
result cards are built in; wording packs (`aac.wording-pack/v0`) apply to
presentation modules a plugin installs, not to these cards.

## 6. Go live

Backfilling is for logs you already have. Going forward, record as you go:

- **Conversations.** When a conversation ends, publish its case record
  then: the same record, without the `backfilled` block, stamped with the
  time it ended.

  ```sh
  jq --arg now "$(date -u +%FT%TZ)" 'del(.provenance_mode) | .capsule.Timestamp = $now' \
    $QS/logs/requests/task-0.json > $QS/live-task-0.json
  capsulectl publish --profile airline --request $QS/live-task-0.json | jq -c '{capsule_id}'
  ```

  ```
  {"capsule_id":"1dfc7cd0d8e7e6772e6f4254271c6fdb64d7c800b80c8151bd2ad3985d9d6553"}
  ```

- **Tool calls.** Run `capsulectl book backfill run` from cron (or your
  host's scheduler) over the rows since the last pass, at a period well
  inside how long your host keeps them. `capsulectl book backfill status`
  prints where the next pass starts. A missed pass shows up as `late` or as
  a gap, not as silence.
- **Judging.** Run `report.sh` each day for the day that just ended.

To seal each tool call inside the agent's own process instead, use
[capsule-emit](https://github.com/action-state-group/capsule-emit): one
`seal()` per consequential action, or an adapter that wraps your
framework's tool calls (MCP, LangChain, CrewAI, Google ADK, OpenAI Agents
SDK and others). It keeps its own ledger file and sends signed checkpoints,
never content, to the witness you name in `CAPSULE_WITNESS_URL`. Here that
is a local stand-in that records what it is sent and countersigns nothing,
so nothing reaches a public witness:

```sh
python3 demo/quickstart/catcher.py --port 8765 --log $QS/caught.jsonl &
CATCHER=$!
pip install -q capsule-emit==0.12.0
export CAPSULE_WITNESS_URL=http://127.0.0.1:8765
```

```python
from capsule_emit import seal, push

cap = seal(
    {"reservation_id": "EHGLP3", "refund": "-327.00"},
    action="cancel_reservation",
    operator="tau2-demo",
    developer="airline-agent@v1",
    verdict="executed",
    effect={"type": "cancel_reservation", "status": "confirmed"},
    agent_output={"status": "cancelled"},
)
print(cap.capsule_id, cap.witness_outcome)
checkpoint = push()
print(checkpoint.mmr_size, checkpoint.witnesses)
```

```
e0416a0bd641ee6daca4475b995ed0a750237f18955a47019c582bf6a1da1ef6 checkpoint_queued
1 []
```

capsule-emit also prints, before its first network attempt, exactly what
it will send and where, and warns that this registration did not complete
(the stand-in answers 503).

```sh
kill $CATCHER
cat $QS/caught.jsonl
```

```
{"method": "POST", "path": "/checkpoints", "bytes": 421}
```

An empty `witnesses` list means the stand-in received the checkpoint and
nothing countersigned it. Name a real witness and the same checkpoint goes
to it for countersigning; this page's run sent nothing to one. This page
does not cover reading a capsule-emit ledger into the reports above; they
read the book.

## Where to go next

- The README's "Report from records" section: every `report.sh` flag, day
  ranges, and merging days into one Result.
- `scripts/report_spec.py`: the full `report-spec/v1` shape.
- `scripts/pack_compile.py` and the comments in the two pack files: every
  `pack-source.yaml` field.
- capsule-cli's `docs/BACKFILL.md`: the backfill format, tiers and gaps, and
  what an import record can and cannot show.
