# Reproducing the ARD Deal

How to run the ARD two-seller deal on your own Mac: four Goose Desktop windows, one buyer agent, two seller agents and the adjudicator's assistant. The buyer finds the sellers through ARD and reads their signed History cards. In the first deal the cheaper seller ships short, the buyer disputes, and the adjudicator rules against the seller. In the second deal the seller's card and the buyer's own records show that ruling, and the buyer buys from the other seller. The simulated rail is the default; the real rail steps are marked Real.

This guide runs evidencebook-skills main. The other repositories are pinned: capsulectl v0.1.1, installed from its two releases, capsule-cli v0.1.1 at 129a80f and evidencebook capsulectl/v0.1.1 for the book and deal plugins (built from evidencebook 2ca6e8a, below); 129a80f contains capsule-cli 052a8a6, the commit this guide was pinned to before, with capsule-cli#644: a slow witness reads as slow, never as a consent ask; capsule-cli#646: one witness delivery ends at its deadline; capsule-cli#648 and #649: a checkpoint the witness refuses as not continuing the one it last accepted is sent once more, then re-anchored from that one, so one refusal no longer stops every later time-stamp, evidencebook-skills#358) · evidencebook 2ca6e8a (the capsulectl/v0.1.1 release's commit; the demo's code reads this checkout; it contains fdd97dd, the commit this guide was pinned to before, with #935's receipt page, #933's `deal tick --now`, #954's rules history, which counts an earlier x-deal-v1 payment to a merchant, #965's `witness_timeout`, #972's Everyday Rules 0.3.10, whose r02 and r06 say "not fully checked" on an incomplete history, #974's wording pack en/v1, #987's receipt page in Steven's design on capsule-viewer 1b91f61, #975, #986, #981 and #988, which move the deal verbs into package deal, #909, which removes the temporary outcome-note seal verb, and #991 and #992, which build the plugins on capsule-cli 052a8a6, so a checkpoint the witness refuses is sent once more, then re-anchored, and `deal tick` tries a re-anchor that got no answer again, #989 and #990 on standing intents, #994's capsule-viewer bebf078, and #1004, whose withheld copy keeps each payment record's settlement leg, so the countersign upgrade can send it (evidencebook#998), and #1022, whose receipt page carries the countersigned copy behind the rung and fills COUNTERSIGNED only from its own check of it (evidencebook#1015, capsule-viewer#457); new since fdd97dd, not yet run by hand in Goose: #1033 and capsule-cli#655, whose receipt page carries the countersigner row's independent_of, and #1034, whose claim with no source note names whose claim it is; the release's book and deal plugins are built from it) · capsule-engine 0263ff1 (go/v0.8.0) · capsule-viewer: the receipt page is drawn by capsulectl with capsule-viewer's Go receipt package at the 9239b7d evidencebook pins (capsule-viewer#457: COUNTERSIGNED from the page's own check of the countersigned copy; before it, bebf078 with capsule-viewer#444's x-deal-v0 receipt lines, and 1b91f61) (capsule-viewer#442: Steven's receipt design on top, with every sealed record under For checkers and the ladder under Technical details; capsule-viewer#437: term names in words, local times in the records table, the time and witness columns on your own copy only; capsule-viewer#438: the page names its wording pack capsuleviewer.receipt.wording.en/v1), and the History page vendors capsule-viewer's 0.28.0 script · capsule-anchor e117b23 (main with capsule-anchor#123, which accepts the withheld copy capsulectl writes; the hosted witness runs v0.1.4), started on this Mac as the demo's countersigner by `countersigner.py up`, which installs it in its own environment under the demo home (evidencebook-skills#383) · Goose Desktop 1.59.2 · Claude Code ACP adapter 0.108.0 (only with Claude Code ACP) · real rail: ln-pay-local 4b936bb. **This line is the one place for the pins:** the set-up commands below use the same commits, a test checks that they agree, and a commit anyone gives you that differs from this line is not the one this guide was checked at.

