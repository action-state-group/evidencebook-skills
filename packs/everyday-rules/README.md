# everyday-rules

An example pack. Whether it becomes a supported one is open under evidencebook-skills#192, where Steven picks the supported list. It judges the semantic rows of an Everyday Rules set; `pack-source.yaml` is the source and `compiled/` is what `scripts/pack_compile.py` writes from it.

## Labelled cases

`fixtures/cases.json` holds hand-written cases for all 13 rows (2, 8, 9, 10, 11, 12, 14, 21, 22, 24, 25, 26, 27): one in scope and met, one in scope and not met, one out of scope. Each out-of-scope case is built from the row's `out_of_scope_means`. For the rule_half rows (2, 11, 12, 27) the cases label only the semantic residual the row's `scope_note` names, never the deterministic half. A test checks their shape and that each row has all three. No model is run against them yet.
