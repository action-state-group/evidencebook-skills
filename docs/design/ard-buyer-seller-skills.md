# Design note: a buyer skill and a seller skill for buying and selling with evidence

Status: draft, round 1, for Codex, Kimi, the Sherlock2 twin and the real Sherlock2. Issue:
[evidencebook-skills#169](https://github.com/action-state-group/evidencebook-skills/issues/169).
No code yet.

**The bar.** None in THE_LOOP. The bar is Ethan's ask of 2026-11-17: "要做，顺带就可以把文字更新。先把方案定下来，然后跟 sherlock and it's twin converge，然后修改。" ("Do it, and update the wording along the way. Settle the plan first, converge it with Sherlock and its twin, then change it.") Latest Steven ruling on buyer or seller skills: none found (ops DECISION logs, all eight lanes, read 2026-11-17). When this is done, a person who wants to buy or sell with evidence installs two skills and a pack instead of copying the ARD demo's Python, and the demo runs from them.

## 1. The problem

The Goose Desktop ARD two-seller demo (evidencebook `python/examples/ard-commerce`, pinned at 3ed74d7; about 2,700 lines, plus about 2,470 reused from `python/examples/goose`) does what any buyer or seller with evidence needs:

- **Buyer (Maya):** find sellers in an ARD catalogue, check each seller's signed `evidence-commitment/1`, ask each seller for its History card and selection over the mailbox its commitment names, verify the answers, decide how far to trust each seller under an admission pack, show the person the comparison, let the person pick, get the person's approval to pay, pay, and show a receipt and the updated History card.
- **Seller (Alder, Kestrel):** advertise one signed commitment with a stapled History card, answer evidence requests, take a deal at its listed price, check the buyer's records, record the sale and its own checkpoint.

Today the decisions (what to ask, when to stop, when to ask the person, what to say) live in each Goose recipe's instructions (`goose/open-windows.py`), and the steps live in a demo MCP server (`desktop_server.py`). Nothing of it is a skill: `skills/` here has daily-judge-and-close, evaluation-compiler, evidence-contract-compile, evidencebook-report, terms-pack-author and weekly-blind-expert.

## 2. What already exists, and is reused as is

| Need | Exists | Source |
|---|---|---|
| The trust and limit rule | An admission pack, compiled here and run by `capsule-engine admission evaluate`; verdict GO, ASK, LIMIT or NO, with the tier and the deciding rows. The demo's pack is a copy of `packs/admission-baseline` with its threshold edited ("50 per 1,000"). | `docs/admission-pack-profile-v0.md`; demo `pack.py`, `buyer.assess`; Steven u582 (2026-10-30): admission uses the Terms Pack build, "the SDK does the math" |
| Recording a purchase or a sale, and the check before paying | The `deal` skill and `capsulectl deal` (x-deal-v0): Purchase (`deal open`, `deal note --kind intent`, `deal check` with `"action":"pay"`, ask the person with its `approval_text`, `deal note --kind act`, `deal close`) and Sale (`deal sale new`, `deal open --sale`, `deal check` with `"action":"commit"`) | evidencebook-deal `skills/deal/SKILL.md:52-63`, `:191-293` |
| Finding a commitment through ARD | `capsulectl commitment find --directory URL/.well-known/ard.json --node-key HEX` | capsule-cli `cli/commitment_cmd.go:12-13` |
| Asking and answering an evidence request | `request` and `respond`, which capsulectl-book and the deal skill use | capsule-cli `cli/evidence_request_cmd.go:52,148` |
| A person's own buyer pack | `packs/admission-muse-buyer` (admission-baseline without the platform rows, plus the own-settled lift) | #168; Steven u600 (2026-11-17) |

Missing as verbs: publishing a commitment with its stapled card, serving or listing an ARD catalogue entry, and the Nostr mailbox carriage the demo's commitment names. These exist only as demo Python (`goose/commitment.py`, `ard-commerce/ard.py`, `goose/nostr_mailbox.py`, `ard-commerce/responder.py`).

## 3. Decision

### 3.1 Two skills in this repository

- `skills/buy-with-evidence/` (buyer) and `skills/sell-with-evidence/` (seller), each a hand-authored `SKILL.md` with a byte-identical `AGENTS.md`, the pattern `skills/README.md` gives for reasoning skills. They own the decisions and the words: what to ask for, how to compare sellers, when to stop, when to ask the person, and what to tell them.
- They call verbs; they never reimplement a check. Every step names the verb or tool it calls and what the person is told.
- They hand the deal itself to the `deal` skill's Purchase and Sale procedures, so the check before paying (`deal check` with `"action":"pay"` and the person's approval) is the deal skill's, not a second copy.

### 3.2 The buyer skill's procedure

