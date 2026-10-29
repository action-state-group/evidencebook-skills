# inference-deals fixtures

Records for `packs/inference-deals` (evidencebook-skills#71): the two ledgers a
Mesh payer node and a Mesh provider node sealed for one scripted two-node run.

- `payer.jsonl`, `provider.jsonl`: each node's `ledger/capsules.jsonl`, one Mesh
  capsule per line, signed by that node's key. Nothing in them is hand-written.
- `generate.patch`: the generator, a test module added to
  `crates/evidence-plugin/src/main.rs` of Mesh-LLM/capsules-plugin at
  `a0297e03a1f7589f3de4c96fd4c57c8d9eb7e6c9`. It opens two nodes with
  `CapsuleState::open` and feeds them host events through the channel
  handler's own paths: `observe_exchange_event` for each exchange, and for each
  payment lifecycle event `parse_and_check`, `emit_settlement_record` and the
  settlement legs, with the payer's terms legs delivered to the provider as
  `record-push/1` would. The plugin's own event checks refuse an impossible
  event, so a scripted event is one a host could send.
- `golden-*.json`: the Result `scripts/evaluators/inference_deals.py` writes for
  each book with `--date 2026-11-01` (tests/test_inference_deals.py).

What is real and what is scripted: the producer, the records, the keys, the
signatures and the legs are the plugin's. The host events are scripted, and no
Lightning network runs: no committed fixture from a paid two-node run over a
network exists yet (the plugin's two-node e2e is free traffic,
`two_node_e2e.rs:604-607`). The paid run over a real network is the live
step 10 finding in evidence-network/loop.

The run, per node (payer exchange ids `deal-*`, provider `p-deal-*`):

| deal | what happens | payer term 1 | provider terms 2 / 3 |
|---|---|---|---|
| `deal-settled` | invoices, both wallets settle, payer accounts the bill | met | met / provider states |
| `deal-short` | the payer's wallet reports less than one invoice | not_met | met / provider states |
| `deal-unreported` | invoices, no settlement, no accounted bill | not_evaluable (`outcome_not_reported`) | not_evaluable / provider states |
| `deal-terms` | terms accepted, no invoice | not_evaluable (`terms_only`) | not_evaluable / provider states |
| `free` | no lifecycle event (`settlement: null`) | not a deal | not a deal |

`golden-provider-countersigned.json` is the provider's book plus the payer's
terms legs its payee legs name. No Mesh node holds those in its book today:
the provider keeps the pushed terms leg in `received-capsules.jsonl`, outside
its ledger, and a payer never receives the payee leg. So a real Mesh book gives
only `self-attested` and `not_evaluable` claims; this golden covers the
`countersigned` rule.

To regenerate (the records' timestamps are the run's wall clock; move
`DATE` in tests/test_inference_deals.py and tests/fresh_env_deals.sh to the end
of the new run's week, then regenerate the goldens):

```bash
git -C capsules-plugin worktree add --detach /tmp/caps-gen a0297e03a1f7589f3de4c96fd4c57c8d9eb7e6c9
git -C /tmp/caps-gen apply "$PWD/tests/fixtures/inference-deals/generate.patch"
INFERENCE_DEALS_OUT=/tmp/fx cargo test --locked --manifest-path /tmp/caps-gen/crates/evidence-plugin/Cargo.toml \
  --bin capsules inference_deals_fixtures -- --ignored --nocapture
```
