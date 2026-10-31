"""scripts/subject_history.py: the frame-5 fields (evidencebook-skills#89) on a day Result.

Synthetic customers only (Sherlock2, Buzz 3958de61): the fixture's four conversations are
built here, never read from a recorded tau2 run.
"""
import copy
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import jsonschema  # noqa: E402

from result_v0 import build_result_v0_for_day, merge_result_v0_documents  # noqa: E402
from rollup import RollupError, all_criteria_from_clauses  # noqa: E402
import subject_history as sh  # noqa: E402

SCHEMA = pathlib.Path(__file__).resolve().parent / "fixtures" / "evidence-result-v0.json"
PACK = "airline-support-outcomes"
SALT = b"s" * 32
CUSTOMER = "synthetic_customer_0001"


def call(i, name, **arguments):
    return {"role": "assistant", "tool_calls": [{"id": f"c{i}", "name": name, "arguments": arguments}]}


def result(i, payload):
    return {"role": "tool", "tool_call_id": f"c{i}", "content": payload if isinstance(payload, str) else json.dumps(payload)}


def convo(user_id, tool, amount, **arguments):
    msgs = []
    if user_id:
        msgs += [call(1, "get_user_details", user_id=user_id), result(1, {"user_id": user_id})]
    if tool == "send_certificate":
        msgs += [call(2, tool, user_id=user_id, amount=amount, **arguments), result(2, "Certificate added")]
    elif tool:
        msgs += [call(2, tool, **arguments), result(2, {"payment_history": [{"payment_id": "p", "amount": amount}]})]
    return msgs


CONVERSATIONS = {
    "t-1": convo(CUSTOMER, "cancel_reservation", 430, reservation_id="R1"),
    "t-2": convo(CUSTOMER, "send_certificate", 50),
    "t-3": convo(CUSTOMER, "update_reservation_flights", 296, reservation_id="R2"),
    "t-4": convo(CUSTOMER, None, None),
}
FACTS = {f"t-{i}": {"halves": {"present": 4, "of": 4}} for i in range(1, 5)}
FACTS["t-3"]["follow_up_of"] = "t-1"


class Fields(unittest.TestCase):
    def test_label_comes_from_the_closed_list(self):
        self.assertEqual(sh.request_label(convo("u", "update_reservation_cabin", 80)), "cabin change")
        for case, label in (("t-1", "cancellation"), ("t-2", "compensation"), ("t-3", "flight change"),
                            ("t-4", "information request")):
            self.assertEqual(sh.request_label(CONVERSATIONS[case]), label)
            self.assertIn(label, sh.LABEL_VALUES)

    def test_band_is_the_order_of_magnitude_of_the_largest_amount(self):
        self.assertEqual([sh.usd_band(CONVERSATIONS[c]) for c in ("t-1", "t-2", "t-3", "t-4")],
                         ["e+2", "e+1", "e+2", None])
        self.assertEqual(sh.usd_band(convo("u", "cancel_reservation", -1000)), "e+3")
        self.assertIsNone(sh.usd_band(convo("u", "cancel_reservation", 0.5)))
        self.assertEqual(sh.usd_band(convo("u", "update_reservation_cabin", 80)), "e+1")
        failed = convo("u", "send_certificate", 5000)
        failed[-1] = result(2, "Error: user not found")
        self.assertIsNone(sh.usd_band(failed))

    def test_customer_id_needs_exactly_one_lookup(self):
        self.assertEqual(sh.customer_id(CONVERSATIONS["t-1"]), CUSTOMER)
        self.assertIsNone(sh.customer_id(convo(None, "cancel_reservation", 5)))
        two = CONVERSATIONS["t-1"] + [call(9, "get_user_details", user_id="other")]
        self.assertIsNone(sh.customer_id(two))

    def test_handle_is_stable_in_scope_and_differs_by_scope_salt_and_customer(self):
        scope = {"pack": PACK, "tier": "operator", "salting": "per-pack"}
        self.assertNotEqual(sh.salt_id(SALT), sh.salt_id(b"t" * 32))
        h = sh.customer_handle(SALT, scope, CUSTOMER)
        self.assertEqual(h, sh.customer_handle(SALT, scope, CUSTOMER))
        self.assertNotEqual(h, sh.customer_handle(SALT, scope, "other"))
        self.assertNotEqual(h, sh.customer_handle(b"t" * 32, scope, CUSTOMER))
        self.assertNotEqual(h, sh.customer_handle(SALT, dict(scope, pack="x"), CUSTOMER))
        self.assertNotIn(CUSTOMER, h)
        with self.assertRaises(RollupError):
            sh.customer_handle(b"short", scope, CUSTOMER)


