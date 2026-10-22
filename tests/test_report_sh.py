"""scripts/report.sh's own wiring, run for real against stand-ins.

A temp copy of the repo's scripts/ has run_daily.py and rollup_day.py replaced
by stubs (rollup_day writes one Result v0 per day in STUB_DAYS, the way the
real one writes every day in the book under the pin), and --capsulectl is a
stub that records the Result handed to `book result build`. That isolates
what report.sh itself decides: which days it reports, which files it reads
from --work, the judge backend it sets, and the title it seals.
"""
import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASH = shutil.which("bash")


def _system_bash_3():
    """macOS's /bin/bash, which is still bash 3.2, when this machine has it: report.sh
    must run there, and a bash 5 earlier on PATH (Homebrew, or Linux CI) would hide a
    bash-4-only construct."""
    if not os.path.exists("/bin/bash"):
        return None
    out = subprocess.run(["/bin/bash", "-c", "echo ${BASH_VERSINFO[0]}"], capture_output=True, text=True)
    return "/bin/bash" if out.stdout.strip() == "3" else None


BASH_3 = _system_bash_3()

STUB_RUN_DAILY = r'''#!/usr/bin/env python3
import json, os, sys
with open(os.environ["STUB_LOG"], "a") as f:
    f.write(json.dumps({"script": "run_daily", "JEV_JUDGE_BACKEND": os.environ.get("JEV_JUDGE_BACKEND"),
                        "argv": sys.argv[1:]}) + "\n")
'''

STUB_ROLLUP_DAY = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from result_v0 import build_result_v0_for_day
argv = sys.argv[1:]
out = pathlib.Path(argv[argv.index("--out") + 1])
out.mkdir(parents=True, exist_ok=True)
with open(os.environ["STUB_LOG"], "a") as f:
    f.write(json.dumps({"script": "rollup_day", "JEV_JUDGE_BACKEND": os.environ.get("JEV_JUDGE_BACKEND")}) + "\n")
for day in filter(None, os.environ.get("STUB_DAYS", "").split(",")):
    doc = build_result_v0_for_day(f"day:{day}", [(f"case-{day}", {"c1": "met"}, {"c1": ["ab" * 32]},
                                                  {"c1": "judged"})],
                                  f"{day}T23:59:59Z", ("c1",), "stub-pack@1")
    (out / f"result-v0-{day}.json").write_text(json.dumps(doc))
'''

STUB_CAPSULECTL = r'''#!/usr/bin/env python3
import json, os, shutil, sys
argv = sys.argv[1:]
def opt(name):
    return argv[argv.index(name) + 1]
cap = os.environ["STUB_CAPTURE"]
if argv[:3] == ["book", "result", "build"]:
    shutil.copy(opt("--result"), os.path.join(cap, "sealed-result.json"))
    shutil.copy(opt("--result"), opt("--out"))
    print(json.dumps({"record_id": "rec-1"}))
elif argv[:3] == ["cll", "checkpoint", "create"]:
    print("{}")
elif argv[:1] == ["disclose"]:
    json.dump({"records": [], "completeness_certificate": {"memberships": {}}}, open(opt("--out"), "w"))
elif argv[:3] == ["book", "report", "build"]:
    shutil.copy(opt("--presentation"), os.path.join(cap, "page-presentation.json"))
    open(opt("--out"), "w").write("<html></html>")
    print("{}")
else:
    sys.exit("stub capsulectl: unexpected call " + " ".join(argv))
