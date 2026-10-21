# Evaluation-compiler demos

Two reproductions of the same compiler workflow. In both, the evaluation source
is a **CLL** (Capsule Ledger Log) read through the Capsule CLI; the compiler turns
a scenario + value proposition into an evaluation-skill bundle, and the bundle's
host agent selects, verifies, extracts (three isolated contexts), judges, and
publishes a new evaluation Capsule.

- **Demo A – Investigation**: the CLL already exists (production investigations).
- **Demo B – tau2**: a plain dataset, so its interactions are first **backfilled**
  into a local **SQLite** CLL, then evaluated exactly like Demo A.

## Prerequisites

```sh
# Capsule CLI (MySQL + SQLite backends). Installs the `capsulectl` binary; the
# older builds installed it as `capsule`, which collided with the Python
# capsule-emit CLI on PATH.
CAPSULE_CLI=~/GitHub/capsule-cli   # cloned capsule-cli repo
git -C "$CAPSULE_CLI" pull && (cd "$CAPSULE_CLI" && go install ./cmd/capsulectl)
# remove any stale `capsule` from a previous install so it no longer shadows capsulectl
BIN="$(go env GOBIN)"; GOPATH="$(go env GOPATH)"; rm -f "${BIN:-${GOPATH%%:*}/bin}/capsule"
capsulectl --version    # capsulectl version 0.1.0-dev
```

- Demo A: the `investigations` MySQL profile configured, and `gh` authenticated for
  `tracker.example.com` (independent business evidence).
- Demo B: no database server — SQLite is a single local file. tau2 dataset at
  `~/GitHub/tau2-bench/data/tau2/domains/…` and the shipped benchmark runs at
  `~/GitHub/tau2-bench/data/tau2/results/final/…` (plain-tracked JSON; the airline
  results file used here is ~10 MB and its `domains/airline/` scenarios are needed
  by the judge, so a full clone is simplest, not a sparse `domains/` one).

---

## Demo A — Investigation (existing CLL)

Value proposition: *"Under limited evidence, reduce ticket uncertainty and guide
the handler to the correct next step faster and more safely."* Evaluation unit:
one investigation trigger/run. `target_mode=evidence_derived`, `aggregation=none`.

1. **Compile the bundle.** Invoke the `evaluation-compiler` skill with the scenario
   above and the access facts (profile `investigations`). It writes the bundle to
   `~/.local/share/evaluation-bundles/investigation/`
   (`SKILL.md`, `axes.json`, `resolved-spec.json`, `references/{source,execution,capsule-cli}.md`).
   `capsulectl` is a host prerequisite on `PATH`, not part of the bundle.

2. **Run the generated skill** in a fresh agent, passing only runtime inputs:
   `profile=investigations`, `selection=(164,165]`, `run_dir=<private dir outside the bundle>`.
   The skill performs, using `capsulectl` and `gh`:

   ```sh
   capsulectl cll list --profile investigations --after 164 --through 165 --limit 1000
   ID=$(capsulectl cll list --profile investigations --after 164 --through 165 --limit 1000 | python3 -c 'import sys,json;print(json.load(sys.stdin)["entries"][-1]["capsule_id"])')
   capsulectl get    --profile investigations --capsule-id "$ID" --raw --output rec.json
   capsulectl verify --profile investigations --capsule rec.json      # identity/signature/bindings
   gh api --hostname tracker.example.com /repos/example-org/tracker/issues/82049
   gh api --hostname tracker.example.com /repos/example-org/tracker/issues/82049/comments
   # three isolated sub-agents: desired outcome, agent outcome, judge
   capsulectl publish --profile investigations --request seal-request.json
   # read back the new evaluation Capsule: capsulectl get + verify + cll list
   ```

   Bindings: `effect_request → effect.request_digest`, `effect_response →
   effect.response_digest`; the `payload` artifact is **unbound** and is not
   authenticated evidence. Verification uses the `--raw` record (readable JSON
   re-encodes request bytes).