class Member(unittest.TestCase):
    def build(self, tier="operator", **kw):
        return sh.build_subject_history(PACK, tier, CONVERSATIONS, FACTS, SALT, **kw)["subject_history"]

    def test_operator_carries_all_five_for_one_customer_across_four_conversations(self):
        sub = self.build()
        self.assertEqual(sub["handle_scope"], {"pack": PACK, "tier": "operator", "salting": "per-pack",
                                               "salt_id": sh.salt_id(SALT)})
        self.assertNotIn(SALT.decode(), json.dumps(sub))
        convs = sub["conversations"]
        self.assertEqual(len(convs), 4)
        self.assertEqual(len({c["customer_handle"] for c in convs.values()}), 1)
        self.assertEqual(convs["t-3"]["follow_up_of"], "t-1")
        self.assertEqual(convs["t-1"]["halves"], {"present": 4, "of": 4})
        self.assertEqual(convs["t-2"]["usd_band"], "e+1")
        self.assertEqual(convs["t-4"]["request_label"], "information request")
        self.assertNotIn("usd_band", convs["t-4"])
        self.assertNotIn(CUSTOMER, json.dumps(sub))

    def test_shared_tier_has_no_handle_scope_handle_or_follow_up(self):
        sub = self.build("shared")
        self.assertNotIn("handle_scope", sub)
        for entry in sub["conversations"].values():
            self.assertEqual(set(entry) - {"request_label", "usd_band", "halves"}, set())

    def test_refusals(self):
        with self.assertRaises(RollupError):
            sh.build_subject_history(PACK, "operator", CONVERSATIONS, FACTS, None)
        with self.assertRaises(RollupError):
            sh.build_subject_history(PACK, "buyer", CONVERSATIONS, FACTS, SALT)
        bad = copy.deepcopy(FACTS)
        bad["t-3"]["follow_up_of"] = "t-9"
        with self.assertRaises(RollupError):
            sh.build_subject_history(PACK, "operator", CONVERSATIONS, bad, SALT)
        bad["t-3"]["follow_up_of"] = "t-3"
        with self.assertRaises(RollupError):
            sh.build_subject_history(PACK, "operator", CONVERSATIONS, bad, SALT)
        for halves in ({"present": 5, "of": 4}, {"present": 0, "of": 0}, {"present": 1}, {"present": True, "of": 4}):
            with self.assertRaises(RollupError):
                sh.build_subject_history(PACK, "shared", CONVERSATIONS, {"t-1": {"halves": halves}})
        with self.assertRaises(RollupError):
            sh.build_subject_history(PACK, "shared", CONVERSATIONS, {"nope": {}})
        for facts in ({"t-3": {"follow_up_of": ["t-1"]}}, ["t-1"], {"t-1": "x"}):
            with self.assertRaises(RollupError):
                sh.build_subject_history(PACK, "operator", CONVERSATIONS, facts, SALT)
        with self.assertRaises(RollupError):
            sh.build_subject_history(PACK, "operator", {"t-1": [call(1, "get_user_details", user_id=7)]}, None, b"x")
        odd = {"t-1": [call(1, "get_user_details", user_id=7)]}
        self.assertNotIn("customer_handle", sh.build_subject_history(PACK, "operator", odd, None, SALT)
                         ["subject_history"]["conversations"]["t-1"])

    def test_ambiguous_customer_gets_no_handle(self):
        two = {"t-1": CONVERSATIONS["t-1"] + [call(9, "get_user_details", user_id="other")]}
        entry = sh.build_subject_history(PACK, "operator", two, None, SALT)["subject_history"]["conversations"]["t-1"]
        self.assertNotIn("customer_handle", entry)


