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


class CaseModel(unittest.TestCase):
    """--case-model names the agent model in the case, so two agents' runs of one
    task and trial are two cases with two case ids."""

    def _run(self, results, *extra):
        d = pathlib.Path(self.enterContext(tempfile.TemporaryDirectory()))
        (d / "results.json").write_text(json.dumps(results))
        with contextlib.redirect_stdout(io.StringIO()):
            rc = backfill.main(["--results", str(d / "results.json"), "--out", str(d / "out"), *extra])
        self.assertEqual(rc, 0)
        return {p.name: json.loads(p.read_text()) for p in sorted((d / "out").glob("task-*.json"))}

    def test_default_case_has_no_model_and_the_old_id(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        from capsulectl_calls import case_id_of
        out = self._run(dict(RESULTS, info=dict(RESULTS["info"], agent_info={"llm": "agent-a"})))
        case = out["task-1.json"]["payload"]["case"]
        self.assertNotIn("agent_model", case)
        self.assertEqual(case_id_of(case), "tau2:airline:task-1:trial-0")
        self.assertEqual(out["task-1.json"]["capsule"]["ActionID"], "urn:tau2:airline:task-1:trial-0")

    def test_case_model_puts_the_agent_in_case_id_and_action_id(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        from capsulectl_calls import case_id_of
        ids = set()
        for llm in ("agent-a", "agent-b"):
            out = self._run(dict(RESULTS, info=dict(RESULTS["info"], agent_info={"llm": llm})), "--case-model")
            request = out["task-1.json"]
            self.assertEqual(request["payload"]["case"]["agent_model"], llm)
            self.assertEqual(request["capsule"]["ActionID"], f"urn:tau2:airline:{llm}:task-1:trial-0")
            ids.add(case_id_of(request["payload"]["case"]))
        self.assertEqual(ids, {"tau2:airline:agent-a:task-1:trial-0", "tau2:airline:agent-b:task-1:trial-0"})

    def test_case_model_without_an_agent_llm_is_refused(self):
        with self.assertRaisesRegex(SystemExit, "names no agent_info.llm"):
            self._run(RESULTS, "--case-model")

    def test_case_id_refuses_a_model_with_a_colon_or_a_slash(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        from capsulectl_calls import case_id_of
        for model in ("a:b", "openai/gpt-4.1", "", "anthropic.claude-3-v1:0"):
            with self.assertRaisesRegex(ValueError, r"\[A-Za-z0-9\._-\]\+"):
                case_id_of({"benchmark": "tau2", "domain": "airline", "task_id": "1", "trial": 0,
                            "agent_model": model})

    def test_a_model_every_reader_would_refuse_is_refused_at_seal_time(self):
        # The book is append-only: a model that can't go in a case id is
        # refused before any seal request is written, not when it is read.
        for llm in ("anthropic.claude-3-5-sonnet-20240620-v1:0", "openai/gpt-4.1"):
            d = pathlib.Path(self.enterContext(tempfile.TemporaryDirectory()))
            (d / "results.json").write_text(json.dumps(dict(RESULTS, info=dict(RESULTS["info"],
                                                                               agent_info={"llm": llm}))))
            with self.assertRaises(SystemExit) as cm, contextlib.redirect_stdout(io.StringIO()):
                backfill.main(["--results", str(d / "results.json"), "--out", str(d / "out"), "--case-model"])
            self.assertIn("can't go in a case id", str(cm.exception.code))
            self.assertIn(repr(llm), str(cm.exception.code))
            self.assertEqual(list((d / "out").glob("*.json")) if (d / "out").exists() else [], [])

    def test_a_rejected_case_model_leaves_the_prior_request_files_in_place(self):
        # review of edd79a8: the model check runs before the old task-*.json files are
        # cleared, so a refused --case-model run never loses the previous run's requests.
        d = pathlib.Path(self.enterContext(tempfile.TemporaryDirectory()))
        good = dict(RESULTS, info=dict(RESULTS["info"], agent_info={"llm": "gpt-4.1-2025-04-14"}))
        (d / "results.json").write_text(json.dumps(good))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(backfill.main(["--results", str(d / "results.json"), "--out", str(d / "out"),
                                            "--case-model"]), 0)
        before = {p.name: p.read_text() for p in (d / "out").glob("task-*.json")}
        self.assertEqual(sorted(before), ["task-1.json", "task-2.json"])
        bad = dict(RESULTS, info=dict(RESULTS["info"], agent_info={"llm": "openai/gpt-4.1"}))
        (d / "bad.json").write_text(json.dumps(bad))
        with self.assertRaises(SystemExit), contextlib.redirect_stdout(io.StringIO()):
            backfill.main(["--results", str(d / "bad.json"), "--out", str(d / "out"), "--case-model"])
        self.assertEqual({p.name: p.read_text() for p in (d / "out").glob("task-*.json")}, before)

    def test_a_model_without_a_colon_or_a_slash_is_sealed(self):
        out = self._run(dict(RESULTS, info=dict(RESULTS["info"], agent_info={"llm": "gpt-4.1-2025-04-14"})),
                        "--case-model")
        self.assertEqual(out["task-1.json"]["payload"]["case"]["agent_model"], "gpt-4.1-2025-04-14")


if __name__ == "__main__":
    unittest.main()
