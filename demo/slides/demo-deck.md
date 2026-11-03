---
marp: true
title: Evaluation-compiler — provable agent evaluation
paginate: true
theme: default
---

<!--
Render (from repo root):  npx @marp-team/marp-cli@latest demo/slides/demo-deck.md -o demo-deck.html
         (--pdf, or --pptx for PowerPoint; --pptx-editable needs LibreOffice/soffice)
Live demo: run the fenced commands in ONE terminal; shell variables (TAU2, EC, DEMO,
…) persist across the blocks. Two exceptions to top-to-bottom: B3 is presenter-driven
(an agent step, not a shell command), and the checkpoint slides are alternatives —
the offline checkpoint and the witnessed checkpoint are two paths at the same MMR size,
so run one, not both. Commands are copy-paste from DEMO.md.
-->

# Provable agent evaluation
## evaluation-compiler + Agent Action Capsules

Turn a **scenario + value proposition** into evaluation **axes** and an
executable **evaluation skill**, run it over a **CLL** of recorded agent
interactions, and publish a **signed, verifiable evaluation report Capsule**.

Two demos:
- **A — Investigation**: evaluate a production investigation (CLL already exists)
- **B — tau2**: evaluate a public benchmark (backfill a local CLL first) — *live*

---

## The pieces

- **Agent Action Capsule (AAC)** — a signed, JCS-canonical, content-addressed
  record of one agent action (IETF I-D `draft-mih-scitt-agent-action-capsule-04`).
- **CLL (Checkpointed Local Log)** — an append-only MMR log of Capsule IDs;
  anchorable to a public **witness**.
- **capsulectl** — the CLI: seal / store / publish / list / verify / checkpoint.
- **evaluation-compiler** — compiles *value proposition → axes → skill bundle*;
  the per-case skill selects a **range** of cases (a sequence range or time
  window), verifies each, extracts **desired** vs **agent** outcome in isolated
  contexts, judges, and publishes **one `case-evaluation/v1` Capsule per case**.
  When cross-case aggregation is asked for, it also generates a second
  **aggregation skill** that reduces those reports into one
  `evaluation-summary/v1` Capsule.

*The interaction and the case-evaluation Capsules are signed and re-verifiable; the
desired outcome is sourced independently and its provenance recorded in the report.*

---

## The workflow (both demos)

```
scenario + value proposition
        │  evaluation-compiler
        ▼
   axes.json + evaluation skill bundle
        │  run skill over the CLL
        ▼
 select a range → for each case: verify Capsule → extract desired outcome (source of truth)
                                 → extract agent outcome (from the Capsule)
                                 → judge against axes
        ▼
 publish one case-evaluation/v1 Capsule per case  → checkpoint / witness
```

The selection is a sequence range `(after, through]` or a time window; the pipeline
above repeats per case. Desired and agent outcomes are extracted in **separate
contexts**; the judge never conflates "what should happen" with "what the agent did."

---

## Setup 1/3 — toolchain (start from nothing)

