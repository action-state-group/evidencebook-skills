---
name: evidence-contract-compile
description: Compile a validated Evidence Contract into two runnable skills — a daily judge-and-close and a weekly blind-expert audit — specialised to that contract's clauses, tiers, disclosure policy and sample policy. Use when a customer's contract changes and their compiled skills need regenerating.
---
# Evidence Contract compile

**This is `evaluation-compiler`, evolved.** Where that skill turned a free-form value
proposition into axes and a scenario bundle, this one turns a validated **Evidence
Contract** into the same axes/judgment machinery plus two cron-run skills, wired to a
customer's own Evidence Book. The compiler is still the only editable source of
evaluation instructions; the compiled skills are still immutable outputs — fix this
skill or its references, then regenerate the whole pair, never patch a compiled skill
by hand. Draft note: this file has not yet replaced
[`../evaluation-compiler/SKILL.md`](../evaluation-compiler/SKILL.md); see
[`../README.md`](../README.md).

## Validate before reading anything as a spec

The input is a single Evidence Contract document. An abridged example, over the
tau2 airline demo domain:

```yaml
contract: airline-outcomes/v1
subject: agent "airline-cs" · book profile "airline"
counterparty: booking-system connector · book profile "airline-sor"
join: reservation_id
clauses:
  - id: refund-lands
    claim: every cancel_reservation reported as refunded has a matching
           refund_issued fact within 24h, amount equal
    tier: recomputed
  - id: policy-followed
    claim: cancellations outside the 24h window were refused unless a policy
           exception is cited in the transcript
    tier: judged
disclosure:
  payloads: selected
  suppress: [passenger_name, payment_method, email]
sample_policy: { weekly: 20, stratify_by: verdict }
close: { period: day, counterparty: airline-sor }
```

Before treating it as anything more than bytes on disk:

```sh
capsulectl contract validate CONTRACT.yaml --schema SCHEMA_PATH_OR_URL --json
```

`--schema` names the caller's schema — this skill embeds none of its own and does not
invent one. A failing validation stops compilation; report the `issues[]` verbatim and
do not proceed against an invalid contract, and never patch around a schema failure by
reading the offending field loosely. This verb is `not-consequential` (a local check);
it produces no capsule. Everything downstream in this file assumes the contract passed.

## Resolve from the contract, not from a conversation

Where the prior compiler asked one focused question at a time to fill gaps in a value
proposition, this one **derives everything from the contract's own fields** and asks
only when a field is genuinely absent or ambiguous — the contract is the spec, not
homework the user still owes:

- `subject` / `counterparty` (if any) — whose book this compiles against, and whether a
  second book is joined for reconciliation. A contract with no `counterparty` compiles
  a single-party Close only (`UNILATERAL` by construction, labelled as such — never
  invent a second party to reconcile against).
- `join` — the field that correlates records across the subject's and counterparty's
  books (e.g. `reservation_id`). Required whenever `counterparty` is present.
