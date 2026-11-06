"""The pack JSON Schema (schemas/pack-source.schema.json) and `terms lint` on every
kind of pack (evidencebook-skills#126; Terms Pack Studio PRD v5 section 15 item 1):
the existing admission, live, report (after-the-fact), deal and conduct packs all
pass, and a pack that breaks the schema is refused by the field.

    python3 -m unittest discover -s tests -p 'test_*.py'
"""
import contextlib
import copy
import glob
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
import unittest.mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
for sub in ("scripts", "scripts/evaluators", "scripts/studio"):
    sys.path.insert(0, str(ROOT / sub))

import yaml  # noqa: E402

import admission_pack  # noqa: E402
import case_eval  # noqa: E402
import deal_pack  # noqa: E402
import live_pack  # noqa: E402
import pack_compile  # noqa: E402
import pack_schema  # noqa: E402
import terms  # noqa: E402

SAMPLES = {
    "admission": ROOT / "packs/admission-baseline/pack-source.yaml",
    "deal": ROOT / "packs/sticker-sale/pack-source.yaml",
    "conduct": ROOT / "tests/fixtures/terms-samples/conduct/pack-source.yaml",
    "live": ROOT / "tests/fixtures/live-pack/airline-engagement-1.0.1/pack-source.yaml",
    "after_the_fact": ROOT / "packs/airline-support-outcomes/pack-source.yaml",
}
EVERY_PACK = sorted(glob.glob(str(ROOT / "packs/*/pack-source.yaml"))
                    + glob.glob(str(ROOT / "tests/fixtures/**/pack-source.yaml"), recursive=True))


def load(path):
    return pack_compile.load_source(pathlib.Path(path).read_text())


def lint(path):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = terms.main(["lint", str(path)])
    return code, json.loads(buf.getvalue())


class EveryExistingPackPasses(unittest.TestCase):
    def test_each_kind_has_a_sample(self):
        for kind, path in SAMPLES.items():
            self.assertEqual(pack_schema.kind_of(load(path)), kind, path)

    def test_every_pack_in_the_repo_passes_the_schema_and_lint(self):
        self.assertGreaterEqual(len(EVERY_PACK), 16)
        for path in EVERY_PACK:
            with self.subTest(path=path):
                self.assertEqual(pack_schema.schema_issues(load(path)), [])
                code, res = lint(path)
                self.assertEqual((code, res["issues"]), (0, []))
                self.assertTrue(res["valid"])

    def test_lint_names_the_kind(self):
        for kind, path in SAMPLES.items():
            self.assertEqual(lint(path)[1]["kind"], kind)


class SchemaIsTheStructure(unittest.TestCase):
    """The schema's closed sets are the ones the validators hold; a change to
    one must be made to both."""

    def setUp(self):
        self.defs = pack_schema.schema()["$defs"]

    def test_scope_kinds(self):
        self.assertEqual(set(pack_schema.schema()["properties"]["scope"]["properties"]["kind"]["enum"]),
                         set(live_pack.SCOPE_KINDS))
        self.assertEqual(set(pack_schema.KINDS), set(live_pack.SCOPE_KINDS))

    def test_closed_member_sets(self):
        self.assertEqual(set(self.defs["deal"]["properties"]), deal_pack.TOP_KEYS)
        self.assertEqual(set(self.defs["deal"]["properties"]["rows"]["items"]["properties"]), deal_pack.ROW_KEYS)
        self.assertEqual(set(self.defs["admission"]["properties"]), admission_pack.ADMISSION_KEYS)
        self.assertEqual(set(self.defs["admission"]["properties"]["rows"]["items"]["properties"]), admission_pack.ROW_KEYS)
        self.assertEqual(set(self.defs["live"]["properties"]), live_pack.LIVE_KEYS)
        self.assertEqual(set(self.defs["live"]["properties"]["obligations"]["items"]["properties"]), live_pack.OBLIGATION_KEYS)
        self.assertEqual(set(self.defs["live"]["properties"]["outcomes"]["items"]["properties"]), live_pack.OUTCOME_KEYS)
        self.assertEqual(set(self.defs["after_the_fact"]["properties"]["report"]["properties"]),
                         set(pack_compile.REPORT_KEYS) | {"card"})
        self.assertEqual(set(self.defs["live"]["properties"]["outcomes"]["items"]["properties"]["clause"]["properties"]),
                         live_pack.CLAUSE_KEYS)

    def test_closed_value_sets(self):
        live = self.defs["live"]["properties"]
        self.assertEqual(live["obligations"]["items"]["properties"]["mode"]["enum"], list(live_pack.MODES))
        self.assertEqual(live["outcomes"]["items"]["properties"]["forward_verdict"]["enum"], list(live_pack.FORWARD_VERDICTS))
        adm = self.defs["admission"]["properties"]["rows"]["items"]["properties"]
        self.assertEqual(adm["source"]["enum"], list(admission_pack.SOURCES))
        self.assertEqual(adm["check"]["enum"], list(admission_pack.PREDICATES))
        crit = self.defs["after_the_fact"]["properties"]["checks"]["items"]["properties"]["criteria"]["items"]["properties"]
        self.assertEqual(set(crit["tier"]["enum"]), pack_compile.TIERS)


