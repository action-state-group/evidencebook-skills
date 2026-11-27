"""The `regrade` record and the judged rows it sits beside (evidencebook#116 PR 9,
Steven's Q3: a regrade sits beside the judged row and never replaces it).

    python3 -m unittest discover -s tests -p 'test_*.py'
"""
import contextlib
import hashlib
import io
import json
import os
import pathlib
import stat
import sys
import tempfile
import unittest
import unittest.mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from capsulectl_calls import CapsuleDoesNotVerify, EvidenceUnavailable, UntrustedSigner  # noqa: E402
from clause_report import CLAUSE_REPORT, LEGACY_CLAUSE_REPORT  # noqa: E402
from rollup_day import group_reports  # noqa: E402
from run_daily import build_report  # noqa: E402
from run_weekly import week_frame  # noqa: E402
import regrade  # noqa: E402
from regrade import RegradeRefused, is_judged_row, regrade_record, rows_with_regrades  # noqa: E402

CONTRACT = "tau2-airline-outcomes/v1"
CONTRACT_REF = "airline-support-outcomes@1.6.1"
CLAUSE = {"id": "policy_compliance.within_fare_rules", "tier": "judged", "claim": "No change the fare class forbids."}
PIN = "ab" * 32
ROW_ID = "cd" * 32
AT = "2026-11-27T00:00:00Z"


def judged_row(verdict="met", **extra):
    return build_report(CLAUSE, {}, {"verdict": verdict, "rationale": "the judge's reason"}, CONTRACT,
                        "case-1", "ef" * 32, PIN, "2026-11-26", contract_ref=CONTRACT_REF, **extra)


def spec(switch=True, never=False, contract_ref=CONTRACT_REF, pack=None):
    s = {"contract_ref": contract_ref, "switches": {"out_of_scope_verdict": switch},
         "clauses": [{**CLAUSE, "never_out_of_scope": never}]}
    if pack is not None:
        s["pack_source_digest"] = pack
    return s


class Contents(unittest.TestCase):
    def test_the_record(self):
        body = regrade_record(ROW_ID, judged_row(), "not_met", "the fare class allowed it", "rater:expert-7", AT)
        self.assertEqual(body, {
            "record_type": "regrade", "epistemic_type": "human_report", "regraded_at": AT,
            "rater_ref": "rater:expert-7",
            "row": {"type": CLAUSE_REPORT, "digest_alg": "SHA-256", "digest": ROW_ID, "citation_purpose": "regraded_row"},
            "case_id": "case-1", "clause_id": CLAUSE["id"], "grade": "not_met", "reason": "the fare class allowed it"})

    def test_no_member_says_it_replaces_the_row(self):
        body = regrade_record(ROW_ID, judged_row(), "not_met", "r", "rater:1", AT)
        self.assertFalse({"supersedes", "verdict", "x-evidence-links", "links"} & set(body))

    def test_a_legacy_judged_row_cites_its_own_name(self):
        row = {**judged_row(), "record_type": LEGACY_CLAUSE_REPORT}
        self.assertEqual(regrade_record(ROW_ID, row, "met", "r", "rater:1", AT)["row"]["type"], LEGACY_CLAUSE_REPORT)


