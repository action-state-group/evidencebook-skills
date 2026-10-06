"""main() orchestration test for scripts/merge_results.py -- the CLI wrapper
around scripts/result_v0.merge_result_v0_documents (already unit-tested in
tests/test_result_v0.py's own MergeResultV0Documents), exercised here through
its actual command-line entry point (argument parsing, file reading, exit
code, and the error path), same split tests/test_pack_edit.py's
MainOrchestration makes for pack_edit.py.
"""
import contextlib
import io
import json
import pathlib
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

from merge_results import main  # noqa: E402


def doc(claim_id, verdict, contract_ref="spec@1"):
    return {
        "result_version": "evidence-result-v0",
        "generated_at": "2026-09-23T23:59:59Z",
        "claims": [{
            "id": claim_id, "contract_ref": contract_ref, "requirement_ref": "x", "tier": "recomputed",
            "grade": "self-attested", "sufficiency": "SATISFIED", "verdict": verdict, "evidence": [], "proofs": [],
            "presentation": {"kind": "disclosure", "status": "SATISFIED", "evidence": []},
        }],
        "aggregate": {"coverage": {"evaluated_population": 1, "excluded_not_applicable": 0, "unknown_count": 0},
                      "buckets": {"met": [claim_id] if verdict == "met" else [],
                                  "not_met": [claim_id] if verdict == "not_met" else [],
                                  "not_evaluable": []}},
        "view": {"spec_version": "presentation/v1", "title": f"day {claim_id}"},
    }


class MainOrchestration(unittest.TestCase):
    def setUp(self):
        self.work = pathlib.Path(tempfile.mkdtemp(prefix="test-merge-results-"))
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def _write(self, name, data):
        path = self.work / name
        path.write_text(json.dumps(data))
        return path

    def _run(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(argv)
        return code, out.getvalue()

    def test_merges_two_inputs_into_one_output_file(self):
        d1 = self._write("d1.json", doc("d1::x", "met"))
        d2 = self._write("d2.json", doc("d2::x", "not_met"))
        out = self.work / "merged.json"
        code, printed = self._run(["--title", "two days", "--generated-at", "2026-09-25T00:00:00Z",
                                    "--out", str(out), str(d1), str(d2)])
        self.assertEqual(code, 0)
        merged = json.loads(out.read_text())
        self.assertEqual(len(merged["claims"]), 2)
        self.assertEqual(merged["view"]["title"], "two days")
        summary = json.loads(printed)
        self.assertEqual(summary["claims"], 2)
        self.assertEqual(summary["inputs"], 2)

    def test_a_single_input_still_produces_a_valid_merged_document(self):
        d1 = self._write("d1.json", doc("d1::x", "met"))
        out = self.work / "merged.json"
        code, _ = self._run(["--title", "one day", "--generated-at", "2026-09-25T00:00:00Z",
                              "--out", str(out), str(d1)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.read_text())["view"]["title"], "one day")

    def test_mismatched_contract_refs_exit_nonzero_and_write_no_output(self):
        d1 = self._write("d1.json", doc("d1::x", "met", contract_ref="a@1"))
        d2 = self._write("d2.json", doc("d2::x", "met", contract_ref="b@1"))
        out = self.work / "merged.json"
        code, printed = self._run(["--title", "mixed", "--generated-at", "2026-09-25T00:00:00Z",
                                    "--out", str(out), str(d1), str(d2)])
        self.assertEqual(code, 2)
        self.assertIn("contract_ref", json.loads(printed)["error"])
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
