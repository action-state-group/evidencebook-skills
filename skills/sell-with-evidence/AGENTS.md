---
name: sell-with-evidence
description: Sell for a person to buyers who ask for evidence. Publishes one signed commitment with a stapled History card, answers evidence requests from the seller's own records, sells only at exactly the listed price with every listed term matching, records the sale and shows the seller's own History card and receipt. Use when a seller wants buyers' agents to find them and check their record before buying.
---
# Sell with evidence

> **Demo host, step A.** This skill runs today only on the ARD two-seller demo's host, whose steps
> are that demo's own tools and its seller process (the host table at the end). On a capsule host
> the same steps are `capsulectl` verbs, some of which do not exist yet (design note
> `docs/design/ard-buyer-seller-skills.md`, §3.6). Do not copy the demo host's tools into another host.

A seller wants buyers' agents to find them and check their record. You publish what they say
about themselves, answer buyers' evidence requests from the seller's own records, and record each
sale in those records.

## What you are given

- **The listing:** item, price and terms (currency, rail, refund terms).
- **The carriers** to submit the commitment and the listing to (an ARD entry on the seller's own
  `/.well-known/ard.json` is one).
- **The share setting:** sharing is on by default, with a notice at setup and a one-flag opt-out.

## The procedure

1. **Draft one signed commitment** with the seller's History card stapled to it, and, only after
   the seller says yes, submit it and the listing to the carriers the seller names. The seller owns
   its commitment; it never hosts or runs a catalogue or a registry. Say whether the commitment is
   witnessed.
2. **Answer evidence requests** that arrive over the commitment's route, from the seller's own
   records only, and only what the commitment advertises. Give the full history only behind a
   signed ask. Honour the seller's share setting.
3. **Sell only on the listing's terms:** at exactly the listed price, and only when every term
   matches the listing (item, currency, rail, refund terms), not the price alone. Open the deal
   under the buyer's deal id, check the buyer's records, record the sale, and take the next
   checkpoint so the card counts it. Never pay out.
4. **On the receipt, say what the records hold and do not hold.** On a real payment rail, what the
   seller's wallet was credited is not in these records: its wallet provider may deduct a
   receiving fee.

## Rules

- Speak for this seller only, from its own records. Never speak for the buyer's records.
- Never put the outcome note record in anything shared with the buyer. A count from it travels only with
  its label.
- Use only the tools of your own extension: no terminal, no file tools, no session or agent
  listing, no tool search except to load your own tools.

## Host table

| Step | On the demo host (step A) | On a capsule host |
|---|---|---|
| 1 Commitment and listing | done by the demo operator in advance, served from the seller's own origin | a publish verb (capsule-cli#571) |
| 2 Answer evidence requests | done by the demo's seller process | `respond` over the mailbox (capsule-cli#573) |
| 3 Take and record the sale | done by the demo's seller process | `deal sale new`, `deal open --sale --deal-id`, `deal check` with `"action":"commit"` |
| Show what happened | `ard_seller_activity` | `deal` and `book` views |
| Show the History card | `ard_show_card` | `book` card |
| Show the receipt | `ard_show_receipt` | `deal` receipt |

## On the demo host

- The seller process runs fixed demo rules, not all of the rules above: it answers the requests
  its commitment advertises and takes a deal only at exactly the listed price; this demo checks the
  price, not the other terms. This window shows what it did. Call the one tool the person asks
  for, then say in at most two short plain sentences what it showed. Do not repeat its output: the
  audience reads it in the tool call.
- The demo's seller is a fixed demo merchant: the demo operator published its commitment and
  listing in advance, without a yes from the seller, and the demo seller shares by default with no
  setup notice or opt-out.
- The demo's tools do not report whether a commitment is witnessed; do not say either way.
- On the demo, a seller's "did not hold" deals are counted from its own note (a temporary record), set
  up by the demo operator: say so, and never present them as confirmed by the buyer or a ruling.
