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
`scripts/pack_compile.py validate`) and compiles it to an Evidence Contract. It
does not evaluate one.

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
| `source` | optional provenance text |
| `outcomes` | the outcomes this pack yields. It must include GO. A Mesh pack under Steven's 10-29 ruling (u137) names `["GO", "NO"]` only |
| `missing` | what a missing input gives: `LIMIT` (at the lowest tier) or `NO`, and never GO. It must be in `outcomes` |
| `accept` | the mapping table: each accepted currency's band unit and scale, `{band, scale}`. An amount in that currency times `10^scale` is the amount in the band unit, so `msat: {band: sat, scale: -3}`. Nothing converts across units |
| `tiers` | the ladder, lowest first: `{id, max_decade: {<band unit>: <decade>}}`. Ceilings rise from tier to tier |
| `budget` | `{max_asks}`: the asks a counterparty may get in the caller's budget window |
| `rows` | the rows, below |

No other field is read, and an unknown field is refused. A pack has no weight,
score or other place a ranking could hide.

Outcome names are written quoted (`"NO"`). YAML 1.1 readers, PyYAML among them,
read a plain `NO` as the boolean false. The lint here refuses an outcome that
reads as a boolean, and the evaluator refuses any plain scalar that YAML 1.1
and YAML 1.2 read differently.

### Rows

| Field | Meaning |
|---|---|
| `id` | lowercase letters, digits, `-` or `_`; unique |
| `statement` | what the row checks, in words |
| `source` | where its input comes from: `platform`, `card`, `own_history`, `operator`, `vouch`, `stake` or `judged` (design §3) |
| `check` | the evaluator predicate, from the list in §2 |
| `params` | the predicate's thresholds, as integers |
| `from` | the lowest tier the row applies to |
| `on_fail` | `"NO"`, `"LIMIT"` or `"record"`. A judged row's is `{cap: <tier>}` |
| `ask` | optional `{derivation}`: the Evidence Request a failing or unread row asks for |

`record` means the row is read and sealed with the decision but decides nothing.
The Mesh base rows work this way.

### What the lint refuses

- An `on_fail: "NO"` on a `card`, `vouch`, `stake` or `judged` row. NO comes only
  from platform facts, the party's own adjudicated history, or the operator's own
  config (Steven, 10-29: u126 and u137).
- A judged row whose `on_fail` is anything but `{cap}`. A judged row caps a tier
  and never decides NO (D-23).
- `missing: GO`.
- `on_fail: "LIMIT"` on a row from the lowest tier. The lowest tier is the floor,
  with nothing below it to limit to.
- An `on_fail` or `ask` whose outcome the pack does not yield.
- An unknown predicate, a predicate under the wrong source, a missing or unknown
  param, a `from` or `cap` that names no tier, or ceilings that do not rise.

## 2. Predicates

Each predicate reads `pass`, `fail` or `not_read`. A row that counts also
records its count and denominator.

| `check` | Source | Params | Pass when | `not_read` when | Count / denominator |
|---|---|---|---|---|---|
| `platform.attestation_not_invalid` | platform | | release attestation is not `invalid` | unknown | |
| `platform.owner_signed` | platform | | the owner signed | unknown | |
| `card.verified` | card | | the card verified (`unverifiable` fails) | absent, refused, unanswered | |
| `card.fresh` | card | `max_age_s` | latest checkpoint at most `max_age_s` old, and not after now | card not verified | |
| `card.key_age` | card | `min_days` | first checkpoint at least `min_days` old | card not verified | |
| `own.settled` | own_history | `min` | settled ≥ `min` | own book not read | settled / exchanges |
| `own.held_halves` | own_history | `min` | halves held ≥ `min` | own book not read | halves / exchanges |
| `own.no_conflicting` | own_history | | no CONFLICTING deal | own book not read | conflicting / exchanges |
| `own.no_adverse_adjudication` | own_history | `window_days` | no adverse verdict in the window | own book not read, or no verdict held yet | adverse / verdicts in the window |
| `operator.not_deny_listed` | operator | | not on the deny list | never | |
| `operator.allow_listed` | operator | | on the allow list, or no allow list kept | never | |
| `vouch.distinct_controllers` | vouch | `min` | distinct vouching controllers, the counterparty's own excluded, ≥ `min` | never | distinct / vouches |
| `stake.covers_deal` | stake | | collateral ≥ the deal, in the same band unit | no stake, or a different unit | |
| `judged` | judged | | the judge met the row | not judged | |

