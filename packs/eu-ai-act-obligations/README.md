# eu-ai-act-obligations

An **example** pack (see [#192](https://github.com/action-state-group/evidencebook-skills/issues/192)), not a supported one. It reads tau2 airline support conversations against ten obligations of Regulation (EU) 2024/1689. `pack-source.yaml` is the source; `demo/eu-ai-act-obligations/` and `contracts/eu-ai-act-obligations/` are compiled from it.

## Reading the report

A report from this pack is a count, per test, of sessions that met it, did not meet it or could not be evaluated. It is not a finding that the AI system complies, or does not comply, with the EU AI Act, and it gives no overall compliance figure. The `regulation` field is a citation of the text each test is read against.

`art50.disclosure_before_first_turn` is **not evaluable on tau2 data**: the first assistant message is the benchmark runner's fixed greeting, not agent output, so it is never a finding.

## Known gaps

- **tau2 and Jev.** The pack is bound to tau2 airline data and judged by Jev (`scripts/judges/jev_judge.py`); its allowed-action checks are airline policy.
- **No labelled cases.** Ten of its rows are model judgments with no labelled cases to check them against.
- **Art 50 turn-one row.** Always not evaluable on this dataset, as above.
