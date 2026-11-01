"""scripts/chart_views.py: the calendar, timeline and co-failure declarations a pack
compiles into presentation.json, and their wiring (evidencebook-skills#94).

    python3 -m unittest tests.test_chart_views
"""
import copy
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import chart_views  # noqa: E402
import wire_presentation  # noqa: E402
from chart_views import BLOCK_KEY, PACK_VIEWS, build_block, validate  # noqa: E402


def lane(**kw):
    out = {"id": "activity", "role": "activity", "where": [("record_type", "case")]}
    out.update(kw)
    return out


class Registry(unittest.TestCase):
    def test_every_registered_declaration_is_valid(self):
        self.assertEqual(chart_views.check_registry(), [])

    def test_terms_pack_calendar_has_roles_classes_and_wording(self):
        block = build_block("airline-support-outcomes")
        (cal,) = block["charts"]
        self.assertEqual(cal["view"], "calendar")
        self.assertEqual([l["role"] for l in cal["lanes"]], ["activity", "judgment", "adjudication"])
        judgment = cal["lanes"][1]
        self.assertEqual(set(judgment["classes"].values()), {"good", "bad", "open"})
        self.assertNotIn("classes", cal["lanes"][0])
        w = block["wording"]
        self.assertEqual((w["calendar.activity"], w["calendar.class.good"], w["calendar.class.bad"]),
                         ("conversations", "resolved", "missed"))

    def test_eu_pack_has_the_four_timeline_lanes_and_a_cofailure(self):
        block = build_block("eu-ai-act-obligations")
        views = {c["view"]: c for c in block["charts"]}
        self.assertEqual(set(views), {"calendar", "timeline", "co-failure"})
        titles = [block["wording"][f"lane.{l['id']}.title"] for l in views["timeline"]["lanes"]]
        self.assertEqual(titles, ["Routed to a person", "Effects not confirmed", "Incident flags",
                                  "Adjudications · close"])
        self.assertEqual({l["mark"] for l in views["timeline"]["lanes"]}, {"tick", "diamond"})
        self.assertEqual(views["co-failure"]["subject"], "statement.session")
        self.assertEqual(views["co-failure"]["count"]["chart"]["encoding"]["color"]["field"],
                         "statement.requirement")
        w = block["wording"]
        self.assertEqual((w["calendar.activity"], w["calendar.class.good"], w["calendar.class.bad"]),
                         ("sessions", "met all", "did not"))

    def test_a_pack_without_views_gets_no_block(self):
        self.assertIsNone(build_block("inference-deals"))

    def test_specs_are_declarations_without_a_statement_or_window(self):
        for pid in PACK_VIEWS:
            for view in build_block(pid)["charts"]:
                charts = [l["chart"] for l in view.get("lanes", [])] + ([view["count"]["chart"]] if "count" in view else [])
                for c in charts:
                    self.assertNotIn("usermeta", c)
                    self.assertEqual(c["data"], {"name": "dataset"})
                    self.assertEqual(c["encoding"]["x"]["timeUnit"], "utcyearmonthdate")
                    # no range filter: the builder adds the sealed window
                    self.assertNotIn("range", str(c["transform"]))

    def test_keyed_lane_is_a_rect_and_plain_lane_a_bar(self):
        (cal,) = build_block("airline-support-outcomes")["charts"]
        self.assertEqual(cal["lanes"][0]["chart"]["mark"], "bar")
        self.assertEqual(cal["lanes"][1]["chart"]["mark"], "rect")
        self.assertEqual(cal["lanes"][1]["chart"]["encoding"]["y"]["field"], "statement.verdict")

    def test_build_is_deterministic(self):
        self.assertEqual(build_block("eu-ai-act-obligations"), build_block("eu-ai-act-obligations"))


class Validate(unittest.TestCase):
    def ok(self, **extra):
        d = {"calendar": [lane()]}
        d.update(extra)
        return d

    def test_minimal_is_valid(self):
        self.assertEqual(validate(self.ok()), [])

    def test_each_refusal(self):
        cases = {
            "role twice": {"calendar": [lane(), lane(id="b")]},
            "unknown role": {"calendar": [lane(role="x")]},
            "class not good/bad/open": {"calendar": [lane(key="k", classes={"a": "great"})]},
            "classes without key": {"calendar": [lane(classes={"a": "good"})]},
            "judgment without classes": {"calendar": [lane(role="judgment", key="k")]},
            "duplicate id": {"calendar": [lane(role=None), lane(role=None)]},
            "bad id": {"calendar": [lane(id="Bad Id")]},
            "timeline mark missing": {"timeline": [lane(role=None)]},
            "timeline role": {"timeline": [lane(mark="tick")]},
            "empty where": {"calendar": [lane(where=[])]},
            "cofail without subject": {"cofail": {"id": "c", "where": [("a", "b")], "key": "k"}},
            "stray member": {"calendar": [lane()], "extra": 1},
            "wording key unknown": {"calendar": [lane()], "wording": {"nope": "x"}},
            "lane title without lane": {"calendar": [lane()], "wording": {"lane.zz.title": "x"}},
            "empty wording": {"calendar": [lane()], "wording": {"calendar.activity": " "}},
        }
        for name, decl in cases.items():
            decl = {k: v for k, v in decl.items()}
            if name == "role twice":
                decl["calendar"][1]["role"] = "activity"
            with self.subTest(name):
                self.assertNotEqual(validate(decl), [], name)


class Wire(unittest.TestCase):
    def presentation(self):
        return {"outcome-report/v1": {"enabled": True, "percentages": False, "terms": {}, "reason_codes": {}},
                BLOCK_KEY: build_block("airline-support-outcomes")}

    def test_block_is_copied_onto_extensions_unchanged(self):
        wired, template, _ = wire_presentation.wire({}, self.presentation())
        self.assertEqual(wired["extensions"][BLOCK_KEY], self.presentation()[BLOCK_KEY])
        self.assertEqual(template, "outcome-report/v1")

    def test_sealed_digest_ignores_the_views_block(self):
        p = self.presentation()
        _, block, _ = wire_presentation.prepare_block(p, sealed=True)
        d = wire_presentation.digest_member("outcome-report/v1", block)
        wired, _, _ = wire_presentation.wire({}, p, sealed_digest=d)
        self.assertIn(BLOCK_KEY, wired["extensions"])

    def test_malformed_block_is_refused(self):
        for bad in ({}, {"charts": [], "wording": {}}, {"charts": [{}]}, {"charts": [{}], "wording": {}, "x": 1}):
            p = self.presentation()
            p[BLOCK_KEY] = bad
            with self.subTest(bad), self.assertRaises(wire_presentation.WireError):
                wire_presentation.wire({}, p)

    def test_existing_extension_is_not_overwritten(self):
        with self.assertRaisesRegex(wire_presentation.WireError, "refusing to overwrite"):
            wire_presentation.wire({"extensions": {BLOCK_KEY: {}}}, self.presentation())


if __name__ == "__main__":
    unittest.main()