Need **git**, **Go 1.21+** with toolchain auto-download (the default; it fetches the
CLI's pinned toolchain, currently 1.27), **python3** (stdlib only — to read JSON output).
Run in one terminal.

```sh
# macOS (Homebrew). Linux: apt/dnf install git golang python3; or https://go.dev/dl
brew install go git python3

# make `go install` binaries findable on PATH (add this line to your shell profile)
BIN="$(go env GOBIN)"; export PATH="$PATH:${BIN:-$(go env GOPATH)/bin}"
```

No API key, no `pip install`: `capsulectl` generates the signing keys itself.

---

## Setup 2/3 — clone the repos

```sh
mkdir -p ~/GitHub && cd ~/GitHub
git clone https://github.com/action-state-group/capsule-cli.git
git clone https://github.com/action-state-group/evaluation-compiler.git

# tau2-bench is 1.8 GB fully; sparse-clone only what the demo reads (~20 MB)
git clone --filter=blob:none --sparse --depth 1 \
  https://github.com/sierra-research/tau2-bench.git
git -C tau2-bench sparse-checkout set --no-cone \
  /data/tau2/results/final/claude-3-7-sonnet-20250219_airline_default_gpt-4.1-2025-04-14_4trials.json \
  /data/tau2/domains/airline
```

The two `action-state-group` repos must be **public** (or the audience needs
access). `tau2-bench` is public.

---

## Setup 3/3 — build & install the CLI

```sh
GOWORK=off go -C ~/GitHub/capsule-cli install ./cmd/capsulectl

capsulectl --version    # capsulectl version 0.1.0-dev  ← if "command not found", re-run the PATH export
```

Nothing else is global: profiles live under `~/.config/capsule/`, the demo's CLL
and keys under `~/.local/share/evaluation-runs/`. No database server, no cloud,
no API key for the live path.

---

## Demo B — tau2 (public benchmark)

**Why tau2 needs a step Demo A doesn't:** tau2 is a *dataset*, not a CLL. But
tau2-bench ships **real recorded runs** (`data/tau2/results/final/*.json`) — an
agent (claude-3-7-sonnet) against a user simulator (gpt-4.1). We **backfill**
those real interactions into a local SQLite CLL, then evaluate exactly like A.
This demo uses the **airline** domain (50 tasks).

**Compiler input**
- Value proposition: *"Give the customer a clear, empathetic service experience
  that fully resolves their request in a single interaction with minimal effort."*
- `target_mode: declared` — desired outcome = the tau2 task scenario, read by
  `task_id`, never seeing the transcript. tau2's own reward is **not** used.

**Generated axes (`aggregation: none`)** — the compiler derives these from the value
proposition; for this value prop they come out as, e.g.:
1. `request_resolution` · 2. `effort_and_containment` · 3. `communication_clarity`

---

## Inside a tau2 results file

```text
results/final/…_airline_…_4trials.json
├─ info           run metadata: agent llm, user-sim llm, domain, limits
├─ tasks[50]      the SCENARIOS + gold
│    id ───────────────────────────────────────────────┐ (join key)
│    user_scenario.instructions{reason_for_call,…}      │ → declared desired outcome
│    evaluation_criteria{actions[],nl_assertions[],…}   │ → tau2 gold (compiler ignores)
└─ simulations[200 = 50 tasks × 4 trials]  the RECORDED RUNS
     task_id ──────────────────────────────────────────┘  + trial  (unique per run)
     messages[12–104]{role:assistant|user|tool, content, tool_calls[{name,arguments}]}  → transcript to judge
     reward_info{reward, action_checks[], nl_assertions[], db_check}                     → tau2 native score
```

Backfill takes one trial-0 run per task → `payload.case{task_id}` +
`payload.agent_interaction.messages`; the judge rejoins the dataset task by `task_id`.

---

## One recorded interaction (airline · task 3, trial 0)

`simulations[task_id=3]` — 14 turns, backfilled verbatim into `agent_interaction.messages`:

```text
assistant  Hi! How can I help you today?
user       I need to know exactly how many suitcases I'm allowed to bring on my flight…
assistant  I'd be happy to help… To provide you with…            (asks for ID + confirmation)
user       my user ID is anya_garcia_5901 and my confirmation number is JMO1MG…
assistant  I'll check your reservation details right away.
    ↳ get_reservation_details({"reservation_id":"JMO1MG"})
tool       {reservation_id:"JMO1MG", cabin:"economy", passengers:[…×2], …}
assistant  Now I'll check your user details to determine your membership level…
    ↳ get_user_details({"user_id":"anya_garcia_5901"})
tool       {name:{first_name:"Anya",…}, membership:"silver", …}
assistant  Based on your reservation and membership status, here's your baggage allowance…
user       I'm pretty sure I'm a Gold member, not Silver. Can you double-check…?
assistant  I apologize… Let me double-check your membership status right away.
    ↳ get_user_details({"user_id":"anya_garcia_5901"})
tool       {…, membership:"silver", …}
assistant  After checking again, I can confirm your status is Silver…
user       Yes, please transfer me to a supervisor. Thank you. ###TRANSFER###
```

Multi-turn, tool-augmented; the agent held the correct **Silver** allowance under
pressure. This whole exchange is the bound payload of one Capsule.

---

## Demo B · B1 — create a local SQLite CLL  *(live)*

```sh
umask 077
DEMO=~/.local/share/evaluation-runs/tau2-airline-eval
# re-runnable: delete the old airline SQLite CLL and profile first
rm -f "$DEMO"/store.db* ; rm -rf "$DEMO"
rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/capsule/profiles/airlinedemo.yaml"
mkdir -p "$DEMO/keys"

# the CLI generates the signing key (writes the seed 0600; prints the public key)
PUB=$(capsulectl key generate --output "$DEMO/keys/airline.ed25519" \
      | python3 -c 'import sys,json;print(json.load(sys.stdin)["public_key"])')

capsulectl profile create --name airlinedemo --type sqlite \
  --sqlite-path "$DEMO/store.db" \
  --namespace tau2 --log-id tau2-airline-20260910 \
  --signing-key-file "$DEMO/keys/airline.ed25519" --trusted-key "$PUB"
capsulectl store init --profile airlinedemo

# what got stored (safe to show: identity + backend + key-file PATHS, not the seed)
cat "${XDG_CONFIG_HOME:-$HOME/.config}/capsule/profiles/airlinedemo.yaml"
#   name/type/log_id/namespace · connection.database (store.db path)
#   signing.file (path to the 0600 seed, NOT the secret) · trusted_keys (public)
```

---

## Demo B · B2 — backfill every task, publish to the CLL  *(live)*

```sh
TAU2=~/GitHub/tau2-bench
EC=~/GitHub/evaluation-compiler
RES="$TAU2/data/tau2/results/final/claude-3-7-sonnet-20250219_airline_default_gpt-4.1-2025-04-14_4trials.json"

# one seal request per task (its trial-0 run) — 50 for airline
python3 "$EC/demo/backfill/backfill.py" --results "$RES" --out "$DEMO/backfill"

# publish each as one CLL entry
for f in "$DEMO"/backfill/*.json; do capsulectl publish --profile airlinedemo --request "$f" >/dev/null; done

capsulectl cll list --profile airlinedemo --after 0 --limit 1000 \
  | python3 -c 'import sys,json;print("CLL entries:",len(json.load(sys.stdin)["entries"]))'
```

Expected: `wrote 50 seal requests …` → `CLL entries: 50`.
Capsule IDs are content-addressed: **seq 1 = `56b1f95f…`** (task 0),
**seq 2 = `ec5b0c62…`** (task 1) — same with any signing key.

---

## Demo B · read one back — signed & verifiable  *(live)*

```sh
# the seq-1 Capsule id (task 0) — 56b1f95f…
ID=$(capsulectl cll list --profile airlinedemo --after 0 --through 1 \
     | python3 -c 'import sys,json;print(json.load(sys.stdin)["entries"][0]["capsule_id"])')

capsulectl get    --profile airlinedemo --capsule-id "$ID" --raw --output rec.json
capsulectl verify --profile airlinedemo --capsule rec.json
# identity + producer signature + payload binding all verify;
# rec.json shows case / provenance / the real agent_interaction transcript
```

`verify` re-checks the content-address, the Ed25519 producer signature, and that
the bound `payload` matches its `agent_input_digest` — offline. Detecting change
against a `capsule_id` you already trust needs no key; authorship is checked against
the trusted key you pin.

---

## Demo B · B3 — compile axes & evaluate  *(presenter-driven, not copy-paste)*

B3 is an **agent** step, not a shell command: it runs inside **Claude Code** with
the `evaluation-compiler` skill — presenter-driven, in a **fresh context**.
Compilation is a short **dialog** (full script in `DEMO.md`):

1. **Compile** — you lead with the **value proposition**; the skill derives the
   evaluation unit, target mode and axes, and asks only for what it can't infer
   (mainly **access**: the `airlinedemo` CLL + the declared dataset). It generates
   `axes.json`, `references/source.md`, the skill bundle.
2. **Run the generated skill** — `selection=(1,2]` → verifies the seq-2 Capsule
   (`ec5b0c62…`, task 1), reads the **declared** desired outcome by `task_id`,
   extracts the **agent** outcome from the transcript in a separate context, judges
   the axes, and **publishes a `case-evaluation/v1` Capsule at seq 51**.

Only *after* B3 has run does seq 51 exist; then read the report back like any Capsule:

```sh
capsulectl cll list --profile airlinedemo --after 50 --through 51
ID=$(capsulectl cll list --profile airlinedemo --after 50 --through 51 \
     | python3 -c 'import sys,json;e=json.load(sys.stdin)["entries"];print(e[-1]["capsule_id"] if e else "")')
capsulectl get --profile airlinedemo --capsule-id "$ID"
```

---

## The evaluation report Capsule (`case-evaluation/v1`)

Bound payload of the published report:

- `evaluation_identity`, `case_run_identity`, `source_selection` (store/log/entries)
- `bundle_provenance` — SHA-256 of every bundle file (which axes/skill produced it)
- **`desired_outcome`** + **`agent_outcome`** — each claim cites evidence ids
- **`axis_judgments`** — pass / fail / unjudgeable + rationale per axis
- `aggregate` (null here), `verification_references`, `limitations`

The report is itself a signed Capsule in the CLL — shareable as a permalink the
buyer can **verify offline**, no access to the vendor's systems.

---

## The report Prompt 2 produces (`case-evaluation/v1`)

For the airline seq-2 case (`ec5b0c62…`, task 1), the generated skill judges each
compiled axis against the real transcript and publishes one report:

```text
axis_judgments (one entry per compiled axis; produced by running Prompt 2):
  request_resolution     = pass | fail | unjudgeable   + rationale + evidence_ids
  effort_and_containment = pass | fail | unjudgeable   + rationale + evidence_ids
  communication_clarity  = pass | fail | unjudgeable   + rationale + evidence_ids
  aggregate              = null   (within-case aggregation: none)
```

→ signed `case-evaluation/v1` Capsule at **seq 51**, verifiable offline;
desired/agent/judge each run in an **isolated context**. Airline B3 is **not yet run**,
so the statuses above are the report *shape*, not pinned values — **Demo A (Investigation)**
below is a pinned, real validated run of this exact pipeline.

---

## Aggregate across cases → `evaluation-summary/v1`

One report per case answers *"was this run good?"* A benchmark also asks *"how good
across all tasks?"* — the **cross-case** roll-up.

- A **second compiler output** (generated when `cross_case_aggregation ≠ none`): an
  **aggregation skill** whose input is the `case-evaluation/v1` Capsules, **not**
  the source interactions.
- It verifies each report, reduces `axis_judgments` across cases (per-axis pass rate;
  `all_required` / `native` overall), and publishes one **`evaluation-summary/v1`**
  Capsule back into the CLL — itself signed, checkpointable, witnessable.
- Re-aggregate any subset without re-judging; the contributing report ids are recorded.

*50 report Capsules → 1 summary Capsule.* (Judging all 50 airline tasks is 50 runs;
reports are selected by type + axes digest + cohort, not a fixed seq window.)

---

## Checkpoint the CLL  *(live, offline — no witness)*

```sh
CKEY="$DEMO/keys/airline-checkpoint.ed25519"
CPUB=$(capsulectl key generate --output "$CKEY" \
       | python3 -c 'import sys,json;print(json.load(sys.stdin)["public_key"])')

capsulectl profile update --profile airlinedemo \
  --checkpoint-signing-key-file "$CKEY" --checkpoint-trusted-key "$CPUB"

# NO-WITNESS path: create is LOCAL only (no endpoint configured). To WITNESS the same
# MMR size instead, SKIP this create — the next slide sets the endpoint FIRST, because a
# delivery is enqueued only by the first create at a size after the endpoint is set.
capsulectl cll checkpoint create --profile airlinedemo
# with the 50 backfilled entries: {"checkpoint":97,"indexed_sequence":50,"statement":"<COSE>"}
# `checkpoint` is the MMR size (2*n - popcount(n)), not the entry count; if B3 has
# appended seq 51 it is 98/51.
```

*Offline vs witnessed are alternative paths for a given MMR size — don't create the same size twice.*

---

## Anchor to the operator's public witness  *(live — real append)*

```sh
# resolve the witness authority public key (verify receipts against this)
curl -s https://witness.agentactioncapsule.org/anchor/authority-pubkey
# -> {"pubkey_hex":"39bb654c9dc0afe1c0edef0deffaa69099b8518836c9ba26e0491535840f96b5",
#     "key_id":"19a9ab3e02fad55c"}

capsulectl profile update --profile airlinedemo \
  --checkpoint-endpoint https://witness.agentactioncapsule.org \
  --checkpoint-public-key 39bb654c9dc0afe1c0edef0deffaa69099b8518836c9ba26e0491535840f96b5

# endpoint is now set; this must be the FIRST create at this MMR size (don't run the
# offline create on the previous slide for the same size, or append an entry first)
CP=$(capsulectl cll checkpoint create --profile airlinedemo)       # the ONLY create at this size
SIZE=$(echo "$CP" | python3 -c 'import sys,json;print(json.load(sys.stdin)["checkpoint"])')
STMT=$(echo "$CP" | python3 -c 'import sys,json;print(json.load(sys.stdin)["statement"])')   # reused next slide
capsulectl cll checkpoint publish --profile airlinedemo --checkpoint "$SIZE"   # -> {"state":"verified","receipt":{…}}
capsulectl cll checkpoint status  --profile airlinedemo --checkpoint "$SIZE"   # re-verifies stored receipt, offline
```

**Not yet delivered for the airline log.** Only the offline checkpoint (MMR 97) was
run here; `publish` above would append the airline checkpoint to the **live** public
log — a permanent record, so run it deliberately. (The retail log *was* delivered live:
`state=verified`, countersigned at witness `tree_size 1062→1063` — a pinned run in git
history.) A delivery is enqueued only by the **first `create` at a size after the
endpoint is set**, so target a fresh size (run B3 → seq 51 → MMR 98) or append an entry.

---

## Fetch the witness record; re-verify locally

Once `publish` (prev slide) has run, the witness *receipt* is verified against the
authority key. Here: fetch the witness's public record, and independently re-verify
the **local** checkpoint offline.

```sh
# 1. fetch the witness's countersigned checkpoint for this log (prints only).
#    Populated after publish; shape (from the retail run) is:
curl -s https://witness.agentactioncapsule.org/checkpoints/tau2-airline-20260910
#   -> {"mmr_size":98,"prev_size":97,"tree_size":<n>,"equivocations":[],
#       "root":"<hex>", "receipt_b64":"0oRH…",   # COSE receipt
#       "key_id":"<this log's checkpoint key, != the authority key 39bb654c…>"}

# 2. re-verify the LOCAL checkpoint offline (reuse $STMT from the single create — no re-create)
mkdir -p "$DEMO/run"
python3 -c 'import json,sys;open(sys.argv[1],"w").write(json.dumps({"checkpoint":sys.argv[2]}))' "$DEMO/run/proof.json" "$STMT"
capsulectl cll verify --profile airlinedemo --proof "$DEMO/run/proof.json"
#   -> checkpoint_signature_and_trust=passed, embedded_consistency=passed, log_id=passed
```

The witness anchors the **MMR root**, not each Capsule. A single Capsule's inclusion
would need a local per-Capsule audit path; this CLI build ships none, so inclusion is
**not proven** (`inclusion=not_performed`) — only the checkpoint, hence the whole MMR,
is. `GET /v1/inclusion/{capsule_id}` is the direct-register surface and 404s a CLL Capsule.

---

## Verify a Capsule — and catch tampering  *(live)*

Content-addressed + **bound** payload → offline verify. Recomputing digests against a
**pinned `capsule_id`** catches change with no key; a self-consistent forgery (id
recomputed too), or confirming **who** signed it, needs the pinned trusted key.

```sh
# re-select the seq-1 Capsule (independent of whether B3 ran)
ID=$(capsulectl cll list --profile airlinedemo --after 0 --through 1 \
     | python3 -c 'import sys,json;print(json.load(sys.stdin)["entries"][0]["capsule_id"])')
capsulectl get    --profile airlinedemo --capsule-id "$ID" --raw --output rec.json
capsulectl verify --profile airlinedemo --capsule rec.json          # exit 0
# -> capsule_identity=passed, producer_signature_and_trust=passed,
#    payload {Bound:true, Verified:true}

# tamper one byte of the bound payload, leave capsule_id as an attacker would present it:
python3 - <<'PY'
import json,base64
r=json.load(open("rec.json")); a=r["artifacts"][0]
p=json.loads(base64.b64decode(a["content"]))
p["agent_interaction"]["messages"][0]["content"] += " [TAMPERED]"
a["content"]=base64.b64encode(json.dumps(p).encode()).decode()
json.dump(r,open("tampered.json","w"))
PY
capsulectl verify --profile airlinedemo --capsule tampered.json     # exit 1
# -> {"capsule_and_artifacts":"failed"}
```

The recomputed payload digest ≠ the committed `agent_input_digest` / `capsule_id`, so
verify **fails** (the forger here left `capsule_id` untouched). A buyer detects change
against a `capsule_id` they trust — offline, no key — and confirms **authorship**
(and catches a fully re-signed forgery) against a producer key they independently trust.

---

## Demo A — Investigation (production CLL)  *(concept; internal, not copy-paste)*

Same workflow, source is an **existing production CLL** of real investigations.
- Value proposition: *"Under limited evidence, reduce ticket uncertainty and
  guide the handler to the correct next step faster and more safely."*
- `target_mode: evidence_derived` — truth comes from the live tracker issue
  (independent evidence), not a declared spec.
- Axes: `uncertainty_reduction`, `next_step_correctness`, `safety_calibration`.

**Real validated run:** source `9c4a2524…` (seq 165, tracker #82049) → evaluation
Capsule `cbcb24e9…` (seq 169); judgments `uncertainty_reduction=pass`,
`next_step_correctness=fail`, `safety_calibration=pass`, `aggregate=null`.

---

## Recap

- **One workflow**, two sources: an existing CLL (A) or a public dataset
  backfilled into a CLL (B).
- Axes are **compiled from the value proposition**, not a hand-checklist and not
  the benchmark's native score.
- The **source interaction** and the **evaluation report** are signed,
  content-addressed Capsules in a checkpointable CLL; the desired/agent outcomes and
  judgments are fields inside the report Capsule, and the desired truth is sourced
  independently (its provenance recorded, not necessarily signed).
- The evaluation report **verifies offline** and can be **witnessed** on a public
  transparency log.

Repos: `action-state-group/capsule-cli`, `action-state-group/evaluation-compiler`,
`sierra-research/tau2-bench`. Full runnable script: `evaluation-compiler/demo/DEMO.md`.
