"""Unit tests for scripts/pack_compile.py: validation (refuses an invalid pack
source with every issue found), deterministic compilation, and the pluggable
report-template seam.

    python3 -m unittest discover -s tests -p 'test_*.py'
"""
import copy
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import pack_compile  # noqa: E402
from pack_compile import (build_clauses, build_compiled_json, compile_pack, resolve_out_dir,  # noqa: E402
                          source_digest, validate_source, write_pack)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _criterion(id_, label=None, text=None, tier="judged", **extra):
    crit = {"id": id_, "label": label or id_, "text": text or f"{id_} happened.", "tier": tier}
    crit.update(extra)
    return crit


def minimal_source():
    """The smallest pack source validate_source() accepts -- two checks, two
    criteria each, a judge, and an outcome-report/v1 report block."""
    return {
        "pack_id": "test-pack",
        "pack_version": "1.0.0",
        "rubric_version": "1",
        "outcome_statement": "The thing works",
        "resolution_rule": "resolved only when all required criteria are met",
        "counterparty": "SAMPLE-PLACEHOLDER-no-counterparty",
        "checks": [
            {"id": "a", "question": "A?", "criteria": [_criterion("one"), _criterion("two")]},
            {"id": "b", "question": "B?", "criteria": [_criterion("three"), _criterion("four")]},
        ],
        "judge": {"model_id": "jev-1.13.0", "sampling_params": {"temperature": 0}},
        "report": {"template": "outcome-report/v1", "percentages": False},
        "sample_policy": {"per_stratum": 1, "stratify_by": "verdict", "seed": "test"},
        "disclosure": {"suppress": []},
    }


