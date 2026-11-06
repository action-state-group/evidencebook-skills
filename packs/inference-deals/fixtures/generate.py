#!/usr/bin/env python3
"""Regenerate fixtures/two-case.json from tests/fixtures/inference-deals/{payer,provider}.jsonl,
the two ledgers a Mesh node's own producer sealed for one scripted run.

    python3 packs/inference-deals/fixtures/generate.py > packs/inference-deals/fixtures/two-case.json

The `met` cases carry one deal's sealed records unchanged. The paid_as_agreed `not_met` case is the payer's own sealed deal whose settlement was short.
The other two are a copy of a sealed record set with one value edited: for served_as_agreed one settlement observation's amount_msat plus 1; for
served_named_model the resolved_model_id replaced. The edited records keep their original
capsule_id and signature, so they are no longer sealed records: the evaluator
(scripts/evaluators/inference_deals.py) never verifies a seal, and these cases test its
reading of the fields, not the seal.
"""
import copy
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "scripts" / "evaluators"), str(ROOT / "tests")]
import inference_deals as d  # noqa: E402
import test_inference_deals as T  # noqa: E402


def main():
    pay, prov = T.load("payer"), T.load("provider")
    met = T.deal_records(prov, "p-deal-settled")
    short = copy.deepcopy(met)
    for c in short:
        o = T.observation(c)
        if o and o.get("phase") in d.SETTLEMENT_PHASES and "amount_msat" in o:
            o["amount_msat"] += 1
            break
    other = copy.deepcopy(met)
    for c in other:
        a = d._attestation(c)
        if "invocation" in a:
            a["invocation"]["resolved_model_id"] = "another-model"

    def case(row, name, records):
        return {"row": "come_through." + row, "case": name, "input": {"records": records, "date": "2026-11-01"}}

    cases = [case("paid_as_agreed", "met", T.deal_records(pay, "deal-settled")),
             case("paid_as_agreed", "not_met", T.deal_records(pay, "deal-short")),
             case("served_as_agreed", "met", met), case("served_as_agreed", "not_met", short),
             case("served_named_model", "met", met), case("served_named_model", "not_met", other)]
    print(json.dumps({"pack": "inference-deals", "cases": cases}, indent=1))


if __name__ == "__main__":
    main()
