"""The repository has one skill tree: skills/<name>/ holds each skill's SKILL.md,
a byte-identical AGENTS.md and any assets/ or references/ the skill reads.
Nothing outside skills/ is a skill, and every relative link in the skills and in
the repository's top-level docs resolves.

    python3 -m unittest discover -s tests -p 'test_*.py'
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"

# Markdown files whose relative links must resolve: every skill's text, plus the
# repository docs that point into the skill tree.
LINKED_DOCS = ["README.md", "skills/**/*.md", "docs/*.md", "demo/DEMO.md"]

_LINK = re.compile(r"\]\(([^)\s]+)\)")
_NAME = re.compile(r"\A---\n(?:.*\n)*?name:\s*(\S+)\s*\n(?:.*\n)*?---\n")


def _repo_files(pattern):
    """Files matching pattern, outside dot-directories (.git, a local .venv)."""
    return sorted(p for p in ROOT.glob(pattern)
                  if p.is_file() and not any(part.startswith(".") for part in p.relative_to(ROOT).parts))


def skill_dirs():
    return sorted(p.parent for p in SKILLS.glob("*/SKILL.md"))


def broken_links(path):
    """The relative link targets in path that name no file or directory."""
    broken = []
    for target in _LINK.findall(path.read_text()):
        if re.match(r"[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
            continue
        rel = target.split("#", 1)[0]
        if rel and not (path.parent / rel).exists():
            broken.append(target)
    return broken


class OneSkillTree(unittest.TestCase):
    def test_no_skill_text_outside_skills(self):
        stray = [str(p.relative_to(ROOT)) for name in ("SKILL.md", "AGENTS.md")
                 for p in _repo_files(f"**/{name}") if SKILLS not in p.parents]
        self.assertEqual(stray, [], "skill text outside skills/")

    def test_root_carries_no_skill_assets(self):
        for name in ("SKILL.md", "AGENTS.md", "assets", "references"):
            self.assertFalse((ROOT / name).exists(), f"{name} at the repository root: it belongs under skills/<name>/")

    def test_each_skill_is_named_for_its_directory(self):
        dirs = skill_dirs()
        self.assertIn(SKILLS / "evaluation-compiler", dirs)
        for d in dirs:
            match = _NAME.match((d / "SKILL.md").read_text())
            self.assertIsNotNone(match, f"{d.name}/SKILL.md has no front-matter name")
            self.assertEqual(match.group(1), d.name)

    def test_agents_md_is_a_byte_identical_copy(self):
        for d in skill_dirs():
            self.assertTrue((d / "AGENTS.md").is_file(), f"{d.name} has no AGENTS.md")
            self.assertEqual((d / "AGENTS.md").read_bytes(), (d / "SKILL.md").read_bytes(),
                             f"{d.name}/AGENTS.md differs from its SKILL.md")

    def test_every_relative_link_resolves(self):
        broken = {}
        for pattern in LINKED_DOCS:
            for path in _repo_files(pattern):
                if found := broken_links(path):
                    broken[str(path.relative_to(ROOT))] = found
        self.assertEqual(broken, {})


class BrokenLinkCheckBites(unittest.TestCase):
    def test_a_moved_target_is_reported(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            doc = pathlib.Path(tmp) / "doc.md"
            (pathlib.Path(tmp) / "here.md").write_text("x")
            doc.write_text("[ok](here.md) [anchor](here.md#a) [web](https://example.com) "
                           "[self](#top) [gone](assets/execution.md)")
            self.assertEqual(broken_links(doc), ["assets/execution.md"])


if __name__ == "__main__":
    unittest.main()
