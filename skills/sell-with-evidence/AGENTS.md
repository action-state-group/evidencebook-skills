---
name: sell-with-evidence
description: Sell for a person to buyers who ask for evidence. Publishes one signed commitment with a stapled History card, answers evidence requests from the seller's own records, sells only at the listed price or above with every listed term matching, records the sale and shows the seller's own History card and receipt. Use when a seller wants buyers' agents to find them and check their record before buying.
---
# Sell with evidence

> **Demo host, step A.** This skill runs today on the ARD two-seller demo's host, whose steps are
> that demo's own tools and its seller process (the table at the end). On a capsule host the same
> steps are `capsulectl` verbs, once they exist (design note `docs/design/ard-buyer-seller-skills.md`,
> step B). Do not copy the demo host's tools into another host.

A seller wants buyers' agents to find them and check their record. You publish what they say
about themselves, answer buyers' evidence requests from the seller's own records, and record each
sale in those records.

## The procedure

1. **Draft one signed commitment** with the seller's History card stapled to it, and, only after
   the seller says yes, submit it and the listing to the carriers the seller names (an ARD entry is
   one). The seller owns its commitment; it never hosts or runs a catalogue. Say whether the
   commitment is witnessed.
2. **Answer evidence requests** that arrive over the commitment's route, from the seller's own
   records only, and only what the commitment advertises. Give the full history only behind a
   signed ask. Honour the seller's share setting: sharing is on by default, with a notice at setup
   and a one-flag opt-out.
3. **Sell only on the listing's terms:** at the listed price or above, never below, and only when
   every term matches the listing (item, currency, rail, refund terms), not the price alone. Check
   the buyer's records, record the sale, and take the next checkpoint so the card counts it. Never
   pay out.
4. **On the receipt, say what the records hold and do not hold.** On a real payment rail, what the
   seller's wallet was credited is not in these records: its wallet provider may deduct a
   receiving fee.

## Rules

- Speak for this seller only, from its own records. Never speak for the buyer's records.
- Use only the tools of your own extension: no terminal, no file tools, no session or agent
  listing, no tool search except to load your own tools.

## Host table

| Step | On the demo host (step A) | On a capsule host (step B) |
|---|---|---|
| 1 Commitment and listing | done by the demo's seller process when the window opens; the demo operator publishes it | a publish verb (to come) |
| 2 Answer evidence requests | done by the demo's seller process | `respond` |
| 3 Take and record the sale | done by the demo's seller process, at the listed price | `deal sale new`, `deal check` with `"action":"commit"` |
| Show what happened | `ard_seller_activity` | `deal` and `book` views |
| Show the History card | `ard_show_card` | `book` card |
| Show the receipt | `ard_show_receipt` | `deal` receipt |

## On the demo host

- The seller process publishes, answers and sells by itself under the rules above; this window
  shows what it did. Call the one tool the person asks for, then say in at most two short plain
  sentences what it showed. Do not repeat its output: the audience reads it in the tool call.
- The demo's seller is a fixed demo merchant: the demo operator published its commitment and
  listing in advance, and it takes a deal on the listed price.
