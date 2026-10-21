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

# CommonMark inline links (bare or <angle-bracketed> destination, with an optional
# "double", 'single' or (paren) title) and reference definitions, not footnotes.
_TITLE = r"""(?:\s+(?:"[^"]*"|'[^']*'|\([^)]*\)))?"""
_LINK = re.compile(r"\]\(\s*(?:<([^>\n]*)>|([^)\s]+))" + _TITLE + r"\s*\)"
                   r"|^ {0,3}\[(?!\^)[^\]]+\]:\s*(?:<([^>\n]*)>|(\S+))", re.M)
# Code is not Markdown: fenced blocks (an unclosed one runs to the end of the
# file) and one-line code spans are dropped before links are read. Indented code
# blocks are not told apart from list continuations, so they are read: a link
# example there fails loudly rather than a real broken link passing.
# A backtick fence's info string holds no backtick (CommonMark), so a line like
# ```js``` x is a code span, not an unclosed fence that would swallow the file.
_FENCED = re.compile(r"^ {0,3}(?:(`{3,})[^`\n]*|(~{3,})[^\n]*)$.*?(?:^ {0,3}(?:\1`*|\2~*)[ \t]*$|\Z)",
                     re.M | re.S)
_CODE_SPAN = re.compile(r"(`+)(?!`)[^\n]*?(?<!`)\1(?!`)")
_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)
_NAME = re.compile(r"^name:\s*(\S+)\s*$", re.M)


def _repo_files(pattern):
    """Files matching pattern, outside dot-directories (.git, a local .venv)."""
    return sorted(p for p in ROOT.glob(pattern)
                  if p.is_file() and not any(part.startswith(".") for part in p.relative_to(ROOT).parts))


def skill_dirs():
    return sorted(p.parent for p in SKILLS.glob("*/SKILL.md"))


def _exists_exactly(base, rel):
    """rel names an entry under base that resolves (no dangling symlink), every
    component spelled with its case. A leading / is the repository root, as
    GitHub reads it."""
    if rel.startswith("/"):
        base, rel = ROOT, rel.lstrip("/")
    here = base
    for part in pathlib.PurePosixPath(rel).parts:
        if not here.is_dir():
            return False
        if part not in (".", "..") and part not in os.listdir(here):
            return False
        here = here / part
    return here.exists()


def _prose(text):
    """text with its code blocks and code spans removed."""
    return _CODE_SPAN.sub("", _FENCED.sub("", text))


def broken_links(path):
    """The relative link targets in path that name no file or directory."""
    broken = []
    for groups in _LINK.findall(_prose(path.read_text())):
        target = next((g for g in groups if g), "")
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

    def test_every_link_form_is_read_and_code_is_not(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            (base / "here.md").write_text("x")
            (base / "dangling.md").symlink_to(base / "nowhere.md")
            doc = base / "doc.md"
            doc.write_text("[a](single.md 'title') [b](paren.md (title)) [c](<has space.md>)\n"
                           "[d](dangling.md) [e](here.md/../here.md) [f](/root-gone.md)\n"
                           "[g](here.md \"t\") [h](<here.md>)\n[^1]: footnote.md\n\n"
                           "```\n[code](fenced.md)\n```\n\n"
                           "a `[span](spanned.md)` and ``[span](double.md)`` in prose\n\n"
                           "- item\n\n    [continued](list-gone.md)\n\n"
                           "a stray ` here\n\nand [after](after-gone.md) a ` there\n\n"
                           "```js``` is a span, not a fence\n\n[spanned-fence](span-gone.md)\n\n"
                           "~~~\n[tilde](tilde.md)\n~~~~\n\n"
                           "```\n[unclosed](fence.md)\n")
            self.assertEqual(broken_links(doc), ["single.md", "paren.md", "has space.md", "dangling.md",
                                                 "here.md/../here.md", "/root-gone.md", "list-gone.md",
                                                 "after-gone.md", "span-gone.md"])

    def test_a_name_only_in_the_body_is_not_the_skill_name(self):
        self.assertIsNone(skill_name("---\ndescription: x\n---\nname: impostor\n"))
        self.assertEqual(skill_name("---\nname: real\ndescription: x\n---\nname: impostor\n"), "real")


if __name__ == "__main__":
    unittest.main()
