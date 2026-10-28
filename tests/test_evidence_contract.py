"""Unit tests for scripts/evidence_contract.py: a pack source or a report spec
compiles to an Evidence Contract v0 document, byte-stably; every published
contract under contracts/ is what its source compiles to today (published
contracts are immutable); and the contract_ref and requirement ids are the
ones the Results here cite.

Schema validity is checked against the vendored EC v0 schema with jsonschema,
and with `capsulectl contract validate` when capsulectl is available
(CAPSULECTL, or on PATH); tests/fresh_env.sh always builds one.
"""
import copy
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import yaml  # noqa: E402

import evidence_contract as ec  # noqa: E402
import pack_compile  # noqa: E402
import report_spec  # noqa: E402
from test_pack_compile import _criterion, minimal_source  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
EU_SOURCE = REPO_ROOT / "packs/eu-ai-act-obligations/pack-source.yaml"
# The golden: the EU pack as it is published here first. A later version is a
# new file beside it; this one never changes.
EU_PUBLISHED = REPO_ROOT / "contracts/eu-ai-act-obligations/0.2.1.json"
SCHEMA = REPO_ROOT / "tests/fixtures/capsule-engine/evidence-contract-v0.json"
# The EC v0 schema agent-action-capsule's interop profile pins (its Dependency
# boundary, row EC): capsule-engine's file at fd43d43, by SHA-256.
SCHEMA_SHA256 = "6d10d5eb97e15421db0ab922b5f6d1f0a2e9f453fb64e52fb45306ba029ad480"
SOURCES = sorted(REPO_ROOT.glob("packs/*/pack-source.yaml")) + sorted(REPO_ROOT.glob("scripts/specs/*.yaml"))


def load_pack(path):
    return pack_compile._strip_strings(yaml.safe_load(path.read_text()))


def capsulectl():
    return os.environ.get("CAPSULECTL") or shutil.which("capsulectl")


