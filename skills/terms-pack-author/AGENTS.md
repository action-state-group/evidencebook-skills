---
name: terms-pack-author
description: Turn a seller's deal terms, said in words, into a rows file, try them over past sales, compare two versions, and publish them so the next sale is checked against them. Use when the seller says what a good sale looks like ("paid before delivery", "delivered within a day", "price as offered"), asks to judge past sales under terms, changes a number in those terms, or says to use the terms on their sales.
---
# Terms: write them in words, try them, switch them on

A seller tells you what a sale should look like. You write it as rows in one small file,
try the rows over the sales already made, show what came through, and only when the seller
says so, publish them. The seller talks in their own words. They never need to hear a
file format, a tier, a kind, a verb, a book or a digest explained: say "your terms", "your
past sales", "came through", "missed", "could not decide".

Every command below is `terms <verb>`. It prints one JSON answer. Read it and tell the
seller what it says in a sentence or two; do not paste it. Work in the seller's workspace
(`~/studio`); the commands write only there (`lint`, `test` and `readiness` also refresh the table beside terms `init` wrote).

## Starting from past sales, with no terms yet

If the seller has sales but has not said what a good sale looks like, do not guess:
`terms init --deals FILE --pack-id NAME` (or `--exports DIR`, or `--store STORE`; the same
sales sources `run` reads). It reads the sales on this computer, writes a first set of
terms and a count of which fields the sales carry, all under `~/studio/packs/NAME/`, and
prints a table: each term with one status. The first three terms are in the pack and are
checked if it is published (`in_pack: true`). The others are ideas kept in `candidates.json`
(`in_pack: false`): they are never checked, and the table says what each is waiting for.

- **checkable now**: the sales carry what the term needs, and the answer says how many sales it can decide.
- **needs examples**: the term takes the seller's judgment, which these terms cannot run yet.
  Tell the seller so. If they want to say how it should go anyway, record their answer for
  each sale in `labels.json` beside the terms, as `{"matched_description": [{"deal_id": "...", "met": true}]}`
  (four sales; the table counts them).
- **needs a field**: the answer names the field the sales lack, or that no sale carries
  it together with its partner. Ask whether they can add it to their sales records, or want to
  drop the term (delete the row from the pack, or the idea from `candidates.json`).
- **needs the other side**: only the buyer's own record can show it.
- **not this pack's concern**: it is about the buyer's conduct, not the seller's terms.

Tell the seller what each term is and its status in a sentence each. The sales are not
sent anywhere or shown to you: you see the field names and counts and the sales the seller labels.
After any edit or run, `terms readiness ~/studio/packs/NAME/pack-source.yaml` shows the table
again; `lint`, `test` and `run` also rewrite `readiness.json` beside the terms, and a label
shows once one of them (or `readiness`) has run. Then continue with the steps below, using the
terms `init` wrote.

## Picking up where someone left off

The workspace folder is the whole state; you remember nothing between sessions. Another
agent, or the seller in a shell, may have started the terms. Read it first:
`terms history ~/studio/packs/NAME/pack-source.yaml` prints the sales the terms were tried
over, the last run, the table, and one line per version of the terms (its fingerprint,
version, and the run made with it). Then continue: `terms run SRC` with no sales flag reads
the same place again; if the answer says `dataset_changed: true`, tell the seller the sales are not
the ones the earlier versions were tried on, and run those versions again before you compare them. Nothing in the workspace records what was said in the conversation, and you
do not write it down; if the seller asks to keep it, `terms keep-transcript SRC FILE` copies a
file they name into a private folder beside the terms, and nothing else ever reads it.

**Going back.** To undo a change, `terms checkout SRC FINGERPRINT` (six or more characters
from `history`) puts that version of the terms back, `terms run SRC` tries it again, and
`terms compare OLDER NEWER` takes two fingerprints and names both. `checkout` refuses when the
terms have edits no run has recorded; tell the seller what would be lost and pass `--force`
only if they say so.

**A throwaway book for rehearsals** is an ordinary store in a throwaway folder, for example
`~/studio/dev-book`: create it with the `capsulectl` commands the seller already uses
(`profile create`, `store init`, `book backfill run`), then `terms init --store ~/studio/dev-book`.
Delete the folder when done; nothing else points at it.

## The file

Write `~/studio/packs/sticker-sale/pack-source.yaml`. Start from this, keep the three
rows and change only the words and the number:

