# coffee-beans-sale fixture

`trades.json` is four coffee beans sales in the normalized shape
`scripts/evaluators/transaction.py` reads: `beans-01` and `beans-02` meet all
three terms (`beans-02` on the 3-day boundary), `beans-03` is delivered after
4 days, and `beans-04` was accepted at 2000, not the 2400 offered. The tests
run `packs/coffee-beans-sale` over it with the same evaluator the sticker-sale
pack uses.