class Refusals(unittest.TestCase):
    def refused(self, row=None, grade="met", reason="r", rater="rater:1", s=None):
        with self.assertRaises(RegradeRefused):
            regrade_record(ROW_ID, judged_row() if row is None else row, grade, reason, rater, AT, spec=s)

    def test_a_recomputed_row(self):
        clause = {**CLAUSE, "id": "grounded_communication.prices_from_system", "tier": "recomputed"}
        with unittest.mock.patch.dict("run_daily.RECOMPUTE_CHECKS", {clause["id"]: len}):
            row = build_report(clause, {}, {"verdict": "met"}, CONTRACT, "case-1", "ef" * 32, PIN, "2026-11-26")
        self.assertFalse(is_judged_row(row))
        self.refused(row=row)

    def test_a_prechecked_judged_clause(self):
        row = {**judged_row(), "epistemic_type": "recomputed_determination"}
        row.pop("judge_pin_digest")
        self.refused(row=row)

    def test_a_regrade_of_a_regrade(self):
        self.refused(row=regrade_record(ROW_ID, judged_row(), "met", "r", "rater:1", AT))

    def test_not_a_clause_report(self):
        self.refused(row={"record_type": "skill-action/v1"})
        self.refused(row={"record_type": "human-rating/v1"})

    def test_empty_reason_or_rater(self):
        self.refused(reason="")
        self.refused(reason="   ")
        self.refused(rater="")
        self.refused(rater=" rater:1")

    def test_a_row_without_its_case_or_clause(self):
        self.refused(row={k: v for k, v in judged_row().items() if k != "case_id"})
        self.refused(row={**judged_row(), "clause_id": ""})

    def test_an_unknown_grade(self):
        self.refused(grade="pass")

    def test_out_of_scope_needs_the_row_s_own_contract(self):
        self.refused(grade="out_of_scope")  # no spec
        self.refused(grade="out_of_scope", s=spec(switch=False))
        self.refused(grade="out_of_scope", s=spec(never=True))
        self.refused(grade="out_of_scope", s=spec(contract_ref="airline-support-outcomes@1.6.0"))
        self.refused(row={k: v for k, v in judged_row().items() if k != "contract_ref"}, grade="out_of_scope", s=spec())
        self.refused(row=judged_row(pack_source_digest="11" * 32), grade="out_of_scope", s=spec(pack="22" * 32))
        body = regrade_record(ROW_ID, judged_row(pack_source_digest="11" * 32), "out_of_scope", "r", "rater:1", AT,
                              spec=spec(pack="11" * 32))
        self.assertEqual(body["grade"], "out_of_scope")


class Beside(unittest.TestCase):
    def setUp(self):
        self.row = judged_row("met")
        self.entries = [(ROW_ID, self.row),
                        ("r1", regrade_record(ROW_ID, self.row, "not_met", "first look", "rater:1", AT)),
                        ("r2", regrade_record(ROW_ID, self.row, "met", "second look", "rater:2", "2026-11-28T00:00:00Z"))]

    def test_both_grades_and_every_regrade_stay(self):
        shown = rows_with_regrades(self.entries, lambda _cid: None)
        self.assertEqual(shown["not_shown"], [])
        [row] = shown["rows"]
        self.assertEqual(row["judge"], {"verdict": "met", "judge_pin_digest": PIN})
        self.assertEqual([(r["capsule_id"], r["grade"]) for r in row["regrades"]], [("r1", "not_met"), ("r2", "met")])
        self.assertEqual(self.row["verdict"], "met")

    def test_a_row_without_a_regrade_is_not_listed(self):
        self.assertEqual(rows_with_regrades([(ROW_ID, self.row)], lambda _cid: None), {"rows": [], "not_shown": []})

    def test_what_is_not_shown_and_why(self):
        def check(cid):
            if cid == "bad":
                raise CapsuleDoesNotVerify("capsule bad does not verify")
        good = self.entries[1][1]
        entries = [self.entries[0],
                   ("bad", good),
                   ("orphan", {**good, "row": {**good["row"], "digest": "00" * 32}}),
                   ("other-case", {**good, "case_id": "case-2"}),
                   ("other-type", {**good, "row": {**good["row"], "type": LEGACY_CLAUSE_REPORT}}),
                   ("no-reason", {**good, "reason": ""}),
                   ("bad-purpose", {**good, "row": {**good["row"], "citation_purpose": "grounds"}})]
        shown = rows_with_regrades(entries, check)
        self.assertEqual(shown["rows"], [])
        self.assertEqual({n["capsule_id"]: n["why"].split(":")[0] for n in shown["not_shown"]}, {
            "bad": "does not verify", "orphan": "cites no judged row in this book",
            "other-case": "case, clause or row type differs from its row",
            "other-type": "case, clause or row type differs from its row",
            "no-reason": "malformed regrade", "bad-purpose": "malformed regrade"})

    def test_a_row_that_does_not_verify_shows_none_of_its_regrades(self):
        def check(cid):
            if cid == ROW_ID:
                raise CapsuleDoesNotVerify("row does not verify")
        shown = rows_with_regrades(self.entries, check)
        self.assertEqual(shown["rows"], [])
        self.assertEqual([n["capsule_id"] for n in shown["not_shown"]], ["r1", "r2"])


