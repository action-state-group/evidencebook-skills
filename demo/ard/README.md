# ARD two-seller demo

To install and run this demo on your own Mac with Goose Desktop, start at [RUNBOOK.md, "What you need"](RUNBOOK.md#what-you-need), then follow [Set up, once](RUNBOOK.md#set-up-once). This page says how the demo is built.

Maya asks her agent for 200 conference badges by Friday, under 3,000 msat. Two sellers are found through ARD: **Alder Print Co.** at 2,000 msat and **Kestrel Print** at 1,000 msat, each with 12 sample deals, all held. In **deal 1** Maya buys from Kestrel, the cheaper one; Kestrel's own delivery record says 150 of 200 badges were shipped; Maya disputes the delivery, and the demo's adjudicator rules against Kestrel on that record. In **deal 2** Kestrel's own History card counts the lost dispute, Maya's own records hold the ruling (her rules then say NO: Steven's u187), and she buys from Alder. A buyer who holds no ruling sees LIMIT from the card alone (Steven's #280 rule); the end-to-end test checks that path.

**What it is not.** The sellers' history is sample history, made by the demo operator. The adjudicator is run by the operator, who also runs every party, so it is not independent of them; the ruling's dialog says so. Action State's witness, which every agreement names, is not independent of them either.

## How it is built

Every deal record is capsulectl-deal's (evidencebook, x-deal-v1): no deal record is written by the demo, and no row status or card count is computed here.

| Part | Code | What it uses |
|---|---|---|
| Each party's profile and its deal verbs | `party.py` | `capsulectl-deal` through the Goose reference's `Ctl` (evidencebook `python/examples/goose`, at the pin); its `Node` for a party's node book |
| The parties and their facts | `cast.py`, `sellers/<name>.yaml` | each seller's own file: its offer and what it discloses (subjects, derivations, `human_gated`, `answers_within`), which `flow.advertise` signs into its commitment; edit it, then reset and seed |
| The sample history | `seed.py` | 12 real x-deal-v1 deals per seller, each with its own sample buyer; contest windows of seconds, stamped on demand, so the seed takes about a minute and the cards count the deals held a minute or two later |
| Discovery | `ard.py`, `discovery.py`, `stage.py` | each seller's own `/.well-known/ard.json` and signed `evidence-commitment/1` (with its `history_card/2` staple, ops u539) and the signed `disclosure-policy/0` its `lcap.policy_uri` names, a stand-in registry answering `POST /search` |
| The History card | `flow.py` (`publish_card`, `fetch_card`) | each seller's shared `standard_history/3` card (`deal standard-history card --shared`), checked by Maya with `capsulectl verify --bundle` |
| The assessment | `buyer.py`, `pack.py`, `pack/` | `capsule-engine admission evaluate` under `demo/ard_admission/2.0.0`; the card's dispute tally (`card.disputes_against`, LIMIT on any lost dispute) and Maya's own rulings, read from capsulectl's report of each of her deals (`own.no_adverse_adjudication`, NO) |
| A deal | `buyer.py`, `flow.py` (`SellerAgent`), `wire.py` | offer naming the adjudicator and the witness, admit, intent, agree, check (Maya's dialog), payer and payee legs, delivery, statements; the parties hand each other the files the verbs write |
| The dispute and the ruling | `buyer.dispute`, `flow.enter_rulings`, `adjudicator.py` | `deal dispute`, sent to the seller and the adjudicator; the adjudicator's request for each side's books and each side's full answer (`deal respond`: its own book and the copy it holds of the other side's); `deal ruling --answer` on the adjudicator's own capsulectl-deal profile, then its stamp; `deal receive` of the ruling; each side's book sent back for `deal ruling entries` |
| The windows | `desktop_server.py`, `goose/open-windows.py`, `goose/locked` | one MCP server per window (`ARD_ROLE`: maya, alder, kestrel, adjudicator), each agent limited to its own tools |
| The pages | `pages.py`, `receipt.py` | capsule-viewer's History view, vendored at 0.25.0; the receipt in words from capsulectl's report |
| Payment | `pay.py` | the simulated rail, the Brattain and Shockley test nodes, or two local Lexe wallets (`ln-pay-local`); the invoice is made first, so Maya's check binds its payment hash |

## What is not there yet

- **The hosted adjudicator.** The adjudicator here is a capsulectl-deal profile the operator runs on this Mac (evidencebook#893). The hosted service, with the adjudicator's own journal record of each request, is evidencebook#861 PR 3.
- **The card's witness.** No verb gives a buyer the witness receipt for a card's anchor (evidencebook#891), so that input is filled in by the operator and the screen says it is not checked.
- **The spending limit.** It returns when the Everyday Rules run as the buyer's pinned rules checker on x-deal-v1 deals (evidencebook#890).
- **The History page's dispute line.** The view has no member for disputes, so the card's tally is one line above it.

## Without Goose

`demo.py run` runs both deals in one terminal, each dialog asked at the prompt (`--auto` answers yes, simulated rail only). `demo.py seed` makes the sample history; `demo.py reset` stops the demo's processes, deletes the home and clears Goose's trust in the demo's own recipes (any other recipe keeps its trust). `demo.py --help` lists the environment each command needs.

## Tests

`tests/` runs without the binaries, except `tests/test_e2e.py`, which runs both deals against the real binaries and Action State's hosted witness with `ARD_E2E=1` (about 20 minutes, most of it the sample deals' contest windows). CI's `ard-demo` job runs both.
