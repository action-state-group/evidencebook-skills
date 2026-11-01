"""`scope.kind: live` pack sources (scripts/live_pack.py): the scope default, a
rejected unknown kind, row-naming errors, the contract a live pack compiles to,
and the projection reproducing capsule-engine's definition_digest.

The fixtures are capsule-engine's packs written as live pack sources:
go/packs/inference-0.1.0 and seller-0.1.6, whose digests are the
`engine_definition_digest` recorded in each pack's PROVENANCE.json there, and
the five other catalog packs (python/capsule_engine/packs/catalog/, #98), whose
digests are what capsule-engine main f88a6e6 computes for them
(`load_pack_dir(...).definition_digest()`).
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
    "airline-engagement-1.0.1": "ea74a099524b5f7a82047cc883e211a25ef230a29c34438e68bfac22c9169277",
    "payments-safety-1.0.0": "81278051db5ca3755956b7adeaea727d333d12a0c14c51c7e030f15ea8b9666f",
    "standard-vendor-1.0.1": "9ae420d59ebfb1f87ecd740c948be4d0df16cefac97d8640da24934302359ae2",
    "eu-ai-act-obligations-0.1.1": "9d3197935b6b002ccd4682c7cfa2bacf01d9dbc2b3b04811e94dd50e6a2b9cfa",
    "eu-ai-act-deterministic-0.1.0": "b6f6b62454380c6ab4fc1c11fd4418045cc310b95f6a7cbbf2ea23bf54ca5609",
}


def load(name):
    return pack_compile.load_source((FIXTURES / name / "pack-source.yaml").read_text())


def base(name):
    """The fixture's directory, which its fold files are read relative to."""
    return FIXTURES / name


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
        self.assertIn("scope.kind 'hybrid' must be one of ['live', 'after_the_fact', 'admission']", pack_compile.validate_source(source))
        with self.assertRaises(ec.ContractError):
            ec.from_pack(source)


