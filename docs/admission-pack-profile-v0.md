# Admission pack profile v0

An admission pack is the relying party's own policy over what it has received
about a counterparty, run before the act. Its output is a decision: GO, ASK,
LIMIT or NO, with the tier and the rows that decided it. It is a Terms Pack in
the one pack format, `pack-source.yaml` with `scope.kind: admission`. Like any
pack, it is written by a person or their AI and pinned by digest.

The pack states thresholds only. The evaluator does the math: the value band,
the tier, the card's freshness, distinct-controller counts and denominators.
The evaluator is capsule-engine#265, one implementation in Go (`go/admission`)
and Rust (`rust/capsule-engine`), so every caller decides the same way. This
repository validates a pack (`scripts/admission_pack.py`, through
`scripts/pack_compile.py validate`) and compiles it to an Evidence Contract and
to `pack-definition.json`, the artifact the evaluator reads (§1.1). It does not
evaluate one.

Sources:

- Steven's ruling of 2026-10-30: admission uses the Terms Pack build approach, and the SDK does the math.
- The admission design of 2026-10-27, §2 to §4.
- Reference v3 §3A.2 and §3A.14.
- The register, §13.1 items 16 and 26.
- #51.

The baseline pack is [`packs/admission-baseline/`](../packs/admission-baseline/pack-source.yaml).

## 1. The pack

| Field | Meaning |
|---|---|
| `pack_id`, `pack_version` | `owner/name/version`, ending in `pack_version` |
| `scope` | `{kind: admission}` |
| `source` | optional provenance text (a string) |
| `outcomes` | the outcomes this pack yields. It must include GO |
| `missing` | what a missing input gives: `LIMIT` (at the lowest tier) or `NO`, and never GO. It must be in `outcomes` |
| `accept` | the mapping table. Each accepted currency maps to its band unit and scale, `{band, scale}`: an amount in that currency times `10^scale` is the amount in the band unit, so `msat: {band: sat, scale: -3}`. Nothing converts across units |
| `tiers` | the ladder, lowest first, each `{id, max_decade: {<band unit>: <decade>}}`. Every key must be a band unit in `accept`. A unit's ceiling rises above that of the last lower tier naming it |
| `budget` | `{max_asks, deadline_s}` (0 to 1,000 asks; 1 second to a century): how many asks a counterparty may get in the caller's budget window, and how long an ask waits before an unanswered one is recorded as absence (design §8) |
| `trust_roots` | optional `{controllers, witnesses, judges, rails}`. The first three are lists of names, saying whose word this pack counts. `rails` is a list of `{id, digest}` pins, each naming a rail by its adapter declaration: the declaration's id and the SHA-256 of its bytes (AAC#406). An empty or absent list trusts none |
| `rows` | the rows, below |

No other field is read, and an unknown field is refused. A pack has no weight,
score or other place a ranking could hide.

Write outcome names quoted (`"NO"`). YAML readers disagree on which unquoted
scalars are strings. PyYAML (YAML 1.1) reads `NO`, `1:30` and `010` as a
boolean and integers, and yaml.v3 (YAML 1.2) reads `1e3` and `0o10` as numbers.
So a plain (unquoted) scalar may only be:

- a plain decimal integer (`3`, `-1`);
- a dotted version (`1.0.0`);
- text that starts with none of `0-9 + - . ~ <` and is not a boolean or null
  word (`y`, `n`, `yes`, `no`, `on`, `off`, `true`, `false` or `null`, in any of
  their cases).

Anything else is quoted. The lint refuses a plain scalar outside this rule, and
also anchors, aliases and explicit tags.

A pack then reads one way everywhere, or not at all.

**A pack picks which outcomes it uses.** A Mesh pack under Steven's 10-29
rulings (u126, u137) yields `["GO", "NO"]` only. It also keeps `own_history`
from deciding NO: an adverse adjudication is sealed as a row result
(`record`), and the operator turns it into NO through its own config. The
baseline lets our own adjudicated history decide NO, as design §4 draws it, so
it is not the Mesh default while u137 stands.

### 1.1 The pinned artifact

Authors and operators write and edit `pack-source.yaml`. The evaluator never
reads YAML: `pack_compile.py compile` writes `pack-definition.json`, and that
file is what a deployment pins and what a decision cites.

