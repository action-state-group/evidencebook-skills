# everyday-rules

An example pack. Whether it becomes a supported one is open under evidencebook-skills#192, where Steven picks the supported list. It judges the semantic rows of an Everyday Rules set; `pack-source.yaml` is the source and `compiled/` is what `scripts/pack_compile.py` writes from it.

## Labelled cases

`fixtures/cases.json` holds hand-written cases for rows 11 (home address to an individual) and 12 (personal phone or email to a new party): one in scope and met, one in scope and not met, one out of scope. A test checks their shape and that each row has all three. No model is run against them yet.

**Known gap:** the other eleven rows (2, 8, 9, 10, 14, 21, 22, 24, 25, 26, 27) have no labelled cases, so no case a person can check exists for them.