class Told(unittest.TestCase):
    class Tty(io.StringIO):
        def isatty(self):
            return True

    def test_a_terminal_answers(self):
        for answer, want in (("y\n", True), ("yes\n", True), ("\n", False), ("n\n", False)):
            err = io.StringIO()
            self.assertEqual(regrade.told("r", self.Tty(answer), err), want)
            self.assertIn(regrade.REASON_NOTICE, err.getvalue())

    def test_no_terminal_is_no(self):
        self.assertFalse(regrade.told("r", io.StringIO("y\n"), io.StringIO()))


class MalformedRowsAndVerifierFailures(unittest.TestCase):
    def setUp(self):
        self.row = judged_row("met")
        self.rg = regrade_record(ROW_ID, self.row, "not_met", "r", "rater:1", AT)

    def test_a_malformed_row_is_no_row_and_other_pairs_still_show(self):
        other_row = {**judged_row("met"), "case_id": "case-2"}
        other_rg = regrade_record("99" * 32, other_row, "met", "r", "rater:1", AT)
        for broken in ({k: v for k, v in self.row.items() if k != "case_id"},
                       {k: v for k, v in self.row.items() if k != "verdict"},
                       {**self.row, "verdict": "pass"},
                       {**self.row, "judge_pin_digest": "not-a-digest"}):
            self.assertFalse(is_judged_row(broken))
            shown = rows_with_regrades([(ROW_ID, broken), ("r1", self.rg), ("99" * 32, other_row), ("r2", other_rg)],
                                       lambda _cid: None)
            self.assertEqual([r["case_id"] for r in shown["rows"]], ["case-2"])
            self.assertEqual(shown["not_shown"], [{"capsule_id": "r1", "why": "cites no judged row in this book"}])

    def test_an_untrusted_signer_is_not_shown(self):
        def check(cid):
            if cid == "r1":
                raise UntrustedSigner("signer not in the trusted keys")
        shown = rows_with_regrades([(ROW_ID, self.row), ("r1", self.rg)], check)
        self.assertEqual(shown["rows"], [])
        self.assertTrue(shown["not_shown"][0]["why"].startswith("does not verify"))

    def test_a_verifier_with_no_verdict_stops_the_read(self):
        def check(_cid):
            raise EvidenceUnavailable("capsulectl verify gave no verdict")
        with self.assertRaises(EvidenceUnavailable):
            rows_with_regrades([(ROW_ID, self.row), ("r1", self.rg)], check)


class CountsIgnoreRegrades(unittest.TestCase):
    def test_result_v0_grouping_and_the_weekly_frame_are_unchanged(self):
        row = judged_row("met")
        rg = regrade_record(ROW_ID, row, "not_met", "r", "rater:1", AT)
        alone, beside = [(ROW_ID, row)], [(ROW_ID, row), ("r1", rg)]
        self.assertEqual(group_reports(beside, CONTRACT), group_reports(alone, CONTRACT))
        bodies = dict(beside)
        frame = week_frame([{"capsule_id": c} for c in bodies], bodies.get, lambda _id: None, {"2026-11-26"})
        self.assertEqual(frame, ([(ROW_ID, row)], 0))


