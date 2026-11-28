# ARD two-seller demo

To install and run this demo on your own Mac with Goose Desktop, start at [RUNBOOK.md, "What you need"](RUNBOOK.md#what-you-need), then follow [Set up, once](RUNBOOK.md#set-up-once). This page says how the demo is built.

Maya asks her agent for 200 conference badges by Friday, under 3,000 msat. Two sellers are found through ARD: **Alder Print Co.** at 2,000 msat and **Kestrel Print** at 1,000 msat, with 15 and 10 sample deals, all held: a longer track record against half the price. In **deal 1** Maya buys from Kestrel, the cheaper one; Kestrel's own delivery record says 150 of 200 badges were shipped and states the delivery not met; Maya disputes the delivery, and the demo's adjudicator rules against Kestrel on that record alone, with no person. In **deal 2** Kestrel's own History card counts the lost dispute, Maya's own records hold the ruling (her rules then say NO: Steven's u187), and she buys from Alder. A buyer who holds no ruling sees LIMIT from the card alone (Steven's #280 rule); the end-to-end test checks that path.

**What it is not.** The sellers' history is sample history, made by the demo operator. The adjudicator is run by the operator, who also runs every party, so it is not independent of them; its window says so. Action State's witness, which every agreement names, is not independent of them either.

## How it is built

Every deal record is capsulectl-deal's (evidencebook, x-deal-v1): no deal record is written by the demo, and no row status or card count is computed here.

| Part | Code | What it uses |
|---|---|---|
| Each party's profile and its deal verbs | `party.py` | `capsulectl-deal` through the Goose reference's `Ctl` (evidencebook `python/examples/goose`, at the pin); its `Node` for a party's node book |
| The parties and their facts | `cast.py`, `sellers/<name>.yaml`, `catalog.yaml` | each seller's own file: the product it offers and what it discloses (subjects, derivations, `human_gated`, `answers_within`), which `flow.advertise` signs into its commitment; the product's title and price from the catalog stand-in, which the stage serves at `/catalog/<seller>/<product>.json` and each listing links (Maya's search checks the listing's offer against it); edit either, then reset and seed |
| The sample history | `seed.py` | 15 real x-deal-v1 deals for Alder and 10 for Kestrel (`cast.SAMPLE_DEALS`), each seller with its own sample buyer; contest windows of seconds, stamped on demand, so the seed takes about a minute and the cards count the deals held a minute or two later |
| Discovery | `ard.py`, `discovery.py`, `stage.py` | each seller's own `/.well-known/ard.json` and signed `evidence-commitment/1` (with its `history_card/2` staple, ops u539) and the signed `disclosure-policy/0` its `lcap.policy_uri` names, a stand-in registry answering `POST /search` |
| The History card | `flow.py` (`publish_card`, `fetch_card`) | each seller's shared `standard_history/3` card (`deal standard-history card --shared`), checked by Maya with `capsulectl verify --bundle` |
| The assessment | `buyer.py`, `pack.py`, `pack/` | `capsule-engine admission evaluate` under `demo/ard_admission/2.1.0`; the card's dispute tally (`card.disputes_against`, LIMIT on any lost dispute) and Maya's own rulings, read from capsulectl's report of each of her deals (`own.no_adverse_adjudication`, NO) |
| A deal | `buyer.py`, `flow.py` (`SellerAgent`), `wire.py` | offer naming the adjudicator and the witness, intent and check (Maya's dialog) before the offer is sent, admit, agree, payer and payee legs, delivery, statements; the parties hand each other the files the verbs write |
| The dispute and the ruling | `buyer.dispute`, `flow.enter_rulings`, `adjudicator.py` | `deal dispute`, sent to the seller and the adjudicator; the adjudicator's request for each side's books and each side's full answer (`deal respond`: its own book and the copy it holds of the other side's); `deal ruling check` and, when the owing side's own signed statement decides the row, `deal ruling --decided-by --answer` on the adjudicator's own capsulectl-deal profile, with no person, then its stamp; `deal receive` of the ruling; each side's book sent back for `deal ruling entries` |
| The windows | `desktop_server.py`, `goose/open-windows.py`, `goose/locked` | one MCP server per window (`ARD_ROLE`: maya, alder, kestrel, adjudicator), each agent limited to its own tools |
| The pages | `pages.py`, `receipt.py` | capsule-viewer's History view, vendored at 0.28.0; the receipt in words from capsulectl's report, and as capsulectl's own page; a page opens in the browser only with `ARD_OPEN_PAGES=1`, which `open-windows.py` sets in the Goose Desktop windows it opens (`ARD_OPEN_PAGES=0` in front of it turns that off); `--print`, `demo.py`, agent runs and the tests only write the page and print its path (#465) |
| The spending limit | `limits.py`, `buyer.question`, `screens.hold_question`, `ard_set_limit` | once the person confirms the limit her agent proposed from her words (`ard_set_limit` seals it with her answer in her own book; #361), capsule-engine's Everyday Rules (`guard check --limits`) pinned as Maya's rules checker (`profile update --rules-checker`), so `deal check` runs them on each payment, checked on her offer before it is sent; a held order is one question listing every reason, with capsulectl's card under it (evidencebook#890) |
| Payment | `pay.py` | the simulated rail, the Brattain and Shockley test nodes, or two local Lexe wallets (`ln-pay-local`); the invoice is made first, so Maya's check binds its payment hash |
| The testbed | `testbed.sh`, `testbed.py`, `testbed.yaml`, `feeds.py`, `watch.py` | one command: the set-up script, reset, the witness (`ARD_WITNESS=local`: capsule-anchor's own `ci/local-witness/start.sh` at the hosted witness's release, named in every profile after `deal init` and in the buyer's pack), the sample history, a Terminal screen for each role without an agent (the witness's stamps from each party's `deal tick` output; the rail's invoices and payments from where Maya's agent pays; the catalog's products and each read the stage serves), then the four windows (evidencebook-skills#382) |

## What is not there yet

- **The hosted adjudicator.** The adjudicator here is a capsulectl-deal profile the operator runs on this Mac (evidencebook#893). The hosted service, with the adjudicator's own journal record of each request, is evidencebook#861 PR 3.
- **The History page's dispute line.** The view has no member for disputes, so the card's tally is one line above it.

## Without Goose

`demo.py run` runs both deals in one terminal, each dialog asked at the prompt (`--auto` answers yes, simulated rail only). `demo.py seed` makes the sample history; `demo.py reset` stops the demo's processes, deletes the home and clears Goose's trust in the demo's own recipes (any other recipe keeps its trust). `demo.py --help` lists the environment each command needs.

## Tests

`tests/` runs without the binaries, except `tests/test_e2e.py`, which runs both deals against the real binaries with `ARD_E2E=1` (about 20 minutes, most of it the sample deals' contest windows). It stamps on a local witness that `scripts/check.sh --full` starts (capsule-anchor's `ci/local-witness`); it names Action State's hosted witness only with `ARD_E2E_WITNESS=hosted`, which only CI's nightly hosted leg sets, and with neither it refuses to run. CI's `ard-demo` job runs both.
