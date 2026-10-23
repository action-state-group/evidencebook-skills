"""Issue #29: the pack's presentation block is sealed by digest in the Result v0.

scripts/wire_presentation.py `seal` pins sha256(JCS(block)) of the block exactly
as it will be wired, as the Result's `x-presentation-digest` member, before
`capsulectl book result build` signs the Result; after disclose the same block
is wired onto the bundle, and `presentation_label` is the page's check:

  - the block matches the sealed digest     -> "producer-signed"
  - one character changed after sealing     -> "unsigned producer text"
  - no block and no digest                  -> no label (renders as today)

Verdicts and counts never depend on it (presentation contract section 6).

    python3 -m unittest discover -s tests -p 'test_*.py'
"""
import copy
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from result_v0 import build_result_v0_for_day  # noqa: E402
from rollup import all_criteria_from_clauses  # noqa: E402
from wire_presentation import (  # noqa: E402
    CARD_FOR_TEMPLATE, DIGEST_ALG, DIGEST_MEMBER, LABEL_SIGNED, LABEL_UNSIGNED, PRODUCER_NOTE_LINES,
    PRODUCER_TERMS_LINE, SEALED_NOTE_LINES, SEALED_TERMS_LINE, WireError,
    block_digest, jcs, prepare_block, presentation_label, seal, sealed_result_of, wire)

AIRLINE = json.loads((ROOT / "demo/airline-support-outcomes/presentation.json").read_text())
EVERYDAY = json.loads((ROOT / "packs/everyday-rules/compiled/presentation.json").read_text())
EU_BLOCK = {"eu-ai-act-compliance/v1": {"enabled": True, "obligations": [
    {"id": "art-50", "title": "Transparency to the people using it", "summary": "Tell people it is an AI."}]}}

CLAUSES = [{"id": "a.one", "check_id": "a"}, {"id": "a.two", "check_id": "a"}]
ALL_CRITERIA = all_criteria_from_clauses(CLAUSES)
ROOT_ID = "c2" * 32


def result_doc():
    tiers = {c: "judged" for c in ALL_CRITERIA}
    verdicts = {"a.one": "met", "a.two": "not_met"}
    digests = {c: "cd" * 32 for c in ALL_CRITERIA}
    return build_result_v0_for_day("day:2026-09-23", [("case-a", verdicts, digests, tiers)],
                                   "2026-09-23T23:59:59Z", ALL_CRITERIA, "some-pack@1.0.0")


def book_bundle(statement):
    """A disclosed bundle in book form: the root record's disclosed agent_input
    is the evidence_result header, the Result document under `statement`
    (the shape `capsulectl disclose` writes for a jsonl book)."""
    return {"root": ROOT_ID,
            "records": [{"capsule_id": ROOT_ID}],
            "disclosures": {ROOT_ID: {"agent_input": {"record_type": "evidence_result", "seq": 66,
                                                      "statement": copy.deepcopy(statement)}}},
            "extensions": {"producer-key/v1": {"public_key": "cd" * 32}}}


def sealed_and_wired(presentation):
    sealed, template, _ = seal(result_doc(), presentation)
    wired, _, _ = wire(book_bundle(sealed), presentation, sealed_digest=sealed[DIGEST_MEMBER])
    return sealed, wired, template


def tamper_one_character(block):
    """Change exactly one character of the first string found in the block."""
    block = copy.deepcopy(block)

    def walk(node):
        items = node.items() if isinstance(node, dict) else enumerate(node)
        for key, value in items:
            if isinstance(value, str) and value and key not in ("enabled",):
                node[key] = value[:-1] + ("X" if value[-1] != "X" else "Y")
                return True
            if isinstance(value, (dict, list)) and walk(value):
                return True
        return False

    assert walk(block), "no string to tamper with"
    return block


