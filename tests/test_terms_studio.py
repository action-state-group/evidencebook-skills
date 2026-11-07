"""The Terms Pack Studio verbs (scripts/studio/terms) and the transaction evaluator
(evidencebook-skills#117), end to end on tests/fixtures/sticker-sale/trades.json:
the ten-sale rehearsal reads 9 of 10 with the price miss, the page verifies
offline and carries result.json's bytes, `compare` of a 1-day and a 2-day pack
shows ten ties on that row and both digests, and `run` writes only into the
workspace it is given.

    python3 -m unittest discover -s tests -p 'test_*.py'
"""
import contextlib
import io
import json
import pathlib
import subprocess
import sys
import os
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "studio"))
sys.path.insert(0, str(ROOT / "scripts" / "evaluators"))

import jsonschema  # noqa: E402

import dataset_plan  # noqa: E402
import transaction  # noqa: E402
import terms  # noqa: E402

SOURCE = ROOT / "packs" / "sticker-sale" / "pack-source.yaml"
TRADES = ROOT / "tests" / "fixtures" / "sticker-sale" / "trades.json"
GENERATED = "2026-11-04T12:00:00Z"


def call(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = terms.main([str(a) for a in argv])
    return code, json.loads(buf.getvalue())


def listing(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


class StickerDeal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_path = pathlib.Path(self.tmp.name)
        self.ws = self.tmp_path / "ws"

    def two_day_source(self):
        text = SOURCE.read_text().replace("within 1 day", "within 2 days").replace(
            "delivered_within_days(1)", "delivered_within_days(2)")
        path = self.tmp_path / "two.yaml"
        path.write_text(text)
        return path

    def rehearse(self, src):
        code, res = call("run", src, "--deals", TRADES, "--dry-run", "--workspace", self.ws, "--generated-at", GENERATED)
        self.assertEqual(code, 0, res)
        return res

    def test_lint_and_test_pass_on_the_shipped_pack(self):
        self.assertEqual(call("lint", SOURCE)[0], 0)
        code, res = call("test", SOURCE)
        self.assertEqual(code, 0, res)
        self.assertEqual([r["passed"] for r in res["rows"]], [True, True, True])

    def test_lint_refuses_a_row_without_a_check_or_with_a_bad_one(self):
        text = SOURCE.read_text()
        for name, bad in (("nocheck", text.replace("    check: price_as_offered\n", "")),
                          ("badcheck", text.replace("price_as_offered\n    proves", "free_stickers\n    proves")),
                          ("noarg", text.replace("delivered_within_days(1)", "delivered_within_days")),
                          ("model", text.replace("tier: recomputed", "tier: judged", 1))):
            path = self.tmp_path / f"{name}.yaml"
            path.write_text(bad)
            code, res = call("lint", path)
            self.assertEqual(code, 1, name)
            self.assertFalse(res["valid"], name)

    def test_the_ten_trade_rehearsal_reads_nine_of_ten_with_the_price_miss(self):
        res = self.rehearse(SOURCE)
        self.assertEqual((res["came_through"], res["sales"], res["rehearsal"]), (9, 10, True))
        result = json.loads(pathlib.Path(res["result"]).read_bytes())
        misses = {c["id"] for c in result["claims"] if c["verdict"] == "not_met"}
        self.assertEqual(misses, {"sticker-07::price_as_offered"})
        self.assertTrue(result["x-rehearsal"])

    def test_the_result_validates_against_the_evidence_result_schema(self):
        sys.path.insert(0, str(ROOT / "tests"))
        import test_result_v0_schema as t  # noqa: E402
        validator = jsonschema.Draft202012Validator(json.loads(t.SCHEMA_PATH.read_bytes()))
        result = json.loads(pathlib.Path(self.rehearse(SOURCE)["result"]).read_bytes())
        self.assertEqual([e.message for e in validator.iter_errors(result)], [])

    def test_two_packs_over_one_deals_file_cite_the_same_plan_and_dataset(self):
        a = self.rehearse(SOURCE)
        with tempfile.TemporaryDirectory() as tmp:
            code, b = call("run", self.two_day_source(), "--deals", TRADES, "--dry-run",
                           "--workspace", pathlib.Path(tmp) / "ws", "--generated-at", GENERATED)
            self.assertEqual(code, 0, b)
            rb = json.loads(pathlib.Path(b["result"]).read_bytes())
        ra = json.loads(pathlib.Path(a["result"]).read_bytes())
        self.assertNotEqual(ra["x-pack"]["definition_digest"], rb["x-pack"]["definition_digest"])
        self.assertEqual((ra["plan_ref"], ra["dataset_ref"]), (rb["plan_ref"], rb["dataset_ref"]))
        self.assertEqual(ra["plan_ref"]["digest_alg"], "SHA-256")
        # the order of the file never matters
        shuffled = self.tmp_path / "shuffled.json"
        sales = json.loads(TRADES.read_text())
        shuffled.write_text(json.dumps(list(reversed(sales["trades"] if isinstance(sales, dict) else sales))))
        code, c = call("run", SOURCE, "--deals", shuffled, "--dry-run", "--workspace", self.ws, "--generated-at", GENERATED)
        self.assertEqual(code, 0, c)
        rc = json.loads(pathlib.Path(c["result"]).read_bytes())
        self.assertEqual((ra["plan_ref"], ra["dataset_ref"]), (rc["plan_ref"], rc["dataset_ref"]))

    def test_other_sales_cite_another_plan_and_dataset(self):
        ra = json.loads(pathlib.Path(self.rehearse(SOURCE)["result"]).read_bytes())
        sales = json.loads(TRADES.read_text())
        sales = sales["trades"] if isinstance(sales, dict) else sales
        # one sale fewer, and one sale's price changed with the same count: both refs move
        for other in (sales[:-1], [dict(sales[0], price=99999)] + sales[1:]):
            path = self.tmp_path / "other.json"
            path.write_text(json.dumps(other))
            code, res = call("run", SOURCE, "--deals", path, "--dry-run", "--workspace", self.tmp_path / "ws2",
                             "--generated-at", GENERATED)
            self.assertEqual(code, 0, res)
            r = json.loads(pathlib.Path(res["result"]).read_bytes())
            self.assertNotEqual(r["plan_ref"], ra["plan_ref"])
            self.assertNotEqual(r["dataset_ref"], ra["dataset_ref"])
            self.assertEqual(call("verify", res["page"])[0], 0)

    def rewrite_page(self, res, change):
        """Replace the run's Result by change(result), with a page that draws it: a forged but
        self-consistent page, so only the plan_ref / dataset_ref checks can refuse it."""
        result = json.loads(pathlib.Path(res["result"]).read_bytes())
        change(result)
        raw = terms.result_bytes(result)
        pathlib.Path(res["result"]).write_bytes(raw)
        pathlib.Path(res["page"]).write_text(terms.page_html(result, raw), encoding="utf-8")

    def test_verify_rebuilds_the_refs_from_the_results_own_sales(self):
        res = self.rehearse(SOURCE)
        run = pathlib.Path(res["run"])
        result = json.loads((run / "result.json").read_bytes())
        plan = json.loads((run / "plan.json").read_bytes())
        dataset = json.loads((run / "dataset.json").read_bytes())
        self.assertEqual(dataset_plan.digest_of(plan), result["plan_ref"]["digest"])
        self.assertEqual(dataset_plan.digest_of(dataset), result["dataset_ref"]["digest"])
        self.assertEqual(dataset["plan_ref"], result["plan_ref"])
        self.assertEqual(len(dataset["rows"]), 10)
        self.assertEqual(plan["nodes"][0]["params"]["through_seq"], 9)
        self.assertNotIn("price", json.dumps(dataset))  # digests only, never a sale's values
        self.assertEqual(call("verify", res["page"])[0], 0)
        # a ref that names other sales than x-pack.sales select is refused
        other = dataset_plan.digest_ref("ab" * 32)
        self.rewrite_page(res, lambda r: r.update(dataset_ref=other))
        code, ver = call("verify", res["page"])
        self.assertEqual(code, 1)
        self.assertIn("dataset_ref", ver["issues"][0])
        self.rewrite_page(res, lambda r: r.update(plan_ref=other, dataset_ref=result["dataset_ref"]))
        self.assertIn("plan_ref", call("verify", res["page"])[1]["issues"][0])
        # one ref without the other is refused too
        self.rewrite_page(res, lambda r: (r.update(plan_ref=result["plan_ref"]), r.pop("dataset_ref")))
        self.assertEqual(call("verify", res["page"])[0], 1)
        # x-pack.sales that is not a table of digests cannot be rebuilt: an issue, not a traceback
        for bad in ([], "x", {"a": ["b"]}):
            self.rewrite_page(res, lambda r: r["x-pack"].update(sales=bad))
            code, ver = call("verify", res["page"])
            self.assertEqual((code, ver["verified"]), (1, False), bad)
            self.assertIn("cannot be rebuilt", ver["issues"][0])
        # a Result made before the refs were set has nothing to check
        self.rewrite_page(res, lambda r: (r.pop("plan_ref", None), r.pop("dataset_ref", None)))
        self.assertEqual(call("verify", res["page"])[0], 0)

    def test_verify_refuses_a_sidecar_that_is_not_the_one_the_sales_give(self):
        res = self.rehearse(SOURCE)
        run = pathlib.Path(res["run"])
        good = {n: (run / n).read_bytes() for n in ("plan.json", "dataset.json")}
        for name, bad in (("dataset.json", json.dumps(dict(json.loads(good["dataset.json"]), rows=[])).encode()),
                          ("plan.json", b'{"nodes":[]}'), ("plan.json", b"not json"), ("plan.json", b"NaN")):
            (run / name).write_bytes(bad)
            code, ver = call("verify", res["page"])
            self.assertEqual((code, ver["verified"]), (1, False), (name, bad))
            self.assertIn(name, ver["issues"][0])
            (run / name).write_bytes(good[name])
        (run / "plan.json").unlink()
        (run / "plan.json").mkdir()  # unreadable: an issue, not a traceback
        code, ver = call("verify", res["page"])
        self.assertEqual((code, ver["verified"]), (1, False))
        (run / "plan.json").rmdir()
        (run / "dataset.json").unlink()
        self.assertEqual(call("verify", res["page"])[0], 0)  # the documents are optional

    def test_the_dataset_is_what_aacs_own_checker_rebuilds(self):
        aac = pathlib.Path(os.environ.get("AAC_CHECKOUT", pathlib.Path.home() / "Github" / "agent-action-capsule"))
        if not (aac / "schemas" / "evidence_dataset.py").exists():
            self.skipTest("no agent-action-capsule checkout (set AAC_CHECKOUT)")
        sys.path.insert(0, str(aac / "schemas"))
        import evidence_dataset  # noqa: E402
        sales = json.loads(TRADES.read_text())
        sales = sales["trades"] if isinstance(sales, dict) else sales
        deals = [dict(d, deal_id=d.get("deal_id", d.get("id"))) for d in sales]
        digests = dataset_plan.sale_digests(deals)
        plan, dataset = dataset_plan.build(digests)
        evidence_dataset.check_dataset(plan, dataset, dataset_plan.headers(digests))
        self.assertEqual(evidence_dataset.build_dataset(plan, dataset_plan.headers(digests)), dataset)

    def test_the_page_verifies_offline_and_embeds_the_result_bytes(self):
        res = self.rehearse(SOURCE)
        page = pathlib.Path(res["page"])
        raw = pathlib.Path(res["result"]).read_bytes()
        self.assertIn(raw.decode(), page.read_text())
        self.assertIn("REHEARSAL", page.read_text())
        code, ver = call("verify", page)
        self.assertEqual((code, ver["verified"]), (0, True), ver)
        # a page edited after the run no longer verifies
        page.write_text(page.read_text().replace("9 of 10", "10 of 10"))
        self.assertEqual(call("verify", page)[0], 1)
        page.write_text(page.read_text().replace('"claims"', '"claimz"', 1))
        self.assertEqual(call("verify", page)[0], 1)

    def test_a_run_without_dry_run_is_not_stamped(self):
        code, res = call("run", SOURCE, "--deals", TRADES, "--workspace", self.ws, "--generated-at", GENERATED)
        self.assertEqual(code, 0)
        self.assertFalse(res["rehearsal"])
        self.assertNotIn("REHEARSAL", pathlib.Path(res["page"]).read_text())
        self.assertEqual(call("verify", res["page"])[0], 0)

    def test_compare_one_day_to_two_days_shows_ten_ties_and_both_digests(self):
        first, second = self.rehearse(SOURCE), self.rehearse(self.two_day_source())
        code, cmp = call("compare", first["run"], second["run"])
        self.assertEqual(code, 0, cmp)
        self.assertTrue(cmp["same_rows"])
        by_row = {r["row"]: r for r in cmp["rows"]}
        within = by_row["delivered_within_days"]
        self.assertEqual((within["result"], within["improved"], within["regressed"], within["tied"]),
                         ("Tie", 0, 0, 10))
        self.assertTrue(within["row_changed"])
        self.assertFalse(by_row["price_as_offered"]["row_changed"])
        self.assertEqual(cmp["before"]["pack_digest"], first["pack_digest"])
        self.assertEqual(cmp["after"]["pack_digest"], second["pack_digest"])
        self.assertNotEqual(first["pack_digest"], second["pack_digest"])

    def test_compare_reports_improvement_regression_and_tradeoff(self):
        base = json.loads(pathlib.Path(self.rehearse(SOURCE)["result"]).read_bytes())
        def variant(flips):
            doc = json.loads(json.dumps(base))
            for claim in doc["claims"]:
                if claim["id"] in flips:
                    claim["verdict"] = flips[claim["id"]]
            path = self.tmp_path / f"v{len(flips)}-{abs(hash(tuple(flips.items())))}.json"
            path.write_text(json.dumps(doc))
            return path
        better = variant({"sticker-07::price_as_offered": "met"})
        worse = variant({"sticker-01::price_as_offered": "not_met"})
        both = variant({"sticker-07::price_as_offered": "met", "sticker-01::price_as_offered": "not_met"})
        base_path = pathlib.Path(self.rehearse(SOURCE)["result"])
        got = {name: {r["row"]: r["result"] for r in call("compare", base_path, p)[1]["rows"]}["price_as_offered"]
               for name, p in (("better", better), ("worse", worse), ("both", both))}
        self.assertEqual(got, {"better": "Improvement", "worse": "Regression", "both": "Tradeoff"})

    def test_compare_flags_rows_added_or_removed_and_refuses_different_sales(self):
        first = self.rehearse(SOURCE)
        short = self.tmp_path / "short.yaml"
        short.write_text(SOURCE.read_text().split("  - id: price_as_offered")[0])
        second = self.rehearse(short)
        code, cmp = call("compare", first["run"], second["run"])
        self.assertEqual(code, 0)
        self.assertFalse(cmp["same_rows"])
        self.assertEqual(cmp["rows_removed"], ["price_as_offered"])
        fewer = self.tmp_path / "fewer.json"
        fewer.write_text(json.dumps(json.loads(TRADES.read_text())["trades"][:5]))
        code, third = call("run", SOURCE, "--deals", fewer, "--dry-run", "--workspace", self.ws)
        self.assertEqual(call("compare", first["run"], third["run"])[0], 1)

    def test_run_and_publish_write_only_into_the_workspace(self):
        src = self.tmp_path / "src"
        src.mkdir()
        pack = src / "pack-source.yaml"
        pack.write_text(SOURCE.read_text())
        before = listing(src)
        self.rehearse(pack)
        code, pub = call("publish", pack, "--workspace", self.ws)
        self.assertEqual(code, 0, pub)
        self.assertEqual(listing(src), before)
        files = listing(self.ws)
        self.assertTrue(files and all(f.startswith(("runs", "published", "packs")) for f in files), files)
        self.assertIn(pub["definition_digest"][:12], pub["published"])
        compiled = json.loads(pathlib.Path(pub["compiled"]).read_text())
        self.assertEqual(compiled["definition_digest"], pub["definition_digest"])

    def test_a_workspace_link_pointing_out_is_refused(self):
        outside = self.tmp_path / "outside"
        outside.mkdir()
        self.ws.mkdir()
        (self.ws / "runs").symlink_to(outside)
        code, res = call("run", SOURCE, "--deals", TRADES, "--dry-run", "--workspace", self.ws)
        self.assertEqual(code, 1)
        self.assertEqual(listing(outside), [])

    def test_the_shipped_compiled_pack_is_current(self):
        committed = json.loads((ROOT / "packs" / "sticker-sale" / "compiled" / "compiled.json").read_text())
        import deal_pack
        self.assertEqual(committed, deal_pack.compiled(terms.load_pack(SOURCE)))


class Folds(unittest.TestCase):
    def test_a_missing_field_is_not_evaluable_never_not_met(self):
        for name, arg in (("paid_before_delivered", None), ("delivered_within_days", 1), ("price_as_offered", None)):
            fold, _ = transaction.CHECKS[name]
            self.assertEqual(fold({}, arg), "not_evaluable", name)
        fold, _ = transaction.CHECKS["delivered_within_days"]
        self.assertEqual(fold({"paid_at": "2026-11-01T10:00:00Z"}, 1), "not_evaluable")

    def test_delivered_within_days_is_inclusive_and_reads_whole_days(self):
        fold, _ = transaction.CHECKS["delivered_within_days"]
        sale = lambda d: {"paid_at": "2026-11-01T10:00:00Z", "delivered_at": d}  # noqa: E731
        self.assertEqual(fold(sale("2026-11-02T10:00:00Z"), 1), "met")
        self.assertEqual(fold(sale("2026-11-02T10:00:01Z"), 1), "not_met")
        self.assertEqual(fold(sale("2026-11-02T10:00:01Z"), 2), "met")

    def test_paid_before_delivered_fails_when_delivery_comes_first(self):
        fold, _ = transaction.CHECKS["paid_before_delivered"]
        self.assertEqual(fold({"paid_at": "2026-11-01T10:00:00Z", "delivered_at": "2026-11-01T09:00:00Z"}, None), "not_met")


def seller_export(n, offer, commit, paid="2026-11-04T10:00:01Z", delivered="2026-11-04T10:00:02Z"):
    """A seller's `deal export` records for one trade, in evidencebook-deal's shapes
    (testdata/studio/README.md); commit=None is trade 7, the unchecked price change."""
    rec = lambda t, b, at="2026-11-04T10:00:00Z": {"type": t, "at": at, "body": b}
    out = [rec("baseline", {}), rec("action-record/v0", {"action": "offer", "amount_minor": offer})]
    if commit is None:
        out.append(rec("action-outcome/v0", {"status": "unchecked_action", "outcome": "mismatch",
                                             "attempted": {"action": "commit", "amount_minor": 175}}))
    else:
        out.append(rec("action-record/v0", {"action": "commit", "amount_minor": commit}))
    out += [{"body": {"source": "x402_settle_response"}, "x-deal-v0": {"record_type": "evidence", "at": paid}},
            {"body": {"source": "seller_handoff"}, "x-deal-v0": {"record_type": "evidence", "at": delivered}},
            rec("close", {})]
    return out


class DealStore(unittest.TestCase):
    def test_ten_exported_deals_read_nine_of_ten_with_the_price_change_the_miss(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = pathlib.Path(t)
            ex = tmp / "exports"
            ex.mkdir()
            for n in range(1, 11):
                records = seller_export(n, 150, None if n == 7 else 150)
                (ex / f"deal-{n:02d}.json").write_text(json.dumps(records))
            code, res = call("run", SOURCE, "--exports", ex, "--dry-run", "--workspace", tmp / "ws",
                             "--generated-at", GENERATED)
            self.assertEqual(code, 0, res)
            self.assertEqual((res["came_through"], res["sales"]), (9, 10))
            result = json.loads(pathlib.Path(res["result"]).read_bytes())
            misses = {c["id"] for c in result["claims"] if c["verdict"] == "not_met"}
            self.assertEqual(misses, {"deal-07::price_as_offered"})

    def test_a_lightning_sale_reads_paid_at_from_the_lightning_wallet_evidence(self):
        import deal_store
        records = seller_export(3, 150, 150, paid="2026-11-04T10:00:01Z")
        for r in records:
            if r["body"].get("source") == "x402_settle_response":
                r["body"]["source"] = "lightning_wallet"
        sale = deal_store.sale_from_records("deal-03", records)
        self.assertEqual(sale["paid_at"], "2026-11-04T10:00:01Z")
        self.assertIn("delivered_at", sale)
        self.assertNotIn("paid_at", deal_store.sale_from_records("d", [
            {"body": {"source": "other_wallet"}, "x-deal-v0": {"record_type": "evidence", "at": "2026-11-04T10:00:01Z"}}]))

    def test_a_price_change_after_the_commit_is_the_miss(self):
        import deal_store
        records = seller_export(7, 150, 150)
        records.insert(-1, {"body": {"changed": ["price"], "source": "seller_message", "terms": {"price_minor": 175}},
                            "x-deal-v0": {"record_type": "detail_change", "at": "2026-11-04T10:00:03Z", "seq": 9}})
        sale = deal_store.sale_from_records("deal-07", records)
        self.assertEqual((sale["offered_price"], sale["accepted_price"]), (150, 175))
        self.assertNotIn("commit_seen", sale)
        for changed in (True, "not_price"):
            bad = seller_export(9, 150, 150)
            bad.insert(-1, {"body": {"changed": changed, "terms": {"price_minor": 175}},
                            "x-deal-v0": {"record_type": "detail_change"}})
            self.assertEqual(deal_store.sale_from_records("d", bad)["accepted_price"], 150)
        re_commit = seller_export(10, 150, 150)
        re_commit.insert(-1, {"body": {"changed": ["price"], "terms": {"price_minor": 175}},
                              "x-deal-v0": {"record_type": "detail_change"}})
        re_commit.insert(-1, {"type": "action-record/v0", "body": {"action": "commit", "amount_minor": 200}})
        self.assertEqual(deal_store.sale_from_records("d", re_commit)["accepted_price"], 200)
        other = seller_export(8, 150, 150)
        other.insert(-1, {"body": {"changed": ["handover"]}, "x-deal-v0": {"record_type": "detail_change"}})
        self.assertEqual(deal_store.sale_from_records("deal-08", other)["accepted_price"], 150)

    def test_a_deal_without_the_facts_is_not_evaluable_and_empty_exports_are_refused(self):
        import deal_store
        sale = deal_store.sale_from_records("d", [{"type": "baseline", "body": {}}])
        self.assertEqual(sale, {"deal_id": "d"})
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(deal_store.StoreError):
                deal_store.sales_from_exports(t)


def check_input(deal_id, offer, commit):
    body = lambda b: {"agent_input": {"body": b}}
    return {"schema": "external-check-input/v0", "party_role": "seller",
            "record": dict(body({"action": "commit", "amount_minor": commit}), deal_id=deal_id, action_id=f"{deal_id}/7"),
            "history": [dict(body({"action": "offer", "amount_minor": 999}), action_id="deal-other/5"),
                        dict(body({"action": "offer", "amount_minor": offer}), action_id=f"{deal_id}/5")]}


class RulesChecker(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        code, res = call("publish", SOURCE, "--workspace", self.tmp.name)
        self.assertEqual(code, 0, res)
        self.res = res
        self.tmp_path = pathlib.Path(self.tmp.name)
        self.pin = json.loads((pathlib.Path(res["published"]) / "rules-checker.json").read_text())

    def run_checker(self, doc):
        p = subprocess.run(self.pin["command"], input=json.dumps(doc), capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def test_publish_writes_the_pin_with_the_pack_digest_and_an_absolute_checker(self):
        self.assertEqual(self.pin["definition_digest"], self.res["definition_digest"])
        self.assertTrue(pathlib.Path(self.pin["command"][0]).is_absolute())
        self.assertTrue(pathlib.Path(self.pin["command"][1]).is_absolute())

    def test_the_pin_states_the_packs_own_kind(self):
        self.assertEqual(self.pin["kind"], "deal")
        # a pack of another kind states that kind, never "deal"
        other = terms.rules_checker_pin({"scope": {"kind": "live"}}, pathlib.Path(self.tmp.name) / "c.json", "0" * 64)
        self.assertEqual(other["kind"], "live")
        # and publish refuses a non-deal pack before it writes any pin
        text = SOURCE.read_text().replace("kind: deal", "kind: live")
        path = pathlib.Path(self.tmp.name) / "live.yaml"
        path.write_text(text)
        ws = pathlib.Path(self.tmp.name) / "ws2"
        self.assertEqual(call("publish", path, "--workspace", ws)[0], 1)
        self.assertEqual(list(ws.rglob("rules-checker.json")) if ws.exists() else [], [])

    def test_the_checker_runs_alone_as_capsulectl_copies_it(self):
        import shutil
        lone = self.tmp_path / "lone" / "terms-checker"
        lone.parent.mkdir()
        shutil.copy(self.pin["command"][0], lone)
        self.pin["command"][0] = str(lone)
        res = self.run_checker(check_input("deal-a", 150, 150))
        self.assertEqual(res["verdict"], "allow")

    def test_the_price_row_passes_on_the_offered_price_and_fails_on_a_changed_one(self):
        ok = self.run_checker(check_input("deal-a", 150, 150))
        self.assertEqual((ok["verdict"], ok["definition_digest"]), ("allow", self.pin["definition_digest"]))
        # capsulectl's sealer reads name@version as an email address and refuses the answer
        self.assertEqual(ok["ruleset_id"], "sticker-sale/0.1.1")
        self.assertNotIn("@", ok["ruleset_id"])
        by = {f["id"]: f["verdict"] for f in ok["findings"]}
        self.assertEqual(by, {"paid_before_delivered": "not_applicable", "delivered_within_days": "not_applicable",
                              "price_as_offered": "pass"})
        bad = self.run_checker(check_input("deal-a", 150, 175))
        self.assertEqual(bad["verdict"], "deny")
        self.assertEqual({f["id"]: f["verdict"] for f in bad["findings"]}["price_as_offered"], "fail")

    def test_no_same_deal_offer_is_not_evaluable(self):
        doc = check_input("deal-a", 150, 150)
        doc["history"] = []
        res = self.run_checker(doc)
        self.assertEqual({f["id"]: f["verdict"] for f in res["findings"]}["price_as_offered"], "not_evaluable")


    def price_finding(self, doc):
        return {f["id"]: f for f in self.run_checker(doc)["findings"]}["price_as_offered"]

    def test_the_cards_words_name_the_row_by_the_packs_statement(self):
        # a changed price: the row's statement and both amounts, in the card's units
        usd = check_input("deal-a", 50, 60)
        usd["record"]["agent_input"]["body"]["currency"] = "USD"
        bad = self.price_finding(usd)
        self.assertEqual(bad["reason"], 'your rule "The price was the price offered" did not hold (the commit was $0.60, the offer $0.50)')
        # a unit the card cannot format (sats), or none stated, leaves the amounts out, never printed wrong
        self.assertNotIn("$", self.price_finding(check_input("deal-a", 50, 60))["reason"])
        sats = check_input("deal-a", 50, 60)
        sats["record"]["agent_input"]["body"]["currency"] = "SAT"
        self.assertEqual(self.price_finding(sats)["reason"],
                         'your rule "The price was the price offered" did not hold (the commit price is not the price offered)')
        # the offer stage: no commit yet, the row is said as pending, not as unchecked
        offer = check_input("deal-a", 50, 50)
        offer["record"]["agent_input"]["body"] = {"action": "offer", "amount_minor": 50}
        pending = self.price_finding(offer)
        self.assertEqual((pending["verdict"], pending["reason"]),
                         ("not_evaluable", 'your rule "The price was the price offered" is checked at the commit'))
        # a commit with no offer on record is a real gap, said as one
        gap = check_input("deal-a", 50, 50)
        gap["history"] = []
        self.assertIn("could not be checked", self.price_finding(gap)["reason"])
        # a commit that states no amount, an offer that states none, and a step after the commit
        nocommit = check_input("deal-a", 50, 50)
        del nocommit["record"]["agent_input"]["body"]["amount_minor"]
        self.assertIn("the commit states no amount", self.price_finding(nocommit)["reason"])
        nooffer = check_input("deal-a", 50, 50)
        nooffer["history"][1]["agent_input"]["body"].pop("amount_minor")
        self.assertIn("the offer states no amount", self.price_finding(nooffer)["reason"])
        after = check_input("deal-a", 50, 60)
        after["record"]["agent_input"]["body"] = {"action": "share_contact"}
        done = self.price_finding(after)
        self.assertEqual((done["verdict"], done["reason"]),
                         ("not_evaluable", 'your rule "The price was the price offered" is decided at the commit'))
        # a clean commit says nothing
        self.assertNotIn("reason", self.price_finding(check_input("deal-a", 50, 50)))


class Hardening(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.t = pathlib.Path(self.tmp.name)

    def test_a_bare_time_or_a_non_number_price_is_not_evaluable(self):
        fold, _ = transaction.CHECKS["paid_before_delivered"]
        self.assertEqual(fold({"paid_at": "2026-11-01T10:00:00", "delivered_at": "2026-11-01T11:00:00Z"}, None), "not_evaluable")
        fold, _ = transaction.CHECKS["price_as_offered"]
        for a, b in ((True, 1), ({}, {}), ("5", "5")):
            self.assertEqual(fold({"offered_price": a, "accepted_price": b}, None), "not_evaluable")

    def test_publish_refuses_to_write_through_a_link(self):
        code, res = call("publish", SOURCE, "--workspace", self.t)
        dest = pathlib.Path(res["published"])
        target = self.t / "elsewhere"
        target.write_text("keep")
        (dest / "compiled.json").unlink()
        (dest / "compiled.json").symlink_to(target)
        code, res = call("publish", SOURCE, "--workspace", self.t)
        self.assertEqual(code, 1)
        self.assertEqual(target.read_text(), "keep")

    def test_publish_says_it_is_not_in_force_and_names_the_install_command(self):
        code, res = call("publish", SOURCE, "--workspace", self.t)
        self.assertFalse(res["in_force"])
        self.assertIn("profile update --profile deal --rules-checker", res["install"])

    def test_lint_refuses_proves_or_statement_that_disagree_with_the_check(self):
        text = SOURCE.read_text()
        for name, bad in (("proves", text.replace("proves: [offered_price, accepted_price]", "proves: [paid_at]")),
                          ("number", text.replace("within 1 day", "within 2 days"))):
            path = self.t / f"{name}.yaml"
            path.write_text(bad)
            code, res = call("lint", path)
            self.assertEqual(code, 1, (name, res))

    def test_compare_refuses_runs_over_different_records_of_the_same_sales(self):
        sales = json.loads(TRADES.read_text())
        rows = sales["trades"] if isinstance(sales, dict) else sales
        other = self.t / "other.json"
        rows[6] = dict(rows[6], accepted_price=rows[6]["offered_price"])
        other.write_text(json.dumps(rows))
        runs = []
        for deals in (TRADES, other):
            code, res = call("run", SOURCE, "--deals", deals, "--dry-run", "--workspace", self.t / "ws", "--generated-at", GENERATED)
            runs.append(res["result"])
        code, res = call("compare", *runs)
        self.assertEqual(code, 1)

    def test_lint_matches_the_whole_number_and_install_quotes_a_spaced_path(self):
        path = self.t / "ten.yaml"
        path.write_text(SOURCE.read_text().replace("within 1 day", "within 10 days"))
        self.assertEqual(call("lint", path)[0], 1)
        ws = self.t / "my studio"
        code, res = call("publish", SOURCE, "--workspace", ws)
        import shlex
        self.assertEqual(shlex.split(res["install"])[-1], res["rules_checker_pin"])

    def test_verify_and_compare_refuse_malformed_records(self):
        code, res = call("run", SOURCE, "--deals", TRADES, "--workspace", self.t / "ws", "--generated-at", GENERATED)
        page = pathlib.Path(res["page"])
        text = page.read_text(encoding="utf-8")
        for bad in ('{"claims":null}', '{"claims":[null]}'):
            import hashlib
            bad_page = self.t / "bad.html"
            m = terms._SCRIPT.search(text)
            raw = bad.encode()
            tag = text[m.start():m.end()].replace(m.group(4), bad).replace(m.group(1), hashlib.sha256(raw).hexdigest())
            bad_page.write_text(text[:m.start()] + tag + text[m.end():], encoding="utf-8")
            self.assertEqual(call("verify", bad_page)[0], 1)
        old = json.loads(pathlib.Path(res["result"]).read_bytes())
        del old["x-pack"]["sales"]
        a = self.t / "a.json"
        a.write_text(json.dumps(old))
        self.assertEqual(call("compare", a, a)[0], 1)

    def test_run_names_the_missed_and_the_undecided_sales_apart(self):
        rows = json.loads(TRADES.read_text())
        rows = rows["trades"] if isinstance(rows, dict) else rows
        rows[0] = {k: v for k, v in rows[0].items() if k != "delivered_at"}
        path = self.t / "sales.json"
        path.write_text(json.dumps(rows))
        code, res = call("run", SOURCE, "--deals", path, "--dry-run", "--workspace", self.t / "ws", "--generated-at", GENERATED)
        self.assertEqual(list(res["missed"]), ["sticker-07"])
        self.assertEqual(list(res["could_not_decide"]), [rows[0].get("deal_id", rows[0].get("id"))])
        self.assertEqual(res["came_through"], 8)

    def test_sales_from_store_with_a_fake_capsulectl(self):
        import deal_store
        calls = []

        def run(argv, **kw):
            calls.append(argv)
            if "list" in argv:
                out = json.dumps([{"deal_id": "d1", "kind": "deal", "state": "closed"}, {"deal_id": "s1", "kind": "sale", "state": "closed"},
                                  {"deal_id": "d2", "kind": "deal", "state": "open"}])
            else:
                pathlib.Path(argv[argv.index("--output") + 1]).write_text(json.dumps(seller_export(1, 150, 150)))
                out = ""
            return subprocess.CompletedProcess(argv, 0, out, "")
        sales = deal_store.sales_from_store(self.t, run=run)
        self.assertEqual([s["deal_id"] for s in sales], ["d1"])
        self.assertEqual(sales[0]["accepted_price"], 150)
        bad = lambda argv, **kw: subprocess.CompletedProcess(argv, 1, "", "no such profile")
        with self.assertRaises(deal_store.StoreError):
            deal_store.sales_from_store(self.t, run=bad)


class OtherGoods(unittest.TestCase):
    """The evaluator is about transactions, not stickers (evidencebook-skills#124): a
    second pack for different goods lints, tests and runs with no evaluator change."""
    BEANS = ROOT / "packs" / "coffee-beans-sale" / "pack-source.yaml"
    BEAN_TRADES = ROOT / "tests" / "fixtures" / "coffee-beans-sale" / "trades.json"

    def test_every_row_that_reads_delivered_at_says_it_is_the_sellers_report(self):
        # delivered_at is the seller's report, not buyer-checked (evidencebook-skills#156)
        import readiness
        rows = [r for src in (SOURCE, self.BEANS) for r in terms.load_pack(src)["rows"]]
        rows += list(readiness.PROPOSED_ROWS)
        reading = [r for r in rows if "delivered_at" in r["proves"]]
        self.assertEqual(len(reading), 6)
        for r in reading:
            self.assertIn("seller", r["statement"], r["id"])

    def test_both_example_packs_name_the_one_transaction_evaluator(self):
        import deal_pack
        for src in (SOURCE, self.BEANS):
            self.assertEqual(terms.load_pack(src)["evaluator"], "transaction")
        self.assertEqual(sorted(deal_pack.EVALUATORS), ["transaction"])
        self.assertNotIn("sticker", transaction.__doc__.split("\n\n")[0].lower())  # its summary names no good
        self.assertNotIn("sticker", pathlib.Path(transaction.__file__).name)

    def test_the_sticker_sale_definition_digest_pin(self):
        # the evaluator name is not part of definition_digest, so a rename changes no pin;
        # this digest is 0.1.1's, where the delivery rows say they rest on the seller's report (#156)
        import deal_pack
        self.assertEqual(deal_pack.definition_digest(terms.load_pack(SOURCE)),
                         "b863e5e4898fc328acc2d997371aff651ec53bd5d4032a26aeac0b21d047d0a7")

    def test_a_second_pack_lints_tests_and_runs_over_the_same_evaluator(self):
        self.assertEqual(call("lint", self.BEANS)[0], 0)
        code, res = call("test", self.BEANS)
        self.assertEqual(code, 0, res)
        self.assertEqual([r["passed"] for r in res["rows"]], [True, True, True])
        with tempfile.TemporaryDirectory() as tmp:
            code, res = call("run", self.BEANS, "--deals", self.BEAN_TRADES, "--dry-run",
                             "--workspace", pathlib.Path(tmp) / "ws", "--generated-at", GENERATED)
            self.assertEqual(code, 0, res)
            self.assertEqual((res["came_through"], res["sales"]), (2, 4))
            result = json.loads(pathlib.Path(res["result"]).read_bytes())
            misses = {c["id"] for c in result["claims"] if c["verdict"] == "not_met"}
            self.assertEqual(misses, {"beans-03::delivered_within_days", "beans-04::price_as_offered"})

    def test_the_second_pack_shipped_compiled_is_current(self):
        import deal_pack
        committed = json.loads((ROOT / "packs" / "coffee-beans-sale" / "compiled" / "compiled.json").read_text())
        self.assertEqual(committed, deal_pack.compiled(terms.load_pack(self.BEANS)))


class CoverageReport(unittest.TestCase):
    """capsule-viewer#303 reads "imported" from coverage_report: backfill-only means every source
    has contemporaneous_count 0 and backfilled_count equal to record_count."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.t = pathlib.Path(self.tmp.name)
        sys.path.insert(0, str(ROOT / "tests"))
        import test_result_v0_schema as schema  # noqa: E402
        self.validator = jsonschema.Draft202012Validator(json.loads(schema.SCHEMA_PATH.read_bytes()))

    def result_over(self, sales):
        deals = self.t / "sales.json"
        deals.write_text(json.dumps({"trades": sales}))
        code, res = call("run", SOURCE, "--deals", deals, "--dry-run", "--workspace", self.t / "ws",
                         "--generated-at", GENERATED)
        self.assertEqual(code, 0, res)
        result = json.loads(pathlib.Path(res["result"]).read_bytes())
        self.assertEqual([e.message for e in self.validator.iter_errors(result)], [])
        return result

    def sources(self, result):
        return [s for r in result["coverage_report"]["requirements"] for s in r["sources"]]

    def sales(self, modes):
        """The first sales, each stated "backfilled", "contemporaneous" or None (states nothing)."""
        base = json.loads(TRADES.read_text())["trades"][:len(modes)]
        return [dict(s, **{m: True}) if m else s for s, m in zip(base, modes)]

    def test_a_backfill_only_result_counts_every_record_as_backfilled(self):
        result = self.result_over(self.sales(["backfilled"] * 3))
        sources = self.sources(result)
        self.assertEqual(len(sources), 3)  # one per pack row
        for s in sources:
            self.assertEqual((s["record_count"], s["contemporaneous_count"], s["backfilled_count"]), (3, 0, 3))
            self.assertEqual(len(s["evidence"]), 3)
        self.assertEqual(result["x-pack"]["provenance_unknown"], [])

    def test_a_result_with_a_contemporaneous_sale_is_not_backfill_only(self):
        for modes in (["backfilled", "backfilled", "contemporaneous"], ["contemporaneous"] * 3):
            for s in self.sources(self.result_over(self.sales(modes))):
                self.assertEqual((s["contemporaneous_count"], s["backfilled_count"]),
                                 (modes.count("contemporaneous"), modes.count("backfilled")))
                self.assertNotEqual(s["backfilled_count"], s["record_count"])

    def test_a_sale_with_no_stated_provenance_leaves_the_report_out(self):
        # issue 152: a sale that says nothing was recorded at some time nobody asserted; the spec's
        # contemporaneous + backfilled == record_count leaves it no place in the counts.
        for modes in ([None] * 3, ["backfilled", None, "contemporaneous"], ["backfilled", "backfilled", None]):
            sales = self.sales(modes)
            result = self.result_over(sales)
            self.assertNotIn("coverage_report", result, modes)
            self.assertEqual(result["x-pack"]["provenance_unknown"],
                             sorted(s["deal_id"] for s, m in zip(sales, modes) if not m))
            self.assertFalse(terms.backfill_only(result), modes)  # unknown is never "all backfilled"
        both = self.result_over([dict(self.sales(["backfilled"])[0], contemporaneous=True)])
        self.assertEqual(len(both["x-pack"]["provenance_unknown"]), 1)  # two modes at once state none
        self.assertNotIn("coverage_report", both)

    def test_the_report_names_each_rows_claims_and_passes_the_engines_cross_checks(self):
        try:
            from capsule_engine.report.coverage import verify_coverage_report
        except ImportError:
            verify_coverage_report = None
        for modes in (["backfilled"] * 3, ["backfilled", "contemporaneous", "contemporaneous"]):
            result = self.result_over(self.sales(modes))
            by_id = {c["id"]: c for c in result["claims"]}
            for row in result["coverage_report"]["requirements"]:
                self.assertEqual(len(row["claim_ids"]), 3)
                for cid in row["claim_ids"]:
                    self.assertEqual(by_id[cid]["requirement_ref"], row["requirement_ref"])
                for s in row["sources"]:  # the spec's count rule, checked here even without the engine
                    self.assertEqual(s["contemporaneous_count"] + s["backfilled_count"], s["record_count"])
                    self.assertEqual(s["record_count"], len(s["evidence"]))
                self.assertEqual(row["independence"]["unattributed_records"], 3)
            if verify_coverage_report:
                verify_coverage_report(result["coverage_report"], by_id)

    def test_a_sale_without_the_member_keeps_its_digest(self):
        # plan_ref and dataset_ref hang on the sale digests: only a sale that states a mode may differ.
        sale = json.loads(TRADES.read_text())["trades"][0]
        self.assertNotIn("backfilled", sale)
        self.assertNotEqual(dataset_plan.digest_of(sale), dataset_plan.digest_of(dict(sale, backfilled=True)))
        self.assertNotEqual(dataset_plan.digest_of(sale), dataset_plan.digest_of(dict(sale, contemporaneous=True)))
        result = self.result_over(self.sales([None] * 3))
        self.assertEqual(result["x-pack"]["sales"][sale["deal_id"]], dataset_plan.digest_of(sale))

    def test_exported_records_are_backfilled_only_when_every_record_says_so(self):
        import deal_store  # noqa: E402
        records = seller_export(1, 150, 150)
        stamp = lambda r, mode: dict(r, provenance_mode={"mode": mode})  # noqa: E731
        self.assertNotIn("backfilled", deal_store.sale_from_records("d", records))
        self.assertNotIn("contemporaneous", deal_store.sale_from_records("d", records))  # states no mode: unknown
        every = [stamp(r, "backfilled") for r in records]
        self.assertIs(deal_store.sale_from_records("d", every)["backfilled"], True)
        mixed = every[:-1] + [stamp(records[-1], "contemporaneous")]
        self.assertNotIn("backfilled", deal_store.sale_from_records("d", mixed))
        self.assertNotIn("contemporaneous", deal_store.sale_from_records("d", mixed))
        live = [stamp(r, "contemporaneous") for r in records]
        self.assertIs(deal_store.sale_from_records("d", live)["contemporaneous"], True)
        self.assertNotIn("backfilled", deal_store.sale_from_records("d", live))
        self.assertNotIn("contemporaneous", deal_store.sale_from_records("d", live + [None]))
        self.assertNotIn("backfilled", deal_store.sale_from_records("d", every + [None]))  # an unreadable record states no mode
        self.assertNotIn("backfilled", deal_store.sale_from_records("d", every[:-1] + [records[-1]]))

    def test_the_report_page_says_imported_only_over_backfill_alone(self):
        b, c = "backfilled", "contemporaneous"
        for flags, says in (([b, b, b], True), ([b, b, c], False), ([c] * 3, False), ([b, b, None], False), ([None] * 3, False)):
            result = self.result_over(self.sales(flags))
            page = terms.page_html(result, terms.result_bytes(result))
            self.assertEqual('id="imported"' in page, says, flags)
            self.assertEqual(terms.IMPORTED in page, says, flags)
            self.assertEqual(terms.backfill_only(result), says, flags)
        self.assertFalse(terms.backfill_only({}))  # a Result with no coverage_report is not imported

    def test_a_backfill_page_still_verifies(self):
        deals = self.t / "sales.json"
        deals.write_text(json.dumps({"trades": self.sales(["backfilled"] * 3)}))
        code, res = call("run", SOURCE, "--deals", deals, "--workspace", self.t / "ws", "--generated-at", GENERATED)
        self.assertEqual(code, 0, res)
        self.assertEqual(call("verify", res["page"])[0], 0)


if __name__ == "__main__":
    unittest.main()
