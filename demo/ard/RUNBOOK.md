# Reproducing the ARD Deal

How to run the ARD two-seller deal on your own Mac: three Goose Desktop windows, one buyer agent and two seller agents, that find each other through ARD, compare signed deal histories, and settle one payment.

evidencebook-skills ecbac12 · evidencebook 5d29ccc · evidencebook-deal 2f82b61 · capsule-engine a331006 (go/v0.4.0) · capsule-viewer 613a8a9 · Goose Desktop 1.59.2 · optional: ln-pay-local 025d566

A plain-text copy of this page, for tools and terminals: [demo/ard/RUNBOOK.md](https://github.com/action-state-group/evidencebook-skills/blob/main/demo/ard/RUNBOOK.md) in evidencebook-skills.

Status: these steps have not yet been run by hand at these pins. The demo's automated tests pass at these pins in CI. The real-payment section has not been run at these pins at all.

## What you will see

Maya needs 200 conference badges by Friday, under 3,000 msat (a msat is a thousandth of a satoshi). Two sellers offer them: Kestrel Print at 1,000 msat and Alder Print Co. at 2,000 msat. Maya's agent decides on each seller's signed history, not only on price. The run has six steps:

1. **Discovery.** Maya's agent searches a local stand-in ARD registry, then fetches each seller's own entry and checks its signed commitment.

2. **History cards.** Each seller answers with its History card over a local relay: Alder 0 of 24 deals did not hold, Kestrel 2 of 24, as Kestrel itself reported. A card's signature shows who wrote the history and that it is unchanged since; it does not show that the deals happened.

3. **Assessment.** Maya's agent assesses both with her admission pack (the rule file). At the starting rule (at most 100 of every 1,000 deals not held) both pass; tightened to 50, Alder passes (GO) and Kestrel is limited (LIMIT: deals under 1,000 msat only). The assessment's inputs come from a demo adapter, and the screen says what it counted, for example "selection: signed answer, no inclusion proofs; this pack counts it".

4. **Recommendation and pick.** Maya's agent recommends; Maya picks. Picking Kestrel opens no deal and pays nothing. Picking Alder seals the pick.

5. **Payment.** A macOS dialog asks you to approve 2,000 msat. Only your click releases the payment, as long as each agent has only its own ard tools (a step below makes sure); by default the payment is simulated and no money moves.

6. **Receipts.** Each side keeps its own record. Maya's card shows 1 deal, Alder's 25, and each side can open a receipt page. A page marked Verified means the verifier (capsulectl-deal) returned VALID for the bundle behind the page against its deal records; it is a check on that copy of the records, not on the seller.

The registry, the seller sites and the 48 sample deals are local stand-ins. The ARD search call, fetching each seller's entry, the signature checks, the assessment and the deal records are the real code.

## What you need

1. A Mac on Apple silicon (the steps use the arm64 build of Goose; an Intel build is on the same release page).

   ```
   uname -m
   ```

   **Expect:** `arm64`.

2. Homebrew, to install the tools below. If `brew --version` fails, install it with the line from brew.sh:

   ```
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```

3. Python 3.10 or later, git, jq, Go, and Node.js with npm. Check each:

   ```
   python3 --version; git --version; jq --version; go version; node --version; npm --version
   ```

   **Expect:** a version from each; Python 3.10 or later. Go may be any recent version: the build lines set `GOTOOLCHAIN=auto`, so Go fetches the version each module asks for.

4. Install whatever is missing:

   ```
   brew install python git jq go node
   ```

5. A Claude Code subscription and the `claude` CLI signed in: the Goose windows use Claude Code as their model. Install it, sign in, then check:

   ```
   npm install -g @anthropic-ai/claude-code
   claude auth login
   claude auth status
   ```

   **Expect:** `claude auth status` says you are signed in.

6. Goose Desktop 1.59.2, installed in the setup below. Other versions were not tried; the recipe links depend on how 1.59.2 opens them.

7. Every Goose extension except the demo's own `ard_*` turned off (the setup below does it, and the shutdown section turns them back on). The payment dialog is the only thing that releases money, and it holds only for agents limited to their own ard tools.

8. Only for a real payment: Rust, and a small amount of bitcoin on Lightning.

   ```
   cargo --version || brew install rust
   ```

## Set up, once

Everything goes under `~/ard-demo`. You can use another folder; change the paths in the next section to match.

1. Install Goose Desktop 1.59.2: download `Goose-darwin-arm64.zip` from [the release page](https://github.com/aaif-goose/goose/releases/tag/v1.59.2), unzip it, move `Goose.app` to Applications.

2. Install the adapter that lets Goose use Claude Code (through the Agent Client Protocol, ACP).

   ```
   npm install -g @agentclientprotocol/claude-agent-acp
   ```

3. Open Goose. On the welcome screen choose Other Providers, then Claude Code ACP, Configure, Submit. Later this lives in Settings, Models.
   **Expect:** a chat opens and answers a short message.

4. **Required:** in Goose, Settings, Extensions, turn off every extension except the demo's own `ard_*` ones (Developer, Computer Controller and the rest). The payment dialog holds only for agents limited to their own `ard_*` tools; an agent with screen control could click it itself.

5. Clone the repositories at the pinned commits, build the two binaries, and install the Python packages (about 5 minutes).

   ```
   mkdir -p $HOME/ard-demo/bin && cd $HOME/ard-demo
   git clone -q https://github.com/action-state-group/evidencebook-skills
   git -C evidencebook-skills checkout -q ecbac123a8c4363d8646edd1eadd30b7f46f58e1
   git clone -q https://github.com/action-state-group/evidencebook
   git -C evidencebook checkout -q 5d29ccc5240bfe1d5d8b926dd5763d5882a30ea9
   git clone -q https://github.com/action-state-group/evidencebook-deal
   git -C evidencebook-deal checkout -q 2f82b61e6410e70d9ca88712d72b0a3f5faeb31d
   git clone -q https://github.com/action-state-group/capsule-engine
   git -C capsule-engine checkout -q a3310060b2d94359bc71c77ae9360d52ee02cf46
   (cd capsule-engine/go && GOTOOLCHAIN=auto go build -o $HOME/ard-demo/bin/capsule-engine ./cmd/capsule-engine)
   (cd evidencebook-deal && GOTOOLCHAIN=auto CGO_ENABLED=0 go build -trimpath -o $HOME/ard-demo/bin/capsulectl-deal ./cmd/capsulectl-deal)
   cd evidencebook-skills && python3 -m venv .venv
   .venv/bin/pip install -q ../evidencebook/python pyyaml rfc8785 websockets "mcp==2.3.0" \
     "capsule-viewer @ git+https://github.com/action-state-group/capsule-viewer@613a8a95144e5851bbb61df72df8cc76b7500381"
   ```

   **Expect:** no error. Each checkout prints a detached HEAD note; that is expected.

## In every terminal you use

1. Go to the checkout and say where the evidencebook checkout and the two binaries are.

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

## Before each run

1. Start clean: quit Goose, then reset. Reset stops the demo's own processes, deletes the demo home (`~/.config/ard-commerce-demo`) and clears the Goose recipe trust given since the demo's windows first opened, so each window asks Trust and Execute again.

   ```
   osascript -e 'quit app "Goose"'
   (cd demo/ard && ../../.venv/bin/python demo.py reset)
   ```

   **Expect:** "removed …" and "removed …" and "cleared Goose's trust in the N recipes trusted since this home's windows first opened …". Recipes you trusted before keep their trust.

2. Make the sample history: 24 deals per seller, 2 of Kestrel's noted as not held (about 20 s).

   ```
   (cd demo/ard && ../../.venv/bin/python demo.py seed)
   ```

3. Open the three windows. Each is a Goose recipe that starts its own copy of the demo's tool server for one party.

   ```
   .venv/bin/python demo/ard/goose/open-windows.py --rail fake
   ```

   **Expect:** three Goose windows, each showing a Trust prompt, Maya on the left. It opens the sellers, then Maya, and tiles them itself: Maya on the left half, the sellers on the right quarters. The first time, macOS asks to let your terminal control System Events and to turn it on under Accessibility: allow both. If it prints "could not tile", allow the access it names, click Maya's window and run the osascript line it prints below that: it tiles the open windows again.

4. Optional: see exactly what each agent is given. This prints each recipe's facts and first message and checks that it carries the skill file from this checkout word for word.

   ```
   .venv/bin/python demo/ard/goose/open-windows.py --rail fake --print | .venv/bin/python -c '
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

   **Expect:** Alder at 2,000 msat, Kestrel at 1,000 msat, Maya's first message only saying she is ready, and "matches the repo file exactly: yes" for all three.

5. Click Trust and Execute in all three windows, in any order.
   **Expect:** each seller reports its card (Alder 24 deals, all held; Kestrel 24, 22 held); Maya says she is ready and searches nothing yet.

6. **Required:** in each window open Extensions: only its own `ard_maya`, `ard_alder` or `ard_kestrel` is on. Turn anything else off before you type the ask: the payment dialog holds only for agents limited to their own ard tools.

## Run the deal

Type one message at a time in Maya's window; each step takes 30 to 60 seconds.

1. Once both sellers have answered, paste the ask into Maya's window.

   ```
   I am Maya. I need 200 conference badges by Friday, under 3,000 msat (a msat is a thousandth of a satoshi: a token amount). Find sellers for me.
   ```

   **Expect:** the search, then both sellers' entries and signatures checked: Alder 2,000 msat, Kestrel 1,000 msat.

2. Optional, in a terminal: what Maya's search sent and what each seller publishes.

   ```
   curl -s -X POST http://127.0.0.1:47481/search -H 'Content-Type: application/json' -d '{"query": {"text": "conference badges print"}, "federation": "none", "pageSize": 10}' | jq
   curl -s http://127.0.0.1:47491/.well-known/ard.json | jq
   curl -s http://127.0.0.1:47492/.well-known/ard.json | jq
   ```

   **Expect:** both sellers in the search result; each seller's ard.json names the digest of its signed commitment.

3. Type in Maya's window.

   ```
   Show me each seller's History card.
   ```

   **Expect:** Alder 0 of 24 deals did not hold; Kestrel 2 of 24, as Kestrel itself reported.

4. The same cards as pages: Cmd+` to Alder's window, then Kestrel's, and type in each.

   ```
   Open my History card as a page.
   ```

   **Expect:** the browser opens that seller's History card page (24 deals; Kestrel's shows the 2 not held). Then Cmd+` back to Maya's window.

5. Type.

   ```
   Assess both sellers, and tighten the rule to at most 50 of every 1,000 deals not holding.
   ```

   **Expect:** at 100 both GO; at 50 Alder GO and Kestrel LIMIT (deals under 1,000 msat).

6. Type.

   ```
   Pick Kestrel Print, the cheaper one.
   ```

   **Expect:** LIMIT: 1,000 msat is at or over this seller's limit; no deal opens and nothing is paid.

7. Type.

   ```
   Pick Alder Print Co.
   ```

   **Expect:** the pick is sealed, and Maya asks before paying.

8. Type, then approve in the macOS dialog (it waits 3 minutes).

   ```
   Yes, pay it.
   ```

   **Expect:** the dialog says "Pay Alder Print Co. 2,000 msat on the simulated rail: no money moves." Click Pay: invoice 2,000 msat, succeeded, deal closed.

9. Type.

   ```
   Show your History card, then open your History card and your receipt as pages.
   ```

   **Expect:** 1 deal, held; the receipt page says Verified (the verifier returned VALID for the page's bundle against its deal records), 2,000 msat, Closed.

10. Switch to Alder's window (Cmd+`) and send the same message.
   **Expect:** 25 deals, all held; its receipt page says Verified, Sale receipt, 2,000 msat agreed. If it still shows 24, ask again a few seconds later.

