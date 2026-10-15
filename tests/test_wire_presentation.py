"""scripts/wire_presentation.py: a compiled pack's presentation.json block onto a
disclosed bundle's extensions, and the report card it selects.

    python3 -m unittest discover -s tests -p 'test_*.py'
"""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from wire_presentation import CARD_FOR_TEMPLATE, WireError, wire  # noqa: E402

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
        self.assertEqual(wired["extensions"]["outcome-report/v1"], presentation["outcome-report/v1"])

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
