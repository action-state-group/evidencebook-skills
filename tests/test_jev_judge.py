"""Unit tests for scripts/judges/jev_judge.py: the mock backend (well-formed answer,
API error), malformed input (bad JSON, missing fields), and the CLI's exit-code
contract. No network, no TYPESAFE_API_KEY, no real Jev call anywhere in this file.

    python3 -m unittest discover -s tests -p 'test_*.py'
"""
import json
import os
import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "judges"))

import jevals  # noqa: E402
import jev_judge  # noqa: E402

SAMPLE_REQUEST = {
    "clause": {
        "id": "policy_compliance.confirmed_before_acting",
        "check_id": "policy_compliance",
        "claim": "Explicit yes from the customer before any booking, change or cancellation.",
    },
    "case": {"benchmark": "tau2", "domain": "airline", "task_id": "1", "trial": 0},
    "agent_interaction": {
        "messages": [
            {"role": "user", "content": "Please cancel my flight."},
            {"role": "assistant", "content": "Can you confirm you want to cancel reservation ABC123?"},
            {"role": "user", "content": "Yes, please cancel it."},
        ]
    },
    "policy": str(ROOT / "airline-data" / "policy.md"),
    "booking_db": str(ROOT / "airline-data" / "db.json"),
    "judge_model_id": "jev-1.13.0",
}

JEV_JUDGE_PATH = str(ROOT / "scripts" / "judges" / "jev_judge.py")


class JudgeFunction(unittest.TestCase):
    def test_mock_backend_well_formed_answer(self):
        answer = jev_judge.judge(SAMPLE_REQUEST, backend=jevals.MockBackend(answers={"q": "met"}))
        self.assertEqual(answer["verdict"], "met")
        self.assertTrue(answer["rationale"])

    def test_every_verdict_is_reachable_through_the_mock_backend(self):
        # clause ids are dotted (e.g. "policy_compliance.confirmed_before_acting"), so
        # MockBackend's answers={"q": ...} shorthand (which un-namespaces on the FIRST
        # dot only) can't address this eval's question by its bare qid; a fn callback
        # sidesteps the namespacing entirely.
        for verdict in jev_judge.VERDICTS:
            answer = jev_judge.judge(SAMPLE_REQUEST, backend=jevals.MockBackend(fn=lambda qid, q, state, v=verdict: v))
            self.assertEqual(answer["verdict"], verdict)

    def test_mock_backend_varies_by_criterion_not_only_by_conversation(self):
        # _mock_fn must hash the question's own instructions (clause-specific),
        # not just state (conversation + policy, identical across a case's nine
        # clauses) -- otherwise every criterion in one conversation gets the same
        # verdict, which defeats tests/fresh_env_outcomes.sh's whole point: exercising a
        # mixed-verdict case for scripts/rollup.py's combine()/check_verdicts().
        # Checked across all nine real clauses (not just two, which a 1-in-3 hash
        # collision could pass by luck): at least one pair must differ.
        compiled = json.loads((ROOT / "demo" / "tau2-outcomes" / "compiled.json").read_text())
        backend = jevals.MockBackend(fn=jev_judge._mock_fn)
        verdicts = {
            clause["id"]: jev_judge.judge(dict(SAMPLE_REQUEST, clause=clause), backend=backend)["verdict"]
            for clause in compiled["clauses"]
        }
        self.assertGreater(len(set(verdicts.values())), 1, verdicts)

    def test_backend_error_fails_closed(self):
        def boom(qid, q, state):
            raise RuntimeError("simulated API error")

        with self.assertRaisesRegex(jev_judge.JudgeError, "judge backend error"):
            jev_judge.judge(SAMPLE_REQUEST, backend=jevals.MockBackend(fn=boom))

    def test_missing_clause_fails_closed(self):
        with self.assertRaisesRegex(jev_judge.JudgeError, "no clause"):
            jev_judge.judge({"case": {}, "agent_interaction": {"messages": [{"role": "user", "content": "hi"}]}})

    def test_missing_messages_fails_closed(self):
        bad = dict(SAMPLE_REQUEST, agent_interaction={})
        with self.assertRaisesRegex(jev_judge.JudgeError, "messages"):
            jev_judge.judge(bad)

    def test_request_that_is_not_an_object_fails_closed(self):
        with self.assertRaisesRegex(jev_judge.JudgeError, "not a JSON object"):
            jev_judge.judge("met")

    def test_real_backend_pins_model_without_ever_calling_it(self):
        """resolve_backend() force-sets TYPESAFE_MODEL and returns the backend spec
        string "jev" -- it never constructs a TypeSafeBackend or makes a request, so
        this test never touches the network or a real key."""
        env_backup = dict(os.environ)
        try:
            os.environ.pop("JEV_JUDGE_BACKEND", None)
            os.environ["TYPESAFE_API_KEY"] = "unit-test-placeholder-never-sent-anywhere"
            os.environ["TYPESAFE_MODEL"] = "some-other-model"
            spec = jev_judge.resolve_backend()
            self.assertEqual(spec, "jev")
            self.assertEqual(os.environ["TYPESAFE_MODEL"], "jev-1.13.0")
        finally:
            os.environ.clear()
            os.environ.update(env_backup)

    def test_a_stale_judge_model_id_is_refused_before_any_backend_call(self):
        # --judge-model-id is operator-supplied free text, sealed verbatim into
        # judge_pin_digest by run_daily.py; nothing else cross-checks it against
        # what this script actually pins (TYPESAFE_MODEL). A mismatch must be
        # refused here, before jevals.evaluate() is ever reached -- passing
        # backend="jev" (the real-backend spec string) directly proves this: if
        # the check didn't fire first, this would instead fail on a missing
        # TYPESAFE_API_KEY deep inside jevals, a different and less clear error.
        bad = dict(SAMPLE_REQUEST, judge_model_id="some-other-model")
        with self.assertRaisesRegex(jev_judge.JudgeError, "does not match the model"):
            jev_judge.judge(bad, backend="jev")

    def test_real_backend_without_a_key_fails_closed(self):
        env_backup = dict(os.environ)
        try:
            os.environ.pop("JEV_JUDGE_BACKEND", None)
            os.environ.pop("TYPESAFE_API_KEY", None)
            with self.assertRaisesRegex(jev_judge.JudgeError, "TYPESAFE_API_KEY"):
                jev_judge.resolve_backend()
        finally:
            os.environ.clear()
            os.environ.update(env_backup)


