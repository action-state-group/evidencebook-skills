"""scripts/wire_presentation.py: a compiled pack's presentation.json block onto a
disclosed bundle's extensions, and the report card it selects.

    python3 -m unittest discover -s tests -p 'test_*.py'
"""
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from wire_presentation import (  # noqa: E402
    CARD_FOR_TEMPLATE, CONTRACT_REPORT_KEY, DIGEST_MEMBER, LABEL_SIGNED, LABEL_UNSIGNED, MAX_NOTE_LINE, MAX_NOTE_LINES,
    MAX_NOTE_TITLE, PRODUCER_NOTE_LINES, PRODUCER_NOTE_TITLE, PRODUCER_TERMS_LINE, WireError,
    presentation_label, seal, wire)

BUNDLE = {"records": [{"capsule_id": "ab" * 32}],
          "extensions": {"producer-key/v1": {"public_key": "cd" * 32}}}


def _load(rel):
    return json.loads((ROOT / rel).read_text())


class ShippedPacks(unittest.TestCase):
    """Every compiled pack in this repo wires, and selects the card that renders it."""

    @unittest.skipUnless((ROOT / "demo/eu-ai-act-obligations/presentation.json").exists(),
                         "the EU AI Act pack lands with PR #8")
    def test_the_eu_pack_wires_its_compliance_block_verbatim_and_selects_the_obligation_card(self):
        presentation = _load("demo/eu-ai-act-obligations/presentation.json")
        wired, template, card = wire(BUNDLE, presentation)
        self.assertEqual((template, card), ("eu-ai-act-compliance/v1", "obligation"))
        self.assertEqual(wired["extensions"]["eu-ai-act-compliance/v1"], presentation["eu-ai-act-compliance/v1"])

    def test_the_airline_pack_wires_its_outcome_report_block_and_selects_the_outcome_card(self):
        presentation = _load("demo/airline-support-outcomes/presentation.json")
        wired, template, card = wire(BUNDLE, presentation)
        self.assertEqual((template, card), ("outcome-report/v1", "outcome"))
        block = dict(wired["extensions"]["outcome-report/v1"])
        note = block.pop("producer_note")
        # the pack's own members ride unchanged; the only addition is the label
        self.assertEqual(block, presentation["outcome-report/v1"])
        self.assertEqual(note, {"title": PRODUCER_NOTE_TITLE,
                                "lines": [*PRODUCER_NOTE_LINES, PRODUCER_TERMS_LINE]})

    def test_every_shipped_outcome_block_is_labelled_producer_supplied(self):
        for rel in ("demo/airline-support-outcomes/presentation.json",
                    "packs/everyday-rules/compiled/presentation.json"):
            with self.subTest(rel):
                wired, _, _ = wire(BUNDLE, _load(rel))
                self.assertIn("producer_note", wired["extensions"]["outcome-report/v1"])

    def test_every_template_the_compiler_registers_has_a_card(self):
        from pack_compile import REPORT_TEMPLATES
        self.assertLessEqual(set(REPORT_TEMPLATES), set(CARD_FOR_TEMPLATE))


