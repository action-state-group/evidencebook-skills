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


if __name__ == "__main__":
    unittest.main()