1. Take the person's ask in their own words (what, by when, the most they will pay) and open the deal (`deal open`).
2. Find sellers in the catalogue the person names; check each seller's commitment (signature, key matches the entry, digest). A seller whose commitment fails is shown as failed, never assessed.
3. Ask each seller for its History card over the commitment's `ask` route and verify the answer; ask for `standard_history/1` and the selection only behind a signed ask (u517).
4. Assess each seller with the person's admission pack (default `admission-baseline`; the person may tighten a threshold, which recompiles the pack as `terms-pack-author` does). The skill shows each verdict, its tier and the deciding rows in plain words.
5. Show the comparison and let the person pick. The skill recommends; it never picks. A seller whose verdict is not GO can be picked, and then no deal opens and nothing is paid (today's demo behaviour).
6. Seal the pick (`deal note --kind intent`), run `deal check` with `"action":"pay"` and the exact amount, and ask the person with the check's own approval text. Pay only on their yes. The admission decision stays in the person's own book, not in the deal (u528).
7. After payment: the receipt and the person's updated History card, each from the person's own records.

### 3.3 The seller skill's procedure

1. Publish one signed commitment with its stapled History card (u545: one commitment over the carriers; u517: the staple is `history_card/1`) and list it in the catalogue the seller names.
2. Answer evidence requests that arrive over the commitment's route, from the seller's own records only.
3. Take a deal only at the listed price and terms (`deal sale new` floor, `deal check` with `"action":"commit"`); check the buyer's records; record the sale; take the next checkpoint so the card counts it.
4. Say on the receipt what the records do and do not hold, for example that what the seller's wallet was credited is not in them (evidencebook#499).

### 3.4 The trust and limit rule is a pack, not Python

The demo's pack copy moves out of evidencebook into this repository as `packs/ard-demo-buyer/` (pack source, compiled pack, fixtures), labelled as a demo pack with placeholder thresholds. The buyer skill points at a pack by path or id; the demo points at this one. The input mapping the demo builds in Python (`buyer.inputs`) becomes the skill's documented mapping from verified evidence to the evaluator's inputs (§5 of the profile), so another host can build the same inputs.

### 3.5 What the person sees: thin recipes and the listings

- **Thin recipes (Ethan, 2026-11-17).** Each party's Goose recipe becomes "load the buyer (or seller) skill and this pack", plus the party's name, item and price. Its instructions carry nothing of their own beyond that. The presenter shows each recipe on screen.
- **The listings.** Before Maya searches, the presenter shows the catalogue entries and each seller's signed commitment (price, what evidence it answers, the signature) in a browser window, not in code. On the current pin this is already possible: the stage serves `/.well-known/ard.json` and `/commitments/<name>.json`.

### 3.6 Staging: two steps

- **Step A (for the demo on Wednesday 2026-11-18).** The two skills and the demo pack land here. The steps the skills call are the demo's existing tools (the `ard_*` MCP tools in evidencebook `desktop_server.py`), named in each skill as this host's tools for the steps of §3.2 and §3.3. The recipes become thin (§3.5). The deal steps stay the demo's own records for Wednesday, since the demo's deal is x-deal-v0 records written by the example code, not by `capsulectl deal`.
- **Step B (after the demo).** The skills' steps move to verbs: the deal to `capsulectl deal` (the v0 Purchase and Sale verbs now; the v1 verbs `deal offer`, `deal agree`, `deal perform`, `deal settle`, `deal dispute` when evidencebook-deal#215 and evidencebook#461 land), the evidence steps to `capsulectl commitment find` and `request`/`respond`, and the missing ones (publish a commitment, list in a catalogue, the mailbox carriage) to new verbs in their owning repositories, each its own issue. The generic parts of `goose_node.py` go to the evidencebook library only where #461's v1 work already covers them.

### 3.7 Where the demo lives

The demo stays in evidencebook for step A: it is pinned and rehearsed there, and its server imports the `python/examples/goose` modules. In step B it moves here as `demo/ard/` (launcher, seeded 48-deal history, simulated seller behaviour, presenter text), once its tools are verbs and it no longer imports example code from another repository. Placement is engineering's call (asg-rules, Work tracking).

## 4. Doors

- **Steven: the buyer and seller skills as a product surface.** They decide for a person: the buyer skill recommends but never picks, never pays without the person's yes to the deal check's approval text, and stops when the pack's verdict is not GO; the seller skill answers evidence requests on its own and commits to a sale only at its listed price. This is new behaviour a person relies on, so it goes to Steven. One-line question: "May evidencebook-skills ship a buyer skill that assesses sellers with the person's admission pack, recommends but never picks, and pays only on the person's yes to the deal check, and a seller skill that answers evidence requests on its own and sells only at its listed price?"
- **Not doors.** The pack's location and the demo's location (engineering's call); the wording on screen (Sherlock2's, under the wording delegation).

## 5. Tests and the by-hand run

- Each skill: a test that `AGENTS.md` equals `SKILL.md` (`tests/test_skill_tree.py` already holds this) and that every verb or tool it names exists.
- The pack: `scripts/pack_compile.py` compiles it and its fixtures give the demo's verdicts (Alder GO, Kestrel LIMIT at 50 per 1,000).
- The demo: the existing `ard-commerce` suite, plus a by-hand run of the three windows on the simulated rail from `demo.py reset`, with the recipes loading the skills, through the listings, the cards, both picks, one Pay click and the receipts.

## 6. Open questions

1. Should the buyer skill's default pack be `admission-baseline` or `admission-muse-buyer` for a person with no pack of their own?
2. Does the seller skill own its listing in the catalogue, or only its commitment, with the catalogue run by whoever hosts it (u545: no discovery system of our own)?
