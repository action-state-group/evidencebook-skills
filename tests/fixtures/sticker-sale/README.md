# sticker-sale fixture

`trades.json` is ten sticker sales in the normalized shape
`scripts/evaluators/transaction.py` reads (its docstring lists the fields): nine
paid, delivered the same day, at the price offered, and `sticker-07`, whose
accepted price (450) is not the price offered (500). The field names are the
replay fixture's (evidencebook-deal#136). The tests use this file, not the deal
store.