- `clauses[]` — each with an `id`, a `claim` (the thing being asserted), and a `tier`:
  - `tier: recomputed` — no model. The claim is a digest-to-digest or count-to-count
    check the `capsulectl-engine` plugin's folds can answer directly (`fold run
    --clause ID --profile NAME`, discovered via `plugin ls` — see
    `daily-judge-and-close/SKILL.md`). This skill does not invent fold logic; it
    records which registered fold answers the clause and rejects a `recomputed` clause
    that names no matching fold rather than approximating one with a judge.
  - `tier: judged` — the claim needs a semantic call the folds can't make (e.g. "was a
    policy exception properly cited"). For every `judged` clause, decompose the
    `claim` into the same **outcome → axes** structure the prior compiler used for a
    value proposition: one or more axes with applicability, required evidence,
    pass/fail boundaries and insufficient-evidence behavior, each carrying `role`
    (`required`/`optional`). A clause is one outcome; do not fan a single clause into
    several unrelated outcomes, and do not collapse two genuinely distinct clauses
    into one outcome to save axes. This is the same aggregation semantics as before
    (`target_mode`, `aggregation: none|all_required|native`, two-level roll-up) —
    unchanged, just scoped per clause instead of per whole scenario.
  - a compound tier (`recomputed + judged`, `judged → recomputed`, as in the EU AI Act
    example) means the clause's evidence comes from more than one step in sequence;
    document the sequence in `resolved-spec.json`, do not silently pick one half.
- `disclosure` (`payloads: all|selected`, `suppress: []`, optional `audience` map) —
  this skill **passes the policy through** into both compiled skills' resolved specs.
  It never chooses what to withhold; the contract decides, this skill only wires it to
  `bundle --disclose`.
- `sample_policy` (`weekly: N`, `stratify_by: verdict|clause`) — passed through to
  `weekly-blind-expert` unchanged. Reuse the deterministic stratified-draw rule already
  specified in `docs/calibration-sampling-spec.md` (seeded, length-prefixed digest
  ordering) rather than inventing a second sampling rule.
- `close` (`period: day|week`, optional `counterparty`) — passed through to
  `daily-judge-and-close`; a contract naming no counterparty here compiles a Close that
  is `UNILATERAL` by construction.
- `obligations_pack` (when present, by digest) — this skill never resolves pack
  currency or fetches a newer pack version; it records the digest the contract named
  and nothing else. Pack currency is a product concern, out of scope here.

If the contract is missing a field this skill cannot proceed without (most often: which
book profile to read, or the output location for the compiled pair), ask exactly that,
once, focused — never a full requirements interview. Never infer the book profile, the
domain, or which clauses apply from the current working directory.

## Generate the pair

Write both compiled skills under the target output directory resolved during intake
(never into this repo, never into the current working directory). For each:

- `daily-judge-and-close/` — specialised to this contract's clauses (which run as
  folds, which run as the pinned judge), its `close` policy, and its `disclosure`
  policy. Reuses `daily-judge-and-close/SKILL.md` here as the template shape; the
  compiled copy names the concrete clause ids, tiers and profile.
- `weekly-blind-expert/` — specialised to the contract's `sample_policy` and the set
  of `judged`-tier clauses it audits (a `recomputed`-only contract still compiles this
  skill, but it has nothing to sample — say so in the resolved spec rather than
  omitting the skill).

Both compiled skills cite the resolved judge pin (model id, prompt digest, axes digest,
sampling — via `judge pin`, once that verb lands; until then, record the same fields by
hand in `resolved-spec.json` and mark the pin as `not yet sealed`) so drift between
contract versions is detectable (`judge drift`, same caveat).

Seal a `contract-compile/v1` record citing the contract by digest via `capsulectl
publish` — this is the primary consequential action this skill takes, and the one
place this skill is `primary-action`. Every other step above is `not-consequential`.
If the seal fails, report `evidence unavailable`, stop, and do not treat the compiled
pair as installed.

## The approval is a record, not a checkbox

**A human approves the compiled pair before it is installed, and that approval is
itself a record** (its shape comes from the judge record family spec, not invented here). This
skill presents the compiled `daily-judge-and-close` and `weekly-blind-expert` text,
the resolved clause→tier mapping, and the disclosure/sample policies for a human to
read before installation; it does not install on its own judgment, and it does not
manufacture an approval from silence or a timeout.

## Every action seals a record

Every action this skill takes (install, discover, map, `contract validate`, generating
the pair, the approval) seals one capsule.
Seal it with `scripts/skill_action.py`. That is one `skill-action/v1` capsule with
digests only (inputs, stdout, argv), never contents, paths, profile or environment.
For example:

```sh
python3 scripts/skill_action.py --profile NAME --skill evidence-contract-compile --action contract-validate \
    --at 2026-09-23T12:00:00Z --input contract=CONTRACT.yaml \
    --input schema=SCHEMA.json -- capsulectl contract validate CONTRACT.yaml --schema SCHEMA.json --json
```

`--at` fixes the capsule's timestamp, so a re-run with the same `--at` seals nothing
new. A failed action is sealed too (`outcome: failed`). If its record cannot be sealed,
the action reports `evidence unavailable` and the skill stops there. See
`docs/skill-action-capsules.md`.

## What this skill never produces

The book's own thin verb skill (`capsulectl`) — that ships with `capsule-cli`, static,
consumed not compiled. A second Evidence Contract schema, a second sampling rule, or a
second builder for `result`/`bundle --disclose` — those belong to the judge record
family spec and to `capsulectl`; check there before adding one here. Pack currency or a fetched
newer obligations pack. A judgment made in code, or a signature made in a prompt.