class ValidateSource(unittest.TestCase):
    def test_minimal_source_is_valid(self):
        self.assertEqual(validate_source(minimal_source()), [])

    def test_not_a_mapping_is_refused(self):
        self.assertEqual(validate_source(["nope"]), ["pack source must be a mapping"])

    def test_pack_id_with_an_at_sign_is_refused(self):
        # build_compiled_json emits contract_ref as f"{pack_id}@{pack_version}",
        # which must match the Evidence Result v0 ContractRef pattern
        # "^[^@\\s]+@[^@\\s]+$" -- an embedded "@" would compile a pack
        # `capsulectl result build` refuses.
        source = minimal_source()
        source["pack_id"] = "airline@support"
        issues = validate_source(source)
        self.assertTrue(any("pack_id" in i and "@" in i for i in issues), issues)

    def test_pack_version_with_whitespace_is_refused(self):
        source = minimal_source()
        source["pack_version"] = "1.3 0"
        issues = validate_source(source)
        self.assertTrue(any("pack_version" in i and "whitespace" in i for i in issues), issues)

    def test_missing_top_level_fields_are_all_reported_at_once(self):
        issues = validate_source({})
        for key in ("pack_id", "pack_version", "rubric_version", "outcome_statement", "resolution_rule", "counterparty"):
            self.assertTrue(any(key in i for i in issues), f"expected an issue mentioning {key!r}, got {issues}")
        self.assertTrue(any("checks" in i for i in issues))

    def test_empty_checks_is_refused(self):
        source = minimal_source()
        source["checks"] = []
        self.assertIn("checks must be a non-empty list", validate_source(source))

    def test_duplicate_check_id_is_refused(self):
        source = minimal_source()
        source["checks"][1]["id"] = "a"
        issues = validate_source(source)
        self.assertTrue(any("duplicate check id" in i for i in issues))

    def test_duplicate_criterion_id_across_the_pack_is_refused(self):
        source = minimal_source()
        source["checks"][1]["id"] = "a"  # same check id as checks[0]
        source["checks"][1]["criteria"][0]["id"] = "one"  # same criterion id -> same composite "a.one"
        issues = validate_source(source)
        self.assertTrue(any("duplicate criterion id" in i for i in issues), issues)

    def test_bad_tier_is_refused(self):
        source = minimal_source()
        source["checks"][0]["criteria"][0]["tier"] = "vibes"
        issues = validate_source(source)
        self.assertTrue(any("tier must be one of" in i for i in issues))

    def test_recomputed_without_fold_id_is_refused(self):
        source = minimal_source()
        source["checks"][0]["criteria"][0]["tier"] = "recomputed"
        issues = validate_source(source)
        self.assertTrue(any("needs a fold_id" in i for i in issues), issues)

    def test_recomputed_with_fold_id_is_accepted(self):
        source = minimal_source()
        source["checks"][0]["criteria"][0]["tier"] = "recomputed"
        source["checks"][0]["criteria"][0]["fold_id"] = "some-fold"
        self.assertEqual(validate_source(source), [])

    def test_missing_judge_model_id_is_refused(self):
        source = minimal_source()
        del source["judge"]["model_id"]
        issues = validate_source(source)
        self.assertTrue(any("judge.model_id" in i for i in issues))

    def test_unknown_report_template_is_refused(self):
        source = minimal_source()
        source["report"]["template"] = "some-future-card/v1"
        issues = validate_source(source)
        self.assertTrue(any("not a known template" in i for i in issues))

    def test_percentages_must_be_boolean(self):
        source = minimal_source()
        source["report"]["percentages"] = "true"
        issues = validate_source(source)
        self.assertTrue(any("percentages must be a boolean" in i for i in issues))

    def test_an_unknown_report_setting_is_refused(self):
        # The report presents outcomes; any other setting belongs to a product.
        source = minimal_source()
        source["report"]["per_resolution_rate"] = {"value": "1"}
        issues = validate_source(source)
        self.assertTrue(any("report.per_resolution_rate is not a report setting" in i for i in issues), issues)

    def test_never_out_of_scope_must_be_boolean_and_compiles_through(self):
        source = minimal_source()
        source["checks"][0]["criteria"][0]["never_out_of_scope"] = "yes"
        self.assertTrue(any("never_out_of_scope must be a boolean" in i for i in validate_source(source)))
        source["checks"][0]["criteria"][0]["never_out_of_scope"] = True
        self.assertEqual(validate_source(source), [])
        clauses = build_clauses(source)
        self.assertTrue(clauses[0]["never_out_of_scope"])
        self.assertNotIn("never_out_of_scope", clauses[1])

    def test_min_confidence_must_be_in_the_unit_interval(self):
        for bad in (0, 1.5, -0.1, "0.8", True):
            source = minimal_source()
            source["judge"]["min_confidence"] = bad
            self.assertTrue(any("judge.min_confidence" in i for i in validate_source(source)), bad)
        source = minimal_source()
        source["judge"]["min_confidence"] = 0.8
        self.assertEqual(validate_source(source), [])
        self.assertEqual(build_compiled_json(source, "demo/test-pack")["judge"]["min_confidence"], 0.8)
        self.assertNotIn("min_confidence", build_compiled_json(minimal_source(), "demo/test-pack")["judge"])

    def test_the_real_pack_marks_done_in_full_and_no_invented_policy_never_out_of_scope(self):
        import yaml
        source = pack_compile._strip_strings(yaml.safe_load(
            (REPO_ROOT / "packs/airline-support-outcomes/pack-source.yaml").read_text()))
        never = {c["id"] for c in build_clauses(source) if c.get("never_out_of_scope")}
        self.assertEqual(never, {"task_resolution.done_in_full", "grounded_communication.no_invented_policy"})


