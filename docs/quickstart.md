# Terms Packs quick start

You have months of agent logs. This page turns them into an evidence book,
defines a Terms Pack, and gives you a report page anyone can
open offline. Every step here is offline and free: no judge is called, so no
API key is needed. For a judged report (a pinned judge, Jev, run live), use
[Zero to a verified outcome report](OUTCOME-REPORT-QUICKSTART.md).

The example is the public tau2-bench airline set: customer-support
conversations between an agent and a simulated customer, with every tool
call the agent made. The two packs are **Airline support outcomes** (did the
agent resolve the request, within policy) and **EU AI Act obligations** (ten
obligations a single conversation can show).

1. [Install](#1-install)
2. [Logs into a book](#2-logs-into-a-book)
3. [Pick or define a pack](#3-pick-or-define-a-pack)
4. [A report with no judge](#4-a-report-with-no-judge)

Dates in the sample outputs come from the run that produced them; yours will differ.
Every command on this page was run top to bottom on macOS (arm64) against
capsulectl and its book plugin `v0.1.0-rc31` (GitHub releases, checksums
verified) and the `main` of this repository at the commit this page landed on.

## 1. Install

You need `gh` (logged in to GitHub), `jq`, `git`, and `python3` with `venv`.
`shasum` comes with macOS; on Linux use `sha256sum -c` where `shasum -a 256 -c`
is shown below. Work in a directory whose path has no spaces. `QS` names it
for the rest of the page.

Download capsulectl and its book plugin (platform `darwin-arm64`, `linux-amd64`
or `linux-arm64`) and check each against its release's `SHA256SUMS`. Do this
first, in your normal shell, because the next step moves `HOME` and `gh` would
lose your login:

```sh
umask 022 && mkdir quickstart && cd quickstart && mkdir bin book-dl
V=v0.1.0-rc31; P=darwin-arm64
gh release download $V --repo action-state-group/capsule-cli -p "capsulectl-$V-$P" -p SHA256SUMS
grep "capsulectl-$V-$P" SHA256SUMS | shasum -a 256 -c
gh release download capsulectl/$V --repo action-state-group/evidencebook -p "capsulectl-book-$V-$P" -p SHA256SUMS -D book-dl
(cd book-dl && grep "capsulectl-book-$V-$P" SHA256SUMS | shasum -a 256 -c)
```

capsulectl keeps its profiles under `$XDG_CONFIG_HOME/capsule` (by default
`~/.config/capsule`) and its plugins under `$HOME/.local/lib/capsulectl`,
and has no flag that moves either. So `env.sh` points `HOME`, `TMPDIR` and
the XDG directories inside `QS`. Every file this page writes, pip's cache
and temporary files included, then lands in `quickstart/`. The exports hold
only in this shell: stay in this terminal for the rest of the page, because
the next block uses `V`, `P` and the current directory. Close it when you are done. capsulectl refuses to install a plugin on a path another
user could change, so make `quickstart/` somewhere only you can write to, such
as your home directory.

```sh
cat > env.sh <<ENV
umask 022
export QS=$PWD
export HOME=\$QS/home TMPDIR=\$QS/tmp XDG_CONFIG_HOME=\$QS/home/.config XDG_DATA_HOME=\$QS/home/.local/share XDG_CACHE_HOME=\$QS/home/.cache
export PATH=\$QS/bin:\$PATH
ENV
. ./env.sh && mkdir -p $TMPDIR $XDG_CONFIG_HOME $XDG_DATA_HOME $XDG_CACHE_HOME
install -m 755 capsulectl-$V-$P bin/capsulectl
install -m 755 book-dl/capsulectl-book-$V-$P bin/capsulectl-book
capsulectl --version
capsulectl plugin install bin/capsulectl-book | jq -r .version_check
```

```
capsulectl v0.1.0-rc31 (commit e736e45db4e035b31f6b449307baf88a82b869c9)
matches capsulectl v0.1.0-rc31
```

Get the packs and scripts, and a Python environment with the packages they use:

```sh
git clone -q https://github.com/action-state-group/evidencebook-skills.git
python3 -m venv venv && . venv/bin/activate
pip install -q pyyaml rfc8785
```

Make a book. A book is an append-only log on your disk. Its records are
signed with a key you hold, and its checkpoints with a second key. The
profile stores the key paths as given, so give them in full:

```sh
capsulectl key generate --output $QS/producer.seed > $QS/producer.json
capsulectl key generate --output $QS/checkpoint.seed > $QS/checkpoint.json
capsulectl profile create --name airline --type jsonl --jsonl-path $QS/store \
  --namespace tau2 --log-id airline-support --log book --operator tau2-demo \
  --signing-key-file $QS/producer.seed --trusted-key "$(jq -r .public_key $QS/producer.json)" \
  --checkpoint-signing-key-file $QS/checkpoint.seed \
  --checkpoint-trusted-key "$(jq -r .public_key $QS/checkpoint.json)" > /dev/null
capsulectl store init --profile airline
```

```
{"log_id":"airline-support","spec_version":"capsule-cli-result/v1","status":"initialized","voice":"silent"}
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
{"kind":"row","source":"tau2.airline.claude-3-7-sonnet-20250219","cursor":0,"id":"toolu_01HwogveKQVZBrHv53sg37Wr","at":"2025-07-01T16:06:01.095106Z","record_kind":"tool_call","task":"tau2:airline:task-0:trial-0","tool_call_id":"toolu_01HwogveKQVZBrHv53sg37Wr","tool":"get_reservation_details","status":"ok","raw_digest":"d4bd8360…"}
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
    "digest": "ccf596662bd99f61452229acb7691134e7f43bb937ed77f4d6d06b91a2faac9a"
  },
  "source_asserted_at": "2025-07-19T16:06:37.787845Z",
  "import_batch": "backfill:2026-10-22T03:09:27Z#1",
  "imported_at": "2026-10-22T03:09:27Z",
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
373-        card_label: "Allowed-action rules (compiled): eligibility checked; reason not checked"
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
  "pack_version": "1.6.0",
  "rubric_version": "3.3",
  "contract": "my-airline-pack/v1",
  "contract_ref": "my-airline-pack@1.6.0",
  "pack_source_digest": "f7c081f14c13b64db135cee8788909a87566e2c5b1d23d0947a8f366833025c5",
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

## 4. A report with no judge

This report runs a judge-free report spec, not the pack from section 3: a
pack's judged rows need a judge. For a report from the pack, see
[Zero to a verified outcome report](OUTCOME-REPORT-QUICKSTART.md).

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
grep -A1 "book result build" $QS/no-judge.log | tail -1 | jq -c '{claims, contract_ref}'
grep -A1 "book report build: render" $QS/no-judge.log | tail -1 | jq -c '{card, claims, verdict, verification, page}'
```

```
{"claims":3,"contract_ref":"tau2-airline-no-judge@1"}
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
Tau2 airline support -- report from records, no judge -- 2026-10-22: 6 conversations, 6 cancellations, 7 refunds totaling $8101, 43 tool calls
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

## Where to go next

- A report whose rows a pinned judge answers: [Zero to a verified outcome report](OUTCOME-REPORT-QUICKSTART.md).
