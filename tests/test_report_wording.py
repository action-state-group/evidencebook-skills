"""report.sh --wording and the committed settlement wording pack (evidencebook-skills#102).

Three groups. (1) scripts/wording_pack.py refuses a pack that capsulectl would
take but the page would not use. (2) report.sh passes the pack to
`book report build` on each path, adds the contract-report/v1 opt-in only on the
evaluator path, and refuses a bad pack before anything is written to the book.
(3) The committed pack covers every row of packs/inference-deals and says
nothing the viewer locks. What the page then SHOWS is checked in a real browser
by tests/fresh_env_deals.sh, which needs a capsulectl-book carrying --wording.
"""
import hashlib
import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import wire_presentation  # noqa: E402
import wording_pack  # noqa: E402

BASH = shutil.which("bash")
PACK = ROOT / "wording" / "inference-deals-settlement-en.json"
PACK_DIGEST = ROOT / "wording" / "inference-deals-settlement-en.sha256"
COMPILED = ROOT / "packs" / "inference-deals" / "compiled" / "compiled.json"

STUB_EVALUATOR = r'''#!/usr/bin/env python3
import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from result_v0 import build_result_v0_for_day
argv = sys.argv[1:]
out = pathlib.Path(argv[argv.index("--out") + 1])
out.mkdir(parents=True, exist_ok=True)
doc = build_result_v0_for_day("day:2026-10-01", [("case-1", {"c1": "met"}, {"c1": ["ab" * 32]}, {"c1": "judged"})],
                              "2026-10-01T23:59:59Z", ("c1",), "stub-pack@1")
(out / "result-v0-2026-10-01.json").write_text(json.dumps(doc))
'''

# Records the argv of `book report build` and the bundle it was handed, and writes a
# bundle with no extensions, the way `disclose` does for a pack with no presentation.json.
STUB_CAPSULECTL = r'''#!/usr/bin/env python3
import json, os, shutil, sys
argv = sys.argv[1:]
def opt(name):
    return argv[argv.index(name) + 1]
cap = os.environ["STUB_CAPTURE"]
with open(os.path.join(cap, "calls.log"), "a") as f:
    f.write(json.dumps(argv) + "\n")
if argv[:3] == ["book", "result", "build"]:
    shutil.copy(opt("--result"), opt("--out"))
    print(json.dumps({"record_id": "rec-1"}))
elif argv[:3] == ["cll", "checkpoint", "create"]:
    print("{}")
elif argv[:1] == ["disclose"]:
    json.dump({"records": [], "completeness_certificate": {"memberships": {}}}, open(opt("--out"), "w"))
elif argv[:3] == ["book", "report", "build"]:
    shutil.copy(opt("--bundle"), os.path.join(cap, "built-bundle.json"))
    open(opt("--out"), "w").write("<html></html>")
    print("{}")
else:
    sys.exit("stub capsulectl: unexpected call " + " ".join(argv))
'''


def _exe(path, text):
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


class WordingPackCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="test-wording-pack-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def write(self, doc):
        path = self.tmp / "pack.json"
        path.write_text(doc if isinstance(doc, str) else json.dumps(doc))
        return path

    def good(self):
        return {"wording_pack_version": "aac.wording-pack/v0", "id": "x/v0", "locale": "en",
                "entries": {"report.title": "T"}}

    def test_a_good_pack_passes_with_its_digest(self):
        path = self.write(self.good())
        self.assertEqual(wording_pack.check(path, _sha(path))["id"], "x/v0")

    def test_a_digest_that_does_not_match_the_bytes_is_refused(self):
        path = self.write(self.good())
        with self.assertRaisesRegex(wording_pack.PackError, "hashes to"):
            wording_pack.check(path, "0" * 64)

    def test_a_digest_that_is_not_lowercase_hex_is_refused(self):
        path = self.write(self.good())
        for bad in (_sha(path).upper(), "abc", ""):
            with self.assertRaisesRegex(wording_pack.PackError, "64 lowercase hex"):
                wording_pack.check(path, bad)

    def test_the_viewers_shape_rules_are_checked_early(self):
        base = self.good()
        for name, mutate in {
            "another version": lambda p: p.update(wording_pack_version="aac.wording-pack/v1"),
            "no id": lambda p: p.pop("id"),
            "no entries": lambda p: p.update(entries={}),
            "an empty entry": lambda p: p["entries"].update({"report.title": ""}),
            "a non-string entry": lambda p: p["entries"].update({"report.title": 3}),
            "a bad key": lambda p: p["entries"].update({"Report Title": "T"}),
            "a core key": lambda p: p["entries"].update({"core.strip": "T"}),
            "an extra member": lambda p: p.update(extra=1),
            "an invisible character in the id": lambda p: p.update(id="x\u202e/v0"),
            "an invisible character in an entry": lambda p: p["entries"].update({"report.title": "T\u200bU"}),
            "a locale that is not a locale": lambda p: p.update(locale="e"),
        }.items():
            with self.subTest(name):
                pack = json.loads(json.dumps(base))
                mutate(pack)
                path = self.write(pack)
                with self.assertRaises(wording_pack.PackError):
                    wording_pack.check(path, _sha(path))

    def test_a_region_locale_is_taken_as_the_viewer_takes_it(self):
        pack = self.good()
        pack["locale"] = "en-US"
        path = self.write(pack)
        self.assertEqual(wording_pack.check(path, _sha(path))["locale"], "en-US")

    def test_text_that_is_not_json_is_refused(self):
        path = self.write("not json")
        with self.assertRaisesRegex(wording_pack.PackError, "not JSON"):
            wording_pack.check(path, _sha(path))


class CommittedSettlementPack(unittest.TestCase):
    pack = json.loads(PACK.read_text())
    compiled = json.loads(COMPILED.read_text())

    def test_its_digest_is_the_one_committed_beside_it(self):
        self.assertEqual(PACK_DIGEST.read_text().strip(), _sha(PACK))
        wording_pack.check(PACK, PACK_DIGEST.read_text().strip())

    def test_it_names_every_row_and_group_of_the_pack_and_no_other(self):
        entries = self.pack["entries"]
        clause_ids = [c["id"] for c in self.compiled["clauses"]]
        # The viewer groups a row by the part of its requirement_ref before the first dot.
        groups = {c["id"].split(".", 1)[0] for c in self.compiled["clauses"]}
        for cid in clause_ids:
            for part in ("label", "detail", "not_evaluable"):
                self.assertIn(f"row.{cid}.{part}", entries)
        for group in groups:
            self.assertIn(f"group.{group}.title", entries)
        rows = {k.split(".", 1)[1].rsplit(".", 1)[0] for k in entries if k.startswith("row.")}
        self.assertEqual(rows, set(clause_ids), "a row key for a clause the pack does not have shows nowhere")

    def test_it_keeps_clear_of_what_the_viewer_locks(self):
        # grade, status, sufficiency and requirement_tier words state what the sealed claim says
        # about its own evidence; a pack that rewords one is dropped whole by the page and the page
        # still seals and checks, so nothing but this test would notice.
        locked = ("grade.", "status.", "sufficiency.", "requirement_tier.", "core.", "front.", "card.mark.")
        self.assertEqual([k for k in self.pack["entries"] if k.startswith(locked)], [])

    def test_every_verdict_word_is_its_own(self):
        words = {k: v for k, v in self.pack["entries"].items() if k.startswith("verdict.")}
        self.assertEqual(sorted(words), ["verdict.met", "verdict.not_evaluable", "verdict.not_met", "verdict.out_of_scope"])
        self.assertEqual(len({v.lower() for v in words.values()}), len(words))

    def test_it_has_no_score_percentage_or_grade_letter(self):
        text = " ".join(self.pack["entries"].values()).lower()
        for word in ("%", "percent", "score", "grade ", "rating", "rated"):
            self.assertNotIn(word, text)

    def test_a_row_label_does_not_promise_more_than_the_evaluator_checks(self):
        entries = self.pack["entries"]
        self.assertIn("its own record", entries["row.come_through.served_named_model.label"])
        self.assertIn("does not show that the answer was good", entries["row.come_through.served_as_agreed.detail"])
        self.assertIn("which no one else has checked", entries["row.come_through.served_named_model.detail"])

    def test_an_undecided_row_says_why_a_deal_can_be_undecided(self):
        # #187: a record whose signature fails, or whose signer is not trusted, makes the deal
        # undecided; the page must not blame the records' content, nor call it tampering.
        entries = self.pack["entries"]
        for cid in (c["id"] for c in self.compiled["clauses"]):
            note = entries[f"row.{cid}.not_evaluable"]
            self.assertIn("signature did not verify", note)
            self.assertIn("not a sign of tampering", note)
        self.assertIn("not a sign of tampering", entries["report.summary"])

    def test_it_uses_no_placeholder(self):
        # A row word has no slot the page could fill, and a stray {x} would show as text.
        self.assertFalse([k for k, v in self.pack["entries"].items() if "{" in v or "}" in v])