class Jcs(unittest.TestCase):
    def test_keys_sort_and_no_whitespace(self):
        self.assertEqual(jcs({"b": 1, "a": [True, None, "x"]}), b'{"a":[true,null,"x"],"b":1}')

    def test_non_ascii_is_written_as_utf8_not_escaped(self):
        self.assertEqual(jcs({"k": "café ·"}), '{"k":"café ·"}'.encode("utf-8"))

    def test_keys_sort_by_utf16_code_units(self):
        # U+1F600 (surrogate pair D83D..) sorts BEFORE U+FF61 in UTF-16, after it by code point.
        self.assertEqual(jcs({"｡": 1, "\U0001F600": 2}),
                         '{"\U0001F600":2,"｡":1}'.encode("utf-8"))

    def test_a_non_integral_number_is_refused(self):
        with self.assertRaises(WireError):
            jcs({"ratio": 0.5})

    def test_digest_is_sha256_of_the_jcs_bytes(self):
        block = {"enabled": True, "z": "last", "a": 1}
        self.assertEqual(block_digest(block), hashlib.sha256(b'{"a":1,"enabled":true,"z":"last"}').hexdigest())


class SealRoundTrip(unittest.TestCase):
    def test_the_sealed_result_carries_the_digest_of_the_block_as_wired(self):
        for name, presentation in (("airline", AIRLINE), ("everyday", EVERYDAY), ("eu", EU_BLOCK)):
            with self.subTest(name):
                sealed, wired, template = sealed_and_wired(presentation)
                member = sealed[DIGEST_MEMBER]
                self.assertEqual(member["template"], template)
                self.assertEqual(member["digest_alg"], DIGEST_ALG)
                self.assertRegex(member["digest"], r"^[0-9a-f]{64}$")
                self.assertEqual(member["digest"], block_digest(wired["extensions"][template]))
                self.assertEqual(presentation_label(wired), (LABEL_SIGNED, template))

    def test_seal_adds_only_the_extension_member(self):
        doc = result_doc()
        sealed, _, _ = seal(doc, AIRLINE)
        self.assertEqual({k: v for k, v in sealed.items() if k != DIGEST_MEMBER}, doc)
        self.assertNotIn(DIGEST_MEMBER, doc, "the input Result must not be modified")
        # an x- member (spec section 8a): a bare name would fail result build's closed schema
        self.assertTrue(DIGEST_MEMBER.startswith("x-"))

    def test_the_member_carries_no_wording(self):
        # section 6: the bundle never supplies the page's wording; the Result pins a digest, not text.
        # AIRLINE opts into contract-report/v1, which carries nothing to sign: the member is unchanged.
        sealed, _, _ = seal(result_doc(), AIRLINE)
        self.assertEqual(set(sealed[DIGEST_MEMBER]), {"template", "digest_alg", "digest"})

    def test_the_sealed_outcome_note_says_the_digest_is_pinned_and_it_is_not_evidence(self):
        _, wired, template = sealed_and_wired(AIRLINE)
        note = wired["extensions"][template]["producer_note"]
        self.assertEqual(note["lines"][0], SEALED_NOTE_LINES[0])
        self.assertIn("not evidence", note["lines"][0])
        self.assertIn(DIGEST_MEMBER, note["lines"][0])

    def test_a_sealed_block_with_terms_never_says_its_wording_is_uncovered(self):
        # review of 5746f2a: the digest covers the whole block, terms included, so the
        # sealed note must not carry the unsealed "no signed record covers either" line
        self.assertIn("terms", AIRLINE["outcome-report/v1"])
        _, wired, template = sealed_and_wired(AIRLINE)
        lines = wired["extensions"][template]["producer_note"]["lines"]
        self.assertEqual(lines, [*SEALED_NOTE_LINES, SEALED_TERMS_LINE])
        self.assertNotIn(PRODUCER_TERMS_LINE, lines)
        text = " ".join(lines)
        self.assertNotIn("no signed record covers", text.lower())
        self.assertIn("sealed digest covers them", SEALED_TERMS_LINE)
        self.assertIn("not evidence", SEALED_TERMS_LINE)
        self.assertIn("does not draw on them", SEALED_TERMS_LINE)

    def test_an_unsealed_block_with_terms_keeps_the_uncovered_terms_line(self):
        _, block, _ = prepare_block(AIRLINE, sealed=False)
        self.assertEqual(block["producer_note"]["lines"], [*PRODUCER_NOTE_LINES, PRODUCER_TERMS_LINE])
        self.assertNotIn(SEALED_TERMS_LINE, block["producer_note"]["lines"])

    def test_a_sealed_block_without_terms_carries_no_terms_line(self):
        bare = {"outcome-report/v1": {"enabled": True}}
        _, block, _ = prepare_block(bare, sealed=True)
        self.assertEqual(block["producer_note"]["lines"], list(SEALED_NOTE_LINES))

    def test_the_label_reads_the_result_from_the_payload_form_too(self):
        sealed, template, _ = seal(result_doc(), AIRLINE)
        bundle = book_bundle(sealed)
        bundle["disclosures"][ROOT_ID] = {"agent_input": copy.deepcopy(sealed)}
        wired, _, _ = wire(bundle, AIRLINE, sealed_digest=sealed[DIGEST_MEMBER])
        self.assertEqual(sealed_result_of(wired)["result_version"], "evidence-result-v0")
        self.assertEqual(presentation_label(wired), (LABEL_SIGNED, template))


