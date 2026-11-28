"""scripts/check.sh: its job selection (evidencebook-skills#425: the end-to-end jobs, ard-demo and tau2-live, run only
with --full, asked through `--plan`, which runs no job) and its runner (#419).

Needs bash 4.4 or later first on PATH, as check.sh itself does (macOS: brew install bash).

    python3 -m unittest tests.test_check_sh
"""
import os
import pathlib
import re
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHECK = ROOT / "scripts" / "check.sh"
FAST = ["unit", "viewer-drift", "admission-engine", "live-engine", "report-grades", "obligations-report", "contracts", "neutrality",
        "ard-demo-unit", "tau2-live-unit"]
E2E = ["ard-demo", "tau2-live"]
GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid", "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_CONFIG_NOSYSTEM": "1"}


class Selection(unittest.TestCase):
    def plan(self, *args):
        run = subprocess.run([str(CHECK), "--plan", *args], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                             timeout=60)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        return run.stdout.splitlines()

    def test_the_default_skips_the_end_to_end_jobs(self):
        self.assertEqual(self.plan(), [f"{job}: runs" for job in FAST] +
                         [f"{job}: skipped (scripts/check.sh --full runs it)" for job in E2E])

    def test_full_runs_every_job(self):
        self.assertEqual(self.plan("--full"), [f"{job}: runs" for job in FAST + E2E])

    def test_an_unknown_argument_is_refused(self):
        run = subprocess.run([str(CHECK), "--fast"], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
        self.assertEqual(run.returncode, 2)
        self.assertIn("usage: scripts/check.sh [--full] [--plan]", run.stderr)


class Stubbed(unittest.TestCase):
    """A copy of check.sh whose jobs are replaced by STUBS just before the runner: the copy's own runner, traps and
    cleanup run, nothing else does."""

    STUBS = ""

    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        repo = self.dir / "repo"
        (repo / "scripts").mkdir(parents=True)
        text = CHECK.read_text()
        marker = "# Every job starts at once"
        self.assertIn(marker, text)
        (repo / "scripts" / "check.sh").write_text(text.replace(marker, self.STUBS + marker, 1))
        (repo / "scripts" / "check.sh").chmod(0o755)
        tools = self.dir / "tools"
        tools.mkdir()
        for tool in ("gh", "go", "uv"):  # only looked up before the runner; the stubs call none of them
            (tools / tool).write_text("#!/bin/sh\nexit 0\n")
            (tools / tool).chmod(0o755)
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, env=GIT_ENV, check=True)
        subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "base"], cwd=repo, env=GIT_ENV, check=True)
        subprocess.run(["git", "update-ref", "refs/remotes/origin/main", "HEAD"], cwd=repo, env=GIT_ENV, check=True)
        self.repo = repo
        self.env = {**GIT_ENV, "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}", "OUT": str(self.dir),
                    "CHECK_DEPS": str(self.dir / "deps")}


