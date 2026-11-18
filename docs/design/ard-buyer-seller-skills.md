# Design note: a buyer skill and a seller skill for buying and selling with evidence

Status: draft, round 1, for Codex, Kimi, the Sherlock2 twin and the real Sherlock2. Issue:
[evidencebook-skills#169](https://github.com/action-state-group/evidencebook-skills/issues/169).
No code yet.

**The bar.** None in THE_LOOP. The bar is Ethan's ask of 2026-11-17: "要做，顺带就可以把文字更新。先把方案定下来，然后跟 sherlock and it's twin converge，然后修改。" ("Do it, and update the wording along the way. Settle the plan first, converge it with Sherlock and its twin, then change it.") Latest Steven ruling on buyer or seller skills: none found (ops DECISION logs, all eight lanes, read 2026-11-17). When this is done, a person who wants to buy or sell with evidence installs two skills and a pack instead of copying the ARD demo's Python, and the demo runs from them.

## 1. The problem

The Goose Desktop ARD two-seller demo (evidencebook `python/examples/ard-commerce`, pinned at 3ed74d7; about 2,700 lines, plus about 2,470 reused from `python/examples/goose`) does what any buyer or seller with evidence needs:

- **Buyer (Maya):** find sellers in an ARD catalogue, check each seller's signed `evidence-commitment/1`, ask each seller for its History card and selection over the mailbox its commitment names, verify the answers, assess each seller under an admission pack, show the person the comparison, let the person pick, get the person's approval to pay, pay, and show a receipt and the updated History card.
- **Seller (Alder, Kestrel):** advertise one signed commitment with a stapled History card, answer evidence requests, take a deal at its listed price, check the buyer's records, record the sale and its own checkpoint.

Today the decisions (what to ask, when to stop, when to ask the person, what to say) live in each Goose recipe's instructions (`goose/open-windows.py`), and the steps live in a demo MCP server (`desktop_server.py`). Nothing of it is a skill: `skills/` here has daily-judge-and-close, evaluation-compiler, evidence-contract-compile, evidencebook-report, terms-pack-author and weekly-blind-expert.

## 2. What already exists, and is reused as is

| Need | Exists | Source |
|---|---|---|
| The trust and limit rule | An admission pack, compiled here and run by `capsule-engine admission evaluate`; verdict GO, ASK, LIMIT or NO, with the tier and the deciding rows. The demo's pack (`demo/ard_admission/1.0.0`) is derived from `packs/admission-baseline`: msat-scale tiers, the demo's own trust roots, no `claims-held` row, a band-history row; it starts at 100 per 1,000 and the presenter tightens it to 50 during the show, which recompiles it. | `docs/admission-pack-profile-v0.md`; demo `pack.py`, `buyer.assess`; Steven company-oss u582 (2026-10-30): admission uses the Terms Pack build, "the SDK does the math" |
| Recording a purchase or a sale, and the check before paying | The `deal` skill and `capsulectl deal` (x-deal-v0): Purchase (`deal open`, `deal note --kind intent`, `deal check` with `"action":"pay"`, ask the person with its `approval_text`, `deal note --kind act`, `deal close`) and Sale (`deal sale new`, `deal open --sale`, `deal check` with `"action":"commit"`) | evidencebook-deal `skills/deal/SKILL.md:52-63`, `:191-293` |
| Finding a commitment through ARD | `capsulectl commitment find --directory URL/.well-known/ard.json --node-key HEX` | capsule-cli `cli/commitment_cmd.go:12-13` |
| Asking and answering an evidence request | `request` and `respond`, which capsulectl-book and the deal skill use | capsule-cli `cli/evidence_request_cmd.go:52,148` |
| A person's own buyer pack | `packs/admission-muse-buyer` (admission-baseline without the platform rows, plus the own-settled lift) | #168; Steven company-oss u600 (2026-11-17) |

Missing as verbs: publishing a commitment with its stapled card, serving or listing an ARD catalogue entry, and the Nostr mailbox carriage the demo's commitment names. These exist only as demo Python (`goose/commitment.py`, `ard-commerce/ard.py`, `goose/nostr_mailbox.py`, `ard-commerce/responder.py`).

## 3. Decision

### 3.1 Two skills in this repository

- `skills/buy-with-evidence/` (buyer) and `skills/sell-with-evidence/` (seller), each a hand-authored `SKILL.md` with a byte-identical `AGENTS.md`, the pattern `skills/README.md` gives for reasoning skills. They own the decisions and the words: what to ask for, how to compare sellers, when to stop, when to ask the person, and what to tell them.
- They call verbs; they never reimplement a check. Every step names the verb or tool it calls and what the person is told.
- They hand the deal itself to the `deal` skill's Purchase and Sale procedures, so the check before paying (`deal check` with `"action":"pay"` and the person's approval) is the deal skill's, not a second copy.