class Wire(unittest.TestCase):
    BLOCK = {"eu-ai-act-compliance/v1": {"enabled": True, "obligations": []}}

    def test_existing_extensions_are_kept_and_the_inputs_are_not_modified(self):
        bundle = json.loads(json.dumps(BUNDLE))
        block = json.loads(json.dumps(self.BLOCK))
        wired, _, _ = wire(bundle, block)
        self.assertEqual(wired["extensions"]["producer-key/v1"], BUNDLE["extensions"]["producer-key/v1"])
        self.assertEqual(bundle, BUNDLE)
        self.assertEqual(block, self.BLOCK)
        wired["extensions"]["eu-ai-act-compliance/v1"]["obligations"].append("x")
        self.assertEqual(block, self.BLOCK)

    def test_a_bundle_with_no_extensions_gets_them(self):
        wired, _, _ = wire({"records": []}, self.BLOCK)
        self.assertEqual(list(wired["extensions"]), ["eu-ai-act-compliance/v1"])

    def test_an_unknown_block_is_refused_not_skipped(self):
        # PR #13's first cut looked for outcome-invoice/v1, which no compiled pack
        # carries and no renderer reads: the wiring silently never ran.
        with self.assertRaisesRegex(WireError, "does not know"):
            wire(BUNDLE, {"outcome-invoice/v1": {"enabled": True}})

    def test_two_blocks_are_refused(self):
        both = {"outcome-report/v1": {"enabled": True}, "eu-ai-act-compliance/v1": {"enabled": True}}
        with self.assertRaisesRegex(WireError, "exactly one"):
            wire(BUNDLE, both)

    def test_an_empty_or_non_object_presentation_is_refused(self):
        for bad in ({}, [], None, "x"):
            with self.assertRaises(WireError):
                wire(BUNDLE, bad)

    def test_a_disabled_or_non_object_block_is_refused(self):
        for block in ({"enabled": False}, {}, [], "x"):
            with self.assertRaises(WireError):
                wire(BUNDLE, {"eu-ai-act-compliance/v1": block})

    def test_an_extension_already_on_the_bundle_is_never_overwritten(self):
        bundle = {"extensions": {"eu-ai-act-compliance/v1": {"enabled": True, "regulation": "theirs"}}}
        with self.assertRaisesRegex(WireError, "refusing to overwrite"):
            wire(bundle, self.BLOCK)

    def test_non_object_bundle_or_extensions_are_refused(self):
        for bundle in ([], {"extensions": []}):
            with self.assertRaises(WireError):
                wire(bundle, self.BLOCK)


