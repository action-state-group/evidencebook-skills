# Reproducing the ARD Deal

How to run the ARD two-seller deal on your own Mac: three Goose Desktop windows, one buyer agent and two seller agents, that find each other through ARD, compare signed deal histories, and settle one payment. The simulated rail is the default; the real rail steps are marked Real.

evidencebook-skills afa24e7 · evidencebook 5d29ccc · capsulectl-deal v0.1.0-rc49 (rc49 or later for the receipt pages) · capsule-engine b84d7d0 (go/v0.7.0) · capsule-viewer 613a8a9 (receipt pages; the History page vendors 0.23.0) · Goose Desktop 1.59.2 · real rail: ln-pay-local 025d566

Plain-text copy of the reproduction guide, for tools and terminals: [demo/ard/RUNBOOK.md](https://github.com/action-state-group/evidencebook-skills/blob/main/demo/ard/RUNBOOK.md).

Status: not yet run by hand at afa24e7, on either rail; the real-payment steps have not been run at these pins at all, and starting Goose on its own settings folder (GOOSE_PATH_ROOT), with the adapter found through GOOSE_SEARCH_PATHS, has not been run by hand. The demo's automated tests pass at these pins in CI.

## What you will see

Maya needs 200 conference badges by Friday, under 3,000 msat (a msat is a thousandth of a satoshi). Two sellers offer them: Kestrel Print at 1,000 msat and Alder Print Co. at 2,000 msat. Maya's agent decides on each seller's signed history, not only on price. The run has six steps:

1. **Discovery.** Maya's agent searches a local stand-in ARD registry, then fetches each seller's own entry and checks its signed commitment.

2. **History cards.** Each seller answers with its History card over a local relay: Alder 0 of 24 deals did not hold, Kestrel 2 of 24, as Kestrel itself reported. A card's signature shows who wrote the history and that it is unchanged since; it does not show that the deals happened.

3. **Assessment.** Maya's agent assesses both with her admission pack (the rule file). At the starting rule (at most 100 of every 1,000 deals not held) both pass; tightened to 50, Alder passes (GO) and Kestrel is limited (LIMIT: deals under 1,000 msat only).

4. **Recommendation and pick.** Maya's agent recommends; Maya picks. Picking Kestrel opens no deal and pays nothing. Picking Alder seals the pick.

5. **Payment.** A macOS dialog asks you to approve 2,000 msat. Only your click releases the payment, as long as each agent has only its own ard tools; by default the payment is simulated and no money moves.

6. **Receipts.** Each side keeps its own record. Maya's card shows 1 deal, Alder's 25, each deal row reads time-stamped by Action State's hosted witness (a hosted witness, run by Action State, not independent of us), and the live deal's row has an Open receipt link (a demo link, with the line "Demo link to this party's receipt page; the History card itself carries no link."). With a spending limit set, a second order is stopped at Maya's deal check, and each side can open a receipt page.

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

   **Expect:** `claude auth status` says you are signed in.

9. [Real] Real rail only: Rust. Check, and install if missing. A real payment also needs a small amount of bitcoin on Lightning.

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

1. Clone and build everything under ~/ard-demo (about 5 minutes). Everything goes under `~/ard-demo`. Another folder works if you change the paths in the next section to match.

   ```
   mkdir -p $HOME/ard-demo/bin && cd $HOME/ard-demo
   git clone -q https://github.com/action-state-group/evidencebook-skills
   git -C evidencebook-skills checkout -q afa24e740bc218979c51910b73d4fdc240d65bc7
   git clone -q https://github.com/action-state-group/evidencebook
   git -C evidencebook checkout -q 5d29ccc5240bfe1d5d8b926dd5763d5882a30ea9
   git clone -q https://github.com/action-state-group/capsule-engine
   git -C capsule-engine checkout -q b84d7d0f2d48f9acdf79880dc1e3fa059aba1355
   (cd capsule-engine/go && GOTOOLCHAIN=auto go build -o $HOME/ard-demo/bin/capsule-engine ./cmd/capsule-engine)
   mkdir -p $HOME/ard-demo/dl && cd $HOME/ard-demo/dl
   curl -fsSLO https://github.com/action-state-group/evidencebook/releases/download/capsulectl%2Fv0.1.0-rc49/SHA256SUMS
   curl -fsSLO https://github.com/action-state-group/evidencebook/releases/download/capsulectl%2Fv0.1.0-rc49/capsulectl-deal-v0.1.0-rc49-darwin-arm64
   cd $HOME/ard-demo
   (cd $HOME/ard-demo/dl && grep ' capsulectl-deal-v0.1.0-rc49-darwin-arm64$' SHA256SUMS | shasum -a 256 -c - \
     && install -m 755 capsulectl-deal-v0.1.0-rc49-darwin-arm64 $HOME/ard-demo/bin/capsulectl-deal)
   cd evidencebook-skills && python3 -m venv .venv
   .venv/bin/pip install -q ../evidencebook/python pyyaml rfc8785 websockets "mcp==2.3.0" \
     "capsule-viewer @ git+https://github.com/action-state-group/capsule-viewer@613a8a95144e5851bbb61df72df8cc76b7500381"
   ```

   **Expect:** the checksum line prints `capsulectl-deal-v0.1.0-rc49-darwin-arm64: OK` (on `FAILED` nothing is installed: stop and do not continue); pip ends with no error. Each checkout prints a detached HEAD note; that is expected.

2. Already cloned? Move the checkout to this pin instead.

   ```
   git -C $HOME/ard-demo/evidencebook-skills fetch -q origin && git -C $HOME/ard-demo/evidencebook-skills checkout -q --detach afa24e740bc218979c51910b73d4fdc240d65bc7
   ```

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

6. In that Goose: on the welcome screen choose Other Providers, then Claude Code ACP, Configure, Submit. Later this lives in Settings, Models.
   **Expect:** a chat opens and answers a short message.

7. **Required, so the payment dialog holds (an agent with screen control could click it itself):** in that Goose, Settings, Extensions, turn off every extension: Analyze, Apps, Developer, Extension Manager, Skills, Summon and Top Of Mind. Each card drops from Default Extensions down to Available as you switch it off, so the next switch slides under the cursor: check each one. The demo's own extensions (ard_maya, ard_alder, ard_kestrel) are not there yet: each window brings its own.

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

1. Quit Goose, then reset: it stops the demo's processes, deletes the demo home and clears the recipe trust given since the demo's windows first opened: the demo's three recipes, and any other recipe you trusted in the meantime. Goose keeps recipe trust in one place for both, so this also applies to your own Goose. The demo home is `~/.config/ard-commerce-demo`. Reset knows the demo's trust because open-windows.py notes Goose's trust before it first opens the windows.

   ```
   osascript -e 'quit app "Goose"'
   (cd demo/ard && ../../.venv/bin/python demo.py reset)
   ```

   **Expect:** "removed …" and "cleared Goose's trust in the N recipes trusted since this home's windows first opened …". Recipes you trusted before the demo's windows first opened keep their trust; any recipe trusted since then is cleared too. A home with no note keeps all trust, and reset says so. If it refuses, it says what to stop.

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

   **Expect:** Alder at 2,000 msat, Kestrel at 1,000 msat, Maya's first message only saying she is ready, and "matches the repo file exactly: yes" at afa24e7.

8. Click Trust and Execute in all three windows, in any order.
   **Expect:** Alder 24 deals, all held; Kestrel 24, 22 held; Maya only says she is ready and searches nothing.

9. **Required:** in each window open Extensions: only its own `ard_maya`, `ard_alder` or `ard_kestrel` is on. Turn anything else off before you type the ask. The payment dialog holds only for agents limited to their own ard tools.

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

   **Expect:** the browser opens that seller's History card page. Then Cmd+` back to Maya's window.

8. Type. The assessment's inputs come from a demo adapter, and the screen says what it counted, for example "selection: signed answer, no inclusion proofs; this pack counts it". Maya's agent recommends; Maya picks.

   ```
   Assess both sellers, and tighten the rule to at most 50 of every 1,000 deals not holding.
   ```

   **Expect:** at 100 both GO; at 50 Alder GO, Kestrel LIMIT (deals under 1,000 msat).

9. Type.

   ```
   Pick Kestrel Print, the cheaper one.
   ```

   **Expect:** LIMIT: 1,000 msat is at or over this seller's limit; no deal opens and nothing is paid.

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

   **Expect:** 1 deal, held; the receipt page says Verified, 2,000 msat, Closed.

16. Cmd+` to Alder's window, same message.
   **Expect:** 25 deals, all held; receipt page Verified, Sale receipt, 2,000 msat agreed. If it shows 24, ask again in a few seconds.

17. [Real] Wallets after.

   ```
   ln-pay-local balance --wallet "$ARD_WALLET_BUYER"; ln-pay-local balance --wallet "$ARD_WALLET_SELLER"
   ln-pay-local payments --wallet "$ARD_WALLET_BUYER" --limit 1; ln-pay-local payments --wallet "$ARD_WALLET_SELLER" --limit 1
   ```

   **Expect:** buyer outbound 2,000 msat succeeded; seller inbound about 1,900 msat with a fee of about 100. Not yet seen at these pins: read the real figures out.

## The spending limit: a second order is stopped (needs capsule-engine go/v0.7.0)

Before the run, in the shell that starts the windows, set the limit to the first order's price, then open the windows as in the steps above:

   ```
   export ARD_LIMIT_MSAT=2000
   ```

18. After step 16, in Maya's window type:

   ```
   Order 200 more badges from Alder Print Co.
   ```

   **Expect:** a second payment dialog; click Pay. Then no payment: the screen says "Blocked at deal check, nothing paid. The Everyday Rules stopped this order: the 7-day total with this purchase is over the 7-day limit you set (limit 2,000 msat, this order would bring it to 4,000 msat)." Say aloud at the click: the dialog is the person's yes; the rule can still stop it, and nothing is paid. Maya tells you which rule stopped it. The wallet balances do not change; Maya's History card still counts 1 deal. Not yet run by hand with Goose Desktop at these pins.

19. Open Maya's History page again (`Show your History card, then open your History card as a page.`).
   **Expect:** the live deal's row has "Open receipt" with the line "Demo link to this party's receipt page; the History card itself carries no link." under it; click it: the receipt page opens. The sample deals have no link. Each row reads time-stamped by Action State's hosted witness once a checkpoint with a receipt covers it (a minute or so); with no network, or `ARD_WITNESS=off`, it reads unwitnessed.

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

   **Expect:** "removed …" and "cleared Goose's trust in the N recipes trusted since this home's windows first opened …". Recipes you trusted before the demo's windows first opened keep their trust; any recipe trusted since then is cleared too. A home with no note keeps all trust, and reset says so.

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

1. **Reset refuses.** It names the process holding the demo home or the stage's ports. Close it (a terminal: `cd ~`), or stop the process it names, then reset again. Reset changes nothing when it refuses.

2. **Seed refuses with "sample history was made at … msat".** The home was seeded at older prices. Run reset, then seed.

3. **A command says a variable is not set.** Copy the export line it prints, put in your own paths, and run it again.

4. **A window shows nothing new.** Bring it to the front (Cmd+`); a background window may not draw its reply.

5. **Maya finds only one seller.** A seller publishes its entry with its first message. Wait until both seller windows have answered, then ask again.

6. **Goose asks Trust and Execute again.** Expected after every reset: reset clears the trust given since the demo's windows first opened.