class EUContract(unittest.TestCase):
    def test_golden_the_eu_pack_compiles_to_its_published_contract(self):
        # Compared at the pack's current version, so a version bump that
        # publishes a new file keeps this test meaningful.
        contract = ec.from_pack(load_pack(EU_SOURCE))
        path = ec.published_path(contract)
        self.assertTrue(path.exists(), f"{ec.contract_ref(contract)} is not published: run evidence_contract.py publish")
        self.assertEqual(ec.to_bytes(contract), path.read_bytes())

    def test_the_first_published_eu_contract_is_kept(self):
        doc = json.loads(EU_PUBLISHED.read_text())
        self.assertEqual(ec.contract_ref(doc), "eu-ai-act-obligations@0.2.1")
        self.assertEqual(len(doc["requirements"]), 12)

    def test_recompiling_is_byte_stable(self):
        a = ec.to_bytes(ec.from_pack(load_pack(EU_SOURCE)))
        b = ec.to_bytes(ec.from_pack(load_pack(EU_SOURCE)))
        self.assertEqual(a, b)
        out = subprocess.run([sys.executable, "scripts/evidence_contract.py", "compile", str(EU_SOURCE)],
                             cwd=REPO_ROOT, capture_output=True, check=True).stdout
        self.assertEqual(out, a)

    def test_ref_and_ids_are_what_compiled_json_and_results_cite(self):
        source = load_pack(EU_SOURCE)
        contract = ec.from_pack(source)
        compiled = pack_compile.build_compiled_json(source, "demo/eu-ai-act-obligations")
        self.assertEqual(ec.contract_ref(contract), compiled["contract_ref"])
        self.assertEqual([r["id"] for r in contract["requirements"]], [c["id"] for c in compiled["clauses"]])
        committed = json.loads((REPO_ROOT / "demo/eu-ai-act-obligations/compiled.json").read_text())
        self.assertEqual(committed["contract_ref"], ec.contract_ref(contract))
        self.assertEqual([c["id"] for c in committed["clauses"]], [r["id"] for r in contract["requirements"]])

    def test_every_eu_row_is_an_obligation_citing_its_article(self):
        source = load_pack(EU_SOURCE)
        articles = {c["id"]: c["article"] for c in source["checks"]}
        for req in ec.from_pack(source)["requirements"]:
            self.assertEqual(req["profile"], "obligation")
            self.assertEqual(req["clause"], {"instrument": source["regulation"],
                                             "article": articles[req["id"].split(".")[0]]})

    def test_judged_and_recomputed_rows(self):
        reqs = {r["id"]: r for r in ec.from_pack(load_pack(EU_SOURCE))["requirements"]}
        judged = reqs["art5.no_manipulation_or_deception"]
        self.assertEqual((judged["mode"], judged["forward_verdict"], judged["backward_verdict"]),
                         ("judged", "UNAVAILABLE-MODEL-REQUIRED", "MODEL-ASSISTED"))
        self.assertEqual(judged["statement"], "No manipulative or deceptive technique")
        self.assertIn("Question: First decide whether the agent tried to move the customer", judged["evidence_rule"])
        self.assertIn("out_of_scope when", judged["evidence_rule"])
        recomputed = reqs["art50.disclosure_before_first_turn"]
        self.assertEqual((recomputed["forward_verdict"], recomputed["backward_verdict"]),
                         ("UNAVAILABLE-STATE-REQUIRED", "DETERMINISTIC"))
        self.assertNotIn("mode", recomputed)
        self.assertIn("Recomputed by fold art50.disclosure_before_first_turn.", recomputed["evidence_rule"])
        # A checker may not answer out_of_scope (run_daily.recomputed_answer), so
        # a recomputed row never lists it, even with the pack's switch on.
        self.assertNotIn("out_of_scope", recomputed["evidence_rule"])
        self.assertIn("art14e.handoff_request_truncated",
                      reqs["art14e.stop_or_handoff_on_request"]["evidence_rule"])
        # epistemic_type filters which evidence counts (interop profile §11.3.7);
        # the pack names none, so the contract states none.
        self.assertFalse(any("epistemic_type" in r for r in reqs.values()))

    def test_the_evidence_scope_is_what_the_judge_reads(self):
        reqs = {r["id"]: r for r in ec.from_pack(load_pack(EU_SOURCE))["requirements"]}
        self.assertIn("the airline policy (`airline-data/policy.md`, supplied to the judge as text)",
                      reqs["art26.consequential_actions_vs_instructions"]["evidence_rule"])

    def test_the_evidence_scope_speaks_of_the_judge_not_to_it(self):
        text = EU_PUBLISHED.read_text()
        self.assertNotIn("passed to you", text)
        self.assertIn("supplied to the judge as text", text)
        # The judge prompt keeps its own wording; the contract only restates it.
        self.assertTrue(any(ec._SECOND_PERSON[0] in e for e in pack_compile._LEGACY_JUDGE_EVIDENCE))

    def test_presentation_wording_is_not_in_the_contract(self):
        text = EU_PUBLISHED.read_text()
        source = load_pack(EU_SOURCE)
        for check in source["checks"]:
            self.assertNotIn(check["plain"], text)
            for crit in check["criteria"]:
                if crit.get("finding"):
                    self.assertNotIn(crit["finding"]["recommendation"], text)
        self.assertNotIn("Sample placeholder", text)


