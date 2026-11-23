"""demo/terms-pack-report (evidencebook-skills#217): the pack, its evaluator and its wording pack.

The runbook's commands (backfill, request by digest, derive, verify, build) run
against the released capsulectl and are checked by hand, not here. What is checked
here is what the runbook leaves to files in this repository: the evaluator turns
what a holder answered into a Result whose every claim cites the response record,
a row or path that is missing reads not_evaluable and never not_met, an unproven
answer is refused, the pack names only the fields it reads, the digest the runbook
has the auditor compute is the JCS digest the holder's book computes, and the
wording pack covers every row and is accepted by scripts/wording_pack.py.

    python3 -m unittest discover -s tests -p 'test_*.py'
"""
import hashlib
import importlib.util
import json
import pathlib
import shutil
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo" / "terms-pack-report"
sys.path.insert(0, str(ROOT / "scripts"))
import wording_pack  # noqa: E402

_spec = importlib.util.spec_from_file_location("terms_pack_evaluator", DEMO / "evaluator.py")
evaluator = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(evaluator)

PACK = json.loads((DEMO / "pack.json").read_text())
RESPONSE = "b" * 64
GENERATED_AT = "2026-11-23T00:00:00Z"
GAP = {"source": "goose.tool_calls", "from_cursor": "6", "to_cursor": "7", "reason": "expired"}


def import_row(gaps=(), anomalies=(), refused=(), rows_read="5"):
    return {"digest": "d" * 64, "leaf_index": 0, "fields": {
        "record_type": "backfill_import",
        "statement": {"anomalies": list(anomalies), "gaps": list(gaps), "refused": list(refused), "rows_read": rows_read}}}


def other_row():
    # A record the pack does not read still comes back with its record_type, and nothing else.
    return {"digest": "e" * 64, "leaf_index": 1, "fields": {"record_type": "index_root"}}


DERIVATION = evaluator.canonical_digest(PACK)


def answer(*records, proven=True):
    return {"response": RESPONSE, "derivation": DERIVATION, "anchor": "a" * 64, "proven": proven, "records": list(records)}


def verdicts(inputs):
    doc = evaluator.evaluate(PACK, inputs, GENERATED_AT)
    return {c["requirement_ref"]: c["verdict"] for c in doc["claims"]}, doc


