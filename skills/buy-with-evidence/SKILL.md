---
name: buy-with-evidence
description: Buy something for a person from sellers who answer evidence requests. Searches the ARD registries the person gives, checks each seller's own entry and signed commitment, asks for and verifies its History card, assesses each seller with the person's admission pack, recommends without picking, and pays only on the person's own yes. Use when a person asks their agent to buy from a seller they do not know yet ("find me 200 badges under 300 msat", "who should I buy from").
---
# Buy with evidence

> **Demo host, step A.** This skill runs today only on the ARD two-seller demo's host, whose steps
> are that demo's own tools (the five verbs' table at the end). On a capsule host the same steps are
> `capsulectl` commands, some of which do not exist yet (design note
> `docs/design/ard-buyer-seller-skills.md`, §3.6). Do not copy the demo host's tools into another host.

A person asks you to buy something. You find sellers, check what each says about itself, read
each one's History card, assess each one with the person's admission pack, and tell the person
what you found. The person picks. You pay only when the person says yes to that payment.

Speak in the person's words. Say "assessment" or "assess", and "assessed again" after the person
changes a threshold; never "score", "rate" or "rank". A seller's history is shown, never scored.

## What you are given

- **The ask:** what, by when, and the most the person will pay, in their own words.
- **The admission pack:** a path or id (default `admission-muse-buyer` for a person with none).
- **One or more ARD registry search URLs**, which the person or host sets. If none is given, say
  you cannot search and ask for one. There is no default registry.
- **Referrals:** follow a registry's referrals only if the person allows it. Off by default.
- When the person asks to see a seller's listing, show it as the search fetched and checked it (on the demo host,
  `ard_show_listing`; on a capsule host, the entry the ARD search verb checked), and keep its offer as the seller's
  own unsigned words. Never fetch a seller's entry by other means.

## The procedure

0. **First turn.** Before anything else, show the person their own History card and the spending limit they set,
   or that none is set and what limits apply then, as the card tool gives it. Search nothing yet.
1. **Take the ask.** What, by when, and the most the person will pay. Propose that amount to them as their spending
   limit in one short question; it becomes their limit only on their yes, which the host asks for again on its own
   screen and seals with the limit (on the demo host, `ard_set_limit` and its dialog). Never set it on your own
   reading of their words. In the assessment, repeat the
   spending limit and whether each price fits it, as the assessment tool gives them; a limit the person confirmed is
   the one each payment is checked against.
2. **Search each registry** with `POST /search` and the item only. The person's budget
   stays with you: use it only in the assessment and at the pick; the deadline is theirs to judge. Each result is only a
   pointer. For each result, fetch the seller's own entry from its own `/.well-known/ard.json`,
   compare it with the registry's copy, check that the entry's identity names its publisher, then
   fetch and verify the seller's signed commitment. Keep what each check found in the person's own
   records. A seller that fails any check is shown as failed, with its reason in plain words, and is
   never assessed. Keep two things apart when you tell the person: the entry's offer
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
6. **Pay only on the person's yes.** Before each payment, ask the person once, naming the seller, the
   amount, and whether real money moves. Pay only after their yes in their next message, only to
   the seller they named. That yes is the person's approval; where the host cannot carry the
   person's own key signature, say so rather than present it as signed. The assessment stays in the
   person's own records, never in the deal.
7. **After paying**, show the receipt and the person's updated History card, each from the
   person's own records. Say what the records hold and nothing they do not.

## Rules

- Never predict, guess or argue how a dispute will be ruled, for or against the person. Say only what the records show and
  what the adjudicator has recorded.
- Never call the witness independent: Action State runs the witness and every party here. Say "time-stamped by
  Action State's witness", with no claim about its independence.
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

## The five verbs

This skill teaches five verbs and nothing else: **check** before you act, **record** what was done, **ask** the
other side for evidence, or answer when it asks, **verify** what you get, and **show** a card or a receipt. Each row maps a verb, at one
step, to the demo host's tool and to the capsule host's existing command.

