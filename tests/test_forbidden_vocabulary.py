"""No forbidden-vocabulary term (vocab/forbidden-vocabulary.yaml) appears in
any string packs/everyday-rules/pack-source.yaml compiles to, or
scripts/judge_bundle.py and scripts/judges/jev_judge.py's disclosed_facts
mode can emit.

    python3 -m unittest discover -s tests -p 'test_*.py'
"""
import pathlib
import re
import sys
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "judges"))

import pack_compile  # noqa: E402
import jev_judge  # noqa: E402
import judge_bundle  # noqa: E402

VOCAB_PATH = ROOT / "vocab" / "forbidden-vocabulary.yaml"


def load_entries():
    return yaml.safe_load(VOCAB_PATH.read_text())["entries"]


_QUOTE_PAIRS = {"`": "`", "'": "'", '"': '"'}


def _is_quoted_mention(text, start, end):
    """True when the match is wrapped in matching quotes or backticks -- the
    vocabulary file's own `quoted_mention_allowed` rule: that wraps a wire value
    being named, not the property being claimed."""
    if start == 0 or end >= len(text):
        return False
    before, after = text[start - 1], text[end]
    return _QUOTE_PAIRS.get(before) == after


def hits(entry, text):
    """Every match of entry's pattern in text that does not lie wholly inside one
    of its `allow` contexts -- the same rule the vocabulary file's own header
    documents: "a match lying wholly inside an allow match is not a hit" -- and,
    for an entry marked `quoted_mention_allowed`, is not itself wrapped in
    matching quotes/backticks."""
    pattern = re.compile(entry["pattern"])
    allow_spans = []
    for allow_pattern in entry.get("allow") or []:
        allow_spans.extend(m.span() for m in re.finditer(allow_pattern, text))
    found = []
    for m in pattern.finditer(text):
        # "If it has one capture group, the group is the matched word (used for
        # line/quote checks)" -- the vocabulary file's own header convention: a
        # pattern with a group may match a leading context char (e.g.
        # witnessed-bare's non-capturing `[^\w-]` prefix) that is not itself part
        # of the word a surrounding quote would wrap.
        word_start, word_end = (m.start(1), m.end(1)) if pattern.groups else (m.start(), m.end())
        if any(a_start <= m.start() and m.end() <= a_end for a_start, a_end in allow_spans):
            continue
        if entry.get("quoted_mention_allowed") and _is_quoted_mention(text, word_start, word_end):
            continue
        found.append(m.group(0))
    return found


def compiled_pack_strings():
    source = pack_compile._strip_strings(yaml.safe_load((ROOT / "packs" / "everyday-rules" / "pack-source.yaml").read_text()))
    compiled, axes, prompt, presentation = pack_compile.compile_pack(source, "packs/everyday-rules/compiled")
    strings = [prompt, source["outcome_statement"], source["resolution_rule"], source.get("decision_note", ""),
              source.get("switches_note", ""), source.get("judge_batch_note", "")]
    for clause in compiled["clauses"]:
        strings += [clause["label"], clause["claim"], clause.get("scope_note", "")]
    for item in source["judge"]["evidence"]:
        strings.append(item)
    strings.append(source["judge"]["citation_note"])
    return [s for s in strings if s]


def judge_bundle_static_strings():
    """Every fixed string scripts/judge_bundle.py can emit as a `rationale` or
    reason on a fail-closed row -- never the judge's own free-text answer, which
    this script does not author and cannot vocabulary-gate here."""
    return [judge_bundle.REASON_PAYLOAD_WITHHELD, judge_bundle.REASON_RECORD_DECLARED_MISSING,
            judge_bundle.REASON_RECORD_NOT_FOUND, judge_bundle.REASON_NOTHING_DISCLOSED]


def jev_judge_disclosed_facts_strings():
    return [jev_judge.DISCLOSED_FACTS_INSTRUCTION_TEMPLATE, jev_judge.DISCLOSED_FACTS_OUT_OF_SCOPE_INSTRUCTIONS,
            *jev_judge.DISCLOSED_FACTS_CHOICE_OPTIONS.values(), *jev_judge.DISCLOSED_FACTS_OUT_OF_SCOPE_OPTION.values()]


class VocabularyGateSelfCheck(unittest.TestCase):
    """Each entry's own hit/pass examples (vocab/forbidden-vocabulary.yaml's own
    documented self-test) -- confirms this test's regex handling (allow contexts,
    RE2-vs-Python-re compatibility) agrees with the file's own stated behaviour
    before trusting it to clear this pack's text."""

    def test_every_entry_hit_and_pass_examples_behave_as_documented(self):
        for entry in load_entries():
            for example in entry.get("hit") or []:
                self.assertTrue(hits(entry, example), f"{entry['id']!r} should hit on {example!r}")
            for example in entry.get("pass") or []:
                self.assertFalse(hits(entry, example), f"{entry['id']!r} should NOT hit on {example!r}")


class EverydayRulesPackIsClean(unittest.TestCase):
    def test_no_forbidden_term_in_any_compiled_pack_string(self):
        entries = load_entries()
        for text in compiled_pack_strings():
            for entry in entries:
                found = hits(entry, text)
                self.assertFalse(found, f"forbidden term {entry['id']!r} ({found!r}) in: {text!r}")


class JudgeBundleOutputIsClean(unittest.TestCase):
    def test_no_forbidden_term_in_judge_bundle_reason_strings(self):
        entries = load_entries()
        for text in judge_bundle_static_strings():
            for entry in entries:
                found = hits(entry, text)
                self.assertFalse(found, f"forbidden term {entry['id']!r} ({found!r}) in: {text!r}")

    def test_no_forbidden_term_in_jev_judge_disclosed_facts_mode_strings(self):
        entries = load_entries()
        for text in jev_judge_disclosed_facts_strings():
            for entry in entries:
                found = hits(entry, text)
                self.assertFalse(found, f"forbidden term {entry['id']!r} ({found!r}) in: {text!r}")


if __name__ == "__main__":
    unittest.main()