class Tamper(unittest.TestCase):
    def test_one_character_changed_after_sealing_reads_as_unsigned_producer_text(self):
        for name, presentation in (("airline", AIRLINE), ("everyday", EVERYDAY), ("eu", EU_BLOCK)):
            with self.subTest(name):
                sealed, wired, template = sealed_and_wired(presentation)
                tampered = copy.deepcopy(wired)
                tampered["extensions"][template] = tamper_one_character(wired["extensions"][template])
                self.assertEqual(presentation_label(tampered), (LABEL_UNSIGNED, template))
                # every verdict and count is unchanged: they live in the sealed claims
                self.assertEqual(sealed_result_of(tampered)["claims"], sealed["claims"])
                self.assertEqual(sealed_result_of(tampered)["aggregate"], sealed["aggregate"])

    def test_a_tampered_digest_in_an_unsigned_copy_of_the_result_still_mismatches(self):
        sealed, wired, template = sealed_and_wired(AIRLINE)
        wired["disclosures"][ROOT_ID]["agent_input"]["statement"][DIGEST_MEMBER]["digest"] = "00" * 32
        self.assertEqual(presentation_label(wired), (LABEL_UNSIGNED, template))

    def test_a_block_with_no_sealed_digest_reads_as_unsigned(self):
        wired, template, _ = wire(book_bundle(result_doc()), AIRLINE)
        self.assertEqual(presentation_label(wired), (LABEL_UNSIGNED, template))

    def test_a_digest_for_a_different_template_reads_as_unsigned(self):
        sealed, wired, template = sealed_and_wired(AIRLINE)
        wired["disclosures"][ROOT_ID]["agent_input"]["statement"][DIGEST_MEMBER]["template"] = \
            "eu-ai-act-compliance/v1"
        self.assertEqual(presentation_label(wired), (LABEL_UNSIGNED, template))

    def test_no_block_and_no_digest_has_no_label(self):
        self.assertEqual(presentation_label(book_bundle(result_doc())), (None, None))
        self.assertEqual(presentation_label({"records": []}), (None, None))

    def test_wiring_refuses_a_block_that_does_not_match_the_sealed_digest(self):
        sealed, _, _ = seal(result_doc(), AIRLINE)
        edited = copy.deepcopy(AIRLINE)
        (template, block), = {k: v for k, v in edited.items() if k in CARD_FOR_TEMPLATE}.items()
        edited[template] = tamper_one_character(block)
        with self.assertRaises(WireError):
            wire(book_bundle(sealed), edited, sealed_digest=sealed[DIGEST_MEMBER])

    def test_seal_refuses_a_result_that_already_carries_a_digest_or_is_not_a_result(self):
        sealed, _, _ = seal(result_doc(), AIRLINE)
        with self.assertRaises(WireError):
            seal(sealed, AIRLINE)
        with self.assertRaises(WireError):
            seal({"claims": []}, AIRLINE)

    def test_sealing_is_deterministic(self):
        a, _, _ = seal(result_doc(), AIRLINE)
        b, _, _ = seal(result_doc(), AIRLINE)
        self.assertEqual(a[DIGEST_MEMBER], b[DIGEST_MEMBER])
        _, block, _ = prepare_block(AIRLINE, sealed=True)
        self.assertEqual(a[DIGEST_MEMBER]["digest"], block_digest(block))