class CLI(unittest.TestCase):
    def _run(self, stdin_text):
        env = dict(os.environ, JEV_JUDGE_BACKEND="mock")
        return subprocess.run(
            [sys.executable, JEV_JUDGE_PATH], input=stdin_text, capture_output=True, text=True, env=env
        )

    def test_bad_json_on_stdin_exits_nonzero_and_prints_nothing_on_stdout(self):
        proc = self._run("not json")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "")
        self.assertIn("not valid JSON", proc.stderr)

    def test_mock_end_to_end_prints_exactly_verdict_and_rationale(self):
        proc = self._run(json.dumps(SAMPLE_REQUEST))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(set(out), {"verdict", "rationale"})
        self.assertIn(out["verdict"], jev_judge.VERDICTS)
        self.assertTrue(out["rationale"])

    def test_missing_clause_exits_nonzero_on_the_cli_too(self):
        bad = dict(SAMPLE_REQUEST)
        del bad["clause"]
        proc = self._run(json.dumps(bad))
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "")


class DateAwareState(unittest.TestCase):
    """The date-aware prompt (always on): state carries the policy's own current
    time and every reservation_id -> created_at the conversation's tool results
    show, so a date-dependent criterion doesn't have to take the agent's own claim
    about a date at face value (the first live run's audit, task 1)."""

    def test_state_carries_policy_current_time_and_reservation_timestamps(self):
        request = dict(SAMPLE_REQUEST, agent_interaction={"messages": [
            {"role": "user", "content": "cancel please"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "name": "cancel_reservation", "arguments": {"reservation_id": "Q69X3R"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": json.dumps(
                {"reservation_id": "Q69X3R", "created_at": "2024-05-14T09:52:38"})},
        ]})
        captured = {}

        def fn(qid, q, state):
            captured.update(state)
            return "met"

        jev_judge.judge(request, backend=jevals.MockBackend(fn=fn))
        self.assertEqual(captured["policy_current_time"], "2024-05-15T15:00:00")
        self.assertEqual(captured["reservation_timestamps"], {"Q69X3R": "2024-05-14T09:52:38"})


