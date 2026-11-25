# Reproducing the ARD Deal

How to run the ARD two-seller deal on your own Mac: three Goose Desktop windows, one buyer agent and two seller agents, that find each other through ARD, compare signed deal histories, and settle one payment. The simulated rail is the default; the real rail steps are marked Real.

evidencebook-skills a4e554d · evidencebook 5d29ccc · capsulectl-deal v0.1.0-rc50 · capsule-engine b84d7d0 (go/v0.7.0) · capsule-viewer 89b75d6 (ts/v0.25.0: the receipt pages, and the History page vendors 0.25.0) · Goose Desktop 1.59.2 · real rail: ln-pay-local 025d566

Plain-text copy of the reproduction guide, for tools and terminals: [demo/ard/RUNBOOK.md](https://github.com/action-state-group/evidencebook-skills/blob/main/demo/ard/RUNBOOK.md).

Status: run by hand at 28118b6 on the simulated rail with `ARD_LIMIT_MSAT=2000` (Steven, 2026-11-24, Goose Desktop 1.59.2, macOS, a new demo home): steps 1 to 19 except step 16 and the optional steps, both orders' one dialog, the second order's Decline (nothing paid), the fresh yes after it and Approve, and both receipts' approval lines. That run found one wrong line, an extra "another of the rules' checks" reason in each receipt's step 3. Changed since then: that line's fix (Steven's patch, evidencebook-skills#237), the History page on capsule-viewer 0.25.0 (#271), and the locked agent (#279: each window's agent gets only ToolSearch and its own ard tools, checked by hand in Maya's window of Goose Desktop at 56aea1e on 2026-11-24, step 9's tool list). The full run has not been done by hand at this pin (a4e554d), and the real-payment steps have not been run at these pins at all. An earlier run at 859c27b plus fixes covered setup from a clean Goose with Goose on its own settings folder (GOOSE_PATH_ROOT) and the pinned adapter found through GOOSE_SEARCH_PATHS. The demo's automated tests pass at these pins in CI.

## What you will see

Maya needs 200 conference badges by Friday, under 3,000 msat (a msat is a thousandth of a satoshi). Two sellers offer them: Kestrel Print at 1,000 msat and Alder Print Co. at 2,000 msat. Maya's agent decides on each seller's signed history, not only on price. The run has six steps:

1. **Discovery.** Maya's agent searches a local stand-in ARD registry, then fetches each seller's own entry and checks its signed commitment.

2. **History cards.** Each seller answers with its History card over a local relay: Alder 0 of 24 deals did not hold, Kestrel 2 of 24, as Kestrel itself reported. A card's signature shows who wrote the history and that it is unchanged since; it does not show that the deals happened.

3. **Assessment.** Maya's agent assesses both with her admission pack (the rule file). At the starting rule (at most 100 of every 1,000 deals not held) both pass; tightened to 50, Alder passes (GO) and Kestrel is limited (LIMIT: deals under 1,000 msat only).

4. **Recommendation and pick.** Maya's agent recommends; Maya picks. Picking Kestrel opens no deal and pays nothing. Picking Alder seals the pick.

5. **Payment.** A macOS dialog asks you to approve 2,000 msat. Only your click releases the payment: each agent has only its own ard tools, which the demo enforces (its locked Claude Code adapter gives an agent no shell, file, web or connector tool and none of your own Claude Code settings); by default the payment is simulated and no money moves.

6. **Receipts.** Each side keeps its own record. Maya's card shows 1 deal, Alder's 25, each deal row reads time-stamped by Action State's hosted witness (a hosted witness, run by Action State, not independent of us), and the live deal's row has an Open receipt link (a demo link, with the line "Demo link to this party's receipt page; the History card itself carries no link."). With a spending limit set, a second order is held for the person's OK at Maya's deal check, and each side can open a receipt page.

The registry, the seller sites and the 48 sample deals are local stand-ins. The ARD search call, fetching each seller's entry, the signature checks, the assessment and the deal records are the real code.

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

1. Clone and build everything under `~/ard-demo` (about 5 minutes). Another folder works if you change the paths in the next section to match. Paste each of the four blocks below into the same terminal window, one block at a time, and wait for each to finish before pasting the next.

   ```
   mkdir -p $HOME/ard-demo/bin && cd $HOME/ard-demo
   git clone -q https://github.com/action-state-group/evidencebook-skills
   git -C evidencebook-skills checkout -q a4e554d5e21847588c40e929005645c8df5cfe07
   git clone -q https://github.com/action-state-group/evidencebook
   git -C evidencebook checkout -q 5d29ccc5240bfe1d5d8b926dd5763d5882a30ea9
   git clone -q https://github.com/action-state-group/capsule-engine
   git -C capsule-engine checkout -q b84d7d0f2d48f9acdf79880dc1e3fa059aba1355
   (cd capsule-engine/go && GOTOOLCHAIN=auto go build -o $HOME/ard-demo/bin/capsule-engine ./cmd/capsule-engine)
   ```

   ```
   mkdir -p $HOME/ard-demo/dl && cd $HOME/ard-demo/dl
   curl -fsSLO https://github.com/action-state-group/evidencebook/releases/download/capsulectl%2Fv0.1.0-rc50/SHA256SUMS
   curl -fsSLO https://github.com/action-state-group/evidencebook/releases/download/capsulectl%2Fv0.1.0-rc50/capsulectl-deal-v0.1.0-rc50-darwin-arm64
   cd $HOME/ard-demo
   ```

   ```
   (cd $HOME/ard-demo/dl && grep ' capsulectl-deal-v0.1.0-rc50-darwin-arm64$' SHA256SUMS | shasum -a 256 -c - && install -m 755 capsulectl-deal-v0.1.0-rc50-darwin-arm64 $HOME/ard-demo/bin/capsulectl-deal)
   ```

   **Check before the next block:** this must print `capsulectl-deal-v0.1.0-rc50-darwin-arm64: OK`. On `FAILED`, nothing was installed: stop here.

   ```
   cd $HOME/ard-demo/evidencebook-skills && python3 -m venv .venv
   .venv/bin/pip install -q ../evidencebook/python pyyaml rfc8785 websockets "mcp==2.3.0" "capsule-viewer @ git+https://github.com/action-state-group/capsule-viewer@89b75d6ab5f34bada727082758562071d494ce0b"
   ```

   **Expect:** pip ends with no error.

2. Already cloned? Move the checkout to this pin instead, then rerun the pip line from step 1, so the venv gets the pinned capsule-viewer. Without it, an earlier capsule-viewer stays installed and the receipt pages are the old ones (evidencebook-skills#239).

   ```
   git -C $HOME/ard-demo/evidencebook-skills fetch -q origin && git -C $HOME/ard-demo/evidencebook-skills checkout -q --detach a4e554d5e21847588c40e929005645c8df5cfe07
   cd $HOME/ard-demo/evidencebook-skills && .venv/bin/pip install -q ../evidencebook/python pyyaml rfc8785 websockets "mcp==2.3.0" "capsule-viewer @ git+https://github.com/action-state-group/capsule-viewer@89b75d6ab5f34bada727082758562071d494ce0b"
   ```

   **Expect:** pip ends with no error.

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

7. **Required, so the payment dialog holds (an agent with screen control could click it itself):** in that Goose, Extensions (in the left sidebar in Goose 1.59.2), turn off every extension: Analyze, Apps, Developer, Extension Manager, Skills, Summon and Top Of Mind. Each card drops from Default Extensions down to Available as you switch it off, so the next switch slides under the cursor: check each one. The demo's own extensions (ard_maya, ard_alder, ard_kestrel) are not there yet: each window brings its own. Scheduler is a Goose setting, not one of these extensions, and stays on in `config.yaml` (`scheduler: enabled: true`); the hand run left it on.

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
     CAPSULE_ENGINE=$HOME/ard-demo/bin/capsule-engine \
     CAPSULECTL_DEAL=$HOME/ard-demo/bin/capsulectl-deal
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

1. Quit Goose, then reset: it stops the demo's processes, deletes the demo home and clears Goose's trust in the demo's own recipes, so each window asks Trust and Execute again. Goose keeps recipe trust in one place for the demo's Goose and your own; reset deletes only the trust files of the recipes open-windows.py opened (it computes their names the way Goose 1.59.2 does), so a recipe you trusted keeps its trust. The demo home is `~/.config/ard-commerce-demo`.

   ```
   osascript -e 'quit app "Goose"'
   (cd demo/ard && ../../.venv/bin/python demo.py reset)
   ```

   **Expect:** "removed …" and "cleared Goose's trust in N of the demo's recipes …", or, when none of them is trusted (the first reset, say), "deleted no Goose recipe trust …". If it refuses, it says what to stop.

2. Make the sample history (about 20 s).

   ```
   (cd demo/ard && ../../.venv/bin/python demo.py seed)
   ```

   **Expect:** 24 deals per seller; 2 of Kestrel's noted as not held.

3. [Real] Read both balances.

   ```
   ln-pay-local balance --wallet "$ARD_WALLET_BUYER"; ln-pay-local balance --wallet "$ARD_WALLET_SELLER"
   ```

   **Expect:** buyer `spendable_msat` at least 2,100 (2,000 plus Lexe's 100 msat minimum send fee).

4. [Real] Open the three windows (it refuses while Goose runs, then starts the demo's own Goose): the sellers, then Maya, tiled with Maya on the left half. The first time, macOS asks to let your terminal control System Events and to turn it on under Accessibility: allow both. Each window is a Goose recipe that starts its own copy of the demo's tool server for one party.

   ```
   .venv/bin/python demo/ard/goose/open-windows.py --rail local
   ```

   **Expect:** three windows, each with a Trust prompt. If tiling fails while macOS asks, the script tries again every 10 s, twice.

5. [Simulated] Or, simulated: the same, and no money moves.

   ```
   .venv/bin/python demo/ard/goose/open-windows.py --rail fake
   ```

6. If the windows are still not tiled: allow the access, click Maya's window, then run this (it tiles the open windows, no new ones). The script prints the same line.

   ```
   osascript -e 'tell application "System Events" to set frontmost of process "Goose" to true' -e 'tell application "System Events" to tell process "Goose" to click menu item "Left & Quarters" of menu "Move & Resize" of menu item "Move & Resize" of menu "Window" of menu bar 1'
   ```

   **Expect:** Maya on the left half, the sellers on the right quarters. By hand: Window, Move & Resize, Left & Quarters.

7. Optional: see what each agent is given. Write `local` or `fake` for the rail you opened. It prints each recipe's facts and first message and checks that it carries the skill file from this checkout word for word.

   ```
   .venv/bin/python demo/ard/goose/open-windows.py --rail local --print | .venv/bin/python -c '
   import sys, json, base64, hashlib, re
   for name, line in zip(["Alder", "Kestrel", "Maya"], sys.stdin):
       c = line.strip().split("config=", 1)[1]
       r = json.loads(base64.urlsafe_b64decode(c + "=" * (-len(c) % 4)))
       head, body = r["instructions"].split("\n\n", 1)
       facts, rail, follow = head.split("\n")
       skill, commit = re.match(r"Follow the (\S+) skill below at evidencebook-skills (\w+)", follow).groups()
       repo = open("skills/" + skill + "/SKILL.md").read()
       repo = repo.split("\n---\n", 1)[1] if repo.startswith("---\n") else repo
       print("== " + name + ": " + r["title"])
       print("   extensions: " + ", ".join(e["name"] for e in r["extensions"]))
       print("   facts: " + facts)
       print("   first message: " + r["prompt"])
       print("   skill: skills/" + skill + "/SKILL.md at " + commit + ", sha256 " + hashlib.sha256(body.strip().encode()).hexdigest()[:12] + ", matches the repo file exactly: " + ("yes" if body.strip() == repo.strip() else "NO"))
   '
   ```

   **Expect:** Alder at 2,000 msat, Kestrel at 1,000 msat, Maya's first message only saying she is ready, and "matches the repo file exactly: yes" at a4e554d.

8. Click Trust and Execute in all three windows, in any order.
   **Expect:** Alder 24 deals, all held; Kestrel 24, 22 held; Maya only says she is ready and searches nothing.

9. **Required:** in each window open Extensions: only its own `ard_maya`, `ard_alder` or `ard_kestrel` is on (the extensions icon under the chat box shows 1). Turn anything else off before you type the ask. The payment dialog holds only for agents limited to their own ard tools: the demo's locked adapter (`demo/ard/goose/locked`, which open-windows.py starts Goose with) gives each agent only ToolSearch and its own ard tools. To see it, type `List every tool you have by exact name, including deferred ones.` in any window before the ask. **Expect:** ToolSearch and that window's own `mcp__ard_…` tools, nothing else (no Bash, Write, WebFetch or connector tools).

10. Keep the screen awake and unlocked: the payment dialog appears on it.

## The run

Type in Maya's window, one message at a time; each step takes 30 to 60 s. Cmd+` moves between windows.

1. [Real] Say the opening line.

   ```
   This is sample history, and the payment is real: a small Lightning payment of 2,000 millisatoshis, 2 sats, between our own test wallets.
   ```

2. [Simulated] Say the opening line.

   ```
   This is sample history, and the payment is simulated: no money moves.
   ```

3. Once both sellers have answered, paste the ask into Maya's window.

   ```
   I am Maya. I need 200 conference badges by Friday, under 3,000 msat (a msat is a thousandth of a satoshi: a token amount). Find sellers for me.
   ```

   **Expect:** the search, then both sellers' entries and signatures checked: Alder 2,000 msat, Kestrel 1,000 msat.

4. Say the registry line.

   ```
   The registry, the seller domains and the listings are local stand-ins we set up. What runs for real is the ARD search call, fetching the seller's own entry, the comparison, and the check of the signed commitment. Only the crawler is missing.
   ```

5. Optional, in a terminal: what the search returns and what each seller publishes.

   ```
   curl -s -X POST http://127.0.0.1:47481/search -H 'Content-Type: application/json' -d '{"query": {"text": "conference badges print"}, "federation": "none", "pageSize": 10}' | jq
   curl -s http://127.0.0.1:47491/.well-known/ard.json | jq
   curl -s http://127.0.0.1:47492/.well-known/ard.json | jq
   ```

   **Expect:** both sellers in the search result; each seller's ard.json names the digest of its signed commitment.

6. Type in Maya's window. A card's signature shows who wrote the history and that it is unchanged since; it does not show that the deals happened.

   ```
   Show me each seller's History card.
   ```

   **Expect:** Alder 0 of 24 deals did not hold; Kestrel 2 of 24, as Kestrel itself reported.

7. The same cards as pages: Cmd+` to Alder's window, then Kestrel's, and type in each.

   ```
   Open my History card as a page.
   ```

   **Expect:** the browser opens that seller's History card page; every deal row, the sample deals included, has an "Open receipt" link (each is a closed two-party deal, so each has a receipt page). A sample deal's receipt says "Sample history: ... (sample deal made up for this demo: no money moved).". Then Cmd+` back to Maya's window.

8. Type. The assessment's inputs come from a demo adapter, and the screen says what it counted, for example "selection: signed answer, no inclusion proofs; this pack counts it". Maya's agent recommends; Maya picks.

   ```
   Assess both sellers, and tighten the rule to at most 50 of every 1,000 deals not holding.
   ```

   **Expect:** at 100 both GO; at 50 Alder GO, Kestrel LIMIT (deals under 1,000 msat).

9. Type.

   ```
   Pick Kestrel Print, the cheaper one.
   ```

   **Expect:** the pick is sealed first ("pick sealed before any payment"), then LIMIT: 1,000 msat is at or over this seller's limit; no deal opens and nothing is paid.

10. Type.

   ```
   Pick Alder Print Co.
   ```

   **Expect:** the pick is sealed, and Maya asks before paying.

11. [Real] Wallets before the payment.

   ```
   ln-pay-local balance --wallet "$ARD_WALLET_BUYER"; ln-pay-local balance --wallet "$ARD_WALLET_SELLER"
   ```

   **Expect:** each prints `{"spendable_msat": N, "lightning_balance_msat": M}`.

12. Type, then wait for the macOS dialog (it waits 3 minutes). Only your click releases the payment.

   ```
   Yes, pay it.
   ```

   **Expect:** real rail "Pay Alder Print Co. 2,000 msat over Lightning: this moves real money, to a wallet Alder Print Co. and Kestrel Print share."; simulated "Pay Alder Print Co. 2,000 msat on the simulated rail: no money moves."

13. Optional refusal: click Cancel, type `Yes, pay Alder`, answer Maya's question with `Yes.`
   **Expect:** Maya says nothing was paid, asks the payment question again, then a new dialog opens.

14. Click Pay.
   **Expect:** invoice 2,000 msat, succeeded, deal closed, both parties' records compared.

15. Type. Verified means the verifier (capsulectl-deal) returned VALID for the bundle behind the page against its deal records; it checks that copy of the records, not the seller.

   ```
   Show your History card, then open your History card and your receipt as pages.
   ```

   **Expect:** 1 deal, held; the receipt page's top line says Verified, "Checked by capsulectl verify --bundle: graph closure, interval coverage, per record membership, checkpoint, producer signatures (all verified)."; then 2,000 msat, Closed; on the simulated rail it says once, near the top, "Test money: this deal's payment was on a simulated rail. No real money moved."; the "Step" header of the records table under "Verify" reads on one line; with no limit set, step 4 reads "Approved by you" (your Pay click); with the spending limit below set before the run, step 3 reads "Checked against the Everyday Rules (0.3.8) and your spending limit: a seller you have not paid before, a payment that cannot be undone and more than a quarter of the price paid up front, which need your approval" and step 4 "Held for your approval, then approved by you"; it says "This copy carries no witness receipt." and that the other party's signed half is in their own copy; once the card's checkpoint is witnessed and covers the deal, it adds that the hosted witness stamped the History checkpoint taken at a named time (checkpoint number and UTC time), which covers this deal as of that checkpoint, and that the card shows the newest checkpoint.

16. Cmd+` to Alder's window, same message.
   **Expect:** 25 deals, all held; receipt page Verified with the same top line, Sale receipt, 2,000 msat agreed, with "The payment proof is in the buyer's records, not this copy." and Alder's own sentence about the payment: on the simulated rail it is tagged "simulated rail: no money moved"; on the real rail it names rail lightning and adds the credit note. If it shows 24, ask again in a few seconds.

17. [Real] Wallets after.

   ```
   ln-pay-local balance --wallet "$ARD_WALLET_BUYER"; ln-pay-local balance --wallet "$ARD_WALLET_SELLER"
   ln-pay-local payments --wallet "$ARD_WALLET_BUYER" --limit 1; ln-pay-local payments --wallet "$ARD_WALLET_SELLER" --limit 1
   ```

   **Expect:** buyer outbound 2,000 msat succeeded; seller inbound about 1,900 msat with a fee of about 100. Not yet seen at these pins: read the real figures out.

## The spending limit: a second order is held for your OK (needs capsule-engine go/v0.7.0)

Before the run, in the shell that starts the windows, set the limit to the first order's price, then open the windows as in the steps above:

   ```
   export ARD_LIMIT_MSAT=2000
   ```

18. After step 16, in Maya's window type:

   ```
   Order 200 more badges from Alder Print Co.
   ```

   **Expect:** Maya asks first, in one sentence naming Alder Print Co., 2,000 msat and the rail, with "Want me to order again?" (the dialog is the second check, never the only one). Answer:

   ```
   Yes.
   ```

   **Expect:** one dialog after Maya's deal check, titled "The Everyday Rules held this order for your OK", with the buttons Don't buy (the default) and Buy anyway. Its text, one line each: "200 conference badges, delivered by Friday from Alder Print Co. for 2,000 msat, on the simulated rail: no money moves. Nothing has been paid yet.", "Over your weekly limit: 4,000 msat with this order, limit 2,000 msat", "The payment is not refundable", "More than a quarter of the price paid up front (2,000 msat)", "The same act was taken in another deal inside the window", and "Your answer is saved on the receipt. Change your rules any time in Everyday Rules." On the real rail the first line reads "..., over Lightning: this moves real money, to a wallet Alder Print Co. and Kestrel Print share. Nothing has been paid yet." Say aloud: every rule that asks is in this one question, and nothing is paid until the answer. When the weekly limit is the only reason, the question is Steven's limit question instead (not reached in this run, where rules 8 and 22 ask on every order): titled "This order goes over your weekly limit", with "Spent this week", "With this order" and "Your weekly limit" in place of the reasons, and "Change your limit any time in Everyday Rules." With the limit set, the first order (step 12) is the same one dialog, with that order's reasons ("No earlier payment to this merchant from this profile", "The payment is not refundable", "More than a quarter of the price paid up front (2,000 msat)"), in place of the payment dialog.

   Click Don't buy.
   **Expect:** nothing is paid, Maya tells you every reason the dialog listed, one per line ("Held for your OK at deal check, nothing paid. …"), without naming any tool, the wallet balances do not change and Maya's History card still counts 1 deal.

   Ask for the order again:

   ```
   Order 200 more badges from Alder Print Co.
   ```

   **Expect:** no dialog yet: Maya asks once more, "Want me to order again?", naming Alder Print Co., 2,000 msat and the rail (the fresh yes after Don't buy). Answer:

   ```
   Yes.
   ```

   **Expect:** the same dialog as above, with no second question (the payment tool refuses the first call after Don't buy, and Maya, who asked you since, calls it again at once). Click Buy anyway: the screen says "You approved this held order (…). Paying now." and the payment goes on. The approval is sealed in the deal's own records (and as a note in Maya's book). Open this deal's receipt (step 19): step 3 reads "Checked against the Everyday Rules (0.3.8) and your spending limit: over your limit, a payment that cannot be undone, more than a quarter of the price paid up front and a repeat of a recent payment to this seller, so the order was held for your approval" and step 4 "Held by your spending limit, then approved by you". Run by hand at 28118b6 (Steven, 2026-11-24) with the earlier dialog ("Held for your OK", Decline and Approve): Decline, the fresh yes and Approve as above; step 3 then carried an extra "another of the rules' checks", fixed since in #237. Not yet run by hand with this dialog (evidencebook-skills#270).

19. Open Maya's History page again (`Show your History card, then open your History card as a page.`).
   **Expect:** the live deal's row has "Open receipt" with the line "Demo link to this party's receipt page; the History card itself carries no link." under it; click it: the receipt page opens. Each row reads time-stamped by Action State's hosted witness once a checkpoint with a receipt covers it (a minute or so); with no network, or `ARD_WITNESS=off`, it reads unwitnessed.

## Quit and re-entry

1. Quit Goose (Cmd+Q) and reopen on the same home, same rail, without reset.

   ```
   .venv/bin/python demo/ard/goose/open-windows.py --rail local
   ```

   **Expect:** Alder 25 deals, all held; Kestrel 24; Maya says she is ready again; nothing is paid twice.

## Fallbacks

1. The real rail fails (a wallet error, the buyer too low): quit Goose, open the simulated rail, use its opening line.

   ```
   osascript -e 'quit app "Goose"'
   .venv/bin/python demo/ard/goose/open-windows.py --rail fake
   ```

2. Without Goose: the same deal in a terminal, with a browser popup for the pick and the payment. Enter moves on; Ctrl-C ends it.

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
   pgrep -fl demo/ard
   ```

   **Expect:** nothing printed.

3. [Real] The wallets are not reset: a real payment stays paid, and both balances stay as they are.

4. Opening Goose normally uses your own settings again.

5. Optional: remove the demo entirely.

   ```
   rm -rf ~/ard-demo ~/.config/ard-commerce-goose
   ```

## Troubleshooting

1. **Reset refuses.** It names the process holding the demo home or the stage's ports. Close it (a terminal: `cd ~`), or stop the process it names, then reset again. Reset changes nothing when it refuses. An app with a folder of the demo home open counts too: on 2026-11-24 a Claude chat with `~/.config/ard-commerce-demo` connected as a folder held it (the process named was Claude's VM). Remove the folder from that chat, or quit the app, then reset. A `stage.py` left from an earlier run is stopped by reset itself.

2. **Seed refuses with "sample history was made at … msat".** The home was seeded at older prices. Run reset, then seed.

3. **A command says a variable is not set.** Copy the export line it prints, put in your own paths, and run it again.

4. **A window shows nothing new.** Bring it to the front (Cmd+`); a background window may not draw its reply.

5. **Maya finds only one seller.** A seller publishes its entry with its first message. Wait until both seller windows have answered, then ask again.

6. **Goose asks Trust and Execute again.** Expected after every reset: reset clears the trust in the demo's recipes.
