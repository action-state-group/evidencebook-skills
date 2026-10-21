"""Unit tests for scripts/judge_bundle.py: the pack compiles, a whole disclosed
bundle (every disclosed record plus the bundle's extensions, the default when
no --capsule-id narrows it) judges met/not_met/out_of_scope through the mock
backend and cites every record it actually used, --capsule-id narrows to one
record, a WITHHELD bundle and a missing/undisclosed record fail closed to
not_evaluable without ever calling the judge, and the judge pin is present,
stable, and only ever sealed on a claim the judge actually ran on.

    python3 -m unittest discover -s tests -p 'test_*.py'
"""
import copy
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "judges"))

import jevals  # noqa: E402
import jev_judge  # noqa: E402
import pack_compile  # noqa: E402
import judge_bundle  # noqa: E402
import instrument_pin  # noqa: E402

PACK_SOURCE = ROOT / "packs" / "everyday-rules" / "pack-source.yaml"
JUDGE_BUNDLE_PATH = str(ROOT / "scripts" / "judge_bundle.py")
GENERATED_AT = "2026-10-08T00:00:00Z"
CAPSULE_ID = "a" * 64
OTHER_CAPSULE_ID = "b" * 64

# A real `capsulectl deal report --bundle` output (capsule-cli main,
# `internal/cli/deal_report.go`), run end to end against the public
# `skills/deal/demo/jet-ski` fixture: deal init/open, four notes, a check, an
# unapproved act, then `deal report`. 10 records, all 10 disclosed, plus an
# `extensions["x-deal-v0"]` block. Used here only to exercise this script's
# plumbing against a real multi-record bundle shape -- the mock backend never
# reads the rental/payment content for its verdict.
REAL_BUNDLE_PATH = ROOT / "tests" / "fixtures" / "deal-bundle-jet-ski.json"


def compiled_pack():
    source = pack_compile._strip_strings(yaml.safe_load(PACK_SOURCE.read_text()))
    compiled, _axes, _prompt, _presentation = pack_compile.compile_pack(source, "packs/everyday-rules/compiled")
    return compiled


def real_deal_bundle():
    return json.loads(REAL_BUNDLE_PATH.read_text())


def withheld_variant(bundle):
    """The same records, with every disclosure withdrawn -- capsule-anchor's
    countersign `parse_bundle` WITHHELD shape: payloads_mode: "none" and no
    "disclosures" key at all."""
    bundle = copy.deepcopy(bundle)
    bundle["completeness"]["payloads_mode"] = "none"
    bundle.pop("disclosures", None)
    return bundle


def _record(capsule_id):
    return {"capsule_id": capsule_id, "operator": "household-fixture", "developer": "example-agent-host",
            "timestamp": "2026-10-01T12:00:00Z"}


def _records(capsule_id, root):
    """The bundle's records: a real bundle's root is one of them (its root
    record), so a fixture root other than the judged record is held too."""
    return [_record(capsule_id)] + ([_record(root)] if root != capsule_id else [])


def disclosed_bundle(facts, capsule_id=CAPSULE_ID, root="test-bundle-disclosed"):
    return {
        "bundle_version": "2", "bundle_kind": "evidence-bundle/v2", "root": root,
        "records": _records(capsule_id, root),
        "completeness": {"closure_depth": 1, "records_mode": "complete", "payloads_mode": "all",
                         "suppressed_fields": [], "missing": []},
        "disclosures": {capsule_id: facts},
    }


def withheld_bundle(capsule_id=CAPSULE_ID, root="test-bundle-withheld"):
    return {
        "bundle_version": "2", "bundle_kind": "evidence-bundle/v2", "root": root,
        "records": _records(capsule_id, root),
        "completeness": {"closure_depth": 1, "records_mode": "complete", "payloads_mode": "none",
                         "suppressed_fields": ["agent_input", "agent_output"], "missing": []},
        # deliberately no "disclosures" key at all
    }


FACTS = {"agent_input": {"action": "pay", "action_class": "money.transfer", "amount_minor": 4500,
                         "currency": "USD", "rail": "card", "counterparty": "Example Merchant LLC",
                         "recurrence": "none"}}


def judged_claims(document):
    """The claims a run actually judged: a --rule-ids run also claims every
    unselected judged rule as not_evaluable (REASON_NOT_SELECTED), and those
    carry no judge pin and cite no record."""
    return [c for c in document["claims"] if "judge_pin_digest" in c]


def fixed_backend(verdict):
    return jevals.MockBackend(fn=lambda qid, q, state: verdict)


def rule9_clauses():
    return judge_bundle.select_clauses(compiled_pack(), ["9"])


def pin_for(model_id, input_refs):
    """judge_bundle.build_judge_pin() over rule 9's compiled clause: the pin's
    prompt_template_hash depends on which questions were sent, so every pin
    built here names the clauses it covers."""
    return judge_bundle.build_judge_pin(model_id, input_refs, rule9_clauses())