class Verdicts(unittest.TestCase):
    def test_a_clean_log_meets_every_clause(self):
        v, _ = verdicts(answer(import_row(), other_row()))
        self.assertEqual(set(v.values()), {"met"})
        self.assertEqual(len(v), len(PACK["clauses"]))

    def test_a_declared_gap_is_not_met_and_only_that_clause(self):
        v, _ = verdicts(answer(import_row(), import_row(gaps=[GAP], rows_read="2")))
        self.assertEqual(v["record_keeping.no_declared_gaps"], "not_met")
        self.assertEqual(v["record_keeping.passes_present"], "met")
        self.assertEqual(v["record_keeping.no_late_or_refused_rows"], "met")

    def test_a_late_or_a_refused_row_is_not_met(self):
        for member in ("anomalies", "refused"):
            with self.subTest(member):
                v, _ = verdicts(answer(import_row(**{member: [{"id": "tc-1"}]})))
                self.assertEqual(v["record_keeping.no_late_or_refused_rows"], "not_met")
                self.assertEqual(v["record_keeping.no_declared_gaps"], "met")

    def test_no_import_record_reads_not_evaluable_never_not_met(self):
        v, _ = verdicts(answer(other_row()))
        self.assertEqual(set(v.values()), {"not_evaluable"})
        v, _ = verdicts(answer())
        self.assertEqual(set(v.values()), {"not_evaluable"})

    def test_a_missing_or_malformed_path_reads_not_evaluable(self):
        row = import_row()
        del row["fields"]["statement"]["gaps"]
        v, _ = verdicts(answer(row))
        self.assertEqual(v["record_keeping.no_declared_gaps"], "not_evaluable")
        self.assertEqual(v["record_keeping.no_late_or_refused_rows"], "met")
        row = import_row()
        row["fields"]["statement"]["anomalies"] = "none"
        v, _ = verdicts(answer(row))
        self.assertEqual(v["record_keeping.no_late_or_refused_rows"], "not_evaluable")
        row = import_row()
        del row["fields"]["statement"]
        v, _ = verdicts(answer(row))
        self.assertEqual(v["record_keeping.no_declared_gaps"], "not_evaluable")

    def test_not_met_outranks_not_evaluable(self):
        broken = import_row()
        del broken["fields"]["statement"]["anomalies"]
        v, _ = verdicts(answer(import_row(anomalies=[{"id": "tc-1"}]), broken))
        self.assertEqual(v["record_keeping.no_late_or_refused_rows"], "not_met")
        v, _ = verdicts(answer(broken, import_row(anomalies=[{"id": "tc-1"}])))
        self.assertEqual(v["record_keeping.no_late_or_refused_rows"], "not_met")

    def test_a_row_with_no_record_type_cannot_be_ruled_out(self):
        # Dropping it would let a row hiding a gap read as met.
        unnamed = import_row(gaps=[GAP])
        del unnamed["fields"]["record_type"]
        v, _ = verdicts(answer(import_row(), unnamed))
        self.assertEqual(v["record_keeping.no_declared_gaps"], "not_evaluable")
        self.assertEqual(v["record_keeping.passes_present"], "met")
        unnamed["fields"]["record_type"] = 7
        v, _ = verdicts(answer(import_row(), unnamed))
        self.assertEqual(v["record_keeping.no_declared_gaps"], "not_evaluable")

    def test_a_row_without_fields_is_unclassified_not_a_crash(self):
        for bad in ({"digest": "x", "leaf_index": 2}, {"digest": "x", "leaf_index": 2, "fields": "nope"}):
            v, _ = verdicts(answer(import_row(), bad))
            self.assertEqual(v["record_keeping.no_declared_gaps"], "not_evaluable")

    def test_one_unreadable_pass_beats_a_met_one(self):
        broken = import_row()
        del broken["fields"]["statement"]["gaps"]
        v, _ = verdicts(answer(import_row(), broken))
        self.assertEqual(v["record_keeping.no_declared_gaps"], "not_evaluable")

    def test_an_unknown_rule_kind_is_refused(self):
        with self.assertRaisesRegex(ValueError, "unknown rule kind"):
            evaluator.decide({"kind": "nope", "record_type": "backfill_import"}, [import_row()])


class TheResult(unittest.TestCase):
    def test_every_claim_cites_exactly_the_response_record(self):
        _, doc = verdicts(answer(import_row(), import_row(gaps=[GAP])))
        for claim in doc["claims"]:
            self.assertEqual(claim["evidence"], [{"digest_alg": "SHA-256", "digest": RESPONSE}])
            self.assertEqual(claim["grade"], "self-attested")
            self.assertEqual(claim["contract_ref"], PACK["contract_ref"])

    def test_the_buckets_partition_the_claims(self):
        _, doc = verdicts(answer(import_row(gaps=[GAP])))
        b = doc["aggregate"]["buckets"]
        self.assertEqual(sorted(b["met"] + b["not_met"] + b["not_evaluable"]), sorted(c["id"] for c in doc["claims"]))
        self.assertEqual(doc["aggregate"]["coverage"]["evaluated_population"], len(PACK["clauses"]))

    def test_the_view_title_is_the_packs(self):
        _, doc = verdicts(answer(import_row()))
        self.assertEqual(doc["view"]["title"], PACK["title"])

    def test_a_pack_other_than_the_one_answered_under_is_refused(self):
        edited = json.loads(json.dumps(PACK))
        edited["clauses"][1]["rule"]["paths"] = ["statement.refused"]
        with self.assertRaisesRegex(ValueError, "not the one the holder answered under"):
            evaluator.evaluate(edited, answer(import_row()), GENERATED_AT)
        with self.assertRaisesRegex(ValueError, "not the one the holder answered under"):
            evaluator.evaluate(PACK, dict(answer(import_row()), derivation="0" * 64), GENERATED_AT)

    def test_a_pack_it_cannot_canonicalize_is_refused(self):
        for bad in ({"n": 1.5}, {"n": "caf\u00e9"}, {"caf\u00e9": 1}, {"a": [{"b": 0.1}]}):
            with self.subTest(bad):
                with self.assertRaises(ValueError):
                    evaluator.canonical_digest(bad)

    def test_an_unproven_answer_is_refused(self):
        with self.assertRaisesRegex(ValueError, "no proofs"):
            evaluator.evaluate(PACK, answer(import_row(), proven=False), GENERATED_AT)