class NotApplicableOption(unittest.TestCase):
    def test_build_eval_without_the_switch_offers_only_three_options(self):
        ev = jev_judge.build_eval(SAMPLE_REQUEST["clause"], allow_not_applicable=False)
        self.assertEqual(set(ev.options), set(jev_judge.VERDICTS))

    def test_build_eval_with_the_switch_offers_a_fourth_option(self):
        ev = jev_judge.build_eval(SAMPLE_REQUEST["clause"], allow_not_applicable=True)
        self.assertEqual(set(ev.options), set(jev_judge.VERDICTS_WITH_NA))

    def test_not_applicable_is_reachable_through_the_mock_backend_when_allowed(self):
        request = dict(SAMPLE_REQUEST, allow_not_applicable=True)
        answer = jev_judge.judge(request, backend=jevals.MockBackend(fn=lambda qid, q, state: "not_applicable"))
        self.assertEqual(answer["verdict"], "not_applicable")

    def test_not_applicable_is_structurally_unreachable_when_not_allowed(self):
        # the eval's own options never include not_applicable unless allowed, so even
        # a backend that "wants" to answer not_applicable can only pick among the three
        # real options (MockBackend falls back to a uniform draw over them).
        answer = jev_judge.judge(SAMPLE_REQUEST, backend=jevals.MockBackend(fn=lambda qid, q, state: "not_applicable"))
        self.assertIn(answer["verdict"], jev_judge.VERDICTS)

    def test_the_real_mock_fn_can_actually_land_on_not_applicable_when_allowed(self):
        # The test above (test_not_applicable_is_reachable_through_the_mock_backend_
        # when_allowed) proves the plumbing with a hand-rolled fn that always answers
        # "not_applicable" -- it never exercises jev_judge._mock_fn, the function
        # tests/fresh_env_outcomes.sh and every real mock run actually uses. _mock_fn used
        # to pick `VERDICTS[hash % 3]` unconditionally -- the real production path --
        # which structurally could never land on a 4th option no matter how many
        # clauses were judged with the switch on; this is the bug that run hit (50
        # cases x 8 not_applicable-eligible clauses, zero not_applicable verdicts,
        # every single time, not by chance). Fixed: _mock_fn now hashes over
        # q.options, whatever size that eval actually offers. Proven here across the
        # real compiled contract's clauses, both ends of the switch: at least one
        # clause lands on not_applicable when allowed, and none ever do when not.
        # 40 synthetic clauses (distinct wording -> distinct hash basis each): with
        # a correct 4-way hash, the chance of never landing on not_applicable is
        # (3/4)^40 ~ 1e-5 -- this is a structural reachability proof, not a hope
        # the real nine happen to hit it (they didn't, in the live mock run this
        # bug was found in: see this test class's own docstring above).
        clauses = [{"id": f"synthetic.clause_{i}", "check_id": "synthetic",
                    "claim": f"Synthetic criterion number {i} for mock-distribution coverage."}
                   for i in range(40)]
        backend = jevals.MockBackend(fn=jev_judge._mock_fn)
        with_na = {
            clause["id"]: jev_judge.judge(dict(SAMPLE_REQUEST, clause=clause, allow_not_applicable=True),
                                           backend=backend)["verdict"]
            for clause in clauses
        }
        self.assertIn("not_applicable", with_na.values())
        without_na = {
            clause["id"]: jev_judge.judge(dict(SAMPLE_REQUEST, clause=clause), backend=backend)["verdict"]
            for clause in clauses
        }
        self.assertTrue(all(v in jev_judge.VERDICTS for v in without_na.values()))