### 3.2 The buyer skill's procedure

1. Take the person's ask in their own words (what, by when, the most they will pay) and open the deal (`deal open`).
2. Find sellers in the catalogue the person names; check each seller's commitment (signature, key matches the entry, digest). Keep two things apart when telling the person: the catalogue entry's offer (item and price) is the catalogue's, unsigned; the signed commitment says how to ask the seller for evidence and under which key, not the price. Matching the entry's key proves only that the entry and the commitment agree; it binds the seller's identity only when the key also comes from somewhere independent of the carrier, such as an earlier deal or a request the person already holds (`commitment find --node-key`). A seller whose commitment fails is shown as failed, never assessed. A commitment with no witness is shown as "unwitnessed", and its first checkpoint is pinned on first contact (spec u545: "witness REQUIRED, plus a simple design for nodes without one"; evidence-network u186: witnessing is opt-in, so most sellers are unwitnessed).
3. Ask each seller for its History card over the commitment's `ask` route and verify the answer; ask for `standard_history/1` and the selection only behind a signed ask (u517).
4. Assess each seller with the person's admission pack (default `admission-muse-buyer`, §6; the person may tighten a threshold, which recompiles the pack as `terms-pack-author` does). The skill shows each verdict, its tier and the deciding rows in plain words.
5. Show the comparison and recommend, with each verdict's deciding rows, never a rank or a score; the person picks. The verdicts mean what the admission profile says (`docs/admission-pack-profile-v0.md` §2 rows table, §3.5 effect, steps 6 to 8): **GO** lets the deal go ahead; **ASK** means the pack makes its Evidence Request of that seller (within the pack's budget), and the skill re-assesses on the answer; **LIMIT** admits the seller only up to a lower tier, so the skill tells the person the most the pack admits for this seller and offers that or another seller; **NO** stops. A pick the verdict does not allow pays nothing: the errand's deal, opened at step 1, records the pick and the verdict and closes as not done (the deal skill's "one errand, one deal"). The demo is the narrower case: Kestrel's LIMIT at 50 per 1,000 admits deals under 100 msat, its price is 268, so nothing is paid; the demo host opens a deal only on GO.
6. Seal the pick (`deal note --kind intent`), run `deal check` with `"action":"pay"` and the exact amount, and ask the person with the check's own approval text. Pay only on their yes. That yes is the person's approval: it carries the person's own key signature where the host supports it (company-oss u599; AAC#627), and otherwise the skill says "your own key's signature: missing" rather than present an agent-relayed yes as signed. The admission decision stays in the person's own book, not in the deal (proprietary u528).
7. After payment: the receipt and the person's updated History card, each from the person's own records.

### 3.3 The seller skill's procedure

1. Draft one signed commitment with its stapled History card (spec u545: one commitment over the carriers; proprietary u517: the staple is `history_card/1`; spec u563 adds `history_card/2`, with `/1` kept, as the later staple) and, only after the seller says yes (the Sale procedure's confirmation before posting a listing), submit it and the listing to the carriers the seller names (an ARD entry is one). The seller owns its commitment and never hosts or runs a catalogue (u545: no discovery system of our own). The skill says whether the commitment is witnessed.
2. Answer evidence requests that arrive over the commitment's route, from the seller's own records only, and only what the commitment advertises; `standard_history/1` only behind a signed ask (proprietary u517). The skill honours the seller's share setting: sharing is on by default, with a clear notice at setup and a one-flag opt-out (evidence-network u56).
3. Take a deal through the Sale procedure's full flow (offer, acceptance, `deal check` with `"action":"commit"`), only at the listed price or above, never below, and only when every term matches the listing (item, currency, rail, refund terms), not the price alone; check the buyer's records; record the sale; take the next checkpoint so the card counts it. The seller skill never pays out.
4. Say on the receipt what the records do and do not hold, for example that what the seller's wallet was credited is not in them (evidencebook#499).

### 3.4 The trust and limit rule is a pack, not Python

The demo's pack copy moves out of evidencebook into this repository as `packs/ard-demo-buyer/` (pack source, compiled pack, fixtures), labelled as a demo pack with placeholder thresholds. The buyer skill points at a pack by path or id; the demo points at this one. The skill documents the mapping from what was verified to the evaluator's inputs (§5 of the profile): each input comes from a verified answer, the person's own records or the person's configuration, and an input nothing supplies is left absent, never filled in as a pass (the pack then decides on the absence, for example LIMIT). The demo's Python mapping (`buyer.inputs`) is not that mapping: it fills operator facts (platform valid, allow-listed, the demo's witness and controller), sets the person's own history to zero and reads the seller's selection as verified although it carries no inclusion proofs. It stays a labelled demo adapter in step A and is not copied into the skill.

