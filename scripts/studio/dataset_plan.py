"""dataset_plan -- the dataset plan and dataset document a `terms run` Result cites.

Result v0 section 7.3 lets a Result name, by digest, the dataset plan it counted over
(`plan_ref`, Plan IR v0 section 5.1) and the dataset that plan selected (`dataset_ref`,
section 6.2). `terms run` has no book, so the sales are the population of a book this module
names: each sale is one record header

    {book_id, seq, record_type: "sale", deal_id, sale_digest}

where `sale_digest` is SHA-256 of JCS(sale) (the digest x-pack.sales already states) and `seq`
is the sale's place in `deal_id` order, so the order of the file never matters. The plan is one
`traditional.population` node over those records; its header holds fixed values (not the run's
time, the pack or its contract), so the plan, and with it the dataset, depends on the sales
alone: two packs run over the same sales cite the same pair, and other sales give another.
Rows hold digests only, never a sale's values.
"""
import hashlib

import rfc8785

BOOK_ID = "terms-sales"
RECORD_TYPE = "sale"
CONTRACT_REF = "terms-sales@1"


def digest_of(value):
    """SHA-256 of UTF8(JCS(value)), the digest section 3.1 of the Result spec uses."""
    return hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def digest_ref(hex_digest):
    return {"digest_alg": "SHA-256", "digest": hex_digest}


def headers(deals):
    """The sales' record headers, in seq order."""
    ordered = sorted(deals, key=lambda d: d["deal_id"])
    return [{"book_id": BOOK_ID, "seq": seq, "record_type": RECORD_TYPE, "deal_id": d["deal_id"],
             "sale_digest": digest_of(d)} for seq, d in enumerate(ordered)]


def build(deals):
    """(plan, dataset) for these sales: both plain JSON documents."""
    records = headers(deals)
    plan = {
        "header": {"contract_ref": CONTRACT_REF, "ir_version": "evidence-plan-ir-v0",
                   "planner_id": "local:terms", "created_at": "1970-01-01T00:00:00Z",
                   "replay_seed": "terms-sales-v1"},
        "nodes": [{"id": "node-1", "family": "traditional", "operator": "traditional.population",
                   "inputs": [], "classification": "PUBLIC", "tier": "recomputed",
                   "contract_ref": CONTRACT_REF,
                   "params": {"book_id": BOOK_ID, "through_seq": len(records) - 1,
                              "record_types": [RECORD_TYPE]}}],
    }
    dataset = {
        "dataset_version": "evidence-dataset-v0",
        "plan_ref": digest_ref(digest_of(plan)),
        "rows": [{"seq": r["seq"], "record_type": r["record_type"], "digest_alg": "SHA-256",
                  "digest": digest_of(r)} for r in records],
    }
    return plan, dataset


def canonical_bytes(document):
    return rfc8785.dumps(document)