class BreakingTheSchema(unittest.TestCase):
    """Each edit of a sample pack is refused, naming the field."""

    def refused(self, kind, edit, *want):
        source = copy.deepcopy(load(SAMPLES[kind]))
        edit(source)
        issues = pack_schema.schema_issues(source)
        self.assertTrue(issues, "the edited pack was accepted")
        for w in want:
            self.assertTrue(any(w in i for i in issues), f"{w!r} not named in {issues}")
        return issues

    def test_deal(self):
        self.refused("deal", lambda s: s["rows"][0].update(tier="judged"), "rows[0].tier")
        self.refused("deal", lambda s: s["rows"][0].update(colour="red"), "rows[0].colour")
        self.refused("deal", lambda s: s.pop("title"), "title is required")
        self.refused("deal", lambda s: s["rows"][0].update(proves=["nonsense"]), "rows[0].proves[0]")

    def test_admission(self):
        self.refused("admission", lambda s: s["budget"].update(max_asks=-1), "budget.max_asks")
        self.refused("admission", lambda s: s["rows"][0].update(check="card.nope"), "rows[0].check")
        self.refused("admission", lambda s: s.update(missing="GO"), "missing")
        self.refused("admission", lambda s: s.update(extra=1), "extra")

    def test_live(self):
        self.refused("live", lambda s: s["obligations"][0].update(mode="guess"), "obligations[0].mode")
        self.refused("live", lambda s: s.update(holds_integration="bogus"), "holds_integration")
        self.refused("live", lambda s: s["outcomes"][0].update(forward_verdict="MAYBE"), "outcomes[0].forward_verdict")
        self.refused("live", lambda s: s.update(colour="red"), "colour")

    def test_the_judge_member_is_checked_by_the_schema(self):
        self.refused("after_the_fact", lambda s: s["judge"].update(model_id=[]), "judge.model_id")
        self.refused("after_the_fact", lambda s: s["judge"].update(min_confidence=2), "judge.min_confidence")
        self.refused("after_the_fact", lambda s: s["report"].update(template=[]), "report.template")
        self.refused("live", lambda s: s["profiles"].append({"profile_id": [], "counterparty_binding": {"direct": "x"}})
                     if "profiles" in s else s.update(profiles=[{"profile_id": [], "counterparty_binding": {"direct": "x"}}]),
                     "profiles[")

    def test_a_nested_choice_names_the_member_that_is_wrong(self):
        """A constraint, fold, instrument or on_fail is one of two forms; the error
        names the field of the form the member chose, never the other form's."""
        payments = ROOT / "tests/fixtures/live-pack/payments-safety-1.0.0/pack-source.yaml"
        SAMPLES["payments"] = payments
        self.addCleanup(SAMPLES.pop, "payments")
        want = (
            (lambda s: s["constraints"][0].pop("check"), ["constraints[0].check is required"]),
            (lambda s: s["constraints"][0].update(wicket_id=[]), ["constraints[0].wicket_id"]),
            (lambda s: s["constraints"][0].update(config="x"), ["constraints[0].config"]),
            (lambda s: s["folds"][0].update(file=[]), ["folds[0].file"]),
        )
        for edit, names in want:
            issues = self.refused("payments", edit, *names)
            self.assertFalse(any("is not a field" in i for i in issues), issues)
        issues = self.refused("admission", lambda s: s["rows"][0].update(on_fail={"cap": []}), "rows[0].on_fail.cap")
        self.assertEqual(len(issues), 1, issues)
        self.refused("admission", lambda s: s["rows"][0].update(on_fail="MAYBE"), "rows[0].on_fail 'MAYBE'")

    def test_report(self):
        self.refused("after_the_fact", lambda s: s["checks"][0]["criteria"][0].update(tier="guessed"),
                     "checks[0].criteria[0].tier")
        self.refused("after_the_fact", lambda s: s.pop("checks"), "checks is required")
        self.refused("after_the_fact", lambda s: s["checks"][0]["criteria"][0].update(recompute_eligible="no"),
                     "checks[0].criteria[0].recompute_eligible")

    def test_conduct(self):
        self.refused("conduct", lambda s: s["checks"][0]["criteria"][0].update(tier="guessed"),
                     "checks[0].criteria[0].tier")
        self.refused("conduct", lambda s: s["scope"].update(kind="conducts"), "scope.kind")
        self.refused("conduct", lambda s: s["scope"].update(audience="counterparty"), "scope.audience")

    def test_an_unknown_kind_names_the_kinds_once(self):
        source = load(SAMPLES["deal"])
        source["scope"]["kind"] = "receipt"
        self.assertEqual(pack_schema.schema_issues(source),
                         ["scope.kind 'receipt' must be one of ['live', 'after_the_fact', 'admission', 'deal', 'conduct']"])

    def test_not_a_mapping(self):
        self.assertEqual(pack_schema.schema_issues(["a"]), ["pack source must be a mapping"])
        self.assertIsNone(pack_schema.kind_of(["a"]))

    def test_a_scope_that_is_not_a_mapping_is_one_issue(self):
        for scope in ("x", [], None):
            source = load(SAMPLES["deal"])
            source["scope"] = scope
            self.assertEqual(pack_schema.schema_issues(source), ["scope must be a mapping with a kind"], scope)

    def test_an_unquoted_date_as_the_kind_is_refused_and_lint_prints_it(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        p = pathlib.Path(d.name) / "pack-source.yaml"
        p.write_text("scope:\n  kind: 2026-01-01\npack_id: x\n")
        code, res = lint(p)
        self.assertEqual((code, res["valid"], res["kind"]), (1, False, None))
        self.assertIn("scope.kind", res["issues"][0])


class LintCli(unittest.TestCase):
    def write(self, text):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        p = pathlib.Path(d.name) / "pack-source.yaml"
        p.write_text(text)
        return p

    def test_lint_refuses_a_schema_break_on_a_non_deal_pack_and_names_the_field(self):
        source = load(SAMPLES["conduct"])
        source["checks"][0]["criteria"][0]["tier"] = "guessed"
        code, res = lint(self.write(yaml.safe_dump(source)))
        self.assertEqual(code, 1)
        self.assertFalse(res["valid"])
        self.assertEqual(res["kind"], "conduct")
        self.assertTrue(any("checks[0].criteria[0].tier" in i for i in res["issues"]), res)

    def test_lint_runs_the_cross_field_rules_after_the_schema(self):
        source = load(SAMPLES["deal"])
        source["rows"][1]["statement"] = "Delivered promptly."
        code, res = lint(self.write(yaml.safe_dump(source)))
        self.assertEqual(code, 1)
        self.assertTrue(any("statement must say" in i for i in res["issues"]), res)

    def test_lint_reads_an_unreadable_file(self):
        code, res = lint(self.write("a: [unclosed"))
        self.assertEqual((code, res["valid"]), (1, False))
        self.assertIn("cannot read", res["issues"][0])

    def test_a_missing_file(self):
        code, res = lint("/nonexistent/pack-source.yaml")
        self.assertEqual((code, res["valid"]), (1, False))


def run_test(path, *flags):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = terms.main(["test", str(path), *flags])
    return code, json.loads(buf.getvalue())


FUZZED = [str(p) for p in SAMPLES.values()] + sorted(glob.glob(str(ROOT / "tests/fixtures/terms-samples/*/pack-source.yaml")))


def _leaves(o, path=()):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from _leaves(v, path + (k,))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _leaves(v, path + (i,))
    yield path


class LintNeverCrashes(unittest.TestCase):
    """The class of defect behind a lint that dies on a malformed member instead of
    naming it: every member of every pack in the repo, replaced by a value of the
    wrong type, must come back as issues (or as a valid pack), never as an exception."""

    BAD = ([], {}, 7, None, "x")

    def test_a_wrong_typed_member_is_reported_not_raised(self):
        for path in FUZZED:
            base = load(path)
            for where in _leaves(base):
                if not where:
                    continue
                for bad in self.BAD:
                    source = copy.deepcopy(base)
                    node = source
                    for p in where[:-1]:
                        node = node[p]
                    node[where[-1]] = bad
                    try:
                        if not pack_schema.schema_issues(source):
                            pack_compile.validate_source(source, pathlib.Path(path).parent)
                    except Exception as e:  # noqa: BLE001
                        self.fail(f"{path}: {'.'.join(map(str, where))} = {bad!r} raised {type(e).__name__}: {e}")


class TestOnEveryKind(unittest.TestCase):
    """`terms test` takes a pack of any kind and its met / not_met cases for every row.
    A deal pack and an evaluator pack (inference-deals) are run in process; an admission
    pack by a capsule-engine binary named with --engine, a live pack by the Python CLI named
    with --live-engine; judged packs have no runner yet. A case that cannot run is reported not evaluated, never passed."""

    SAMPLES = {k: ROOT / f"tests/fixtures/terms-samples/{k}/pack-source.yaml"
               for k in ("admission", "live", "report", "conduct")}

    def test_deal_runs_both_cases_of_every_row(self):
        code, res = run_test(SAMPLES["deal"])
        self.assertEqual((code, res["passed"], res["kind"]), (0, True, "deal"))
        self.assertTrue(all(r["evaluated"] and (r["met_case"], r["miss_case"]) == ("met", "not_met") for r in res["rows"]))

    def test_each_other_kind_checks_its_fixtures_and_says_nothing_was_run(self):
        for name, path in self.SAMPLES.items():
            with self.subTest(kind=name), unittest.mock.patch.dict("os.environ", clear=True):
                code, res = run_test(path)
                self.assertEqual(code, 3, res)
                self.assertIsNone(res["passed"])
                self.assertTrue(res["fixtures_valid"])
                self.assertEqual((res["evaluated"], res["not_evaluated"]), (0, res["cases"]))
                self.assertTrue(all(not r["evaluated"] and r["reason"] for r in res["rows"]))

    def test_a_judged_pack_is_not_run_with_or_without_a_key(self):
        for name in ("report", "conduct"):
            for env in ({}, {"TYPESAFE_API_KEY": "x"}):
                with self.subTest(kind=name, key=bool(env)), unittest.mock.patch.dict("os.environ", env, clear=True):
                    code, res = run_test(self.SAMPLES[name])
                    self.assertEqual((code, res["passed"], res["evaluated"]), (3, None, 0))
                    self.assertIn("waits for the owner's go", res["rows"][0]["reason"])

    def test_live_without_an_engine_says_how_to_name_one(self):
        with unittest.mock.patch.dict("os.environ", clear=True):
            _, res = run_test(self.SAMPLES["live"])
        self.assertIn("--live-engine", res["rows"][0]["reason"])

    def test_the_evaluator_pack_runs_both_cases_of_every_row(self):
        code, res = run_test(ROOT / "packs/inference-deals/pack-source.yaml")
        self.assertEqual((code, res["passed"], res["evaluated"], res["not_evaluated"]), (0, True, 6, 0))
        for r in res["rows"]:
            self.assertEqual((r["met_case"], r["miss_case"]), ("met", "not_met"))
            self.assertEqual(r["decided_by"]["name"], "inference_deals")
            self.assertRegex(r["decided_by"]["sha256"], "^[0-9a-f]{64}$")

    def test_the_evaluator_fixture_is_what_its_generator_writes(self):
        import subprocess
        gen = ROOT / "packs/inference-deals/fixtures/generate.py"
        made = subprocess.run([sys.executable, str(gen)], capture_output=True, text=True, check=True).stdout
        self.assertEqual(made, (ROOT / "packs/inference-deals/fixtures/two-case.json").read_text())

    def test_an_evaluator_case_the_evaluator_decides_otherwise_fails(self):
        dst = self.copy_evaluator_pack()
        f = dst / "fixtures/two-case.json"
        doc = json.loads(f.read_text())
        row = "come_through.paid_as_agreed"
        met, miss = [c for c in doc["cases"] if c["row"] == row]
        met["input"], miss["input"] = miss["input"], met["input"]
        f.write_text(json.dumps(doc))
        code, res = run_test(dst / "pack-source.yaml")
        self.assertEqual((code, res["passed"]), (1, False))
        bad = [r for r in res["rows"] if r["row"] == row][0]
        self.assertEqual((bad["evaluated"], bad["passed"], bad["met_case"], bad["miss_case"]),
                         (True, False, "not_met", "met"))

    def test_an_evaluator_case_that_cannot_be_built_is_not_evaluated(self):
        dst = self.copy_evaluator_pack()
        f = dst / "fixtures/two-case.json"
        doc = json.loads(f.read_text())
        doc["cases"][0]["input"] = {"records": [], "date": "2026-11-01"}
        f.write_text(json.dumps(doc))
        code, res = run_test(dst / "pack-source.yaml")
        self.assertEqual((code, res["passed"], res["evaluated"], res["not_evaluated"]), (3, None, 4, 2), res)
        self.assertFalse(res["rows"][0]["evaluated"])
        self.assertIn("could not be built", res["rows"][0]["reason"])

    def test_a_malformed_record_is_not_evaluated_and_does_not_crash(self):
        dst = self.copy_evaluator_pack()
        f = dst / "fixtures/two-case.json"
        doc = json.loads(f.read_text())
        doc["cases"][0]["input"]["records"][0]["model_attestation"] = "x"
        f.write_text(json.dumps(doc))
        code, res = run_test(dst / "pack-source.yaml")
        self.assertEqual((code, res["passed"]), (3, None), res)
        self.assertFalse(res["rows"][0]["evaluated"])

    def test_a_case_with_two_deals_is_not_evaluated(self):
        dst = self.copy_evaluator_pack()
        f = dst / "fixtures/two-case.json"
        doc = json.loads(f.read_text())
        met = [c for c in doc["cases"] if c["row"] == "come_through.paid_as_agreed"]
        met[0]["input"]["records"] = met[0]["input"]["records"] + met[1]["input"]["records"]
        f.write_text(json.dumps(doc))
        code, res = run_test(dst / "pack-source.yaml")
        self.assertIsNone(res["passed"])
        row = [r for r in res["rows"] if r["row"] == "come_through.paid_as_agreed"][0]
        self.assertFalse(row["evaluated"])
        self.assertIn("exactly one counted deal", row["reason"])

    def test_the_evaluator_runs_the_source_not_a_compiled_file(self):
        dst = self.copy_evaluator_pack()
        shutil_rmtree(dst / "compiled")
        code, res = run_test(dst / "pack-source.yaml")
        self.assertEqual((code, res["passed"], res["evaluated"]), (0, True, 6), res)

    def copy_evaluator_pack(self):
        import shutil
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        dst = pathlib.Path(d.name) / "inference-deals"
        shutil.copytree(ROOT / "packs/inference-deals", dst)
        return dst

    def copy_sample(self, name):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        import shutil
        dst = pathlib.Path(d.name) / "pack"
        shutil.copytree(self.SAMPLES[name].parent, dst)
        return dst

    def test_a_row_without_a_not_met_case_is_refused(self):
        dst = self.copy_sample("conduct")
        f = dst / "fixtures/two-case.json"
        doc = json.loads(f.read_text())
        doc["cases"] = [c for c in doc["cases"] if c["case"] == "met"]
        f.write_text(json.dumps(doc))
        code, res = run_test(dst / "pack-source.yaml")
        self.assertEqual((code, res["passed"]), (1, False))
        self.assertTrue(any("has no not_met case" in i for i in res["issues"]), res)

    def test_a_case_for_a_row_the_pack_lacks_is_refused(self):
        dst = self.copy_sample("admission")
        f = dst / "fixtures/two-case.json"
        doc = json.loads(f.read_text())
        doc["cases"].append({"row": "ghost", "case": "met", "input": {"a": 1}})
        f.write_text(json.dumps(doc))
        code, res = run_test(dst / "pack-source.yaml")
        self.assertEqual(code, 1)
        self.assertTrue(any("'ghost'" in i for i in res["issues"]), res)

    def test_a_missing_fixture_file_is_refused(self):
        dst = self.copy_sample("report")
        (dst / "fixtures/two-case.json").unlink()
        code, res = run_test(dst / "pack-source.yaml")
        self.assertEqual(code, 1)
        self.assertTrue(any("is missing" in i for i in res["issues"]), res)

    def test_a_pack_that_breaks_the_schema_is_not_tested(self):
        dst = self.copy_sample("live")
        p = dst / "pack-source.yaml"
        p.write_text(p.read_text().replace("holds_integration: stubbed", "holds_integration: bogus"))
        code, res = run_test(p)
        self.assertEqual((code, res["passed"]), (1, False))
        self.assertTrue(any("holds_integration" in i for i in res["issues"]), res)

    def test_the_same_input_in_both_cases_is_refused(self):
        dst = self.copy_sample("report")
        f = dst / "fixtures/two-case.json"
        doc = json.loads(f.read_text())
        for c in doc["cases"]:
            c["input"] = doc["cases"][0]["input"]
        f.write_text(json.dumps(doc))
        code, res = run_test(dst / "pack-source.yaml")
        self.assertEqual(code, 1)
        self.assertTrue(any("same input" in i for i in res["issues"]), res)

    def test_sample_fixtures_name_their_own_pack(self):
        for name, path in self.SAMPLES.items():
            doc = json.loads((path.parent / "fixtures/two-case.json").read_text())
            self.assertEqual(doc["pack"], load(path)["pack_id"], name)


class ConductIsAScopeKind(unittest.TestCase):
    def test_a_conduct_pack_validates_and_compiles_like_a_report_pack(self):
        source = load(SAMPLES["conduct"])
        self.assertEqual(live_pack.scope_kind(source), "conduct")
        self.assertEqual(pack_compile.validate_source(source), [])
        self.assertEqual(pack_compile.compile_pack(source, "x/y")[0]["contract_ref"], "asg/conduct-sample@0.1.0")

    def test_the_source_digest_names_the_kind(self):
        a = load(SAMPLES["conduct"])
        b = copy.deepcopy(a)
        b["scope"]["kind"] = "after_the_fact"
        self.assertNotEqual(pack_compile.source_digest(a), pack_compile.source_digest(b))


def shutil_rmtree(path):
    import shutil
    shutil.rmtree(path)


class AdmissionEngine(unittest.TestCase):
    """`terms test` on an admission pack, with a capsule-engine named by --engine. The fake
    engine below checks the plumbing (what is run, what is read back, what is refused); the
    real binary is exercised when CAPSULE_ENGINE names one."""
    SAMPLE = ROOT / "tests/fixtures/terms-samples/admission/pack-source.yaml"

    def fake(self, body):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        f = pathlib.Path(d.name) / "capsule-engine"
        f.write_text("#!/usr/bin/env python3\nimport json, sys\n" + body)
        f.chmod(0o755)
        return str(f)

    SHA = "f5a84681835498907da70615701cca7b08edd465"

    def setUp(self):
        self.info = unittest.mock.patch.object(
            case_eval, "build_info", side_effect=lambda p: f"{p}: go1\n\tbuild\tvcs.revision={self.SHA}\n")
        self.info.start()
        self.addCleanup(self.info.stop)

    # An engine that fails the `attestation` row when the input says the attestation is invalid.
    ENGINE = """
a = sys.argv
inp = json.load(open(a[a.index("--input") + 1]))
bad = inp.get("platform", {}).get("release_attestation") == "invalid"
denied = inp.get("operator", {}).get("deny_listed") is True
print(json.dumps({"verdict": "NO", "rows": [
    {"row": "attestation", "result": "fail" if bad else "pass", "effect": "NO"},
    {"row": "deny-list", "result": "fail" if denied else "pass", "effect": "NO"}]}))
"""

    def test_cases_are_decided_by_the_engine_and_it_is_named(self):
        engine = self.fake(self.ENGINE)
        code, res = run_test(self.SAMPLE, "--engine", engine)
        self.assertEqual((code, res["passed"], res["evaluated"], res["not_evaluated"]), (0, True, 4, 0), res)
        self.assertEqual(res["rows"][0]["decided_by"]["name"], "capsule-engine")
        self.assertEqual(res["rows"][0]["decided_by"]["path"], str(pathlib.Path(engine).resolve()))
        self.assertRegex(res["rows"][0]["pack_digest"], "^[0-9a-f]{64}$")

    def test_a_row_the_engine_decides_otherwise_fails(self):
        engine = self.fake(self.ENGINE.replace('"pass"', '"fail"', 1))
        code, res = run_test(self.SAMPLE, "--engine", engine)
        self.assertEqual((code, res["passed"]), (1, False), res)

    def test_a_refusing_engine_leaves_the_row_unrun(self):
        engine = self.fake("sys.stderr.write('bad pack'); sys.exit(2)")
        code, res = run_test(self.SAMPLE, "--engine", engine)
        self.assertEqual((code, res["passed"], res["evaluated"]), (3, None, 0), res)
        self.assertIn("bad pack", res["rows"][0]["reason"])

    def test_an_engine_that_cannot_start_leaves_the_rows_unrun(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        f = pathlib.Path(d.name) / "capsule-engine"
        f.write_text("#!/nonexistent/interpreter\n")
        f.chmod(0o755)
        code, res = run_test(self.SAMPLE, "--engine", str(f))
        self.assertEqual((code, res["passed"], res["evaluated"]), (3, None, 0), res)
        self.assertIn("could not decide", res["rows"][0]["reason"])

    def test_a_missing_engine_leaves_the_rows_unrun(self):
        code, res = run_test(self.SAMPLE, "--engine", "/nonexistent/capsule-engine")
        self.assertEqual((code, res["passed"], res["evaluated"]), (3, None, 0), res)

    def test_the_build_commit_is_reported_and_a_matching_pin_runs(self):
        engine = self.fake(self.ENGINE)
        code, res = run_test(self.SAMPLE, "--engine", engine, "--engine-commit", self.SHA[:8])
        self.assertEqual((code, res["passed"]), (0, True), res)
        self.assertEqual(res["rows"][0]["decided_by"]["commit"], self.SHA)

    def test_an_engine_with_no_known_build_revision_is_not_used(self):
        engine = self.fake(self.ENGINE)
        with unittest.mock.patch.object(case_eval, "build_info", return_value=""):
            code, res = run_test(self.SAMPLE, "--engine", engine)
        self.assertEqual((code, res["passed"], res["evaluated"]), (3, None, 0), res)
        self.assertIn("build revision is unknown", res["rows"][0]["reason"])

    def test_a_locally_modified_build_does_not_satisfy_a_pin(self):
        engine = self.fake(self.ENGINE)
        info = f"build\tvcs.revision={self.SHA}\nbuild\tvcs.modified=true\n"
        with unittest.mock.patch.object(case_eval, "build_info", return_value=info):
            code, res = run_test(self.SAMPLE, "--engine", engine, "--engine-commit", self.SHA)
        self.assertEqual((code, res["passed"], res["evaluated"]), (3, None, 0), res)
        self.assertIn("local changes", res["rows"][0]["reason"])

    def test_a_bare_engine_name_runs_the_file_it_identifies(self):
        engine = self.fake(self.ENGINE)
        path = str(pathlib.Path(engine).parent)
        with unittest.mock.patch.dict("os.environ", {"PATH": path + os.pathsep + os.environ["PATH"]}):
            code, res = run_test(self.SAMPLE, "--engine", "capsule-engine")
        self.assertEqual((code, res["passed"]), (0, True), res)
        self.assertEqual(res["rows"][0]["decided_by"]["path"], str(pathlib.Path(engine).resolve()))

    def test_a_commit_prefix_under_seven_characters_is_refused_before_the_engine_runs(self):
        marker = pathlib.Path(tempfile.mkdtemp()) / "ran"
        self.addCleanup(lambda: marker.unlink(missing_ok=True))
        engine = self.fake(f"open({str(marker)!r}, 'w').close()\n" + self.ENGINE)
        code, res = run_test(self.SAMPLE, "--engine", engine, "--engine-commit", "abc123")
        self.assertEqual((code, res["passed"]), (1, False), res)
        self.assertIn("at least 7", res["issues"][0])
        self.assertFalse(marker.exists())

    def test_an_engine_not_built_from_the_pinned_commit_is_not_used(self):
        engine = self.fake(self.ENGINE)
        code, res = run_test(self.SAMPLE, "--engine", engine, "--engine-commit", "abc1234")
        self.assertEqual((code, res["passed"], res["evaluated"]), (3, None, 0), res)
        self.assertIn("pinned abc1234", res["rows"][0]["reason"])


class RealAdmissionEngine(unittest.TestCase):
    """The real capsule-engine, with nothing mocked: CI builds it at CAPSULE_ENGINE_REF."""
    SAMPLE = AdmissionEngine.SAMPLE

    @unittest.skipUnless(os.environ.get("CAPSULE_ENGINE"), "CAPSULE_ENGINE names no capsule-engine build")
    def test_the_real_engine_decides_the_sample_pack_and_names_its_commit(self):
        code, res = run_test(self.SAMPLE)
        self.assertEqual((code, res["passed"], res["evaluated"]), (0, True, 4), res)
        ref = os.environ.get("CAPSULE_ENGINE_REF")
        for r in res["rows"]:
            self.assertRegex(r["decided_by"]["commit"], "^[0-9a-f]{40}$")
            if ref:
                self.assertEqual(r["decided_by"]["commit"], ref)


GIT = {"url": "https://example/capsule-engine", "vcs_info": {"vcs": "git", "commit_id": "05185b02f121227d1e0cd30274396f7e826ec2d4"}}


class LiveEngine(unittest.TestCase):
    """`terms test` on a live pack, with the Python capsule-engine CLI named by --live-engine. The
    fake CLI below checks the plumbing; its interpreter answers the identity query the way a git
    install's metadata does. The real CLI runs when CAPSULE_LIVE_ENGINE names one."""
    SAMPLE = ROOT / "tests/fixtures/terms-samples/live/pack-source.yaml"
    SHA = "05185b02f121227d1e0cd30274396f7e826ec2d4"

    def fake(self, body, identity=None):  # noqa: D417
        """A CLI script under this interpreter, whose install record (the identity query) is `identity`."""
        identity = {"version": "0.3.0", "direct_url": GIT} if identity is None else identity
        info = {"version": identity["version"], "direct_url": identity["direct_url"]}
        patch = unittest.mock.patch.object(case_eval, "LIVE_IDENTITY", f"print({json.dumps(json.dumps(info))})")
        patch.start()
        self.addCleanup(patch.stop)
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        f = pathlib.Path(d.name) / "capsule-engine"
        f.write_text(f"#!{sys.executable}\nimport json, sys\n" + body)
        f.chmod(0o755)
        return str(f)

    # An engine that reports the row not met when the input holds two actions.
    ENGINE = """
a = sys.argv
doc = json.load(open(a[a.index("--input") + 1]))
res = "not_met" if len(doc["actions"]) > 1 else "met"
print(json.dumps({"engine": {"name": "capsule-engine", "version": "0.3.0"}, "pack": {"id": "x", "digest": "d" * 64},
                  "verdict": "NO", "rows": [{"row": "no-duplicate-dispatch", "result": res, "reason": "r"}]}))
"""

    def test_a_commit_prefix_under_seven_characters_is_refused_before_the_engine_runs(self):
        marker = pathlib.Path(tempfile.mkdtemp()) / "ran"
        self.addCleanup(lambda: marker.unlink(missing_ok=True))
        engine = self.fake(f"open({str(marker)!r}, 'w').close()\n" + self.ENGINE)
        code, res = run_test(self.SAMPLE, "--live-engine", engine, "--engine-commit", self.SHA[:6])
        self.assertEqual((code, res["passed"]), (1, False), res)
        self.assertIn("at least 7", res["issues"][0])
        self.assertFalse(marker.exists())

    def test_cases_are_decided_by_the_engine_and_its_commit_is_named(self):
        code, res = run_test(self.SAMPLE, "--live-engine", self.fake(self.ENGINE), "--engine-commit", self.SHA[:7])
        self.assertEqual((code, res["passed"], res["evaluated"], res["not_evaluated"]), (0, True, 2, 0), res)
        by = res["rows"][0]["decided_by"]
        self.assertEqual((by["name"], by["version"], by["commit"]), ("capsule-engine", "0.3.0", self.SHA))
        self.assertEqual(res["rows"][0]["pack_digest"], "d" * 64)

    def test_a_row_the_engine_decides_otherwise_fails(self):
        code, res = run_test(self.SAMPLE, "--live-engine", self.fake(self.ENGINE.replace('"not_met"', '"met"')))
        self.assertEqual((code, res["passed"]), (1, False), res)

    def test_a_different_pin_leaves_the_rows_unrun(self):
        code, res = run_test(self.SAMPLE, "--live-engine", self.fake(self.ENGINE), "--engine-commit", "deadbee")
        self.assertEqual((code, res["passed"], res["evaluated"]), (3, None, 0), res)
        self.assertIn("not the pinned deadbee", res["rows"][0]["reason"])

    def test_a_pin_needs_a_recorded_commit(self):
        engine = self.fake(self.ENGINE, {"version": "0.4.0", "direct_url": None})
        _, res = run_test(self.SAMPLE, "--live-engine", engine, "--engine-commit", "05185b0")
        self.assertIsNone(res["passed"])
        _, res = run_test(self.SAMPLE, "--live-engine", engine)
        self.assertEqual((res["passed"], res["rows"][0]["decided_by"]["version"]), (True, "0.4.0"), res)

    def test_an_install_from_a_directory_an_archive_or_a_wheel_is_not_used(self):
        for record in ({"url": "file:///x", "dir_info": {"editable": True}}, {"url": "file:///x", "dir_info": {}},
                       {"url": "file:///x.whl", "archive_info": {"hash": "sha256=1"}}, {"url": "file:///x", "vcs_info": {}}):
            with self.subTest(record=record):
                _, res = run_test(self.SAMPLE, "--live-engine", self.fake(self.ENGINE, {"version": "0.3.0", "direct_url": record}))
                self.assertEqual((res["passed"], res["evaluated"]), (None, 0), res)
                self.assertIn("directory or an archive", res["rows"][0]["reason"])

    def test_the_engine_runs_isolated_under_the_identified_interpreter(self):
        # A PYTHONPATH that shadows the installed package must not reach the engine that decides.
        engine = self.fake("if not sys.flags.isolated:\n    sys.exit(3)\n" + self.ENGINE)
        with unittest.mock.patch.dict("os.environ", {"PYTHONPATH": "/nonexistent"}):
            _, res = run_test(self.SAMPLE, "--live-engine", engine)
        self.assertEqual(res["passed"], True, res)
        self.assertEqual(res["rows"][0]["decided_by"]["python"], sys.executable)

    def test_a_refusing_engine_leaves_the_rows_unrun(self):
        engine = self.fake("sys.stderr.write('pack failed to load'); sys.exit(2)")
        code, res = run_test(self.SAMPLE, "--live-engine", engine)
        self.assertEqual((code, res["passed"], res["evaluated"]), (3, None, 0), res)
        self.assertIn("pack failed to load", res["rows"][0]["reason"])

    def test_a_row_the_engine_cannot_evaluate_is_never_passed(self):
        engine = self.fake(self.ENGINE.replace('"not_met" if len(doc["actions"]) > 1 else "met"', '"not_evaluable"'))
        code, res = run_test(self.SAMPLE, "--live-engine", engine)
        self.assertEqual((code, res["passed"], res["evaluated"]), (3, None, 0), res)
        self.assertIn("not_evaluable", res["rows"][0]["reason"])

    def test_output_that_is_not_the_verbs_is_unrun(self):
        for body in ("print('hello')", "print(json.dumps({'rows': []}))"):
            with self.subTest(body=body):
                _, res = run_test(self.SAMPLE, "--live-engine", self.fake(body))
                self.assertEqual((res["passed"], res["evaluated"]), (None, 0), res)

    def test_a_missing_or_non_python_engine_leaves_the_rows_unrun(self):
        _, res = run_test(self.SAMPLE, "--live-engine", "/nonexistent/capsule-engine")
        self.assertEqual((res["passed"], res["evaluated"]), (None, 0), res)
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        f = pathlib.Path(d.name) / "capsule-engine"
        f.write_bytes(b"\x7fELF binary")
        f.chmod(0o755)
        _, res = run_test(self.SAMPLE, "--live-engine", str(f))
        self.assertEqual((res["passed"], res["evaluated"]), (None, 0), res)
        self.assertIn("shebang", res["rows"][0]["reason"])
        f.write_text("#!/bin/sh\nexec python \"$@\"\n")
        _, res = run_test(self.SAMPLE, "--live-engine", str(f))
        self.assertEqual((res["passed"], res["evaluated"]), (None, 0), res)
        self.assertIn("shebang", res["rows"][0]["reason"])

    def test_the_engine_may_be_named_by_the_environment(self):
        with unittest.mock.patch.dict("os.environ", {"CAPSULE_LIVE_ENGINE": self.fake(self.ENGINE)}, clear=True):
            _, res = run_test(self.SAMPLE)
        self.assertEqual(res["passed"], True, res)

    def test_a_pack_not_named_pack_source_is_unrun(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        import shutil
        dst = pathlib.Path(d.name) / "pack"
        shutil.copytree(self.SAMPLE.parent, dst)
        (dst / "pack-source.yaml").rename(dst / "other.yaml")
        _, res = run_test(dst / "other.yaml", "--live-engine", self.fake(self.ENGINE))
        self.assertEqual((res["passed"], res["evaluated"]), (None, 0), res)


class RealLiveEngine(unittest.TestCase):
    """The real Python capsule-engine, with nothing mocked: CI installs it at CAPSULE_ENGINE_PY_REF."""

    @unittest.skipUnless(os.environ.get("CAPSULE_LIVE_ENGINE"), "CAPSULE_LIVE_ENGINE names no capsule-engine")
    def test_the_real_engine_decides_the_sample_pack_and_names_its_commit(self):
        code, res = run_test(LiveEngine.SAMPLE)
        self.assertEqual((code, res["passed"], res["evaluated"]), (0, True, 2), res)
        ref = os.environ.get("CAPSULE_ENGINE_PY_REF")
        by = res["rows"][0]["decided_by"]
        self.assertRegex(by["version"], r"^\d+\.\d+\.\d+")
        if ref:
            self.assertEqual(by["commit"], ref)
            code, res = run_test(LiveEngine.SAMPLE, "--engine-commit", ref[:7])
            self.assertEqual(res["passed"], True, res)
            _, res = run_test(LiveEngine.SAMPLE, "--engine-commit", "deadbee")
            self.assertIsNone(res["passed"])


if __name__ == "__main__":
    unittest.main()
