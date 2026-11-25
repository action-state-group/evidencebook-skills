# Reproducing the ARD Deal

How to run the ARD two-seller deal on your own Mac: four Goose Desktop windows, one buyer agent, two seller agents and the adjudicator's assistant. The buyer finds the sellers through ARD and reads their signed History cards. In the first deal the cheaper seller ships short, the buyer disputes, and the adjudicator rules against the seller. In the second deal the seller's card and the buyer's own records show that ruling, and the buyer buys from the other seller. The simulated rail is the default; the real rail steps are marked Real.

This guide runs evidencebook-skills main. The other repositories are pinned: capsule-cli 0043a944 (capsulectl v0.1.0-main.0043a944, with evidencebook's book and deal plugins installed at the same version) · evidencebook 1372f2e (main, with #935's receipt page and #933's `deal tick --now`; the book and deal plugins are built from it) · capsule-engine 0263ff1 (go/v0.8.0) · capsule-viewer 1259579 (main, with #427's local times on the receipt page; the History page vendors its 0.27.2 script) · Goose Desktop 1.59.2 · real rail: ln-pay-local 4b936bb

Status: run by hand on 2026-11-25 on a Mac at evidencebook-skills cd33ab8, evidencebook 45eaceb and capsule-viewer d56da4d: steps 1 to 15 passed, then the re-entry (Goose quit and reopened, no reset). Changed since, not yet run by hand: the 10-minute dialogs, local times, both agents' ruling and witness wording (#305); the buyer's agent asks before saying it received what it paid for (#306); a ruling the witness stamps late is sent again with its time (#308); this set-up (#311); and the receipt page, capsulectl's own `deal report --html` (evidencebook#935) drawn by capsule-viewer 130877b (#310). Open: the windows open stacked, not tiled. The spending-limit section returns when the Everyday Rules run as the buyer's pinned rules checker on these deals (evidencebook#890).

## What you will see

Maya needs 200 conference badges by Friday, under 3,000 msat (a msat is a thousandth of a satoshi). Two sellers offer them: Kestrel Print at 1,000 msat and Alder Print Co. at 2,000 msat. Both start with 12 sample deals, all held, and no disputes. Each seller's offer and what it discloses to a buyer are in its own file, `demo/ard/sellers/kestrel.yaml` and `alder.yaml`. Edit one, then reset and seed: the seller signs a new commitment from what it discloses, and its ARD entry lists the new offer. The steps below quote today's values. Maya's budget stays 3,000 msat, and the story needs Kestrel to be the cheaper seller.

1. **Discovery.** Maya's agent searches a local stand-in ARD registry, then fetches each seller's own entry and checks its signed commitment.

2. **History cards.** Each seller's card: 12 deals, every one went as agreed, no disputes. A card's signature shows who wrote the counts and that they are unchanged since; these are the seller's own counts.

3. **Deal 1.** Both sellers are "Good to buy"; Maya picks Kestrel, the cheaper one, and pays 1,000 msat (a dialog asks you first). Kestrel's own delivery record says 150 of 200 badges were shipped. Maya disputes the delivery.

4. **The adjudicator.** The adjudicator asks each side for its books, and each side's agent answers on its own: its own book and the copy it holds of the other side's. The adjudicator's window shows the case and Kestrel's own signed delivery record. You rule against Kestrel in a dialog. The adjudicator is run by the operator, who also runs every party here, so it is not independent of them. Both parties enter the ruling in their own records.

5. **Deal 2.** Kestrel's card now counts 13 deals, 1 that didn't go as agreed, 1 dispute decided against it. Maya's own records hold the ruling, so her rules give Kestrel "Not from this seller" (NO). Alder is "Good to buy"; Maya buys from Alder, and Alder ships all 200.

The registry, the seller sites and the 24 sample deals are local stand-ins, and the adjudicator runs on this Mac. The ARD search call, fetching each seller's entry, the signature checks, the assessment, every deal record (capsulectl-deal), the dispute and the ruling (capsulectl-deal's `deal respond` and `deal ruling`, the adjudicator's own profile) are the real code.

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

Paste each block into the same terminal window, one at a time, and wait for each to finish before the next. Every block can be run again: it leaves what is already right and moves the rest.

1. Install the build tools. GNU tar is needed because the plugin build script refuses macOS's own tar.

   ```
   brew install go gnu-tar
   ```

2. Get the code: evidencebook-skills at main, and the other repositories at their pins. This block clones what is missing and moves what is already there, so it is the same on a new Mac and on one that ran an earlier version of this guide.

   ```
   mkdir -p $HOME/ard-demo && cd $HOME/ard-demo
   [ -d evidencebook-skills ] || git clone -q https://github.com/action-state-group/evidencebook-skills evidencebook-skills; git -C evidencebook-skills fetch -q origin; git -C evidencebook-skills checkout -q --detach origin/main
   [ -d evidencebook ] || git clone -q https://github.com/action-state-group/evidencebook evidencebook; git -C evidencebook fetch -q origin 1372f2ea75c2bc9c884dd701307ab3b1be92fa1e; git -C evidencebook checkout -q 1372f2ea75c2bc9c884dd701307ab3b1be92fa1e
   [ -d capsule-cli ] || git clone -q https://github.com/action-state-group/capsule-cli capsule-cli; git -C capsule-cli fetch -q origin 0043a944b22dc25515f1440169fcdabfd345750b; git -C capsule-cli checkout -q 0043a944b22dc25515f1440169fcdabfd345750b
   [ -d capsule-engine ] || git clone -q https://github.com/action-state-group/capsule-engine capsule-engine; git -C capsule-engine fetch -q origin 0263ff119911d91eb54dd3d3debdcc71324042eb; git -C capsule-engine checkout -q 0263ff119911d91eb54dd3d3debdcc71324042eb
   ```

   **Expect:** no output.

3. Build and install capsulectl with its book and deal plugins, all at one version (about 5 minutes). It installs into `~/.local`.

   ```
   cd $HOME/ard-demo && export GOTOOLCHAIN=auto TAR=gtar PATH="$HOME/.local/bin:$PATH"
   CORE_SHA=0043a944b22dc25515f1440169fcdabfd345750b EB_SHA=1372f2ea75c2bc9c884dd701307ab3b1be92fa1e V=v0.1.0-main.0043a944 P=darwin-arm64 PKG=github.com/action-state-group/capsule-cli/cli
   mkdir -p $HOME/.local/bin $HOME/.local/lib/capsulectl/plugins
   (cd capsule-cli && scripts/release-build.sh "$V" "$CORE_SHA" "$HOME/ard-demo/core" > /dev/null)
   install -m 0755 "$HOME/ard-demo/core/capsulectl-$V-$P" $HOME/.local/bin/capsulectl
   evidencebook/capsulectl/scripts/release-build.sh "$V" "$EB_SHA" "$HOME/ard-demo/dist" > /dev/null
   for l in book deal; do (cd evidencebook/capsulectl && CGO_ENABLED=0 go build -trimpath -buildvcs=false -ldflags "-s -w -buildid= -X $PKG.CLIVersion=$V -X $PKG.CLICommit=$CORE_SHA -X $PKG.PluginVersion=$V -X $PKG.PluginCommit=$EB_SHA" -o "$HOME/ard-demo/dist/capsulectl-$l-$V-$P" "./cmd/capsulectl-$l"); done
   capsulectl plugin install "$HOME/ard-demo/dist/capsulectl-book-$V-$P" > /dev/null && capsulectl plugin install "$HOME/ard-demo/dist/capsulectl-deal-$V-$P" > /dev/null
   tar -xzf "$HOME/ard-demo/dist/standard-history-$V.tar.gz" -C $HOME/.local/lib/capsulectl/plugins
   tar -xzf "$HOME/ard-demo/dist/deal-view-$V.tar.gz" -C $HOME/.local/lib/capsulectl/plugins
   capsulectl --version; capsulectl plugin ls | python3 -c 'import json,sys; d=json.load(sys.stdin); print([(p["name"], p["version"]) for p in d["plugins"]], "refused:", d["refused"])'
   ```

   **Expect:** `capsulectl v0.1.0-main.0043a944 (commit 0043a944…)`, then `[('book', 'v0.1.0-main.0043a944'), ('deal', 'v0.1.0-main.0043a944')] refused: []`.

4. Build capsule-engine, and make the Python environment.

   ```
   cd $HOME/ard-demo && mkdir -p bin && (cd capsule-engine/go && GOTOOLCHAIN=auto go build -o $HOME/ard-demo/bin/capsule-engine ./cmd/capsule-engine)
   cd $HOME/ard-demo/evidencebook-skills && python3 -m venv .venv
   .venv/bin/pip install -q cryptography pyyaml rfc8785 "mcp==2.3.0" "capsule-viewer @ git+https://github.com/action-state-group/capsule-viewer@125957929578f651d3ab474c56c87e0ad74b324e"
   .venv/bin/pip install -q --force-reinstall --no-deps "capsule-viewer @ git+https://github.com/action-state-group/capsule-viewer@125957929578f651d3ab474c56c87e0ad74b324e"
   ```

   **Expect:** pip ends with no error. The second line is needed: every capsule-viewer commit carries the same version number, so the first line alone keeps an earlier capsule-viewer.

5. Install Goose Desktop 1.59.2 (Apple silicon), replacing any Goose already in Applications.

   ```
   osascript -e 'quit app "Goose"'
   curl -fsSL -o /tmp/Goose-darwin-arm64.zip https://github.com/aaif-goose/goose/releases/download/v1.59.2/Goose-darwin-arm64.zip
   rm -rf /tmp/goose-1.59.2 && ditto -x -k /tmp/Goose-darwin-arm64.zip /tmp/goose-1.59.2 && rm -rf /Applications/Goose.app && mv /tmp/goose-1.59.2/Goose.app /Applications/
   ```

   **Expect:** `/Applications/Goose.app` exists, and Goose > About Goose shows 1.59.2. Other versions were not tried; the recipe links depend on how 1.59.2 opens them.

6. Install the demo's own Claude Code adapter (ACP) at a pinned version, under ~/ard-demo. **Never install it with npm install -g.** A global install replaces the adapter version other tools on your Mac use; one ACP client stopped working above 0.94.0. open-windows.py points the demo's Goose at this copy (Goose looks in GOOSE_SEARCH_PATHS first). 0.108.0 is the version Goose 1.59.2 ran with when this guide was made.

   ```
   npm install --prefix $HOME/ard-demo/acp @agentclientprotocol/claude-agent-acp@0.108.0
   ```

7. Quit Goose, then start the demo's own Goose. **It runs on its own settings folder, `~/.config/ard-commerce-goose`, so the next two steps never change your own Goose.** Goose 1.59.2 keeps its provider and extension settings under `GOOSE_PATH_ROOT` when it is set; open-windows.py starts Goose with it. Reset never deletes this folder.

   ```
   osascript -e 'quit app "Goose"'
   cd $HOME/ard-demo/evidencebook-skills && .venv/bin/python demo/ard/goose/open-windows.py --goose-only
   ```

   **Expect:** "started the demo's own Goose on …/ard-commerce-goose", and Goose opens on its welcome screen.

8. In that Goose: the window may open small; maximize it. On the welcome screen click Connect to a Provider, type `claude` in the search box to find Claude Code ACP, wait for "ACP adapter found", click Continue. A privacy screen follows (untick "Share anonymous usage data" if you like), then Get Started. Later this lives in Settings, Models. (Goose 1.59.2, hand run 2026-11-24.)
   **Expect:** a chat opens and answers a short message.

9. **Required, so the payment dialog holds (an agent with screen control could click it itself):** in that Goose, Extensions (in the left sidebar in Goose 1.59.2), turn off every extension: Analyze, Apps, Developer, Extension Manager, Skills, Summon and Top Of Mind. Each card drops from Default Extensions down to Available as you switch it off, so the next switch slides under the cursor: check each one. The demo's own extensions (ard_maya, ard_alder, ard_kestrel, ard_adjudicator) are not there yet: each window brings its own. Scheduler is a Goose setting, not one of these extensions, and stays on in `config.yaml` (`scheduler: enabled: true`); the hand run left it on.

10. Quit that Goose.

   ```
   osascript -e 'quit app "Goose"'
   ```

## Real rail, once

Do a full run on the simulated rail first, then the real rail. This moves real bitcoin on Lightning mainnet. Use new wallets and small amounts. Not yet run at these pins. Lexe's fees, from [docs.lexe.tech/pricing](https://docs.lexe.tech/pricing) (read 2026-11-18; the page says rates may change): receiving payments 0.5%, sending to other Lexe users 0.5% of the payment amount, and "Lightning sends and receives have a minimum fee of ₿0.1 (100 msat …). It only applies to payments under ₿20." At 2,000 msat, 0.5% is 10 msat, so the 100 msat minimum applies on both sides: the buyer needs 2,100 msat and the seller should receive about 1,900.

1. [Real] Install ln-pay-local. ln-pay-local is a small command-line wallet on Lexe's Lightning SDK.

   ```
   [ -d $HOME/ard-demo/ln-pay-local ] || git clone -q https://github.com/action-state-group/ln-pay-local $HOME/ard-demo/ln-pay-local; git -C $HOME/ard-demo/ln-pay-local fetch -q origin 4b936bb164d7dcea4db37075ad336d4a9f2ec102; git -C $HOME/ard-demo/ln-pay-local checkout -q 4b936bb164d7dcea4db37075ad336d4a9f2ec102
   cargo install --path $HOME/ard-demo/ln-pay-local --locked
   ln-pay-local --help
   ```

   **Expect:** one usage line starting `{"error": "usage: ln-pay-local init`.

2. [Real] Make a buyer and a seller wallet. **Each registers a wallet account with Lexe and writes its private seed into its folder, unencrypted: back the folder up, never print or share it.**

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
     CAPSULECTL_DEAL=$HOME/.local/lib/capsulectl/plugins/capsulectl-deal \
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

1. Quit Goose, then reset: it stops the demo's processes, deletes the demo home and clears Goose's trust in the demo's own recipes, so each window asks Trust and Execute again. Goose keeps recipe trust in one place for the demo's Goose and your own; reset deletes only the trust files of the recipes open-windows.py opened (it computes their names the way Goose 1.59.2 does), so any other recipe you trusted keeps its trust. The demo home is `~/.config/ard-commerce-demo`.

   ```
   osascript -e 'quit app "Goose"'
   (cd demo/ard && ../../.venv/bin/python demo.py reset)
   ```

   **Expect:** "removed …" and "cleared Goose's trust in N of the demo's recipes …", or, when none of them is trusted (the first reset, say), "deleted no Goose recipe trust …". If it refuses, it says what to stop.

2. Make the sample history. This is set-up: run it before anyone watches, at least two minutes before you open the windows. It takes about a minute: 12 sample deals per seller, with contest windows of seconds, and one witness stamp per seller. Each card counts its deals held from the first stamp after their windows end, which each seller's window takes as it opens; a window opened sooner waits for that minute and says so.

   ```
   (cd demo/ard && ../../.venv/bin/python demo.py seed)
   ```

   **Expect:** "sample history made and stamped in … s. Each card counts it held from HH:MM:SS". Each party's checkpoints go to Action State's hosted witness (hashes only); with no network, set `ARD_WITNESS=off` first (the cards are then not time-stamped).

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
   **Expect:** Alder and Kestrel each say 12 deals, all held; Maya and the adjudicator's assistant only say they are ready.

8. **Required:** in each window open Extensions: only its own `ard_maya`, `ard_alder`, `ard_kestrel` or `ard_adjudicator` is on (the extensions icon under the chat box shows 1). Turn anything else off before you type. To see what an agent has, type `List every tool you have by exact name, including deferred ones.` in any window. **Expect:** ToolSearch and that window's own `mcp__ard_…` tools, nothing else: Maya's eleven (`ard_find_sellers`, `ard_show_history`, `ard_assess`, `ard_pick`, `ard_pay`, `ard_dispute`, `ard_confirm_received`, `ard_show_card`, `ard_open_card_page`, `ard_show_receipt`, `ard_open_receipt_page`), a seller's five (`ard_seller_activity` and the four card and receipt tools), the adjudicator's three (`ard_case`, `ard_rule`, `ard_case_activity`).

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

   **Expect:** for each: "History card: 12 deals, every one went as agreed. Disputes others raised about it: 0 decided against it, of 0 decided; 0 open." and "Signed by … These are the seller's own counts. Its first 12 deals are sample history the operator made before this run." The witness line reads "this card's time-stamp is not checked here: no receipt for it is available to the buyer yet" (evidencebook#891).

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

6. Type, then wait for the macOS dialog (it waits 10 minutes). Only your click releases the payment.

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

   **Expect:** "This adjudicator is run by the operator, who also runs every party here: it is not independent of the parties.", then "deal …, row delivered: disputed by Maya", "asked both sides for their books at …", "Maya answered at …" and "Kestrel Print answered at …" (each: "own book and the copy held of" the other side's), "Maya's statement on the row: not met" and "Kestrel Print's own signed delivery record: 150 of 200 badges". It waits up to 30 seconds for the answers; if one says "no answer yet", ask again.

10. Type, then answer the dialog.

    ```
    Rule against Kestrel: its own delivery record says 150 of 200.
    ```

    **Expect:** the dialog "Rule on deal …, row delivered: not met, against Kestrel Print. Conflict: the operator runs this adjudicator and every party here, so it is not independent of the parties. Either side may challenge it within 7 days. A challenge is recorded beside the ruling and never replaces it." (default Cancel); click Rule. Then "Ruling recorded … not met, against Kestrel Print" and "Its stamp was taken by Action State's witness; each party's window shows the time it was stamped.", "Sent to both parties; each enters it in its own records." (when the witness is slow or out of reach: "Not yet time-stamped: Action State's witness did not answer within 12 seconds. Both parties have the ruling without a stamp. This window keeps asking for 3 minutes and, once stamped, sends the ruling to both parties again with its stamp. Keep this window open until then. If none comes by then, run this again.").

11. After a few seconds, type `Did both parties enter it?`.
    **Expect:** "Maya: entered" and "Kestrel Print: entered". Cmd+` to Kestrel's window and ask `What happened?` again: "the adjudicator's ruling on deal … entered in this party's records", with the time Action State's witness stamped it.

12. In Kestrel's window, type `Show my History card.`
    **Expect:** "13 deals, 1 didn't go as agreed. Disputes others raised about it: 1 decided against it, of 1 decided; 0 open.", then "Its first 12 deals are sample history the operator made before this run." The card is stamped when you ask, so it counts at once; if the deal's outcome still shows 0 that didn't go as agreed, ask again: it can follow the dispute's count by one stamp.

13. Cmd+` back to Maya's window, type:

    ```
    Order 200 more badges. Show me each seller's History card again, then assess both.
    ```

    **Expect:** Kestrel's card as in step 12; Kestrel "NO: you hold a ruling against this seller (deal …, delivery not met, ruled …). Your rules block a seller you hold a ruling against for 180 days. Its card also counts 1 dispute decided against it, of 1 decided; the card does not say which deal."; Alder "GO".

14. Type `Pick Alder Print Co.`, then `Yes, pay it.` and answer the dialog ("Pay Alder Print Co. 2,000 msat on the simulated rail: no money moves."): click Pay.
    **Expect:** invoice 2,000 msat succeeded, "Alder Print Co.'s delivery record says 200 of 200 badges were shipped." and "Nothing has been sent in Maya's name. If she received it, she can say so, and Alder Print Co. gets her statement that she received what she paid for." Maya's agent sends nothing in her name on its own.

    Then type `I received all 200.` and answer the dialog ("Did you receive what you paid for from Alder Print Co.? Its delivery record says 200 of 200 badges were shipped. Choosing Received sends Alder Print Co. your statement that you received it."): click Received.
    **Expect:** "Maya's statement sent to Alder Print Co.: she received what she paid for." Cancel instead: "Maya chose Cancel, so nothing was sent in Maya's name."

15. Type `Show your History card, then your receipt.`
    **Expect:** Maya's card counts her 2 deals; her receipt reads each row's status as capsulectl reports it (Alder's deal: met so far, as both sides said, still open to dispute until its window ends), "Signed by both sides: the other side's half verifies (capsulectl deal verify).", "Time-stamped by Action State's witness at …" (or, before her next checkpoint reaches the witness, "Not time-stamped yet: the next checkpoint sends it to Action State's witness.") and "Test money: this deal's payment was on a simulated rail. No real money moved." Then type `Open your receipt as a page.` **Expect:** a browser page "Deal report" with "✓ Unchanged since it was sealed", "10 of 10 checks passed", "Time-stamped by Action State's witness at …, as capsulectl verify reported on your own book." and "Signed by both sides: this copy carries the other party's signed agreement, recorded in their own book." Its times are UTC, as the page writes them.

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

   **Expect:** "removed …" and "cleared Goose's trust in N of the demo's recipes …", or, when none of them is trusted (the first reset, say), "deleted no Goose recipe trust …".

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

2. **Seed says a seller's sample deals were not stamped by the witness within their window.** The witness did not take the stamp in time (no network, or it answered slowly): check the network, or set `ARD_WITNESS=off`, then reset and seed.

3. **A command says a variable is not set.** Copy the export line it prints, put in your own paths, and run it again.

4. **The adjudicator's case says Kestrel Print: no answer yet.** Kestrel's window is not running: open it and ask again. The case can still be ruled on from Maya's answer, which carries the records Kestrel signed that she holds, its delivery record among them.

5. **A window shows nothing new.** Bring it to the front (Cmd+`); a background window may not draw its reply.

6. **Maya finds only one seller.** A seller publishes its entry when its window starts. Wait until both seller windows are open, then ask again.

7. **Goose asks Trust and Execute again.** Expected after every reset: reset clears the trust in the demo's recipes. Once, after moving to this version from one before evidencebook-skills#277: the first reset finds no note of the demo's recipes and deletes no trust, so the next windows may open without a Trust prompt; from the next reset on, it is asked again.