Status: run by hand on 2026-11-25 on a Mac at evidencebook-skills cd33ab8, evidencebook 45eaceb and capsule-viewer d56da4d: steps 1 to 15 passed, then the re-entry (Goose quit and reopened, no reset). Changed since, not yet run by hand: every dialog is now a form in that party's own Goose window (with Claude Code ACP, a typed reply in Maya's chat), no longer a macOS dialog, and the sellers' macOS notifications are gone (#418); the 10-minute dialogs, local times, both agents' ruling and witness wording (#305); the buyer's agent asks before saying it received what it paid for (#306); a ruling the witness stamps late is sent again with its time (#308); this set-up (#311); the receipt page, capsulectl's own `deal report --html` (evidencebook#935, #951) on capsule-viewer bb8169bb (#310, #320); the History page on capsule-viewer 0.27.2, evidencebook 684dd44 and ln-pay-local 4b936bb (#320); the Python environment without capsule-viewer's Python package (#270); evidencebook 47a35cd (evidencebook#954: a repeat order to a seller Maya already paid no longer lists "No earlier payment to this merchant"); capsule-cli dcecbf5 and evidencebook 184fec5 (evidencebook#965: a witness that times out reads as slow, never as a consent ask; evidencebook#971: the receipt page on capsule-viewer 8fe749b); capsule-cli 16ec5bc and evidencebook 4c07d0f (evidencebook#972: Everyday Rules 0.3.10 and one witness delivery bounded by its deadline; evidencebook#974: the receipt page names its wording pack en/v1); evidencebook 625e344 (evidencebook#987: the receipt page in Steven's design, capsule-viewer#442; at this revision the receipt page was read by hand in a browser, drawn by the demo's own `deal report --html` call after a terminal run of both deals; Goose was not run); Maya's spending-limit lines in Sherlock2's words (#354); capsule-cli 052a8a6 and evidencebook 63f2d61 (capsule-cli#648 and #649, evidencebook#991 and #992: a checkpoint the witness refuses as not continuing the one it last accepted is sent once more, then re-anchored, so one refusal no longer leaves every later deal without a time-stamp and Maya's card counts both deals at step 15, evidencebook-skills#358; checked with the deal plugin's tests at that revision, Goose not run); Kestrel's ruling line with the witness time and "No refund", in Sherlock2's words (#360; checked by the end-to-end test against Kestrel's real `deal report`, Goose not run). Open: the windows open stacked, not tiled. New in evidencebook fdd97dd (evidencebook#1022), not yet run by hand in Goose: the receipt page after the upgrade (step 16); its terminal run (Run it, step 2, simulated rail) at evidencebook-skills cde76b3, evidencebook fdd97dd and capsule-viewer 9239b7d, with Maya's page then written by `ard_open_receipt_page`'s code and opened in Chrome, showed the countersign upgrade's line and COUNTERSIGNED as expected on 2026-11-26 (evidencebook-skills#410). New in #383 and in the testbed (#382), not yet run by hand: the testbed's countersigner screen and its `countersigner.py up` step; the demo's countersigner (`countersigner.py up`, Before each run step 2), the countersign upgrade after deal 2 (step 16) and the receipt's countersign line (step 15); evidencebook e5407dc (evidencebook#998: the withheld copy keeps a payment record's settlement leg) and capsule-anchor e117b23 (capsule-anchor#123: it accepts that copy). The spending-limit section (Everyday Rules as Maya's pinned rules checker on x-deal-v1, evidencebook#890) and the card shown under every payment dialog that pauses (Sherlock2's ruling on evidencebook#890) are new in #321: their dialog lines were captured with the real capsulectl-deal and capsule-engine on the simulated rail, not yet run by hand in Goose. New after Steven's hand run of 2026-11-26 at fc9f073 (#411 to #414), run by hand on 2026-11-27 at 98901d8 in Goose 1.59.2 sessions with the demo's recipes and locked adapter (Goose's command line, not its windows; the demo's own macOS dialogs, Set limit, Don't buy and Buy anyway included, clicked by the tester; simulated rail): Maya asks for the spending limit right after the search and her yes sets only the limit (step 2); Don't buy tells her the hold's own reasons and she offers to order again, never a higher limit (the spending-limit section, steps 3 and 4); she opens her Kestrel receipt as a page after the ruling, with the "Didn't go as agreed" seal (step 13). The set-up from the v0.1.1 releases (#436), with no source build, was run by hand on 2026-11-27 at evidencebook-skills 0ff2a99 on a Mac with an empty home folder (only step 8's model choice was copied from an earlier set-up): the one-line set-up reached "Set-up is done" and a rerun changed nothing; a Mac set up at the earlier pins moving to the release, and the run itself (Before each run onward) on the release, are not yet run by hand. New in #416: the adjudicator rules on its own with no Rule dialog, on Kestrel's own signed statement that its delivery was not met (steps 9 and 10). Run by hand on 2026-11-26 at ab2ec63, before #418 moved the party dialogs into Goose, in Goose 1.59.2 sessions with the demo's recipes and locked adapter (Goose's command line, not its windows; simulated rail; Action State's witness): steps 1 to 12 passed, and the ruling reached both parties 5 seconds after the dispute with no dialog; the adjudicator's session quit and reopened shows the same ruling and seals nothing again. Step 10 was run again by hand on 2026-11-27 with `Show the ruling.`, and steps 1 to 12 and the adjudicator's re-entry again at 02815c2 (goose command line, Claude Code ACP, #418's typed replies): the ruling came 7 seconds after the dispute with no dialog. At step 10 the agent quoted the ruling line word for word on one run and restated it as bullets on another, and it added a sentence or two past the skill's one-sentence limit. New in #446: the adjudicator's window shows only its tools' output (`ard_ruling` for the ruling; with Claude Code ACP, no text of the agent's), in plain lines rather than one line of JSON. Run by hand on 2026-11-27 at 3d31c4e in the goose CLI 1.59.2 with Claude Code ACP 0.108.0 through the demo's locked adapter (simulated rail, Action State's witness; the deal and the dispute made by the terminal run with the adjudicator's window closed): the window opened on "no case yet"; steps 9, 10 and 11, questions asking for the reason or about independence in the agent's own words, a reopened session and a resumed one each showed only the tools' lines, the not-independent line first; steps 9 and 10 and the independence question again at 67cf922, after the filter also dropped the agent's thinking, with the same result. Not run: Goose Desktop, and providers other than Claude Code ACP, where only the adjudicate-deal skill holds the agent to its tools' output. New in #448: the History page on capsule-viewer 0.28.0; on 2026-11-28, Alder's and Kestrel's card pages written by `ard_open_card_page`'s code after `demo.py seed` and drawn in headless Chrome, their disclosures opened, say the same as on 0.27.2 apart from their times, and How this was checked draws each check in its own box; not yet opened in Goose.

## What you will see

Maya needs 200 conference badges by Friday, under 3,000 msat (a msat is a thousandth of a satoshi). Two sellers offer them: Kestrel Print at 1,000 msat and Alder Print Co. at 2,000 msat. Alder starts with 15 sample deals and Kestrel with 10, all held, and no disputes: a longer track record against half the price. Each seller's own file, `demo/ard/sellers/kestrel.yaml` and `alder.yaml`, names the product it offers and what it discloses to a buyer; the product's title and price are in the catalog stand-in, `demo/ard/catalog.yaml` (a stand-in for a store platform's product catalog, not a real store). Edit either, then reset and seed: the seller signs a new commitment from what it discloses, and its ARD entry lists the new offer and links its product in the catalog, which Maya's agent checks. The steps below quote today's values. Maya's budget stays 3,000 msat, and the story needs Kestrel to be the cheaper seller.

1. **Discovery.** Maya's agent searches a local stand-in ARD registry, then fetches each seller's own entry and checks its signed commitment.

2. **History cards.** Alder's card: 15 deals, every one went as agreed, no disputes; Kestrel's: 10 deals, the same. A card's signature shows who wrote the counts and that they are unchanged since; these are the seller's own counts.

3. **Deal 1.** Both sellers are "Good to buy"; Maya picks Kestrel, the cheaper one, and pays 1,000 msat (a dialog asks you first). Kestrel's own delivery record says 150 of 200 badges were shipped. Maya disputes the delivery.

4. **The adjudicator.** The adjudicator asks each side for its books, and each side's agent answers on its own: its own book and the copy it holds of the other side's. The adjudicator's window shows the case and Kestrel's own signed delivery record, which says 150 of 200 badges and states the delivery not met: Kestrel's own admission. The adjudicator rules against Kestrel on that record alone, with no person, under its published rules; nobody clicks to rule. The adjudicator is run by the operator, who also runs every party here, so it is not independent of them. Both parties enter the ruling in their own records.

5. **Deal 2.** Kestrel's card now counts 11 deals, 1 that didn't go as agreed, 1 dispute decided against it. Maya's own records hold the ruling, so her rules give Kestrel "Not from this seller" (NO). Alder is "Good to buy"; Maya buys from Alder, and Alder ships all 200.

6. **The countersign upgrade.** Maya asks for her deal with Alder to be countersigned. The demo's countersigner signs her own records of the deal (as digests with their seal times, and her own payments' details; never Alder's records), and her receipt then says so. The operator runs the countersigner and every party here, so it is not independent of them.

The registry, the seller sites and the 25 sample deals are local stand-ins, and the adjudicator runs on this Mac. The ARD search call, fetching each seller's entry, the signature checks, the assessment, every deal record (capsulectl-deal), the dispute and the ruling (capsulectl-deal's `deal respond` and `deal ruling`, the adjudicator's own profile) are the real code.

## What you need

1. A Mac on Apple silicon, on the internet, and its password: Homebrew's installer asks for it when Homebrew is not there yet. The set-up script below checks everything else and installs only what is missing with Homebrew, saying so first, and upgrades nothing you already have: Python 3.10 or later (3.14 tested by hand at an earlier pin), git, jq, Go, Node.js and npm, and tmux (the testbed's screens run in it). It checks that lsof is there (macOS ships it; `demo.py reset` needs it).

2. A model for the Goose windows: either a Claude Code subscription (Claude Code ACP), or a provider Goose runs itself: ChatGPT Codex (a ChatGPT sign-in) or an API key (Google, OpenAI, Anthropic and others). Providers that run their own agent (Claude Code CLI, OpenAI Codex CLI, Cursor Agent, Gemini CLI and ACP agents other than Claude Code) are refused: their agent brings its own tools, so it could answer the Set limit, Pay, Received and Dispute dialogs instead of you. The set-up script asks which one, once.

3. [Real] Real rail only: run the set-up script with `--real-rail`, which also installs Rust. A real payment also needs a small amount of bitcoin on Lightning.

## If you used this guide before 2026-11-19

1. Its setup changed your own Goose: the provider became Claude Code ACP and the extensions were switched off, in `~/.config/goose/config.yaml`. In your normal Goose, set your provider back in Settings, Models, and switch back on the extensions you had on before. The demo now uses its own Goose settings folder and leaves yours alone.

2. It also installed the Claude Code adapter globally, replacing the version you had. If you know which version that was, put it back (npm keeps no history of it); one ACP client stopped working above 0.94.0. The demo now uses its own pinned copy under ~/ard-demo/acp.

   ```
   npm install -g @agentclientprotocol/claude-agent-acp@<the version you had (or the version your other tool requires)>
   ```

## Set up, once

Paste this line into a terminal and press Return:

```
f=$(mktemp) && curl -fsSL https://raw.githubusercontent.com/action-state-group/evidencebook-skills/main/demo/ard/setup.sh -o "$f" && /bin/bash "$f"
```

On a Mac that already has `~/ard-demo/evidencebook-skills`, this does the same: `~/ard-demo/evidencebook-skills/demo/ard/setup.sh` (add `--real-rail` for the real rail).

It prints one line for each thing it checks or does, and stops once for you (step 8 below). If something fails, it says which step and where the details are; once that is fixed, run it again. Run it again at any time: it skips everything already done, so on a set-up Mac it changes nothing.

**Expect:** it ends with one line naming what it set up (`Set-up is done at evidencebook-skills …, capsulectl v0.1.1 (capsule-cli 129a80f, evidencebook 2ca6e8a), capsule-engine 0263ff1, Goose Desktop 1.59.2, provider …`), then `Next: "Before each run" in the RUNBOOK.`

What it does, in order (you do not type these):

1. Installs what is missing (What you need, item 1) with Homebrew.

2. Gets the code into `~/ard-demo`: evidencebook-skills at main, and evidencebook and capsule-engine at the pins in this guide's header. It clones what is missing and moves what is already there, so it is the same on a new Mac and on one that ran an earlier version of this guide. A checkout with changes of its own is neither moved nor built from: the script stops and says so.

3. Downloads capsulectl v0.1.1 and its book and deal plugins from their releases into `~/ard-demo/dist`, checks each file against its release's SHA256SUMS, and installs them into `~/.local`. A checkout of capsule-cli that an earlier set-up left in `~/ard-demo` is no longer used; it can stay.

4. Builds capsule-engine into `~/ard-demo/bin`, and makes the Python environment (`.venv` in evidencebook-skills). A capsule-viewer package an earlier set-up left in `.venv` is no longer used; it can stay.

5. Installs Goose Desktop 1.59.2 (Apple silicon), replacing any other version in Applications. Other versions were not tried; the recipe links depend on how 1.59.2 opens them.

6. Claude Code ACP only: installs the demo's own Claude Code adapter (ACP) 0.108.0 under `~/ard-demo/acp`, **never with npm install -g**: a global install replaces the adapter version other tools on your Mac use, and one ACP client stopped working above 0.94.0. open-windows.py points the demo's Goose at this copy (Goose looks in GOOSE_SEARCH_PATHS first). 0.108.0 is the version Goose 1.59.2 ran with when this guide was made. It also installs the `claude` CLI with Homebrew if it is missing, and when Claude Code is not signed in, opens its sign-in in your browser.

7. Starts the demo's own Goose. **It runs on its own settings folder, `~/.config/ard-commerce-goose`, never on your own Goose's settings**, so a provider, sign-in or key you set up in your own Goose is not there, and steps 8 and 9 never change your own Goose. Goose 1.59.2 keeps its provider and extension settings under `GOOSE_PATH_ROOT` when it is set; open-windows.py starts Goose with it. Reset never deletes this folder.

8. **Your step.** The script asks which model, then says where to click. In that Goose (maximize the window if it opens small), on the welcome screen click Connect to a Provider. With Claude Code ACP: type `claude` in the search box to find Claude Code ACP, wait for "ACP adapter found", click Continue. With another provider: pick it (for example ChatGPT Codex, then sign in; or Google or OpenAI, then paste the API key) and follow its screens; the key is kept by this Goose only. A privacy screen follows (untick "Share anonymous usage data" if you like), then Get Started. With ChatGPT Codex, then choose the model gpt-5.6-sol in Settings, Models: Goose presets gpt-5.5, which ChatGPT refuses for a ChatGPT account ("The 'gpt-5.5' model is not supported when using Codex with a ChatGPT account"), so every window's first answer would fail. Type hello in the chat and check that it answers, then press Return in the terminal. The script checks the choice the way open-windows.py does and, if it is not right yet, says why and opens Goose again. Later this lives in Settings, Models. (Goose 1.59.2, hand run 2026-11-24.) A rerun skips this step once a model is chosen.

9. **Required, so the payment dialog holds (an agent with screen control could click it itself):** quits that Goose and turns off every Goose extension in its settings (Analyze, Apps, Computer Controller, Developer, Extension Manager, Skills, Summon and Top Of Mind), then checks, the way open-windows.py does, that none is still on. The demo's own extensions (ard_maya, ard_alder, ard_kestrel, ard_adjudicator) are not there: each window brings its own. Scheduler is a Goose setting, not one of these extensions, and stays on (`scheduler: enabled: true`).

10. Leaves that Goose quit.

11. Checks that Action State's witness takes a real stamp, not only that its home page loads: it makes one test stamp on a new, empty log of its own (the witness receives only that log's hashes) and waits up to 60 seconds for the witness's receipt. If the witness refuses it or does not answer, the set-up stops with one line saying which. To check again just before a run: `ARD_EVIDENCEBOOK=~/ard-demo/evidencebook CAPSULECTL_DEAL=~/.local/lib/capsulectl/plugins/capsulectl-deal ~/ard-demo/evidencebook-skills/.venv/bin/python ~/ard-demo/evidencebook-skills/demo/ard/witness_check.py`.