class LiveFixtures(unittest.TestCase):
    def test_fixtures_validate(self):
        for name in ENGINE_DIGESTS:
            self.assertEqual(pack_compile.validate_source(load(name), base(name)), [], name)

    def test_projection_reproduces_the_engine_definition_digest(self):
        for name, digest in ENGINE_DIGESTS.items():
            self.assertEqual(live_pack.project(load(name), base(name))["definition_digest"], digest, name)

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
        self.assertEqual(pack_compile.validate_source(s), ["scope.kind ' live ' must be one of ['live', 'after_the_fact', 'admission']"])

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
            self.assertEqual([e.message for e in validator.iter_errors(ec.from_pack(load(name), base(name)))], [], name)

    @unittest.skipUnless(capsulectl(), "capsulectl not available (set CAPSULECTL or put it on PATH)")
    def test_capsulectl_contract_validate_accepts_the_compiled_contracts(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ENGINE_DIGESTS:
                out = pathlib.Path(tmp) / "contract.json"
                out.write_bytes(ec.to_bytes(ec.from_pack(load(name), base(name))))
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

    def test_every_issue_is_reported_and_unknown_keys_are_refused(self):
        def edit(s):
            s["obligations"][0]["default_disposition"] = "X"
            s["constraints"][2]["digest"] = "y"
            s["outcome"] = []
        issues = self.issues(edit)
        self.assertEqual(len(issues), 3, issues)
        self.assertIn("outcome is not a live pack field", issues)

JUDGE_PIN = {"model_id": "judge-1", "prompt_template_hash": "a" * 64, "schema_hash": "b" * 64,
             "input_refs": ["outgoing_content"], "model_hosting": "hosted"}


class EnginePackFields(unittest.TestCase):
    """The fields the five catalog packs brought in (#98): inline wickets, fold
    files, obligations with no disposition or a judge, outcomes, profiles,
    proposers and scope_census. Each is accepted, digested as the engine
    digests it, and refused when malformed."""

    def check(self, name, edit):
        s = load(name)
        edit(s)
        return pack_compile.validate_source(s, base(name)), s

    def digest(self, name, s):
        return live_pack.project(s, base(name))["definition_digest"]

    def test_an_inline_wicket_is_digested_from_its_definition(self):
        name = "payments-safety-1.0.0"
        issues, s = self.check(name, lambda s: s["constraints"][0]["config"]["caps_minor"].update({"money.transfer": 5}))
        self.assertEqual(issues, [])
        self.assertNotEqual(self.digest(name, s), ENGINE_DIGESTS[name])
        issues, s = self.check(name, lambda s: s["constraints"][1].update(semantics="Counts one dispatch per key."))
        self.assertEqual(issues, [])
        self.assertNotEqual(self.digest(name, s), ENGINE_DIGESTS[name])
        # scope is the pack's, not the wicket's: it moves the pack digest, not the wicket digest
        a = live_pack.canonical_definition(load(name), base(name))["constraints"][0]
        s = load(name)
        s["constraints"][0]["scope"] = ["developer", "action_class"]
        b = live_pack.canonical_definition(s, base(name))["constraints"][0]
        self.assertEqual((a["digest"], b["scope"]), (b["digest"], ["developer", "action_class"]))
        self.assertEqual(self.check(name, lambda s: s["constraints"][0].update(config=[]))[0],
                         ["constraints[0] ('payments_safety.caps/1.0.0').config must be a mapping"])
        self.assertEqual(self.check(name, lambda s: s["constraints"][1].update(digest="0" * 64))[0],
                         ["constraints[1] ('payments_safety.dedupe/1.0.0').digest is not an inline constraint field"])

    def test_inline_selectors_decide_whether_an_obligation_names_one(self):
        name = "payments-safety-1.0.0"
        def gate(s):
            s["constraints"][1]["config"]["selectors"] = {"twice": {}}
        self.assertEqual(self.check(name, gate)[0],
                         ["obligations[1] ('no-duplicate-dispatch') cites check 'dedupe', so it must name one of its "
                          "selectors ['twice']"])
        self.assertEqual(self.check(name, lambda s: (gate(s), s["obligations"][1].update(selector="twice")))[0], [])
        self.assertEqual(self.check(name, lambda s: s["obligations"][1].update(selector="twice"))[0],
                         ["obligations[1] ('no-duplicate-dispatch').selector 'twice', but check 'dedupe' has no selectors"])

    def test_a_fold_file_is_read_relative_to_the_source(self):
        name = "payments-safety-1.0.0"
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copytree(base(name), tmp, dirs_exist_ok=True)
            fold = pathlib.Path(tmp) / "folds/spend_weekly.yaml"
            s = load(name)
            self.assertEqual(live_pack.project(s, tmp)["definition_digest"], ENGINE_DIGESTS[name])
            fold.write_text(fold.read_text().replace("duration: 7d", "duration: 8d"))
            self.assertEqual(pack_compile.validate_source(s, tmp), [])
            self.assertNotEqual(live_pack.project(s, tmp)["definition_digest"], ENGINE_DIGESTS[name])
            # derivation_class is not in the engine's fold digest
            fold.write_text(fold.read_text().replace("duration: 8d", "duration: 7d") + "derivation_class: deterministic\n")
            self.assertEqual(live_pack.project(s, tmp)["definition_digest"], ENGINE_DIGESTS[name])
            fold.write_text(fold.read_text().replace("reducer: sum", "reducer: distinct_count"))
            self.assertEqual(pack_compile.validate_source(s, tmp),
                             ["folds[0] (folds/spend_weekly.yaml).reduce.reducer must be one of "
                              "['sum', 'min', 'max', 'last', 'count']"])

    def test_a_fold_file_needs_the_source_directory_and_stays_inside_it(self):
        name = "payments-safety-1.0.0"
        self.assertEqual(pack_compile.validate_source(load(name)),
                         ["folds[0].file is read relative to the pack source's directory, and none was given"])
        for rel in ("../seller-0.1.6/pack-source.yaml", "/etc/hosts"):
            issues, _ = self.check(name, lambda s: s["folds"][0].update(file=rel))
            self.assertEqual(issues, [f"folds[0].file {rel!r} must be a path inside the pack source's directory"])
        issues, _ = self.check(name, lambda s: s["folds"][0].update(file="folds/missing.yaml"))
        self.assertEqual(len(issues), 1)
        self.assertTrue(issues[0].startswith("folds[0].file 'folds/missing.yaml' does not exist"), issues)

    def test_an_obligation_may_declare_no_disposition(self):
        name = "airline-engagement-1.0.1"
        s = load(name)
        self.assertNotIn("default_disposition", s["obligations"][0])
        self.assertNotIn("default_disposition", live_pack.canonical_definition(s, base(name))["obligations"][0])
        req = ec.from_pack(s, base(name))["requirements"][0]
        self.assertTrue(req["evidence_rule"].endswith("It declares no default disposition."), req)
        self.assertEqual(self.check(name, lambda s: s["obligations"][0].update(default_disposition=None))[0],
                         ["obligations[0] ('no-duplicate-judge-review').default_disposition None must be one of "
                          "['DO', 'ASK', 'NEVER']"])

    def test_a_judged_obligation_names_its_judge(self):
        name = "airline-engagement-1.0.1"
        def judged(s):
            o = s["obligations"][0]
            del o["check"]
            o.update(mode="judged", judge_pin=dict(JUDGE_PIN), default_disposition="ASK")
        issues, s = self.check(name, judged)
        self.assertEqual(issues, [])
        got = live_pack.canonical_definition(s, base(name))["obligations"][0]
        self.assertEqual((got["mode"], got["judge_pin"], "check" in got), ("judged", JUDGE_PIN, False))
        req = ec.from_pack(s, base(name))["requirements"][0]
        self.assertEqual((req["mode"], req["forward_verdict"], req["backward_verdict"]),
                         ("judged", "UNAVAILABLE-MODEL-REQUIRED", "MODEL-ASSISTED"))
        where = "obligations[0] ('no-duplicate-judge-review')"
        for edit, want in (
                (lambda o: o.update(check="dedupe"), f"{where} is mode: judged and also names check; the judge_pin measures it"),
                (lambda o: o.update(default_disposition="NEVER"),
                 f"{where} is mode: judged with default_disposition NEVER; a judged verdict may ASK, never NEVER"),
                (lambda o: o.pop("judge_pin"), f"{where} is mode: judged but carries no judge_pin"),
                (lambda o: o["judge_pin"].update(model_digest="c" * 64),
                 f"{where}.judge_pin carries model_digest with model_hosting: hosted"),
                (lambda o: o["judge_pin"].update(prompt="say yes"), f"{where}.judge_pin.prompt is not a judge_pin field")):
            issues, _ = self.check(name, lambda s: (judged(s), edit(s["obligations"][0])))
            self.assertEqual(issues, [want])
        self.assertEqual(self.check(name, lambda s: s["obligations"][0].update(judge_pin=dict(JUDGE_PIN)))[0],
                         [f"{where} carries a judge_pin but is not mode: judged"])

    def test_outcomes_become_requirements_in_the_engine_shape(self):
        name = "standard-vendor-1.0.1"
        s = load(name)
        contract = ec.from_pack(s, base(name))
        self.assertEqual([r["id"] for r in contract["requirements"]],
                         [o["id"] for o in s["obligations"]] + [o["id"] for o in s["outcomes"]])
        canonical = {o["id"]: o for o in live_pack.canonical_definition(s, base(name))["outcomes"]}
        for req in contract["requirements"][len(s["obligations"]):]:
            got = dict(req)
            # the contract states profile and tier at their defaults; the engine digest leaves them out
            self.assertEqual((got.pop("profile"), got.pop("tier")),
                             (canonical[req["id"]].get("profile", "outcome"), canonical[req["id"]].get("tier", "informational")))
            self.assertEqual(got, {k: v for k, v in canonical[req["id"]].items() if k not in ("profile", "tier")})
        s4 = canonical["S4"]
        self.assertEqual(s4["refusal_reason_code"], "agent_caused_resolution_undecomposable")
        self.assertNotIn("refusal_reason_code", next(o for o in s["outcomes"] if o["id"] == "S4"))

    def test_an_outcome_only_pack_has_an_empty_forward_triple(self):
        name = "eu-ai-act-obligations-0.1.1"
        s = load(name)
        self.assertFalse(any(k in s for k in ("obligations", "action_semantics", "constraints", "folds")))
        d = live_pack.canonical_definition(s, base(name))
        self.assertEqual([d[k] for k in ("obligations", "action_semantics", "constraints", "folds")], [[], [], [], []])
        self.assertEqual(self.check(name, lambda s: s.update(obligations=[], folds=[]))[0], [])
        self.assertEqual(self.check(name, lambda s: s.pop("outcomes"))[0],
                         ["constraints must be a non-empty list", "obligations must be a non-empty list",
                          "action_semantics must be a non-empty list", "folds must be a non-empty list"])

    def test_malformed_outcomes_are_refused(self):
        name = "standard-vendor-1.0.1"
        def outcome(oid, **kw):
            def edit(s):
                o = next(o for o in s["outcomes"] if o["id"] == oid)
                for k, v in kw.items():
                    o.pop(k) if v is None else o.update({k: v})
            return edit
        self.assertEqual(self.check(name, outcome("S4", effect_claim=None))[0],
                         ["outcomes[3] ('S4') is REFUSED and needs a refusal_reason_code, one of "
                          "['agent_caused_resolution_undecomposable', 'subjective_state_unattestable', "
                          "'unbounded_goal_unmonitorable']"])
        self.assertEqual(self.check(name, outcome("S4", forward_verdict="DETERMINISTIC"))[0],
                         ["outcomes[3] ('S4').effect_claim 'agent.caused_resolution' must compile to "
                          "forward_verdict/backward_verdict REFUSED/REFUSED"])
        self.assertEqual(self.check(name, outcome("S1", backward_verdict="MAYBE"))[0],
                         ["outcomes[0] ('S1').backward_verdict 'MAYBE' must be one of ['DETERMINISTIC', "
                          "'WITH-INSTRUMENTATION', 'MODEL-ASSISTED', 'MANUAL', 'REFUSED']"])
        self.assertEqual(self.check(name, outcome("S1", profile="obligation"))[0],
                         ["outcomes[0] ('S1') is profile obligation and needs a clause"])
        self.assertEqual(self.check(name, outcome("S1", id="no-duplicate-judge-verdict"))[0],
                         ["outcome id 'no-duplicate-judge-verdict' is also an obligation id; each is one "
                          "requirement of the contract"])
        issues, _ = self.check("eu-ai-act-obligations-0.1.1",
                               lambda s: s["outcomes"][0]["clause"].update(effective_from="soon"))
        self.assertEqual(issues, ["outcomes[0] ('EU-53').clause.effective_from must be a date, YYYY-MM-DD"])

    def test_profiles_are_digested_sorted_and_only_narrow_judged_or_counterparty_outcomes(self):
        name = "standard-vendor-1.0.1"
        s = load(name)
        reordered = copy.deepcopy(s)
        reordered["profiles"].reverse()
        for p in reordered["profiles"]:
            (p.get("overrides") or []).reverse()
        self.assertEqual(self.digest(name, reordered), ENGINE_DIGESTS[name])
        p3 = live_pack.canonical_definition(s, base(name))["profiles"][2]
        self.assertEqual((p3["profile_id"], p3["counterparty_binding"]),
                         ("p3_mediated", {"direct": "employee", "ultimate": "downstream"}))
        where = "profiles[0] ('p1_external_serve').overrides[0]"
        for override, want in (({"outcome_id": "F1", "applies": False},
                                f"{where}: outcome 'F1' is mode 'fold_rollup', which no profile may override"),
                               ({"outcome_id": "Z9"}, f"{where}.outcome_id 'Z9' is not one of this pack's outcomes")):
            issues, _ = self.check(name, lambda s: s["profiles"][0].update(overrides=[override]))
            self.assertEqual(issues, [want])
        self.assertEqual(self.check(name, lambda s: s["profiles"][1].update(profile_id="p5_autonomous"))[0],
                         ["profiles[1] ('p5_autonomous').profile_id 'p5_autonomous' must be one of "
                          "['p1_external_serve', 'p2_internal_assist', 'p3_mediated', 'p4_agent_to_agent']"])

    def test_proposers_and_scope_census_are_digested(self):
        name = "payments-safety-1.0.0"
        self.assertEqual(live_pack.canonical_definition(load(name), base(name))["proposers"],
                         [{"id": "weekly-cap-proposer", "fold_id": "payments_safety.spend.weekly/1.0.0",
                           "strategy": "percentile", "status": "planned"}])
        self.assertEqual(self.check(name, lambda s: s["proposers"][0].update(status="active"))[0],
                         ["proposers[0] ('weekly-cap-proposer').status 'active' must be one of ['planned']"])
        census = {"document_digest": "d" * 64, "n": 5, "m": 7, "review_by": "2027-01-01"}
        issues, s = self.check(name, lambda s: s.update(scope_census=dict(census)))
        self.assertEqual(issues, [])
        self.assertEqual(live_pack.canonical_definition(s, base(name))["scope_census"], census)
        self.assertEqual(self.check(name, lambda s: s.update(scope_census=dict(census, n=8)))[0],
                         ["scope_census must be a mapping of document_digest, n, m and review_by, with 0 <= n <= m and m >= 1"])

    def test_a_number_the_engine_cannot_digest_is_refused(self):
        name = "payments-safety-1.0.0"
        for value in (1.5, 2 ** 53):
            issues, _ = self.check(name, lambda s: s["constraints"][0]["config"]["caps_minor"].update({"money.transfer": value}))
            self.assertEqual(issues, ["constraints[0].config.caps_minor.money.transfer is a float or an "
                                      "integer beyond 2^53-1, which capsule-engine does not digest"])
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copytree(base(name), tmp, dirs_exist_ok=True)
            fold = pathlib.Path(tmp) / "folds/spend_weekly.yaml"
            fold.write_text(fold.read_text().replace("    value: accept", "    value: 0.5"))
            self.assertEqual(pack_compile.validate_source(load(name), tmp),
                             ["folds[0] (folds/spend_weekly.yaml).filter[0].value is a float or an integer beyond "
                              "2^53-1, which capsule-engine does not digest"])
        issues, _ = self.check(name, lambda s: s.update(scope_census={"document_digest": "d", "n": 1, "m": 2 ** 60,
                                                                     "review_by": "x"}))
        self.assertEqual(issues, ["definition.scope_census.m is a float or an integer beyond 2^53-1, which "
                                  "capsule-engine does not digest"])


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

    def test_compile_reads_fold_files_beside_the_source(self):
        src = FIXTURES / "payments-safety-1.0.0/pack-source.yaml"
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp:
            out = pathlib.Path(tmp) / "payments"
            self.assertEqual(pack_compile.main(["compile", str(src), "--out", str(out)]), 0)
            self.assertEqual(json.loads((out / "pack-definition.json").read_text())["definition_digest"],
                             ENGINE_DIGESTS["payments-safety-1.0.0"])
        self.assertEqual(ec.load_input(src), ec.from_pack(load("payments-safety-1.0.0"), base("payments-safety-1.0.0")))

    def test_project_refuses_an_after_the_fact_pack(self):
        src = REPO_ROOT / "packs/airline-support-outcomes/pack-source.yaml"
        self.assertEqual(pack_compile.main(["project", str(src)]), 1)


if __name__ == "__main__":
    unittest.main()