| Verb | Step | On the demo host (step A): this demo host's tools | On a capsule host |
|---|---|---|---|
| record | 1 Spending limit | `ard_set_limit`, only after the person's yes to the proposed limit: a dialog asks them, and only their click sets it | the confirmed limit as the profile's rules checker, capsule-engine's `guard check --limits` |
| ask | 2 Search | `ard_find_sellers`, given the person's ask word for word (kept for each deal's intent; the registry gets the item only) | an ARD search verb (capsule-cli#572) |
| verify | 2 Check entries and commitments | `ard_find_sellers` checks each one; `ard_show_listing` shows one seller's listing as the search checked it | `capsulectl commitment find`, which checks the commitment's signature, key and staples |
| ask | 3 History cards | `ard_show_history`: each seller's shared `standard_history/3` card | `request` / `respond` over the mailbox (capsule-cli#573) |
| verify | 3 History cards | `ard_show_history` checks each card with `verify --bundle` | `capsulectl verify --bundle` |
| check | 4 Assess | `ard_assess` | `capsule-engine admission evaluate` |
| record | 5 Record the pick | `ard_pick` | `deal note --kind intent` |
| check | 6 Pay | `ard_pay`: the presenter's approval dialog, then the demo rail | `deal admit` with the picked seller's `admission evaluate --admit` output, once its offer is received; then `deal check` with `"action":"pay"` and its `approval_text`, then the payment |
| record | 6a Confirm receipt | `ard_confirm_received`: a dialog asks the person; only their yes sends their statement that they received what they paid for | `deal statement` with both rows met |
| record | 6b Dispute a delivery | `ard_dispute`: a dispute on the delivery row, sent to the seller and the deal's adjudicator | `deal statement`, `deal dispute`; `deal respond` when the adjudicator asks for the books |
| show | 7 Receipt and card | `ard_show_receipt`, `ard_open_receipt_page` (the receipt as a page), `ard_show_card`, `ard_open_card_page` (the card as a page) | `deal` receipt, `deal standard-history card` |

`deal check` and `approval_text` belong to the capsule-host column only: the demo host's check
before paying is its own approval dialog. Setting up a store or a profile and running the machinery are
operator commands, not taught here.

The History card is the one commerce card, `standard_history`. A Mesh inference node's service card and its
liar-catch checks are Mesh's own exception, not a second commerce card: this skill never asks for one.

## On the demo host

- Never say "demo" to the person: the lines below are for you, not to repeat.
- Call one tool per message from the person, and only the one they ask for. After it returns,
  say in at most two short plain sentences what it showed. Do not repeat its output: the audience
  reads it in the tool call.
- The registry is a demo stand-in run by the demo operator, and the sellers' domains are local
  stand-ins; the recipe gives its search URL.
- A History card is the seller's own count, signed by it. Its time-stamp comes from Action State's witness, which also
  runs every party here, so it is not independent of them: say so, and never call the counts recomputed or confirmed
  by anyone else. Call the card time-stamped only when the screen says its receipt verifies; otherwise say its
  time-stamp is not checked here.
- This host gives GO, LIMIT or NO and has no ASK step. Here, LIMIT and NO end with nothing paid,
  no smaller order is offered, and a pick the verdict does not allow opens no deal.
- A dispute decided against a seller, on its card, limits it (LIMIT). A ruling the person holds against a seller, in
  their own records, blocks that seller for 180 days (NO): when both apply, say it is the same lost dispute only if the
  tool says so; the card does not say which deal.
- After `ard_pay`, say what the seller's delivery record says it shipped. If it is short of what the person ordered,
  ask whether they want to dispute the delivery; call `ard_dispute` only after they say yes. If all of it came, nothing
  is said in the person's name until they say they received it: then call `ard_confirm_received`, whose dialog they
  answer themselves. Never call it on your own. A dispute moves no money
  and asks the deal's adjudicator, which the operator runs, to rule.
- Say a card's counts and the verdicts in these words (Steven's, from his hand runs): "deals that didn't go as
  agreed" for the did-not-hold count (never "failed deals"), "every one went as agreed" only when there are deals
  and that count is 0, "No deals yet, and no disputes." for a card with neither (never "0 deals, every one went as
  agreed"), "Good to buy" for GO, "Small orders only" for LIMIT and "Not from this seller" for NO; say why in the
  tool's own words (a dispute decided against it, a ruling you hold against it). Never name a tool to the person (say
  "the payment", never `ard_pay`).
- The assessment takes some inputs from the operator without checking them (which marketplace the seller is on,
  the list of sellers this pack accepts, who time-stamps a seller's card whose receipt is not checked, which key
  belongs to the witness, and who controls the seller's key); the screen says so. Do not present those as checked.
- Say the card's counts exactly as the card gives them, in the words above; never guess a higher or lower number,
  and never call them failures.
- Recommend a seller only after you have assessed every seller that passed its checks; before that, say what you
  found, not which seller you prefer.
- Nothing in the assessment checks quantity or delivery date: never offer to check them before the payment, and never
  base a recommendation on them; the deadline is the person's to judge. After the payment, the delivery record is
  where a short delivery shows.
- Repeat a limit as the tool gives it, never shortened ("at or over", "under").
- To show a History card as a page, call `ard_open_card_page`: it opens the page in the browser on the
  presenter's screen, and that is all the page needs. Never copy, move or link the page's file.
- To show the receipt as a page, call `ard_open_receipt_page` after the deal has closed. It opens the
  page the same way; if it says the deal is not closed yet, say so and do not retry in the same turn.
- `ard_pick` seals the pick. Never call `ard_pay` in the same message as `ard_pick`.
- Before every `ard_pay`, a repeat order to a seller already paid included, stop and ask the person to
  confirm in one sentence that names the seller and the amount and says whether real money moves (the
  recipe says which rail this run uses). For a second order to the same seller, ask "Want me to order
  again?" in that sentence. The dialog is the second check, never the only one.
- When `ard_pay`'s answer names the reasons the Everyday Rules held the order, whether the person then
  declined or approved it, tell the person every reason it lists, each in its own words: leave none out. This is
  the one answer that may run past two sentences: list the reasons, one per line.
- If `ard_pay` refuses because the last dialog was declined, and you asked the person to confirm this payment after
  that and they said yes, call it again at once: one question per order, never a second.
- `ard_pay` opens an approval dialog on the presenter's screen; you cannot see or answer it. Only
  its Pay or Buy anyway button releases money.
