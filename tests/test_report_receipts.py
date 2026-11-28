"""report.sh --receipts FILE (evidencebook-skills#215; capsules-plugin#336, evidencebook#764).

report.sh forwards the receipts file the plugin's settlement-report.sh writes to
`capsulectl book report build --receipts FILE`, unchanged, and refuses it before
anything is written to the book when the capsulectl in use does not list the
flag. Without --receipts the build call is the one it was, and no help probe is
made. On the evaluator path the evaluator gets the same file, to name each
deal's receipt as its claims' subject_bundle (capsule-viewer#353). The builder,
not report.sh, checks the file; what the page then shows is the builder's and
capsule-viewer's to test.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import test_report_wording as tw  # noqa: E402

ROOT = tw.ROOT
BASH = tw.BASH

# The wording stub plus `book report build --help`, which lists --receipts only
# when STUB_HAS_RECEIPTS is set (a capsulectl that predates the flag lists none).
STUB_CAPSULECTL = tw.STUB_CAPSULECTL.replace(
    'if argv[:3] == ["book", "result", "build"]:',
    'if argv[:4] == ["book", "report", "build", "--help"]:\n'
    '    print("usage: capsulectl book report build --card C --out F" + (" [--receipts FILE]" if os.environ.get("STUB_HAS_RECEIPTS") else ""))\n'
    'elif argv[:3] == ["book", "result", "build"]:', 1)

RECEIPTS = [{"exchange_capsule_id": "ab" * 32, "receipt": "{\"bundle\": \"as the node served it\"}"},
            {"exchange_capsule_id": "cd" * 32, "held": True}]


class ReportShReceipts(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="test-report-receipts-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        shutil.copytree(ROOT / "scripts", self.tmp / "scripts")
        tw._exe(self.tmp / "scripts" / "evaluators" / "stub_eval.py", tw.STUB_EVALUATOR)
        self.ctl = self.tmp / "capsulectl"
        tw._exe(self.ctl, STUB_CAPSULECTL)
        self.capture = self.tmp / "capture"
        self.capture.mkdir()
        self.spec = self.tmp / "eval.json"
        self.spec.write_text(json.dumps({"contract": "stub-pack", "clauses": [{"id": "c1"}], "evaluator": "stub_eval",
                                         "presentation": {"card": "settlement"}}))
        self.receipts = self.tmp / "receipts.json"
        self.receipts.write_text(json.dumps(RECEIPTS, sort_keys=True))

    def run_report(self, *args, has_flag=True, bash=BASH, spec=None):
        env = dict(os.environ, STUB_CAPTURE=str(self.capture),
                   PATH=f"{pathlib.Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}")
        env.pop("STUB_HAS_RECEIPTS", None)
        if has_flag:
            env["STUB_HAS_RECEIPTS"] = "1"
        cmd = [bash, str(self.tmp / "scripts" / "report.sh"), "--spec", str(spec or self.spec), "--profile", "p",
               "--date", "2026-10-01", "--out", str(self.tmp / "report.html"), "--capsulectl", str(self.ctl),
               "--work", str(self.tmp / "work"), *args]
        return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120)

    def calls(self):
        log = self.capture / "calls.log"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def build_argv(self):
        builds = [c for c in self.calls() if c[:3] == ["book", "report", "build"] and "--help" not in c]
        self.assertEqual(len(builds), 1)
        return builds[0]

    def test_the_file_reaches_the_build_unchanged(self):
        before = self.receipts.read_bytes()
        proc = self.run_report("--receipts", str(self.receipts))
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        argv = self.build_argv()
        self.assertEqual(argv[argv.index("--receipts") + 1], str(self.receipts))
        self.assertEqual(argv.count("--receipts"), 1)
        self.assertEqual(self.receipts.read_bytes(), before)

    def test_the_evaluator_gets_the_same_file_before_the_result_is_sealed(self):
        # capsule-viewer#353: the evaluator names each deal's receipt as its
        # claims' subject_bundle, so it reads the very file the page builder gets.
        stub = tw.STUB_EVALUATOR.replace(
            "argv = sys.argv[1:]\n",
            "argv = sys.argv[1:]\nimport os\n"
            "(pathlib.Path(os.environ['STUB_CAPTURE']) / 'eval-argv.json').write_text(json.dumps(argv))\n", 1)
        tw._exe(self.tmp / "scripts" / "evaluators" / "stub_eval.py", stub)
        proc = self.run_report("--receipts", str(self.receipts))
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        argv = json.loads((self.capture / "eval-argv.json").read_text())
        self.assertEqual(argv[argv.index("--receipts") + 1], str(self.receipts))
        result_builds = [i for i, c in enumerate(self.calls()) if c[:3] == ["book", "result", "build"]]
        self.assertTrue(result_builds, "the Result is sealed after the evaluator ran")
        shutil.rmtree(self.capture)
        self.capture.mkdir()
        self.assertEqual(self.run_report(has_flag=False).returncode, 0)
        self.assertNotIn("--receipts", json.loads((self.capture / "eval-argv.json").read_text()))

    def test_seal_wording_and_receipts_reach_the_same_build(self):
        proc = self.run_report("--seal", "--receipts", str(self.receipts), "--wording", str(tw.PACK),
                               "--wording-digest", tw._sha(tw.PACK))
        argv = self.build_argv()  # the stub has no `report check`, so the run stops after the one build
        self.assertIn("--seal", argv)
        self.assertEqual(argv[argv.index("--receipts") + 1], str(self.receipts))
        self.assertEqual(argv[argv.index("--wording-digest") + 1], tw._sha(tw.PACK))

    def test_without_the_option_the_build_call_is_unchanged_and_no_help_probe_is_made(self):
        proc = self.run_report(has_flag=False)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertNotIn("--receipts", self.build_argv())
        self.assertFalse([c for c in self.calls() if "--help" in c])

    def test_a_capsulectl_without_the_flag_is_refused_before_anything_is_written_to_the_book(self):
        out = self.tmp / "report.html"
        out.write_text("<html>an earlier page</html>")
        proc = self.run_report("--seal", "--receipts", str(self.receipts), has_flag=False)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("takes --receipts", proc.stderr)
        self.assertEqual([c for c in self.calls() if "--help" not in c], [], "only the help probe, no book write")
        self.assertFalse(out.exists(), "a failed --seal run leaves no page at --out")

    def test_a_missing_receipts_file_stops_the_run_before_any_capsulectl_call(self):
        proc = self.run_report("--receipts", str(self.tmp / "nope.json"))
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("no such receipts file", proc.stderr)
        self.assertEqual(self.calls(), [])

    def test_an_empty_receipts_path_is_refused_not_dropped(self):
        proc = self.run_report("--receipts", "")
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("no such receipts file", proc.stderr)
        self.assertEqual(self.calls(), [])

    def test_the_judged_path_passes_it_through_too(self):
        spec = self.tmp / "judged.json"
        spec.write_text(json.dumps({"contract": "stub-pack", "clauses": [{"id": "c1"}],
                                    "judge": {"model_id": "jev-1.13.0"}}))
        tw._exe(self.tmp / "scripts" / "run_daily.py", "#!/usr/bin/env python3\n")
        tw._exe(self.tmp / "scripts" / "rollup_day.py", tw.STUB_ROLLUP_DAY)
        proc = self.run_report("--receipts", str(self.receipts), spec=spec)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        argv = self.build_argv()
        self.assertEqual(argv[argv.index("--receipts") + 1], str(self.receipts))

    @unittest.skipUnless(os.path.exists("/bin/bash"), "no system bash")
    def test_both_paths_run_under_the_system_bash(self):
        # macOS's /bin/bash is 3.2: an empty array under `set -u` must not break the call.
        for args, carried in (([], False), (["--receipts", str(self.receipts)], True)):
            shutil.rmtree(self.capture)
            self.capture.mkdir()
            proc = self.run_report(*args, bash="/bin/bash")
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            self.assertEqual("--receipts" in self.build_argv(), carried)


if __name__ == "__main__":
    unittest.main()