class FromPack(unittest.TestCase):
    def test_outcome_pack_rows_are_native_outcomes(self):
        contract = ec.from_pack(minimal_source())
        self.assertEqual((contract["id"], contract["version"]), ("test-pack", "1.0.0"))
        self.assertEqual([r["id"] for r in contract["requirements"]], ["a.one", "a.two", "b.three", "b.four"])
        for req in contract["requirements"]:
            self.assertEqual(req["profile"], "outcome")
            self.assertNotIn("clause", req)
            self.assertIn("Judged on one test case, from the test fixture.", req["evidence_rule"])
            self.assertNotIn("out_of_scope", req["evidence_rule"])

    def test_requirement_tier_is_written_on_every_row_as_must_have(self):
        src = minimal_source()
        src["checks"][0]["criteria"][1]["requirement_tier"] = "must_have"
        contract = ec.from_pack(src)
        self.assertEqual([r["tier"] for r in contract["requirements"]], ["must_have"] * 4)
        # the judged/recomputed `tier` of a clause is not the requirement tier
        for req in contract["requirements"]:
            self.assertIn(req["mode"], ("judged", "value"))

    def test_a_bad_or_unsupported_requirement_tier_is_refused(self):
        # informational waits for rollup support: see pack_compile.validate_source
        for bad in ("optional", "informational", [], {}, None, 3):
            src = minimal_source()
            src["checks"][0]["criteria"][0]["requirement_tier"] = bad
            with self.assertRaisesRegex(ec.ContractError, "requirement_tier"):
                ec.from_pack(src)

    def test_out_of_scope_answer_follows_the_switch_and_never_out_of_scope(self):
        source = minimal_source()
        source["switches"] = {"out_of_scope_verdict": True}
        source["checks"][0]["criteria"][0]["never_out_of_scope"] = True
        reqs = ec.from_pack(source)["requirements"]
        self.assertNotIn("out_of_scope", reqs[0]["evidence_rule"])
        self.assertIn("out_of_scope when", reqs[1]["evidence_rule"])

    def test_switches_resolve_to_what_runs(self):
        source = minimal_source()
        source["switches"] = {"flip": True}
        source["checks"][0]["criteria"][0] = _criterion(
            "one", tier="judged", fold_id="fold.one", tier_switch={"flag": "flip", "tier_when_on": "recomputed"},
            claim_switch={"flag": "flip", "claim_when_on": "Switched claim."})
        req = ec.from_pack(source)["requirements"][0]
        self.assertEqual(req["backward_verdict"], "DETERMINISTIC")
        self.assertTrue(req["evidence_rule"].startswith("Switched claim.\n"))
        self.assertIn("Recomputed by fold fold.one.", req["evidence_rule"])
        source["switches"] = {"flip": False}
        req = ec.from_pack(source)["requirements"][0]
        self.assertEqual(req["backward_verdict"], "MODEL-ASSISTED")

    def test_duplicate_requirement_ids_are_refused_whatever_the_input(self):
        with self.assertRaisesRegex(ec.ContractError, "must be unique"):
            ec._contract("x", "1", [{"id": "a"}, {"id": "a"}])

    def test_an_obligation_needs_a_regulation_and_an_article(self):
        source = minimal_source()
        source["checks"][0]["article"] = "Art 1"
        with self.assertRaisesRegex(ec.ContractError, "regulation must be a non-empty string"):
            ec.from_pack(copy.deepcopy(source))
        for bad in ("", None, 3):
            source["regulation"] = bad
            with self.assertRaisesRegex(ec.ContractError, "regulation must be a non-empty string"):
                ec.from_pack(copy.deepcopy(source))
        source["regulation"] = "Regulation X"
        source["checks"][0]["article"] = " "
        with self.assertRaisesRegex(ec.ContractError, r"checks\[0\]\.article must be a non-empty string"):
            ec.from_pack(copy.deepcopy(source))
        source["checks"][0]["article"] = "Art 1"
        reqs = ec.from_pack(source)["requirements"]
        self.assertEqual(reqs[0]["clause"], {"instrument": "Regulation X", "article": "Art 1"})
        self.assertEqual(reqs[2]["profile"], "outcome")

    def test_an_invalid_pack_is_refused_with_its_issues(self):
        source = minimal_source()
        del source["pack_version"]
        with self.assertRaisesRegex(ec.ContractError, "pack_version must be a non-empty string"):
            ec.from_pack(source)

    def test_editing_a_judge_question_changes_the_contract(self):
        source = minimal_source()
        before = ec.contract_digest(ec.from_pack(copy.deepcopy(source)))
        source["checks"][0]["criteria"][0]["judge_question"] = "Did it?"
        self.assertNotEqual(ec.contract_digest(ec.from_pack(source)), before)

    def test_digest_is_sha256_of_jcs(self):
        contract = ec.from_pack(minimal_source())
        import rfc8785
        self.assertEqual(ec.contract_digest(contract), hashlib.sha256(rfc8785.dumps(contract)).hexdigest())


