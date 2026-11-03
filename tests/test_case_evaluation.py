"""The evaluation-compiler's per-case report is `case-evaluation/v1`, not the AAC Judge
Record Family's `evaluation-report/v1` (evidencebook-skills#115, after #113). Its skill,
templates and docs must not claim the JF name, except to say how a reader treats records
sealed under the legacy name: only with `axis_judgments` and no `cases[]`.

    python3 -m unittest discover -s tests -p 'test_*.py'
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FILES = ([ROOT / "README.md", ROOT / "docs" / "calibration-sampling-spec.md", ROOT / "demo" / "DEMO.md",
          ROOT / "demo" / "slides" / "demo-deck.md"]
         + sorted((ROOT / "skills" / "evaluation-compiler").rglob("*.md")))
LEGACY = "evaluation-report/v1"


class CaseEvaluationName(unittest.TestCase):
    def test_docs_name_case_evaluation(self):
        for f in FILES:
            self.assertNotIn("evaluation-report Capsule", f.read_text(), f)
        text = (ROOT / "skills/evaluation-compiler/assets/execution.md").read_text()
        self.assertIn("spec_version: case-evaluation/v1", text)
        self.assertNotIn("2026-11-03", text)

    def test_legacy_name_only_with_the_shape_rule(self):
        for f in FILES:
            for para in re.split(r"\n\s*\n", f.read_text()):
                if LEGACY in para:
                    self.assertIn("`cases[]`", para, f"{f}: legacy name without the shape rule")
                    self.assertIn("axis_judgments", para, f)

    def test_every_reader_states_the_rule(self):
        for name in ("aggregation", "sampling", "calibration"):
            text = (ROOT / "skills/evaluation-compiler/assets" / f"{name}.md").read_text()
            self.assertIn(LEGACY, text, name)
            self.assertIn("`axis_judgments` and no `cases[]`", text, name)


if __name__ == "__main__":
    unittest.main()