class OptIn(unittest.TestCase):
    def test_it_adds_only_the_empty_contract_report_block(self):
        bundle = {"records": [], "extensions": {"other/v1": {"a": 1}}}
        wired = wire_presentation.opt_in(bundle)
        self.assertEqual(wired["extensions"], {"other/v1": {"a": 1}, "contract-report/v1": {}})
        self.assertNotIn("contract-report/v1", bundle["extensions"], "the input is not modified")

    def test_a_bundle_with_no_extensions_gets_one(self):
        self.assertEqual(wire_presentation.opt_in({"records": []})["extensions"], {"contract-report/v1": {}})

    def test_one_that_already_has_it_is_refused_not_overwritten(self):
        with self.assertRaises(wire_presentation.WireError):
            wire_presentation.opt_in({"extensions": {"contract-report/v1": {}}})

    def test_a_bundle_that_is_not_an_object_is_refused(self):
        with self.assertRaises(wire_presentation.WireError):
            wire_presentation.opt_in([])


@unittest.skipIf(BASH is None or shutil.which("jq") is None, "needs bash and jq")
class ReportShWording(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="test-report-wording-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        shutil.copytree(ROOT / "scripts", self.tmp / "scripts")
        _exe(self.tmp / "scripts" / "evaluators" / "stub_eval.py", STUB_EVALUATOR)
        self.ctl = self.tmp / "capsulectl"
        _exe(self.ctl, STUB_CAPSULECTL)
        self.capture = self.tmp / "capture"
        self.capture.mkdir()
        self.spec = self.tmp / "eval.json"
        self.spec.write_text(json.dumps({"contract": "stub-pack", "clauses": [{"id": "c1"}], "evaluator": "stub_eval",
                                         "presentation": {"card": "settlement"}}))

    def run_report(self, *args, spec=None):
        env = dict(os.environ)
        env.update({"STUB_CAPTURE": str(self.capture),
                    "PATH": f"{pathlib.Path(sys.executable).parent}{os.pathsep}{env.get('PATH', '')}"})
        cmd = [BASH, str(self.tmp / "scripts" / "report.sh"), "--spec", str(spec or self.spec), "--profile", "p",
               "--date", "2026-10-01", "--out", str(self.tmp / "report.html"), "--capsulectl", str(self.ctl),
               "--work", str(self.tmp / "work"), *args]
        return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120)

    def build_argv(self):
        calls = [json.loads(line) for line in (self.capture / "calls.log").read_text().splitlines()]
        builds = [c for c in calls if c[:3] == ["book", "report", "build"]]
        self.assertEqual(len(builds), 1)
        return builds[0]

    def built_extensions(self):
        return json.loads((self.capture / "built-bundle.json").read_text()).get("extensions", {})

    def digest_args(self):
        return ["--wording", str(PACK), "--wording-digest", _sha(PACK)]

    def test_the_evaluator_path_passes_the_pack_and_opts_into_the_contract_report(self):
        proc = self.run_report(*self.digest_args())
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        argv = self.build_argv()
        self.assertEqual(argv[argv.index("--wording") + 1], str(PACK))
        self.assertEqual(argv[argv.index("--wording-digest") + 1], _sha(PACK))
        self.assertEqual(self.built_extensions(), {"contract-report/v1": {}})

    def test_without_the_pack_the_evaluator_page_is_unchanged(self):
        proc = self.run_report()
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        argv = self.build_argv()
        self.assertNotIn("--wording", argv)
        self.assertNotIn("--wording-digest", argv)
        self.assertEqual(self.built_extensions(), {})

    def test_seal_and_wording_together_reach_the_same_build(self):
        # The stub has no `report check`, so the run stops there; what matters is the one build call.
        self.run_report("--seal", *self.digest_args())
        argv = self.build_argv()
        self.assertIn("--seal", argv)
        self.assertEqual(argv[argv.index("--wording-digest") + 1], _sha(PACK))

    @unittest.skipUnless(os.path.exists("/bin/bash"), "no system bash")
    def test_the_flag_paths_run_under_the_system_bash(self):
        # macOS's /bin/bash is 3.2, where an empty array under `set -u` and `mapfile` break.
        for case in ([], self.digest_args()):
            shutil.rmtree(self.capture); self.capture.mkdir()
            env = dict(os.environ, STUB_CAPTURE=str(self.capture),
                       PATH=f"{pathlib.Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}")
            proc = subprocess.run(["/bin/bash", str(self.tmp / "scripts" / "report.sh"), "--spec", str(self.spec),
                                   "--profile", "p", "--date", "2026-10-01", "--out", str(self.tmp / "r.html"),
                                   "--capsulectl", str(self.ctl), "--work", str(self.tmp / "w3"), *case],
                                  capture_output=True, text=True, env=env, timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            self.assertEqual("--wording" in self.build_argv(), bool(case))

    def test_the_two_flags_come_together(self):
        for args in (["--wording", str(PACK)], ["--wording-digest", _sha(PACK)]):
            proc = self.run_report(*args)
            self.assertEqual(proc.returncode, 2, proc.stderr)
            self.assertIn("come together", proc.stderr)
            self.assertFalse((self.capture / "calls.log").exists())

    def test_a_wrong_digest_stops_the_run_before_anything_is_written_to_the_book(self):
        proc = self.run_report("--wording", str(PACK), "--wording-digest", "0" * 64)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("hashes to", proc.stderr)
        self.assertFalse((self.capture / "calls.log").exists(), "no capsulectl call at all")

    def test_a_wrong_digest_with_seal_still_removes_an_earlier_page(self):
        # report.sh's own contract: a failed --seal run leaves no page at --out.
        out = self.tmp / "report.html"
        out.write_text("<html>an earlier page</html>")
        proc = self.run_report("--seal", "--wording", str(PACK), "--wording-digest", "0" * 64)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertFalse(out.exists())

    def test_a_missing_pack_stops_the_run_the_same_way(self):
        proc = self.run_report("--wording", str(self.tmp / "nope.json"), "--wording-digest", "0" * 64)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertFalse((self.capture / "calls.log").exists())

    def test_the_judged_path_passes_the_pack_through_and_adds_no_opt_in(self):
        spec = self.tmp / "judged.json"
        spec.write_text(json.dumps({"contract": "stub-pack", "clauses": [{"id": "c1"}],
                                    "judge": {"model_id": "jev-1.13.0"}}))
        _exe(self.tmp / "scripts" / "run_daily.py", "#!/usr/bin/env python3\n")
        _exe(self.tmp / "scripts" / "rollup_day.py", STUB_ROLLUP_DAY)
        proc = self.run_report(*self.digest_args(), spec=spec)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        argv = self.build_argv()
        self.assertEqual(argv[argv.index("--wording-digest") + 1], _sha(PACK))
        self.assertEqual(self.built_extensions(), {})


STUB_ROLLUP_DAY = r'''#!/usr/bin/env python3
import pathlib, sys, json
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from result_v0 import build_result_v0_for_day
argv = sys.argv[1:]
out = pathlib.Path(argv[argv.index("--out") + 1])
out.mkdir(parents=True, exist_ok=True)
doc = build_result_v0_for_day("day:2026-10-01", [("case-1", {"c1": "met"}, {"c1": ["ab" * 32]}, {"c1": "judged"})],
                              "2026-10-01T23:59:59Z", ("c1",), "stub-pack@1")
(out / "result-v0-2026-10-01.json").write_text(json.dumps(doc))
'''


if __name__ == "__main__":
    unittest.main()