## Real rail, once

Do a full run on the simulated rail first, then the real rail. This moves real bitcoin on Lightning mainnet. Use new wallets and small amounts. Not yet run at these pins. Lexe's fees, from [docs.lexe.tech/pricing](https://docs.lexe.tech/pricing) (read 2026-11-18; the page says rates may change): receiving payments 0.5%, sending to other Lexe users 0.5% of the payment amount, and "Lightning sends and receives have a minimum fee of ₿0.1 (100 msat …). It only applies to payments under ₿20." At 2,000 msat, 0.5% is 10 msat, so the 100 msat minimum applies on both sides: the buyer needs 2,100 msat and the seller should receive about 1,900.

1. [Real] Install ln-pay-local. ln-pay-local is a small command-line wallet on Lexe's Lightning SDK. Run this block again after each upgrade of this guide: it moves ln-pay-local to the pin and reinstalls it.

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

## The testbed: every role in one step

The testbed (evidencebook-skills#382) brings up every role of the deal, each on its own screen, with one command: the four agents in their Goose windows as below, and four roles that run no agent, each in a window of the tmux session `ard-testbed` showing what the parties sent that role and got back: the witness (each hash a party's book sent it, never a record, and each time-stamp it signed: a line for each stamp a deal step asks for, and one line per party for its routine stamps, one a minute, at the bottom), the payment rail (each invoice and payment, who paid whom), the catalog stand-in (each seller's products and prices, and each time an agent reads one) and the countersigner (each deal a party asked it to countersign: its own records as digests with their seal times, and its own payments' details; never the other side's records; the demo's own, so not independent of the parties). Which roles, which witness and which rail are in `demo/ard/testbed.yaml`.

1. Bring it up. It runs the set-up script first (which skips everything already done). If Goose is running, it asks before quitting it. Then it resets, starts the witness when `witness: local`, makes the sample history (about a minute), starts the demo's countersigner (`countersigner.py up`, "Before each run" step 2), opens the witness, rail, catalog and countersigner screens in tmux, and opens the four Goose windows as "Before each run" steps 4 to 6 do.

   ```
   ~/ard-demo/evidencebook-skills/demo/ard/testbed.sh
   ```

   **Expect:** "sample history made and stamped in … s", "the screens are in tmux: tmux attach -t ard-testbed (Ctrl-b n for the next one)", then the four Goose windows. The tmux session has four windows, Witness (testbed), Rail (testbed), Catalog (testbed) and Countersigner (testbed, not independent); no Terminal window opens. Then carry on from "Before each run" step 6 (tiling by hand if they came up stacked), wait two minutes after the sample history before the first message, and follow "The run". To show a screen, attach to the session in a terminal of your own (`tmux attach -t ard-testbed`) and put that terminal on a second display, or beside the Goose windows, where the room can read it; Ctrl-b n moves to the next screen, Ctrl-b d detaches.

2. The witness. `witness: public` (the default) names Action State's hosted witness, the free default every agreement names. Before it changes anything, `up` measures it: one test stamp from each of four throwaway profiles at once, as a run's four parties would send, each given the 30 seconds a receipt page waits for its witness time (`tests/witness_probe.py`); when any is not taken in time, or it cannot be measured, it asks whether to bring the testbed up on the local test witness instead (Return says yes). `--no-probe` skips the measurement. `testbed.sh` leaves this check to the testbed, so the set-up's own witness stamp is skipped there. `--witness local` starts a witness on this Mac instead, the local test witness (capsule-anchor at the release the hosted one runs, under `~/ard-demo/testbed`; it needs Python 3.11 or later): for test runs, and as the fallback when the hosted one is slow on the day. It keeps nothing when stopped, so each `up` resets and makes the sample history again.

   ```
   ~/ard-demo/evidencebook-skills/demo/ard/testbed.sh --witness local
   ```

3. Quit and re-entry. Quit Goose (Cmd+Q), then open the windows again on the same home and the same witness, without reset:

   ```
   (cd ~/ard-demo/evidencebook-skills && .venv/bin/python demo/ard/testbed.py reopen)
   ```

   This needs the three paths of "In every terminal" exported. With the local witness it refuses once that witness has stopped (after a restart of the Mac, say): bring the testbed up again.

4. Shut down: quit Goose, then close the screens, reset and stop the local witness.

   ```
   (cd ~/ard-demo/evidencebook-skills && .venv/bin/python demo/ard/testbed.py down)
   ```

   **Expect:** "removed …" and, with the local witness, "stopped the testbed's local witness (pid …)". The tmux session `ard-testbed` and its four screens close too.

## In every terminal

1. Go to the checkout and set the three paths.

   ```
   cd $HOME/ard-demo/evidencebook-skills
   export ARD_EVIDENCEBOOK=$HOME/ard-demo/evidencebook \
     CAPSULECTL_DEAL=$HOME/.local/lib/capsulectl/plugins/capsulectl-deal \
     CAPSULE_ENGINE=$HOME/ard-demo/bin/capsule-engine
   ```

   If you moved to another demo home (Troubleshooting 1), export it here too, in every terminal: `export ARD_HOME=~/.config/ard-commerce-demo-2`.

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

1. Quit Goose, then reset: it stops the demo's processes, deletes the demo home and clears Goose's trust in the demo's own recipes, so each window asks Trust and Execute again. Goose keeps recipe trust in one place for the demo's Goose and your own; reset deletes only the trust files of the recipes open-windows.py opened (it computes their names the way Goose 1.59.2 does), so any other recipe you trusted keeps its trust. The demo home is `~/.config/ard-commerce-demo` (or `$ARD_HOME` when set).

   ```
   osascript -e 'quit app "Goose"'
   (cd demo/ard && ../../.venv/bin/python demo.py reset)
   ```

   **Expect:** "removed …" and "cleared Goose's trust in N of the demo's recipes …", or, when none of them is trusted (the first reset, say), "deleted no Goose recipe trust …". If it refuses, it says what to stop.

2. Make the sample history. This is set-up: run it before anyone watches, at least two minutes before you open the windows. It takes about a minute: 15 sample deals for Alder and 10 for Kestrel, with contest windows of seconds, and one witness stamp per seller. Each card counts its deals held from the first stamp after their windows end, which each seller's window takes as it opens; a window opened sooner waits for that minute and says so.

   ```
   (cd demo/ard && ../../.venv/bin/python demo.py seed)
   ```

   **Expect:** "sample history made and stamped in … s. Each card counts it held from HH:MM:SS". Each party's checkpoints go to Action State's hosted witness (hashes only); with no network, set `ARD_WITNESS=off` first (the cards are then not time-stamped).

   Then start the demo's countersigner for those parties (the first time on a new home it installs capsule-anchor, about 30 s):

   ```
   (cd demo/ard && ../../.venv/bin/python countersigner.py up)
   ```

   **Expect:** "the demo's countersigner listens on https://localhost:…/countersign/register, admitting maya, alder, kestrel, adjudicator". It runs until reset (or `countersigner.py down`) and countersigns only those four parties' books; it learns each record's digest and seal time and, for each of the party's own payments, whether it sent or received it, the amount, fees, payment reference, status and when it saw it; never a payment's secret or the other side's records.

3. [Real] Read both balances.

   ```
   ln-pay-local balance --wallet "$ARD_WALLET_BUYER"; ln-pay-local balance --wallet "$ARD_WALLET_SELLER"
   ```

   **Expect:** buyer `spendable_msat` at least 3,200 (1,000 and 2,000 for the two deals, plus Lexe's 100 msat minimum send fee each).

4. [Real] Open the four windows (it refuses while Goose runs, then starts the demo's own Goose): the sellers, the adjudicator, then Maya, tiled in quarters. The first time, macOS asks to let your terminal control System Events and to turn it on under Accessibility: allow both.

   ```
   .venv/bin/python demo/ard/goose/open-windows.py --rail local
   ```

   **Expect:** four windows, each with a Trust prompt (Maya's may not have one: see step 7). If tiling fails while macOS asks, the script tries again every 10 s, twice; if they come up stacked, see step 6.

   These windows open each card and receipt page in your default browser when you ask for one. To keep pages closed and only see where each was written, open the windows with `ARD_OPEN_PAGES=0` in front of the command. A page opens only in windows this command opened in Goose Desktop, or with `ARD_OPEN_PAGES=1`: windows from `--print` recipes write the page and print its path (evidencebook-skills#465).

5. [Simulated] Or, simulated: the same, and no money moves.

   ```
   .venv/bin/python demo/ard/goose/open-windows.py --rail fake
   ```

6. If the windows are stacked, tile them by hand: click Maya's window, then Window, Move & Resize, then Quarters under Arrange (the last item of the Arrange group; the Quarters above Top Left is only a heading). The script can print no error while the windows are still stacked (evidencebook-skills#322: hand runs on 2026-11-25 found them stacked), and the menu item works only while a Goose window is in front, which the click makes it.

7. Click Trust and Execute in all four windows, in any order. Click each window once first: a window behind the others takes the first click only to come forward. Maya's window can open with no Trust prompt and answer at once. After an upgrade from a version before evidencebook-skills#277 that is expected once (Troubleshooting 7); otherwise it was seen on another Mac on 2026-11-25, after a reset that cleared all four recipes' trust, with the cause not known yet (evidencebook-skills#322). On the simulated rail, carry on: step 8 checks that it has only its own `ard_maya` tools. On the real rail, Maya's window is the one that pays and the prompt is your check of what it runs: quit Goose and do "Before each run" again from step 1 (reset, seed and its wait, the balances, the windows). If Maya's window again opens with no Trust prompt, stop: run on the simulated rail instead.
   **Expect:** Alder says 15 deals and Kestrel 10, all held; Maya's window shows her own History card ("No deals yet, and no disputes.") and "No spending limit is set yet, so only this pack's limits apply: deals under 10 msat, 1,000 msat or 10,000 msat, depending on the seller's history." (she sets hers in step 2), then says it is ready; the adjudicator's window shows "no case yet: a party has sent no dispute to this adjudicator". Every answer in the adjudicator's window is its tool's output and nothing else: with Claude Code ACP, the demo's locked adapter ends the agent's turn when a tool returns and never shows the agent's own text (evidencebook-skills#446).

8. **Required:** in each window open Extensions: only its own `ard_maya`, `ard_alder`, `ard_kestrel` or `ard_adjudicator` is on (the extensions icon under the chat box shows 1). Turn anything else off before you type. Change no provider or extension while the windows are open; if you do, quit Goose and open the windows again, so open-windows.py checks them again. To see what an agent has, type `List every tool you have by exact name, including deferred ones.` in any window. **Expect:** that window's own `ard_…` tools and nothing else (with Claude Code ACP they show as `mcp__ard_…`, beside ToolSearch, which only loads them; with another provider their names may show without the prefix, and any other tool means an extension is still on): Maya's fifteen (`ard_find_sellers`, `ard_set_limit`, `ard_show_listing`, `ard_show_history`, `ard_assess`, `ard_pick`, `ard_pay`, `ard_dispute`, `ard_confirm_received`, `ard_countersign`, `ard_show_card`, `ard_open_card_page`, `ard_show_receipt`, `ard_open_receipt_page`, `ard_confirm`), a seller's five (`ard_seller_activity` and the four card and receipt tools). The adjudicator's window answers only with its tools' output, so with Claude Code ACP it does not list its tools: there the Extensions check above (only `ard_adjudicator` on) is the check, and its three tools are `ard_case`, `ard_ruling` and `ard_case_activity`.

9. Keep the screen awake and unlocked while the windows are open.

## The run

Type in Maya's window unless a step names another; each step takes 30 to 60 s. Cmd+` moves between windows.

**The dialogs.** Each dialog (Set limit, Pay or Buy anyway, Dispute, Received) appears inside that party's own Goose window, under its chat: the dialog's words, then "Your answer", preset to the safe choice (Cancel, or Don't buy), and a Submit button. To answer, choose the answer under "Your answer" and click Submit; Submit with nothing changed sends the safe choice. In the tiled windows the form may sit partly under the window's top bar: scroll the chat until you see both "Your answer" and Submit. Answer within 5 minutes: Goose ends a form nobody submitted after 5 minutes and fails the step's call (in the hand run of #433 the call answered "request timeout after PT300S"); the step then does nothing (the safe choice), and Maya's agent says the request timed out; after a payment dialog it says "The approval timed out, so nothing was paid." and offers to order again, as after Don't buy. Ask for the step again to see the dialog again. Only an answer submitted in the window counts. The window's agent cannot see or answer a dialog: none of its tools gives an answer, and the answer goes from the window straight to the party's own records.

**With Claude Code ACP, a typed reply instead.** Goose cannot show the form to a Claude Code window, so Maya's agent shows the dialog's words in the chat, word for word, with the exact reply that says yes (for example "To answer Buy anyway, type exactly: Buy anyway"), and stops. Type that reply as your next message to say yes; anything else you type, or no reply within 10 minutes, is the safe choice (Cancel, or Don't buy). The demo reads your reply from Goose's own record of the chat, which only typing in the window writes, never from the agent, and seals it with your answer ("Answered by a typed reply in the chat: …"). After your reply Maya's agent calls `ard_confirm`, which carries on the step. So in the steps below, for Maya's dialogs, "choose X and click Submit" means typing X with Claude Code ACP.

1. Say the opening line (simulated rail; on the real rail say the payments are real and small).

   ```
   This is sample history, and the payment is simulated: no money moves.
   ```

2. Paste the ask.

   ```
   I am Maya. I need 200 conference badges by Friday, under 3,000 msat (a msat is a thousandth of a satoshi: a token amount). Find sellers for me.
   ```

   **Expect:** the search, then both sellers' entries and signatures checked: Alder 2,000 msat, Kestrel 1,000 msat. Maya's agent then asks, in one short question, whether 3,000 msat should be your spending limit, and stops there: no History card and no assessment yet. Until you set it, she calls it the most you said you'll pay, never your limit. It is not your limit until you say yes and answer Set limit. Type, then answer the dialog (a form waits 5 minutes, a typed reply 10):

   ```
   Yes.
   ```

   **Expect:** the dialog "Set your spending limit to 3,000 msat for any one order, and 3,000 msat in total over 7 days? Each payment is then checked against it, and an order over it waits for your OK." (answers Cancel, preset, and Set limit). Choose Set limit and click Submit. Then "Your spending limit: 3,000 msat for any one order, and 3,000 msat in total over 7 days. Each payment is checked against it.", and Maya waits for your next request: your yes sets the limit and nothing more. The dialog's words and your answer are sealed with the limit in Maya's own records; her card, the assessment and every payment check use it from now on. Cancel sets no limit.

3. Type.

   ```
   Show me each seller's History card.
   ```

   **Expect:** Alder: "History card: 15 deals, every one went as agreed. Disputes others raised about it: 0 decided against it, of 0 decided; 0 open." and "Signed by … These are the seller's own counts. Its first 15 deals are sample history the operator made before this run." Kestrel: the same with 10 deals and "Its first 10 deals …". The witness line reads "time-stamped by Action State's witness: its receipt verifies under the witness's key", and the "Signed by" line adds "and time-stamped by Action State's witness. The operator, Action State, also runs every party here, so the witness is not independent of the parties." (with `ARD_WITNESS=off`: "not checked: the card carries no time-stamp receipt").

4. Type.

   ```
   Assess both sellers.
   ```

   **Expect:** "Your spending limit: 3,000 msat …" first, then both "GO: … is within this pack's limit for it. Within your limit of 3,000 msat for one order; your 7-day total is checked at payment.", Kestrel at 1,000 msat and Alder at 2,000 msat. Kestrel is half the price with 10 deals on its card; Alder has 15. Both pass Maya's rules.

5. Type.

   ```
   Pick Kestrel Print, the cheaper one.
   ```

   **Expect:** the pick is sealed first ("pick sealed before any payment"), then Maya asks before paying.

6. Type, then wait for the dialog in Maya's window (a form waits 5 minutes, a typed reply 10). Only your answer releases the payment.

   ```
   Yes, pay it.
   ```

   **Expect:** the held-order question, since her spending limit is set: titled "The Everyday Rules held this order for your OK", with the answers Don't buy (preset) and Buy anyway. Its text (Goose shows it as one paragraph):
   - "200 conference badges, delivered by Friday from Kestrel Print for 1,000 msat, on the simulated rail: no money moves. Nothing has been paid yet."
   - "No earlier payment to this merchant from this profile"
   - "The payment is not refundable"
   - "Your answer is saved on the receipt."

   Under them, "Saved with your answer:" and capsulectl's card, which your answer is sealed with: "PAUSED FOR YOU", "Pay 1,000 msat to Kestrel Print (kestrel.ard-demo.test) for the 200 conference badges, delivered by Friday?", "1,000 msat · by simulated · not refundable · within your 3,000 msat limit" and "Why I'm asking: I picked item 200 conference badges, delivered by Friday, not you." Nothing is sent to Kestrel until you answer it. The 1,000 msat is within her limit: the order is held because it is her first payment to Kestrel and cannot be refunded. Choose Buy anyway and click Submit: "You approved this held order (…). Paying now." Then "invoice 1,000 msat; the simulated rail paid it (no money moved): succeeded" and "Kestrel Print's delivery record says 150 of 200 badges were shipped." Maya asks whether you want to dispute the delivery.

7. Type, then answer the dialog (a form waits 5 minutes, a typed reply 10).

   ```
   Only 150 arrived. Dispute the delivery.
   ```

   **Expect:** the dialog "Dispute your delivery from Kestrel Print? Its delivery record says 150 of 200 badges were shipped. Choosing Dispute sends Kestrel Print and the adjudicator your signed statement that the delivery was not met. It moves no money." (Cancel preset); nothing is sent until you answer it. Choose Dispute and click Submit. Then "Dispute raised on this deal's delivery. Sent to Kestrel Print and to the adjudicator your agreement names. Nothing is refunded by this step."

8. Cmd+` to Kestrel's window, type `What happened with the buyer since then?`.
   **Expect:** one line for each event so far: "deal agreed: 1,000 msat for 200 conference badges, delivered by Friday, signed by both (deal …)", "paid: the buyer says it paid 1,000 msat (simulated rail: no money moved)", "delivered to the buyer: 150 of 200 badges (this seller's delivery record says so, and states the delivery not met)", "dispute received: the buyer disputed the delivery of deal …; the adjudicator asks for this seller's books, which this seller answers in full". A Goose window shows nothing until it is asked. Once the adjudicator has asked (it asks as soon as the dispute arrives), also "the adjudicator asked for this party's books of deal …: sent in full (its own book and the copy it holds of the other side's)".

   **Steps 9 to 11 wait on Action State's witness.** When it answers slowly, an answer can say "no answer yet", "not yet", "not time-stamped yet" or "trying again". Wait a minute and ask the same question again; nothing needs doing in another window. What a party's agent does on its own (answering the adjudicator, entering the ruling, sending its book) says in one line when it has to wait, and tries again; the error itself goes to that party's log (Troubleshooting 8).

9. Cmd+` to the adjudicator's window, type:

   ```
   Show me the case.
   ```

   **Expect:** the tool's own lines, with no sentence of the agent's after them (with Claude Code ACP; with another provider only the skill holds the agent to it): "This adjudicator is run by the operator, who also runs every party here: it is not independent of the parties.", then "deal …, row delivered: disputed by Maya", the ruling (below) once there is one, "asked both sides for their books at …", "Maya answered at …" and "Kestrel Print answered at …" (each: "own book and the copy held of" the other side's), "Maya's statement on the row: not met", "Kestrel Print's own signed delivery record: 150 of 200 badges" and "Kestrel Print's statement on the row: not met". Once both have answered, the adjudicator rules on its own within a few seconds, with no dialog, so the answer usually shows its ruling right under the deal's line: "Ruled without a person: Kestrel Print stated in its own signed record that the delivery was not met (its record says 150 of 200 badges). Against Kestrel Print. Either side may challenge it within 7 days. A challenge is recorded beside the ruling and never replaces it." and "Sent to both parties; each enters it in its own records." When the witness is slow or out of reach, the last line is "Its stamp is not taken yet: this window keeps asking Action State's witness and sends the ruling to both parties again with its stamp. Keep this window open until then." If it says "Not ruled yet", a side has not answered: wait a minute and ask again (Troubleshooting 4). The adjudicator asked for the books when the dispute arrived (step 7), so they are usually in by now; it waits up to 30 seconds more for any still out. If one says "no answer yet", wait a minute and ask again.

10. Type:

    ```
    Show the ruling.
    ```

    **Expect:** no dialog, and the tool's own lines with no sentence of the agent's (with Claude Code ACP; with another provider only the skill holds the agent to it): "This adjudicator is run by the operator, who also runs every party here: it is not independent of the parties.", then "deal …, row delivered: disputed by Maya", "Ruled without a person: Kestrel Print stated in its own signed record that the delivery was not met (its record says 150 of 200 badges). Against Kestrel Print. Either side may challenge it within 7 days. A challenge is recorded beside the ruling and never replaces it.", "ruling …" and "Sent to both parties; each enters it in its own records." Any question about the ruling, its reason or the adjudicator's independence ("What did you rule, and why?", "Does it matter that it is not independent?") gets the same lines.

11. After a few seconds, type `Check whether each party entered the ruling in its own records.`
    **Expect:** "deal …: the ruling was time-stamped by Action State's witness at …", then "Maya: entered it; the entry is time-stamped by Action State's witness" and the same for Kestrel Print. With a slow witness a line can say "not time-stamped yet" or "has not sent their book back yet": wait a minute and ask again, since each party sends its book and its stamp on its own. Cmd+` to Kestrel's window and ask `What happened with the buyer since then?` again: "the adjudicator's ruling on deal … entered in this party's records", then the ruling line, read from Kestrel's own records each time it is asked: "ruling on deal …: Ruled against you: delivery not met. Time-stamped by Action State's witness at …. No refund: this deal was agreed as not refundable." Until the witness has stamped the ruling it says "Not time-stamped by Action State's witness yet." in place of the time; ask again a minute later.

12. In Kestrel's window, type `Show my History card.`
    **Expect:** "11 deals, 1 didn't go as agreed. Disputes others raised about it: 1 decided against it, of 1 decided; 0 open.", then "Its first 10 deals are sample history the operator made before this run." The card is stamped when you ask, so it counts at once; if the deal's outcome still shows 0 that didn't go as agreed, ask again: it can follow the dispute's count by one stamp.

13. Cmd+` back to Maya's window, type `Open your receipt as a page.`
    **Expect:** a browser page "Deal report" for her deal with Kestrel Print, with the seal "Didn't go as agreed" and the top line "Ruled: Delivery not met": the adjudicator's ruling is final, so the receipt shows it. Maya says the same: "Ruled for you: delivery not met, against Kestrel Print. No refund: this deal was agreed as not refundable." (The page at step 15, Alder's deal, is still open to dispute, so it has no seal.) If it says the receipt page is not ready yet, ask again in a minute. Then type:

    ```
    Order 200 more badges. Show me each seller's History card again, then assess both.
    ```

    **Expect:** Kestrel's card as in step 12; Kestrel "NO: you hold a ruling against this seller (deal …, delivery not met, ruled …). Your rules block a seller you hold a ruling against for 180 days. Its card also counts 1 dispute decided against it, of 1 decided; the card does not say which deal."; Alder "GO".

14. Type `Pick Alder Print Co.`, then `Yes, pay it.` and answer the dialog: the same held-order question as in step 6, for Alder Print Co. at 2,000 msat, with the same two reasons ("No earlier payment to this merchant from this profile", "The payment is not refundable") and capsulectl's card under it ("… 2,000 msat …"). With Kestrel's 1,000 msat, the total for the last 7 days is 3,000 msat, which is within her limit. Choose Buy anyway and click Submit.
    **Expect:** invoice 2,000 msat succeeded, "Alder Print Co.'s delivery record says 200 of 200 badges were shipped." and "Nothing has been sent in Maya's name. If she received it, she can say so, and Alder Print Co. gets her statement that she received what she paid for." Maya's agent sends nothing in her name on its own.

    Then type `I received all 200.` and answer the dialog ("Did you receive what you paid for from Alder Print Co.? Its delivery record says 200 of 200 badges were shipped. Choosing Received sends Alder Print Co. your statement that you received it."): choose Received and click Submit.
    **Expect:** "Maya's statement sent to Alder Print Co.: she received what she paid for." Cancel (or Submit with nothing changed) instead: "Maya chose Cancel, so nothing was sent in Maya's name."

15. Type `Show your History card, then your receipt.`
    **Expect:** Maya's card counts her 2 deals (with a slow witness it counts only the deals the witness has time-stamped, then adds a line such as "1 more deal not counted yet: waiting for a time-stamp."; ask again in a minute); her receipt reads each row's status as capsulectl reports it (Alder's deal: met so far, as both sides said, still open to dispute until its window ends), "Signed by both sides: the other side's signed agreement checks out on Maya's own book. It covers their agreement only, not anything after it.", "Time-stamped by Action State's witness at …, as checked on Maya's own book." (the same time as the page below; with a slow witness, "Not time-stamped yet: Action State's witness has not taken Maya's latest stamp; ask again in a minute."), "Not countersigned yet: no countersigner has signed Maya's records of this deal." and "Test money: this deal's payment was on a simulated rail. No real money moved." Then type `Open your receipt as a page.` **Expect:** a browser page "Deal report" in Steven's receipt design (capsule-viewer#442): "✓ Unchanged since it was sealed" and "10 of 10 checks passed" at the top; "Order receipt", "Private: your copy" and "Download proof file"; the top line "Both sides say the same so far; still open to dispute", with no seal; the cards Payment ("2 sats", "2,000 msat", "Recorded as settled"), Status ("Both say the same so far") and Seller's side ("Their signed agreement: capsulectl verify reported it verified"); the stamps RECORDED "Checkpointed", TIME-STAMPED "Action State's witness · …, as capsulectl verify reported" and COUNTERSIGNED "Not countersigned"; "What happened, step by step" with "Deal agreed", "Payment recorded as settled: 2,000 msat" and "You said: Delivery: met; Payment as agreed: met"; "Is this record intact?" ("Yes. capsulectl verify passed every test when this page was made. …", its last row "Outside time stamp: Action State's witness at …, as capsulectl verify reported on your own book"), "Check it yourself" and "What this does not prove". Under "For checkers: every sealed record": the three records, the log, the proof fingerprint and "Producer version: not recorded". Under "Technical details": "Signed by both sides: this copy carries the other party's signed agreement, recorded in their own book. …" and the records each term rests on. With a slow witness the stamp reads "Not time-stamped yet" and the page opens with "This file carries no witness receipt, so this page could not check a time-stamp itself."; open it again a minute later. Its times are in this Mac's own zone, with UTC beside the due and window-end times.

16. The countersign upgrade. Type `Get my deal with Alder countersigned.`
    **Expect:** "Maya's deal … with Alder Print Co.: Countersigned by the demo's countersigner at …, as capsulectl reports. It signed Maya's own records of this deal, 1 to N of N: their digests and seal times, and Maya's own payments' amounts, fees, references and status. It does not cover Alder Print Co.'s records. In this demo the operator runs it and every party, so it is not independent of them." With the countersigner not running: "the demo's countersigner is not running: start it with `python demo/ard/countersigner.py up` (after `demo.py seed`)"; start it in a terminal and ask again. Then type `Show your receipt.` **Expect:** the same countersign line in place of "Not countersigned yet". Then type `Open your receipt as a page.` **Expect:** the page as at step 15, with COUNTERSIGNED now "Countersigned by the demo's countersigner at …, through record N of N. Its directory entry does not list it as independent of the parties.": the page file carries the countersigned copy and the page checked it itself (evidencebook#1015, capsule-viewer#457).

17. [Real] Wallets after: buyer outbound 1,000 and 2,000 msat succeeded.

## The spending limit: an order over it

The main run sets a spending limit of 3,000 msat in step 2, so every payment is checked against it, and each order is held for your OK because it is a first payment to its seller and cannot be refunded. To also see an order go over the limit, run the steps above with 2,000 msat.

1. At step 2, paste the ask with 2,000 msat in place of 3,000:

   ```
   I am Maya. I need 200 conference badges by Friday, under 2,000 msat (a msat is a thousandth of a satoshi: a token amount). Find sellers for me.
   ```

   **Expect:** Maya's agent asks whether 2,000 msat should be your spending limit. Type `Yes.`, then in the dialog choose Set limit and click Submit. **Expect:** "Your spending limit: 2,000 msat for any one order, and 2,000 msat in total over 7 days. Each payment is checked against it."

2. At step 6, the held-order question is as written there.

3. At step 14, type `Pick Alder Print Co.`, then `Yes, pay it.`

   **Expect:** the same held-order question for Alder Print Co. at 2,000 msat. Its reasons: "Over your 7-day limit: 3,000 msat with this order, limit 2,000 msat", "No earlier payment to this merchant from this profile" and "The payment is not refundable", then capsulectl's card ("… over your 2,000 msat limit").

   Click Submit with Don't buy, as preset. **Expect:** nothing is paid, and nothing was sent to Alder Print Co. Maya tells you the hold's own reasons, without naming any tool and without guessing at a cause: "The Everyday Rules held this order for your OK, and nothing was paid: over your 7-day limit: 3,000 msat with this order, limit 2,000 msat; no earlier payment to this merchant from this profile; the payment is not refundable." Then she asks "Want me to order again from Alder Print Co. for 2,000 msat, on the simulated rail, where no money moves?" and says you can choose another seller instead. She does not offer to change your spending limit: it changes only when you ask. The wallet balances do not change. Maya's book keeps the cancelled offer and her answer. Alder Print Co.'s book has no record of the deal.

4. Answer her question:

   ```
   Yes.
   ```

   **Expect:** this is the fresh yes after Don't buy: the same question as in step 3, and no second question in chat. Choose Buy anyway and click Submit: "You approved this held order (…). Paying now.", and the rest of step 14 as written. The approval is sealed in the deal's own records.

When the 7-day limit is the only reason, the question is Steven's limit question: titled "This order goes over your 7-day limit", with "Spent in the last 7 days", "With this order" and "Your 7-day limit" in place of the reasons, and the same last line. This run does not reach it, because every order here is also a first payment to its seller and cannot be refunded.

## Quit and re-entry

1. Quit Goose (Cmd+Q) and reopen on the same home, same rail, without reset.

   ```
   .venv/bin/python demo/ard/goose/open-windows.py --rail fake
   ```

   **Expect:** Kestrel's card still counts the lost dispute; the adjudicator's window opens on its case, which still shows the not-independent line and the ruling, as the tool prints them; nothing is paid twice. To run deal 1 again, reset and seed first.

## Fallbacks

1. The real rail fails (a wallet error, the buyer too low): quit Goose, open the simulated rail, use its opening line.

   ```
   osascript -e 'quit app "Goose"'
   .venv/bin/python demo/ard/goose/open-windows.py --rail fake
   ```

2. Without Goose: the same two deals and the countersign upgrade after deal 2 in one terminal (start the countersigner first, Before each run step 2). Enter moves on; each dialog is a yes or no at the prompt; Ctrl-C ends it.

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

   Do this step even when you stop for now: each open seller window sends Action State's witness a routine time-stamp about once a minute. A window left open stops those after 2 hours with no deal activity (its activity says "Routine time-stamps stopped"), and the stage the windows share stops once every window has quit.

2. Check that nothing of the demo is left running.

   ```
   ps -ax | grep -E "[d]emo/ard|[c]apsule_anchor"
   ```

   **Expect:** nothing printed.

3. [Real] The wallets are not reset: a real payment stays paid, and both balances stay as they are.

4. Opening Goose normally uses your own settings again.

5. Optional: remove the demo entirely.

   ```
   rm -rf ~/ard-demo ~/.config/ard-commerce-goose
   ```

## Running this guide with an agent

An agent with a terminal can run the command blocks for you: the set-up script (Set up, once) up to its question in step 8, Real rail, In every terminal, Before each run steps 1 to 5 (reset, seed and its wait, the balances, opening the windows), and the shutdown. It must stop and hand over to you for:

- anything that asks for your password or a sign-in: Homebrew's install, the Claude Code sign-in and the model choice, sign-in or key (all in the set-up script, Set up step 8), funding a real-rail wallet;
- the safety step: checking each window's extensions (Before each run step 8). It is what keeps a window's agent to its own tools, so you do it, not the agent. (The set-up script turns every extension off itself, Set up step 9, and checks it.);
- Goose's Trust and Execute prompts, every macOS permission prompt and tiling the windows by hand (Before each run step 6);
- the run itself: typing in the windows and answering every dialog (Set limit, Pay or Buy anyway, Received, Dispute). Only an answer submitted in a party's window, or typed there as Maya's reply, answers its dialog. No dialog asks you to rule: the adjudicator rules on its own.

While the demo's windows are open, the agent that drives this guide must not have screen control (computer use): with it, it could answer a dialog itself. Run the run's steps yourself.

## Troubleshooting

1. **Reset refuses.** It names the process holding the demo home or the stage's ports. Close it (a terminal: `cd ~`), or stop the process it names, then reset again. A refusal at the first checks changes nothing; a refusal after reset stopped the demo's own processes says which it stopped, and keeps the home. An app with a folder of the demo home open counts too: the Claude app, for one, keeps a folder you connected to a session open (the demo's `pages` folder, say).
   - First choice: remove that folder from the Claude session (or quit the app), then reset again.
   - If you can't now, use a new home: add `export ARD_HOME=~/.config/ard-commerce-demo-2` to the export in "In every terminal", in every terminal, for this run and every later one (reset, seed, the windows, `demo.py run` and the cleanup all read it), then reset and seed. Don't connect the new home's `pages` folder to a Claude session, or the same refusal comes back.
   - The old home keeps its files until you reset it once the app has let go: `(cd demo/ard && ARD_HOME=~/.config/ard-commerce-demo ../../.venv/bin/python demo.py reset)`.
   A `stage.py` left from an earlier run is stopped by reset itself.

2. **Seed says a seller's sample deals were not stamped by the witness within their window.** The witness did not take the stamp in time (no network, or it answered slowly): check the network, or set `ARD_WITNESS=off`, then reset and seed.

3. **A command says a variable is not set.** Copy the export line it prints, put in your own paths, and run it again.

4. **The adjudicator's case says Kestrel Print: no answer yet.** With a slow witness an answer can take a minute or two: wait and ask again. If it still says so, Kestrel's window is not running: open it and ask again. Two minutes after it asked, the adjudicator rules on Maya's answer alone, which carries the records Kestrel signed that she holds, its delivery record and its statement among them.

5. **A window shows nothing new.** Bring it to the front (Cmd+`); a background window may not draw its reply.

6. **Maya finds only one seller.** A seller publishes its entry when its window starts. Wait until both seller windows are open, then ask again.

7. **Goose asks Trust and Execute again.** Expected after every reset: reset clears the trust in the demo's recipes. Once, after moving to this version from one before evidencebook-skills#277: the first reset finds no note of the demo's recipes and deletes no trust, so the next windows may open without a Trust prompt; from the next reset on, it is asked again.

8. **A window says a step is "not done yet (the reason is in this party's log, agent.log); trying again".** The window keeps trying on its own. The full error is in that party's log: `~/.config/ard-commerce-demo/<maya|alder|kestrel|adjudicator>/agent.log` (under `$ARD_HOME` if you set it).