class BatchMode(unittest.TestCase):
    """judge_many(): every clause of one conversation in a single jevals.evaluate()
    call. Since every ChoiceEval built from the same request shares one state()
    (identical conversation + policy), jevals packs them into ONE backend request --
    a cost fix (the policy text was sent nine times per conversation instead of
    once)."""

    CLAUSES = [
        {"id": "policy_compliance.confirmed_before_acting", "claim": "Explicit yes before any action."},
        {"id": "policy_compliance.within_fare_rules", "claim": "No change the fare class forbids."},
        {"id": "task_resolution.right_reservation", "claim": "Found the right reservation."},
    ]

    def _request(self, **extra):
        return dict(SAMPLE_REQUEST, clauses=self.CLAUSES, **extra)

    def test_one_answer_per_clause_one_call_to_the_backend(self):
        backend = jevals.MockBackend(fn=jev_judge._mock_fn)
        request = self._request()
        del request["clause"]
        answers = jev_judge.judge_many(request, backend=backend)
        self.assertEqual(set(answers), {c["id"] for c in self.CLAUSES})
        self.assertEqual(len(backend.calls), 1, backend.calls)

    def test_verdicts_still_vary_by_criterion_not_only_by_conversation(self):
        backend = jevals.MockBackend(fn=jev_judge._mock_fn)
        answers = jev_judge.judge_many(self._request(), backend=backend)
        self.assertGreater(len({a["verdict"] for a in answers.values()}), 1, answers)

    def test_missing_clauses_fails_closed(self):
        bad = self._request()
        del bad["clauses"]
        with self.assertRaisesRegex(jev_judge.JudgeError, "no clauses"):
            jev_judge.judge_many(bad)

    def test_cli_batch_mode_prints_an_answers_object(self):
        env = dict(os.environ, JEV_JUDGE_BACKEND="mock")
        bad = self._request()
        del bad["clause"]
        proc = subprocess.run([sys.executable, JEV_JUDGE_PATH], input=json.dumps(bad),
                               capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(set(out), {"answers"})
        self.assertEqual(set(out["answers"]), {c["id"] for c in self.CLAUSES})


class PinnedInstructions(unittest.TestCase):
    """The judge pin covers what this judge sends (instruction_template_digest),
    not only a prompt file it never reads."""

    def test_describe_reports_the_template_digest(self):
        proc = subprocess.run([sys.executable, JEV_JUDGE_PATH], input=json.dumps({"describe": True}),
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        described = json.loads(proc.stdout)
        self.assertEqual(described["instruction_template_digest"], jev_judge.instruction_template_digest())
        self.assertEqual(described["pinned_model"], jev_judge.PINNED_MODEL)

    def test_the_digest_moves_when_the_instructions_move(self):
        before = jev_judge.instruction_template_digest()
        original = jev_judge.INSTRUCTION_TEMPLATE
        try:
            jev_judge.INSTRUCTION_TEMPLATE = original + " Be lenient."
            self.assertNotEqual(jev_judge.instruction_template_digest(), before)
        finally:
            jev_judge.INSTRUCTION_TEMPLATE = original
        self.assertEqual(jev_judge.instruction_template_digest(), before)

    def test_build_eval_sends_exactly_the_pinned_template(self):
        clause = SAMPLE_REQUEST["clause"]
        expected = jev_judge.INSTRUCTION_TEMPLATE.format(clause_id=clause["id"], claim=clause["claim"],
                                                         na_instructions="")
        self.assertEqual(jev_judge.build_eval(clause).instructions, expected)


class BackendSelection(unittest.TestCase):
    def test_a_misspelled_backend_is_refused_not_the_real_backend(self):
        for typo in ("mok", "MOCK ", "jevv", "real"):
            env = dict(os.environ, JEV_JUDGE_BACKEND=typo, TYPESAFE_API_KEY="present-but-unused")
            proc = subprocess.run([sys.executable, JEV_JUDGE_PATH], input=json.dumps(SAMPLE_REQUEST),
                                  capture_output=True, text=True, env=env)
            if typo.strip().lower() == "mock":
                self.assertEqual(proc.returncode, 0, proc.stderr)
                continue
            self.assertEqual(proc.returncode, 1, typo)
            self.assertIn("is not one of", proc.stderr)
            self.assertEqual(proc.stdout, "")


class ConfidenceThreshold(unittest.TestCase):
    def _backend(self, confidence):
        class Result:
            def __init__(self):
                self.error, self.skipped, self.detail = None, False, None
                self.answer = "met"
                self.evidence = {"probabilities": {"met": confidence}, "confidence": confidence}
        return Result()

    def test_below_the_threshold_is_not_evaluable(self):
        low = jev_judge._answer_from_result(self._backend(0.55), False, min_confidence=0.8)
        self.assertEqual(low["verdict"], "not_evaluable")
        self.assertIn("below the pinned min_confidence", low["rationale"])
        high = jev_judge._answer_from_result(self._backend(0.95), False, min_confidence=0.8)
        self.assertEqual(high["verdict"], "met")
        none = jev_judge._answer_from_result(self._backend(None), False, min_confidence=0.8)
        self.assertEqual(none["verdict"], "not_evaluable", "no reported confidence never clears a threshold")
        self.assertEqual(jev_judge._answer_from_result(self._backend(0.1), False)["verdict"], "met",
                         "no threshold: unchanged")

    def test_a_malformed_threshold_is_refused(self):
        for bad in (0, 2, "0.8", True):
            with self.assertRaises(jev_judge.JudgeError):
                jev_judge.judge(dict(SAMPLE_REQUEST, min_confidence=bad),
                                backend=jevals.MockBackend(fn=lambda qid, q, state: "met"))


class NeverNotApplicable(unittest.TestCase):
    def test_a_never_not_applicable_clause_is_not_offered_not_applicable(self):
        clause = dict(SAMPLE_REQUEST["clause"], never_not_applicable=True)
        ev = jev_judge.build_eval(clause, allow_not_applicable=True)
        self.assertNotIn("not_applicable", ev.options)
        self.assertNotIn("not_applicable --", ev.instructions)


class MalformedRequests(unittest.TestCase):
    def test_a_mistyped_request_exits_cleanly(self):
        for request in ({"clauses": ["not-a-clause"], **{k: v for k, v in SAMPLE_REQUEST.items() if k != "clause"}},
                        {"clause": {"id": "x", "claim": "y"}, "agent_interaction": {"messages": "nope"}}):
            env = dict(os.environ, JEV_JUDGE_BACKEND="mock")
            proc = subprocess.run([sys.executable, JEV_JUDGE_PATH], input=json.dumps(request),
                                  capture_output=True, text=True, env=env)
            self.assertEqual(proc.returncode, 1)
            self.assertEqual(proc.stdout, "")
            self.assertNotIn("Traceback", proc.stderr)


if __name__ == "__main__":
    unittest.main()