11. Quit Goose (Cmd+Q) and reopen the windows without resetting.

   ```
   .venv/bin/python demo/ard/goose/open-windows.py --rail fake
   ```

   **Expect:** Alder still has 25 deals, Kestrel 24, and nothing is paid twice.

## Without Goose

1. The same deal in a terminal, with a browser popup for the pick and the payment. Enter moves to each step; Ctrl-C ends it.

   ```
   (cd demo/ard && ../../.venv/bin/python demo.py run --rail fake)
   ```

## Optional: a real payment (not yet run at these pins)

This moves real bitcoin on Lightning mainnet. Use new wallets and small amounts. Lexe's fees, from [docs.lexe.tech/pricing](https://docs.lexe.tech/pricing) (read 2026-11-18; the page says rates may change): receiving payments 0.5%, sending to other Lexe users 0.5% of the payment amount, and "Lightning sends and receives have a minimum fee of ₿0.1 (100 msat …). It only applies to payments under ₿20." At 2,000 msat, 0.5% is 10 msat, so the 100 msat minimum applies on both sides: the buyer needs 2,100 msat and the seller should receive about 1,900.

1. Install ln-pay-local, a small command-line wallet on Lexe's Lightning SDK.

   ```
   git clone -q https://github.com/action-state-group/ln-pay-local $HOME/ard-demo/ln-pay-local
   git -C $HOME/ard-demo/ln-pay-local checkout -q 025d56672d92ea12fda5fe6c3fbb84dd1d40ddf7
   cargo install --path $HOME/ard-demo/ln-pay-local --locked
   ln-pay-local --help
   ```

   **Expect:** one usage line starting `{"error": "usage: ln-pay-local init`.

