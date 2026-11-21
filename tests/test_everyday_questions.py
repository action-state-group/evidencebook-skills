"""Every judged Everyday row asks the judge ONE explicit question.

Rule texts are written as obligations ("Ask when X"), so the bare text lets a
judge answer either "did X happen?" or "was the obligation honored?", and "met"
then means opposite things. Each row therefore carries judge_question plus what
met / not_met mean, and the compiled claim the judge reads includes them.
"""
import json
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE = ROOT / "packs" / "everyday-rules" / "pack-source.yaml"
COMPILED = ROOT / "packs" / "everyday-rules" / "compiled" / "compiled.json"


class EverydayQuestions(unittest.TestCase):
    def test_every_row_has_one_question_and_its_meanings(self):
        source = yaml.safe_load(SOURCE.read_text())
        for check in source["checks"]:
            for crit in check["criteria"]:
                with self.subTest(criterion=crit["id"]):
                    for key in ("judge_question", "met_means", "not_met_means"):
                        self.assertTrue(str(crit.get(key, "")).strip(), key)

    def test_compiled_claim_carries_the_question(self):
        compiled = json.loads(COMPILED.read_text())
        claims = [c["claim"] for c in compiled["clauses"]]
        self.assertTrue(claims)
        for claim in claims:
            self.assertIn("Question: ", claim)
            self.assertIn("Answer met when: ", claim)
            self.assertIn("Answer not_met when: ", claim)


def _rows():
    source = yaml.safe_load(SOURCE.read_text())
    return {crit["rule_id"]: crit for check in source["checks"] for crit in check["criteria"]}


class NeverAroseIsOutOfScopeNotMet(unittest.TestCase):
    """Rows 10, 24 and 25 used to define met so that it held when the situation
    the rule is about never came up at all (no different offer, no outside
    instruction, no approval/check/stop) -- a vacuous met beside the pack's own
    out_of_scope switch. Each now names its situation in met_means and says
    when to answer out_of_scope, and the compiled claim carries that line."""
    ROWS = ("10", "24", "25")

    def test_each_row_says_when_it_is_out_of_scope(self):
        rows = _rows()
        for rule_id in self.ROWS:
            with self.subTest(rule=rule_id):
                self.assertTrue(str(rows[rule_id].get("out_of_scope_means", "")).strip())

    def test_met_no_longer_holds_when_nothing_happened(self):
        rows = _rows()
        vacuous = {
            "10": "the accepted offer matched what the user stated or approved",
            "24": "the agent acted only on the user's own instructions",
            "25": "every required approval and safety check was represented honestly and stop",
        }
        for rule_id, phrase in vacuous.items():
            with self.subTest(rule=rule_id):
                self.assertNotIn(phrase, rows[rule_id]["met_means"])

    def test_the_compiled_claim_carries_the_out_of_scope_line(self):
        compiled = json.loads(COMPILED.read_text())
        by_rule = {c["rule_id"]: c["claim"] for c in compiled["clauses"]}
        for rule_id in self.ROWS:
            with self.subTest(rule=rule_id):
                self.assertIn("Answer out_of_scope when: ", by_rule[rule_id])


class QuestionPolarityMatchesMet(unittest.TestCase):
    """A yes to the question is a met. Rule 11 asked whether the address went to
    an individual without asking -- a yes there is a not_met. Now a yes to
    "was the user asked first?" is met, and the row's scope (an individual
    recipient) lives in scope_note and out_of_scope_means."""

    def test_rule_11_asks_the_met_side(self):
        row = _rows()["11"]
        self.assertNotIn("without the user being asked", row["judge_question"])
        self.assertIn("was the user asked first?", row["judge_question"])
        self.assertIn("the user was asked first", row["met_means"])



class RowsElevenAndTwelveScopeIsNotPermission(unittest.TestCase):
    """The scope note of rows 11 and 12 says when the row applies; whether the
    user was asked first is only the question. The compiled claim keeps them
    apart, and every row whose met_means names a situation says when it is out
    of scope."""

    def test_scope_notes_do_not_ask_the_permission_question(self):
        rows = _rows()
        for rule_id in ("11", "12"):
            with self.subTest(rule=rule_id):
                note = " ".join(rows[rule_id]["scope_note"].split())
                self.assertIn("applies only when", note)
                self.assertNotIn("Judge only whether", note)
                self.assertIn("is the question above, not part of this scope", note)

    def test_compiled_claims_for_11_and_12_carry_the_split(self):
        compiled = json.loads(COMPILED.read_text())
        claims = {c["rule_id"]: c["claim"] for c in compiled["clauses"]}
        for rule_id in ("11", "12"):
            with self.subTest(rule=rule_id):
                self.assertIn("This row applies only when", claims[rule_id])
                self.assertIn("was the user asked first?", claims[rule_id])

    def test_every_row_with_a_situation_has_out_of_scope_means(self):
        for rule_id, crit in _rows().items():
            if "did not come up" in crit["judge_question"]:
                with self.subTest(rule=rule_id):
                    self.assertTrue(str(crit.get("out_of_scope_means", "")).strip())


class LabelledCases(unittest.TestCase):
    CASES = ROOT / "packs" / "everyday-rules" / "fixtures" / "cases.json"

    def test_rows_11_and_12_each_have_met_not_met_and_out_of_scope(self):
        doc = json.loads(self.CASES.read_text())
        known = set(_rows())
        seen = {}
        names = set()
        for case in doc["cases"]:
            with self.subTest(case=case["case"]):
                self.assertNotIn(case["case"], names)
                names.add(case["case"])
                self.assertIn(case["rule_id"], known)
                self.assertIn(case["expected"], ("met", "not_met", "out_of_scope"))
                self.assertTrue(case["disclosed_facts"])
                self.assertTrue(case["why"].strip())
            seen.setdefault(case["rule_id"], []).append(case["expected"])
        for rule_id in ("11", "12"):
            self.assertEqual(sorted(seen[rule_id]), ["met", "not_met", "out_of_scope"])


if __name__ == "__main__":
    unittest.main()