### 3.5 What the person sees: thin recipes and the listings

- **Thin recipes (Ethan, 2026-11-17).** Each party's Goose recipe becomes "load the buyer (or seller) skill and this pack", plus the party's name, item and price. Its instructions carry nothing of their own beyond that. The presenter shows each recipe on screen.
- **The listings.** Before Maya searches, the presenter shows the catalogue entries and each seller's signed commitment (price, what evidence it answers, the signature) in a browser window, not in code. On the current pin this is already possible: the stage serves `/.well-known/ard.json` and `/commitments/<name>.json`.

### 3.6 Staging: two steps

- **Step A (for the demo on Wednesday 2026-11-18).** The two skills and the demo pack land here, each skill marked "demo host, step A" at its top and naming the `ard_*` tools as "this demo host's tools", not verbs, so nobody who tries them after the demo copies the demo-only steps. The steps the skills call are the demo's existing tools (the `ard_*` MCP tools in evidencebook `desktop_server.py`), named in each skill as this host's tools for the steps of §3.2 and §3.3. The recipes become thin (§3.5). The deal steps stay the demo's own records for Wednesday, since the demo's deal is x-deal-v0 records written by the example code, not by `capsulectl deal`.
  - Each skill states where the demo host differs from its procedure: the seller is a fixed demo merchant whose commitment and listing the demo operator publishes; it takes Maya's deal on price alone; Maya's pay step asks with the demo's own dialog, not `deal check`; the evaluator's inputs come from the demo adapter (§3.4). A host runs either the `ard_*` tools or the generic deal procedure for one errand, never both.
  - Wiring: `open-windows.py` builds each recipe's instructions from the skill file in a pinned evidencebook-skills checkout, plus the party's name, item and price; `pack.py` reads `packs/ard-demo-buyer/pack-source.yaml` from that checkout. The run sheet pins the evidencebook-skills commit beside the evidencebook one.
