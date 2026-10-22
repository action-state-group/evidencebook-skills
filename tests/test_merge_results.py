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
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

from merge_results import main  # noqa: E402


# A claim cites at least one record (agent-action-capsule#353).
CITED = {"digest_alg": "SHA-256", "digest": "cd" * 32}


def doc(claim_id, verdict, contract_ref="spec@1"):
    return {
        "result_version": "evidence-result-v0",
        "generated_at": "2026-09-23T23:59:59Z",
        "claims": [{
            "id": claim_id, "contract_ref": contract_ref, "requirement_ref": "x", "tier": "recomputed",
            "grade": "self-attested", "sufficiency": "SATISFIED", "verdict": verdict, "evidence": [CITED], "proofs": [],
            "presentation": {"kind": "disclosure", "status": "SATISFIED", "evidence": [CITED]},
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

    def _merge_with_spec(self, spec_name, spec_text):
        spec = self.work / spec_name
        spec.write_text(spec_text)
        d1 = self._write("d1.json", doc("d1::x", "met"))
        d2 = self._write("d2.json", doc("d2::x", "met"))
        out = self.work / "merged.json"
        code, _ = self._run(["--spec", str(spec), "--period", "2026-10-01 to 2026-10-02",
                              "--generated-at", "2026-09-25T00:00:00Z", "--out", str(out), str(d1), str(d2)])
        self.assertEqual(code, 0)
        return json.loads(out.read_text())["view"]["title"]

    def test_a_compiled_pack_titles_the_range_with_its_own_title(self):
        title = self._merge_with_spec("compiled.json", json.dumps(
            {"contract": "airline-support-outcomes/v1", "title": "Airline support outcomes"}))
        self.assertEqual(title, "Airline support outcomes \u2014 2026-10-01 to 2026-10-02")

    def test_a_report_spec_titles_the_range_with_its_title(self):
        title = self._merge_with_spec("spec.yaml", "spec_version: report-spec/v1\nid: tau2-x\ntitle: Tau2 report\n")
        self.assertEqual(title, "Tau2 report \u2014 2026-10-01 to 2026-10-02")

    def test_title_and_spec_are_mutually_exclusive_and_spec_needs_a_period(self):
        d1 = self._write("d1.json", doc("d1::x", "met"))
        spec = self._write("compiled.json", {"contract": "x/v1"})
        base = ["--generated-at", "2026-09-25T00:00:00Z", "--out", str(self.work / "m.json"), str(d1)]
        for extra in ([], ["--title", "t", "--spec", str(spec), "--period", "p"], ["--spec", str(spec)]):
            with self.subTest(extra=extra), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    main(extra + base)
                self.assertEqual(cm.exception.code, 2)

    def test_the_title_survives_a_c_locale(self):
        # report.sh passes only ASCII; the em dash is composed inside Python,
        # so the sealed title doesn't depend on the caller's locale.
        spec = self._write("compiled.json", {"contract": "x/v1", "title": "Pack"})
        d1 = self._write("d1.json", doc("d1::x", "met"))
        d2 = self._write("d2.json", doc("d2::x", "met"))
        out = self.work / "merged.json"
        script = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "merge_results.py"
        env = dict(os.environ, LC_ALL="C", LANG="C", PYTHONUTF8="0")
        subprocess.run([sys.executable, str(script), "--spec", str(spec), "--period", "2026-10-01 to 2026-10-02",
                        "--generated-at", "2026-09-25T00:00:00Z", "--out", str(out), str(d1), str(d2)],
                       check=True, capture_output=True, env=env)
        self.assertEqual(json.loads(out.read_text())["view"]["title"], "Pack \u2014 2026-10-01 to 2026-10-02")

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