'''


def _exe(path, text):
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@unittest.skipIf(BASH is None or shutil.which("jq") is None, "needs bash and jq")
class ReportShJudgedPath(unittest.TestCase):
    bash = BASH

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="test-report-sh-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        shutil.copytree(ROOT / "scripts", self.tmp / "scripts")
        _exe(self.tmp / "scripts" / "run_daily.py", STUB_RUN_DAILY)
        _exe(self.tmp / "scripts" / "rollup_day.py", STUB_ROLLUP_DAY)
        self.ctl = self.tmp / "capsulectl"
        _exe(self.ctl, STUB_CAPSULECTL)
        # A compiled pack contract NOT named compiled.json: no presentation
        # block, so the presentation-digest steps are skipped here (they are
        # tested in tests/test_presentation_digest.py).
        self.spec = self.tmp / "contract.json"
        self.spec.write_text(json.dumps({"contract": "stub-pack", "clauses": [{"id": "c1"}],
                                         "judge": {"model_id": "jev-1.13.0"}}))
        self.capture = self.tmp / "capture"
        self.capture.mkdir()
        self.log = self.tmp / "stub.log"

    def run_report(self, *args, days="2026-10-01,2026-10-02", env_extra=None, work=None):
        env = dict(os.environ)
        env.pop("JEV_JUDGE_BACKEND", None)
        env.update({"STUB_LOG": str(self.log), "STUB_CAPTURE": str(self.capture), "STUB_DAYS": days,
                    "PATH": f"{pathlib.Path(sys.executable).parent}{os.pathsep}{env.get('PATH', '')}"})
        env.update(env_extra or {})
        cmd = [self.bash, str(self.tmp / "scripts" / "report.sh"), "--spec", str(self.spec), "--profile", "p",
               "--out", str(self.tmp / "report.html"), "--capsulectl", str(self.ctl),
               "--work", str(work or self.tmp / "work"), *args]
        return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120)

    def sealed(self):
        return json.loads((self.capture / "sealed-result.json").read_text())

    def calls(self, script):
        return [json.loads(line) for line in self.log.read_text().splitlines()
                if json.loads(line)["script"] == script]

    def test_a_two_day_book_reports_only_the_day_asked_for(self):
        proc = self.run_report("--date", "2026-10-02")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        claim_ids = [c["id"] for c in self.sealed()["claims"]]
        self.assertTrue(claim_ids)
        self.assertTrue(all("2026-10-02" in cid for cid in claim_ids), claim_ids)

    def test_a_range_takes_every_day_in_it_and_nothing_outside(self):
        proc = self.run_report("--date", "2026-10-01", "--to", "2026-10-02",
                               days="2026-09-30,2026-10-01,2026-10-02,2026-10-03")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        days = sorted({c["id"].split("::")[0] for c in self.sealed()["claims"]})
        self.assertEqual(days, ["case-2026-10-01", "case-2026-10-02"])

    def test_a_day_in_the_range_with_no_result_stops_the_run(self):
        proc = self.run_report("--date", "2026-10-01", "--to", "2026-10-03")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("no judged result for 2026-10-03", proc.stderr)
        self.assertFalse((self.capture / "sealed-result.json").exists())

    def test_a_reused_work_dir_never_mixes_in_an_earlier_runs_results(self):
        work = self.tmp / "work"
        stale = work / "rollup"
        stale.mkdir(parents=True)
        (stale / "result-v0-2026-09-01.json").write_text("{}")
        (stale / "result-v0-merged.json").write_text("{}")
        first = self.run_report("--date", "2026-10-01", work=work)
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        second = self.run_report("--date", "2026-10-02", work=work)
        self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
        days = {c["id"].split("::")[0] for c in self.sealed()["claims"]}
        self.assertEqual(days, {"case-2026-10-02"})
        self.assertEqual(len(list(work.glob("run.*"))), 2)
        # --work/last-run is the newest run's directory.
        last = work / "last-run"
        self.assertTrue(last.is_symlink())
        claims = json.loads((last / "rollup" / "result-v0-2026-10-02.json").read_text())["claims"]
        self.assertTrue(all("2026-10-02" in c["id"] for c in claims))

    def test_live_sets_the_real_backend_even_with_an_inherited_mock(self):
        proc = self.run_report("--date", "2026-10-01", "--judge-backend", "live",
                               env_extra={"JEV_JUDGE_BACKEND": "mock", "TYPESAFE_API_KEY": "test-key"})
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        for script in ("run_daily", "rollup_day"):
            self.assertEqual({c["JEV_JUDGE_BACKEND"] for c in self.calls(script)}, {"jev"}, script)
        argv = self.calls("run_daily")[0]["argv"]
        self.assertEqual(argv[argv.index("--judge-model-id") + 1], "jev-1.13.0")

    def test_mock_sets_the_mock_backend_and_marks_the_model_id(self):
        proc = self.run_report("--date", "2026-10-01", env_extra={"JEV_JUDGE_BACKEND": "jev"})
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        for script in ("run_daily", "rollup_day"):
            self.assertEqual({c["JEV_JUDGE_BACKEND"] for c in self.calls(script)}, {"mock"}, script)
        argv = self.calls("run_daily")[0]["argv"]
        self.assertIn("mock backend", argv[argv.index("--judge-model-id") + 1])

    def test_title_is_sealed_in_the_result_not_replaced_after(self):
        proc = self.run_report("--date", "2026-10-01", "--title", "October, airline support")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertEqual(self.sealed()["view"]["title"], "October, airline support")
        page = json.loads((self.capture / "page-presentation.json").read_text())
        self.assertEqual(page["title"], "October, airline support")

    def test_without_title_the_page_shows_the_sealed_results_own(self):
        proc = self.run_report("--date", "2026-10-01")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        page = json.loads((self.capture / "page-presentation.json").read_text())
        self.assertEqual(page["title"], self.sealed()["view"]["title"])



@unittest.skipIf(BASH_3 is None or shutil.which("jq") is None, "needs /bin/bash 3.x (macOS) and jq")
class ReportShJudgedPathBash3(ReportShJudgedPath):
    """Every case above again under bash 3.2."""
    bash = BASH_3


if __name__ == "__main__":
    unittest.main()
