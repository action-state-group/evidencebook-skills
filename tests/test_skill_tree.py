"""The repository has one skill tree: skills/<name>/ holds each skill's SKILL.md,
a byte-identical AGENTS.md and any assets/ or references/ the skill reads.
Nothing outside skills/ is a skill, and every relative link in the repository's
Markdown resolves, with the case the file system holds (macOS would forgive a
wrong case that Linux and GitHub do not).

The checks walk the working tree, not git's index, so an untracked SKILL.md
(a generated bundle written into the checkout, say) fails them too: generated
bundles belong outside this repository.

    python3 -m unittest discover -s tests -p 'test_*.py'
"""
import os
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"

# Inline links, with or without angle brackets or a title, and reference definitions.
_LINK = re.compile(r"\]\(<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\)|^\s{0,3}\[[^\]]+\]:\s*<?(\S+?)>?(?:\s|$)", re.M)
_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)
_NAME = re.compile(r"^name:\s*(\S+)\s*$", re.M)


def _repo_files(pattern):
    """Files matching pattern, outside dot-directories (.git, a local .venv)."""
    return sorted(p for p in ROOT.glob(pattern)
                  if p.is_file() and not any(part.startswith(".") for part in p.relative_to(ROOT).parts))


def skill_dirs():
    return sorted(p.parent for p in SKILLS.glob("*/SKILL.md"))


def _exists_exactly(base, rel):
    """rel names an entry under base, every component spelled with its case."""
    here = base
    for part in pathlib.PurePosixPath(rel).parts:
        if part in (".", ".."):
            here = here / part
            continue
        if not here.is_dir() or part not in os.listdir(here):
            return False
        here = here / part
    return True


def broken_links(path):
    """The relative link targets in path that name no file or directory."""
    broken = []
    for inline, reference in _LINK.findall(path.read_text()):
        target = inline or reference
        if re.match(r"[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
            continue
        rel = target.split("#", 1)[0]
        if rel and not _exists_exactly(path.parent, rel):
            broken.append(target)
    return broken


def skill_name(text):
    """The name: line of a SKILL.md's front matter, never one from its body."""
    front = _FRONT_MATTER.match(text)
    name = front and _NAME.search(front.group(1))
    return name.group(1) if name else None


class OneSkillTree(unittest.TestCase):
    def test_no_skill_text_outside_skills(self):
        stray = [str(p.relative_to(ROOT)) for name in ("SKILL.md", "AGENTS.md")
                 for p in _repo_files(f"**/{name}") if SKILLS not in p.parents]
        self.assertEqual(stray, [], "skill text outside skills/")

    def test_skill_text_sits_exactly_one_level_down(self):
        misplaced = [str(p.relative_to(ROOT)) for name in ("SKILL.md", "AGENTS.md")
                     for p in _repo_files(f"skills/**/{name}") if p.parent.parent != SKILLS]
        self.assertEqual(misplaced, [], "skill text not at skills/<name>/")
        for d in sorted(p for p in SKILLS.iterdir() if p.is_dir() and not p.name.startswith(".")):
            self.assertTrue((d / "SKILL.md").is_file(), f"skills/{d.name}/ has no SKILL.md")

    def test_root_carries_no_skill_assets(self):
        for name in ("SKILL.md", "AGENTS.md", "assets", "references"):
            self.assertFalse((ROOT / name).exists(), f"{name} at the repository root: it belongs under skills/<name>/")

    def test_each_skill_is_named_for_its_directory(self):
        dirs = skill_dirs()
        self.assertIn(SKILLS / "evaluation-compiler", dirs)
        for d in dirs:
            self.assertEqual(skill_name((d / "SKILL.md").read_text()), d.name,
                             f"{d.name}/SKILL.md's front-matter name")

    def test_agents_md_is_a_byte_identical_copy(self):
        for d in skill_dirs():
            self.assertTrue((d / "AGENTS.md").is_file(), f"{d.name} has no AGENTS.md")
            self.assertEqual((d / "AGENTS.md").read_bytes(), (d / "SKILL.md").read_bytes(),
                             f"{d.name}/AGENTS.md differs from its SKILL.md")

    def test_every_relative_link_resolves(self):
        broken = {}
        for path in _repo_files("**/*.md"):
            found = broken_links(path)
            if found:
                broken[str(path.relative_to(ROOT))] = found
        self.assertEqual(broken, {})


class BrokenLinkCheckBites(unittest.TestCase):
    def test_a_moved_target_is_reported(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            doc = pathlib.Path(tmp) / "doc.md"
            (pathlib.Path(tmp) / "here.md").write_text("x")
            doc.write_text("[ok](here.md) [anchor](here.md#a) [web](https://example.com) "
                           "[self](#top) [gone](assets/execution.md) [titled](gone.md \"t\") "
                           "[angled](<gone2.md>) [case](Here.md)\n[ref]: gone3.md\n[ok-ref]: here.md\n")
            self.assertEqual(broken_links(doc), ["assets/execution.md", "gone.md", "gone2.md", "Here.md", "gone3.md"])

    def test_a_name_only_in_the_body_is_not_the_skill_name(self):
        self.assertIsNone(skill_name("---\ndescription: x\n---\nname: impostor\n"))
        self.assertEqual(skill_name("---\nname: real\ndescription: x\n---\nname: impostor\n"), "real")


if __name__ == "__main__":
    unittest.main()