- It is the source in JSON with `"format": "admission-pack/v0"` added, encoded
  as RFC 8785 (JCS) bytes. Optional fields are written out: `params` as `{}`,
  and the three `trust_roots` lists of names. The evaluator therefore applies
  no default. `trust_roots.rails` is the one exception: it is written only when
  the pack pins a rail, and the evaluator reads its absence as an empty list.
  A pack that pins no rail therefore keeps the bytes, and the digest, it had
  before rails were added.
- A pin is named and cited as a live pack's is: `pack_id` plus
  `definition_digest`, the SHA-256 of those bytes. The decision's `reads`
  policy entry carries both. Admission adds no digest name of its own.
- The evaluator loads the bytes only if they are exactly the JCS encoding of
  their own parse. That rules out duplicate keys, other whitespace or key order,
  and non-integer numbers. It then decodes them strictly: unknown fields, nulls
  and wrong types are refused. Its loader holds every rule the lint holds
  (below), so a pack refused here is refused there too.
- PyYAML, in the compiler, is the only YAML reader. A pack therefore reads one
  way, as this compiler reads it.

The baseline's compiled files are committed beside it in
`packs/admission-baseline/compiled/`, and a test keeps them equal to what the
source compiles to.

### Rows

| Field | Meaning |
|---|---|
| `id` | lowercase letters, digits, `-` or `_`; unique |
| `statement` | what the row checks, in words |
| `source` | where its input comes from (design §3): `platform`, `card` (the counterparty's own card, as of its checkpoint), `bound` (an artifact returned to our own ask, over our nonce), `own_history`, `operator`, `vouch`, `stake` or `judged` |
| `check` | the evaluator predicate, from the list in §2 |
| `params` | the predicate's thresholds, as integers |
| `from` | the lowest tier the row applies to |
| `on_fail` | `"NO"`, `"LIMIT"` or `"record"`. A judged row's is `{cap: <tier>}` |
| `ask` | optional `{derivation}`, on a `LIMIT` row only: the Evidence Request it makes when it does not pass |

`record` means the row is read and sealed with the decision but decides nothing.

### What the lint refuses

- An `on_fail: "NO"` on a `card`, `bound`, `vouch`, `stake` or `judged` row. NO
  comes only from platform facts, the party's own adjudicated history, or the
  operator's own config (Steven, 10-29: u126 and u137).
- A judged row whose `on_fail` is anything but `{cap}`, or whose cap is not a
  tier below its `from`, or one in a pack whose `outcomes` lack LIMIT. A judged
  row caps a tier and never decides NO (D-23).
- `missing: GO`.
- `on_fail: "LIMIT"` on a row from the lowest tier. The lowest tier is the floor,
  with nothing below it to limit to.
- An `ask` on any row but a `LIMIT` row.
- An `on_fail` or `ask` whose outcome the pack does not yield.
- An unknown predicate, a predicate under the wrong source, or a missing or
  unknown param.
- A budget out of range: `max_asks` from 0 to 1,000, and `deadline_s` from 1
  second to a century.
- A currency, band unit or other key that is not a string (`840:` is quoted).
- A param below 0 or above its bound: `max_age_s` up to a century of seconds,
  `min_days` and `window_days` up to 36,500, `min` and `k` up to 2^53 − 1,
  `step_decades` up to 60, and `max_adverse_permille` up to 1,000.
- A `from` or `cap` that names no tier.
- A rail pin that is not exactly `{id, digest}`, has an empty id, has a digest
  other than 64 lowercase hex digits, or is listed twice. A rail named without
  a pin (`rails: [x402]`) is refused too.
- A ladder whose `k` is 0: a band is earned by at least one subject.
- A ceiling in a unit `accept` does not name, a ceiling that does not rise,
  or a unit in `accept` that no tier names.
- A field of the wrong type. It is reported, never raised.

## 2. Predicates

Each predicate reads `pass`, `fail` or `not_read`. A row that counts also
records its count, and its denominator where one exists.

| `check` | Source | Params | Pass when | `not_read` when | Count / denominator |
|---|---|---|---|---|---|
| `platform.attestation_not_invalid` | platform | | release attestation is not `invalid` | unknown | |
| `platform.owner_signed` | platform | | the owner signed | unknown | |
| `card.verified` | card | | the card verified (`unverifiable` fails) | absent, refused, unanswered | |
| `card.fresh` | card | `max_age_s` | latest checkpoint at most `max_age_s` old, and not after now | card not verified | |
| `card.key_age` | card | `min_days` | first checkpoint at least `min_days` old | card not verified | |
| `card.witnessed` | card | | the latest checkpoint's witness is in `trust_roots.witnesses` | card not verified | |
| `card.claims_held` | card | `min` | claims held ≥ `min` | card not verified, or it carries no counts | held / made |
| `card.controller_declared` | card | | the card's key declares a controller | card not verified | |
| `card.controller_trusted` | card | | that controller is in `trust_roots.controllers` | card not verified | |
| `bound.selection_verified` | bound | | the selection verified, inclusion proofs included (`unverifiable` fails) | absent, refused, unanswered | |
| `bound.no_unanswered_dispute` | bound | `window_days` | no dispute with anyone left unanswered in the window | selection not verified | unanswered disputes |
| `own.settled` | own_history | `min` | settled ≥ `min` | own book not read | settled / exchanges |
| `own.held_halves` | own_history | `min` | halves held ≥ `min` | own book not read | halves / exchanges |
| `own.no_conflicting` | own_history | | no CONFLICTING deal | own book not read | conflicting / exchanges |
| `own.no_adverse_adjudication` | own_history | `window_days` | no adverse verdict in the window | own book not read, or no verdict held yet | adverse / verdicts in the window |
| `operator.not_deny_listed` | operator | | not on the deny list | never | |
| `operator.allow_listed` | operator | | on the allow list, or no allow list kept | never | |
| `vouch.distinct_controllers` | vouch | `min` | distinct vouching controllers, the counterparty's own excluded, ≥ `min` | never | distinct / vouches |
| `stake.covers_deal` | stake | | collateral ≥ the deal, in the same band unit | no stake, a stake on a rail `trust_roots.rails` does not pin, or a different unit | |
| `card.band_history_or_stake` | card | `k`, `step_decades`, `max_adverse_permille` | the deal is within the earned band plus `step_decades` decades, or a stake on a pinned rail covers it (§3.1) | no covering stake, and the card is not verified or carries no per-band counts | |
| `card.open_disputes` | card | `max` | open disputes raised about the counterparty ≤ `max` (§3.3) | card not verified, or it carries no dispute tally | open / all received |
| `judged` | judged | | the judge met the row | not judged, or judged by a judge outside `trust_roots.judges` (reported, not counted) | |

**A missing input versus nothing to read.** `not_read` has two causes. The
input can be missing: the card was not received, or the own book was not
read. Or the input was read and held nothing yet, as when our own book holds no
verdict about the counterparty. Only the first is a missing input in §4. A book
that has been read and holds no verdict is `not_read`, but it never invokes the
missing default.

Freshness is measured from the holder's checkpoint, never from when a card
arrived (design §8). Verifying a card or a selection is the caller's job before
it reaches the evaluator: the signature, the witness receipt, that its subject
presented it, and for a selection its inclusion proofs and our nonce (design
§3, §5). Today only `served_summary/1` carries counts. `history_card/1`
carries checkpoints only, so `card.claims_held` reads `not_read` on it.

## 3. The value band and the tier

The band is `(unit, decade)`. The decade is the power of ten of the amount's
leading digit, in the band unit, computed exactly from the decimal digits and
never through a float. 5 sat is decade 0, 1,000,000 msat is 1,000 sat or decade
3, and 0.25 USDC is decade −1.

- An amount must be a plain decimal (`0`, `12.50`): no sign, no exponent, no
  redundant leading zero.
- A zero amount is free and has no band. It sits in the lowest tier.
- The deal's tier is the first tier whose `max_decade` for the band unit holds
  the decade.
- A band above the highest tier that names its unit is `above_tier`. The deal is
  then held to that tier: the baseline names `sat` up to T1 only, so a sat deal
  above T1 is held at T1.
- A currency outside `accept`, or an amount that does not read, is a missing
  input.

### 3.1 The per-band ladder: history or stake

Reference v3 §3A.14 gives a new relationship's limit as
`max(earned band × step-up, collateral on this deal)`. There are two roads
to a band: earned history or posted stake. `card.band_history_or_stake` is
that rule.

- **Card input.** The card's per-band counts. Each count gives a currency
  and a decade, the subjects in that band, and how many of those subjects were
  resolved against the counterparty. A subject is corroborated and
  net-settled (settled − refunded − charged back), and it is banded once,
  after netting. Each band maps through `accept` as an amount does: a decade
  in a currency is that decade plus the currency's `scale` in its band unit.
  Bands that map to one decade of one unit are added together. The added
  subjects stop at 2^53 − 1, and the added adverse subjects never exceed the
  added subjects. A currency outside `accept`, a band in another unit, and a
  count that does not read are not counted. A count does not read when its
  subjects or adverse subjects are negative, its subjects are above 2^53 − 1,
  it has more adverse subjects than subjects, or its decade is outside −1,000
  to 1,000.
- **Earned band.** The highest decade, in the deal's band unit, with at least
  `k` subjects, of which at most `max_adverse_permille` per thousand were
  resolved against the counterparty. A lower band never adds up to a higher
  one: a hundred subjects at decade 0 earn decade 0. Disputes still open are
  not in this share: a pack shows them as their own count beside the ladder,
  with `card.open_disputes` (§3.3).
- **Pass** when the deal's decade is at most the earned band plus
  `step_decades`, where 1 is the 10× step-up. It also passes when a stake on a
  pinned rail covers the deal, whatever the card shows.
- **Fail** when the card's bands were read and neither road holds. An empty
  list of bands was read, so it fails. **not_read** when no stake covers and
  the card is not verified, carries no per-band counts at all (absent, not
  empty), or the deal's band does not read. Both ask, if the row carries an
  `ask`.
- **Effect.** A plain LIMIT row that does not pass lowers the tier admitted to
  the tier below its `from`. A ladder row lowers it only to the highest tier
  its earned limit holds whole: the earned limit holds a tier when every tier
  up to it that names the deal's unit has a ceiling at or below the earned band
  plus the step. It never lowers below the tier below its `from`. History
  earns a tier, not just a pass.

No served card carries per-band counts of corroborated, net-settled subjects
yet (§6), so the baseline has no ladder row. The rule ships with its own
conformance pack,
`conformance-vectors/admission/v0/packs/history-or-stake.yaml` in
capsule-engine.

**From a `standard_history/1` card.** The one served card with per-band
counts is `standard_history/1` (AAC `spec/standard-history-v0.md` §4, §5.3).
capsule-engine's `StandardHistoryCounts` reads a verified card's `bands` into
the card input. The artifact must be the JCS of the card, as that spec's §3
says; bytes that are not exactly the JCS of their own parse are refused, so
every evaluator reads one card one way:

- each band tally gives `subjects = held + did_not_hold` (its decided deals)
  and `adverse = did_not_hold`; its `undecided` deals are left out, and a band
  whose `decade` is `null` (zero-amount deals) is skipped;
- the currency is the card's SR `assetCode` as written and the decade is in
  that asset's own unit, so 250 sat is `BTC` decade −6. A pack that reads these
  cards maps the asset in `accept`, for example `BTC: {band: sat, scale: 8}`.

A ladder filled this way counts decided deals by outcome claim, not
corroborated, net-settled subjects: a `/1` band carries no corroboration split
(`happened` is card-level), no netting, and both roles. It is therefore not
the ladder §3A.14 describes, and the baseline still gets no ladder row from it.
Counting `did_not_hold` as adverse is the conservative direction: the card
does not say which side failed, and counting it against the counterparty can
only lower an earned band, never raise one.

### 3.2 Rails

A rail is trusted by its adapter declaration, named by id plus digest
(AAC#406). A stake carries the pin of the rail it is posted on. A stake counts,
in `stake.covers_deal` and in the ladder's stake road, only when
`trust_roots.rails` holds that exact pin. A stake on any other rail is
`not_read`, never a pass. A pack with no rails therefore counts no stake.

### 3.3 Open disputes beside the ladder

The ladder's adverse share counts deals that were decided against the
counterparty. A dispute still open is not in it. So that leaving a dispute
unresolved cannot make a history look clean, a pack shows open disputes beside
the ladder, and `card.open_disputes` is that count: the open disputes others
raised about the counterparty, out of all disputes they raised, as the card
shows them. From a `standard_history/1` card these are
`disputes.received.by_outcome.open` and `disputes.received.of`. The count is
card-level, across all bands, since `/1` carries no disputes per band. It is a
`card` row, so it records or limits and never decides NO.

## 4. Resolution

In order:

1. **Rows.** Each row whose `from` is at or below the deal's tier is read.
2. **NO.** A failing row with `on_fail: "NO"` decides NO, whatever the deal's
   band.
3. **Missing.** A missing band input decides the pack's `missing` default. So
   does a NO row that reads `not_read` because its input is missing (§2). The
   source is `missing` or that row's id.
4. **Tier admitted.** It starts at the deal's tier. A `LIMIT` row that does not
   pass lowers it to the tier below that row's `from`, and a ladder row lowers
   it only to the tier its earned history holds (§3.1). A failing judged row
   lowers it to its `cap`.
5. **Above the top tier.** If the deal is `above_tier` and no row lowered the
   tier admitted, the decision is LIMIT at that top tier with source
   `above_tier`. If a row did lower it, the deal goes on to steps 6 to 8 like
   any other.
6. **GO.** If the tier admitted holds the deal, the decision is GO.
7. **ASK.** Otherwise, a `LIMIT` row that did not pass and carries an `ask` asks
   for it, if that derivation has not been asked of this counterparty and the
   budget allows. One ask answers every row that needs the same derivation. If
   any ask results, the decision is ASK at the tier admitted.
8. **LIMIT.** Otherwise the decision is LIMIT at the tier admitted. A refused,
   unanswered or pending ask lands here: a refusal limits and never bans.

An outcome the pack does not yield is never produced. The lint refuses rows
that could produce one. Only step 5 could still produce one: a LIMIT above the
top tier in a pack without LIMIT. The `missing` default then decides it, and the
source stays `above_tier`. In a Mesh pack yielding GO and NO only, that default
is NO.

No step sums, weights or ranks rows. There is no score.

## 5. Inputs and the decision

The evaluator's input is the deal and what was received:

- **The deal and the clock:** `now`; the deal's `amount` and `currency`.
- **What was received about the counterparty:**
  - the platform facts;
  - the card, with its state, first and latest checkpoint times, witness,
    declared controller, claims held and made, per-band counts
    `{currency, decade, subjects, adverse}`, and its received disputes
    `{open, of}`;
  - a bound selection, with its state and its unanswered disputes;
  - the party's own book with the counterparty, as counts and adjudications;
  - the operator's list result;
  - verified vouches (by controller) and the counterparty's own controller;
  - any stake posted on the deal, with its rail's pin `{id, digest}`;
  - judged rows' results, each with its judge.
- **Asks:** the asks already made (by derivation, with their state) and the
  number made in the budget window.

The [baseline fixtures](../packs/admission-baseline/fixtures/cases.json) write
inputs in this shape.

The decision is the `admission_decision` block the Mesh capsules plugin
already seals. Its existing names are kept, so loop step 04 reads them as it
does today:

- `verdict`: GO, ASK, LIMIT or NO;
- `source`: the id of the row that decided, `rows` when the rows decided
  together, `above_tier`, or `missing`;
- `reads`: the policy entry, `pack_id` and the SHA-256 of its
  `pack-definition.json`;
- `rows`: each `{row, result}`.

The new members are additive:

- `tier`, which is null on NO and otherwise always set;
- `band`, `{currency, decade}`, null for a free deal or a band that does not
  read;
- `asks`, each `{row, derivation, deadline_s}`;
- each row's `effect` (`none`, `NO`, `LIMIT`, `ASK` or `cap`), with `count` and
  `denominator` where it counts.

The caller seals the block and names the counterparty by its own reference.
The block is about one counterparty, so it is local-only and is never exported
for another party.

## 6. Status and what v0 leaves out

v0. The baseline's numbers are placeholders, calibrated first from the live
stage-1 health report. The fixtures are checked against the evaluator in
capsule-engine's CI. `pack lint` and `pack test` are #56.

Added after the first v0 compile (#79, #87):

- **The per-band ladder** with k and a step-up (§3.1; Reference v3 §3A.14,
  item 26). The evaluator reads it. No served card carries per-band counts of
  corroborated, net-settled subjects yet, so the baseline does not use it, and
  its k, step-up and adverse share have no calibrated value.
- **Rails in `trust_roots`** (§3.2), pinned by adapter declaration id plus
  digest (AAC#406).
- **The ladder from a `standard_history/1` card** (§3.1) and
  `card.open_disputes` (§3.3), from #87.

All are additive within `admission-pack/v0`. An evaluator from before them
refuses a pack that uses them, as an unknown predicate or field, so it fails
closed. A pack that uses none of them compiles to the same bytes as before, but
one meaning changes, in the fail-closed direction: a pack written before
rails that has a `stake.covers_deal` row pins no rail, so every stake it reads
is now `not_read` where a covering one used to pass.