class FromReportSpec(unittest.TestCase):
    SPEC = REPO_ROOT / "scripts/specs/tau2-airline-no-judge.yaml"

    def test_report_spec_compiles_to_recomputed_rows_only(self):
        spec = report_spec.load_spec(self.SPEC)
        contract = ec.from_report_spec(spec)
        self.assertEqual(ec.contract_ref(contract), report_spec.contract_ref(spec))
        self.assertEqual([r["id"] for r in contract["requirements"]], [c["id"] for c in spec["claims"]])
        for req in contract["requirements"]:
            self.assertEqual(req["backward_verdict"], "DETERMINISTIC")
            self.assertEqual(req["mode"], "value")
            self.assertNotEqual(req.get("mode"), "judged")
            self.assertTrue(req["evidence_rule"].startswith("report-spec/v1 computation"))
            self.assertNotIn("measurability", req)

    def test_evidence_rule_carries_the_metrics_and_sources_a_claim_reads(self):
        reqs = {r["id"]: r for r in ec.from_report_spec(report_spec.load_spec(self.SPEC))["requirements"]}
        rule = reqs["cancellation_volume_bounded"]["evidence_rule"]
        computation = json.loads(rule.split(": ", 1)[1].split("\n", 1)[0])
        self.assertEqual([m["name"] for m in computation["metrics"]],
                         ["cancelling_conversation_count", "conversation_count"])
        self.assertEqual([s["name"] for s in computation["sources"]], ["conversations", "cancel_results"])
        computation = json.loads(reqs["refund_amount_matches_payment_record"]["evidence_rule"]
                                 .split(": ", 1)[1].split("\n", 1)[0])
        self.assertEqual([s["name"] for s in computation["sources"]],
                         ["conversations", "cancel_results", "refund_entries"])

    def test_grouping_and_the_out_of_scope_switch_change_the_contract(self):
        spec = report_spec.load_spec(self.SPEC)
        base = ec.contract_digest(ec.from_report_spec(spec))
        regrouped = copy.deepcopy(spec)
        regrouped["group_by"] = "domain"
        self.assertNotEqual(ec.contract_digest(ec.from_report_spec(regrouped)), base)
        switched = copy.deepcopy(spec)
        switched["switches"] = {"out_of_scope_verdict": False}
        self.assertNotIn("out_of_scope", ec.from_report_spec(switched)["requirements"][0]["evidence_rule"])
        self.assertIn("out_of_scope when", ec.from_report_spec(spec)["requirements"][0]["evidence_rule"])

    def test_bad_specs_are_refused(self):
        spec = report_spec.load_spec(self.SPEC)
        for mutate, message in (
                (lambda s: s["claims"].append(dict(s["claims"][0])), "must be unique"),
                (lambda s: s["claims"][0].pop("description"), "needs a description"),
                (lambda s: s["claims"][0].update(metric="nope"), "does not define"),
                (lambda s: s["claims"][1].update(source="nope"), "not defined"),
                (lambda s: s["claims"][0].update(value="conversation_count +"), "not a valid expression")):
            bad = copy.deepcopy(spec)
            mutate(bad)
            with self.assertRaisesRegex(ec.ContractError, message):
                ec.from_report_spec(bad)


