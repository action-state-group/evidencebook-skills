"""`scope.kind: admission` pack sources (scripts/admission_pack.py, admission
pack profile v0): the baseline pack and its fixtures, the design rules the lint
holds, and the Evidence Contract an admission pack compiles to. The fixtures'
expected decisions are checked against the evaluator in capsule-engine#265's
CI; here they are checked for shape and against the pack.
"""
import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import rfc8785  # noqa: E402
import yaml  # noqa: E402

import admission_pack  # noqa: E402
import evidence_contract as ec  # noqa: E402
import pack_compile  # noqa: E402

try:
    import jsonschema
except ImportError:
    jsonschema = None

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
BASELINE = REPO_ROOT / "packs/admission-baseline"
SCHEMA = REPO_ROOT / "tests/fixtures/capsule-engine/evidence-contract-v0.json"

INPUT_KEYS = {"now", "amount", "currency", "platform", "card", "selection", "own", "operator", "vouches",
              "subject", "judged", "asks", "asks_made", "stake"}


def baseline_text():
    return (BASELINE / "pack-source.yaml").read_text()


def load(text):
    return pack_compile.load_source(text)


class Baseline(unittest.TestCase):
    def test_validates(self):
        self.assertEqual(pack_compile.validate_source(load(baseline_text())), [])

    def test_every_number_is_a_placeholder(self):
        # #51's added acceptance: every amount is marked as a placeholder.
        for line in baseline_text().splitlines():
            if any(k in line for k in ("max_decade:", "max_asks:", "deadline_s:", "params:")):
                self.assertIn("placeholder", line, line)

    def test_stake_is_a_recorded_source_only(self):
        rows = [r for r in load(baseline_text())["rows"] if r["source"] == "stake"]
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual(r["on_fail"], "record")
            self.assertEqual(set(r), {"id", "statement", "source", "check", "from", "on_fail"})
        roots = load(baseline_text())["trust_roots"]
        self.assertNotIn("stake", roots)

    def test_not_the_mesh_default(self):
        # u137: a Mesh pack keeps own_history from deciding NO. The baseline
        # does let it, so it says it is not the Mesh default.
        self.assertIn("Not the Mesh default", baseline_text())

    def test_the_climb_rests_on_the_counterpartys_evidence(self):
        # Design §4: our own book gates no tier above T0; the card gates T1
        # and the bound selection T2.
        rows = load(baseline_text())["rows"]
        gating = {r["source"] for r in rows if r["from"] != "T0" and r.get("on_fail") == "LIMIT"}
        self.assertLessEqual(gating, {"card", "bound", "own_history"})
        own_gates = [r["id"] for r in rows if r["source"] == "own_history" and r.get("on_fail") == "LIMIT"]
        self.assertEqual(own_gates, ["no-conflicting-deal"])

    def test_compiles_to_a_contract(self):
        contract = ec.from_pack(load(baseline_text()))
        self.assertEqual(ec.contract_ref(contract), "asg/admission_baseline/1.0.0@1.0.0")
        self.assertEqual([r["id"] for r in contract["requirements"]],
                         [r["id"] for r in load(baseline_text())["rows"]])
        judged = [r for r in contract["requirements"] if r["id"] == "adjacent-domain"]
        self.assertEqual(judged[0]["backward_verdict"], "MODEL-ASSISTED")
        if jsonschema is not None:
            jsonschema.validate(contract, json.loads(SCHEMA.read_text()))

    def test_compile_writes_the_contract_and_the_pinned_artifact(self):
        with tempfile.TemporaryDirectory(dir=REPO_ROOT / "packs") as tmp:
            out = pathlib.Path(tmp).relative_to(REPO_ROOT)
            run = subprocess.run([sys.executable, "scripts/pack_compile.py", "compile",
                                  str(BASELINE / "pack-source.yaml"), "--out", str(out)],
                                 cwd=REPO_ROOT, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            answer = json.loads(run.stdout)
            self.assertEqual(answer["scope"], "admission")
            self.assertEqual(sorted(p.name for p in pathlib.Path(tmp).iterdir()), ["contract.json", "pack-definition.json"])
            pinned = (pathlib.Path(tmp) / "pack-definition.json").read_bytes()
            self.assertEqual(hashlib.sha256(pinned).hexdigest(), answer["definition_digest"])

    def test_the_committed_artifact_is_the_compiled_source(self):
        # packs/admission-baseline/compiled/ is what a consumer pins and copies;
        # it must be exactly what the source compiles to.
        source = load(baseline_text())
        self.assertEqual((BASELINE / "compiled/pack-definition.json").read_bytes(), admission_pack.compiled_bytes(source))
        self.assertEqual((BASELINE / "compiled/contract.json").read_bytes(), ec.to_bytes(admission_pack.from_admission(source)))

    def test_the_artifact_is_jcs_and_complete(self):
        pinned = admission_pack.compiled_bytes(load(baseline_text()))
        doc = json.loads(pinned)
        self.assertEqual(rfc8785.dumps(doc), pinned)
        self.assertEqual(doc["format"], "admission-pack/v0")
        self.assertEqual(set(doc["trust_roots"]), {"controllers", "witnesses", "judges"})
        self.assertTrue(all("params" in r for r in doc["rows"]))

class Fixtures(unittest.TestCase):
    def setUp(self):
        self.doc = json.loads((BASELINE / "fixtures/cases.json").read_text())
        self.pack = load(baseline_text())

    def test_name_the_pack(self):
        self.assertEqual(self.doc["pack"], self.pack["pack_id"])

    def test_cases_are_well_formed(self):
        tiers = {t["id"] for t in self.pack["tiers"]}
        rows = {r["id"] for r in self.pack["rows"]}
        names = [c["case"] for c in self.doc["cases"]]
        self.assertEqual(len(names), len(set(names)))
        for c in self.doc["cases"]:
            self.assertLessEqual(set(c["input"]), INPUT_KEYS, c["case"])
            e = c["expected"]
            self.assertIn(e["verdict"], self.pack["outcomes"], c["case"])
            self.assertIn(e["source"], rows | {"rows", "above_tier", "missing"}, c["case"])
            if e["verdict"] == "NO":
                self.assertIsNone(e["tier"], c["case"])
            else:
                self.assertIn(e["tier"], tiers, c["case"])

    def test_every_outcome_is_exercised(self):
        self.assertEqual({c["expected"]["verdict"] for c in self.doc["cases"]}, set(self.pack["outcomes"]))

    def test_no_comes_only_from_rows_that_may_decide_it(self):
        sources = {r["id"]: r["source"] for r in self.pack["rows"]}
        for c in self.doc["cases"]:
            if c["expected"]["verdict"] == "NO" and c["expected"]["source"] in sources:
                self.assertIn(sources[c["expected"]["source"]], admission_pack.MAY_DECIDE_NO, c["case"])


class Refusals(unittest.TestCase):
    """Each edit of the baseline must be refused, naming the rule it breaks."""

    def assertRefused(self, old, new, want):
        text = baseline_text()
        self.assertTrue(old in text, f"the baseline has no {old!r}")
        issues = pack_compile.validate_source(load(text.replace(old, new, 1)))
        self.assertTrue(any(want in i for i in issues), issues)

    def test_a_card_row_deciding_no(self):
        self.assertRefused("    check: card.verified\n    from: T1\n    on_fail: \"LIMIT\"",
                           "    check: card.verified\n    from: T1\n    on_fail: \"NO\"", "a card row may not decide NO")

    def test_a_vouch_row_deciding_no(self):
        self.assertRefused("    check: vouch.distinct_controllers\n    params: {min: 3}            # placeholder\n"
                           "    from: T2\n    on_fail: \"record\"",
                           "    check: vouch.distinct_controllers\n    params: {min: 3}\n    from: T2\n    on_fail: \"NO\"",
                           "a vouch row may not decide NO")

    def test_a_stake_row_deciding_no(self):
        self.assertRefused("    check: stake.covers_deal\n    from: T2\n    on_fail: \"record\"",
                           "    check: stake.covers_deal\n    from: T2\n    on_fail: \"NO\"", "a stake row may not decide NO")

    def test_a_judged_row_deciding_no(self):
        self.assertRefused("    on_fail: {cap: T1}", "    on_fail: \"NO\"", "a judged row's on_fail must be {cap: <tier>}")

    def test_missing_go(self):
        self.assertRefused('missing: "LIMIT"', 'missing: "GO"', "never a silent GO")

    def test_an_unquoted_no(self):
        self.assertRefused('    on_fail: "NO"', "    on_fail: NO", "YAML 1.1 reads a plain NO as false")

    def test_a_score(self):
        self.assertRefused("budget:\n", "score: {weights: [1]}\nbudget:\n", "score is not an admission pack field")

    def test_a_row_weight(self):
        self.assertRefused("    check: own.settled\n", "    check: own.settled\n    weight: 2\n", "weight is not a row field")

    def test_limit_on_the_lowest_tier(self):
        self.assertRefused("    check: operator.allow_listed\n    from: T0\n    on_fail: \"NO\"",
                           "    check: operator.allow_listed\n    from: T0\n    on_fail: \"LIMIT\"", "cannot LIMIT")

    def test_an_unknown_predicate(self):
        self.assertRefused("check: own.settled", "check: own.reputation", "is not an admission predicate")

    def test_a_wrong_param(self):
        self.assertRefused("    params: {max_age_s: 604800}", "    params: {max_age: 604800}", "needs params.max_age_s")

    def test_decades_that_do_not_rise(self):
        self.assertRefused("max_decade: {sat: 4, USD: 0}", "max_decade: {sat: 3, USD: 0}", "does not rise")

    def test_an_ask_without_ask(self):
        self.assertRefused('outcomes: ["GO", "ASK", "LIMIT", "NO"]', 'outcomes: ["GO", "LIMIT", "NO"]',
                           "ASK is not in outcomes")

    def test_a_judged_row_in_a_pack_without_limit(self):
        text = baseline_text().replace('outcomes: ["GO", "ASK", "LIMIT", "NO"]', 'outcomes: ["GO", "ASK", "NO"]')
        issues = pack_compile.validate_source(load(text))
        self.assertIn("rows[17] ('adjacent-domain'): a judged row caps a tier, so LIMIT must be in outcomes", issues)

    def test_a_cap_that_lowers_nothing(self):
        self.assertRefused("    on_fail: {cap: T1}", "    on_fail: {cap: T2}", "cap T2 must be a tier below from T2")

    def test_an_ask_on_a_no_row(self):
        self.assertRefused("    check: platform.attestation_not_invalid\n    from: T0\n    on_fail: \"NO\"",
                           "    check: platform.attestation_not_invalid\n    from: T0\n    on_fail: \"NO\"\n"
                           "    ask: {derivation: history_card/1}", "only a LIMIT row may carry an ask")

    def test_a_ceiling_in_a_unit_accept_does_not_name(self):
        self.assertRefused("max_decade: {USD: 2}", "max_decade: {USD: 2, Sat: 9}", "max_decade.Sat is not a band unit in accept")

    def test_a_ceiling_that_falls_across_a_skipped_tier(self):
        text = baseline_text().replace("max_decade: {sat: 4, USD: 0}", "max_decade: {USD: 0}") \
            .replace("max_decade: {USD: 2}", "max_decade: {USD: 2, sat: 2}")
        issues = pack_compile.validate_source(load(text))
        self.assertIn("tier T2: max_decade.sat 2 does not rise above the tier below (3)", issues)

    def test_no_ask_deadline(self):
        self.assertRefused("  deadline_s: 86400", "  max_wait: 86400", "deadline_s: <positive integer>")

    def test_an_unknown_trust_root(self):
        self.assertRefused("  judges: [placeholder-judge]", "  rails: [x402]", "trust_roots must map some of")

    def test_wrong_types_are_reported_not_raised(self):
        text = baseline_text().replace("  - id: attestation\n", "  - id: [attestation]\n") \
            .replace("check: platform.owner_signed", "check: [platform.owner_signed]") \
            .replace('source: "evidencebook-skills#51', 'source_was: "x"\nsource: {by: "evidencebook-skills#51')
        text = text.replace('§4"\n', '§4"}\n', 1)
        issues = pack_compile.validate_source(load(text))
        self.assertTrue(any("id must be lowercase" in i for i in issues), issues)
        self.assertTrue(any("is not an admission predicate" in i for i in issues), issues)
        self.assertIn("source must be provenance text (a string)", issues)

    def test_a_scale_out_of_range(self):
        self.assertRefused("scale: -3}", "scale: -300}", "scale -300 must be from -30 to 30")

    def test_a_ceiling_out_of_range(self):
        self.assertRefused("max_decade: {USD: 2}", "max_decade: {USD: 99}", "max_decade.USD 99 must be from -60 to 60")

    def test_a_unit_no_tier_names(self):
        self.assertRefused("  USD: {band: USD, scale: 0}\n", "  USD: {band: USD, scale: 0}\n  EUR: {band: EUR, scale: 0}\n",
                           "band unit EUR is named by no tier")

    def test_a_negative_threshold(self):
        self.assertRefused("params: {min: 10}", "params: {min: -1}", "params.min -1 must be from 0")

    def test_a_threshold_whose_duration_wraps(self):
        self.assertRefused("params: {max_age_s: 604800}", "params: {max_age_s: 99999999999}",
                           "params.max_age_s 99999999999 must be from 0")

    def test_an_unknown_scope_kind_still_names_admission(self):
        issues = pack_compile.validate_source(load(baseline_text().replace("kind: admission", "kind: admit")))
        self.assertIn("scope.kind 'admit' must be one of ['live', 'after_the_fact', 'admission']", issues)


class GoNoPack(unittest.TestCase):
    """A pack shaped like the Mesh default under u137: GO and NO only, NO from
    the operator alone, the other rows recorded. Its evaluator vectors, above
    the top tier among them, are capsule-engine#265's (mesh-go-no.yaml)."""

    SOURCE = """
pack_id: asg/mesh_admission_example/0.1.0
pack_version: 0.1.0
scope: {kind: admission}
outcomes: ["GO", "NO"]
missing: "NO"
accept:
  msat: {band: sat, scale: -3}
tiers:
  - {id: T0, max_decade: {sat: 6}}
budget: {max_asks: 0, deadline_s: 86400}
rows:
  - {id: deny-list, statement: Not on the deny list., source: operator, check: operator.not_deny_listed, from: T0, on_fail: "NO"}
  - {id: disputes, statement: No adverse adjudication in 30 days., source: own_history, check: own.no_adverse_adjudication, params: {window_days: 30}, from: T0, on_fail: "record"}
"""

    def test_validates(self):
        self.assertEqual(pack_compile.validate_source(load(self.SOURCE)), [])

    def test_refuses_a_limit_or_an_ask(self):
        self.assertTrue(pack_compile.validate_source(load(self.SOURCE.replace('on_fail: "record"', 'on_fail: "LIMIT"'))))
        self.assertTrue(pack_compile.validate_source(load(self.SOURCE.replace(
            'on_fail: "record"}', 'on_fail: "record", ask: {derivation: history_card/1}}'))))


class TextIssues(unittest.TestCase):
    """What the evaluator's loader refuses in the text, before any mapping."""

    def issues(self, old, new):
        text = baseline_text()
        self.assertTrue(old in text, old)
        return admission_pack.text_issues(text.replace(old, new, 1))

    def test_the_baseline_has_none(self):
        self.assertEqual(admission_pack.text_issues(baseline_text()), [])

    def test_accepted_plain_forms(self):
        # A version, a decimal, words and text read alike everywhere; the
        # non-specific tag ! is ignored, as yaml.v3 ignores it.
        for doc in ("v: 1.0.0", "v: -3", "v: 0", "v: asg/admission_baseline/1.0.0", "v: history_card/1",
                    "v: The card is 7 days old.", "v: ! text", 'v: "NO"', "v:"):
            self.assertEqual(admission_pack.text_issues(doc), [], doc)

    def test_refused(self):
        for old, new, want in [
            ('on_fail: "NO"', "on_fail: NO", "quote 'NO'"),
            ('on_fail: "NO"', "on_fail: y", "quote 'y'"),
            ('on_fail: "NO"', "on_fail: null", "quote 'null'"),
            ("scale: -3}", "scale: -3.5}", "quote '-3.5'"),
            ("max_asks: 3", "max_asks: 0x3", "quote '0x3'"),
            ("max_asks: 3", "max_asks: 03", "quote '03'"),
            ("max_asks: 3", "max_asks: 1_0", "quote '1_0'"),
            ("max_asks: 3", "max_asks: -0", "quote '-0'"),
            ("max_asks: 3", "max_asks: +3", "quote '+3'"),
            ("  - id: attestation\n", "  - id: true\n", "quote 'true'"),
            ("  - id: attestation\n", "  - id: 1e3\n", "quote '1e3'"),
            ("  - id: attestation\n", "  - id: 1E-2\n", "quote '1E-2'"),
            ("  - id: attestation\n", "  - id: 0o10\n", "quote '0o10'"),
            ("  - id: attestation\n", "  - id: 2026-1-2\n", "quote '2026-1-2'"),
            ("  - id: attestation\n", "  - id: 1:30\n", "quote '1:30'"),
            ("  - id: attestation\n", "  - id: .inf\n", "quote '.inf'"),
            ("  - id: T0 ", "  - &t0 id: T0 ", "anchors and aliases"),
            ("  - id: attestation\n", "  - id: !!str attestation\n", "tags are not read"),
            ("max_asks: 3", 'max_asks: !!int "3"', "tags are not read"),
            ("source: \"evidencebook", "source: 2026-10-30\nx: \"evidencebook", "quote '2026-10-30'"),
        ]:
            got = self.issues(old, new)
            self.assertTrue(any(want in i for i in got), (new, got))

    def test_the_shared_probes(self):
        # The source's plain scalar rule: PyYAML, in the compiler, is the one
        # YAML reader an admission pack has (the evaluator reads the compiled
        # pack-definition.json), so this guards what it would misread.
        probes = json.loads((REPO_ROOT / "tests/fixtures/admission-plain-scalars.json").read_text())
        for doc in probes["accepted"]:
            self.assertEqual(admission_pack.text_issues(doc), [], doc)
        for doc in probes["refused"]:
            try:
                got = admission_pack.text_issues(doc)
            except yaml.YAMLError:
                continue
            self.assertTrue(got, doc)

    def test_the_cli_reports_them(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", dir=REPO_ROOT / "packs", delete=False) as f:
            f.write(baseline_text().replace("max_asks: 3", "max_asks: 0x3", 1))
        try:
            run = subprocess.run([sys.executable, "scripts/pack_compile.py", "validate", f.name],
                                 cwd=REPO_ROOT, capture_output=True, text=True)
        finally:
            pathlib.Path(f.name).unlink()
        self.assertEqual(run.returncode, 1)
        self.assertTrue(any("quote '0x3'" in i for i in json.loads(run.stdout)["issues"]), run.stdout)


if __name__ == "__main__":
    unittest.main()