class ContractReportV1(unittest.TestCase):
    """agent-action-capsule spec/contract-report-v1.md section 1: a producer's
    opt-in, a closed empty object carried beside the pack's own template block.
    It carries nothing to sign, so it never enters the sealed
    x-presentation-digest member: the bundle digest covers it like every
    extension."""

    WITH_BOTH = {"eu-ai-act-compliance/v1": {"enabled": True, "obligations": []}, CONTRACT_REPORT_KEY: {}}

    def test_wired_beside_the_template_block_unchanged(self):
        wired, template, card = wire(BUNDLE, self.WITH_BOTH)
        self.assertEqual((template, card), ("eu-ai-act-compliance/v1", "obligation"))
        self.assertEqual(wired["extensions"][CONTRACT_REPORT_KEY], {})
        self.assertEqual(wired["extensions"]["eu-ai-act-compliance/v1"],
                         self.WITH_BOTH["eu-ai-act-compliance/v1"])

    def test_a_non_empty_block_is_refused_never_wired(self):
        for bad in ({"x": 1}, {"enabled": True}, []):
            with self.subTest(bad=bad):
                presentation = {"eu-ai-act-compliance/v1": {"enabled": True, "obligations": []},
                                CONTRACT_REPORT_KEY: bad}
                with self.assertRaisesRegex(WireError, "must be exactly"):
                    wire(BUNDLE, presentation)

    def test_alone_with_no_template_block_is_refused(self):
        with self.assertRaisesRegex(WireError, "0 report-template block"):
            wire(BUNDLE, {CONTRACT_REPORT_KEY: {}})

    def test_a_pack_that_does_not_opt_in_wires_no_such_key(self):
        wired, _, _ = wire(BUNDLE, Wire.BLOCK)
        self.assertNotIn(CONTRACT_REPORT_KEY, wired["extensions"])

    def test_an_extension_already_on_the_bundle_is_never_overwritten(self):
        bundle = {"extensions": {CONTRACT_REPORT_KEY: {}}}
        with self.assertRaisesRegex(WireError, f"{re.escape(CONTRACT_REPORT_KEY)}.*refusing to overwrite"):
            wire(bundle, self.WITH_BOTH)

    def test_an_opt_in_already_on_the_bundle_is_refused_whatever_presentation_json_says(self):
        bundle = {"extensions": {CONTRACT_REPORT_KEY: {}}}
        without = {"eu-ai-act-compliance/v1": {"enabled": True, "obligations": []}}
        with self.assertRaisesRegex(WireError, f"{re.escape(CONTRACT_REPORT_KEY)}.*refusing to overwrite"):
            wire(bundle, without)

    def test_the_sealed_member_is_the_same_three_keys_with_or_without_the_opt_in(self):
        without = {"eu-ai-act-compliance/v1": {"enabled": True, "obligations": []}}
        sealed_without, _, _ = seal({"result_version": "evidence-result-v0"}, without)
        sealed_with, _, _ = seal({"result_version": "evidence-result-v0"}, self.WITH_BOTH)
        self.assertEqual(sealed_with[DIGEST_MEMBER], sealed_without[DIGEST_MEMBER])
        self.assertEqual(set(sealed_with[DIGEST_MEMBER]), {"template", "digest_alg", "digest"})

    def test_a_result_sealed_before_the_opt_in_wires_and_reads_signed_with_it(self):
        # A Result sealed before this pack opted in, wired with today's
        # presentation.json that carries the opt-in: nothing it signed changed.
        without = {"eu-ai-act-compliance/v1": {"enabled": True, "obligations": []}}
        sealed, _, _ = seal({"result_version": "evidence-result-v0"}, without)
        wired, _, _ = wire(BUNDLE, self.WITH_BOTH, sealed_digest=sealed[DIGEST_MEMBER])
        self.assertEqual(wired["extensions"][CONTRACT_REPORT_KEY], {})
        bundle = {"root": "r", "disclosures": {"r": {"agent_input": sealed}},
                  "extensions": wired["extensions"]}
        self.assertEqual(presentation_label(bundle), (LABEL_SIGNED, "eu-ai-act-compliance/v1"))

    def test_wiring_never_writes_a_non_empty_block_even_when_the_template_block_is_disabled(self):
        # The refusal to wire an unknown/disabled template block must happen
        # before this key is ever copied onto a bundle -- no partial wiring.
        presentation = {"eu-ai-act-compliance/v1": {"enabled": False}, CONTRACT_REPORT_KEY: {}}
        with self.assertRaises(WireError):
            wire(BUNDLE, presentation)


