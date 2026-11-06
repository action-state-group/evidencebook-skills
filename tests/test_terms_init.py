"""`terms init`, the field census and the readiness table (evidencebook-skills#127):
a dataset with no terms yields a pack whose every term has one of the five statuses,
"needs a field" names the field the census lacks, and readiness follows each edit,
label and run with no other step.

    python3 -m unittest discover -s tests -p 'test_*.py'
"""
import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "studio"))
sys.path.insert(0, str(ROOT / "scripts" / "evaluators"))

import readiness  # noqa: E402
import terms  # noqa: E402

TRADES = ROOT / "tests" / "fixtures" / "sticker-sale" / "trades.json"


def call(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = terms.main([str(a) for a in argv])
    return code, json.loads(buf.getvalue())


class Census(unittest.TestCase):
    def test_counts_filled_fields_and_ignores_empty_ones(self):
        c = readiness.census([{"a": 1, "b": {"c": "x"}, "e": ""}, {"a": 2, "b": {"c": None}, "e": [], "l": [{"k": 1}, {"k": 2}]}])
        got = {f["field"]: (f["filled"], f["rate"]) for f in c["fields"]}
        self.assertEqual(got, {"a": (2, 1.0), "b.c": (1, 0.5), "l[].k": (1, 0.5)})
        self.assertEqual(c["records"], 2)

    def test_empty_dataset(self):
        self.assertEqual(readiness.census([])["fields"], [])
        self.assertEqual(readiness.census([])["records"], 0)

    def test_a_key_that_holds_data_is_not_written_into_the_census(self):
        c = readiness.census([{"buyers": {"alice@example.com": {"paid_at": "x"}}}])
        self.assertEqual([f["field"] for f in c["fields"]], ["buyers.*.paid_at"])


class Init(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = pathlib.Path(self.tmp.name) / "ws"
        self.deals = pathlib.Path(self.tmp.name) / "sales.json"

    def init(self, sales, *extra):
        self.deals.write_text(json.dumps(sales))
        return call("init", "--deals", self.deals, "--workspace", self.ws, *extra)

    def sale(self, **kw):
        base = {"deal_id": "d1", "offered_price": 500, "accepted_price": 500,
                "paid_at": "2026-10-11T10:00:00Z", "delivered_at": "2026-10-11T15:30:00Z"}
        base.update(kw)
        return base

    def test_every_term_has_one_of_the_five_statuses(self):
        code, res = call("init", "--deals", TRADES, "--workspace", self.ws)
        self.assertEqual(code, 0, res)
        self.assertTrue(res["terms"])
        self.assertEqual({t["status"] for t in res["terms"]} - set(readiness.STATUSES), set())
        self.assertEqual(set(res["counts"]), set(readiness.STATUSES))
        self.assertEqual(sum(res["counts"].values()), len(res["terms"]))
        # a full dataset has every field the rows read, so only "needs a field" is absent
        self.assertEqual([s for s in readiness.STATUSES if not res["counts"][s]], ["needs a field"])
        self.assertEqual(res["records"], 10)

    def test_the_proposed_pack_lints_and_tests(self):
        _, res = self.init([self.sale()])
        self.assertEqual(call("lint", res["pack"])[0], 0)
        self.assertEqual(call("test", res["pack"])[0], 0)

    def test_needs_a_field_names_the_missing_field(self):
        sale = self.sale()
        del sale["delivered_at"]
        _, res = self.init([sale])
        by = {t["term"]: t for t in res["terms"]}
        self.assertEqual(by["paid_before_delivered"]["status"], "needs a field")
        self.assertEqual(by["paid_before_delivered"]["missing_fields"], ["delivered_at"])
        self.assertIn("delivered_at", by["paid_before_delivered"]["detail"])
        self.assertEqual(by["price_as_offered"]["status"], "checkable now")

    def test_fields_split_across_sales_are_not_checkable(self):
        a, b = self.sale(deal_id="a"), self.sale(deal_id="b")
        del a["delivered_at"]
        del b["paid_at"]
        _, res = self.init([a, b])
        by = {t["term"]: t for t in res["terms"]}
        self.assertEqual(by["paid_before_delivered"]["status"], "needs a field")
        self.assertIn("paid_at and delivered_at together", by["paid_before_delivered"]["detail"])
        self.assertEqual(by["price_as_offered"]["status"], "checkable now")

    def test_a_value_the_check_cannot_read_is_not_checkable(self):
        _, res = self.init([self.sale(offered_price="5.00", accepted_price="5.00")])
        self.assertEqual({t["term"]: t for t in res["terms"]}["price_as_offered"]["status"], "needs a field")

    def test_init_refuses_when_any_workspace_file_exists(self):
        folder = self.ws / "packs" / "sale-terms"
        folder.mkdir(parents=True)
        (folder / "candidates.json").write_text("[]")
        code, res = self.init([self.sale()])
        self.assertEqual(code, 1)
        self.assertIn("candidates.json", res["error"])
        self.assertEqual((folder / "candidates.json").read_text(), "[]")

    def test_a_broken_helper_file_is_an_error_not_an_empty_table(self):
        _, res = self.init([self.sale()])
        folder = pathlib.Path(res["pack"]).parent
        (folder / "candidates.json").write_text("[oops")
        code, err = call("readiness", res["pack"])
        self.assertEqual(code, 1)
        self.assertIn("not JSON", err["error"])
        before = (folder / "readiness.json").read_text()
        call("lint", res["pack"])
        self.assertEqual((folder / "readiness.json").read_text(), before)

    def test_a_linked_readiness_file_is_never_written_through(self):
        _, res = self.init([self.sale()])
        folder = pathlib.Path(res["pack"]).parent
        target = pathlib.Path(self.tmp.name) / "elsewhere.json"
        target.write_text("keep")
        (folder / "readiness.json").unlink()
        (folder / "readiness.json").symlink_to(target)
        code, _ = call("lint", res["pack"])
        self.assertEqual(code, 0)  # lint's own answer stands; the refresh failure goes to stderr
        self.assertEqual(target.read_text(), "keep")

    def test_the_conduct_candidate_is_about_my_own_agent_and_never_a_buyer(self):
        _, res = self.init([self.sale()])
        term = next(t for t in res["terms"] if t["term"] == "my_agent_stayed_within_authority")
        self.assertEqual(term["status"], "not this pack's concern")
        self.assertIn("private conduct pack, which is kept for you and is never meant for a buyer", term["detail"])
        self.assertNotIn("buyer_stayed_polite", {t["term"] for t in res["terms"]})

    def test_an_unwritable_readiness_file_leaves_the_verb_answer_alone(self):
        _, res = self.init([self.sale()])
        folder = pathlib.Path(res["pack"]).parent
        (folder / "readiness.json").unlink()
        (folder / "readiness.json").mkdir()
        code, out = call("test", res["pack"])
        self.assertEqual((code, out["passed"]), (0, True))

    def test_a_linked_source_with_another_name_reads_the_linked_pack(self):
        _, res = self.init([self.sale()])
        folder = pathlib.Path(res["pack"]).parent
        alias = pathlib.Path(self.tmp.name) / "alias.yaml"
        alias.symlink_to(res["pack"])
        src = pathlib.Path(res["pack"])
        src.write_text(src.read_text().replace("- id: price_as_offered", "- id: price_quoted"))
        call("lint", alias)
        self.assertIn("price_quoted", (folder / "readiness.json").read_text())

    def test_rewording_a_row_keeps_it_unready(self):
        _, res = self.init([self.sale(offered_price="5.00", accepted_price="5.00")])
        src = pathlib.Path(res["pack"])
        src.write_text(src.read_text().replace("The price was the price offered.", "We charged what we listed."))
        call("lint", src)
        table = json.loads((src.parent / "readiness.json").read_text())
        row = {t["term"]: t for t in table["terms"]}["price_as_offered"]
        self.assertEqual(row["status"], "needs a field")
        self.assertEqual(row["missing_fields"], ["offered_price", "accepted_price"])

    def test_a_row_that_fails_lint_gets_no_table(self):
        _, res = self.init([self.sale()])
        src = pathlib.Path(res["pack"])
        before = (src.parent / "readiness.json").read_text()
        src.write_text(src.read_text().replace("check: price_as_offered", "check: rating_above(4)"))
        self.assertEqual(call("lint", src)[0], 1)
        code, err = call("readiness", src)
        self.assertEqual(code, 1)
        self.assertIn("does not lint", err["error"])
        self.assertEqual((src.parent / "readiness.json").read_text(), before)

    def test_a_row_missing_its_members_is_an_error_not_a_crash(self):
        _, res = self.init([self.sale()])
        src = pathlib.Path(res["pack"])
        src.write_text(src.read_text().replace("  proves:\n  - offered_price\n  - accepted_price\n", ""))
        code, err = call("readiness", src)
        self.assertEqual(code, 1)
        self.assertIn("error", err)

    def test_labels_count_distinct_sales_with_a_verdict(self):
        _, res = self.init([self.sale()])
        folder = pathlib.Path(res["pack"]).parent
        mark = lambda deal: {"deal_id": deal, "met": True}  # noqa: E731
        labels = {"matched_description": [mark("a"), mark("a"), mark("b"), {"deal_id": "c"}, "junk"]}
        (folder / "labels.json").write_text(json.dumps(labels))
        _, table = call("readiness", res["pack"])
        row = {t["term"]: t for t in table["terms"]}["matched_description"]
        self.assertEqual(row["detail"], "2 of 4 sales labelled")
        labels["matched_description"] += [mark("c"), mark("d")]
        (folder / "labels.json").write_text(json.dumps(labels))
        _, table = call("readiness", res["pack"])
        self.assertIn("4 labelled", {t["term"]: t for t in table["terms"]}["matched_description"]["detail"])

    def test_run_outside_its_workspace_writes_nothing_beside_the_pack(self):
        _, res = self.init([self.sale()])
        folder = pathlib.Path(res["pack"]).parent
        before = (folder / "census.json").read_text()
        other = pathlib.Path(self.tmp.name) / "other"
        sales = [self.sale(buyer_confirmed_at="2026-10-12T10:00:00Z")]
        self.deals.write_text(json.dumps(sales))
        self.assertEqual(call("run", res["pack"], "--deals", self.deals, "--dry-run", "--workspace", other)[0], 0)
        self.assertEqual((folder / "census.json").read_text(), before)

    def test_wrong_shapes_inside_helper_files_never_crash_a_verb(self):
        _, res = self.init([self.sale()])
        folder = pathlib.Path(res["pack"]).parent
        census = json.loads((folder / "census.json").read_text())
        cases = [
            ("census.json", {"records": 1, "fields": [{}]}),
            ("census.json", {"fields": []}),
            ("census.json", dict(census, fields=["x"])),
            ("census.json", dict(census, evaluable=[1])),
            ("candidates.json", [{"id": "x", "statement": "s", "tier": "judged", "reads": None, "side": "own"}]),
            ("candidates.json", [{"id": "x", "statement": "s", "tier": "judged", "reads": 5, "side": "own"}]),
            ("labels.json", {"matched_description": 5}),
        ]
        for name, doc in cases:
            with self.subTest(name=name, doc=doc):
                original = (folder / name).read_text() if (folder / name).exists() else None
                (folder / name).write_text(json.dumps(doc))
                code, err = call("readiness", res["pack"])
                if name != "labels.json":
                    self.assertEqual(code, 1)
                    self.assertIn("error", err)
                self.assertEqual(call("lint", res["pack"])[0], 0)
                if original is None:
                    (folder / name).unlink()
                else:
                    (folder / name).write_text(original)

    def test_init_reads_a_directory_of_deal_exports(self):
        exports = pathlib.Path(self.tmp.name) / "exports"
        exports.mkdir()
        records = [
            {"body": {"source": "x402_settle_response"}, "x-deal-v0": {"record_type": "evidence", "at": "2026-10-11T10:00:00Z"}},
            {"body": {"source": "seller_handoff"}, "x-deal-v0": {"record_type": "evidence", "at": "2026-10-11T12:00:00Z"}},
        ]
        (exports / "deal-1.json").write_text(json.dumps(records))
        code, res = call("init", "--exports", exports, "--workspace", self.ws)
        self.assertEqual(code, 0, res)
        by = {t["term"]: t for t in res["terms"]}
        self.assertEqual(by["paid_before_delivered"]["status"], "checkable now")
        self.assertEqual(by["price_as_offered"]["status"], "needs a field")
        self.assertIn("offered_price", by["price_as_offered"]["detail"])

    def test_init_refuses_a_packs_folder_linked_out_of_the_workspace(self):
        outside = pathlib.Path(self.tmp.name) / "outside"
        outside.mkdir()
        self.ws.mkdir()
        (self.ws / "packs").symlink_to(outside)
        code, err = self.init([self.sale()])
        self.assertEqual(code, 1)
        self.assertIn("outside the workspace", err["error"])
        self.assertEqual(list(outside.iterdir()), [])

    def test_init_never_overwrites_a_pack(self):
        self.init([self.sale()])
        code, res = self.init([self.sale()])
        self.assertEqual(code, 1)
        self.assertIn("already holds", res["error"])

    def test_rejects_a_bad_pack_id_and_an_escaping_one(self):
        self.assertEqual(self.init([self.sale()], "--pack-id", "../x")[0], 1)

    def test_readiness_follows_an_edit_a_label_and_a_run_with_no_other_step(self):
        _, res = self.init([self.sale()])
        folder = pathlib.Path(res["pack"]).parent
        table = lambda: json.loads((folder / "readiness.json").read_text())  # noqa: E731
        status = lambda t, term: {x["term"]: x["status"] for x in t["terms"]}.get(term)  # noqa: E731
        self.assertEqual(status(table(), "matched_description"), "needs examples")

        # an edit: rename a row, then lint
        src = pathlib.Path(res["pack"])
        src.write_text(src.read_text().replace("- id: price_as_offered", "- id: price_as_quoted"))
        self.assertEqual(call("lint", src)[0], 0)
        self.assertIsNone(status(table(), "price_as_offered"))
        self.assertEqual(status(table(), "price_as_quoted"), "checkable now")

        # a label: four sales labelled, then test
        (folder / "labels.json").write_text(json.dumps({"matched_description": [{"deal_id": f"d{i}", "met": True} for i in range(4)]}))
        call("test", src)
        row = {x["term"]: x for x in table()["terms"]}["matched_description"]
        self.assertIn("4 labelled", row["detail"])

        # a run over sales that now carry a buyer confirmation: the census, and so the table, moves
        sales = [self.sale(buyer_confirmed_at="2026-10-12T10:00:00Z")]
        self.deals.write_text(json.dumps(sales))
        self.assertEqual(call("run", src, "--deals", self.deals, "--dry-run", "--workspace", self.ws)[0], 0)
        self.assertEqual({f["field"] for f in json.loads((folder / "census.json").read_text())["fields"]} >= {"buyer_confirmed_at"}, True)
        # the term still needs the other side: a buyer's confirmation field is not the buyer's own record
        self.assertEqual(status(table(), "buyer_confirmed_receipt"), "needs the other side")

    def test_readiness_verb_prints_the_same_table(self):
        _, res = self.init([self.sale()])
        code, again = call("readiness", res["pack"])
        self.assertEqual(code, 0)
        self.assertEqual(again["terms"], res["terms"])

    def test_readiness_refuses_a_pack_with_no_census(self):
        code, res = call("readiness", ROOT / "packs" / "sticker-sale" / "pack-source.yaml")
        self.assertEqual(code, 1)
        self.assertIn("terms init", res["error"])

    def test_verbs_leave_a_pack_without_a_census_alone(self):
        folder = pathlib.Path(self.tmp.name) / "plain"
        folder.mkdir()
        src = folder / "pack-source.yaml"
        src.write_text((ROOT / "packs" / "sticker-sale" / "pack-source.yaml").read_text())
        call("lint", src)
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ["pack-source.yaml"])


if __name__ == "__main__":
    unittest.main()
