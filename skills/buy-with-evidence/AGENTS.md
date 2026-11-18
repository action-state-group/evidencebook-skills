---
name: buy-with-evidence
description: Buy something for a person from sellers who answer evidence requests. Finds sellers, checks each seller's signed commitment, asks for and verifies its History card, assesses each seller with the person's admission pack, recommends without picking, and pays only on the person's own yes. Use when a person asks their agent to buy from a seller they do not know yet ("find me 200 badges under 300 msat", "who should I buy from").
---
# Buy with evidence

> **Demo host, step A.** This skill runs today on the ARD two-seller demo's host, whose steps are
> that demo's own tools (the table at the end). On a capsule host the same steps are `capsulectl`
> verbs, once they exist (design note `docs/design/ard-buyer-seller-skills.md`, step B). Do not copy
> the demo host's tools into another host.

A person asks you to buy something. You find sellers, check what each says about itself, read
each one's History card, assess each one with the person's admission pack, and tell the person
what you found. The person picks. You pay only when the person says yes to that payment.

Speak in the person's words. Say "assessment", never "score" or "rank". A seller's history is
shown, never scored.

## The procedure

1. **Take the ask.** What, by when, and the most the person will pay, in their own words.
2. **Find sellers** in the catalogue the person names. Check each seller's signed commitment:
   its signature, that its key is the entry's, that its digest matches. A seller whose commitment
   fails is shown as failed and is never assessed. Keep two things apart when you tell the person:
   the catalogue entry's offer (item and price) is the catalogue's and is not signed; the signed
   commitment says how to ask the seller for evidence and under which key. Matching keys show only
   that the entry and the commitment agree. A commitment with no witness is "unwitnessed": say so.
3. **Ask each seller for its History card** over the route its commitment names, and verify the
   answer. Ask for anything more (its full history, its selection) only behind a signed ask.
4. **Assess each seller** with the person's admission pack (the demo uses its own pack,
   `packs/ard-demo-buyer`). The person may tighten a threshold; the pack is then recompiled, never
   edited by you in words. Show each verdict with its deciding rows, in plain words.
5. **Recommend; the person picks.** What a pick may lead to follows that seller's verdict:
   - **GO**: the deal may go ahead.
   - **ASK**: the pack asks the seller for the evidence it names, and you assess again on the answer.
   - **LIMIT**: the pack admits this seller only up to a lower amount. Tell the person that amount,
     and offer it or another seller.
   - **NO**: stop.

   A pick the verdict does not allow pays nothing.
6. **Pay only on the person's yes.** Before paying, ask the person once, naming the seller, the
   amount, and whether real money moves. Pay only after their yes in their next message, only to
   the seller they named. That yes is the person's approval; where the host cannot carry the
   person's own key signature, say so rather than present it as signed.
7. **After paying**, show the receipt and the person's updated History card, each from the
   person's own records. Say what the records hold and nothing they do not.

## Rules

- Never pick for the person. Never pay without their yes to that payment, in a message after
  your question.
- If a step answers REFUSED, say so in one sentence and do not retry it on your own. If the person
  asks again, start again from your question before paying.
- Use only the tools of your own extension: no terminal, no file tools, no session or agent
  listing, no tool search except to load your own tools.

## Host table

| Step | On the demo host (step A): this demo host's tools | On a capsule host (step B) |
|---|---|---|
| 2 Find sellers, check commitments | `ard_find_sellers` | `capsulectl commitment find` |
| 3 History cards | `ard_show_history` | `request` / `respond` |
| 4 Assess | `ard_assess` (and the threshold edit it takes) | `capsule-engine admission evaluate` |
| 5 Record the pick | `ard_pick` | `deal note --kind intent` |
| 6 Pay | `ard_pay`: the presenter's approval dialog, then the demo rail | `deal check` with `"action":"pay"` and its `approval_text`, then the payment |
| 7 Receipt and card | `ard_show_receipt`, `ard_show_card` | `deal` receipt, `book` card |

`deal check` and `approval_text` belong to the capsule-host column only: the demo host's check
before paying is its own approval dialog.

## On the demo host

- Call one tool per message from the person, and only the one they ask for. After it returns,
  say in at most two short plain sentences what it showed. Do not repeat its output: the audience
  reads it in the tool call.
- `ard_pick` seals the pick. Never call `ard_pay` in the same message as `ard_pick`.
- Before `ard_pay`, stop and ask the person to confirm in one sentence that names the seller and
  the amount and says whether real money moves (the recipe says which rail this run uses).
- `ard_pay` opens an approval dialog on the presenter's screen; you cannot see or answer it. Only
  its Pay button releases money.
- The demo's seller sets its price in its catalogue entry; the demo host opens a deal only on GO.
