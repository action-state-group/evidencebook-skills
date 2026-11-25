# Reproducing the ARD Deal

How to run the ARD two-seller deal on your own Mac: four Goose Desktop windows, one buyer agent, two seller agents and the adjudicator's assistant. The buyer finds the sellers through ARD and reads their signed History cards. In the first deal the cheaper seller ships short, the buyer disputes, and the adjudicator rules against the seller. In the second deal the seller's card and the buyer's own records show that ruling, and the buyer buys from the other seller. The simulated rail is the default; the real rail steps are marked Real.

evidencebook-skills PIN (set when this guide's PR merges: evidencebook-skills#285) · evidencebook 710d865 (evidencebook#893; capsulectl-deal built from it, for every party and the adjudicator) · capsule-engine 0263ff1 (go/v0.8.0) · capsule-viewer b21b993 (ts/v0.26.1) · Goose Desktop 1.59.2 · real rail: ln-pay-local 025d566

Plain-text copy of the reproduction guide, for tools and terminals: [demo/ard/RUNBOOK.md](https://github.com/action-state-group/evidencebook-skills/blob/main/demo/ard/RUNBOOK.md).

Status: not yet run by hand at this pin. The demo's automated tests, both deals end to end against Action State's hosted witness included, pass in CI. The spending-limit section of earlier pins is not in this guide: it returns when the Everyday Rules run as the buyer's pinned rules checker on these deals (evidencebook#890). The receipt page is not available for these deals yet (the page viewer does not check this kind of deal copy yet); the receipt in words is.

## What you will see

Maya needs 200 conference badges by Friday, under 3,000 msat (a msat is a thousandth of a satoshi). Two sellers offer them: Kestrel Print at 1,000 msat and Alder Print Co. at 2,000 msat. Both start with 24 sample deals, all held, and no disputes.

1. **Discovery.** Maya's agent searches a local stand-in ARD registry, then fetches each seller's own entry and checks its signed commitment.

2. **History cards.** Each seller's card: 24 deals, every one went as agreed, no disputes. A card's signature shows who wrote the counts and that they are unchanged since; these are the seller's own counts.

3. **Deal 1.** Both sellers are "Good to buy"; Maya picks Kestrel, the cheaper one, and pays 1,000 msat (a dialog asks you first). Kestrel's own delivery record says 150 of 200 badges were shipped. Maya disputes the delivery.

4. **The adjudicator.** The adjudicator asks each side for its books, and each side's agent answers on its own: its own book and the copy it holds of the other side's. The adjudicator's window shows the case and Kestrel's own signed delivery record. You rule against Kestrel in a dialog. The adjudicator is run by the operator, who also runs every party here, so it is not independent of them. Both parties enter the ruling in their own records.

5. **Deal 2.** Kestrel's card now counts 25 deals, 1 that didn't go as agreed, 1 dispute decided against it. Maya's own records hold the ruling, so her rules give Kestrel "Not from this seller" (NO). Alder is "Good to buy"; Maya buys from Alder, and Alder ships all 200.

The registry, the seller sites and the 48 sample deals are local stand-ins, and the adjudicator runs on this Mac. The ARD search call, fetching each seller's entry, the signature checks, the assessment, every deal record (capsulectl-deal), the dispute and the ruling (capsulectl-deal's `deal respond` and `deal ruling`, the adjudicator's own profile) are the real code.

## What you need

1. A Mac on Apple silicon. The steps use the arm64 build of Goose; an Intel build is on the same release page.

   ```
   uname -m
   ```

   **Expect:** `arm64`.

2. Homebrew. If `brew --version` fails, install it with the line from brew.sh.

   ```
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```

3. Python 3.10 or later (3.14 tested by hand at an earlier pin). Check, and install if missing.

   ```
   python3 --version
   brew install python
   ```

4. git. Check, and install if missing.

   ```
   git --version
   brew install git
   ```

5. jq (stock macOS often lacks it). Check, and install if missing.

   ```
   jq --version
   brew install jq
   ```

6. Go. Check, and install if missing. Any recent version works: the build lines set `GOTOOLCHAIN=auto`, so Go fetches the version each module asks for.

   ```
   go version
   brew install go
   ```

7. Node.js and npm. Check, and install if missing.

   ```
   node --version; npm --version
   brew install node
   ```

8. The `claude` CLI, signed in to a Claude Code subscription. Install it only if missing, sign in, check. The Goose windows use Claude Code as their model.

   ```
   command -v claude || npm install -g @anthropic-ai/claude-code
   claude auth login
   claude auth status
   ```

   **Expect:** `claude auth status` prints JSON with `"loggedIn": true`.

9. lsof. macOS ships it; check that it is there. `demo.py reset` stops with an error without it.

   ```
   command -v lsof
   ```

   **Expect:** a path such as `/usr/sbin/lsof`.

10. [Real] Real rail only: Rust. Check, and install if missing. A real payment also needs a small amount of bitcoin on Lightning.

    ```
    cargo --version
    brew install rust
    ```

## If you used this guide before 2026-11-19

1. Its setup changed your own Goose: the provider became Claude Code ACP and the extensions were switched off, in `~/.config/goose/config.yaml`. In your normal Goose, set your provider back in Settings, Models, and switch back on the extensions you had on before. The demo now uses its own Goose settings folder and leaves yours alone.

2. It also installed the Claude Code adapter globally, replacing the version you had. If you know which version that was, put it back (npm keeps no history of it); one ACP client stopped working above 0.94.0. The demo now uses its own pinned copy under ~/ard-demo/acp.

   ```
   npm install -g @agentclientprotocol/claude-agent-acp@<the version you had (or the version your other tool requires)>
   ```

## Set up, once

1. Clone and build everything under `~/ard-demo` (about 5 minutes). Another folder works if you change the paths in the next section to match. Paste each block below into the same terminal window, one block at a time, and wait for each to finish before pasting the next.

   ```
   mkdir -p $HOME/ard-demo/bin && cd $HOME/ard-demo
   git clone -q https://github.com/action-state-group/evidencebook-skills
   git -C evidencebook-skills checkout -q PIN
   git clone -q https://github.com/action-state-group/evidencebook
   git -C evidencebook fetch -q origin 710d8655d487c1a2b7810c8d23a68eeea57bb85a
   git -C evidencebook checkout -q 710d8655d487c1a2b7810c8d23a68eeea57bb85a
   (cd evidencebook/capsulectl && GOTOOLCHAIN=auto go build -o $HOME/ard-demo/bin/capsulectl-deal ./cmd/capsulectl-deal)
   ```

   ```
   cd $HOME/ard-demo
   git clone -q https://github.com/action-state-group/capsule-engine
   git -C capsule-engine checkout -q 0263ff119911d91eb54dd3d3debdcc71324042eb
   (cd capsule-engine/go && GOTOOLCHAIN=auto go build -o $HOME/ard-demo/bin/capsule-engine ./cmd/capsule-engine)
   ```

   ```
   ls $HOME/ard-demo/bin
   ```

   **Expect:** `capsule-engine capsulectl-deal`.

   ```
   cd $HOME/ard-demo/evidencebook-skills && python3 -m venv .venv
   .venv/bin/pip install -q cryptography pyyaml rfc8785 "mcp==2.3.0" "capsule-viewer @ git+https://github.com/action-state-group/capsule-viewer@b21b993bca899fa69a4311c406ba86f442b50b2a"
   ```

   **Expect:** pip ends with no error.

2. Already cloned at an earlier pin? Move each checkout to this pin, rebuild the binaries with the build lines above, and rerun the pip line. The earlier evidencebook Python package is no longer used; it may stay installed.

3. Install Goose Desktop 1.59.2: download `Goose-darwin-arm64.zip` from [the release page](https://github.com/aaif-goose/goose/releases/tag/v1.59.2), unzip it, move `Goose.app` to Applications. Other versions were not tried; the recipe links depend on how 1.59.2 opens them.

4. Install the demo's own Claude Code adapter (ACP) at a pinned version, under ~/ard-demo. **Never install it with npm install -g.** A global install replaces the adapter version other tools on your Mac use; one ACP client stopped working above 0.94.0. open-windows.py points the demo's Goose at this copy (Goose looks in GOOSE_SEARCH_PATHS first). 0.108.0 is the version Goose 1.59.2 ran with when this guide was made.

   ```
   npm install --prefix $HOME/ard-demo/acp @agentclientprotocol/claude-agent-acp@0.108.0
   ```

5. Quit Goose, then start the demo's own Goose. **It runs on its own settings folder, `~/.config/ard-commerce-goose`, so the next two steps never change your own Goose.** Goose 1.59.2 keeps its provider and extension settings under `GOOSE_PATH_ROOT` when it is set; open-windows.py starts Goose with it. Reset never deletes this folder.

   ```
   osascript -e 'quit app "Goose"'
   .venv/bin/python demo/ard/goose/open-windows.py --goose-only
   ```

   **Expect:** "started the demo's own Goose on …/ard-commerce-goose", and Goose opens on its welcome screen.

6. In that Goose: the window may open small; maximize it. On the welcome screen click Connect to a Provider, type `claude` in the search box to find Claude Code ACP, wait for "ACP adapter found", click Continue. A privacy screen follows (untick "Share anonymous usage data" if you like), then Get Started. Later this lives in Settings, Models. (Goose 1.59.2, hand run 2026-11-24.)
   **Expect:** a chat opens and answers a short message.

7. **Required, so the payment dialog holds (an agent with screen control could click it itself):** in that Goose, Extensions (in the left sidebar in Goose 1.59.2), turn off every extension: Analyze, Apps, Developer, Extension Manager, Skills, Summon and Top Of Mind. Each card drops from Default Extensions down to Available as you switch it off, so the next switch slides under the cursor: check each one. The demo's own extensions (ard_maya, ard_alder, ard_kestrel, ard_adjudicator) are not there yet: each window brings its own. Scheduler is a Goose setting, not one of these extensions, and stays on in `config.yaml` (`scheduler: enabled: true`); the hand run left it on.

8. Quit that Goose.

   ```
   osascript -e 'quit app "Goose"'
   ```

## Real rail, once

Do a full run on the simulated rail first, then the real rail. This moves real bitcoin on Lightning mainnet. Use new wallets and small amounts. Not yet run at these pins. Lexe's fees, from [docs.lexe.tech/pricing](https://docs.lexe.tech/pricing) (read 2026-11-18; the page says rates may change): receiving payments 0.5%, sending to other Lexe users 0.5% of the payment amount, and "Lightning sends and receives have a minimum fee of ₿0.1 (100 msat …). It only applies to payments under ₿20." At 2,000 msat, 0.5% is 10 msat, so the 100 msat minimum applies on both sides: the buyer needs 2,100 msat and the seller should receive about 1,900.

1. [Real] Install ln-pay-local. ln-pay-local is a small command-line wallet on Lexe's Lightning SDK.

   ```
   git clone -q https://github.com/action-state-group/ln-pay-local $HOME/ard-demo/ln-pay-local
   git -C $HOME/ard-demo/ln-pay-local checkout -q 025d56672d92ea12fda5fe6c3fbb84dd1d40ddf7
   cargo install --path $HOME/ard-demo/ln-pay-local --locked
   ln-pay-local --help
   ```

   **Expect:** one usage line starting `{"error": "usage: ln-pay-local init`.

2. [Real] Make a buyer and a seller wallet. **Each writes a private seed file into its folder: back it up, never print or share it.**

   ```
   ln-pay-local init --wallet $HOME/ard-wallets/buyer
   ln-pay-local init --wallet $HOME/ard-wallets/seller
   ```

3. [Real] Fund the buyer: pay the printed invoice from another Lightning wallet. The seller needs no funding.

   ```
   ln-pay-local invoice 10000 --wallet $HOME/ard-wallets/buyer
   ```

   **Expect:** `{"invoice": "lnbc…", "amount_msat": 10000}`. About 9,900 msat arrives after Lexe's 100 msat minimum receive fee: enough for 4 runs at 2,100 msat each.

## In every terminal

1. Go to the checkout and set the three paths.

   ```
   cd $HOME/ard-demo/evidencebook-skills
   export ARD_EVIDENCEBOOK=$HOME/ard-demo/evidencebook \
     CAPSULECTL_DEAL=$HOME/ard-demo/bin/capsulectl-deal \
     CAPSULE_ENGINE=$HOME/ard-demo/bin/capsule-engine
   ```

2. Check which variables each command needs.

   ```
   .venv/bin/python demo/ard/demo.py --help
   ```

   **Expect:** the commands (seed, run, reset) and an Environment section with an export line to copy. A command with a variable missing names it and stops before it runs.

3. [Real] Real rail: also the wallets and the payment program.

   ```
   export ARD_WALLET_BUYER=$HOME/ard-wallets/buyer ARD_WALLET_SELLER=$HOME/ard-wallets/seller \
     ARD_PAY_LOCAL=$(command -v ln-pay-local)
   ```

## Before each run

1. Quit Goose, then reset: it stops the demo's processes (the stage and the windows' servers), deletes the demo home and clears the recipe trust given since the demo's windows first opened: the demo's four recipes, and any other recipe you trusted in the meantime. Goose keeps recipe trust in one place for both, so this also applies to your own Goose. The demo home is `~/.config/ard-commerce-demo`.

   ```
   osascript -e 'quit app "Goose"'
   (cd demo/ard && ../../.venv/bin/python demo.py reset)
   ```

   **Expect:** "removed …" and "cleared Goose's trust in the N recipes trusted since this home's windows first opened …". If it refuses, it says what to stop.

2. Make the sample history (about 8 minutes: each sample deal counts as held only once its contest window ends and a checkpoint covers it).

   ```
   (cd demo/ard && ../../.venv/bin/python demo.py seed)
   ```

   **Expect:** "alder: 24 deals, all held" and "kestrel: 24 deals, all held". Each party's checkpoints go to Action State's hosted witness (hashes only); with no network, set `ARD_WITNESS=off` first (the cards are then not time-stamped).

3. [Real] Read both balances.

   ```
   ln-pay-local balance --wallet "$ARD_WALLET_BUYER"; ln-pay-local balance --wallet "$ARD_WALLET_SELLER"
   ```

   **Expect:** buyer `spendable_msat` at least 3,200 (1,000 and 2,000 for the two deals, plus Lexe's 100 msat minimum send fee each).

4. [Real] Open the four windows (it refuses while Goose runs, then starts the demo's own Goose): the sellers, the adjudicator, then Maya, tiled in quarters. The first time, macOS asks to let your terminal control System Events and to turn it on under Accessibility: allow both.

   ```
   .venv/bin/python demo/ard/goose/open-windows.py --rail local
   ```

   **Expect:** four windows, each with a Trust prompt. If tiling fails while macOS asks, the script tries again every 10 s, twice.

5. [Simulated] Or, simulated: the same, and no money moves.

   ```
   .venv/bin/python demo/ard/goose/open-windows.py --rail fake
   ```

6. If the windows are still not tiled: allow the access, click Maya's window, then by hand: Window, Move & Resize, Quarters.

7. Click Trust and Execute in all four windows, in any order.
   **Expect:** Alder and Kestrel each say 24 deals, all held; Maya and the adjudicator's assistant only say they are ready.

8. **Required:** in each window open Extensions: only its own `ard_maya`, `ard_alder`, `ard_kestrel` or `ard_adjudicator` is on (the extensions icon under the chat box shows 1). Turn anything else off before you type. To see what an agent has, type `List every tool you have by exact name, including deferred ones.` in any window. **Expect:** ToolSearch and that window's own `mcp__ard_…` tools, nothing else: Maya's ten (`ard_find_sellers`, `ard_show_history`, `ard_assess`, `ard_pick`, `ard_pay`, `ard_dispute`, `ard_show_card`, `ard_open_card_page`, `ard_show_receipt`, `ard_open_receipt_page`), a seller's five (`ard_seller_activity` and the four card and receipt tools), the adjudicator's three (`ard_case`, `ard_rule`, `ard_case_activity`).

9. Keep the screen awake and unlocked: the payment and ruling dialogs appear on it.

## The run

Type in Maya's window unless a step names another; each step takes 30 to 60 s. Cmd+` moves between windows.

1. Say the opening line (simulated rail; on the real rail say the payments are real and small).

   ```
   This is sample history, and the payment is simulated: no money moves.
   ```

2. Paste the ask.

   ```
   I am Maya. I need 200 conference badges by Friday, under 3,000 msat (a msat is a thousandth of a satoshi: a token amount). Find sellers for me.
   ```

   **Expect:** the search, then both sellers' entries and signatures checked: Alder 2,000 msat, Kestrel 1,000 msat.

3. Type.

   ```
   Show me each seller's History card.
   ```

   **Expect:** for each: "History card: 24 deals, every one went as agreed. Disputes others raised about it: 0 decided against it, of 0 decided; 0 open." and "Signed by … These are the seller's own counts." The witness line reads "this card's time-stamp is not checked here: no receipt for it is available to the buyer yet" (evidencebook#891).

4. Type.

   ```
   Assess both sellers.
   ```

   **Expect:** both "GO: … is within this pack's limit for it", Kestrel at 1,000 msat and Alder at 2,000 msat.

5. Type.

   ```
   Pick Kestrel Print, the cheaper one.
   ```

   **Expect:** the pick is sealed first ("pick sealed before any payment"), then Maya asks before paying.

6. Type, then wait for the macOS dialog (it waits 3 minutes). Only your click releases the payment.

   ```
   Yes, pay it.
   ```

   **Expect:** the dialog "Pay Kestrel Print 1,000 msat on the simulated rail: no money moves."; nothing is sent to Kestrel until you answer it. Click Pay. Then "invoice 1,000 msat; the simulated rail paid it (no money moved): succeeded" and "Kestrel Print's delivery record says 150 of 200 badges were shipped." Maya asks whether you want to dispute the delivery.

7. Type.

   ```
   Only 150 arrived. Dispute the delivery.
   ```

   **Expect:** "Dispute raised on this deal's delivery. Sent to Kestrel Print and to the adjudicator your agreement names. Nothing is refunded by this step."

8. Cmd+` to Kestrel's window, type `What happened?`.
   **Expect:** among the lines: "delivered to the buyer: 150 of 200 badges (this seller's delivery record says so)", "the buyer disputed the delivery …: the adjudicator will ask for this seller's books". After step 9, also "the adjudicator asked for this party's books of deal …: sent in full (its own book and the copy it holds of the other side's)".

9. Cmd+` to the adjudicator's window, type:

   ```
   Show me the case.
   ```

   **Expect:** "This adjudicator is run by the operator, who also runs every party here: it is not independent of the parties.", then "deal …, row delivered: disputed by Maya", "asked both sides for their books at …", "Maya answered at …" and "Kestrel Print answered at …" (each: "its own book and the copy it holds of" the other side's), "Maya's statement on the row: not met" and "Kestrel Print's own signed delivery record: 150 of 200 badges". It waits up to 30 seconds for the answers; if one says "no answer yet", ask again.

10. Type, then answer the dialog.

    ```
    Rule against Kestrel: its own delivery record says 150 of 200.
    ```

    **Expect:** the dialog "Rule on deal …, row delivered: not met, against Kestrel Print. Conflict: the operator runs this adjudicator and every party here, so it is not independent of the parties. Either side may challenge it within 7 days. A challenge is recorded beside the ruling and never replaces it." (default Cancel); click Rule. Then "Ruling recorded … not met, against Kestrel Print" and "Its stamp was taken by Action State's witness; each party's window shows the time it was stamped.", "Sent to both parties; each enters it in its own records." (with no network: "Not yet time-stamped: Action State's witness took no stamp within 90 seconds (no network?). Run this again to send it with its stamp.").

11. After about a minute, type `Did both parties enter it?`.
    **Expect:** "Maya: entered" and "Kestrel Print: entered". Cmd+` to Kestrel's window and ask `What happened?` again: "the adjudicator's ruling on deal … entered in this party's records", with the time Action State's witness stamped it.

12. In Kestrel's window, type `Show my History card.`
    **Expect:** "25 deals, 1 didn't go as agreed. Disputes others raised about it: 1 decided against it, of 1 decided; 0 open." If it still shows 24 deals, or 0 that didn't go as agreed, ask again in a minute: the card counts after the seller's next checkpoint, and the deal's outcome can follow the dispute's count by one checkpoint.

13. Cmd+` back to Maya's window, type:

    ```
    Order 200 more badges. Show me each seller's History card again, then assess both.
    ```

    **Expect:** Kestrel's card as in step 12; Kestrel "NO: you hold a ruling against this seller (deal …, delivery not met, ruled …). Your rules block a seller you hold a ruling against for 180 days. Its card also counts 1 dispute decided against it, of 1 decided; the card does not say which deal."; Alder "GO".

14. Type `Pick Alder Print Co.`, then `Yes, pay it.` and answer the dialog ("Pay Alder Print Co. 2,000 msat on the simulated rail: no money moves."): click Pay.
    **Expect:** invoice 2,000 msat succeeded, "Alder Print Co.'s delivery record says 200 of 200 badges were shipped." and "Maya's statement sent: she received what she paid for."

15. Type `Show your History card, then your receipt.`
    **Expect:** Maya's card counts her 2 deals; her receipt reads each row's status as capsulectl reports it (Alder's deal: met so far, as both sides said, still open to dispute until its window ends) and "Test money: this deal's payment was on a simulated rail. No real money moved."

16. [Real] Wallets after: buyer outbound 1,000 and 2,000 msat succeeded.

## Quit and re-entry

1. Quit Goose (Cmd+Q) and reopen on the same home, same rail, without reset.

   ```
   .venv/bin/python demo/ard/goose/open-windows.py --rail fake
   ```

   **Expect:** Kestrel's card still counts the lost dispute; the adjudicator's case still shows the ruling; nothing is paid twice. To run deal 1 again, reset and seed first.

## Fallbacks

1. The real rail fails (a wallet error, the buyer too low): quit Goose, open the simulated rail, use its opening line.

   ```
   osascript -e 'quit app "Goose"'
   .venv/bin/python demo/ard/goose/open-windows.py --rail fake
   ```

2. Without Goose: the same two deals in one terminal. Enter moves on; each dialog is a yes or no at the prompt; Ctrl-C ends it.

   ```
   (cd demo/ard && ../../.venv/bin/python demo.py run --rail fake)
   ```

## After the run: shut down and reset

1. Quit Goose, then reset.

   ```
   osascript -e 'quit app "Goose"'
   (cd demo/ard && ../../.venv/bin/python demo.py reset)
   ```

   **Expect:** "removed …" and "cleared Goose's trust in the N recipes trusted since this home's windows first opened …".

2. Check that nothing of the demo is left running.

   ```
   ps -ax | grep -E "[d]emo/ard"
   ```

   **Expect:** nothing printed.

3. [Real] The wallets are not reset: a real payment stays paid, and both balances stay as they are.

4. Opening Goose normally uses your own settings again.

5. Optional: remove the demo entirely.

   ```
   rm -rf ~/ard-demo ~/.config/ard-commerce-goose
   ```

## Troubleshooting

1. **Reset refuses.** It names the process holding the demo home or the stage's ports. Close it (a terminal: `cd ~`), or stop the process it names, then reset again. Reset changes nothing when it refuses. An app with a folder of the demo home open counts too. A `stage.py` left from an earlier run is stopped by reset itself.

2. **Seed says a card counts fewer than 24 held after 5 minutes.** The checkpoints did not reach the witness: check the network, or set `ARD_WITNESS=off`, then reset and seed.

3. **A command says a variable is not set.** Copy the export line it prints, put in your own paths, and run it again.

4. **The adjudicator's case says Kestrel Print: no answer yet.** Kestrel's window is not running: open it and ask again. The case can still be ruled on from Maya's answer, which carries the records Kestrel signed that she holds, its delivery record among them.
