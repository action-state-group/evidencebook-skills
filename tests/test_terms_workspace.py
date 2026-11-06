"""The Terms Pack Studio workspace and its pack-digest history (evidencebook-skills#130):
a second agent continues from the folder alone, `compare` takes any earlier digest in
the history and names both, undo is `checkout` plus `run` plus `compare`, and no verb
keeps an authoring transcript unless asked.

    python3 -m unittest discover -s tests -p 'test_*.py'
"""
import contextlib
import io
import json
import os
import pathlib
import stat
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "studio"))
sys.path.insert(0, str(ROOT / "scripts" / "evaluators"))

import terms  # noqa: E402

TRADES = ROOT / "tests" / "fixtures" / "sticker-sale" / "trades.json"
GENERATED = "2026-11-05T12:00:00Z"


def call(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        code = terms.main([str(a) for a in argv])
    return code, json.loads(buf.getvalue())


class Workspace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = pathlib.Path(self.tmp.name) / "ws"
        code, res = call("init", "--deals", TRADES, "--workspace", self.ws, "--pack-id", "stickers")
        self.assertEqual(code, 0, res)
        self.src = pathlib.Path(res["pack"])
        self.folder = self.src.parent

    def run_pack(self, *extra):
        code, res = call("run", self.src, "--workspace", self.ws, "--dry-run", "--generated-at", GENERATED, *extra)
        self.assertEqual(code, 0, res)
        return res

    def edit(self, old, new, version):
        """Change the delivery limit in the check and in the words (lint holds them equal)."""
        text = self.src.read_text()
        self.assertIn(old, text)
        days = lambda c: c.split("(")[1].rstrip(")")
        text = text.replace(old, new).replace(f"within {days(old)} days", f"within {days(new)} days")
        self.src.write_text(text.replace("pack_version: 0.1.0", f"pack_version: {version}"))

    def test_init_records_the_dataset_and_run_needs_no_source_flag(self):
        st = json.loads((self.folder / "workspace.json").read_text())
        self.assertEqual((st["dataset"]["kind"], st["dataset"]["sales"]), ("deals", 10))
        self.assertEqual(st["dataset"]["path"], str(TRADES.resolve()))
        res = self.run_pack()  # a second agent: only the folder, no --deals
        self.assertEqual(res["sales"], 10)
        st = json.loads((self.folder / "workspace.json").read_text())
        self.assertEqual(st["last_run"]["run"], pathlib.Path(res["run"]).relative_to(self.ws.resolve()).as_posix())

    def test_run_with_no_dataset_anywhere_says_so(self):
        (self.folder / "workspace.json").unlink()
        code, res = call("run", self.src, "--workspace", self.ws, "--dry-run")
        self.assertEqual(code, 1)
        self.assertIn("name the sales", res["error"])

    def test_history_has_one_line_per_digest_and_a_snapshot_each(self):
        first = self.run_pack()
        again = self.run_pack()
        self.assertEqual(first["pack_digest"], again["pack_digest"])
        self.assertNotEqual(first["run"], again["run"])
        self.edit("delivered_within_days(2)", "delivered_within_days(3)", "0.2.0")
        second = self.run_pack()
        lines = [json.loads(l) for l in (self.folder / "history.jsonl").read_text().splitlines()]
        self.assertEqual([l["digest"] for l in lines], [first["pack_digest"], second["pack_digest"]])
        self.assertEqual(self.ws.resolve() / lines[0]["run"], pathlib.Path(again["run"]))  # the latest run under that digest
        self.assertTrue((self.folder / "history" / f"{first['pack_digest'][:12]}.yaml").is_file())
        code, hist = call("history", self.src, "--workspace", self.ws)
        self.assertEqual((code, len(hist["history"])), (0, 2))
        self.assertEqual(hist["last_run"]["digest"], second["pack_digest"])

    def test_compare_by_digest_names_both_digests(self):
        first = self.run_pack()
        self.edit("delivered_within_days(2)", "delivered_within_days(3)", "0.2.0")
        second = self.run_pack()
        code, res = call("compare", first["pack_digest"][:12], second["pack_digest"][:12], "--workspace", self.ws)
        self.assertEqual(code, 0, res)
        self.assertEqual((res["before"]["pack_digest"], res["after"]["pack_digest"]),
                         (first["pack_digest"], second["pack_digest"]))
        # the same answer as comparing the run folders
        self.assertEqual(res, call("compare", first["run"], second["run"])[1])

    def test_compare_refuses_an_unknown_short_or_never_run_digest(self):
        first = self.run_pack()
        for bad in ("deadbeefcafe", first["pack_digest"][:4]):
            code, res = call("compare", bad, first["run"], "--workspace", self.ws)
            self.assertEqual(code, 1, bad)
            self.assertIn("digest", res["error"])
        self.edit("delivered_within_days(2)", "delivered_within_days(3)", "0.2.0")
        code, pub = call("publish", self.src, "--workspace", self.ws)  # published, never run
        code, res = call("compare", first["run"], pub["definition_digest"][:12], "--workspace", self.ws)
        self.assertEqual(code, 1)
        self.assertIn("never run", res["error"])

    def test_undo_is_checkout_then_run_then_compare(self):
        first = self.run_pack()
        original = self.src.read_text()
        self.edit("delivered_within_days(2)", "delivered_within_days(3)", "0.2.0")
        second = self.run_pack()
        code, res = call("checkout", self.src, first["pack_digest"][:10], "--workspace", self.ws)
        self.assertEqual((code, res["restored"]), (0, first["pack_digest"]), res)
        self.assertEqual(self.src.read_text(), original)
        third = self.run_pack()
        self.assertEqual(third["pack_digest"], first["pack_digest"])
        code, cmp_ = call("compare", second["pack_digest"], third["pack_digest"], "--workspace", self.ws)
        self.assertEqual((code, cmp_["before"]["pack_digest"], cmp_["after"]["pack_digest"]),
                         (0, second["pack_digest"], first["pack_digest"]))
        self.assertEqual(len((self.folder / "history.jsonl").read_text().splitlines()), 2)

    def test_checkout_refuses_to_lose_unrecorded_edits_unless_forced(self):
        first = self.run_pack()
        self.edit("delivered_within_days(2)", "delivered_within_days(9)", "0.3.0")  # never run
        code, res = call("checkout", self.src, first["pack_digest"], "--workspace", self.ws)
        self.assertEqual(code, 1)
        self.assertIn("--force", res["error"])
        self.assertIn("delivered_within_days(9)", self.src.read_text())
        self.assertEqual(call("checkout", self.src, first["pack_digest"], "--workspace", self.ws, "--force")[0], 0)
        self.assertIn("delivered_within_days(2)", self.src.read_text())

    def test_checkout_refuses_a_link_and_a_pack_outside_the_workspace(self):
        first = self.run_pack()
        outside = pathlib.Path(self.tmp.name) / "elsewhere.yaml"
        outside.write_text(self.src.read_text())
        code, res = call("checkout", outside, first["pack_digest"], "--workspace", self.ws)
        self.assertEqual(code, 1)
        self.assertIn("outside the workspace", res["error"])

    def test_nothing_keeps_a_transcript_by_default(self):
        self.run_pack()
        call("publish", self.src, "--workspace", self.ws)
        names = [str(p.relative_to(self.ws)) for p in self.ws.rglob("*")]
        self.assertFalse([n for n in names if "transcript" in n or "private" in n], names)

    def test_keep_transcript_is_private_and_publish_leaves_it_out(self):
        talk = pathlib.Path(self.tmp.name) / "talk.md"
        talk.write_text("seller: delivered within a day\n")
        code, res = call("keep-transcript", self.src, talk, "--workspace", self.ws)
        self.assertEqual(code, 0, res)
        kept = pathlib.Path(res["kept"])
        self.assertEqual(stat.S_IMODE(kept.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(kept.parent.stat().st_mode), 0o700)
        code, pub = call("publish", self.src, "--workspace", self.ws)
        published = sorted(p.name for p in pathlib.Path(pub["published"]).iterdir())
        self.assertEqual(published, ["compiled.json", "pack-source.yaml", "rules-checker.json"])

    def test_history_and_checkout_find_the_pack_wherever_its_source_sits(self):
        drafts = self.ws / "drafts"
        drafts.mkdir()
        loose = drafts / "foo.yaml"
        loose.write_text(self.src.read_text())
        code, res = call("run", loose, "--workspace", self.ws, "--dry-run", "--generated-at", GENERATED)
        self.assertEqual(code, 0, res)
        code, hist = call("history", loose, "--workspace", self.ws)
        self.assertEqual((code, [e["digest"] for e in hist["history"]]), (0, [res["pack_digest"]]))
        self.assertEqual(call("checkout", loose, res["pack_digest"][:8], "--workspace", self.ws)[0], 0)

    def test_checkout_notices_an_edit_the_digest_does_not_cover(self):
        first = self.run_pack()
        text = self.src.read_text()
        self.src.write_text(text.replace("stickers terms", "stickers, my words"))
        code, res = call("checkout", self.src, first["pack_digest"], "--workspace", self.ws)
        self.assertEqual(code, 1, res)
        self.assertIn("stickers, my words", self.src.read_text())
        self.assertEqual(self.run_pack()["pack_digest"], first["pack_digest"])  # same digest, newest bytes kept
        self.assertEqual(call("checkout", self.src, first["pack_digest"], "--workspace", self.ws)[0], 0)
        self.assertIn("stickers, my words", self.src.read_text())

    def test_checkout_says_which_two_digests_to_compare(self):
        first = self.run_pack()
        self.edit("delivered_within_days(2)", "delivered_within_days(3)", "0.2.0")
        second = self.run_pack()
        code, res = call("checkout", self.src, first["pack_digest"], "--workspace", self.ws)
        self.assertEqual(res["replaced"], second["pack_digest"])
        self.assertIn(f"terms compare {second['pack_digest'][:12]} {first['pack_digest'][:12]} --workspace", res["next"])
        self.assertIn(str(self.ws.resolve()), res["next"])

    def test_a_linked_history_or_private_folder_is_refused(self):
        outside = pathlib.Path(self.tmp.name) / "outside"
        outside.mkdir()
        talk = pathlib.Path(self.tmp.name) / "talk.md"
        talk.write_text("x")
        (self.folder / "private").symlink_to(outside)
        code, res = call("keep-transcript", self.src, talk, "--workspace", self.ws)
        self.assertEqual(code, 1, res)
        (self.folder / "history").symlink_to(outside)
        code, res = call("run", self.src, "--workspace", self.ws, "--dry-run")
        self.assertEqual(code, 1, res)
        self.assertEqual(list(outside.iterdir()), [])

    def test_two_transcripts_in_one_second_are_both_kept(self):
        talk = pathlib.Path(self.tmp.name) / "talk.md"
        talk.write_text("x")
        import workspace
        import datetime
        now = datetime.datetime(2026, 11, 6, 12, 0, 0, tzinfo=datetime.timezone.utc)
        one = workspace.keep_transcript(self.folder, talk, now)
        two = workspace.keep_transcript(self.folder, talk, now)
        self.assertNotEqual(one, two)

    def test_force_checkout_restores_a_source_broken_by_an_edit(self):
        first = self.run_pack()
        self.src.write_text("rows: [unclosed\n")
        code, res = call("checkout", self.src, first["pack_digest"], "--workspace", self.ws, "--force")
        self.assertEqual(code, 0, res)
        self.assertIn("pack_id: stickers", self.src.read_text())

    def test_a_new_pack_can_keep_a_transcript_before_its_first_run(self):
        loose = self.ws / "drafts" / "foo.yaml"
        loose.parent.mkdir()
        loose.write_text(self.src.read_text().replace("pack_id: stickers", "pack_id: fresh"))
        talk = pathlib.Path(self.tmp.name) / "talk.md"
        talk.write_text("x")
        code, res = call("keep-transcript", loose, talk, "--workspace", self.ws)
        self.assertEqual(code, 0, res)
        self.assertEqual(pathlib.Path(res["kept"]).parent, (self.ws / "packs" / "fresh" / "private").resolve())

    def test_a_new_shell_finds_the_workspace_from_the_pack_folder(self):
        env = os.environ.pop("TERMS_WORKSPACE", None)
        self.addCleanup(lambda: env and os.environ.__setitem__("TERMS_WORKSPACE", env))
        code, res = call("run", self.src, "--dry-run")  # no --workspace, no env, no sales flag
        self.assertEqual((code, res["sales"]), (0, 10), res)
        code, hist = call("history", self.src)
        self.assertEqual((code, len(hist["history"]), hist["workspace"]), (0, 1, str(self.ws.resolve())))

    def test_compare_takes_a_run_as_history_prints_it_and_a_dataset_inside_the_workspace_moves_too(self):
        first = self.run_pack()
        rel = json.loads((self.folder / "history.jsonl").read_text().splitlines()[0])["run"]
        self.assertFalse(pathlib.Path(rel).is_absolute())
        code, res = call("compare", rel, first["run"], "--workspace", self.ws)
        self.assertEqual(code, 0, res)
        inside = self.ws / "dev-sales.json"
        inside.write_text(TRADES.read_text())
        self.assertEqual(self.run_pack("--deals", inside)["sales"], 10)
        self.assertEqual(json.loads((self.folder / "workspace.json").read_text())["dataset"]["path"], "dev-sales.json")
        moved = pathlib.Path(self.tmp.name) / "moved2"
        self.ws.rename(moved)
        code, res = call("run", moved / "packs" / "stickers" / "pack-source.yaml", "--dry-run")
        self.assertEqual((code, res["sales"]), (0, 10), res)

    def test_the_workspace_can_move_and_compare_by_digest_still_works(self):
        first = self.run_pack()
        self.edit("delivered_within_days(2)", "delivered_within_days(3)", "0.2.0")
        second = self.run_pack()
        moved = pathlib.Path(self.tmp.name) / "moved"
        self.ws.rename(moved)
        code, res = call("compare", first["pack_digest"][:12], second["pack_digest"][:12], "--workspace", moved)
        self.assertEqual(code, 0, res)

    def test_a_stray_file_or_bad_history_in_packs_does_not_block_compare(self):
        first = self.run_pack()
        (self.ws / "packs" / ".DS_Store").write_text("x")
        (self.ws / "packs" / "other").mkdir()
        (self.ws / "packs" / "other" / "history.jsonl").write_text("not json\n")
        code, res = call("compare", first["pack_digest"][:12], first["run"], "--workspace", self.ws)
        self.assertEqual(code, 0, res)

    def test_run_says_when_the_remembered_sales_changed(self):
        self.assertFalse(self.run_pack()["dataset_changed"])
        data = json.loads(TRADES.read_text())
        deals = data["trades"] if isinstance(data, dict) else data
        deals[0]["note"] = "changed"
        copy = pathlib.Path(self.tmp.name) / "trades2.json"
        copy.write_text(json.dumps(deals))
        self.assertTrue(self.run_pack("--deals", copy)["dataset_changed"])

    def test_init_that_refuses_the_data_leaves_nothing_behind(self):
        bad = pathlib.Path(self.tmp.name) / "big.json"
        bad.write_text(json.dumps([{"deal_id": "a", "t": 1730000000000000000}]))
        code, res = call("init", "--deals", bad, "--workspace", self.ws, "--pack-id", "big")
        self.assertEqual(code, 1, res)
        self.assertFalse((self.ws / "packs" / "big" / "pack-source.yaml").exists())

    def test_force_checkout_of_an_unrun_edit_does_not_suggest_a_compare(self):
        first = self.run_pack()
        self.edit("delivered_within_days(2)", "delivered_within_days(9)", "0.3.0")  # lints, never run
        code, res = call("checkout", self.src, first["pack_digest"], "--workspace", self.ws, "--force")
        self.assertEqual(code, 0, res)
        self.assertNotIn("compare", res["next"])

    def test_checkout_will_not_write_through_a_linked_source_or_read_a_linked_history(self):
        first = self.run_pack()
        real = pathlib.Path(self.tmp.name) / "real.yaml"
        real.write_text(self.src.read_text())
        link = self.ws / "packs" / "stickers" / "link.yaml"
        link.symlink_to(real)
        code, res = call("checkout", link, first["pack_digest"], "--workspace", self.ws, "--force")
        self.assertEqual(code, 1, res)
        (self.folder / "history").rename(self.folder / "history-real")
        (self.folder / "history").symlink_to(self.folder / "history-real")
        code, res = call("checkout", self.src, first["pack_digest"], "--workspace", self.ws, "--force")
        self.assertEqual(code, 1, res)

    def test_read_only_verbs_do_not_make_the_workspace(self):
        gone = pathlib.Path(self.tmp.name) / "never"
        code, _ = call("compare", "aaaaaa", "bbbbbb", "--workspace", gone)
        self.assertEqual(code, 1)
        self.assertFalse(gone.exists())


if __name__ == "__main__":
    unittest.main()