- **Step B (after the demo).** The skills' steps move to verbs: the deal to `capsulectl deal` (the v0 Purchase and Sale verbs now; the v1 verbs `deal offer`, `deal agree`, `deal perform`, `deal settle`, `deal dispute` when evidencebook-deal#215 and evidencebook#461 land), the evidence steps to `capsulectl commitment find` and `request`/`respond`, and the missing ones (publish a commitment, list in a catalogue, the mailbox carriage) to new verbs in their owning repositories, each its own issue. The generic parts of `goose_node.py` go to the evidencebook library only where #461's v1 work already covers them.
  - **Discovery for real (Ethan, 2026-11-17).** Sellers publish their entries at `https://{domain}/.well-known/ard.json` (ARD v0.91 §5.1, https://agenticresourcediscovery.org/spec: a manifest with an `entries` array). The buyer skill queries the ARD registries the person configures through their search interface (§5.3.2 `POST /search`, with `"federation": "referrals"` returning `referrals` to other registries the client may query) and then fetches and verifies each seller's commitment itself. A registry finds sellers; it is never what the person trusts: ARD "does not define a signing or verification procedure of its own" (§4.5.2), a registry only SHOULD verify trust manifests (§4.5.2), and a search's relevance score is not a trust rating (§3.3, §5.3.2). Registries crawl the hosted manifests (§5.2 "Ingestion Pipelines"). One gap to close in step B: the demo's entries carry a raw key in `trustManifest.identity`, while §4.5.1 says that identity "MUST align with the <publisher> domain embedded in the entry's discovery identifier" (a `urn:air:<publisher>:...` identifier, Appendix C), so a real entry needs a publisher domain and a discovery identifier the key is tied to. For the 2026-11-18 demo the presenter says plainly that the catalogue is local and the two sellers were set up in advance.

### 3.7 Where the demo lives

The demo stays in evidencebook for step A: it is pinned and rehearsed there, and its server imports the `python/examples/goose` modules. In step B it moves here as `demo/ard/` (launcher, seeded 48-deal history, simulated seller behaviour, presenter text), once its tools are verbs and it no longer imports example code from another repository. Placement is engineering's call (asg-rules, Work tracking).

## 4. Doors

- **Steven: the buyer and seller skills as a product surface.** They decide for a person:
  - The buyer skill recommends (with the deciding rows, never a score) but never picks, and never pays without the person's yes to the deal check's approval text. A pick follows the seller's verdict as the admission profile defines it: GO goes ahead, ASK asks the seller for the pack's evidence and re-assesses, LIMIT goes ahead only within the lower tier it admits, NO stops (§3.2 step 5).
  - The seller skill answers evidence requests with no person approving each answer, within limits: only what its commitment advertises, `standard_history/1` only behind a signed ask, and the seller's share setting. Posting the listing needs the seller's yes, and a sale goes through the Sale procedure at the listed price or above, with every listed term matching; it never pays out (§3.3).
  - The default pack for a person with none is `admission-muse-buyer` (§6): it changes who can get GO, so it is part of the question.

  This is new behaviour a person relies on, so it goes to Steven. One-line question: "May evidencebook-skills ship a buyer skill that assesses sellers with the person's admission pack, recommends but never picks, and pays only on the person's yes to the deal check, and a seller skill that answers evidence requests on its own and sells only at its listed price or above, with every listed term matching?" Updated after round 2 to match §3.3; the thread also has the default pack (`admission-muse-buyer`) and the seller's limits above. Ruling thread: buzz://message?channel=0d760ea3-529d-4dec-b309-24184967f8e0&id=e44aa2299018f0704ce9c3bc370793670c0253027f07ddd2702cecf56d74f998.
- Already ruled, so not new in the door: paying only on the deal check's approval (the deal skill), the pack doing the math (company-oss u582), sellers answering by default with an opt-out (evidence-network u56), the admission decision in the person's book (proprietary u528). The new product meaning is (a) an agent recommending a seller from a pack verdict and (b) the default pack for a person with none (§6).
- **Not doors.** The pack's location and the demo's location (engineering's call); the wording on screen (Sherlock2's, under the wording delegation).

## 5. Tests and the by-hand run

- Each skill: a test that `AGENTS.md` equals `SKILL.md` (`tests/test_skill_tree.py` already holds this) and that every verb or tool it names exists.
- The demo wiring: a test that each recipe's instructions come from the pinned skill file and that the assess step reads `packs/ard-demo-buyer`.
- Step B (with the verbs): a catalogue entry whose price was changed, a commitment under a swapped key, and a selection with no inclusion proofs each give the person a failed or unproven check, never a pass.
- The pack: `scripts/pack_compile.py` compiles it and its fixtures give the demo's verdicts (Alder GO, Kestrel LIMIT at 50 per 1,000).
- The demo: the existing `ard-commerce` suite, plus a by-hand run of the three windows on the simulated rail from `demo.py reset`, with the recipes loading the skills, through the listings, the cards, both picks, one Cancel (nothing paid, the agent does not retry on its own), one Pay click and the receipts, then a quit and re-entry of the windows with no second payment. If any of it fails, the demo runs on the current pin (evidencebook with ln-pay-local 3558d27), which stays the fallback.

Ruling citations name their ops lane, since numbers repeat across lanes (company-oss u528 and u545 are other rulings).

## 6. Settled questions

1. **The buyer skill's default pack** is `admission-muse-buyer` for a person with no pack of their own: the baseline's platform rows need facts a lone buyer cannot supply, and company-oss u600's own-settled lift was ruled for the person's own pack (Sherlock2 and its twin, round 1); `admission-baseline` stays the platform default. The demo uses its own pack (§3.4).
2. **The seller owns its commitment, not a catalogue:** it sends the commitment to a catalogue someone else runs and never hosts one (u545; Sherlock2, round 1). In the demo the stage runs the catalogue.