STUB = r'''#!/usr/bin/env python3
import hashlib, json, os, sys
BOOK = os.environ["STUB_BOOK"]
book = json.load(open(BOOK))
argv = sys.argv[1:]
opts = dict(zip(argv[1::2], argv[2::2]))
if argv[:2] == ["profile", "show"]:
    print(json.dumps({"Operator": "op:test"})); sys.exit(0)
if argv[:2] == ["cll", "list"]:
    after = int(argv[argv.index("--after") + 1])
    page = book[after:]
    print(json.dumps({"entries": [{"capsule_id": e["capsule_id"]} for e in page], "next_after": after + len(page)}))
    sys.exit(0)
if argv[0] == "get":
    cid = argv[argv.index("--capsule-id") + 1]
    e = next((e for e in book if e["capsule_id"] == cid), None)
    if e is None:
        sys.exit("no capsule")
    if "--raw" in argv:
        open(argv[argv.index("--output") + 1], "w").write(json.dumps(e))
    else:
        print(json.dumps({"artifacts": [{"name": "payload", "content": e["payload"]}]}))
    sys.exit(0)
if argv[0] == "verify":
    e = json.load(open(argv[argv.index("--capsule") + 1]))
    if e.get("forged"):
        sys.stderr.write("capsule verification failed: signature"); sys.exit(1)
    sys.exit(0)
if argv[0] == "publish":
    req = json.load(open(argv[argv.index("--request") + 1]))
    cid = hashlib.sha256(json.dumps(req, sort_keys=True).encode()).hexdigest()
    if not any(e["capsule_id"] == cid for e in book):
        book.append({"capsule_id": cid, "payload": req["payload"], "request": req})
        json.dump(book, open(BOOK, "w"))
    print(json.dumps({"capsule_id": cid})); sys.exit(0)
sys.exit("stub capsulectl: unexpected call " + " ".join(argv))
'''


class Cli(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.ctl = self.dir / "capsulectl"
        self.ctl.write_text(STUB)
        self.ctl.chmod(self.ctl.stat().st_mode | stat.S_IEXEC)
        self.book = self.dir / "book.json"
        self.book.write_text(json.dumps([{"capsule_id": ROW_ID, "payload": judged_row("met")}]))
        os.environ["STUB_BOOK"] = str(self.book)

    def tearDown(self):
        os.environ.pop("STUB_BOOK", None)

    def main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = regrade.main([*argv, "--profile", "p", "--capsulectl", str(self.ctl)])
        return code, out.getvalue(), err.getvalue()

    def seal(self, *extra):
        return self.main("seal", "--row", ROW_ID, "--grade", "not_met", "--reason", "allowed by fare class",
                         "--rater-ref", "rater:1", "--at", AT, "--reason-sealed-ok", *extra)

    def test_the_rater_is_told_before_anything_is_sealed(self):
        code, _out, err = self.main("seal", "--row", ROW_ID, "--grade", "not_met", "--reason", "allowed by fare class",
                                    "--rater-ref", "rater:1", "--at", AT)
        self.assertEqual(code, 2)
        self.assertIn(regrade.REASON_NOTICE, err)
        self.assertIn("--reason-sealed-ok", err)
        self.assertEqual(len(json.loads(self.book.read_text())), 1)

    def test_seal_then_rows_shows_both_grades(self):
        code, out, err = self.seal()
        self.assertEqual(code, 0, err)
        sealed = json.loads(out)["capsule_id"]
        book = json.loads(self.book.read_text())
        self.assertEqual(book[1]["request"]["capsule"]["Timestamp"], AT)
        self.assertEqual(book[1]["payload"]["row"]["digest"], ROW_ID)
        code, out, err = self.main("rows")
        self.assertEqual(code, 0, err)
        [row] = json.loads(out)["rows"]
        self.assertEqual(row["judge"]["verdict"], "met")
        self.assertEqual([(r["capsule_id"], r["grade"]) for r in row["regrades"]], [(sealed, "not_met")])

    def test_a_rerun_with_the_same_at_seals_nothing_new(self):
        first, second = self.seal(), self.seal()
        self.assertEqual(first, second)
        self.assertEqual(len(json.loads(self.book.read_text())), 2)

    def test_a_row_that_does_not_verify_is_never_regraded(self):
        book = json.loads(self.book.read_text())
        book[0]["forged"] = True
        self.book.write_text(json.dumps(book))
        code, _out, err = self.seal()
        self.assertEqual(code, 1)
        self.assertIn("evidence unavailable", err)
        self.assertEqual(len(json.loads(self.book.read_text())), 1)

    def test_a_refusal_seals_nothing(self):
        code, _out, err = self.main("seal", "--row", ROW_ID, "--grade", "out_of_scope", "--reason", "r",
                                    "--rater-ref", "rater:1", "--at", AT, "--reason-sealed-ok")
        self.assertEqual(code, 2)
        self.assertIn("regrade refused", err)
        self.assertEqual(len(json.loads(self.book.read_text())), 1)


if __name__ == "__main__":
    unittest.main()
