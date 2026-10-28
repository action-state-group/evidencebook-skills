"""The evidencebook-report skill's three grades, at the pieces this repo owns.

Grade 1 (narrated): scripts/narration_check.py over records given to it.
Grade 2 (sealed and checked): scripts/report.sh --seal against a stub
capsulectl, which isolates what report.sh decides: that it seals, that it runs
`book report check`, and that a page which does not match is never left at
--out. tests/fresh_env_report.sh runs the same against a real capsulectl.
No pack: scripts/packs.py's refusal.
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import narration_check  # noqa: E402
import packs  # noqa: E402
from test_report_sh import BASH, STUB_ROLLUP_DAY, STUB_RUN_DAILY, _exe  # noqa: E402

RESULT = {
    "result_version": "evidence-result-v0",
    "generated_at": "2026-10-28T23:59:59Z",
    "claims": [{"id": "2026-10-28::refund_within_policy", "verdict": "met",
                "evidence": [{"digest": "sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"}]}],
    "aggregate": {"buckets": {"met": ["2026-10-28::refund_within_policy"], "not_met": [], "not_evaluable": []},
                  "coverage": {"evaluated_population": 12, "excluded_not_applicable": 0, "unknown_count": 0}},
    "view": {"title": "Refunds, 1,250 conversations"},
    "x-digest": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
}
RID = "4291b3a0"


def narration(*body):
    return "\n".join([*body, narration_check.OFFER, "Narrated by your agent, from your records."])


class Narration(unittest.TestCase):
    def findings(self, text, records=None):
        return narration_check.check(text, {RID: RESULT} if records is None else records)

    def test_a_cited_number_read_from_the_result_passes(self):
        self.assertEqual(self.findings(narration(f"On 2026-10-28 the report [{RID}] evaluated 12 checks.")), [])

    def test_a_computed_number_fails(self):
        found = self.findings(narration(f"The report [{RID}] evaluated 12 checks, 13 with yesterday."))
        self.assertTrue(any(f.startswith("states 13 ") for f in found), found)

    def test_a_number_from_a_digest_is_not_read_from_the_record(self):
        # 9 and 86 are digit runs inside x-digest; neither is a number the Result states.
        found = self.findings(narration(f"The report [{RID}] has 86 checks."))
        self.assertTrue(any(f.startswith("states 86 ") for f in found), found)

    def test_a_number_cited_from_another_sentence_fails(self):
        found = self.findings(narration(f"The report is [{RID}].", "It evaluated 12 checks."))
        self.assertTrue(any(f.startswith("states 12 ") for f in found), found)

    def test_a_record_it_was_not_given_cannot_be_cited(self):
        found = self.findings(narration("The report [deadbeef] evaluated 12 checks."))
        self.assertIn("cites [deadbeef], a record it was not given as verified", found)

    def test_no_citation_fails(self):
        found = self.findings(narration("Everything went through."))
        self.assertTrue(any(f.startswith("cites no verified record") for f in found), found)

    def test_every_statement_cites_not_just_one(self):
        found = self.findings(narration(f"The report exists [{RID}].", "Everything was approved."))
        self.assertEqual(found, ["cites no verified record for this statement: 'Everything was approved.'"])

    def test_the_no_total_sentence_stands_without_a_citation(self):
        text = narration(f"I read 3 deals [{RID}].", narration_check.NO_TOTAL)
        self.assertEqual(self.findings(text, {RID: {"deals": [1, 2, 3]}}), [])

    def test_the_skill_quotes_the_checks_fixed_words(self):
        skill = (ROOT / "skills/evidencebook-report/SKILL.md").read_text()
        for fixed in (*narration_check.FIXED, narration_check.LABEL):
            self.assertIn(fixed, " ".join(skill.split()), fixed)

    def test_a_number_in_the_label_sentence_is_checked(self):
        text = f"The report [{RID}] covers 99 deals, narrated by your agent, from your records.\n{narration_check.OFFER}"
        found = self.findings(text)
        self.assertTrue(any(f.startswith("states 99 ") for f in found), found)

    def test_a_grouped_number_is_read_whole(self):
        self.assertEqual(self.findings(narration(f"The report [{RID}] covers 1,250 conversations.")), [])
        found = self.findings(narration(f"The report [{RID}] covers 1,000 conversations."))
        self.assertTrue(any(f.startswith("states 1,000 ") for f in found), found)

    def test_a_timestamp_and_a_dated_claim_id_are_read(self):
        text = narration(f"The report [{RID}] was generated on 2026-10-28 at 23:59.")
        self.assertEqual(self.findings(text), [])

    def test_a_spelled_out_number_fails(self):
        found = self.findings(narration(f"The report [{RID}] evaluated twelve checks."))
        self.assertTrue(any(f.startswith("writes the number 'twelve' as a word") for f in found), found)
        self.assertTrue(any(f.startswith("states a number but") for f in
                            self.findings(f"The report [{RID}] evaluated twelve checks.\n"
                                          "Narrated by your agent, from your records.")))

    def test_unlabelled_fails(self):
        found = self.findings(f"The report [{RID}] says everything was met.")
        self.assertTrue(any(f.startswith("not labelled") for f in found), found)

    def test_a_percentage_fails(self):
        found = self.findings(narration(f"The report [{RID}] met 100% of 12 checks."))
        self.assertIn("shows a percentage", found)

    def test_a_count_without_the_offer_fails(self):
        text = f"The report [{RID}] evaluated 12 checks.\nNarrated by your agent, from your records."
        found = self.findings(text)
        self.assertTrue(any(f.startswith("states a number but does not offer") for f in found), found)

    def test_no_number_needs_no_offer(self):
        text = f"The report [{RID}] says everything was met.\nNarrated by your agent, from your records."
        self.assertEqual(self.findings(text), [])

    def test_the_offer_is_made_once(self):
        text = narration(f"The report [{RID}] evaluated 12 checks.", narration_check.OFFER)
        self.assertIn("offers the sealed version more than once", self.findings(text))

    def test_the_command_line_exits_1_with_findings(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "r.json").write_text(json.dumps(RESULT))
        (tmp / "n.txt").write_text(narration(f"The report [{RID}] evaluated 13 checks."))
        proc = subprocess.run([sys.executable, str(ROOT / "scripts/narration_check.py"), "--narration",
                               str(tmp / "n.txt"), "--record", f"{RID}={tmp / 'r.json'}"],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertFalse(json.loads(proc.stdout)["ok"])


class NoPack(unittest.TestCase):
    def test_every_pack_in_the_tree_is_listed_with_its_spec_and_card(self):
        listed = {p["name"]: p for p in packs.list_packs()}
        self.assertEqual(set(listed), {d.parent.name for d in (ROOT / "packs").glob("*/pack-source.yaml")})
        for p in listed.values():
            self.assertTrue((ROOT / p["spec"]).is_file(), p)
        self.assertEqual(listed["eu-ai-act-obligations"]["card"], "obligation")

    def test_a_pack_is_found_by_its_name_or_its_pack_id(self):
        self.assertEqual(packs.require("everyday-rules")[1]["name"], "everyday-rules")
        self.assertEqual(packs.require("asg/everyday-rules")[1]["name"], "everyday-rules")

    def assert_honest(self, answer):
        self.assertEqual(answer["refused"], "no_pack")
        self.assertEqual(answer["packs"], [p["name"] for p in packs.list_packs()])
        say = answer["say"]
        for title in answer["titles"]:
            self.assertIn(title, say)
            say = say.replace(title, "")
        self.assertIn("History card (your checkpoints and receipts; it has no totals yet)", say)
        # No count, no judgment: there is no Result to read one from.
        self.assertIsNone(re.search(r"\d", say), say)

    def test_a_question_with_no_pack_is_refused_honestly(self):
        code, answer = packs.require("personal-deals")
        self.assertEqual(code, packs.REFUSED)
        self.assert_honest(answer)

    def test_refuse_needs_no_pack_name(self):
        proc = subprocess.run([sys.executable, str(ROOT / "scripts/packs.py"), "refuse"],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, packs.REFUSED, proc.stderr)
        answer = json.loads(proc.stdout)
        self.assertIsNone(answer["asked"])
        self.assert_honest(answer)

    def test_an_uncompiled_pack_is_refused_too(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "packs" / "draft").mkdir(parents=True)
        (tmp / "packs" / "draft" / "pack-source.yaml").write_text("pack_id: draft\n")
        code, answer = packs.require("draft", root=tmp)
        self.assertEqual(code, packs.REFUSED)
        self.assertEqual(answer["reason"], "the draft pack is not compiled yet")
        self.assertTrue(answer["say"].startswith("The draft pack exists but isn't ready to report from yet."),
                        answer["say"])


STUB_CAPSULECTL = r'''#!/usr/bin/env python3
import json, os, shutil, sys
argv = sys.argv[1:]
def opt(name):
    return argv[argv.index(name) + 1]
log = os.environ["STUB_CALLS"]
with open(log, "a") as f:
    f.write(json.dumps(argv) + "\n")
if argv[:3] == ["book", "result", "build"]:
    shutil.copy(opt("--result"), opt("--out"))
    print(json.dumps({"record_id": "rec-1"}))
elif argv[:3] == ["cll", "checkpoint", "create"]:
    print("{}")
elif argv[:1] == ["disclose"]:
    json.dump({"records": [], "completeness_certificate": {"memberships": {}}}, open(opt("--out"), "w"))
elif argv[:3] == ["book", "report", "build"]:
    open(opt("--out"), "w").write("<html></html>")
    print("{}")
elif argv[:3] == ["book", "report", "check"]:
    page = os.environ.get("STUB_CHECK_PAGE", "match")
    print(json.dumps({"page": page, "verification": os.environ.get("STUB_CHECK_VERIFICATION", "VALID")}))
    sys.exit(0 if page == "match" else 5)
else:
    sys.exit("stub capsulectl: unexpected call " + " ".join(argv))
'''


@unittest.skipIf(BASH is None or shutil.which("jq") is None, "needs bash and jq")
class SealedAndChecked(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="test-report-grades-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        shutil.copytree(ROOT / "scripts", self.tmp / "scripts")
        _exe(self.tmp / "scripts" / "run_daily.py", STUB_RUN_DAILY)
        _exe(self.tmp / "scripts" / "rollup_day.py", STUB_ROLLUP_DAY)
        self.ctl = self.tmp / "capsulectl"
        _exe(self.ctl, STUB_CAPSULECTL)
        self.spec = self.tmp / "contract.json"
        self.spec.write_text(json.dumps({"contract": "stub-pack", "clauses": [{"id": "c1"}],
                                         "judge": {"model_id": "jev-1.13.0"}}))
        self.calls_log = self.tmp / "calls.log"
        self.out = self.tmp / "report.html"

    def run_report(self, *args, **env_extra):
        env = dict(os.environ)
        env.update({"STUB_LOG": str(self.tmp / "stub.log"), "STUB_CAPTURE": str(self.tmp),
                    "STUB_DAYS": "2026-10-01", "STUB_CALLS": str(self.calls_log),
                    "PATH": f"{pathlib.Path(sys.executable).parent}{os.pathsep}{env.get('PATH', '')}"})
        env.update(env_extra)
        cmd = [BASH, str(self.tmp / "scripts" / "report.sh"), "--spec", str(self.spec), "--profile", "p",
               "--date", "2026-10-01", "--out", str(self.out), "--capsulectl", str(self.ctl),
               "--work", str(self.tmp / "work"), *args]
        return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120)

    def calls(self):
        return [json.loads(line) for line in self.calls_log.read_text().splitlines()]

    def test_seal_seals_the_page_then_checks_it(self):
        proc = self.run_report("--seal")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        build = next(c for c in self.calls() if c[:3] == ["book", "report", "build"])
        self.assertIn("--seal", build)
        page = build[build.index("--out") + 1]
        self.assertNotEqual(page, str(self.out))
        self.assertEqual(self.calls()[-1], ["book", "report", "check", "--profile", "p", "--page", page])
        self.assertIn("sealed and checked", proc.stdout)
        self.assertTrue(self.out.is_file())
        self.assertFalse(pathlib.Path(page).exists())

    def test_a_failed_run_leaves_no_earlier_page_at_out(self):
        self.out.write_text("<html>an earlier, unsealed page</html>")
        proc = self.run_report("--seal", STUB_CHECK_PAGE="mismatch")
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(self.out.exists())

    def test_without_seal_nothing_is_sealed_or_checked(self):
        proc = self.run_report()
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        build = next(c for c in self.calls() if c[:3] == ["book", "report", "build"])
        self.assertNotIn("--seal", build)
        self.assertFalse(any(c[:3] == ["book", "report", "check"] for c in self.calls()))

    def test_a_mismatched_page_is_not_handed_over(self):
        proc = self.run_report("--seal", STUB_CHECK_PAGE="mismatch")
        self.assertEqual(proc.returncode, 1)
        self.assertIn('"page": "mismatch"', proc.stdout)
        self.assertIn("report check did not match", proc.stderr)
        self.assertFalse(self.out.exists())
        self.assertTrue((self.tmp / "work" / "last-run" / "report.html").is_file())

    def test_a_match_over_evidence_that_is_not_valid_is_not_handed_over(self):
        proc = self.run_report("--seal", STUB_CHECK_VERIFICATION="INCOMPLETE")
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(self.out.exists())


if __name__ == "__main__":
    unittest.main()
