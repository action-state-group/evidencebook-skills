"""`scope.kind: live` pack sources (scripts/live_pack.py): the scope default, a
rejected unknown kind, row-naming errors, the contract a live pack compiles to,
and the projection reproducing capsule-engine's definition_digest.

The two fixtures are capsule-engine's go/packs/inference-0.1.0 and seller-0.1.6
pack.yaml written as live pack sources; their digests are the
`engine_definition_digest` recorded in each pack's PROVENANCE.json there.
"""
import copy
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
import live_pack  # noqa: E402
import pack_compile  # noqa: E402
from test_pack_compile import minimal_source  # noqa: E402

try:
    import jsonschema
except ImportError:
    jsonschema = None

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests/fixtures/live-pack"
SCHEMA = REPO_ROOT / "tests/fixtures/capsule-engine/evidence-contract-v0.json"
ENGINE_DIGESTS = {
    "inference-0.1.0": "b8410fcf29faa0c027012a76bd275d397e210b788a6aa64098e96c4cd09098ed",
    "seller-0.1.6": "5e112a7f5136e2193adb177605dfad10b7b0753a2de93ed72e446695b7acc56a",
}


def load(name):
    return pack_compile.load_source((FIXTURES / name / "pack-source.yaml").read_text())


def capsulectl():
    return os.environ.get("CAPSULECTL") or shutil.which("capsulectl")


class ScopeKind(unittest.TestCase):
    def test_absent_means_after_the_fact(self):
        source = minimal_source()
        self.assertNotIn("scope", source)
        self.assertEqual(live_pack.scope_kind(source), "after_the_fact")
        self.assertFalse(live_pack.is_live(source))
        self.assertEqual(pack_compile.validate_source(source), [])

    def test_explicit_after_the_fact_compiles_as_absent_does(self):
        absent, explicit = minimal_source(), minimal_source()
        explicit["scope"] = {"kind": "after_the_fact"}
        self.assertEqual(pack_compile.validate_source(explicit), [])
        # pack_source_digest hashes the whole source, so declaring the default changes it and nothing else
        got, want = (pack_compile.compile_pack(x, "demo/t") for x in (explicit, absent))
        self.assertNotEqual(got[0].pop("pack_source_digest"), want[0].pop("pack_source_digest"))
        self.assertEqual(got, want)
        self.assertEqual(ec.to_bytes(ec.from_pack(explicit)), ec.to_bytes(ec.from_pack(absent)))

    def test_an_unknown_kind_is_rejected(self):
        for scope in ({"kind": "hybrid"}, {"kind": None}, {}, "live", {"kind": "live", "extra": 1}):
            source = minimal_source()
            source["scope"] = scope
            issues = pack_compile.validate_source(source)
            self.assertTrue(issues, scope)
            self.assertTrue(all(i.startswith("scope") for i in issues), issues)
        source = minimal_source()
        source["scope"] = {"kind": "hybrid"}
        self.assertIn("scope.kind 'hybrid' must be one of ['live', 'after_the_fact']", pack_compile.validate_source(source))
        with self.assertRaises(ec.ContractError):
            ec.from_pack(source)