class PackSource(unittest.TestCase):
    def test_pack_source_is_valid(self):
        source = pack_compile._strip_strings(yaml.safe_load(PACK_SOURCE.read_text()))
        self.assertEqual(pack_compile.validate_source(source), [])

    def test_compiles_to_thirteen_judged_clauses(self):
        pack = compiled_pack()
        self.assertEqual(len(pack["clauses"]), 13)
        self.assertTrue(all(c["tier"] == "judged" for c in pack["clauses"]))
        self.assertTrue(all(c.get("measurability") == "measured" for c in pack["clauses"]))

    def test_rule_half_rows_are_exactly_2_11_12_27(self):
        pack = compiled_pack()
        halves = {c["rule_id"] for c in pack["clauses"] if c.get("rule_half")}
        self.assertEqual(halves, {"2", "11", "12", "27"})


class SelectClauses(unittest.TestCase):
    def test_default_is_every_judged_clause(self):
        pack = compiled_pack()
        self.assertEqual(len(judge_bundle.select_clauses(pack, None)), 13)

    def test_rule_ids_subset(self):
        pack = compiled_pack()
        clauses = judge_bundle.select_clauses(pack, ["8", "26"])
        self.assertEqual({c["rule_id"] for c in clauses}, {"8", "26"})

    def test_unknown_rule_id_is_bad_input(self):
        pack = compiled_pack()
        with self.assertRaisesRegex(judge_bundle.BadInput, "no judged clause"):
            judge_bundle.select_clauses(pack, ["not-a-rule"])

    def test_repeated_rule_id_is_bad_input(self):
        # Never silently judge (and claim) the same row twice.
        pack = compiled_pack()
        with self.assertRaisesRegex(judge_bundle.BadInput, "repeats rule"):
            judge_bundle.select_clauses(pack, ["8", "8"])

    def test_empty_rule_ids_list_is_bad_input_not_zero_clauses(self):
        # A malformed "--rule-ids ," on the CLI parses to [] (not None) --
        # must be refused here, not silently judge zero rows.
        pack = compiled_pack()
        with self.assertRaisesRegex(judge_bundle.BadInput, "no rule id"):
            judge_bundle.select_clauses(pack, [])


