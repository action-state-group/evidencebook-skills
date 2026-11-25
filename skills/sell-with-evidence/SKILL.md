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
- Never predict, guess or argue how a dispute will be ruled, for or against this seller. Say only what the records
  show and what the adjudicator has recorded.
- Never call the witness independent: Action State runs the witness and every party here. Say "time-stamped by
  Action State's witness", with no claim about its independence.
- Use only the tools of your own extension: no terminal, no file tools, no session or agent
  listing, no tool search except to load your own tools.

## Host table

| Step | On the demo host (step A) | On a capsule host |
|---|---|---|
| 1 Commitment and listing | done by the demo operator in advance, served from the seller's own origin | a publish verb (capsule-cli#571) |
| 2 Share the History card | done by the demo's seller process: its shared `standard_history/3` card, as of each checkpoint | `deal standard-history card --shared`, or `respond` over the mailbox (capsule-cli#573) |
| 3 Take and record the sale | done by the demo's seller process | `deal receive`, `deal admit`, `deal agree`, `deal check` with `"action":"commit"`, `deal perform` |
| 4 Answer a dispute and enter a ruling | done by the demo's seller process: its full answer to the adjudicator's request, the ruling entered in its own records | `deal respond` to the adjudicator's request, `deal receive` the ruling |
| Show what happened | `ard_seller_activity` | `deal` and `book` views |
| Show the History card | `ard_show_card`, `ard_open_card_page` (as a page) | `book` card |
| Show the receipt | `ard_show_receipt`, `ard_open_receipt_page` (as a page) | `deal` receipt |

## On the demo host

- Never say "demo" to the person: the lines below are for you, not to repeat.
- The seller process runs fixed demo rules, not all of the rules above: it shares its card and takes a deal only at
  exactly the listed price; it checks the price, not the other terms. Here Kestrel Print ships 150 of
  the 200 badges, and its own delivery record says so. This window shows what it did. Call the one tool the person asks
  for, then say in at most two short plain sentences what it showed. Do not repeat its output: the
  audience reads it in the tool call.
- The demo's seller is a fixed demo merchant: the demo operator published its commitment and
  listing in advance, from the seller's file (`demo/ard/sellers/<name>.yaml`) but without a yes from the seller, and
  the demo seller shares by default with no setup notice or opt-out.
- The card is time-stamped by Action State's witness, which also runs every party here, so it is not
  independent of them: say so when you speak of it.
- To show a History card as a page, call `ard_open_card_page`: it opens the page in the browser on the
  presenter's screen, and that is all the page needs. Never copy, move or link the page's file.
- To show the receipt as a page, call `ard_open_receipt_page` after the deal has closed. It opens the
  page the same way; if it says the deal is not closed yet, say so and do not retry in the same turn.
- A buyer may dispute a delivery. When the deal's adjudicator, which the operator runs, asks for this seller's books,
  the seller process answers in full, and it enters any ruling in this seller's own records. Say what the ruling found in its
  own words ("ruled against this seller on the delivery"), never that the seller was dishonest or failed.
