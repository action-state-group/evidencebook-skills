---
name: evidencebook-report
description: Answer "what happened" from a person's or a node's evidence book at the right grade, name the grade, and offer the higher one. Narrated (the agent reads sealed records and talks), sealed and checked (an EvidenceBook report built, verified and sealed through capsulectl), or stamped (the History card and the receipt, which are never narrated). Thin on verbs, strict on grades.
---
# EvidenceBook report: three grades, named every time

A person asks their agent "what happened with the cleaner?", "how did my agent do this
month?", "make an EvidenceBook report", "send me the receipt". A Mesh node operator presses
the same questions as buttons. This skill decides which **grade** of answer the question
calls for, produces it with the verbs below and nothing else, says which grade it is in
the person's own words, and offers the next grade up whenever the answer carries a count
or might be passed on. It never produces a score, a grade letter or a percentage, and it
never states a number that is not read from a sealed Result or a signed derivation.

The three grades, and the words the person hears:

| Grade | What it is | The person hears | Shareable? |
|---|---|---|---|
| **1 · narrated** | the agent reads sealed records and answers in prose | "narrated by your agent, from your records" | no: for the person's own eyes |
| **2 · sealed and checked** | an Evidence Result sealed in the book, a page built from the verified bundle, the page's digest sealed; anyone verifies it offline | "sealed and checked: an EvidenceBook report" | yes: the page and the bundle |
| **3 · stamped** | the History card (a signed derivation as of a witnessed checkpoint) and the receipt (one deal's sealed records, both halves) | "stamped" | yes, by construction; these are what travel |

Grade 3 is never narrated: a question about one deal is answered by reading its receipt
and saying so. Grade 1 may be answered freely, under the rules below. Grade 2 is produced
only through the verbs, never written by the agent.

## Choosing the grade

1. The person asks about **one deal** ("the cleaner", "the bike sale", "that $40 lesson"):
   read the deal's records (grade 3) and answer from them. Offer "send me this receipt" as
   the stamped form. Never summarize a receipt as if it were a narration of memory.
2. The person asks **what happened over a period or a kind** ("how did my agent do this
   month", "did everything I approved go through"): grade 1, from sealed Results and
   derivations only. If no Result covers the period, say so: counts come from Results,
   and without one the agent can list deals but not total them.
3. The person says **"make an EvidenceBook report"**, "make it official", "I need to show
   this to someone", or a grade-1 answer contained a count or a judgment: grade 2, if a
   Terms Pack (an Evidence Contract) covers the question. If none does, run
   `python3 scripts/packs.py refuse` (or `require NAME` for a pack the person named,
   which exits 3 when that pack is missing or not compiled) and say its `say` sentence:
   it names the packs that exist by title and offers grade 1 or the History card (the
   person's checkpoints and receipts; no totals yet). It states no count.
4. Anyone **other than the holder** asks: this skill does not answer them. Evidence
   requests from other parties are answered by `book respond` under the share policy, by
   the `capsulectl-book` skill, never by narration.

After any grade-1 answer that states a count, or that the person says they will forward,
end with one sentence: **"Tell me if you'd like an EvidenceBook version of this: sealed,
checked, and the same page anyone can verify."** Say it once per answer, not per number.

## Grade 1: narrated

Verbs: `cll list`, `get --raw --output FILE` then `verify --capsule FILE` (never read a
record you have not verified), `book reconcile` (read-only), and the book's own served
derivations where the holder's host exposes them. A sealed Result is not a capsule, so
`get` does not return it: read it from its bundle once `verify --bundle` says `VALID`
(the Result is the root's statement). No record is sealed: reading is not a
consequential action.

Before the person sees a narration, run
`python3 scripts/narration_check.py --narration ANSWER.txt --record ID=FILE ...` with
each record it cites. It checks the rules below against those records: every statement
cites a record, and every number is held by a record cited in the same sentence. Write
numbers as digits so the check can read them. A finding means rewrite the answer; it is
never delivered as it stands.

Rules that make a narration safe:

- **Every number is read, never computed.** A count comes from a sealed Evidence Result's
  `aggregate` or a signed derivation (the History card). If the question needs a number no
  Result holds, say "I can list them; I can't total them until a report is run", and offer
  grade 2.
- **Cite what you read.** Each statement names the record ids it rests on, as
  `[RECORD_ID]`, so the person can tap through to the receipt or the Result.
- **Say whose words they are.** A judge's reason is "the judge wrote"; a counterparty's
  half is "their record says"; the agent's own reading is "I read".
- **Label it.** The first or last line says "narrated by your agent, from your records".
- **Keep it in the room.** A narration is for the holder. It is never sent to another
  party and never attached to an offer.

## Grade 2: sealed and checked (the EvidenceBook report)

Preconditions, checked before any verb runs:

- A **pack** whose contract covers the question. `python3 scripts/packs.py list` names
  the packs in this repository, each with its title, compiled spec and card. Two packs
  are **not written yet**: a Muse personal-deals pack (intentions, approvals, both
  halves) and a Mesh node's inference-deals pack (card `settlement`). An agent asked for
  an EvidenceBook report that only one of them would cover says so (`packs.py refuse`)
  and offers grade 1 or the History card.
- The pack's **judge pin** resolves (`judge pin FILE`), as `daily-judge-and-close` requires.
- The book profile is the holder's own (`--profile NAME`).

Steps, in order; each one's output is the next one's input. For the airline support and
EU AI Act packs, one command runs steps 1 to 5:
`scripts/report.sh --spec SPEC --profile NAME --date FROM --to TO --out report.html --seal --judge-backend live`
with the spec `packs.py` names. `--judge-backend live` runs the pack's real judge (it
needs `TYPESAFE_API_KEY` and makes model calls); the default `mock` backend is for demos
and tests, and its page says no model read the conversations, so it is never handed over
as a report. The command stops at the first refusal, and it leaves no page at `--out`
unless `report check` says `match` with the embedded evidence `VALID`.

1. **Judge.** Run the pack's judge over the period's cases exactly as
   [`../daily-judge-and-close/SKILL.md`](../daily-judge-and-close/SKILL.md) does
   (`scripts/run_daily.py` for the cron packs, `scripts/judge_bundle.py` for
   `everyday-rules`). Days already judged are not re-judged. The outcome is an Evidence
   Result v0 document whose claims cite the sealed `evaluation-report/v1` records.
2. **Seal the Result.**
   `capsulectl book result build --profile NAME --result RESULT.json --contract <pack_id>@<version> --out RESULT.sealed.json --capsule-out RESULT.capsule.json`.
   It refuses a Result whose headline numbers do not recompute from its claims, or that
   cites a record the book does not hold. A refusal is reported verbatim; the skill never
   edits the Result to get past it.
3. **Build the bundle.** Disclose the Result record and its closure with the `capsulectl`
   core skill's bundle verb, under the holder's disclosure policy. The bundle must verify
   `VALID`; `INCOMPLETE` or `INVALID` stops here and the person is told what is unmet.
4. **Build and seal the page.**
   `capsulectl book report build --profile NAME --bundle BUNDLE.json --card CARD --presentation PRESENTATION.json --out report.html --seal`.
   `--card` is the pack's card (table above). `--presentation` carries only a display
   name, a logo as a `data:image/` URL, and a title; nothing else goes in it. `--seal`
   writes the page's SHA-256 into the book and checkpoints it. Never deliver a `--dry-run`
   page: it is marked draft, mints no permalink and is never sealed.
   The **wording pack** (`aac.wording-pack/v0`: consumer/en for a person, the node
   operator's pack for Mesh) is applied through the SDK's `report.View.Wording`
   (`evidencebook/report` v0.2.0). On the command line it is `--wording FILE
   --wording-digest SHA256`, which is on evidencebook main but not yet in a
   capsulectl-book release; a page built with a released capsulectl-book carries the
   viewer's base words, and the skill says so. A worded page gets no permalink, by
   design: the permalink would carry the bundle without the words.
5. **Check.** `capsulectl book report check --profile NAME --page report.html` must say
   `match`. Anything else (`mismatch`, `no sealed record`, `not covered by a checkpoint`)
   is reported verbatim and the page is not handed over.
6. **Hand over** the page and the bundle together, with one sentence: "Sealed and
   checked. Anyone can verify this page offline without us; `report check` proves it is
   the one your book sealed." Say which pack and which window it covers.

What grade 2 can and cannot do today: the page is the contract report (the Result's
rows and statuses, grouped, in the wording pack's words). A report shaped by the person's
own question (a plan over a chosen dataset, with the plan and dataset digests sealed) is
the ad-hoc path, not built yet (capsule-viewer#81–#83, evidencebook#107). The skill
does not promise it.

## Grade 3: stamped

- **The receipt**: one deal's records as the holder holds them (the approval, the one-way
  action, the settlement object, the close, the counterparty half as received, the
  witness receipts). "Send me this receipt" exports the deal root's disclosed bundle.
  "Show me the other side's receipt" shows the counterparty half as received, labelled so.
  A receipt whose other side is missing is "your receipt only"; the skill never calls it
  agreed.
- **The History card**: a derivation the holder's book serves (`history_card/1` today:
  checkpoints, receipts and consistency proofs, no counts; the standard card with counts
  once its derivation is registered). "Show me what they see" asks the holder's own
  responder as a stranger would (`book doctor --probe`) and shows the answer. The card is
  never typed by the agent.

## Every action seals a record

Steps 2 and 4 (with `--seal`) are primary actions: running them is the record. Step 1
seals its reports as `daily-judge-and-close` does. Steps 3 and 5 and every grade-1 read
seal nothing. Any other action this skill takes (a judge pin resolved on its own) is
sealed with `scripts/skill_action.py` as a `skill-action/v1` capsule, digests only. A seal
that fails is reported as `evidence unavailable` and the skill stops before the next
consequential step.

## What this skill never does

Compute, estimate or round a number. Show a score, a grade letter or a percentage. Present
a narration as sealed, or a draft page as a report. Pick a pack the question does not
match, or judge days a prior run sealed. Share a narration, a receipt or a report with
anyone but the holder. Edit a Result, a page or a wording pack to get past a refusal.
Answer another party's evidence request.

## Status, 2026-10-28

Shipped: `capsulectl book result build`, `report build --seal`, `report check` on
evidencebook main (not yet in a capsulectl-book release); `evidencebook/report` v0.2.0
with `View.Wording` and `View.ContractReport`; the three packs above with their judges;
`scripts/report.sh --seal`, `scripts/packs.py` and `scripts/narration_check.py`, run
end to end by `tests/fresh_env_report.sh`.
Not yet: a Muse personal-deals pack; a Mesh inference-deals pack; a released command-line
wording flag (`--wording` is on evidencebook main); the standard History card
derivation; the ad-hoc report path. The skill states each gap to the person instead of
working around it.