class LoadBundle(unittest.TestCase):
    def test_wrong_bundle_kind_is_bad_input(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"bundle_kind": "something-else/v1"}, f)
            path = f.name
        try:
            with self.assertRaisesRegex(judge_bundle.BadInput, "evidence-bundle/v2"):
                judge_bundle.load_bundle(path)
        finally:
            pathlib.Path(path).unlink()

    def test_unparseable_json_is_bad_input(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("not json")
            path = f.name
        try:
            with self.assertRaisesRegex(judge_bundle.BadInput, "not valid JSON"):
                judge_bundle.load_bundle(path)
        finally:
            pathlib.Path(path).unlink()


class Withheld(unittest.TestCase):
    def test_is_withheld_true_for_payloads_none_and_no_disclosures_key(self):
        self.assertTrue(judge_bundle.is_withheld(withheld_bundle()))

    def test_is_withheld_false_when_disclosures_key_present_even_if_empty(self):
        bundle = withheld_bundle()
        bundle["disclosures"] = {}
        self.assertFalse(judge_bundle.is_withheld(bundle))

    def test_is_withheld_false_for_payloads_selected(self):
        bundle = disclosed_bundle(FACTS)
        bundle["completeness"]["payloads_mode"] = "selected"
        self.assertFalse(judge_bundle.is_withheld(bundle))

    def test_withheld_bundle_every_row_not_evaluable_payload_withheld_no_judge_call(self):
        pack = compiled_pack()
        clauses = judge_bundle.select_clauses(pack, None)
        backend = jevals.MockBackend(fn=lambda qid, q, state: (_ for _ in ()).throw(
            AssertionError("the judge must never be called on a withheld bundle")))
        answers, target_ids, actually_judged = judge_bundle.judge_bundle(
            withheld_bundle(), clauses, None, "jev-1.13.0", backend=backend)
        self.assertFalse(actually_judged)
        self.assertEqual(target_ids, [])
        self.assertTrue(all(a["verdict"] == "not_evaluable" for a in answers.values()))
        self.assertTrue(all(a["rationale"] == judge_bundle.REASON_PAYLOAD_WITHHELD for a in answers.values()))

    def test_withheld_bundle_end_to_end_no_claim_carries_a_judge_pin(self):
        pack = compiled_pack()
        document = judge_bundle.run(pack, withheld_bundle(), None, None, "jev-1.13.0", GENERATED_AT)
        self.assertEqual(len(document["claims"]), 13)
        self.assertTrue(all(c["verdict"] == "not_evaluable" for c in document["claims"]))
        self.assertTrue(all("judge_pin_digest" not in c for c in document["claims"]))
        self.assertTrue(all(c["rationale"] == judge_bundle.REASON_PAYLOAD_WITHHELD for c in document["claims"]))
        # A fail-closed abstention cites only the bundle it was asked about,
        # never a record it read (it read none): a claim cites at least one
        # record (agent-action-capsule#353).
        root = [{"digest_alg": "SHA-256", "digest": withheld_bundle()["root"]}]
        self.assertTrue(all(c["evidence"] == root for c in document["claims"]))

    def test_withheld_bundle_with_more_than_one_record_is_also_all_not_evaluable(self):
        # The global WITHHELD check applies whatever --capsule-id says, and
        # whatever the bundle's record count -- no longer "ambiguous" input,
        # since whole-bundle judging never needed a single named target.
        bundle = withheld_bundle()
        bundle["records"].append(_record(OTHER_CAPSULE_ID))
        pack = compiled_pack()
        document = judge_bundle.run(pack, bundle, None, None, "jev-1.13.0", GENERATED_AT)
        self.assertTrue(all(c["verdict"] == "not_evaluable" for c in document["claims"]))
        self.assertTrue(all(c["rationale"] == judge_bundle.REASON_PAYLOAD_WITHHELD for c in document["claims"]))

    def test_real_multi_record_bundle_withheld_is_all_not_evaluable(self):
        # Same withholding rule, over the real 10-record capsulectl deal
        # bundle (tests/fixtures/deal-bundle-jet-ski.json): withholding the
        # whole deal's disclosures must not depend on how many records it
        # carries.
        bundle = withheld_variant(real_deal_bundle())
        pack = compiled_pack()
        document = judge_bundle.run(pack, bundle, None, None, "jev-1.13.0", GENERATED_AT)
        self.assertEqual(len(document["claims"]), 13)
        self.assertTrue(all(c["verdict"] == "not_evaluable" for c in document["claims"]))
        self.assertTrue(all(c["rationale"] == judge_bundle.REASON_PAYLOAD_WITHHELD for c in document["claims"]))
        root = [{"digest_alg": "SHA-256", "digest": bundle["root"]}]
        self.assertTrue(all(c["evidence"] == root for c in document["claims"]))


class AbstentionCitesTheBundle(unittest.TestCase):
    def test_a_bundle_with_no_root_is_refused_rather_than_claimed_with_no_record(self):
        bundle = withheld_bundle()
        del bundle["root"]
        with self.assertRaisesRegex(judge_bundle.BadInput, "no record to cite"):
            judge_bundle.run(compiled_pack(), bundle, None, None, "jev-1.13.0", GENERATED_AT)

    def test_a_root_the_bundle_does_not_hold_is_never_cited(self):
        bundle = withheld_bundle()
        bundle["records"] = [_record(CAPSULE_ID)]
        with self.assertRaisesRegex(judge_bundle.BadInput, "no record to cite"):
            judge_bundle.run(compiled_pack(), bundle, None, None, "jev-1.13.0", GENERATED_AT)

    def test_a_partial_run_with_nothing_to_cite_is_refused_before_the_judge_is_called(self):
        bundle = disclosed_bundle(FACTS, root="not-held")
        bundle["records"] = [_record(CAPSULE_ID)]
        backend = jevals.MockBackend(fn=lambda qid, q, state: (_ for _ in ()).throw(
            AssertionError("the judge must not be called when the run cannot be claimed")))
        with self.assertRaisesRegex(judge_bundle.BadInput, "no record to cite"):
            judge_bundle.run(compiled_pack(), bundle, ["9"], None, "jev-1.13.0", GENERATED_AT, backend=backend)

    def test_a_narrowed_abstention_cites_the_record_it_was_asked_about(self):
        bundle = disclosed_bundle(FACTS)
        bundle["completeness"]["payloads_mode"] = "selected"
        bundle["disclosures"] = {}
        document = judge_bundle.run(compiled_pack(), bundle, None, CAPSULE_ID, "jev-1.13.0", GENERATED_AT)
        cited = [{"digest_alg": "SHA-256", "digest": CAPSULE_ID}]
        self.assertTrue(all(c["rationale"] == judge_bundle.REASON_PAYLOAD_WITHHELD for c in document["claims"]))
        self.assertTrue(all(c["evidence"] == cited for c in document["claims"]))

    def test_a_full_run_with_no_root_still_judges_every_rule(self):
        bundle = disclosed_bundle(FACTS, root=CAPSULE_ID)
        del bundle["root"]
        document = judge_bundle.run(compiled_pack(), bundle, None, None, "jev-1.13.0", GENERATED_AT,
                                    backend=fixed_backend("met"))
        self.assertTrue(all(c["verdict"] == "met" for c in document["claims"]))


class MissingRecord(unittest.TestCase):
    def test_record_declared_missing(self):
        bundle = {
            "bundle_version": "2", "bundle_kind": "evidence-bundle/v2", "root": "missing-declared",
            "records": [_record("missing-declared")], "completeness": {"records_mode": "declared_incomplete", "payloads_mode": "all",
                                            "missing": [OTHER_CAPSULE_ID]},
            "disclosures": {},
        }
        record, reason = judge_bundle.resolve_target(bundle, OTHER_CAPSULE_ID)
        self.assertIsNone(record)
        self.assertEqual(reason, judge_bundle.REASON_RECORD_DECLARED_MISSING)

    def test_record_not_found_and_not_declared(self):
        bundle = {
            "bundle_version": "2", "bundle_kind": "evidence-bundle/v2", "root": "ghost",
            "records": [], "completeness": {"records_mode": "complete", "payloads_mode": "all", "missing": []},
            "disclosures": {},
        }
        record, reason = judge_bundle.resolve_target(bundle, "ghost-id")
        self.assertIsNone(record)
        self.assertEqual(reason, judge_bundle.REASON_RECORD_NOT_FOUND)

    def test_missing_record_end_to_end_is_not_evaluable_never_a_hard_refusal(self):
        pack = compiled_pack()
        bundle = {
            "bundle_version": "2", "bundle_kind": "evidence-bundle/v2", "root": "missing-declared",
            "records": [_record("missing-declared")], "completeness": {"records_mode": "declared_incomplete", "payloads_mode": "all",
                                            "missing": [OTHER_CAPSULE_ID]},
            "disclosures": {},
        }
        document = judge_bundle.run(pack, bundle, None, OTHER_CAPSULE_ID, "jev-1.13.0", GENERATED_AT)
        self.assertTrue(all(c["verdict"] == "not_evaluable" for c in document["claims"]))
        self.assertTrue(all(c["rationale"] == judge_bundle.REASON_RECORD_DECLARED_MISSING for c in document["claims"]))
        # The asked-for record is not held, so the claims cite the root record.
        root = [{"digest_alg": "SHA-256", "digest": "missing-declared"}]
        self.assertTrue(all(c["evidence"] == root for c in document["claims"]))

    def test_record_present_but_not_individually_disclosed_is_payload_withheld(self):
        # --capsule-id narrows to THIS record, which has no entry under
        # disclosures -- distinct from the bundle being globally WITHHELD.
        bundle = disclosed_bundle(FACTS)
        bundle["completeness"]["payloads_mode"] = "selected"
        bundle["disclosures"] = {}
        pack = compiled_pack()
        clauses = judge_bundle.select_clauses(pack, None)
        answers, target_ids, actually_judged = judge_bundle.judge_bundle(bundle, clauses, CAPSULE_ID, "jev-1.13.0")
        self.assertFalse(actually_judged)
        self.assertEqual(target_ids, [])
        self.assertTrue(all(a["rationale"] == judge_bundle.REASON_PAYLOAD_WITHHELD for a in answers.values()))

    def test_record_disclosed_but_empty_is_also_payload_withheld(self):
        # Explicitly disclosed ({}) but nothing is actually in it -- same
        # treatment as an absent disclosure: never a live judge call over
        # nothing, and never silently coerced into "disclosed facts" an answer
        # could be read from.
        bundle = disclosed_bundle({})
        pack = compiled_pack()
        clauses = judge_bundle.select_clauses(pack, None)
        backend = jevals.MockBackend(fn=lambda qid, q, state: (_ for _ in ()).throw(
            AssertionError("the judge must never be called over empty disclosed facts")))
        answers, target_ids, actually_judged = judge_bundle.judge_bundle(
            bundle, clauses, None, "jev-1.13.0", backend=backend)
        self.assertFalse(actually_judged)
        self.assertEqual(target_ids, [])
        self.assertTrue(all(a["rationale"] == judge_bundle.REASON_NOTHING_DISCLOSED for a in answers.values()))

    def test_a_bundle_disclosing_nothing_is_nothing_disclosed_not_a_hard_refusal(self):
        # Whole-bundle mode: records with nothing disclosed is "nothing to
        # judge from", not bad input; the claims cite the root record.
        bundle = disclosed_bundle({}, capsule_id="root-only", root="root-only")
        bundle["disclosures"] = {}
        pack = compiled_pack()
        document = judge_bundle.run(pack, bundle, None, None, "jev-1.13.0", GENERATED_AT)
        self.assertTrue(all(c["verdict"] == "not_evaluable" for c in document["claims"]))
        self.assertTrue(all(c["rationale"] == judge_bundle.REASON_NOTHING_DISCLOSED for c in document["claims"]))
        root = [{"digest_alg": "SHA-256", "digest": "root-only"}]
        self.assertTrue(all(c["evidence"] == root for c in document["claims"]))

    def test_a_bundle_with_no_records_has_nothing_to_cite_and_is_refused(self):
        # Every Result claim cites at least one record (agent-action-capsule#353).
        bundle = {
            "bundle_version": "2", "bundle_kind": "evidence-bundle/v2", "root": "empty",
            "records": [], "completeness": {"records_mode": "complete", "payloads_mode": "all", "missing": []},
            "disclosures": {},
        }
        with self.assertRaisesRegex(judge_bundle.BadInput, "no record to cite"):
            judge_bundle.run(compiled_pack(), bundle, None, None, "jev-1.13.0", GENERATED_AT)


class DisclosedBundleJudged(unittest.TestCase):
    def test_semantic_rule_met(self):
        pack = compiled_pack()
        clauses = judge_bundle.select_clauses(pack, ["9"])
        answers, target_ids, actually_judged = judge_bundle.judge_bundle(
            disclosed_bundle(FACTS), clauses, None, "jev-1.13.0", backend=fixed_backend("met"))
        self.assertTrue(actually_judged)
        self.assertEqual(target_ids, [CAPSULE_ID])
        self.assertEqual(answers["transaction_scope.material_terms_changed"]["verdict"], "met")

    def test_semantic_rule_not_met(self):
        pack = compiled_pack()
        clauses = judge_bundle.select_clauses(pack, ["9"])
        answers, target_ids, actually_judged = judge_bundle.judge_bundle(
            disclosed_bundle(FACTS), clauses, None, "jev-1.13.0", backend=fixed_backend("not_met"))
        self.assertEqual(answers["transaction_scope.material_terms_changed"]["verdict"], "not_met")

    def test_out_of_scope_when_nothing_this_rule_describes_is_present(self):
        pack = compiled_pack()
        clauses = judge_bundle.select_clauses(pack, ["21"])
        answers, target_ids, actually_judged = judge_bundle.judge_bundle(
            disclosed_bundle(FACTS), clauses, None, "jev-1.13.0", backend=fixed_backend("out_of_scope"))
        self.assertEqual(answers["counterparty_behavior.unexpected_channel_change"]["verdict"], "out_of_scope")

    def test_end_to_end_met_and_not_met_rows_both_produce_claims(self):
        pack = compiled_pack()
        clauses = judge_bundle.select_clauses(pack, ["9", "10"])

        def fn(qid, q, state):
            return "met" if "material_terms_changed" in qid else "not_met"

        document = judge_bundle.run(pack, disclosed_bundle(FACTS), ["9", "10"], None, "jev-1.13.0",
                                    GENERATED_AT, backend=jevals.MockBackend(fn=fn))
        verdicts = {c["requirement_ref"]: c["verdict"] for c in document["claims"]}
        self.assertEqual(verdicts["transaction_scope.material_terms_changed"], "met")
        self.assertEqual(verdicts["transaction_scope.materially_different_offer"], "not_met")

    def test_out_of_scope_row_excluded_from_claims_but_others_still_judged(self):
        pack = compiled_pack()

        def fn(qid, q, state):
            return "out_of_scope" if "unexpected_channel_change" in qid else "met"

        document = judge_bundle.run(pack, disclosed_bundle(FACTS), ["9", "21"], None, "jev-1.13.0",
                                    GENERATED_AT, backend=jevals.MockBackend(fn=fn))
        ids = {c["requirement_ref"] for c in document["claims"]}
        self.assertNotIn("counterparty_behavior.unexpected_channel_change", ids)
        self.assertIn("transaction_scope.material_terms_changed", ids)
        self.assertEqual(document["aggregate"]["coverage"]["excluded_not_applicable"], 1)

    def test_judged_claim_cites_the_bundle_record(self):
        pack = compiled_pack()
        document = judge_bundle.run(pack, disclosed_bundle(FACTS), ["9"], None, "jev-1.13.0",
                                    GENERATED_AT, backend=fixed_backend("met"))
        claim = document["claims"][0]
        self.assertEqual(claim["evidence"], [{"digest_alg": "SHA-256", "digest": CAPSULE_ID}])

    def test_never_out_of_scope_clause_is_never_offered_out_of_scope(self):
        # judge_bundle.py always sends allow_out_of_scope: True -- a clause's
        # own never_out_of_scope must still carry through to jev_judge, or an
        # out_of_scope-forbidden row could be answered out_of_scope anyway.
        pack = {"contract_ref": "test-pack@1", "clauses": [
            {"id": "c.one", "check_id": "c", "claim": "the thing happened", "tier": "judged",
             "rule_id": "1", "never_out_of_scope": True, "judge_input_refs": ["amount_minor"]},
        ], "judge": {"prompt": "packs/everyday-rules/compiled/judge-prompt.md",
                     "axes": "packs/everyday-rules/compiled/axes.json"}}
        seen = {}

        def fn(qid, q, state):
            seen["options"] = set(q.criteria)
            return "met"

        judge_bundle.run(pack, disclosed_bundle(FACTS), None, None, "jev-1.13.0", GENERATED_AT,
                         backend=jevals.MockBackend(fn=fn))
        self.assertNotIn("out_of_scope", seen["options"])


class MonthOfBundles(unittest.TestCase):
    """A month is many bundles: each bundle's claim ids are scoped to the bundle
    (`<root>::<criterion>`), so merge_result_v0_documents takes two of them."""

    def test_two_bundles_results_merge_into_one_document(self):
        from result_v0 import CASE_SEPARATOR, merge_result_v0_documents
        pack = compiled_pack()
        docs = [judge_bundle.run(pack, disclosed_bundle(FACTS, capsule_id=cid, root=root), ["9", "10"], None,
                                 "jev-1.13.0", GENERATED_AT, backend=fixed_backend(verdict))
                for cid, root, verdict in ((CAPSULE_ID, "bundle-oct-01", "met"),
                                           (OTHER_CAPSULE_ID, "bundle-oct-02", "not_met"))]
        for doc, root in zip(docs, ("bundle-oct-01", "bundle-oct-02")):
            for claim in doc["claims"]:
                self.assertEqual(claim["id"], f"{root}{CASE_SEPARATOR}{claim['requirement_ref']}")
        merged = merge_result_v0_documents(docs, "Everyday Rules -- October", GENERATED_AT)
        # 13 judged rules per bundle: 2 selected, 11 claimed not_evaluable.
        self.assertEqual(len(merged["claims"]), 26)
        self.assertEqual(len(merged["aggregate"]["buckets"]["met"]), 2)
        self.assertEqual(len(merged["aggregate"]["buckets"]["not_met"]), 2)
        self.assertEqual(len(merged["aggregate"]["buckets"]["not_evaluable"]), 22)

    def test_two_capsule_id_runs_on_one_bundle_merge(self):
        # Narrowed runs on one bundle share its root; the claim id is scoped to
        # <root>/<capsule_id>, so they no longer collide.
        from result_v0 import CASE_SEPARATOR, merge_result_v0_documents
        pack = compiled_pack()
        bundle = real_deal_bundle()
        ids = [r["capsule_id"] for r in bundle["records"]][:2]
        self.assertEqual(len(ids), 2)
        docs = [judge_bundle.run(pack, bundle, ["9"], cid, "jev-1.13.0", GENERATED_AT,
                                 backend=fixed_backend("met")) for cid in ids]
        for doc, cid in zip(docs, ids):
            claim = judged_claims(doc)[0]
            self.assertEqual(claim["id"], f"{bundle['root']}/{cid}{CASE_SEPARATOR}{claim['requirement_ref']}")
        merged = merge_result_v0_documents(docs, "Everyday Rules -- one bundle", GENERATED_AT)
        self.assertEqual(len(merged["claims"]), 26)

    def test_a_bundle_root_holding_the_case_separator_is_refused(self):
        from result_v0 import RollupError
        pack = compiled_pack()
        with self.assertRaisesRegex(RollupError, "::"):
            judge_bundle.run(pack, disclosed_bundle(FACTS, root="bundle::oct"), ["9"], None,
                             "jev-1.13.0", GENERATED_AT, backend=fixed_backend("met"))


class PartialRunIsNotAFullPass(unittest.TestCase):
    """A --rule-ids run judges some rules. The card renders against the whole
    pack and reads a rule with no claim as not_applicable, so every judged rule
    outside the selection is claimed not_evaluable: the run cannot resolve."""

    def test_one_rule_met_leaves_every_other_judged_rule_not_evaluable(self):
        pack = compiled_pack()
        bundle = disclosed_bundle(FACTS)
        document = judge_bundle.run(pack, bundle, ["9"], None, "jev-1.13.0",
                                    GENERATED_AT, backend=fixed_backend("met"))
        judged_rule_ids = {c["rule_id"] for c in pack["clauses"] if c.get("tier") == "judged"}
        self.assertEqual({c["rule_id"] for c in document["claims"]}, judged_rule_ids)
        by_rule = {c["rule_id"]: c for c in document["claims"]}
        self.assertEqual(by_rule["9"]["verdict"], "met")
        for rid, claim in by_rule.items():
            if rid == "9":
                continue
            self.assertEqual(claim["verdict"], "not_evaluable")
            self.assertEqual(claim["rationale"], judge_bundle.REASON_NOT_SELECTED)
            self.assertNotIn("judge_pin_digest", claim)
            self.assertEqual(claim["evidence"], [{"digest_alg": "SHA-256", "digest": bundle["root"]}])
        buckets = document["aggregate"]["buckets"]
        self.assertEqual(len(buckets["met"]), 1)
        self.assertEqual(len(buckets["not_evaluable"]), len(judged_rule_ids) - 1)
        self.assertEqual(document["aggregate"]["coverage"]["excluded_not_applicable"], 0)

    def test_a_full_run_claims_nothing_as_not_selected(self):
        pack = compiled_pack()
        document = judge_bundle.run(pack, disclosed_bundle(FACTS), None, None, "jev-1.13.0",
                                    GENERATED_AT, backend=fixed_backend("met"))
        self.assertTrue(all(c["verdict"] == "met" for c in document["claims"]))
        self.assertFalse(any(c.get("rationale") == judge_bundle.REASON_NOT_SELECTED for c in document["claims"]))


class WholeBundleDefault(unittest.TestCase):
    """The default (no --capsule-id): every disclosed record in the bundle,
    plus its extensions, feed one batched judge request -- exercised against
    the real 10-record capsulectl deal bundle, not a hand-built stand-in."""

    def test_disclosed_records_gathers_every_disclosed_record_and_nothing_else(self):
        bundle = real_deal_bundle()
        facts_by_id = judge_bundle.disclosed_records(bundle)
        self.assertEqual(set(facts_by_id), {r["capsule_id"] for r in bundle["records"]})
        self.assertEqual(len(facts_by_id), 10)

    def test_whole_bundle_judges_every_clause_and_cites_every_disclosed_record(self):
        pack = compiled_pack()
        bundle = real_deal_bundle()
        expected_ids = sorted(r["capsule_id"] for r in bundle["records"])
        document = judge_bundle.run(pack, bundle, None, None, "jev-1.13.0", GENERATED_AT,
                                    backend=fixed_backend("met"))
        self.assertEqual(len(document["claims"]), 13)
        for claim in document["claims"]:
            cited = sorted(e["digest"] for e in claim["evidence"])
            self.assertEqual(cited, expected_ids)
            self.assertIn("judge_pin_digest", claim)

    def test_every_claim_in_one_batch_carries_the_same_pin_even_a_clause_with_no_input_refs_of_its_own(self):
        # judge_batch: true -- every in-scope clause shares one jev_judge.judge_many()
        # request and so one judge_pin, including a clause (rule 21, unexpected_channel_change)
        # that declares no judge_input_refs of its own: it was still decided from
        # the batch's one shared request, not a request of its own, so it carries
        # the batch's pin too -- never a different, narrower one invented per clause.
        pack = compiled_pack()
        bundle = real_deal_bundle()
        document = judge_bundle.run(pack, bundle, ["9", "21"], None, "jev-1.13.0", GENERATED_AT,
                                    backend=fixed_backend("met"))
        self.assertEqual(len(judged_claims(document)), 2)
        digests = {c["judge_pin_digest"] for c in judged_claims(document)}
        pins = [c["judge_pin"] for c in judged_claims(document)]
        self.assertEqual(len(digests), 1)
        self.assertEqual(pins[0], pins[1])
        self.assertEqual(pins[0]["input_refs"], ["amount_minor", "currency", "recurrence"])

    def test_whole_bundle_request_carries_every_record_and_the_extension(self):
        bundle = real_deal_bundle()
        pack = compiled_pack()
        clauses = judge_bundle.select_clauses(pack, ["9"])
        seen = {}

        def fn(qid, q, state):
            seen["disclosed_facts"] = state["disclosed_facts"]
            return "met"

        judge_bundle.judge_bundle(bundle, clauses, None, "jev-1.13.0", backend=jevals.MockBackend(fn=fn))
        self.assertEqual(set(seen["disclosed_facts"]["records"]), {r["capsule_id"] for r in bundle["records"]})
        self.assertEqual(seen["disclosed_facts"]["extensions"], bundle["extensions"])

    def test_capsule_id_narrows_to_one_record_of_the_real_bundle(self):
        bundle = real_deal_bundle()
        one_id = bundle["records"][0]["capsule_id"]
        pack = compiled_pack()
        document = judge_bundle.run(pack, bundle, ["9"], one_id, "jev-1.13.0", GENERATED_AT,
                                    backend=fixed_backend("met"))
        claim = document["claims"][0]
        self.assertEqual(claim["evidence"], [{"digest_alg": "SHA-256", "digest": one_id}])

    def test_capsule_id_naming_a_record_outside_the_bundle_is_not_evaluable(self):
        bundle = real_deal_bundle()
        pack = compiled_pack()
        document = judge_bundle.run(pack, bundle, None, "not-a-real-capsule-id", "jev-1.13.0",
                                    GENERATED_AT)
        self.assertTrue(all(c["verdict"] == "not_evaluable" for c in document["claims"]))
        self.assertTrue(all(c["rationale"] == judge_bundle.REASON_RECORD_NOT_FOUND for c in document["claims"]))


class JudgePin(unittest.TestCase):
    def test_pin_is_present_and_stable(self):
        pin_a, digest_a = pin_for("jev-1.13.0", ["outgoing_content"])
        pin_b, digest_b = pin_for("jev-1.13.0", ["outgoing_content"])
        self.assertEqual(pin_a, pin_b)
        self.assertEqual(digest_a, digest_b)
        self.assertEqual(set(pin_a), set(instrument_pin.PIN_KEYS))
        self.assertEqual(pin_a["model_id"], "jev-1.13.0")
        self.assertEqual(pin_a["input_refs"], ["outgoing_content"])
        self.assertEqual(pin_a["model_hosting"], "hosted")
        self.assertEqual(pin_a["prompt_template_hash"], jev_judge.compiled_prompt_digest(
            judge_bundle.request_clauses(rule9_clauses()), judge_bundle.ALLOW_OUT_OF_SCOPE, mode="disclosed_facts"))
        self.assertEqual(pin_a["schema_hash"], jev_judge.answer_schema_digest())

    def test_pin_moves_with_input_refs(self):
        pin_a, digest_a = pin_for("jev-1.13.0", ["outgoing_content"])
        pin_b, digest_b = pin_for("jev-1.13.0", ["amount_minor"])
        self.assertNotEqual(pin_a, pin_b)
        self.assertNotEqual(digest_a, digest_b)

    def test_build_pin_refuses_a_duplicate_input_ref(self):
        """build_pin itself, the one place meant to assert the pin's own
        invariants, must not silently seal a pin #96's own loader would
        refuse for exactly this reason."""
        with self.assertRaises(ValueError):
            instrument_pin.build_pin("jev-1.13.0", "a" * 64, "b" * 64, ["amount_minor", "amount_minor"], "hosted")

    def test_build_pin_refuses_an_empty_input_refs(self):
        with self.assertRaises(ValueError):
            instrument_pin.build_pin("jev-1.13.0", "a" * 64, "b" * 64, [], "hosted")

    def test_declared_input_refs_unions_every_judged_clause(self):
        clauses = [
            {"id": "c.one", "judge_input_refs": ["amount_minor", "currency"]},
            {"id": "c.two", "judge_input_refs": ["currency", "outgoing_content"]},
            {"id": "c.three"},  # no judge_input_refs at all: contributes nothing
        ]
        self.assertEqual(judge_bundle.declared_input_refs(clauses), ["amount_minor", "currency", "outgoing_content"])

    def test_declared_input_refs_empty_when_no_clause_declares_one(self):
        self.assertEqual(judge_bundle.declared_input_refs([{"id": "c.one"}]), [])

    def test_judged_claim_carries_judge_pin_digest_matching_model_and_input_refs(self):
        pack = compiled_pack()
        document = judge_bundle.run(pack, disclosed_bundle(FACTS), ["9"], None, "jev-1.13.0",
                                    GENERATED_AT, backend=fixed_backend("met"))
        claim = document["claims"][0]
        self.assertIn("judge_pin_digest", claim)
        self.assertEqual(claim["judge_pin"]["model_id"], "jev-1.13.0")
        self.assertEqual(claim["judge_pin"]["model_hosting"], "hosted")
        # rule 9's own judge_input_refs (packs/everyday-rules/pack-source.yaml)
        self.assertEqual(claim["judge_pin"]["input_refs"], ["amount_minor", "currency", "recurrence"])
        # ... never a record/capsule_id -- that stays in evidence[] (above tests), not the pin.
        self.assertNotIn(CAPSULE_ID, claim["judge_pin"]["input_refs"])

    def test_run_refuses_to_seal_a_pin_when_no_selected_clause_declares_an_input_ref(self):
        pack = compiled_pack()
        with self.assertRaisesRegex(judge_bundle.BadInput, "judge_input_refs"):
            judge_bundle.run(pack, disclosed_bundle(FACTS), ["21"], None, "jev-1.13.0",
                             GENERATED_AT, backend=fixed_backend("met"))


class CliSmoke(unittest.TestCase):
    """End-to-end CLI runs against the real compiled pack, JEV_JUDGE_BACKEND=mock."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bundle_path = pathlib.Path(self.tmp.name) / "bundle.json"
        self.pack_path = ROOT / "packs" / "everyday-rules" / "compiled" / "compiled.json"

    def _run(self, bundle, *extra_args):
        self.bundle_path.write_text(json.dumps(bundle))
        import os
        env = dict(os.environ, JEV_JUDGE_BACKEND="mock")
        return subprocess.run(
            [sys.executable, JUDGE_BUNDLE_PATH, "--bundle", str(self.bundle_path), "--pack", str(self.pack_path),
            "--generated-at", GENERATED_AT, *extra_args],
            capture_output=True, text=True, env=env,
        )

    def test_disclosed_bundle_runs_end_to_end(self):
        proc = self._run(disclosed_bundle(FACTS))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        document = json.loads(proc.stdout)
        self.assertEqual(document["result_version"], "evidence-result-v0")
        self.assertTrue(document["claims"])

    def test_withheld_bundle_runs_end_to_end_all_not_evaluable(self):
        proc = self._run(withheld_bundle())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        document = json.loads(proc.stdout)
        self.assertEqual(len(document["claims"]), 13)
        self.assertTrue(all(c["verdict"] == "not_evaluable" for c in document["claims"]))

    def test_rule_ids_subset_on_the_cli(self):
        proc = self._run(disclosed_bundle(FACTS), "--rule-ids", "8,26")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        document = json.loads(proc.stdout)
        judged = {c["rule_id"] for c in document["claims"] if c["verdict"] != "not_evaluable"}
        self.assertTrue(judged <= {"8", "26"})
        others = [c for c in document["claims"] if c["rule_id"] not in {"8", "26"}]
        self.assertEqual(len(others), 11)
        self.assertTrue(all(c["verdict"] == "not_evaluable" for c in others))

    def test_malformed_rule_ids_exits_as_bad_input_not_a_backend_failure(self):
        proc = self._run(disclosed_bundle(FACTS), "--rule-ids", ",")
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertEqual(proc.stdout, "")
        self.assertIn("no rule id", proc.stderr)

    def test_bad_bundle_kind_exits_nonzero(self):
        proc = self._run({"bundle_kind": "nope/v1"})
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, "")
        self.assertIn("evidence-bundle/v2", proc.stderr)

    def test_real_multi_record_bundle_runs_end_to_end_on_the_cli(self):
        # The mock backend's verdict is a content hash, so some of the 13
        # clauses may land on out_of_scope (excluded from claims[] by design,
        # see result_v0.py) -- the fixed count to check is claims +
        # excluded_not_applicable, not claims alone.
        proc = self._run(real_deal_bundle())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        document = json.loads(proc.stdout)
        self.assertTrue(document["claims"])
        self.assertEqual(len(document["claims"]) + document["aggregate"]["coverage"]["excluded_not_applicable"], 13)
        for claim in document["claims"]:
            self.assertEqual(len(claim["evidence"]), 10)

    def test_real_multi_record_bundle_narrowed_to_one_capsule_id_on_the_cli(self):
        bundle = real_deal_bundle()
        one_id = bundle["records"][0]["capsule_id"]
        proc = self._run(bundle, "--capsule-id", one_id)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        document = json.loads(proc.stdout)
        for claim in document["claims"]:
            self.assertEqual(claim["evidence"], [{"digest_alg": "SHA-256", "digest": one_id}])


if __name__ == "__main__":
    unittest.main()