Freshness is measured from the holder's checkpoint, never from when a card
arrived (design §8). Verifying a card is the caller's job before it reaches the
evaluator: its signature, the witness receipt on its checkpoint, and that its
subject presented it (design §3, §5).

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
- A band above every tier is `above_tier`.
- A currency outside `accept`, or an amount that does not read, is a missing
  input.

## 4. Resolution

1. **Rows.** Each row whose `from` is at or below the deal's tier is read.
2. **NO.** A failing row with `on_fail: "NO"` decides NO. If such a row instead
   reads `not_read` because its input is missing, the pack's `missing` default
   decides. A missing band input does the same.
3. **Tier admitted.** It starts at the deal's tier. A `LIMIT` row that does not
   pass lowers it to the tier below that row's `from`. A failing judged row
   lowers it to its `cap`.
4. **Above the top tier.** The decision is LIMIT at the top tier, with source
   `above_tier`, never NO. The exception is an operator row that decides NO
   first.
5. **GO.** If the tier admitted holds the deal, the decision is GO.
6. **ASK.** Otherwise, a `LIMIT` row that did not pass and carries an `ask` asks
   for it, if that derivation has not been asked of this counterparty and the
   budget allows. One ask answers every row that needs the same derivation. If
   any ask results, the decision is ASK at the tier admitted.
7. **LIMIT.** Otherwise the decision is LIMIT at the tier admitted. A refused,
   unanswered or pending ask lands here: a refusal limits and never bans.

An outcome the pack does not yield is never produced. The lint refuses rows that
could produce one. Where only the resolution could, above the top tier, the
`missing` default decides. A Mesh pack that yields GO and NO only therefore
refuses a deal above its top tier as missing.

No step sums, weights or ranks rows. There is no score.

## 5. Inputs and the decision

The evaluator's input is the deal and what was received:

- **The deal and the clock:** `now`; the deal's `amount` and `currency`.
- **What was received about the counterparty:**
  - the platform facts;
  - the card, with its state and its first and latest checkpoint times;
  - the party's own book with the counterparty, as counts and adjudications;
  - the operator's list result;
  - verified vouches (by controller) and the counterparty's own controller;
  - any stake posted on the deal;
  - judged rows' results.
- **Asks:** the asks already made (by derivation, with their state) and the
  number made in the budget window.

The [baseline fixtures](../packs/admission-baseline/fixtures/cases.json) write
inputs in this shape.

The decision is the `admission_decision` block the Mesh capsules plugin
already seals. Its existing names are kept, so loop step 04 reads them as it
does today:

- `verdict`: GO, ASK, LIMIT or NO;
- `source`: the deciding row's id, `rows`, `above_tier` or `missing`;
- `reads`: the policy entry, `pack_id` and its digest;
- `rows`: each `{row, result}`.

The new members are additive: `tier`, `band`, `asks` (each
`{row, derivation}`), and each row's `effect` with `count` and `denominator`
where it counts. The caller seals the block and names the counterparty by its
own reference. The block is about one counterparty, so it is local-only and is
never exported for another party.

## 6. Status

v0. The baseline's numbers are placeholders, calibrated first from the live
stage-1 health report. The fixtures are checked against the evaluator in
capsule-engine's CI. `pack lint` and `pack test` are #56.