class ThePack(unittest.TestCase):
    def test_the_digest_the_runbook_names_is_the_jcs_digest(self):
        # The runbook computes it as `jq -cS . pack.json | tr -d '\n' | shasum -a 256`, which is JCS for a
        # document that is ASCII and holds no number.
        text = (DEMO / "pack.json").read_text()
        self.assertTrue(text.isascii())
        self.assertNotRegex(json.dumps(PACK), r"[0-9]\s*[,}\]]")  # no bare number: every digit run sits in a string
        canonical = json.dumps(PACK, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        try:
            import rfc8785
        except ImportError:
            self.skipTest("rfc8785 is not installed")
        self.assertEqual(digest, hashlib.sha256(rfc8785.dumps(PACK)).hexdigest())

    def test_the_readme_expects_the_packs_digest(self):
        self.assertIn(DERIVATION, (DEMO / "README.md").read_text())

    @unittest.skipUnless(shutil.which("jq") and shutil.which("shasum"), "needs jq and shasum")
    def test_the_runbooks_hashing_pipeline_gives_the_evaluators_digest(self):
        out = subprocess.run("jq -cS . pack.json | tr -d '\\n' | shasum -a 256 | cut -d' ' -f1", shell=True, cwd=DEMO,
                             capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(out, DERIVATION)

    def test_the_pack_declares_the_fields_its_rules_read_and_nothing_else(self):
        read = {"record_type"}
        for clause in PACK["clauses"]:
            read.update(clause["rule"].get("paths", []))
            read.add("record_type")
        self.assertEqual(set(PACK["fields"]), read)
        self.assertEqual(PACK["fields"], sorted(PACK["fields"]))

    def test_clause_ids_are_unique_and_share_one_group(self):
        ids = [c["id"] for c in PACK["clauses"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual({i.split(".", 1)[0] for i in ids}, {"record_keeping"})
        self.assertEqual(PACK["contract_ref"], f"{PACK['pack_id']}@{PACK['pack_version']}")

    def test_the_fixture_rows_are_the_ones_the_runbook_imports(self):
        for name, rows in (("pass1.jsonl", 5), ("pass2.jsonl", 3)):
            lines = [json.loads(line) for line in (DEMO / "fixtures" / name).read_text().splitlines()]
            self.assertEqual(len(lines), rows)
            for line in lines:
                self.assertIn(line["kind"], ("row", "horizon"))


class TheWordingPack(unittest.TestCase):
    path = ROOT / "wording" / "goose-record-keeping-en.json"
    digest = ROOT / "wording" / "goose-record-keeping-en.sha256"
    entries = json.loads(path.read_text())["entries"]

    def test_its_digest_is_the_one_committed_beside_it(self):
        self.assertEqual(self.digest.read_text().strip(), hashlib.sha256(self.path.read_bytes()).hexdigest())
        wording_pack.check(self.path, self.digest.read_text().strip())

    def test_it_words_every_row_and_the_group_and_no_other(self):
        ids = [c["id"] for c in PACK["clauses"]]
        for cid in ids:
            for part in ("label", "detail", "not_evaluable"):
                self.assertIn(f"row.{cid}.{part}", self.entries)
        self.assertIn("group.record_keeping.title", self.entries)
        rows = {k[len("row."):].rsplit(".", 1)[0] for k in self.entries if k.startswith("row.")}
        self.assertEqual(rows, set(ids))

    def test_its_labels_and_details_are_the_packs_own_words(self):
        for clause in PACK["clauses"]:
            self.assertEqual(self.entries[f"row.{clause['id']}.label"], clause["label"])
            self.assertEqual(self.entries[f"row.{clause['id']}.detail"], clause["claim"])

    def test_it_keeps_clear_of_what_the_viewer_locks(self):
        for prefix in ("grade.", "status.", "sufficiency.", "requirement_tier.", "core.", "front.", "card.mark."):
            self.assertFalse([k for k in self.entries if k.startswith(prefix)], prefix)


if __name__ == "__main__":
    unittest.main()
