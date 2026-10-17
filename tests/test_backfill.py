"""demo/backfill/backfill.py: one seal request per task, for the trial asked for.

    python3 -m unittest discover -s tests -p 'test_*.py'
"""
import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "demo" / "backfill"))

import backfill  # noqa: E402


def _sim(task_id, trial):
    return {"id": f"sim-{task_id}-{trial}", "task_id": task_id, "trial": trial,
            "timestamp": f"2025-06-05T14:1{trial}:05Z",
            "messages": [{"role": "user", "content": f"task {task_id} trial {trial}"}]}


RESULTS = {"info": {"environment_info": {"domain_name": "airline"}},
           "simulations": [_sim(t, n) for t in ("1", "2") for n in (0, 1)]}


class Trial(unittest.TestCase):
    def _run(self, *extra):
        d = pathlib.Path(self.enterContext(tempfile.TemporaryDirectory()))
        (d / "results.json").write_text(json.dumps(RESULTS))
        with contextlib.redirect_stdout(io.StringIO()):
            rc = backfill.main(["--results", str(d / "results.json"), "--out", str(d / "out"), *extra])
        self.assertEqual(rc, 0)
        return {p.name: json.loads(p.read_text()) for p in sorted((d / "out").glob("task-*.json"))}

    def test_default_is_trial_zero(self):
        out = self._run()
        self.assertEqual(sorted(out), ["task-1.json", "task-2.json"])
        self.assertEqual({r["payload"]["case"]["trial"] for r in out.values()}, {0})

    def test_trial_one_seals_each_task_s_trial_one_run(self):
        out = self._run("--trial", "1")
        self.assertEqual(sorted(out), ["task-1.json", "task-2.json"])
        for name, request in out.items():
            self.assertEqual(request["payload"]["case"]["trial"], 1)
            self.assertTrue(request["capsule"]["ActionID"].endswith(":trial-1"))
            self.assertIn("trial 1", request["payload"]["agent_interaction"]["messages"][0]["content"])

    def test_a_trial_the_file_does_not_hold_is_refused(self):
        with self.assertRaisesRegex(SystemExit, "no trial-7 simulations"):
            self._run("--trial", "7")

    def test_a_negative_trial_is_refused(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self._run("--trial", "-1")


if __name__ == "__main__":
    unittest.main()