class Switches(unittest.TestCase):
    def test_no_switches_block_compiles_with_no_switches_key_at_all(self):
        # A pack source without switches compiles with no "switches" and no
        # "judge_batch" key; scripts/run_daily.py reads an absent "switches" as {}.
        compiled = build_compiled_json(minimal_source(), "demo/test-pack")
        self.assertNotIn("switches", compiled)
        self.assertNotIn("judge_batch", compiled)

    def test_switches_and_judge_batch_pass_through_verbatim(self):
        source = minimal_source()
        source["switches"] = {"out_of_scope_verdict": True, "done_in_full_refusal_aware": False}
        source["judge_batch"] = True
        compiled = build_compiled_json(source, "demo/test-pack")
        self.assertEqual(compiled["switches"], source["switches"])
        self.assertTrue(compiled["judge_batch"])

    def test_switches_must_be_boolean(self):
        source = minimal_source()
        source["switches"] = {"out_of_scope_verdict": "yes"}
        issues = validate_source(source)
        self.assertTrue(any("switches.out_of_scope_verdict must be a boolean" in i for i in issues), issues)

    def test_the_retired_not_applicable_names_are_refused_not_ignored(self):
        source = minimal_source()
        source["switches"] = {"not_applicable_verdict": True}
        source["checks"][0]["criteria"][0]["never_not_applicable"] = True
        issues = validate_source(source)
        self.assertTrue(any("switches.not_applicable_verdict is a retired name" in i for i in issues), issues)
        self.assertTrue(any("never_not_applicable is a retired name" in i for i in issues), issues)

    def test_judge_batch_must_be_boolean(self):
        source = minimal_source()
        source["judge_batch"] = "yes"
        issues = validate_source(source)
        self.assertTrue(any("judge_batch must be a boolean" in i for i in issues), issues)

    def test_tier_switch_flag_must_be_declared_in_switches(self):
        source = minimal_source()
        source["switches"] = {"some_other_flag": False}
        source["checks"][0]["criteria"][0]["tier_switch"] = {
            "flag": "within_fare_rules_recomputed", "tier_when_on": "recomputed",
        }
        issues = validate_source(source)
        self.assertTrue(any("not declared in the top-level switches block" in i for i in issues), issues)

    def test_tier_switch_tier_when_on_must_be_a_known_tier(self):
        source = minimal_source()
        source["switches"] = {"flag_x": False}
        source["checks"][0]["criteria"][0]["tier_switch"] = {"flag": "flag_x", "tier_when_on": "bogus"}
        issues = validate_source(source)
        self.assertTrue(any("tier_switch.tier_when_on must be one of" in i for i in issues), issues)

    def test_claim_switch_flag_must_be_declared_and_claim_when_on_non_empty(self):
        source = minimal_source()
        source["switches"] = {"flag_x": False}
        source["checks"][0]["criteria"][0]["claim_switch"] = {"flag": "undeclared_flag", "claim_when_on": ""}
        issues = validate_source(source)
        self.assertTrue(any("claim_switch.flag" in i and "not declared" in i for i in issues), issues)
        self.assertTrue(any("claim_switch.claim_when_on must be a non-empty string" in i for i in issues), issues)

    def test_valid_tier_switch_and_claim_switch_pass_validation_and_compile_through(self):
        source = minimal_source()
        source["switches"] = {"flag_tier": False, "flag_claim": False}
        source["checks"][0]["criteria"][0]["tier_switch"] = {
            "flag": "flag_tier", "tier_when_on": "recomputed", "note": "why",
        }
        source["checks"][0]["criteria"][1]["claim_switch"] = {
            "flag": "flag_claim", "claim_when_on": "a different claim", "note": "why",
        }
        self.assertEqual(validate_source(source), [])
        clauses = build_clauses(source)
        self.assertEqual(clauses[0]["tier_switch"], source["checks"][0]["criteria"][0]["tier_switch"])
        self.assertEqual(clauses[1]["claim_switch"], source["checks"][0]["criteria"][1]["claim_switch"])
        self.assertNotIn("tier_switch", clauses[1])
        self.assertNotIn("claim_switch", clauses[0])


class BuildClauses(unittest.TestCase):
    def test_composite_id_and_grouping_fields(self):
        clauses = build_clauses(minimal_source())
        self.assertEqual([c["id"] for c in clauses], ["a.one", "a.two", "b.three", "b.four"])
        self.assertEqual(clauses[0]["check_id"], "a")
        self.assertEqual(clauses[0]["check_question"], "A?")
        self.assertEqual(clauses[0]["tier"], "judged")


