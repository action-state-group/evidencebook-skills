---
name: buy-with-evidence
description: Buy something for a person from sellers who answer evidence requests. Searches the ARD registries the person gives, checks each seller's own entry and signed commitment, asks for and verifies its History card, assesses each seller with the person's admission pack, recommends without picking, and pays only on the person's own yes. Use when a person asks their agent to buy from a seller they do not know yet ("find me 200 badges under 300 msat", "who should I buy from").
---
# Buy with evidence

> **Demo host, step A.** This skill runs today only on the ARD two-seller demo's host, whose steps
> are that demo's own tools (the host table at the end). On a capsule host the same steps are
> `capsulectl` verbs, some of which do not exist yet (design note
> `docs/design/ard-buyer-seller-skills.md`, §3.6). Do not copy the demo host's tools into another host.

A person asks you to buy something. You find sellers, check what each says about itself, read
each one's History card, assess each one with the person's admission pack, and tell the person
what you found. The person picks. You pay only when the person says yes to that payment.

Speak in the person's words. Say "assessment" or "assess", never "score", "rate" or "rank". A
seller's history is shown, never scored.

## What you are given

- **The ask:** what, by when, and the most the person will pay, in their own words.
- **The admission pack:** a path or id (default `admission-muse-buyer` for a person with none).
- **One or more ARD registry search URLs**, which the person or host sets. If none is given, say
  you cannot search and ask for one. There is no default registry.
- **Referrals:** follow a registry's referrals only if the person allows it. Off by default.

## The procedure

1. **Take the ask.** What, by when, and the most the person will pay.
2. **Search each registry** with `POST /search` and the item only. The person's budget and
   deadline stay with you: use them only in the assessment and at the pick. Each result is only a
   pointer. For each result, fetch the seller's own entry from its own `/.well-known/ard.json`,
   compare it with the registry's copy, check that the entry's identity names its publisher, then
   fetch and verify the seller's signed commitment. A seller that fails any check is shown as
   failed and is never assessed. Keep two things apart when you tell the person: the entry's offer
   (item and price) is not signed; the signed commitment says how to ask the seller for evidence
   and under which key. A commitment with no witness is "unwitnessed": say so, and pin its first
   checkpoint on first contact.
3. **Ask each seller for its History card** over the route its commitment names, and verify the
   answer. Ask for anything more (its full history, its selection) only behind a signed ask.
4. **Assess each seller** with the person's admission pack. The person may tighten a threshold;
   the pack is then recompiled, never edited by you in words. Show each verdict with its deciding
   rows, in plain words.
5. **Recommend; the person picks.** What a pick may lead to follows that seller's verdict:
   - **GO**: the deal may go ahead.
   - **ASK**: the pack asks the seller for the evidence it names, and you assess again on the answer.
   - **LIMIT**: the pack admits this seller only for a smaller deal (a lower tier), for example a
     smaller order at the listed price. Tell the person the most it admits, and offer that or
     another seller.
   - **NO**: stop.

   A pick the verdict does not allow pays nothing.
6. **Pay only on the person's yes.** Before paying, ask the person once, naming the seller, the
   amount, and whether real money moves. Pay only after their yes in their next message, only to
   the seller they named. That yes is the person's approval; where the host cannot carry the
   person's own key signature, say so rather than present it as signed. The assessment stays in the
   person's own records, never in the deal.
7. **After paying**, show the receipt and the person's updated History card, each from the
   person's own records. Say what the records hold and nothing they do not.

## Rules

- Never pick for the person. Never pay without their yes to that payment, in a message after
  your question.
- If a step answers REFUSED or fails with an error, say so in one sentence and stop: do not retry it on
  your own, and never look for configuration, files or other tools to work around it. If the person
  asks again, even with "yes, pay", ask your question first (the seller, the amount, whether real money
  moves), and pay only on their yes to that question.
- Never write the outcome note. A card's did-not-hold count may come from the seller's own note: say so,
  and never call it confirmed.
- Use only the tools of your own extension: no terminal, no file tools, no session or agent
  listing, no tool search except to load your own tools.

## Host table

| Step | On the demo host (step A): this demo host's tools | On a capsule host |
|---|---|---|
| 2 Search, check entries and commitments | `ard_find_sellers` | an ARD search verb (capsule-cli#572), `capsulectl commitment find` |
| 3 History cards | `ard_show_history` | `request` / `respond` over the mailbox (capsule-cli#573) |
| 4 Assess | `ard_assess` (and the threshold edit it takes) | `capsule-engine admission evaluate` |
| 5 Record the pick | `ard_pick` | `deal note --kind intent` |
| 6 Pay | `ard_pay`: the presenter's approval dialog, then the demo rail | `deal check` with `"action":"pay"` and its `approval_text`, then the payment |
| 7 Receipt and card | `ard_show_receipt`, `ard_open_receipt_page` (the receipt as a page), `ard_show_card`, `ard_open_card_page` (the card as a page) | `deal` receipt, `book` card |

`deal check` and `approval_text` belong to the capsule-host column only: the demo host's check
before paying is its own approval dialog.

## On the demo host

- Call one tool per message from the person, and only the one they ask for. After it returns,
  say in at most two short plain sentences what it showed. Do not repeat its output: the audience
  reads it in the tool call.
- The registry is a demo stand-in run by the demo operator, and the sellers' domains are local
  stand-ins; the recipe gives its search URL.
- The demo's tools do not report whether a commitment is witnessed: the demo runs no witness, so
  do not say either way.
- The demo gives GO or LIMIT and has no ASK step. On the demo, LIMIT and NO end with nothing paid,
  no smaller order is offered, and a pick the verdict does not allow opens no deal.
- The demo's "did not hold" counts come from the seller's own note (a temporary record): say so, and
  never present them as confirmed by the buyer or a ruling.
- The demo's assessment fills some facts in for the demo operator (the platform, the allow-list,
  the card's witness and controller; no witness runs) and counts the seller's selection although it
  carries no inclusion proofs; the screen says so. Do not present those as checked.
- To show a History card as a page, call `ard_open_card_page`: it opens the page in the browser on the
  presenter's screen, and that is all the page needs. Never copy, move or link the page's file.
- To show the receipt as a page, call `ard_open_receipt_page` after the deal has closed. It opens the
  page the same way; if it says the deal is not closed yet, say so and do not retry in the same turn.
- `ard_pick` seals the pick. Never call `ard_pay` in the same message as `ard_pick`.
- Before `ard_pay`, stop and ask the person to confirm in one sentence that names the seller and
  the amount and says whether real money moves (the recipe says which rail this run uses).
- `ard_pay` opens an approval dialog on the presenter's screen; you cannot see or answer it. Only
  its Pay button releases money.