2. Make a buyer wallet and a seller wallet. **Each writes a private seed file into its folder: back it up, never print or share it.**

   ```
   ln-pay-local init --wallet $HOME/ard-wallets/buyer
   ln-pay-local init --wallet $HOME/ard-wallets/seller
   ```

3. Fund the buyer: this prints an invoice; pay it from any Lightning wallet. The seller needs no funding.

   ```
   ln-pay-local invoice 10000 --wallet $HOME/ard-wallets/buyer
   ```

   **Expect:** `{"invoice": "lnbc…", "amount_msat": 10000}`. About 9,900 msat arrives after Lexe's 100 msat minimum receive fee: enough for 4 runs at 2,100 msat each.

4. Check the buyer can pay.

   ```
   ln-pay-local balance --wallet $HOME/ard-wallets/buyer
   ```

   **Expect:** `spendable_msat` at least 2,100 (2,000 for Alder plus Lexe's 100 msat minimum send fee).

5. In every terminal, also set the wallets and the program.

   ```
   export ARD_WALLET_BUYER=$HOME/ard-wallets/buyer ARD_WALLET_SELLER=$HOME/ard-wallets/seller ARD_PAY_LOCAL=$(command -v ln-pay-local)
   ```

6. Run as above, opening the windows with the local rail.

   ```
   .venv/bin/python demo/ard/goose/open-windows.py --rail local
   ```

   **Expect:** the dialog says "Pay Alder Print Co. 2,000 msat over Lightning: this moves real money, to a wallet Alder Print Co. and Kestrel Print share." Both sellers share the one seller wallet.

7. After the receipts, read both wallets.

   ```
   ln-pay-local payments --wallet "$ARD_WALLET_BUYER" --limit 1; ln-pay-local payments --wallet "$ARD_WALLET_SELLER" --limit 1
   ```

   **Expect:** buyer outbound 2,000 msat succeeded; seller inbound with its own `amount_msat` and `fee_msat`. With Lexe's 100 msat minimum receive fee the seller should receive about 1,900 msat; not yet observed at these pins, so read the figures from this line.

## After the show: shut down and reset

1. Quit Goose, then reset: it stops the demo's stage and servers, deletes the demo home and clears the recipe trust the demo's windows were given.

   ```
   osascript -e 'quit app "Goose"'
   (cd demo/ard && ../../.venv/bin/python demo.py reset)
   ```

   **Expect:** "removed …" and "cleared Goose's trust in the N recipes trusted since this home's windows first opened …". Recipes you trusted before keep their trust.

2. Check that nothing of the demo is left running.

   ```
   pgrep -fl demo/ard
   ```

   **Expect:** nothing printed.

3. Turn your Goose extensions back on: Settings, Extensions, switch on the ones you turned off in setup.

4. If you made a real payment: the wallets are not reset, so it stays paid, and both balances stay as they are.

## Troubleshooting

1. **Reset refuses.** It names the process holding the demo home or the stage's ports. Close it (a terminal: `cd ~`), or stop the process it names, then reset again. Reset changes nothing when it refuses.

2. **Seed refuses with "sample history was made at … msat".** The home was seeded at older prices. Run reset, then seed.

3. **A command says a variable is not set.** Copy the export line it prints, put in your own paths, and run it again.

4. **A window shows nothing new.** Bring it to the front (Cmd+`); a background window may not draw its reply.

5. **Maya finds only one seller.** A seller publishes its entry with its first message. Wait until both seller windows have answered, then ask again.

6. **Goose asks Trust and Execute again.** Expected after every reset: reset clears the trust the demo's windows were given.
