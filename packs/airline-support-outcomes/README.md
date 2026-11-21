# airline-support-outcomes

An **example** pack (see [#192](https://github.com/action-state-group/evidencebook-skills/issues/192)), not a supported one. It judges tau2 airline support conversations on nine criteria under three checks. `pack-source.yaml` is the source; `demo/airline-support-outcomes/` and `contracts/airline-support-outcomes/` are compiled from it.

## Reading the rows

- **Done in full.** A correct refusal under airline policy counts as done. That is the shipped default (`done_in_full_refusal_aware: true`); with the flag off the judge gets the plainer wording and the label no longer describes it.
- **Prices from the system.** Every fare and fee quoted appears in a tool result, or is a total or difference worked out from figures that do. The judge decides this row; no deterministic check backs it today.

## Known gaps

- **Extra cancellation.** An unrequested write the agent bundles into the narration of a confirmed one still reads as confirmed in the deterministic confirm-before-write check (`scripts/recompute.py:469`; `tests/test_recompute.py:538-559` asserts `met`). That check is not run for this pack, whose `confirmed_before_acting` and `no_unrequested_actions` rows are judged; the same wrong `met` is the open gap in the EU pack's recomputed row. Not fixed here.
- **No per-row fixtures.** The judged rows have no labelled cases to check a judge against.
- **tau2 and Jev.** The pack reads tau2 airline data and is judged by Jev (`scripts/judges/jev_judge.py`); it does not run on other data or another judge without work.
- **Stale copy.** `demo/tau2-outcomes/` is an older compiled copy and is not regenerated from this source.
