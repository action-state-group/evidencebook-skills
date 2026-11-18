# ARD two-seller demo

Maya asks her agent for 200 conference badges by Friday, under 3,000 msat. Two sellers are found
through ARD: **Alder Print Co.** at 2,000 msat (2 sats) and **Kestrel Print** at 1,000 msat (1 sat). Maya's library asks
each for its evidence, checks each signed answer, assesses each seller with an admission pack, and a
popup lets the presenter pick for Maya. The deal and a real Lightning payment follow the pick. It
runs on evidencebook's Goose loop reference (`python/examples/goose`, read from a pinned evidencebook checkout, `ARD_EVIDENCEBOOK`): four nodes in one process (Maya,
Alder, Kestrel and the sample buyer that ran their history), one private relay on localhost, the discovery stand-ins (`discovery.py`: each seller's own `/.well-known/ard.json` on a port of its own and a stand-in registry answering `POST /search`) and one local web server.

**What it is not.** The sellers' history is *sample history, run by the demo operator*. Kestrel's
card comes from its own book: two sample deals carry the owner's temporary `outcome_note`
([#462](https://github.com/action-state-group/evidencebook/issues/462)); a hand-written sample card is the fallback. The screen says "assessment", never "admission": the assessment gates no payment; the
presenter's pick and the approval dialog (below) are the controls (a LIMIT seller can be picked, and then nothing is paid). The
deal profile still gives no *did not hold* from records ([#212](https://github.com/action-state-group/evidencebook/issues/212)).

## What runs

| Step | Code |
|---|---|
| 2 ARD discovery: Maya's agent searches the stand-in registry (`POST /search`, the item only), then fetches each seller's own `/.well-known/ard.json`, compares the entry, checks the identity names its `.test` publisher, and verifies the signed `evidence-commitment/1` | `ard.py`, `discovery.py` |
| 3 evidence: `history_card/1` (the Goose reference's ask and poll), `standard_history/1` and the selection, each as a request sealed in Maya's book and answered over the sellers' mailbox | `buyer.gather`, `responder.py`, `relay.py` |
| 4 assessment: `capsule-engine admission evaluate` under the demo pack, one decision per seller, sealed in Maya's book | `buyer.assess`, `pack.py`; the pack is this repository's `packs/ard-demo-buyer` |
| 4b the on-stage edit: `max_adverse_permille` 100 → 50, version 1.0.0 → 1.1.0, recompiled with this repository's `scripts/pack_compile.py`, both sellers re-assessed on the saved evidence | `Run.edit` |
| 5 the popup and the pick, sealed before any payment | `popup.html`, `buyer.seal_pick` |
| 6 deal opened from the pick; Shockley's wallet issues an invoice for the picked price, Brattain's wallet pays it | `buyer.open_deal`, `pay.py` |
| 7 both parties' records compared, deal closed, Alder's card after the next checkpoint | `deals.py`, `demo_node.py` |

The demo pack is a fork of `admission-baseline`: pack id `demo/ard_admission/<version>` (never
`asg/`), `claims-held` removed (no card carries claims yet), trust roots naming the demo operator,
sat-band tiers T0 under 10 msat, T1 under 1,000 msat, T2 under 10,000 msat, `BTC` accepted, and the row
`card.band_history_or_stake` at T2 (`k: 10`, `max_adverse_permille`: 100 at the start, 50 after the
edit). All thresholds are placeholders for this demo only.

## Run sheet

Needs Python 3.10+, an evidencebook checkout at commit 5d29ccc (its `python/` package installed, and
the checkout itself for the Goose reference and the x-deal-v0 checker), and a `capsule-engine` binary
built at `go/v0.4.0`: the pins the `ard-demo` job in `.github/workflows/tests.yml` tests. The skills, the pack and its compiler are this repository's.

```bash
export ARD_EVIDENCEBOOK=/path/to/evidencebook        # checked out at the pinned commit
export CAPSULE_ENGINE=/path/to/capsule-engine        # go build ./cmd/capsule-engine in capsule-engine/go
python3 -m venv .venv
.venv/bin/pip install "$ARD_EVIDENCEBOOK/python" pyyaml rfc8785 websockets "mcp==2.3.0" \
  "capsule-viewer @ git+https://github.com/action-state-group/capsule-viewer@613a8a95144e5851bbb61df72df8cc76b7500381"
export CAPSULECTL_DEAL=/path/to/capsulectl-deal  # verifies each receipt page's copy (capsulectl verify --bundle)
cd demo/ard
../../.venv/bin/python demo.py seed                  # once, about 20 s: 24 + 24 sample deals
../../.venv/bin/python demo.py run --rail lightning  # the demo; --rail fake moves no money
```

Step 0, before `run`: the presenter says once, "This is sample history, and the payment is simulated: no money
moves" (on a real rail: "This is sample history, and the payment is real: a small Lightning payment between our
test wallets"). Nothing on screen says it for them.

`run` pauses at each step (Enter) and asks for the new threshold (default 50). The popup opens in the
browser; click "Pay Alder Print Co. 2,000 msat". `Ctrl-C` ends a run; running again starts over on the
same sample history. `demo.py reset` puts the Mac back to before the demo
ran, and needs none of the environment variables above: it refuses while Goose Desktop runs, stops the demo's own
`stage.py` and `desktop_server.py` on the home, including one started from an older commit that names the home or
runs from this checkout's `demo/ard` (and refuses if anything else holds the home or listens on the stage's ports),
deletes the home (`$ARD_HOME`, default `~/.config/ard-commerce-demo`,
keys and history included), and clears the Goose recipe trust given since the demo's windows first opened on that home,
so each window asks Trust and Execute again. Goose 1.59.2 names each trust file by a hash of the recipe as its own
server decodes it, which `reset.py` cannot reproduce, so `open-windows.py` notes which trust files exist before it
first opens the windows (`goose-trust-before.json` in the home) and reset deletes only the ones made since. Recipes
trusted before keep their trust; a home with no note keeps all of it.

A home seeded at other prices (before 2026-11-18's move to whole satoshis, say) is refused by `seed`: run
`reset`, then `seed`. After a paid run Alder's card reads 25 deals. Run `reset` and `seed` before the next rehearsal so the
audience sees 24 again. The card counts the sale after the next checkpoint (one minute here, the
shortest cadence the profile allows), so a run within a minute of the previous tick waits.

### Real payment

`--rail lightning` runs only `pay-lightning control` `balance`, `fund` and `send` on the two test
nodes over `gcloud compute ssh` (Shockley `mc53-u755-provider` issues the invoice, Brattain
`mc53-u755-payer` pays it, `max_fee_msat` 1,000). Pricing, wallet policy and config are never touched.
One payment per run, for the picked price in msat; the screen shows the invoice amount, never a
balance difference. On a real rail Maya's line shows the routing fee as her wallet reports it, and
the seller's receipt says that what its wallet was credited is not in its records: the seller's
wallet provider may deduct a receiving fee. Preimages are never printed or kept. You need `gcloud` signed in to the project.

### The local rail

`--rail local` (script) or `ARD_RAIL=local` (Goose windows) pays between two local Lexe wallets with
[ln-pay-local](https://github.com/action-state-group/ln-pay-local), with no gcloud and no mesh-llm. Real
Lightning on mainnet, so use small amounts and wallets made for this. Set `ARD_WALLET_BUYER` and
`ARD_WALLET_SELLER` to two wallet directories (`ln-pay-local init --wallet <dir>` makes one; fund the buyer), install the
program (`cargo install --locked --git https://github.com/action-state-group/ln-pay-local`, or set `ARD_PAY_LOCAL` to the
binary), then run as for `--rail lightning`. For the Goose windows, export the two wallet variables (and `ARD_PAY_LOCAL`
if the program is not on the PATH) and run `goose/open-windows.py --rail local`; only Maya's window gets them. The Brattain and Shockley rail stays the default for `--rail lightning`.

### The one switch

`--kestrel-card sentinel` (the default; `seed` writes it) reads Kestrel's card from its own book: two
deals carry the book owner's `outcome_note` (the temporary record of #462, in evidencebook v0.14.2),
which the card counts as did not hold. `--kestrel-card sample` is the fallback: Kestrel's hand-written
sample card (22 held, 2 did not hold), for a package without that record. Use the same value for `seed`
and `run`. The card does not show who wrote the note, and the screen says it is the seller's own
note, not confirmed by the buyer or a ruling.

## In Goose Desktop

The same story, run by each party's own Goose in three Goose Desktop windows side by side: Maya (the
buyer), Alder and Kestrel (the sellers). Each window is a thin recipe: the party's facts and the rail,
then the evidencebook-skills skill it follows (`buy-with-evidence` for Maya, `sell-with-evidence` for the
sellers), read from this repository's `skills/`. Each recipe has its own embedded extension,
`desktop_server.py` with `ARD_ROLE` set, so each party has its own process, keys and book (its own
directory under the demo home) and sees only its own records. They meet only through the *stage*
(`stage.py`: one private relay and the discovery stand-ins on localhost, started by the first window that needs
it) and a wire directory where the parties leave deal halves for each other; the sellers' agents answer
Maya's evidence requests and deal halves on their own, as the sellers do in the script demo.
The stage listens on `ARD_STAGE_PORT` (default 47481) and the two sellers' origins 10 and 11 ports above it (47491, 47492); if something
else already holds that port (an earlier demo's `stage.py`, say), the windows refuse it and say so: stop it before a show.

| Window | Tools | What it shows |
|---|---|---|
| Maya | `ard_find_sellers`, `ard_show_history`, `ard_assess`, `ard_pick`, `ard_pay`, `ard_show_card`, `ard_open_card_page`, `ard_show_receipt`, `ard_open_receipt_page` | the steps of the script demo; `ard_pay` is the one tool that moves money; her own card and receipt |
| Alder, Kestrel | `ard_seller_activity`, `ard_show_card`, `ard_open_card_page`, `ard_show_receipt`, `ard_open_receipt_page` | what that seller's agent did; its own History card; its own receipt for the deal |

`demo.py --help` (or `demo.py` alone) and `goose/open-windows.py --help` list each variable, which command needs
it and the export line to copy; a command that lacks one names every missing variable with that line and stops,
before anything runs.

At the start of the show the presenter says, once: "This is sample history, and the payment is simulated: no
money moves." (on a real rail, say instead that the payment is real). Nothing on screen says it for them: the pages and the tools' output carry no demo banner (Ethan,
2026-11-17), and only the payment dialog repeats "simulated rail: no money moves".

Set up (once): seed the demo home as above, then

```bash
export CAPSULE_ENGINE=... ARD_EVIDENCEBOOK=...
.venv/bin/python demo/ard/goose/open-windows.py --rail fake   # or lightning
```

It opens one `goose://recipe?config=…` link per party (sellers first, Maya last) and right after tiles the windows itself
with Window, Move & Resize, Left & Quarters, Maya on the left; the first time, macOS asks to let your terminal control
System Events and to turn it on under Accessibility, and the script tries again every 10 s, twice, while you allow it. If all three tries fail it prints how, then, after a blank line, the one osascript line that tiles the open windows again.
Goose Desktop asks once per recipe, Trust and Execute. The three can start in any order: each seller's first message publishes its entry, and
Maya's first message only says she is ready, so nothing is searched until the presenter, once both sellers have answered, types the ask
("I am Maya. I need 200 conference badges by Friday, under 3,000 msat (a msat is a thousandth of a satoshi: a token amount). Find sellers for me."). Keep the global (Settings) copy of any
`ard_demo` extension off. `ARD_ROLE=all` (the default of `desktop_server.py`) runs the whole story in one
process and one window, with Maya's tools.

Cards and receipts. In every window `ard_show_card` prints that party's own `standard_history/1` card and `ard_show_receipt`
its own receipt for the deal, both computed from that party's own sealed records (Maya's from her book, Alder's from
his); a window never shows another party's. Before the deal Maya's card counts 0 deals, Alder's 24 and Kestrel's 24 (2 did
not hold); after it Alder's counts 25 and Maya's 1: `ard_pay` takes Maya's checkpoint over her own records as part of closing (waiting up to a minute if her last one was that recent) and Alder's agent takes its own right after the close, so both cards show the sale within seconds in the demo's story. The seller's
receipt holds no payment step: the payment is the buyer's act, so only Maya's receipt shows it.

The History card as a page. `ard_open_card_page` writes that party's own card as a page under `$ARD_HOME/pages/` and
opens it in the browser (`ARD_OPEN_PAGES=0` writes it without opening): capsule-viewer's History view (`history-view/v0`),
drawn by the released `history-view.iife.js` of capsule-viewer 0.18.0 vendored in `vendor/` and pinned by its sha256, from
a model the party builds from its own card (`pages.py`). The page fetches nothing and carries no demo banner (Ethan, 2026-11-17: the presenter says "sample history,
simulated payment" once at the start); it keeps only the label a count needs, such as Kestrel's did-not-hold counted
from its own note.

The receipt as a page. `ard_open_receipt_page` writes that party's own receipt for its closed deal as a page under
`$ARD_HOME/pages/` and opens it the same way (`receipt.py`). The page is capsule-viewer's receipt module (the Python
package at the commit the install line pins) drawing the party's own copy of the deal: its deal book as an Evidence
Bundle with every step disclosed, and a sealed report in the standalone form (`x-deal-report/v0`, on no log, so no
other step's reader sees it), whose lines are this demo's words from the party's own records. `capsulectl verify
--bundle` (the binary `CAPSULECTL_DEAL` names) checks the copy before it is drawn. The tool refuses before the deal is
closed and the other party's closing half has arrived. The report is kept under the party's home (`receipts/`) and
sealed again only when the deal book grew. On the simulated rail Maya's live deal seals the rail `simulated` in its
terms, so neither its records nor its receipt say Lightning (the sample deals keep `lightning`; they carry no payment).
A receipt page is capsule-viewer's own, with nothing added: no banner, and no DEMO badge (the baseline seals no `demo` flag).

The payment gate. `ard_pay` never pays on the agent's word: before it moves anything it shows a native macOS dialog on
the presenter's screen (payee, amount, real or simulated rail; Cancel is the default) and pays only if the presenter
clicks Pay. The agent neither sees nor answers that dialog, so it cannot pay in one turn; Cancel, a timeout or no screen
refuses and pays nothing. After such a refusal the next `ard_pay` for that seller opens no dialog: it returns
the question to ask Maya (seller, amount, real or simulated), and the call after it opens the dialog again. Stated limit: it stops the agent, not an agent that has computer-use tools and clicks the dialog
itself; the demo agent is told to use only the `ard_*` tools, but that is a prompt, not enforcement: Goose's extension manager stays on, so before a show confirm in each window that only its own extension is enabled. On the real rails the money settles to one node or wallet the two sellers share (the dialog says so). `ARD_APPROVAL=none` in the extension command turns the gate off on the simulated rail only (tests only; the tool says so); on a real rail `ard_pay` refuses it and pays nothing.

Things to know. Goose Desktop keeps environment values of a custom extension as secrets it does not pass
to the server, so the recipes put them in the command (`/usr/bin/env`). One Goose chat per party and home:
a second chat's server refuses to start. A Claude-backed provider (Claude Code ACP) reads the account's own
instructions (language, tools, other sessions); ask it for English in the first message, or use a clean
provider. The script demo above is unchanged and is the fallback.

## What differs from the design note

- The sellers answer `standard_history/1` themselves: the book answers that card only to an
  authenticated requester, so the seller agent signs it for Maya's request (as `Node.history_staple`
  signs it for the node's own).
- The selection is the demo's own form (a signed statement of unanswered disputes bound to Maya's
  nonce, `selection/1`); it carries no inclusion proofs and the screen says so.
- The Python deal profile has no producer for `ec:deal-reconcile@1`, so a deal counts as *held* when
  the node's own reconcile check (both closes name the same amount and currency) says so
  (`demo_node.py`).
- Maya holds no loop admission of a seller, only her assessment, so she checks a seller's half under the
  checkpoint key its verified commitment names (`deals._reconcile`), not under the key a GO admission pinned.
- The sellers' commitments name `wss://ard-demo.relay.local`, which this process maps to its one
  local relay (the mailbox events are not encrypted, so the relay is localhost only).

## Tests

```bash
cd demo/ard
ARD_EVIDENCEBOOK=… ../../.venv/bin/python -m pytest -q tests                      # the unit tests; the demo tests skip without the engine
ARD_EVIDENCEBOOK=… CAPSULE_ENGINE=… ../../.venv/bin/python -m pytest -q tests     # + the demo end to end on a fake rail, about 4 minutes
```

The end-to-end tests need a capsule-engine binary: run them with both paths set before each rehearsal.