class CompilePack(unittest.TestCase):
    def test_deterministic(self):
        source = minimal_source()
        a = compile_pack(copy.deepcopy(source), "demo/test-pack")
        b = compile_pack(copy.deepcopy(source), "demo/test-pack")
        self.assertEqual(a, b)

    def test_editing_a_criterion_wording_changes_the_source_digest(self):
        source = minimal_source()
        before = source_digest(source)
        source["checks"][0]["criteria"][0]["text"] = "A different claim entirely."
        after = source_digest(source)
        self.assertNotEqual(before, after)

    def test_editing_a_criterion_text_changes_axes_bytes(self):
        source = minimal_source()
        _, axes_a, _, _ = compile_pack(copy.deepcopy(source), "demo/test-pack")
        source["checks"][0]["criteria"][0]["text"] = "A completely different claim."
        _, axes_b, _, _ = compile_pack(source, "demo/test-pack")
        self.assertNotEqual(json.dumps(axes_a), json.dumps(axes_b))
        # the OTHER criteria's wording is untouched -- editing one doesn't rewrite all
        self.assertEqual(axes_a["axes"][1], axes_b["axes"][1])

    def test_editing_a_criterion_label_changes_prompt_bytes(self):
        # judge-prompt.md's per-check summary line is built from each criterion's
        # own label (not its full text) -- see build_judge_prompt().
        source = minimal_source()
        _, _, prompt_a, _ = compile_pack(copy.deepcopy(source), "demo/test-pack")
        source["checks"][0]["criteria"][0]["label"] = "A wholly reworded label"
        _, _, prompt_b, _ = compile_pack(source, "demo/test-pack")
        self.assertNotEqual(prompt_a, prompt_b)

    def test_compiled_json_is_runnable_by_run_daily_shape(self):
        compiled, axes, prompt, presentation = compile_pack(minimal_source(), "demo/test-pack")
        # the fields scripts/run_daily.py reads directly
        self.assertIn("contract", compiled)
        self.assertIn("clauses", compiled)
        for clause in compiled["clauses"]:
            self.assertIn("id", clause)
            self.assertIn("tier", clause)
            self.assertIn("claim", clause)
        self.assertEqual(compiled["judge"]["prompt"], "demo/test-pack/judge-prompt.md")
        self.assertEqual(compiled["judge"]["axes"], "demo/test-pack/axes.json")
        self.assertIn("counterparty", compiled)

    def test_adding_a_criterion_adds_one_clause_and_one_axis(self):
        source = minimal_source()
        before, _, _, _ = compile_pack(copy.deepcopy(source), "demo/test-pack")
        source["checks"][0]["criteria"].append(_criterion("five"))
        after, axes, _, presentation = compile_pack(source, "demo/test-pack")
        self.assertEqual(len(after["clauses"]) - len(before["clauses"]), 1)
        self.assertIn("a.five", [c["id"] for c in after["clauses"]])
        self.assertIn("a.five", [a["id"] for a in axes["axes"]])
        self.assertIn("a.five", presentation["outcome-report/v1"]["reason_codes"])

    def test_removing_a_criterion_removes_one_clause(self):
        source = minimal_source()
        before, _, _, _ = compile_pack(copy.deepcopy(source), "demo/test-pack")
        del source["checks"][0]["criteria"][0]
        after, _, _, _ = compile_pack(source, "demo/test-pack")
        self.assertEqual(len(before["clauses"]) - len(after["clauses"]), 1)
        self.assertNotIn("a.one", [c["id"] for c in after["clauses"]])

    def test_reason_code_override_takes_precedence_over_the_label_fallback(self):
        source = minimal_source()
        source["reason_code_overrides"] = {"a.one": "STRUCTURED_CODE_1"}
        _, _, _, presentation = compile_pack(source, "demo/test-pack")
        codes = presentation["outcome-report/v1"]["reason_codes"]
        self.assertEqual(codes["a.one"], "STRUCTURED_CODE_1")
        self.assertEqual(codes["a.two"], "two")  # untouched: falls back to the criterion's own label

    def test_percentages_flow_through_and_no_money_field_exists(self):
        source = minimal_source()
        source["report"]["percentages"] = True
        _, _, _, presentation = compile_pack(source, "demo/test-pack")
        block = presentation["outcome-report/v1"]
        self.assertTrue(block["percentages"])
        self.assertEqual(set(block), {"enabled", "percentages", "terms", "reason_codes"})

    def test_every_rubric_switch_flip_changes_the_pack_source_digest(self):
        # The judge pin carries pack_source_digest (scripts/judge_pin.py), so a
        # switch flip or a claim_when_on edit moves the pin.
        source = minimal_source()
        source["switches"] = {"out_of_scope_verdict": False, "refusal_aware": False}
        source["checks"][0]["criteria"][0]["claim_switch"] = {"flag": "refusal_aware", "claim_when_on": "x or y."}
        base = build_compiled_json(source, "demo/test-pack")["pack_source_digest"]
        for mutate in (lambda s: s["switches"].update(out_of_scope_verdict=True),
                       lambda s: s["switches"].update(refusal_aware=True),
                       lambda s: s["checks"][0]["criteria"][0]["claim_switch"].update(claim_when_on="x or z.")):
            changed = copy.deepcopy(source)
            mutate(changed)
            self.assertNotEqual(build_compiled_json(changed, "demo/test-pack")["pack_source_digest"], base)