class OnTheResult(unittest.TestCase):
    CLAUSES = [{"id": "a.one", "check_id": "a"}]

    def day(self, cases, member):
        crit = all_criteria_from_clauses(self.CLAUSES)
        rollups = [(c, {k: "met" for k in crit}, {k: "ab" * 32 for k in crit}, {k: "judged" for k in crit}) for c in cases]
        doc = build_result_v0_for_day("d", rollups, "2026-10-31T00:00:00Z", crit, "c@1")
        doc[sh.extension_name(PACK)] = member
        return doc

    def test_day_and_merged_documents_validate_and_follow_up_may_span_days(self):
        validator = jsonschema.Draft202012Validator(json.loads(SCHEMA.read_bytes()))
        known = set(CONVERSATIONS)
        d1 = self.day(["t-1", "t-2"], sh.build_subject_history(
            PACK, "operator", {c: CONVERSATIONS[c] for c in ("t-1", "t-2")}, FACTS, SALT, known_cases=known))
        d2 = self.day(["t-3", "t-4"], sh.build_subject_history(
            PACK, "operator", {c: CONVERSATIONS[c] for c in ("t-3", "t-4")}, FACTS, SALT, known_cases=known))
        for d in (d1, d2):
            self.assertEqual([e.message for e in validator.iter_errors(d)], [])
        merged = merge_result_v0_documents([d1, d2], "t", "2026-10-31T00:00:00Z")
        self.assertEqual([e.message for e in validator.iter_errors(merged)], [])
        convs = merged[sh.extension_name(PACK)]["subject_history"]["conversations"]
        self.assertEqual(sorted(convs), ["t-1", "t-2", "t-3", "t-4"])
        self.assertEqual(convs["t-3"]["follow_up_of"], "t-1")

    def test_merge_needs_the_member_on_every_day_and_ignores_other_x_members(self):
        d1 = self.day(["t-1"], sh.build_subject_history(PACK, "shared", {"t-1": CONVERSATIONS["t-1"]}))
        d2 = self.day(["t-2"], sh.build_subject_history(PACK, "shared", {"t-2": CONVERSATIONS["t-2"]}))
        del d2[sh.extension_name(PACK)]
        d2["x-other"] = {"anything": 1}
        with self.assertRaises(RollupError):
            merge_result_v0_documents([d1, d2], "t", "2026-10-31T00:00:00Z")
        d2[sh.extension_name(PACK)] = sh.build_subject_history(PACK, "shared", {"t-2": CONVERSATIONS["t-2"]})
        merged = merge_result_v0_documents([d1, d2], "t", "2026-10-31T00:00:00Z")
        self.assertNotIn("x-other", merged)

    def test_merge_refuses_days_sealed_under_different_salts(self):
        a = sh.build_subject_history(PACK, "operator", {"t-1": CONVERSATIONS["t-1"]}, None, SALT)
        b = sh.build_subject_history(PACK, "operator", {"t-2": CONVERSATIONS["t-2"]}, None, b"t" * 32)
        with self.assertRaises(RollupError):
            sh.merge_subject_history([a, b])

    def test_merge_refuses_mixed_scopes_and_dangling_follow_ups(self):
        a = sh.build_subject_history(PACK, "operator", {"t-1": CONVERSATIONS["t-1"]}, None, SALT)
        b = sh.build_subject_history(PACK, "shared", {"t-2": CONVERSATIONS["t-2"]})
        with self.assertRaises(RollupError):
            sh.merge_subject_history([a, b])
        dangling = sh.build_subject_history(PACK, "operator", {"t-3": CONVERSATIONS["t-3"]}, {"t-3": {"follow_up_of": "t-1"}},
                                            SALT, known_cases={"t-1", "t-3"})
        with self.assertRaises(RollupError):
            sh.merge_subject_history([dangling])


FIXTURE_DIR = pathlib.Path(__file__).resolve().parent / "fixtures" / "subject-history"


def fixture_document(tier):
    """The committed frame-5 fixtures: one synthetic customer across four conversations.
    Regenerate with: python3 tests/test_subject_history.py --write-fixtures"""
    crit = all_criteria_from_clauses(OnTheResult.CLAUSES)
    rollups = [(c, {k: "met" for k in crit}, {k: f"{i:02x}" * 32 for k in crit}, {k: "judged" for k in crit})
               for i, c in enumerate(sorted(CONVERSATIONS), 1)]
    doc = build_result_v0_for_day("2026-10-31", rollups, "2026-10-31T00:00:00Z", crit, f"{PACK}@1.5.0")
    doc[sh.extension_name(PACK)] = sh.build_subject_history(PACK, tier, CONVERSATIONS, FACTS, SALT)
    return doc


class Fixtures(unittest.TestCase):
    def test_committed_fixtures_are_current_and_validate(self):
        validator = jsonschema.Draft202012Validator(json.loads(SCHEMA.read_bytes()))
        for tier in sh.TIERS:
            raw = (FIXTURE_DIR / f"result-v0-{tier}.json").read_text()
            self.assertEqual(json.loads(raw), fixture_document(tier))
            self.assertEqual([e.message for e in validator.iter_errors(json.loads(raw))], [])
            self.assertNotIn(CUSTOMER, raw)
            self.assertNotIn(SALT.decode(), raw)


if __name__ == "__main__":
    if sys.argv[1:] == ["--write-fixtures"]:
        FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
        for t in sh.TIERS:
            (FIXTURE_DIR / f"result-v0-{t}.json").write_text(json.dumps(fixture_document(t), indent=2) + "\n")
        sys.exit(0)
    unittest.main()