**Actual result of the validated run** (`run-20260909T070002Z`): source capsule
`9c4a2524…` at CLL **sequence 165** (tracker #82049); new evaluation Capsule
`cbcb24e9…` at CLL **sequence 169**, payload verified identical; judgments
`uncertainty_reduction=pass`, `next_step_correctness=fail`, `safety_calibration=pass`,
`aggregate=null`.

---

## Demo B — tau2 (backfill a local SQLite CLL, then evaluate)

tau2 supplies the dataset (customer-service task scenarios and gold criteria) and
its own recorded benchmark runs under `data/tau2/results/final/`. Axes are the
compiler's job. Value proposition used here: **customer experience** — *"give the
customer a clear, empathetic service experience that fully resolves their request
in one interaction with minimal effort."*

This demo uses the tau2 **airline** domain. Logical pipeline: **compile → backfill →
run → aggregate**. The compile (B3) reads the *dataset* and needs no CLL, so it is
independent of the backfill; B1–B2 create the CLL and load the interactions that the
**run** (B3) then reads; B4 aggregates. The sections below list CLL setup (B1–B2)
first only because the run needs it — you may compile before or after backfilling. B1
and B2 are verified/reproducible against the shipped airline results; the B3/B4
compiler runs are presenter-driven (log `tau2-airline-20260910`).

### B1. Create a local SQLite CLL

```sh
umask 077   # new key/config files are created owner-only, no world-readable window
DEMO=~/.local/share/evaluation-runs/tau2-airline-eval
# re-runnable clean slate (store init / profile create are not idempotent):
# delete the old airline SQLite CLL and the airlinedemo profile first
rm -f "$DEMO"/store.db*                                             # the old SQLite CLL (+ WAL/SHM)
rm -rf "$DEMO"                                                      # keys/, backfill/, any prior run
rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/capsule/profiles/airlinedemo.yaml"
mkdir -p "$DEMO/keys"
# generate the producer signing key (CLI writes the seed file 0600; prints the public key)
PUB=$(capsulectl key generate --output "$DEMO/keys/airline.ed25519" \
      | python3 -c 'import sys,json;print(json.load(sys.stdin)["public_key"])')

capsulectl profile create --name airlinedemo --type sqlite \
  --sqlite-path "$DEMO/store.db" \
  --namespace tau2 --log-id tau2-airline-20260910 \
  --signing-key-file "$DEMO/keys/airline.ed25519" --trusted-key "$PUB"
capsulectl store init --profile airlinedemo   # generates + pins store_id into the profile

# inspect what the profile stored (safe to print: identity, backend, key-file PATHS)
cat "${XDG_CONFIG_HOME:-$HOME/.config}/capsule/profiles/airlinedemo.yaml"
# name/type/log_id/namespace, connection.database (the store.db path),
# signing.file (path to the 0600 seed — NOT the secret itself),
# trusted_keys (producer public key), checkpoint.* (added later in C1/C2)
```

The SQLite store keeps the artifact tables and the CLL log in one file
(`store.db`), opened with `foreign_keys`, `busy_timeout`, and WAL. The profile holds
only identity, the store path, and key-file **paths** plus trusted **public** keys —
the ed25519 seed stays in its own `0600` file, never in the profile.

### B2. Backfill tau2 interactions as Capsules

Backfill reads **only shipped tau2 results**: no agent run, no user simulator,
**no model/LLM API key**, and nothing synthesized. tau2-bench is a runnable
benchmark and ships its recorded runs under `data/tau2/results/final/*.json`;
each file holds `simulations[]` for every `(task_id, trial)`, with the real agent
+ user-simulator transcript. `demo/backfill/backfill.py` takes just the
results file and an output dir, and writes one `capsule-seal-request/v1` per task
(its trial-0 run) as `task-<id>.json`. The bound `payload` carries the real
`agent_interaction` (transcript + tool calls, with each call's `requestor`
attribution), a `case` block, and `provenance`. Domain is read from the results
file; the Capsule's operator/developer are fixed backfill-provenance labels.

```sh
TAU2=~/GitHub/tau2-bench            # cloned tau2-bench repo
EC=~/GitHub/evaluation-compiler     # this repo
RES="$TAU2/data/tau2/results/final/claude-3-7-sonnet-20250219_airline_default_gpt-4.1-2025-04-14_4trials.json"
python3 "$EC/demo/backfill/backfill.py" --results "$RES" --out "$DEMO/backfill"
# publish every backfilled interaction (one per task) as one CLL entry
for f in "$DEMO"/backfill/*.json; do capsulectl publish --profile airlinedemo --request "$f" >/dev/null; done
capsulectl cll list --profile airlinedemo --after 0 --limit 1000 \
  | python3 -c 'import sys,json;print("CLL entries:",len(json.load(sys.stdin)["entries"]))'
```

The airline file backfills **50 tasks** → 50 CLL entries. Capsule IDs are
content-addressed (JCS over the metadata and payload digest), so they do **not**
depend on the signing key: **seq 1** = `56b1f95f…` (task 0), **seq 2** =
`ec5b0c62…` (task 1, a 26-message conversation). CLL sequence follows the publish
order — the shell glob over `task-*.json`, which is lexical (`task-0`, `task-1`,
`task-10`, …, `task-2`), **not** `task_id` order — so beyond seq 1/2 the sequence
number is not the task number; select a specific case by its capsule/`case.task_id`,
not by assuming `seq == task`. `payload` is bound
(`agent_input_digest`) and therefore authenticated. The desired outcome for judging
is the task's declared `user_scenario.instructions`, which the judge reads
independently from the dataset by `payload.case.task_id`. Neither it nor tau2's own
`reward_info` (the benchmark's score, which the compiler does not consume) is placed
in the bound payload. (To mirror Demo A's split exactly one may instead set
`capsule.effect` with `effect_request`/`effect_response` artifacts; the payload
form above needs no manual digest computation.)

### B3. Compile and run the evaluation

B3 is presenter-driven: it runs inside **Claude Code** with the `evaluation-compiler`
skill (agent host + model access), not a shell command. Run it in a **fresh** Claude
Code context. Compilation is a short **dialog** — you lead with the value proposition;
the skill derives what it can and asks for what it cannot infer; you answer from the
prepared facts. The exchange below is from a real run.

**The compile dialog:**

> **You:** invoke skills/evaluation-compiler/SKILL.md in this repo
>
> **evaluation-compiler:** *(loads `SKILL.md`)* I compile a **value proposition** plus
> a recorded-interaction source into an evaluation skill bundle. What should improve,
> and for whom? I'll derive the scenario, evaluation unit, outcome authority and
> judging policy myself; the one thing I usually can't infer is **access** — the named
> Capsule CLI profile that reads the CLL, or, if the source is a benchmark/dataset,
> where it lives so it can be backfilled into a CLL first.
>
> **You:** Give the customer a clear, empathetic service experience that fully resolves
> their request in a single interaction with minimal effort. We're evaluating an
> **airline** customer-service agent.
>
> **evaluation-compiler:** From that I derive: one customer interaction per case; draft
> axes for resolution completeness, single-interaction resolution, customer effort,
> empathy/tone, and policy compliance; aggregation none by default. Target mode is
> `declared` if each case ships its own criteria, else `evidence_derived` — I'll confirm
> once I see the source. The one thing I can't infer: **where are the interactions
> recorded?** An existing CLL (which profile?), or a benchmark/dataset to backfill
> (where does it live, and does it ship a scoring contract to preserve)?
>
> **You:** They're not in any system yet — just JSON files on disk. The recorded
> conversations are in
> `~/GitHub/tau2-bench/data/tau2/results/final/claude-3-7-sonnet-20250219_airline_default_gpt-4.1-2025-04-14_4trials.json`,
> and
> `~/GitHub/tau2-bench/data/tau2/domains/airline/tasks.json`
> describes the task behind each conversation and what counts as fully resolving it.

*(dialog continues — captured live below as the run proceeds)*

From here the skill inspects the **original benchmark data** — one sample run from the
results file and one task scenario from the dataset — to confirm the shape and target
mode, finalizes the axes, and compiles the bundle to
`~/.local/share/evaluation-bundles/airline-investigation/`: `axes.json`,
`references/source.md` (the dataset→Capsule payload mapping the backfill follows),
`resolved-spec.json`, and `references/{execution,capsule-cli}.md` (`capsulectl` is a
host prerequisite, not bundled). Compile touches no CLL — it reads the dataset — so it
is independent of B1/B2; the CLL that the run step below reads is the one B1/B2 create
(run them in either order, they meet at the run).

**Run the generated skill on one case** — a runtime invocation, not intake:

> **You:** Run the generated tau2-airline evaluation skill from
> `~/.local/share/evaluation-bundles/airline-investigation/`. Inputs:
> `profile=airlinedemo`, `selection=(1,2]`,
> `dataset_path=~/GitHub/tau2-bench/data/tau2/domains/airline/tasks.json`,
> `run_dir=~/.local/share/evaluation-runs/tau2-airline-eval/run`.

It enumerates the CLL, `get --raw` + `verify`s the seq-2 Capsule (`ec5b0c62…`, task 1),
reads the declared desired outcome by `payload.case.task_id` in one isolated context,
extracts the agent outcome from the transcript in another, judges the axes, publishes
the `evaluation-report/v1` Capsule at **seq 51**, and reads it back.

Read the published report back like any capsule:

```sh
capsulectl cll list --profile airlinedemo --after 50 --through 51
ID=$(capsulectl cll list --profile airlinedemo --after 50 --through 51 | python3 -c 'import sys,json;e=json.load(sys.stdin)["entries"];print(e[-1]["capsule_id"] if e else "")')
capsulectl get --profile airlinedemo --capsule-id "$ID"
```

Airline B3 has **not** been executed against this CLL yet, so no evaluation Capsule
id or judgments are pinned (contrast Demo A, a pinned validated run). The judged
system is the shipped `claude-3-7-sonnet` airline run (user simulator `gpt-4.1`);
point `--results` at another tau2 results file to evaluate a different system.

### B4. Aggregate across cases (cross-case roll-up)

B3 publishes one report per case (`aggregate:null` — the *within-case* roll-up).
A benchmark story also wants the *cross-case* roll-up: how the system did across
many tasks. That is a separate compiler output, generated only when
`cross_case_aggregation` is not `none`: a second **aggregation skill** whose input is
the `evaluation-report/v1` Capsules (never the source interactions). It selects the
report range, verifies each report, reduces their `axis_judgments` across cases
(per-axis pass/fail/unjudgeable counts and pass rate; the `all_required` or `native`
overall), and publishes one `evaluation-summary/v1` Capsule back into the same CLL —
itself signed, checkpointable and witnessable.

**Aggregate across cases** — same scenario, but now ask for a cross-case rate:

> **You:** Same airline scenario and access as before, but this time I also want a
> cross-case roll-up — a pass rate across the tasks. Set `cross_case_aggregation=rate`
> so you also generate the aggregation skill.
>
> **evaluation-compiler:** Compiling with `cross_case_aggregation=rate`; it adds an
> aggregation bundle whose input is the `evaluation-report/v1` Capsules (not the source
> interactions).
>
> **You:** Now run that aggregation skill: `profile=airlinedemo`, over this run's
> `evaluation-report/v1` Capsules. Select them by **type + shared axes digest +
> cohort**, not by a fixed sequence window — a full 50-case run appends its reports
> after the 50 backfilled entries, but any earlier one-case B3 report shifts those
> positions. Reduce the axis judgments across cases under one cohort with unique
> case/trial dedup, and publish one `evaluation-summary/v1` Capsule.

```sh
# the appended evaluation reports — filter to evaluation-report/v1 with this bundle's
# axes digest; don't assume a fixed seq window (seq 51+ only if nothing else appended)
capsulectl cll list --profile airlinedemo --after 50 --limit 1000
```

Aggregating all 50 airline tasks means 50 per-case judge runs first (paid). The
aggregation skill reduces whatever reports exist, so a subset is a valid summary as
long as its contributing set (cohort + unique case/trial keys) is recorded.

---

## Checkpointing and witnessing the CLL

`publish`/`cll append` only append entries — they do not witness or checkpoint.
Anchoring the log is a separate, explicit `cll checkpoint` step. This applies to
any CLL (SQLite `airlinedemo` here, or the MySQL `investigations` profile).

### C1. Local checkpoint (offline, no witness)

A checkpoint needs a *checkpoint* signing key (distinct from the producer signing
key), and that key must be trusted:

```sh
umask 077
CKEY=~/.local/share/evaluation-runs/tau2-airline-eval/keys/airline-checkpoint.ed25519
mkdir -p "$(dirname "$CKEY")"
CPUB=$(capsulectl key generate --output "$CKEY" \
       | python3 -c 'import sys,json;print(json.load(sys.stdin)["public_key"])')

capsulectl profile update --profile airlinedemo \
  --checkpoint-signing-key-file "$CKEY" --checkpoint-trusted-key "$CPUB"

CP=$(capsulectl cll checkpoint create --profile airlinedemo); echo "$CP"
# after B1+B2 (50 entries): {"checkpoint":97,"indexed_sequence":50,"statement":"<base64 COSE>", ...}
# checkpoint is the MMR size (2*n - popcount(n)), not the entry count; running B3
# appends sequence 51 and makes it 98 / 51.
```

With no endpoint configured, `create` is fully local: it builds and COSE-signs the
checkpoint over the current MMR and stores it; no network, no witness. Verify it
offline (optionally with a Capsule inclusion proof):

```sh
STMT=$(echo "$CP" | python3 -c "import sys,json;print(json.load(sys.stdin)['statement'])")   # reuse the create above
mkdir -p "$DEMO/run"   # owner-only (umask 077); avoids a shared /tmp symlink target
python3 -c "import json,sys;open(sys.argv[1],'w').write(json.dumps({'checkpoint':sys.argv[2]}))" "$DEMO/run/proof.json" "$STMT"
capsulectl cll verify --profile airlinedemo --proof "$DEMO/run/proof.json"
# -> checkpoint_signature_and_trust=passed, log_id=passed, embedded_consistency=passed
#    inclusion=not_performed (exit 3, partial) unless the proof includes capsule_id + path
```

### C2. Configure the Action State Group witness endpoint

The operator's witness is `capsule-anchor` at
`https://witness.agentactioncapsule.org`; its `/checkpoints` route is public and
unauthenticated for a non-enrolled `log_id` (no token). Resolve its authority key
and add the endpoint + key to the profile:

```sh
# resolve the witness authority public key (do not trust a hardcoded copy blindly)
curl -s https://witness.agentactioncapsule.org/anchor/authority-pubkey
# -> {"pubkey_hex":"39bb654c9dc0afe1c0edef0deffaa69099b8518836c9ba26e0491535840f96b5","key_id":"19a9ab3e02fad55c"}
# same key at /.well-known/did.json as publicKeyJwk.x (base64url) = ObtlTJ3Ar-HA7e8N7_qmkJm4UYg2ybom4EkVNYQPlrU

capsulectl profile update --profile airlinedemo \
  --checkpoint-endpoint https://witness.agentactioncapsule.org \
  --checkpoint-public-key 39bb654c9dc0afe1c0edef0deffaa69099b8518836c9ba26e0491535840f96b5
```

The pinned authority public key is
`39bb654c9dc0afe1c0edef0deffaa69099b8518836c9ba26e0491535840f96b5` (`key_id`
`19a9ab3e02fad55c`); re-resolve from `/anchor/authority-pubkey` or
`/.well-known/did.json` if it rotates. For an *enrolled* production log, e.g.
`investigations`, set the same checkpoint endpoint and public-key fields here with your
enrolled witness key (alongside the checkpoint signing/trusted keys from C1).

### C3. Publish the checkpoint to the witness and check status

A witness delivery is enqueued only by the **first `create` at a given MMR size
after the endpoint is configured**. C1 already created a checkpoint offline at the
50-entry size (97); so to witness, either target a *fresh* size — running B3 appends
seq 51, making size 98 new — or, if the size you want was already created offline,
append one more entry (`cll append`, or run B3) before this `create`. With the
endpoint configured (C2) and a fresh size, deliver by MMR size:

```sh
CP=$(capsulectl cll checkpoint create --profile airlinedemo)   # the only create at this size
SIZE=$(echo "$CP" | python3 -c "import sys,json;print(json.load(sys.stdin)['checkpoint'])")
STMT=$(echo "$CP" | python3 -c "import sys,json;print(json.load(sys.stdin)['statement'])")   # reused in C4
capsulectl cll checkpoint publish --profile airlinedemo --checkpoint "$SIZE"
# -> {"state":"verified","receipt":{...}}   (pending/failed otherwise)
capsulectl cll checkpoint status  --profile airlinedemo --checkpoint "$SIZE"
```

`--checkpoint` is the MMR size (not the entry count). On `publish` the witness
verifies the checkpoint's COSE signature against its embedded `key_id`, grades it
`mmr-verified` (it understands the CLL MMR scheme), timestamps + countersigns, and
returns a receipt; the CLI verifies that receipt against the witness authority key
from C2 and stores it. `status` re-verifies the STORED receipt locally and makes no
network call. Note: `publish` appends to the live, append-only public transparency
log.

**Not yet executed for `tau2-airline-20260910`.** Only the offline checkpoint (C1,
MMR 97) has been run for the airline log; C2–C5 here are the procedure. `publish`
would append this log's checkpoint to the **live** public witness — a permanent
record — so run it only when you mean to. (The retail `tau2-retail-20260909` log was
delivered live and returned `state=verified`, countersigned at witness
`tree_size=1063`; git history holds that pinned run.)

### C4. Fetch the witness record; re-verify the local checkpoint offline

The witness anchors the **checkpoint (the log's MMR root)**, not individual
Capsules. The witness *receipt* was already cryptographically verified against the
authority key during `publish`/`status` (C3). Here you fetch the witness's public
record of the checkpoint and independently re-verify the **local** checkpoint
statement offline (this step checks the local checkpoint's signature/trust/
consistency, not the fetched receipt):

```sh
LOG=tau2-airline-20260910
# the witness's countersigned checkpoint(s) for this log (this curl only prints it).
# Populated once C3's publish has run; the shape (from the retail run) is:
curl -s "https://witness.agentactioncapsule.org/checkpoints/$LOG"
# -> {"log_id":"<LOG>","mmr_size":98,"prev_size":97,
#     "root":"<hex>", "prev_root":"<hex>",
#     "key_id":"<this log's checkpoint signing key, distinct from the authority key>",
#     "receipt_b64":"0oRH…",  # COSE receipt
#     "leaf_index":<witness tree pos>,"tree_size":<witness tree size>,"equivocations":[]}

# verify the checkpoint offline against the trusted checkpoint key (no network).
# Reuse $STMT captured from the single C3 create above — do not re-create at this size.
mkdir -p "$DEMO/run"
python3 -c "import json,sys;open(sys.argv[1],'w').write(json.dumps({'checkpoint':sys.argv[2]}))" "$DEMO/run/proof.json" "$STMT"
capsulectl cll verify --profile airlinedemo --proof "$DEMO/run/proof.json"
# -> checkpoint_signature_and_trust=passed, embedded_consistency=passed, log_id=passed
#    inclusion=not_performed (exit 3, partial): this CLI build has no per-Capsule
#    audit-path emitter, so a single Capsule's inclusion against the checkpointed
#    root is not proven here — the checkpoint (hence the whole MMR) is.
```

The witness `root` is the bagged MMR root; the local checkpoint `statement` carries
the raw peaks and the 97→98 consistency proof (which `embedded_consistency` checks).
The `GET /v1/inclusion/{capsule_id}` route is for statements registered directly to
the transparency log, not for CLL-checkpoint capsules, so it returns `not found` for
an `airlinedemo` Capsule id.

### C5. Query the witness endpoint directly

```sh
curl -s https://witness.agentactioncapsule.org/health        # {"ok":true,"key_id":...,"tree_size":...,"latest_root_hash":...}
curl -s https://witness.agentactioncapsule.org/.well-known/did.json   # authority Ed25519 key (JWK)
# interactive API docs: https://witness.agentactioncapsule.org/docs
```

Network vs local: `create` (C1) and `status` (C3) are local — only `publish` (C3)
and the curls (C4/C5) contact the witness. `status`/`publish` both require the
endpoint configured (they derive the service id from it) and error with "checkpoint
service not configured" if it is unset, but only `publish` sends bytes over the
network.

Executed here: for the airline log only C1 (offline checkpoint, MMR 97 / indexed 50)
was run — no bytes left the machine. C2–C5 are the documented procedure and have not
been delivered to the live witness for `tau2-airline-20260910`. The retail log
`tau2-retail-20260909` was the live-executed example (C3 `state=verified`,
countersigned at witness `tree_size=1063`); git history holds that pinned run.
Because `publish` appends to a public, append-only log, only run it when you intend a
permanent public record. If a checkpoint at the current MMR size already exists
locally, append/observe a new entry before `create` so a fresh witness delivery is
enqueued.

---

## D. Verify a Capsule — and catch tampering

Every Capsule is content-addressed and its `payload` is **bound**, so verification is
offline — but be precise about what each check buys. Given the **expected `capsule_id`**
(the one you already trust, from the CLL or a permalink), recomputing the content
address and payload digest catches **any** change to the bytes, no key needed. That
only works against an id you pinned independently: hand someone an arbitrary record
with no trusted `capsule_id` and a forger can recompute a self-consistent id for a
tampered payload — so genuineness ultimately rests on the **producer signature** checked
against a key you independently trust (the profile's `--trusted-key`). Tampering with
the payload breaks the content-address chain against the pinned id, and breaks the
signature regardless. Uses the airline CLL from B1/B2.

### D1. Positive — a genuine Capsule verifies

```sh
ID=$(capsulectl cll list --profile airlinedemo --after 0 --through 1 \
     | python3 -c 'import sys,json;print(json.load(sys.stdin)["entries"][0]["capsule_id"])')
capsulectl get    --profile airlinedemo --capsule-id "$ID" --raw --output rec.json
capsulectl verify --profile airlinedemo --capsule rec.json ; echo "exit=$?"
# -> {"artifacts":{"payload":{"State":"present","Bound":true,"Verified":true}},
#     "capsule_identity":"passed","producer_signature_and_trust":"passed",
#     "cll_inclusion":"not_performed","business_truth":"not_performed", ...}
#    exit=0
```

Identity, the producer signature/trust, and the bound payload all pass.
`cll_inclusion` and `business_truth` are `not_performed`: a Capsule verify proves
**integrity and authorship**, not ledger inclusion (that's `cll verify`) or business
correctness.

### D2. Negative — tamper the payload, verification fails

Edit one byte of the bound payload (append `[TAMPERED]` to the first message), leaving
the `capsule_id` and stored digest exactly as an attacker would re-present them:

```sh
python3 - rec.json tampered.json <<'PY'
import json,sys,base64
rec=json.load(open(sys.argv[1])); art=rec["artifacts"][0]
p=json.loads(base64.b64decode(art["content"]))
p["agent_interaction"]["messages"][0]["content"] += " [TAMPERED]"
art["content"]=base64.b64encode(json.dumps(p).encode()).decode()  # capsule_id left untouched
json.dump(rec,open(sys.argv[2],"w"))
PY

capsulectl verify --profile airlinedemo --capsule tampered.json ; echo "exit=$?"
# -> {"capsule_and_artifacts":"failed","cll_inclusion":"not_performed", ...}
#    capsulectl: operation failed; ...
#    exit=1
```

The recomputed payload digest no longer matches the `agent_input_digest` the Capsule
committed to (nor the content-addressed `capsule_id`), so `capsule_and_artifacts`
**fails** and the CLI exits non-zero. This catch is naive-tamper only — the forger
here left `capsule_id` untouched. Against a `capsule_id` you already trust, detecting
change needs no key; a forger who also recomputes a matching `capsule_id` is caught
only by the producer signature checked against a trusted key. So a buyer recomputes
the content address against the `capsule_id` they trust to detect tampering, and
checks the signature against a producer key they independently trust.