class WritePack(unittest.TestCase):
    def test_write_pack_produces_the_four_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "out"
            write_pack(minimal_source(), out, "demo/test-pack")
            for name in ("compiled.json", "axes.json", "judge-prompt.md", "presentation.json"):
                self.assertTrue((out / name).exists(), name)
            json.loads((out / "compiled.json").read_text())  # valid JSON
            json.loads((out / "axes.json").read_text())
            json.loads((out / "presentation.json").read_text())


class ResolveOutDir(unittest.TestCase):
    def test_accepts_demo_slash_name(self):
        out_abs, out_rel = resolve_out_dir(pathlib.Path("demo/some-pack"))
        self.assertEqual(out_rel, "demo/some-pack")
        self.assertEqual(out_abs, REPO_ROOT / "demo" / "some-pack")

    def test_rejects_wrong_depth(self):
        with self.assertRaises(ValueError):
            resolve_out_dir(pathlib.Path("demo/nested/too-deep"))

    def test_rejects_outside_repo_root(self):
        with self.assertRaises(ValueError):
            resolve_out_dir(pathlib.Path("/tmp/somewhere-else"))

    def test_rejects_wrong_top_level_dir(self):
        with self.assertRaises(ValueError):
            resolve_out_dir(pathlib.Path("packs/some-pack"))


class CliSmoke(unittest.TestCase):
    """Thin end-to-end checks of the CLI's exit codes and issues[] shape --
    everything else is exercised directly against the pure functions above."""

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "pack_compile.py"), *args],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )

    def test_validate_the_real_pack_source_is_valid(self):
        proc = self._run("validate", "packs/airline-support-outcomes/pack-source.yaml")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["valid"])

    def test_validate_an_invalid_source_exits_nonzero_with_issues(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write("pack_id: x\n")
            path = f.name
        try:
            proc = self._run("validate", path)
            self.assertEqual(proc.returncode, 1)
            result = json.loads(proc.stdout)
            self.assertFalse(result["valid"])
            self.assertTrue(result["issues"])
        finally:
            pathlib.Path(path).unlink()

    def test_compile_refuses_before_writing_anything_when_invalid(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write("pack_id: x\n")
            path = f.name
        try:
            proc = self._run("compile", path, "--out", "demo/should-not-exist")
            self.assertEqual(proc.returncode, 1)
            self.assertFalse((REPO_ROOT / "demo" / "should-not-exist").exists())
        finally:
            pathlib.Path(path).unlink()


if __name__ == "__main__":
    unittest.main()
