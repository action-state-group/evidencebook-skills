# A report over a holder's records, asked for by a pack's digest

An auditor wants to know whether the tool-call log of someone else's Goose agent reached that agent's book without a gap. The holder will not hand over its book, and the auditor will not take the holder's word for a verdict. So the auditor writes down the terms (a Terms Pack), names them by their SHA-256, and asks for the three fields the terms read. The holder answers with only those fields, proven to be in its log at a signed checkpoint. The auditor runs the terms over the answer, signs the Result, and builds one bundle that a machine verifies and a person reads as a page.

Every command below runs offline against the released `capsulectl` and its book plugin, `v0.1.0-rc50`. No judge and no model is called, so no key is needed. Nothing is built from source.

1. [Install](#1-install)
2. [The holder's book](#2-the-holders-book)
3. [The auditor asks, by digest](#3-the-auditor-asks-by-digest)
4. [Run the terms and build the report](#4-run-the-terms-and-build-the-report)
5. [What the report shows, and what it does not](#5-what-the-report-shows-and-what-it-does-not)

## What you will see

Two import passes of the agent host's tool-call log: five calls with nothing missing, then two later calls after the host's log had already dropped two cursors, so the second pass declares a gap. The report has three terms: the log was imported (met), no gap declared (not met), no late or refused row (met). The page is built from the same bundle `capsulectl verify --bundle` checks.

The rows here are a hand-written sample, not read from a Goose host: `fixtures/pass1.jsonl` and `fixtures/pass2.jsonl` are `backfill-source-record/v0` lines in the shape a Goose reader would write from the host's own tool-call table. capsulectl has no code for any particular host; a reader for your host writes the same lines from its own store (see `docs/quickstart.md`, "Logs into a book").

## 1. Install

You need `gh` (logged in to GitHub), `jq`, `git` and `python3`. `shasum` comes with macOS; on Linux use `sha256sum -c` where `shasum -a 256 -c` is shown. Work in a directory whose path has no spaces. `QS` names it for the rest of the page.

Download capsulectl and its book plugin (platform `darwin-arm64`, `linux-amd64` or `linux-arm64`) and check each against its release's `SHA256SUMS`. Do this first, in your normal shell, because the next step moves `HOME` and `gh` would lose your login:

```sh
umask 022 && mkdir terms-pack-report-run && cd terms-pack-report-run && mkdir bin book-dl
V=v0.1.0-rc50; P=darwin-arm64
gh release download $V --repo action-state-group/capsule-cli -p "capsulectl-$V-$P" -p SHA256SUMS
grep "capsulectl-$V-$P" SHA256SUMS | shasum -a 256 -c
gh release download capsulectl/$V --repo action-state-group/evidencebook -p "capsulectl-book-$V-$P" -p SHA256SUMS -D book-dl
(cd book-dl && grep "capsulectl-book-$V-$P" SHA256SUMS | shasum -a 256 -c)
```

capsulectl keeps its profiles under `$XDG_CONFIG_HOME/capsule` and its plugins under `$HOME/.local/lib/capsulectl`, and has no flag that moves either. `env.sh` points `HOME` and the XDG directories inside `QS`, so everything this page writes lands there. The exports hold only in this shell: stay in this terminal for the rest of the page. capsulectl refuses to install a plugin on a path another user could change, so make the directory somewhere only you can write to, such as your home directory.

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

**Expect:** a `capsulectl v0.1.0-rc50` line, then `matches capsulectl v0.1.0-rc50`.

Get this repository, for the pack, the fixtures, the evaluator and the page wording:

```sh
git clone -q https://github.com/action-state-group/evidencebook-skills.git
T=$QS/evidencebook-skills/demo/terms-pack-report
```

## 2. The holder's book

The holder is the party whose agent ran. It has its own book (an append-only log on its disk, signed with a key it holds, checkpointed with a second key). One profile is enough for each party here; the auditor's comes in step 3.

```sh
for n in holder auditor; do
  capsulectl key generate --output $QS/$n.seed > $QS/$n.json
  capsulectl key generate --output $QS/$n.cseed > $QS/$n.cjson
  capsulectl profile create --name $n --type jsonl --jsonl-path $QS/$n-store \
    --namespace goose --log-id $n-log --log book --operator $n-op \
    --signing-key-file $QS/$n.seed --trusted-key "$(jq -r .public_key $QS/$n.json)" \
    --checkpoint-signing-key-file $QS/$n.cseed \
    --checkpoint-trusted-key "$(jq -r .public_key $QS/$n.cjson)" > /dev/null
  capsulectl store init --profile $n > /dev/null
done
mkdir packs
```

`mkdir packs` only silences a warning: capsulectl-book looks for a workspace `packs` directory.

The holder imports the host's log. The first pass has nothing missing:

```sh
capsulectl book backfill run --profile holder --source $T/fixtures/pass1.jsonl | jq -r .summary
```

**Expect:** `Digested 5 new host records (Tier A) and retained 0 as backfilled Capsules ...; 0 refused, 0 anomalies, 0 gaps declared.`

The second pass reads two later calls, but the host's log no longer held cursors 6 and 7. The pass says so and exits 3: that is the importer reporting a gap, not a failure, and the pass is still recorded.

```sh
capsulectl book backfill run --profile holder --source $T/fixtures/pass2.jsonl | jq -c '{rows_read, gaps}'
echo "exit ${pipestatus[1]:-${PIPESTATUS[0]}}"
```

**Expect:** `"rows_read":2` and one gap from cursor 6 to 7; `exit 3`, with a line on stderr saying the verification is incomplete (the `echo` line works in zsh and bash).

Each pass sealed one `backfill_import` record whose statement names its gaps, late rows and refused rows. Cut a checkpoint over them, so a requester can ask for a state the holder has signed:

```sh
capsulectl book cll checkpoint create --profile holder | jq -c '{checkpoint, log_id}'
```

Now the holder opts the pack in. The file names the pack, who may be answered it, the form of the question, and the only fields an answer reveals of each record: here a record's type and the three lists the terms read, never the rest of the statement.

```sh
mkdir -p $QS/holder-store/book/derivations
jq -n --slurpfile p $T/pack.json \
  '{document: $p[0], recipients: ["auditor"], forms: ["full_history"], fields: $p[0].fields}' \
  > $QS/holder-store/book/derivations/goose-record-keeping.json
capsulectl book doctor --profile holder | jq -r '.findings[] | select(.check == "terms_packs_served") | .detail'
```

**Expect:** `6f9866750bae33a8cb02a834cd63d0ad61c5e053a5865545e021f1335f5ef382 (forms full_history, 1 granted)`. That digest is the pack's. A pack not listed here is refused `derivation_unsupported`, whatever digest a requester names.

## 3. The auditor asks, by digest

The auditor does not need the holder's file. It has the pack (`pack.json`, public) and names its digest, the SHA-256 of the pack's canonical JSON. `pack.json` is ASCII and holds no number, so `jq -cS` produces exactly the canonical bytes:

```sh
D=$(jq -cS . $T/pack.json | tr -d '\n' | shasum -a 256 | cut -d' ' -f1); echo $D
```

**Expect:** the same digest the holder's `doctor` listed. If you change one character of `pack.json` the digest changes, and the holder's answer is refused.

The question is the holder's full history, derived by that pack, from a checkpoint over at least one record (`min_freshness` is a log size here; the holder picks the anchor):

```sh
echo "{\"subject\":{\"full_history\":null},\"coverage\":{\"min_freshness\":1},\"derivation\":\"$D\"}" > $QS/ask.json
capsulectl book request --profile auditor --request $QS/ask.json --responder holder --output $QS/ask.sent > $QS/ask.out
Q=$(jq -r .record_id $QS/ask.out); echo $Q
```

The holder answers the request. `--requester auditor` is the identity the holder's transport has authenticated (a pipe here; a relay or an HTTP binding in practice), never a name the requester declared:

```sh
capsulectl book respond --profile holder --request $QS/ask.sent --requester auditor --output $QS/answer.json | jq -c '{outcome, reason}'
```

**Expect:** `{"outcome":"artifact","reason":null}`. A requester the holder did not name gets `{"outcome":"refusal","reason":"policy_declined"}`: try `--requester stranger`.

The auditor records the answer, checking the holder's signatures under the two keys it pinned:

```sh
capsulectl book request --profile auditor --for $Q --response $QS/answer.json \
  --responder-key "$(jq -r .public_key $QS/holder.json)" \
  --responder-checkpoint-key "$(jq -r .public_key $QS/holder.cjson)" > $QS/recorded.out
R=$(jq -r .record_id $QS/recorded.out); echo $R
capsulectl book result derived-inputs --profile auditor --response $R > $QS/inputs.json
jq -c '{proven, rows: (.records | length)}' $QS/inputs.json
jq -c '.records[] | .fields' $QS/inputs.json
```

**Expect:** `"proven":true`, four rows (two import passes and two index records the log keeps), and for each import pass the `statement` with `anomalies`, `gaps` and `refused`. The second pass shows its gap. `proven` means each row's digest was checked in the holder's log at a signed checkpoint. The values on a row are the holder's word.

## 4. Run the terms and build the report

`evaluator.py` runs the pack's three terms over those rows and writes an Evidence Result whose every claim cites exactly the holder's response record (`$R`). It refuses a pack whose digest is not the one the holder answered under, and a row or field it cannot read counts as "couldn't tell", never as not met. It uses the standard library and this repository's `scripts/result_v0.py`; it calls no model.

```sh
python3 $T/evaluator.py --pack $T/pack.json --inputs $QS/inputs.json > $QS/result.json
jq -c '.aggregate.buckets' $QS/result.json
```

**Expect:** `met` holds `record_keeping.passes_present` and `record_keeping.no_late_or_refused_rows`, `not_met` holds `record_keeping.no_declared_gaps`.

`book report derive` seals the Result in the auditor's own book, signed by the auditor's key. It checks that you name the pack the holder answered, that the Result is valid and that every claim cites the response, and writes the bundle:

```sh
capsulectl book report derive --profile auditor --response $R --pack $D --result $QS/result.json --out $QS/bundle.json | jq -c '{result_record_id, proven}'
capsulectl verify --bundle $QS/bundle.json | jq -c '{verdict}'
```

**Expect:** `"proven":true`, then `{"verdict":"VALID"}`. The bundle carries the `contract-report/v1` view, which is what the page is drawn from.

The page is built from that same file. `--wording` lays this example's words over the page (its digest is beside the file):

```sh
capsulectl book report build --bundle $QS/bundle.json --card obligation \
  --wording $T/../../wording/goose-record-keeping-en.json \
  --wording-digest "$(cat $T/../../wording/goose-record-keeping-en.sha256)" \
  --out $QS/report.html | jq -c '{verdict, claims, unsupported_claims, page}'
open $QS/report.html
```

**Expect:** `"verdict":"VALID"`, `"claims":3`, `"unsupported_claims":0`, `"page":"written"`. The page opens offline: 2 met, 1 not met, 0 couldn't tell, and each row opens to the claim and the records it cites. Its "Check this report yourself" section names the producer key and the checkpoint the bundle holds.

Run `book report derive` again with the same Result and a new `--out` and it returns the same `result_record_id`: the Result is sealed once.

## 5. What the report shows, and what it does not

It shows what the holder's book holds about the host's log: the passes it imported, the gaps, late rows and refused rows each pass declared, and, from the holder's own signed answer, that each row is in the holder's log at a checkpoint the holder signed.

It does not show:

- that the field values are true. They are the holder's word; only each row's presence in the log is proven.
- that no row was left out of the answer. A holder that wants a term met could answer with fewer rows, and no proof here shows the answer is complete.
- anything the host did not write down, or anything the agent did that the importer never read. The book detects an absence or a late record; it does not prevent one.
- that the agent complied with any rule, law or policy. The three terms are about the log, not about what the agent did.
- who the holder is. The report names keys; a key is not a person.

The Result is signed by the auditor, not the holder. The holder signed its answer, and the Result cites that answer as its only evidence.