class LiveFixtures(unittest.TestCase):
    def test_fixtures_validate(self):
        for name in ENGINE_DIGESTS:
            self.assertEqual(pack_compile.validate_source(load(name)), [], name)

    def test_projection_reproduces_the_engine_definition_digest(self):
        for name, digest in ENGINE_DIGESTS.items():
            self.assertEqual(live_pack.project(load(name))["definition_digest"], digest, name)

    def test_the_digest_follows_what_the_engine_digests_and_not_what_it_does_not(self):
        base = load("inference-0.1.0")
        digest = live_pack.project(base)["definition_digest"]
        for edit in (lambda s: s["obligations"][0].update(statement="changed"),
                     lambda s: s["obligations"][0].update(default_disposition="ASK"),
                     lambda s: s["constraints"][0].update(digest="0" * 64),
                     lambda s: s.update(holds_integration="stubbed")):
            s = copy.deepcopy(base)
            edit(s)
            self.assertNotEqual(live_pack.project(s)["definition_digest"], digest)
        # not digested: the requirement tier
        s = copy.deepcopy(base)
        s["obligations"][0]["requirement_tier"] = "informational"
        self.assertEqual(live_pack.project(s)["definition_digest"], digest)

    def test_strings_are_digested_as_written(self):
        # capsule-engine keeps a folded `>` scalar's trailing newline in the digest
        text = (FIXTURES / "inference-0.1.0/pack-source.yaml").read_text()
        folded = text.replace("statement: >-\n      Checks the input", "statement: >\n      Checks the input", 1)
        self.assertNotEqual(folded, text)
        s = pack_compile.load_source(folded)
        self.assertTrue(s["obligations"][0]["statement"].endswith("\n"))
        self.assertNotEqual(live_pack.project(s)["definition_digest"], ENGINE_DIGESTS["inference-0.1.0"])

    def test_a_padded_kind_is_refused_not_stripped_into_live(self):
        text = (FIXTURES / "inference-0.1.0/pack-source.yaml").read_text().replace("\n  kind: live", '\n  kind: " live "', 1)
        s = pack_compile.load_source(text)
        self.assertEqual(pack_compile.validate_source(s), ["scope.kind ' live ' must be one of ['live', 'after_the_fact']"])

    def test_compile_is_byte_stable(self):
        a, b = load("seller-0.1.6"), load("seller-0.1.6")
        self.assertEqual(ec.to_bytes(ec.from_pack(a)), ec.to_bytes(ec.from_pack(b)))
        self.assertEqual(live_pack.projection_bytes(a), live_pack.projection_bytes(b))

    def test_contract_has_one_requirement_per_obligation(self):
        source = load("seller-0.1.6")
        contract = ec.from_pack(source)
        self.assertEqual((contract["id"], contract["version"]), ("asg/seller/0.1.6", "0.1.6"))
        self.assertEqual([r["id"] for r in contract["requirements"]], [o["id"] for o in source["obligations"]])
        self.assertEqual([r["statement"] for r in contract["requirements"]], [o["statement"] for o in source["obligations"]])
        self.assertTrue(all(r["tier"] == "must_have" and r["forward_verdict"] == "DETERMINISTIC"
                            for r in contract["requirements"]))

    @unittest.skipUnless(jsonschema, "jsonschema not installed (requirements.txt)")
    def test_contracts_are_valid_against_the_pinned_schema(self):
        validator = jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text()))
        for name in ENGINE_DIGESTS:
            self.assertEqual([e.message for e in validator.iter_errors(ec.from_pack(load(name)))], [], name)

    @unittest.skipUnless(capsulectl(), "capsulectl not available (set CAPSULECTL or put it on PATH)")
    def test_capsulectl_contract_validate_accepts_the_compiled_contracts(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ENGINE_DIGESTS:
                out = pathlib.Path(tmp) / "contract.json"
                out.write_bytes(ec.to_bytes(ec.from_pack(load(name))))
                proc = subprocess.run([capsulectl(), "contract", "validate", str(out), "--schema", str(SCHEMA), "--json"],
                                      capture_output=True, text=True)
                self.assertEqual(proc.returncode, 0, f"{name}: {proc.stdout}{proc.stderr}")

    def test_declared_not_measured_obligation(self):
        s = load("inference-0.1.0")
        s["obligations"].append({"id": "r04-x", "statement": "Not measured yet.", "default_disposition": "ASK",
                                 "measurability": "declared_not_measured",
                                 "evidence_instrument": {"kind": "structured_field", "field": "peer_rate"}})
        self.assertEqual(pack_compile.validate_source(s), [])
        req = ec.from_pack(s)["requirements"][-1]
        self.assertEqual((req["measurability"], req["forward_verdict"]), ("declared_not_measured", "UNAVAILABLE-STATE-REQUIRED"))
        added = live_pack.canonical_definition(s)["obligations"][-1]
        self.assertEqual(added, {"id": "r04-x", "statement": "Not measured yet.", "default_disposition": "ASK",
                                 "measurability": "declared_not_measured",
                                 "evidence_instrument": {"kind": "structured_field", "field": "peer_rate"}})


class LiveErrorsNameTheRow(unittest.TestCase):
    def issues(self, edit):
        s = load("inference-0.1.0")
        edit(s)
        return pack_compile.validate_source(s)

    def test_obligation_errors_name_the_row(self):
        self.assertEqual(self.issues(lambda s: s["obligations"][1].update(default_disposition="MAYBE")),
                         ["obligations[1] ('r02-counterparty-list').default_disposition 'MAYBE' must be one of "
                          "['DO', 'ASK', 'NEVER']"])
        self.assertEqual(self.issues(lambda s: s["obligations"][2].update(check="nope")),
                         ["obligations[2] ('r03-same-purchase-twice').check 'nope' has no matching constraint"])
        self.assertEqual(self.issues(lambda s: s["obligations"][0].update(statement="")),
                         ["obligations[0] ('r01-rate-caps').statement must be a non-empty string"])

    def test_pack_id_version_and_closed_sets_follow_the_engine_loader(self):
        self.assertEqual(self.issues(lambda s: s.update(pack_id="Inference")),
                         ["pack_id 'Inference' must be <owner>/<name>/<major.minor.patch>, as capsule-engine's PACK_ID_RE requires"])
        self.assertEqual(len(self.issues(lambda s: s.update(pack_version="9.9.9"))), 1)
        self.assertEqual(self.issues(lambda s: s.update(holds_integration="bogus")),
                         ["holds_integration 'bogus' must be one of ['none', 'stubbed', 'built']"])
        self.assertEqual(self.issues(lambda s: s.update(folds=[])), ["folds must be a non-empty list"])
        self.assertEqual(self.issues(lambda s: s.update(action_semantics=[])), ["action_semantics must be a non-empty list"])

    def test_null_or_unknown_requirement_tier_is_refused(self):
        for tier in (None, "optional"):
            self.assertEqual(len(self.issues(lambda s: s["obligations"][0].update(requirement_tier=tier))), 1, tier)

    def test_duplicate_obligation_and_measured_with_instrument(self):
        self.assertEqual(self.issues(lambda s: s["obligations"][1].update(id="r01-rate-caps")),
                         ["duplicate obligation id: 'r01-rate-caps'"])
        issues = self.issues(lambda s: s["obligations"][0].update(evidence_instrument={"kind": "tool_call_name", "name": "x"}))
        self.assertEqual(issues, ["obligations[0] ('r01-rate-caps') is measured by its check and also names an evidence_instrument"])

    def test_constraint_fold_and_action_semantics_errors_name_the_row(self):
        self.assertEqual(self.issues(lambda s: s["constraints"][0].update(digest="ABC")),
                         ["constraints[0] ('rate_cap/1.0.0').digest must be 64 lowercase hex characters"])
        self.assertEqual(self.issues(lambda s: s["folds"][0].pop("digest")),
                         ["folds[0] ('spend.weekly/3.1.0').digest must be 64 lowercase hex characters"])
        self.assertEqual(self.issues(lambda s: s["action_semantics"][0].update(required_fields="target")),
                         ["action_semantics[0] ('inference.purchase').required_fields must be a list of strings"])

    def test_every_issue_is_reported_and_unsupported_keys_are_refused(self):
        def edit(s):
            s["obligations"][0]["default_disposition"] = "X"
            s["constraints"][2]["digest"] = "y"
            s["outcomes"] = []
        issues = self.issues(edit)
        self.assertEqual(len(issues), 3, issues)
        self.assertIn("outcomes is not a live pack field (not supported yet)", issues)


class LiveCLI(unittest.TestCase):
    def test_compile_writes_the_contract_and_the_projection(self):
        src = FIXTURES / "inference-0.1.0/pack-source.yaml"
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp:
            out = pathlib.Path(tmp) / "inference"
            self.assertEqual(pack_compile.main(["compile", str(src), "--out", str(out)]), 0)
            self.assertEqual((out / "contract.json").read_bytes(), ec.to_bytes(ec.from_pack(load("inference-0.1.0"))))
            self.assertEqual(json.loads((out / "pack-definition.json").read_text())["definition_digest"],
                             ENGINE_DIGESTS["inference-0.1.0"])
            self.assertEqual(sorted(p.name for p in out.iterdir()), ["contract.json", "pack-definition.json"])

    def test_project_refuses_an_after_the_fact_pack(self):
        src = REPO_ROOT / "packs/airline-support-outcomes/pack-source.yaml"
        self.assertEqual(pack_compile.main(["project", str(src)]), 1)


if __name__ == "__main__":
    unittest.main()
