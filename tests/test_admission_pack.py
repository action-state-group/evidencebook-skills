"""`scope.kind: admission` pack sources (scripts/admission_pack.py, admission
pack profile v0): the baseline pack and its fixtures, the design rules the lint
holds, and the Evidence Contract an admission pack compiles to. The fixtures'
expected decisions are checked against the evaluator in capsule-engine#265's
CI; here they are checked for shape and against the pack.
"""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

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

INPUT_KEYS = {"now", "amount", "currency", "platform", "card", "own", "operator", "vouches", "subject",
              "judged", "asks", "asks_made", "stake"}


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
            if any(k in line for k in ("max_decade:", "max_asks:", "params:")):
                self.assertIn("placeholder", line, line)

    def test_stake_is_a_recorded_source_only(self):
        rows = [r for r in load(baseline_text())["rows"] if r["source"] == "stake"]
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual(r["on_fail"], "record")
            self.assertEqual(set(r), {"id", "statement", "source", "check", "from", "on_fail"})

    def test_compiles_to_a_contract(self):
        contract = ec.from_pack(load(baseline_text()))
        self.assertEqual(ec.contract_ref(contract), "asg/admission_baseline/1.0.0@1.0.0")
        self.assertEqual([r["id"] for r in contract["requirements"]],
                         [r["id"] for r in load(baseline_text())["rows"]])
        judged = [r for r in contract["requirements"] if r["id"] == "adjacent-domain"]
        self.assertEqual(judged[0]["backward_verdict"], "MODEL-ASSISTED")
        if jsonschema is not None:
            jsonschema.validate(contract, json.loads(SCHEMA.read_text()))

    def test_compile_writes_the_contract_alone(self):
        with tempfile.TemporaryDirectory(dir=REPO_ROOT / "packs") as tmp:
            out = pathlib.Path(tmp).relative_to(REPO_ROOT)
            run = subprocess.run([sys.executable, "scripts/pack_compile.py", "compile",
                                  str(BASELINE / "pack-source.yaml"), "--out", str(out)],
                                 cwd=REPO_ROOT, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertEqual(json.loads(run.stdout)["scope"], "admission")
            self.assertEqual(sorted(p.name for p in pathlib.Path(tmp).iterdir()), ["contract.json"])


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
        self.assertIn(old, text)
        issues = pack_compile.validate_source(load(text.replace(old, new, 1)))
        self.assertTrue(any(want in i for i in issues), issues)

    def test_a_card_row_deciding_no(self):
        self.assertRefused("    check: card.verified\n    from: T1\n    on_fail: \"LIMIT\"",
                           "    check: card.verified\n    from: T1\n    on_fail: \"NO\"", "a card row may not decide NO")

    def test_a_vouch_row_deciding_no(self):
        self.assertRefused("    check: vouch.distinct_controllers\n    params: {min: 3}            # placeholder\n"
                           "    from: T2\n    on_fail: \"LIMIT\"",
                           "    check: vouch.distinct_controllers\n    params: {min: 3}\n    from: T2\n    on_fail: \"NO\"",
                           "a vouch row may not decide NO")

    def test_a_stake_row_deciding_no(self):
        self.assertRefused("    on_fail: \"record\"", "    on_fail: \"NO\"", "a stake row may not decide NO")

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
        self.assertRefused("    params: {min_days: 60}", "    params: {min: 60}", "needs params.min_days")

    def test_decades_that_do_not_rise(self):
        self.assertRefused("max_decade: {sat: 4, USD: 0}", "max_decade: {sat: 3, USD: 0}", "does not rise")

    def test_an_ask_without_ask(self):
        self.assertRefused('outcomes: ["GO", "ASK", "LIMIT", "NO"]', 'outcomes: ["GO", "LIMIT", "NO"]',
                           "ASK is not in outcomes")

    def test_an_unknown_scope_kind_still_names_admission(self):
        issues = pack_compile.validate_source(load(baseline_text().replace("kind: admission", "kind: admit")))
        self.assertIn("scope.kind 'admit' must be one of ['live', 'after_the_fact', 'admission']", issues)


if __name__ == "__main__":
    unittest.main()
