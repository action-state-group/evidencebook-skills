"""scripts/specs/mesh-llm-settlement-draft.yaml is a DRAFT: mesh-llm has no
shipped sealed-record export format yet, so there is no live book to run it
against (see the spec file's own header). This is as far as "the spec format
fits mesh-llm's use case" can be demonstrated today -- the YAML loads as a
valid report-spec/v1 document, and the engine's real evaluate_group/
build_documents functions (no mocking, no reimplementation) produce a sensible
Result v0 over rows SHAPED like the draft's own placeholder record (hand-built
here, standing in for select_record_rows' own output -- not read from a book).
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

from report_spec import apply_field_projections, build_documents, load_spec  # noqa: E402

SPEC_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "specs" / "mesh-llm-settlement-draft.yaml"


def exchange_row(capsule_id, day, peer_id, direction, amount_cents, tokens_served=None,
                  counterparty_seal_digest="ab" * 32):
    """One row shaped exactly as select_record_rows (kind: record) would
    produce it for this draft's own `fields:` mapping -- built by hand since
    there is no real mesh-llm book to read it from yet."""
    body = {"peer": {"id": peer_id}, "direction": direction, "amount_cents": amount_cents,
            "tokens_served": tokens_served, "counterparty_seal_digest": counterparty_seal_digest}
    row = {"day": day, "__capsule_id": capsule_id}
    apply_field_projections(row, body, SPEC["sources"][0]["fields"])
    return row


SPEC = load_spec(SPEC_PATH)


class MeshLlmDraftSpecLoads(unittest.TestCase):
    def test_spec_version_and_shape(self):
        self.assertEqual(SPEC["spec_version"], "report-spec/v1")
        self.assertEqual(SPEC["group_by"], "peer_day")
        self.assertEqual(SPEC["sources"][0]["kind"], "record")
        self.assertEqual(SPEC["sources"][0]["match"], {"record_type": "mesh-settlement-exchange/v1"})

    def test_title_is_labelled_draft(self):
        self.assertIn("DRAFT", SPEC["title"])


class MeshLlmDraftSpecOverSyntheticRows(unittest.TestCase):
    def test_peer_day_grouping_and_served_earned_paid_metrics(self):
        rows = {
            "exchanges": [
                exchange_row("cap1", "2026-09-23", "peer-a", "served", 500, tokens_served=1000),
                exchange_row("cap2", "2026-09-23", "peer-a", "consumed", 200),
                exchange_row("cap3", "2026-09-23", "peer-b", "served", 900, tokens_served=2000),
            ],
        }
        docs, group_results = build_documents(SPEC, rows, "2026-09-24T00:00:00Z")
        self.assertEqual(set(docs), {"peer-a/2026-09-23", "peer-b/2026-09-23"})
        by_group = {g["peer_day"]: g["metrics"] for g in group_results}
        self.assertEqual(by_group["peer-a/2026-09-23"],
                          {"exchange_count": 2, "tokens_served_total": 1000, "earned_cents": 500, "paid_cents": 200})
        self.assertEqual(by_group["peer-b/2026-09-23"],
                          {"exchange_count": 1, "tokens_served_total": 2000, "earned_cents": 900, "paid_cents": 0})

    def test_bilateral_seal_claim_met_when_every_exchange_names_a_counterparty_digest(self):
        rows = {"exchanges": [exchange_row("cap1", "2026-09-23", "peer-a", "served", 500)]}
        docs, _ = build_documents(SPEC, rows, "2026-09-24T00:00:00Z")
        claim = docs["peer-a/2026-09-23"]["claims"][0]
        self.assertEqual(claim["verdict"], "met")
        self.assertEqual(claim["tier"], "recomputed")
        self.assertEqual(claim["requirement_ref"], "bilateral_seal_present")

    def test_bilateral_seal_claim_not_met_when_one_exchange_has_no_counterparty_link(self):
        rows = {"exchanges": [
            exchange_row("cap1", "2026-09-23", "peer-a", "served", 500),
            exchange_row("cap2", "2026-09-23", "peer-a", "consumed", 100, counterparty_seal_digest=None),
        ]}
        docs, _ = build_documents(SPEC, rows, "2026-09-24T00:00:00Z")
        self.assertEqual(docs["peer-a/2026-09-23"]["claims"][0]["verdict"], "not_met")

    def test_different_peers_or_days_never_share_a_group(self):
        rows = {"exchanges": [
            exchange_row("cap1", "2026-09-23", "peer-a", "served", 500),
            exchange_row("cap2", "2026-09-24", "peer-a", "served", 100),
        ]}
        docs, _ = build_documents(SPEC, rows, "2026-09-25T00:00:00Z")
        self.assertEqual(set(docs), {"peer-a/2026-09-23", "peer-a/2026-09-24"})


if __name__ == "__main__":
    unittest.main()