```yaml
scope:
  kind: deal
pack_id: sticker-sale
pack_version: 0.1.0
title: Sticker sale terms
statement: >-
  A sticker sale came through when the buyer paid before delivery, the sticker
  was delivered within a day of payment, and the price was the price offered.
evaluator: transaction
rows:
  - id: paid_before_delivered
    statement: The buyer paid before the sticker was delivered.
    tier: recomputed
    check: paid_before_delivered
    proves: [paid_at, delivered_at]
  - id: delivered_within_days
    statement: The sticker was delivered within 1 day of payment.
    tier: recomputed
    check: delivered_within_days(1)
    proves: [paid_at, delivered_at]
  - id: price_as_offered
    statement: The price was the price offered.
    tier: recomputed
    check: price_as_offered
    proves: [offered_price, accepted_price]
```

Any sale works the same way, whatever is sold: `evaluator: transaction` judges a buyer
and a seller's deal, not stickers. This file is the worked example. If the seller sells
something else (coffee beans, a course, a used bike), write the same three rows in their
goods and words, set `pack_id` and `title` to match (for example `coffee-beans-sale`), put
the file at `~/studio/packs/<pack_id>/pack-source.yaml`, and keep `evaluator: transaction`.
The commands below show the sticker-sale path; for other goods, give each `terms` command
the path of the file you wrote.

The three checks are all there is: `paid_before_delivered`, `delivered_within_days(N)` (a
whole number of days, written inside the row) and `price_as_offered`. When the seller
changes the number, change it in both places: the `statement` and the `check`. Bump
`pack_version` (0.1.0 to 0.1.1) whenever a row changes, so the two versions can be told apart.

If the seller asks for a term none of the three can say (a rating, "the sticker looked
like the photo", a refund window), say plainly that these terms cannot check that yet.
Do not invent a row, a check or a field, and do not stretch one of the three to cover it.

## Steps

1. **Write the rows** from what the seller said. Use the seller's own words in each
   `statement`.
2. **`terms lint ~/studio/packs/sticker-sale/pack-source.yaml`**. If it says `valid: false`,
   fix what `issues` names and run it again.
3. **`terms test ~/studio/packs/sticker-sale/pack-source.yaml`**. Each row is tried on one
   sale it should accept and one it should refuse. If a row fails, fix it; never tell the
   seller their terms are ready while a row fails.
4. **Try the terms over past sales**:
   `terms run ~/studio/packs/sticker-sale/pack-source.yaml --store STORE --dry-run`
   where STORE is the seller's deal store (the home the studio setup names): the sales are
   read from what their deals sealed, which is the point. Use `--deals FILE` (a JSON file of
   sales) only as an offline fallback, and say so when you do. Say how many sales came
   through out of how many, name each that missed (the answer's `missed`) with the term it
   missed, and name each the terms could not decide (`could_not_decide`) with the term. A
   sale the terms could not decide is never counted as came through and never as missed. Tell the
   seller this was a rehearsal: nothing is switched on. The answer's `page` is a report
   page; tell the seller where it is so they can open it, and that it holds the same record
   the numbers come from. `terms verify PAGE` checks a page against its own record.
5. **When the seller changes a term**, edit the row (both places), bump the version, run
   lint, test and run again, then
   `terms compare RUN_BEFORE RUN_AFTER` with the two `run` folders the runs reported (or
   the two fingerprints from `terms history`).
   Say what the answer's `summary` lines say: per term, whether it improved, got worse,
   traded one for another, or was a tie, and how many sales came through before and after.
   If `same_rows` is false, say which term was added or removed.
6. **Switch them on only when the seller says to** ("use these terms on my sales"):
   `terms publish ~/studio/packs/sticker-sale/pack-source.yaml`. Before you run it, say in
   one sentence which terms will be checked on their next sales and ask for a yes. After
   it, give the first 12 characters of the pack digest it printed and call it "your terms' fingerprint".
   Published is not in force: the terms check sales only after the answer's `install`
   command has run (it pins the checker on the seller's deal profile). Run it, and only
   then say the terms are on. Do not say the fingerprint will appear on a receipt: that is not in place yet.
   If it fails, say the terms are published but not switched on, and why.

## Never

- Never run `publish` for a rehearsal, or before the seller said to use the terms.
- Never claim sales came through that the answer did not count, or round a count.
- Never edit a published pack: change the source, bump the version, publish again.
- Never write anywhere but `~/studio` (the one exception: the `install` command `publish` prints, after the seller's yes), and never read other files to "help" the rows.