class Published(unittest.TestCase):
    def test_every_published_contract_is_named_by_its_ref_and_recompiles_unchanged(self):
        published = sorted((REPO_ROOT / "contracts").rglob("*.json"))
        self.assertIn(EU_PUBLISHED, published)
        by_ref = {}
        for path in SOURCES:
            contract = ec.load_input(path)
            by_ref[ec.contract_ref(contract)] = contract
        for path in published:
            doc = json.loads(path.read_text())
            self.assertEqual(ec.published_path(doc), path)
            current = by_ref.get(ec.contract_ref(doc))
            if current is not None:
                self.assertEqual(ec.to_bytes(current), path.read_bytes(),
                                 f"{ec.contract_ref(doc)} is published and its source now compiles to "
                                 "something else: a published contract is immutable, bump the version")

    def test_publish_writes_once_and_refuses_a_changed_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            contract = ec.from_pack(minimal_source())
            path, written = ec.publish(contract, root)
            self.assertEqual((path, written), (root / "test-pack/1.0.0.json", True))
            self.assertEqual(ec.publish(contract, root), (path, False))
            changed = copy.deepcopy(contract)
            changed["requirements"][0]["statement"] = "changed"
            with self.assertRaisesRegex(ec.ContractError, "immutable: bump the version"):
                ec.publish(changed, root)
            self.assertEqual(path.read_bytes(), ec.to_bytes(contract))

    def test_a_new_version_is_a_new_file_and_the_old_one_stays(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source = minimal_source()
            old, _ = ec.publish(ec.from_pack(copy.deepcopy(source)), root)
            old_bytes = old.read_bytes()
            source["pack_version"] = "1.0.1"
            source["checks"][0]["criteria"][0]["label"] = "Relabelled"
            new, written = ec.publish(ec.from_pack(source), root)
            self.assertTrue(written)
            self.assertEqual(new, root / "test-pack/1.0.1.json")
            self.assertEqual(old.read_bytes(), old_bytes)

    def test_an_id_with_a_slash_nests_and_an_escaping_one_is_refused(self):
        root = pathlib.Path("/r")
        self.assertEqual(ec.published_path({"id": "asg/everyday-rules", "version": "0.1.0"}, root),
                         root / "asg/everyday-rules/0.1.0.json")
        for bad in ({"id": "../x", "version": "1"}, {"id": "a//b", "version": "1"},
                    {"id": "a", "version": ".."}, {"id": "/a", "version": "1"}):
            with self.assertRaises(ec.ContractError):
                ec.published_path(bad, root)

    def test_publish_cli_on_the_eu_pack_is_a_no_op(self):
        out = subprocess.run([sys.executable, "scripts/evidence_contract.py", "publish", str(EU_SOURCE)],
                             cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout
        result = json.loads(out)
        contract = ec.from_pack(load_pack(EU_SOURCE))
        self.assertEqual((result["contract_ref"], result["path"], result["written"]),
                         (ec.contract_ref(contract), ec.published_path(contract).relative_to(REPO_ROOT).as_posix(),
                          False))
        self.assertEqual(result["contract_digest"], ec.contract_digest(contract))

    def test_cli_runs_the_report_spec_runner_s_own_checks(self):
        spec = yaml.safe_load((REPO_ROOT / "scripts/specs/tau2-airline-no-judge.yaml").read_text())
        spec["switches"] = {"out_of_scope_verdict": "false"}
        with tempfile.NamedTemporaryFile("w", suffix=".yaml") as f:
            yaml.safe_dump(spec, f)
            f.flush()
            proc = subprocess.run([sys.executable, "scripts/evidence_contract.py", "compile", f.name],
                                  cwd=REPO_ROOT, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("out_of_scope_verdict must be a boolean", json.loads(proc.stdout)["error"])

    def test_cli_refuses_a_file_that_is_neither_input(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml") as f:
            f.write("hello: world\n")
            f.flush()
            proc = subprocess.run([sys.executable, "scripts/evidence_contract.py", "compile", f.name],
                                  cwd=REPO_ROOT, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("neither a pack source", json.loads(proc.stdout)["error"])


try:
    import jsonschema
except ImportError:  # requirements.txt installs it; the capsulectl check below covers a bare run
    jsonschema = None


class SchemaValid(unittest.TestCase):
    def test_vendored_schema_is_the_pinned_one(self):
        self.assertEqual(hashlib.sha256(SCHEMA.read_bytes()).hexdigest(), SCHEMA_SHA256)

    @unittest.skipUnless(jsonschema, "jsonschema not installed (requirements.txt)")
    def test_every_compiled_contract_is_valid_against_the_pinned_schema(self):
        validator = jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text()))
        for path in SOURCES:
            errors = [e.message for e in validator.iter_errors(ec.load_input(path))]
            self.assertEqual(errors, [], path)
        bad = ec.from_pack(minimal_source())
        bad["requirements"][0]["result"] = "met"
        self.assertFalse(validator.is_valid(bad))
        # negative vector: a tier outside must_have | informational
        bad = ec.from_pack(minimal_source())
        bad["requirements"][0]["tier"] = "optional"
        self.assertFalse(validator.is_valid(bad))
        # positive vector: the schema accepts both tiers
        good = ec.from_pack(minimal_source())
        good["requirements"][1]["tier"] = "informational"
        self.assertEqual({r["tier"] for r in good["requirements"]}, {"must_have", "informational"})
        self.assertTrue(validator.is_valid(good))

    @unittest.skipUnless(capsulectl(), "capsulectl not available (set CAPSULECTL or put it on PATH)")
    def test_capsulectl_contract_validate_accepts_every_compiled_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            for path in SOURCES:
                out = pathlib.Path(tmp) / "contract.json"
                out.write_bytes(ec.to_bytes(ec.load_input(path)))
                proc = subprocess.run([capsulectl(), "contract", "validate", str(out), "--schema", str(SCHEMA),
                                       "--json"], capture_output=True, text=True)
                self.assertEqual(proc.returncode, 0, f"{path}: {proc.stdout}{proc.stderr}")
                self.assertTrue(json.loads(proc.stdout)["valid"], path)

    @unittest.skipUnless(capsulectl(), "capsulectl not available (set CAPSULECTL or put it on PATH)")
    def test_capsulectl_refuses_a_contract_with_a_status(self):
        contract = ec.from_pack(minimal_source())
        contract["requirements"][0]["status"] = "SATISFIED"
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "contract.json"
            out.write_bytes(ec.to_bytes(contract))
            proc = subprocess.run([capsulectl(), "contract", "validate", str(out), "--schema", str(SCHEMA), "--json"],
                                  capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(json.loads(proc.stdout)["valid"])


if __name__ == "__main__":
    unittest.main()
