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
(`~/studio`); the commands write only there.

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
   `terms compare RUN_BEFORE RUN_AFTER` with the two `run` folders the runs reported.
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
