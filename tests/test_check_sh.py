"""scripts/check.sh's job selection (evidencebook-skills#374): ard-demo runs only when the change since the merge base
with origin/main touches a file it reads, or with --full. Each case builds a throwaway repository holding this
checkout's scripts/check.sh and asks it for its plan (`--plan`, which runs no job).

Needs bash 4.4 or later first on PATH, as check.sh itself does (macOS: brew install bash).

    python3 -m unittest tests.test_check_sh
"""
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHECK = ROOT / "scripts" / "check.sh"
OTHERS = ["unit", "viewer-drift", "admission-engine", "live-engine", "report-grades", "obligations-report", "tau2-live"]
GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid", "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_CONFIG_NOSYSTEM": "1"}


class Selection(unittest.TestCase):
    def setUp(self):
        self.repo = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.repo)
        self.git("init", "-q", "-b", "main")
        (self.repo / "scripts").mkdir()
        shutil.copy2(CHECK, self.repo / "scripts" / "check.sh")
        for path in ("demo/ard/pack.py", "docs/a.md", "packs/p.yaml", ".github/workflows/fast.yml",
                     ".github/workflows/tests.yml", "demo/tau2-live/x.py"):
            self.write(path, "base\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        # origin/main at the base commit, as a fetched clone has it.
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, env=GIT_ENV, check=True, capture_output=True, text=True)

    def write(self, path, text):
        p = self.repo / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def commit(self, *paths):
        for path in paths:
            self.write(path, "changed\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "change")

    def plan(self, *args):
        run = subprocess.run([str(self.repo / "scripts" / "check.sh"), "--plan", *args], cwd=self.repo,
                             capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        lines = run.stdout.splitlines()
        # Every other job runs whatever changed.
        self.assertEqual(lines[:-1], [f"{job}: runs" for job in OTHERS])
        return lines[-1]

    def assertRuns(self, line, why):
        self.assertTrue(line.startswith("ard-demo: runs ("), line)
        self.assertIn(why, line)

    def assertSkipped(self, line):
        self.assertTrue(line.startswith("ard-demo: skipped (no change since the merge base with origin/main"), line)
        self.assertIn("scripts/check.sh --full runs it", line)

    def test_a_change_under_the_demo_runs_it(self):
        self.commit("demo/ard/pack.py")
        self.assertRuns(self.plan(), "demo/ard/pack.py changed")

    def test_a_change_outside_its_inputs_skips_it_with_one_line(self):
        self.commit("docs/a.md", "demo/tau2-live/x.py", ".github/workflows/fast.yml", "requirements.txt")
        self.assertSkipped(self.plan())

    def test_no_change_skips_it(self):
        self.assertSkipped(self.plan())

    def test_full_runs_it_whatever_changed(self):
        self.commit("docs/a.md")
        self.assertRuns(self.plan("--full"), "(--full)")

    def test_its_pins_in_tests_yml_run_it(self):
        self.commit(".github/workflows/tests.yml")
        self.assertRuns(self.plan(), ".github/workflows/tests.yml changed")

    def test_this_script_runs_it(self):
        with open(self.repo / "scripts" / "check.sh", "a") as f:
            f.write("# edited\n")
        self.git("commit", "-q", "-am", "edit check.sh")
        self.assertRuns(self.plan(), "scripts/check.sh changed")

    def test_an_untracked_file_under_its_inputs_runs_it(self):
        self.write("skills/new/SKILL.md", "x\n")
        self.assertRuns(self.plan(), "skills/new/SKILL.md changed")

    def test_an_unstaged_edit_runs_it(self):
        self.write("packs/p.yaml", "edited\n")
        self.assertRuns(self.plan(), "packs/p.yaml changed")

    def test_a_staged_file_runs_it(self):
        self.write("schemas/s.json", "{}\n")
        self.git("add", "schemas/s.json")
        self.assertRuns(self.plan(), "schemas/s.json changed")

    def test_a_file_moved_out_of_its_inputs_runs_it(self):
        self.git("mv", "demo/ard/pack.py", "docs/pack.py")
        self.git("commit", "-q", "-m", "move")
        self.assertRuns(self.plan(), "demo/ard/pack.py changed")

    def test_a_name_that_only_starts_like_an_input_skips_it(self):
        self.commit("demo/ardent.md", "skillsets/x.md")
        self.assertSkipped(self.plan())

    def test_without_a_merge_base_it_runs(self):
        self.git("update-ref", "-d", "refs/remotes/origin/main")
        self.assertRuns(self.plan(), "no merge base with origin/main")

    def test_an_unknown_argument_is_refused(self):
        run = subprocess.run([str(self.repo / "scripts" / "check.sh"), "--fast"], cwd=self.repo,
                             capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
        self.assertEqual(run.returncode, 2)
        self.assertIn("usage: scripts/check.sh [--full] [--plan]", run.stderr)


class CIStillRunsIt(unittest.TestCase):
    """What the local check may skip, main and nightly still run: every ard-demo input is in tests.yml's
    main-push paths filter, and the workflow keeps its nightly schedule."""

    def test_every_input_is_in_the_main_push_filter(self):
        text = CHECK.read_text()
        inputs = re.search(r"^ARD_INPUTS=\((.*)\)$", text, re.M).group(1).split()
        workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text()
        filters = re.findall(r'"([^"]+)"', re.search(r"^    paths: \[(.*)\]$", workflow, re.M).group(1))
        for path in inputs:
            want = path + "**" if path.endswith("/") else path
            covered = want in filters or any(f.endswith("/**") and want.startswith(f[:-2]) for f in filters)
            self.assertTrue(covered, f"{path} selects ard-demo locally but a push to main that changes it runs no "
                                     "heavy tests")
        self.assertRegex(workflow, r"(?m)^  schedule:\n    - cron: ")


if __name__ == "__main__":
    unittest.main()
