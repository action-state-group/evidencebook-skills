"""Agent skills teach five verbs and nothing else (Steven's ruling, ops u632; asg-agent-team-ethan#391).

Each agent skill maps check, record, ask, verify and show to existing commands in one table, "The five verbs",
and names no expert command in its own text: setup, operations, judging and `x-deal-v0` sales live in its
references/ when it still needs them (skills/README.md, "Two kinds of skill").

    python3 -m unittest discover -s tests -p 'test_*.py'
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"

AGENT_SKILLS = ("buy-with-evidence", "sell-with-evidence", "adjudicate-deal", "evidencebook-report")
PACK_AUTHOR_SKILLS = ("evaluation-compiler", "evidence-contract-compile", "daily-judge-and-close",
                      "weekly-blind-expert", "terms-pack-author")
VERBS = {"check", "record", "ask", "verify", "show"}

# The taught paths that became expert commands (the plan on asg-agent-team-ethan#391, issuecomment-7159138897,
# section 1: setup and operations, pack authoring, and the x-deal-v0 sale path).
EXPERT = (
    "store init", "profile create", "profile update", "plugin install", "plugin ls", "plugin remove",
    "deal init", "deal set-version", "deal tick", "deal audit-host", "book doctor", "cll checkpoint cadence",
    "settlement", "book window", "discover",
    "contract validate", "contract diff", "judge", "calibration", "book backfill", "book close",
    "book result derived-inputs",
    "deal open", "deal sale",
)
_CODE_SPAN = re.compile(r"(`+)(?!`)([^\n]*?)(?<!`)\1(?!`)")
_PATHS = "|".join(re.escape(e) for e in EXPERT)
_ONE_WORD = "|".join(re.escape(e) for e in EXPERT if " " not in e)
_MULTI = "|".join(re.escape(e) for e in EXPERT if " " in e)
# A path after `capsulectl`, a bare multi-word path, or a bare one-word path with arguments after it: a bare
# one-word span such as `settlement` is also the name of a pack's card (evidencebook-report), not the command.
_EXPERT = re.compile(r"^(?:capsulectl(?:-book|-deal)?\s+(" + _PATHS + r")(?:\s|$)|(" + _MULTI + r")(?:\s|$)|("
                     + _ONE_WORD + r")\s)")


def expert_commands_named(text):
    """The expert command paths text names in its code spans."""
    return sorted({m.group(1) or m.group(2) or m.group(3) for _, span in _CODE_SPAN.findall(text) if (m := _EXPERT.match(span.strip()))})


def verb_table_rows(text):
    """The first cell of each body row of the skill's "The five verbs" table."""
    section = text.split("\n## The five verbs\n", 1)[1].split("\n## ", 1)[0]
    rows = [line for line in section.splitlines() if line.startswith("|")]
    return [row.split("|")[1].strip() for row in rows[2:]]


class FiveVerbs(unittest.TestCase):
    def test_the_lists_cover_every_skill(self):
        self.assertEqual(sorted(p.name for p in SKILLS.iterdir() if (p / "SKILL.md").is_file()),
                         sorted(AGENT_SKILLS + PACK_AUTHOR_SKILLS))

    def test_each_agent_skill_maps_only_the_five_verbs(self):
        for name in AGENT_SKILLS:
            text = (SKILLS / name / "SKILL.md").read_text()
            self.assertIn("\n## The five verbs\n", text, name)
            verbs = verb_table_rows(text)
            self.assertTrue(verbs, name)
            self.assertLessEqual(set(verbs), VERBS, name)

    def test_no_agent_skill_names_an_expert_command(self):
        for name in AGENT_SKILLS:
            self.assertEqual(expert_commands_named((SKILLS / name / "SKILL.md").read_text()), [], name)

    def test_the_expert_commands_kept_are_in_references(self):
        kept = expert_commands_named((SKILLS / "evidencebook-report" / "references" / "expert.md").read_text())
        self.assertEqual(kept, ["book doctor", "judge"])

    def test_each_pack_author_skill_says_so(self):
        for name in PACK_AUTHOR_SKILLS:
            self.assertIn("> **Pack-author skill.**", (SKILLS / name / "SKILL.md").read_text(), name)

    def test_the_agent_skills_name_the_mesh_exception(self):
        for name in ("buy-with-evidence", "sell-with-evidence", "evidencebook-report"):
            flat = " ".join((SKILLS / name / "SKILL.md").read_text().split())
            self.assertIn("Mesh's own exception, not a second commerce card", flat, name)

    def test_the_check_sees_an_expert_command(self):
        self.assertEqual(expert_commands_named("run `capsulectl judge pin FILE` and `deal sale new`"),
                         ["deal sale", "judge"])
        self.assertEqual(expert_commands_named("`store init`, `plugin ls` and `deal tick`"),
                         ["deal tick", "plugin ls", "store init"])
        self.assertEqual(expert_commands_named("`deal standard-history card`, `book report check`, `settlement`"), [])


if __name__ == "__main__":
    unittest.main()