class ProducerNote(unittest.TestCase):
    """Gap 10: the wired block is the producer's text, outside the signed records.
    On the outcome card the page says so through `producer_note`, the one member of
    the block the renderer draws as text, under its own "Producer's note ... not
    evidence" label (agent-action-capsule ts/src/outcome-report-presentation.ts)."""

    OUTCOME = {"outcome-report/v1": {"enabled": True, "percentages": False}}

    def _note(self, presentation):
        wired, _, _ = wire(BUNDLE, presentation)
        return wired["extensions"]["outcome-report/v1"]["producer_note"]

    def test_the_note_says_the_producer_added_it_and_no_signed_record_covers_it(self):
        note = self._note(self.OUTCOME)
        text = " ".join(note["lines"])
        self.assertIn("producer added", text)
        self.assertIn("after it was disclosed", text)
        self.assertIn("No signed record covers", text)
        self.assertIn("not evidence", text)

    def test_the_terms_line_appears_only_when_the_block_carries_the_packs_wording(self):
        self.assertEqual(self._note(self.OUTCOME)["lines"], list(PRODUCER_NOTE_LINES))
        with_terms = {"outcome-report/v1": {"enabled": True, "terms": {"checks": []}}}
        self.assertEqual(self._note(with_terms)["lines"][-1], PRODUCER_TERMS_LINE)
        with_codes = {"outcome-report/v1": {"enabled": True, "reason_codes": {}}}
        self.assertEqual(self._note(with_codes)["lines"][-1], PRODUCER_TERMS_LINE)

    def test_the_note_is_inside_the_renderers_limits_so_it_is_never_dropped(self):
        # readProducerNote drops a note whole if any line is empty or over-long,
        # or there are too many lines -- which would leave the page unlabelled.
        presentation = _load("demo/airline-support-outcomes/presentation.json")
        note = self._note(presentation)
        self.assertLessEqual(len(note["lines"]), MAX_NOTE_LINES)
        self.assertTrue(0 < len(note["title"].strip()) and len(note["title"]) <= MAX_NOTE_TITLE)
        for line in note["lines"]:
            self.assertIsInstance(line, str)
            self.assertTrue(0 < len(line.strip()) and len(line) <= MAX_NOTE_LINE, line)

    def test_a_note_the_block_already_carries_is_kept_and_the_label_appended(self):
        own = {"title": "What changed in this run", "lines": ["Rerun after the r22 retune."]}
        note = self._note({"outcome-report/v1": {"enabled": True, "producer_note": own}})
        self.assertEqual(note["title"], own["title"])
        self.assertEqual(note["lines"], [*own["lines"], *PRODUCER_NOTE_LINES])

    def test_a_note_the_renderer_would_drop_is_refused_not_wired(self):
        full = {"title": "t", "lines": ["x"] * MAX_NOTE_LINES}
        for bad in (full, {"title": "t", "lines": ["y" * (MAX_NOTE_LINE + 1)]},
                    {"title": "t" * (MAX_NOTE_TITLE + 1), "lines": ["x"]},
                    {"title": "t", "lines": [""]}, {"title": "t", "lines": "x"}, "x"):
            with self.subTest(bad=bad), self.assertRaisesRegex(WireError, "producer_note"):
                wire(BUNDLE, {"outcome-report/v1": {"enabled": True, "producer_note": bad}})

    def test_the_eu_block_is_copied_verbatim_with_no_note_its_renderer_would_not_read(self):
        # The obligation card reads no producer_note; it labels the producer's
        # mapping itself, so a note there would be text no reader ever sees.
        wired, _, _ = wire(BUNDLE, Wire.BLOCK)
        self.assertEqual(wired["extensions"]["eu-ai-act-compliance/v1"], Wire.BLOCK["eu-ai-act-compliance/v1"])

    def test_the_input_block_is_not_modified(self):
        presentation = json.loads(json.dumps(self.OUTCOME))
        wire(BUNDLE, presentation)
        self.assertEqual(presentation, self.OUTCOME)


class Cli(unittest.TestCase):
    def _run(self, bundle, presentation):
        with tempfile.TemporaryDirectory() as d:
            d = pathlib.Path(d)
            (d / "b.json").write_text(json.dumps(bundle))
            (d / "p.json").write_text(json.dumps(presentation))
            proc = subprocess.run([sys.executable, str(ROOT / "scripts/wire_presentation.py"),
                                   "--bundle", str(d / "b.json"), "--presentation", str(d / "p.json"),
                                   "--out", str(d / "o.json")], capture_output=True, text=True)
            out = json.loads((d / "o.json").read_text()) if (d / "o.json").exists() else None
            return proc, out

    def test_prints_the_template_and_card_and_writes_the_wired_bundle(self):
        proc, out = self._run(BUNDLE, Wire.BLOCK)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), {"template": "eu-ai-act-compliance/v1", "card": "obligation"})
        self.assertIn("eu-ai-act-compliance/v1", out["extensions"])

    def test_a_refusal_exits_non_zero_and_writes_nothing(self):
        proc, out = self._run(BUNDLE, {"outcome-invoice/v1": {"enabled": True}})
        self.assertEqual(proc.returncode, 1)
        self.assertIn("does not know", proc.stderr)
        self.assertIsNone(out)


if __name__ == "__main__":
    unittest.main()