class Runner(Stubbed):
    """The runner that starts every job at once (evidencebook-skills#419)."""

    STUBS = r"""
for j in "${jobs[@]}"; do eval "job_${j//-/_}() { echo \"ran $j\"; }"; done
job_unit() { echo unit-out; sleep 1; }
job_contracts() { echo contracts-out; exit 3; }
job_tau2_live() {
  # A grandchild that ignores TERM, and checks that the run's $tmp is still there while it is being stopped.
  # set +e: the job's errexit would end it when TERM kills its sleep.
  ( set +e; trap '[[ -d "$tmp" ]] && echo kept >"$OUT/tmp-at-term"' TERM; echo $BASHPID >"$OUT/grandchild";
    while :; do sleep 0.1; done ) &
  [[ -n "${HANG:-}" ]] && wait
  kill -KILL $! 2>/dev/null; true
}
"""

    def gone(self, pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        return False

    def test_a_failing_job_fails_the_run_and_the_others_still_finish(self):
        run = subprocess.run([str(self.repo / "scripts" / "check.sh"), "--full"], cwd=self.repo, env=self.env,
                             capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("check.sh: FAILED: contracts", run.stderr)
        # Each job's own output is printed under its name, ahead of its result line.
        self.assertRegex(run.stdout, r"(?m)^=== unit\nunit-out\n=== unit: pass ")
        self.assertRegex(run.stdout, r"(?m)^=== contracts\ncontracts-out\n=== contracts: FAIL ")
        summary = [line.split()[:2] for line in run.stdout.splitlines() if re.match(r"^[a-z0-9-]+ {2,}(pass|FAIL)", line)]
        want = [[j, "FAIL" if j == "contracts" else "pass"] for j in FAST + E2E]
        self.assertEqual(summary, want)

    def test_the_default_run_starts_no_end_to_end_job(self):
        run = subprocess.run([str(self.repo / "scripts" / "check.sh")], cwd=self.repo, env=self.env,
                             capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)  # the contracts stub fails
        for job in FAST:
            self.assertRegex(run.stdout, rf"(?m)^=== {job}: (pass|FAIL) ")
        for job in E2E:
            self.assertNotRegex(run.stdout, rf"(?m)^(=== {job}$|ran {job}$)")
            self.assertRegex(run.stdout, rf"(?m)^{job} +skipped \(scripts/check.sh --full runs it\)$")
        self.assertFalse((self.dir / "grandchild").exists(), "the tau2-live stub ran")

    def test_a_term_stops_every_job_and_what_it_started(self):
        env = {**self.env, "HANG": "1"}
        proc = subprocess.Popen([str(self.repo / "scripts" / "check.sh"), "--full"], cwd=self.repo, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True)
        marker = self.dir / "grandchild"

        def stop():  # however the test ends: the runner's own TERM cleanup first, then KILL to what is left
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.communicate(timeout=20)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.communicate()
            if marker.exists() and marker.read_text().strip():
                pid = int(marker.read_text())
                if not self.gone(pid):
                    os.kill(pid, signal.SIGKILL)
        self.addCleanup(stop)
        deadline = time.monotonic() + 30
        while not marker.exists() or not marker.read_text().strip():
            self.assertLess(time.monotonic(), deadline, "the stub job never started its grandchild")
            time.sleep(0.1)
        grandchild = int(marker.read_text())
        started = time.monotonic()
        proc.send_signal(signal.SIGTERM)
        out, _ = proc.communicate(timeout=60)
        self.assertEqual(proc.returncode, 143, out)
        self.assertGreaterEqual(time.monotonic() - started, 9, "the check ended before its grace period: " + out)
        # TERM is ignored, so only the KILL after the grace period stops it; $tmp was still there at TERM.
        self.assertEqual((self.dir / "tmp-at-term").read_text().strip(), "kept")
        deadline = time.monotonic() + 5
        while not self.gone(grandchild):
            self.assertLess(time.monotonic(), deadline, f"process {grandchild} outlived the check")
            time.sleep(0.1)


class DemoHomes(Stubbed):
    """Each job runs with fresh, empty demo folders of its own and none of the caller's ARD_* variables, and the run
    leaves none behind (evidencebook-skills#357): what a job sees does not depend on whether the person has a seeded
    demo home."""

    VARS = ("ARD_HOME", "ARD_GOOSE_ROOT", "ARD_TESTBED", "ARD_ACP_PREFIX", "ARD_CAPSULE_ANCHOR")
    STUBS = r"""
for j in "${jobs[@]}"; do
  eval "job_${j//-/_}() {
    env | grep '^ARD_' | sort >\"\$OUT/$j.env\"
    for v in ARD_HOME ARD_GOOSE_ROOT ARD_TESTBED ARD_ACP_PREFIX ARD_CAPSULE_ANCHOR; do
      [[ -d \"\${!v}\" && -z \"\$(ls -A \"\${!v}\")\" ]] || { echo \"\$v not a fresh empty folder\"; exit 1; }
      echo seeded >\"\${!v}/left-by-$j\"
    done
  }"
done
"""

    def test_each_job_gets_fresh_demo_folders_and_none_of_the_callers(self):
        real = self.dir / "seeded-home"
        real.mkdir()
        (real / "pages").mkdir()
        # ARD_OPEN_PAGES=1 in the caller's shell never reaches a job, so no job opens a page in the browser (#465)
        env = {**self.env, "ARD_HOME": str(real), "ARD_RAIL": "lightning", "ARD_WITNESS": "public", "ARD_OPEN_PAGES": "1"}
        run = subprocess.run([str(self.repo / "scripts" / "check.sh"), "--full"], cwd=self.repo, env=env,
                             capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        seen = {}
        for job in FAST + E2E:
            got = dict(line.split("=", 1) for line in (self.dir / f"{job}.env").read_text().splitlines())
            self.assertEqual(sorted(got), sorted(self.VARS), job)  # ARD_RAIL, ARD_WITNESS and ARD_OPEN_PAGES were dropped
            for var, value in got.items():
                self.assertNotEqual(value, str(real))
                self.assertNotIn(value, seen, f"{job} shares {var} with {seen.get(value)}")
                seen[value] = job
                self.assertFalse(pathlib.Path(value).exists(), f"{job}'s {var} outlived the run")
        self.assertEqual([p.name for p in real.iterdir()], ["pages"])  # the caller's home is untouched


class CIStillRunsIt(unittest.TestCase):
    """What the local check runs only with --full, CI still runs: tests.yml holds both end-to-end jobs, runs nightly,
    and runs on a push to main that changes either demo."""

    def test_tests_yml_runs_both_nightly_and_on_main(self):
        workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text()
        self.assertRegex(workflow, r"(?m)^  schedule:\n    - cron: ")
        self.assertRegex(workflow, r"(?m)^  push:\n    branches: \[main\]$")
        filters = re.findall(r'"([^"]+)"', re.search(r"^    paths: \[(.*)\]$", workflow, re.M).group(1))
        for job, path in (("ard-demo", "demo/ard/**"), ("tau2-live", "demo/tau2-live/**")):
            self.assertRegex(workflow, rf"(?m)^  {job}:$")
            self.assertIn(path, filters)


if __name__ == "__main__":
    unittest.main()