class ReportShOrder(unittest.TestCase):
    """report.sh pins the digest BEFORE book result build, and wires the block
    (checked against the sealed Result) after disclose and before report build."""

    SH = (ROOT / "scripts/report.sh").read_text()

    def _at(self, pattern):
        lines = [i for i, line in enumerate(self.SH.splitlines())
                 if not line.lstrip().startswith("#") and re.search(pattern, line)]
        self.assertEqual(len(lines), 1, f"{pattern!r} should appear on exactly one command line: {lines}")
        return lines[0]

    def test_the_digest_is_pinned_before_result_build_and_wired_after_disclose(self):
        seal_at = self._at(r'wire_presentation\.py" seal ')
        build_at = self._at(r'"\$CAPSULECTL" book result build ')
        disclose_at = self._at(r'"\$CAPSULECTL" disclose ')
        wire_at = self._at(r'wire_presentation\.py" --bundle ')
        label_at = self._at(r'wire_presentation\.py" label ')
        report_at = self._at(r'"\$CAPSULECTL" book report build ')
        self.assertLess(seal_at, build_at)
        self.assertLess(build_at, disclose_at)
        self.assertLess(disclose_at, wire_at)
        self.assertLess(wire_at, label_at)
        self.assertLess(label_at, report_at)

    def test_result_build_seals_the_result_carrying_the_digest(self):
        self.assertIn('RESULT_V0="$SEALED_RESULT_V0"', self.SH)
        self.assertIn('--sealed-result "$WORK/result-sealed.json"', self.SH)


class Cli(unittest.TestCase):
    def _run(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "scripts/wire_presentation.py"), *args],
                              capture_output=True, text=True)

    def test_seal_then_wire_then_label_round_trips_and_a_tamper_flips_the_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            (tmp / "p.json").write_text(json.dumps(AIRLINE))
            (tmp / "r.json").write_text(json.dumps(result_doc()))
            proc = self._run("seal", "--presentation", str(tmp / "p.json"), "--result", str(tmp / "r.json"),
                             "--out", str(tmp / "sealed.json"))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            printed = json.loads(proc.stdout)
            self.assertEqual(printed["card"], "outcome")
            sealed = json.loads((tmp / "sealed.json").read_text())
            self.assertEqual(printed[DIGEST_MEMBER], sealed[DIGEST_MEMBER])
            (tmp / "b.json").write_text(json.dumps(book_bundle(sealed)))
            proc = self._run("--bundle", str(tmp / "b.json"), "--presentation", str(tmp / "p.json"),
                             "--sealed-result", str(tmp / "sealed.json"), "--out", str(tmp / "w.json"))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            proc = self._run("label", "--bundle", str(tmp / "w.json"))
            self.assertEqual(json.loads(proc.stdout), {"template": "outcome-report/v1", "label": LABEL_SIGNED})
            wired = json.loads((tmp / "w.json").read_text())
            wired["extensions"]["outcome-report/v1"]["producer_note"]["title"] += "!"
            (tmp / "w.json").write_text(json.dumps(wired))
            proc = self._run("label", "--bundle", str(tmp / "w.json"))
            self.assertEqual(json.loads(proc.stdout)["label"], LABEL_UNSIGNED)

    def test_wiring_against_a_result_with_no_digest_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            (tmp / "p.json").write_text(json.dumps(AIRLINE))
            (tmp / "r.json").write_text(json.dumps(result_doc()))
            (tmp / "b.json").write_text(json.dumps(book_bundle(result_doc())))
            proc = self._run("--bundle", str(tmp / "b.json"), "--presentation", str(tmp / "p.json"),
                             "--sealed-result", str(tmp / "r.json"), "--out", str(tmp / "w.json"))
            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse((tmp / "w.json").exists())


if __name__ == "__main__":
    unittest.main()
