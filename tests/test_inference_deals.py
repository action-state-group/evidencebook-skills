"""packs/inference-deals and its evaluator (evidencebook-skills#71).

Fixtures: tests/fixtures/inference-deals/{payer,provider}.jsonl, the two
ledgers the Mesh plugin's own producer sealed for one scripted two-node run
(that directory's README). Each test hands the evaluator a node's records
as (book capsule id, payload) pairs, the shape scripts/evaluators/
inference_deals.py reads from a book; the book id here is the Mesh
capsule's own id. tests/fresh_env_deals.sh runs the same records through a
real book, `report.sh --seal` and `report check`.
"""
import copy
import datetime
import json
import os
import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "evaluators"))

import evidence_contract  # noqa: E402
import inference_deals as deals  # noqa: E402
import pack_compile  # noqa: E402
import packs  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "inference-deals"
SOURCE = ROOT / "packs" / "inference-deals" / "pack-source.yaml"
COMPILED = ROOT / "packs" / "inference-deals" / "compiled" / "compiled.json"
DATE = datetime.date(2026, 11, 1)  # the window ends 2026-11-02T00:00Z, after the fixtures' week
GENERATED_AT = "2026-11-01T23:59:59Z"

PAID, SERVED, MODEL = deals.PAID, deals.SERVED, deals.MODEL


def load(node):
    return [json.loads(line) for line in (FIXTURES / f"{node}.jsonl").read_text().splitlines()]


def records(capsules):
    return [(c["capsule_id"], c) for c in capsules]


def compiled():
    return json.loads(COMPILED.read_text())


def run(capsules, date=DATE, policy=None):
    return deals.build_result(records(capsules), compiled(), date, GENERATED_AT, policy)


def claims(doc):
    return {c["id"]: c for c in doc["claims"]}


def observation(capsule):
    return deals._attestation(capsule).get(deals.OBSERVATION)


def deal_records(capsules, exchange_id):
    return [c for c in capsules
            if (observation(c) or {}).get("exchange_id") == exchange_id
            or (deals._attestation(c).get(deals.EXCHANGE) or {}).get("serving_provenance", {})
            .get("exchange_id") == exchange_id]


class PackCompiles(unittest.TestCase):
    def test_validates_and_compiles_to_the_committed_file(self):
        source = pack_compile._strip_strings(__import__("yaml").safe_load(SOURCE.read_text()))
        self.assertEqual(pack_compile.validate_source(source), [])
        built, axes, prompt, presentation = pack_compile.compile_pack(source, "packs/inference-deals/compiled")
        self.assertEqual((axes, prompt, presentation), (None, None, None), "a deterministic pack has no judge files")
        self.assertNotIn("judge", built)
        self.assertEqual(json.dumps(built, indent=2) + "\n", COMPILED.read_text())
        self.assertEqual(sorted(p.name for p in COMPILED.parent.iterdir()), ["compiled.json"])

    def test_every_requirement_is_must_have_and_published(self):
        source = __import__("yaml").safe_load(SOURCE.read_text())
        contract = evidence_contract.from_pack(pack_compile._strip_strings(source))
        self.assertEqual([r["tier"] for r in contract["requirements"]], ["must_have"] * 3)
        self.assertTrue(all(r["backward_verdict"] == "DETERMINISTIC" for r in contract["requirements"]))
        published = json.loads((ROOT / "contracts" / "inference-deals" / "0.1.1.json").read_text())
        self.assertEqual(published, contract)

    def test_packs_list_shows_it_on_card_settlement(self):
        entry = {p["name"]: p for p in packs.list_packs()}["inference-deals"]
        self.assertEqual(entry["card"], "settlement")
        self.assertEqual(entry["contract_ref"], "inference-deals@0.1.1")
        self.assertEqual(packs.require("inference-deals")[0], 0)

    def test_default_policy_is_the_nodes_service_history_policy(self):
        policy = compiled()["window"]["period_policy"]
        self.assertEqual(deals.policy_digest(policy),
                         "0d4b28af7ebfca01a49c1ad59e74b7d9bff0e6712dd3478b4ee35b8ff6af5150")


class DeterministicPackValidation(unittest.TestCase):
    def source(self):
        return pack_compile._strip_strings(__import__("yaml").safe_load(SOURCE.read_text()))

    def issues(self, source):
        return " | ".join(pack_compile.validate_source(source))

    def test_a_judge_is_refused(self):
        s = self.source()
        s["judge"] = {"model_id": "m"}
        self.assertIn("names an evaluator and no judge", self.issues(s))

    def test_a_judged_criterion_is_refused(self):
        s = self.source()
        s["checks"][0]["criteria"][2]["tier"] = "judged"
        self.assertIn("must be 'recomputed' in a deterministic pack", self.issues(s))

    def test_an_unknown_evaluator_is_refused(self):
        s = self.source()
        s["evaluator"] = "llm_judge"
        self.assertIn("evaluator must be one of", self.issues(s))

    def test_a_rolling_or_malformed_window_is_refused(self):
        for window, expected in (({"months": 12}, "exactly {months, period_policy}"),
                                 ({"months": 0, "period_policy": self.source()["window"]["period_policy"]},
                                  "positive integer"),
                                 ({"months": 12, "period_policy": {"length_s": 86400}}, "must have exactly")):
            s = self.source()
            s["window"] = window
            self.assertIn(expected, self.issues(s))

    def test_a_report_template_is_refused(self):
        s = self.source()
        s["report"] = {"template": "outcome-report/v1"}
        self.assertIn("no report template", self.issues(s))


class Window(unittest.TestCase):
    POLICY = {"epoch": "2026-01-05T00:00:00Z", "length_s": 604800, "min_length_s": 86400,
              "floor": 5, "suppression": "complementary"}

    def test_twelve_months_of_weeks_end_at_the_last_boundary(self):
        start, to, periods = deals.window_bounds(datetime.date(2026, 10, 29), 12, self.POLICY)
        self.assertEqual(to.isoformat(), "2026-10-26T00:00:00+00:00")  # Monday, the last closed week
        self.assertEqual(start.isoformat(), "2025-10-27T00:00:00+00:00")
        self.assertEqual(periods, 52)

    def test_the_window_moves_only_when_a_period_closes(self):
        bounds = {deals.window_bounds(datetime.date(2026, 10, d), 12, self.POLICY) for d in range(26, 32)}
        self.assertEqual(len(bounds), 1, "every day of one week gives the same window")
        self.assertNotEqual(deals.window_bounds(datetime.date(2026, 11, 1), 12, self.POLICY), bounds.pop())

    def test_a_record_in_the_open_period_is_not_read(self):
        with self.assertRaisesRegex(deals.DealsError, "no counted deal"):
            run(load("payer"), date=datetime.date(2026, 10, 31))

    def test_months_clamp_to_the_target_month(self):
        dt = datetime.datetime(2026, 3, 31, tzinfo=datetime.timezone.utc)
        self.assertEqual(deals._months_before(dt, 1).day, 28)

    def test_a_node_policy_replaces_the_default(self):
        daily = dict(self.POLICY, length_s=86400)
        doc, _ = run(load("payer"), policy=daily)
        self.assertEqual(doc["x-window"]["periods"], 365)
        self.assertEqual(doc["x-window"]["to"], "2026-11-02T00:00:00Z")
        self.assertNotEqual(doc["x-window"]["period_policy_digest"], deals.policy_digest(self.POLICY))


class Goldens(unittest.TestCase):
    """The committed Results: self-attested and not_evaluable from the two
    ledgers, and a countersigned vector from the provider's ledger plus the
    payer's terms legs its payee legs name (no Mesh node holds those in its book
    today; see the fixtures README)."""

    def check(self, capsules, golden):
        doc, _ = run(capsules)
        expected = json.loads((FIXTURES / golden).read_text())
        self.assertEqual(doc, expected, f"regenerate {golden} only for an intended change")
        return doc

    def test_payer(self):
        doc = self.check(load("payer"), "golden-payer.json")
        got = {cid: (c["verdict"], c["grade"]) for cid, c in claims(doc).items()}
        self.assertEqual(got, {
            f"d1::{PAID}": ("met", "self-attested"),            # settled for the invoiced amounts
            f"d2::{PAID}": ("not_met", "self-attested"),        # the wallet paid less than one invoice
            f"d3::{PAID}": ("not_evaluable", "self-attested"),  # terms_only
            f"d4::{PAID}": ("not_evaluable", "self-attested"),  # outcome_not_reported
        })
        self.assertEqual(doc["aggregate"]["coverage"]["excluded_not_applicable"], 8, "terms 2 and 3 do not apply")

    def test_provider(self):
        doc = self.check(load("provider"), "golden-provider.json")
        self.assertEqual(claims(doc)[f"d1::{SERVED}"]["verdict"], "met")
        self.assertEqual(claims(doc)[f"d4::{SERVED}"]["verdict"], "not_evaluable")
        model = {cid: (c["verdict"], c["x-reading"], c.get("x-adjudication"))
                 for cid, c in claims(doc).items() if cid.endswith(MODEL)}
        self.assertEqual(model, {
            f"d1::{MODEL}": ("met", "adjudicated", "corroborated"),             # the referee corroborated it
            f"d2::{MODEL}": ("not_met", "adjudicated", "contradicted"),
            f"d3::{MODEL}": ("met", "provider_states", None),
            f"d4::{MODEL}": ("met", "provider_states", None),
        })
        self.assertEqual(doc["x-window"]["adjudicated_deals"], 2)
        self.assertFalse(any(cid.endswith(PAID) for cid in claims(doc)), "a provider deal has no payer row")

    def test_provider_countersigned(self):
        payer, provider = load("payer"), load("provider")
        named = {c["settlement"]["terms_ref"] for c in provider if "settlement" in c}
        held = [c for c in payer if c["capsule_id"] in named]
        self.assertEqual(len(held), 4, "the payer's terms legs of the two settled deals")
        doc = self.check(provider + held, "vector-provider-countersigned.json")
        grades = {cid: c["grade"] for cid, c in claims(doc).items() if cid.endswith(SERVED)}
        self.assertEqual(grades, {f"d1::{SERVED}": "countersigned", f"d2::{SERVED}": "countersigned",
                                  f"d3::{SERVED}": "self-attested", f"d4::{SERVED}": "self-attested"})

    def test_one_countersigned_payment_of_two_is_not_countersigned(self):
        payer, provider = load("payer"), load("provider")
        settled = [c for c in provider if "settlement" in c][:2]  # deal-settled's two payee legs
        held = [c for c in payer if c["capsule_id"] == settled[0]["settlement"]["terms_ref"]]
        doc, _ = run(provider + held)
        self.assertEqual(claims(doc)[f"d1::{SERVED}"]["grade"], "self-attested")

    def test_a_settlement_without_a_hash_is_not_countersigned(self):
        payer, provider = load("payer"), load("provider")
        named = {c["settlement"]["terms_ref"] for c in provider if "settlement" in c}
        held = [c for c in payer if c["capsule_id"] in named]
        for c in deal_records(provider, "p-deal-settled"):
            if observation(c) and observation(c)["phase"] == "output_settlement_observed":
                observation(c)["payment_hash"] = None  # joined to its invoice by segment
        row = claims(run(provider + held)[0])[f"d1::{SERVED}"]
        self.assertEqual((row["verdict"], row["grade"]), ("met", "self-attested"))

    def test_a_repeated_settlement_of_one_payment_stays_countersigned(self):
        payer, provider = load("payer"), load("provider")
        named = {c["settlement"]["terms_ref"] for c in provider if "settlement" in c}
        held = [c for c in payer if c["capsule_id"] in named]
        again = copy.deepcopy(next(c for c in deal_records(provider, "p-deal-settled")
                                   if observation(c) and observation(c)["phase"] == "output_settlement_observed"))
        again["capsule_id"] = "b" * 64
        row = claims(run(provider + held + [again])[0])[f"d1::{SERVED}"]
        self.assertEqual((row["verdict"], row["grade"]), ("met", "countersigned"))

    def test_an_own_leg_without_a_key_is_not_a_countersignature(self):
        payer, provider = load("payer"), load("provider")
        named = {c["settlement"]["terms_ref"] for c in provider if "settlement" in c}
        held = [c for c in payer if c["capsule_id"] in named]
        keyless = [{k: v for k, v in c.items() if k != "key_id"} if "settlement" in c else c for c in provider]
        doc, _ = run(keyless + held)
        self.assertTrue(all(c["grade"] == "self-attested" for c in doc["claims"]))

    def test_a_leg_under_the_nodes_own_key_is_not_a_countersignature(self):
        payer, provider = load("payer"), load("provider")
        named = {c["settlement"]["terms_ref"] for c in provider if "settlement" in c}
        own_key = next(c["key_id"] for c in provider if "key_id" in c)
        forged = [dict(c, key_id=own_key) for c in payer if c["capsule_id"] in named]
        doc, _ = run(provider + forged)
        self.assertTrue(all(c["grade"] == "self-attested" for c in doc["claims"]))

    def test_results_validate_against_evidence_result_v0(self):
        import jsonschema
        schema = json.loads((ROOT / "tests" / "fixtures" / "evidence-result-v0.json").read_text())
        for node in ("payer", "provider"):
            jsonschema.validate(run(load(node))[0], schema)

    def test_the_same_records_give_the_same_bytes(self):
        a, _ = run(load("provider"))
        b, _ = run(list(reversed(load("provider"))))
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))


class Negatives(unittest.TestCase):
    """Issue #71 acceptance 3: each of these must fail."""

    def test_a_free_exchange_is_never_judged(self):
        payer = load("payer")
        free = deal_records(payer, "free")
        self.assertEqual(len(free), 1, "the fixture's free exchange: one exchange record, no observation")
        doc, _ = run(payer)
        cited = {e["digest"] for c in doc["claims"] for e in c["evidence"]}
        self.assertNotIn(free[0]["capsule_id"], cited)
        self.assertEqual(doc["x-window"]["deals_counted"], 4)

    def test_a_shop_preauth_deal_is_not_counted(self):
        payer = load("payer")
        for target in deal_records(payer, "deal-short")[:2]:  # on one record or on several that agree
            target["counterparty_class"] = "shop_preauth"
        doc, _ = run(payer)
        self.assertEqual(doc["x-window"]["not_counted_shop_preauth"], 1)
        self.assertEqual(doc["x-window"]["deals_counted"], 3)
        self.assertNotIn("not_met", {c["verdict"] for c in doc["claims"]}, "the short deal is gone")

    def test_counterparty_classes_that_disagree_read_as_lacking_and_conflicting(self):
        payer = load("payer")
        first, second = deal_records(payer, "deal-short")[:2]
        first["counterparty_class"], second["counterparty_class"] = "shop_preauth", "person_agent"
        doc, _ = run(payer)
        self.assertEqual(doc["x-window"]["not_counted_shop_preauth"], 0)
        self.assertEqual((doc["x-window"]["class_missing"], doc["x-window"]["class_conflicting"]), (4, 1))

    def test_unreported_and_unseen_settlements_are_never_not_met(self):
        payer = load("payer")
        unreported = deal_records(payer, "deal-unreported")
        accounted = next(c for c in deal_records(payer, "deal-settled")
                         if observation(c) and observation(c)["phase"] == "final_accounted")
        unseen = copy.deepcopy(accounted)
        observation(unseen)["exchange_id"] = "deal-unreported"
        unseen["capsule_id"] = "f" * 64
        doc, summary = run(payer + [unseen])
        states = {c["x-state"]: c["verdict"] for c in doc["claims"]}
        self.assertEqual(states["no_settlement_seen"], "not_evaluable")
        doc, _ = run(payer)
        states = {c["x-state"]: c["verdict"] for c in doc["claims"]}
        self.assertEqual(states["outcome_not_reported"], "not_evaluable")
        self.assertEqual(states["terms_only"], "not_evaluable")
        self.assertTrue(unreported)

    def test_the_peer_book_is_not_available_never_a_row(self):
        doc, _ = run(load("provider"))
        self.assertEqual(doc["x-window"]["peer_book"], "not_available")
        self.assertEqual({c["requirement_ref"] for c in doc["claims"]}, {SERVED, MODEL})

    def test_an_unmatched_settlement_is_counted_not_graded(self):
        payer = load("payer")
        settlement = next(c for c in deal_records(payer, "deal-settled")
                          if observation(c) and observation(c)["phase"] == "output_settlement_observed")
        stray = copy.deepcopy(settlement)
        observation(stray)["payment_hash"] = "00" * 32
        stray["capsule_id"] = "e" * 64
        doc, _ = run(payer + [stray])
        self.assertEqual(doc["x-window"]["unmatched_settlements"], 1)
        self.assertEqual(claims(doc)[f"d1::{PAID}"]["verdict"], "met", "the stray settlement grades nothing")
        cited = {e["digest"] for e in claims(doc)[f"d1::{PAID}"]["evidence"]}
        self.assertIn(stray["capsule_id"], cited)

    def test_a_missing_amount_is_never_met(self):
        payer = load("payer")
        for c in deal_records(payer, "deal-settled"):
            if observation(c) and observation(c)["phase"] == "output_settlement_observed":
                del observation(c)["amount_msat"]
        row = claims(run(payer)[0])[f"d1::{PAID}"]
        self.assertEqual((row["verdict"], row["x-state"]), ("not_evaluable", "amount_missing"))

    def test_served_records_that_disagree_decide_nothing(self):
        provider = load("provider")
        served = next(c for c in deal_records(provider, "p-deal-terms") if deals._attestation(c).get(deals.EXCHANGE))
        other = copy.deepcopy(served)
        other["capsule_id"] = "d" * 64
        deals._attestation(other)["invocation"]["resolved_model_id"] = "another-model"
        for book in (provider + [other], [other] + provider):  # either order
            self.assertEqual(claims(run(book)[0])[f"d3::{MODEL}"]["verdict"], "not_evaluable")

    def test_a_contradiction_naming_the_other_half_is_corroborated_for_this_node(self):
        provider = load("provider")
        adj = next(c for c in provider if "adjudication_received" in deals._attestation(c)
                   and deals._attestation(c)["adjudication_received"]["verdict"].startswith("contradicted:"))
        block = deals._attestation(adj)["adjudication_received"]
        block["verdict"] = "contradicted:" + block["half_node_ids"][1]  # the twin, not this node
        row = claims(run(provider)[0])[f"d2::{MODEL}"]
        self.assertEqual((row["verdict"], row["x-adjudication"]), ("met", "corroborated"))
        block["verdict"] = "contradicted:" + "7e" * 32  # a node outside the two halves
        row = claims(run(provider)[0])[f"d2::{MODEL}"]
        self.assertEqual((row["verdict"], row["x-adjudication"]), ("not_evaluable", "no_ruling"))

    def test_a_verdict_without_exactly_two_halves_decides_nothing(self):
        provider = load("provider")
        adj = next(c for c in provider if "adjudication_received" in deals._attestation(c)
                   and deals._attestation(c)["adjudication_received"]["verdict"] == "corroborated")
        block = deals._attestation(adj)["adjudication_received"]
        for halves in (block["half_node_ids"][:1], block["half_node_ids"] + ["7e" * 32]):
            block["half_node_ids"] = halves
            row = claims(run(provider)[0])[f"d1::{MODEL}"]
            self.assertEqual((row["verdict"], row["x-adjudication"]), ("not_evaluable", "no_ruling"))

    def test_adjudications_that_disagree_decide_nothing(self):
        provider = load("provider")
        adj = next(c for c in provider if "adjudication_received" in deals._attestation(c))
        other = copy.deepcopy(adj)
        other["capsule_id"] = "c" * 64
        deals._attestation(other)["adjudication_received"]["verdict"] = "inconclusive"
        row = claims(run(provider + [other])[0])[f"d1::{MODEL}"]
        self.assertEqual((row["verdict"], row["x-adjudication"]), ("not_evaluable", "conflicting"))

    def test_a_provider_record_is_never_counted_in_the_payer_row(self):
        payer, provider = load("payer"), load("provider")
        mixed = copy.deepcopy(next(c for c in provider if (observation(c) or {}).get("phase") == "delivered"))
        observation(mixed)["exchange_id"] = "deal-settled"
        doc, _ = run(payer + [mixed])
        # One node is never both sides of one exchange: the deal's records
        # conflict, so no row is graded from them, the payer row least of all.
        rows = [c for cid, c in claims(doc).items() if cid.startswith("d1::")]
        self.assertEqual({(c["verdict"], c["x-state"]) for c in rows}, {("not_evaluable", "conflicting_roles")})

    def test_an_exchange_record_on_the_other_side_is_a_conflict(self):
        payer, provider = load("payer"), load("provider")
        served = copy.deepcopy(next(c for c in provider if (deals._attestation(c).get(deals.EXCHANGE) or {})
                                    .get("serving_provenance", {}).get("exchange_id") == "p-deal-settled"))
        deals._attestation(served)[deals.EXCHANGE]["serving_provenance"]["exchange_id"] = "deal-settled"
        rows = [c for cid, c in claims(run(payer + [served])[0]).items() if cid.startswith("d1::")]
        self.assertEqual({(c["verdict"], c["x-state"]) for c in rows}, {("not_evaluable", "conflicting_roles")})

    def test_a_payer_record_is_never_counted_in_the_provider_rows(self):
        payer, provider = load("payer"), load("provider")
        mixed = copy.deepcopy(next(c for c in payer if (observation(c) or {}).get("phase") == "final_accounted"))
        observation(mixed)["exchange_id"] = "p-deal-settled"
        doc, _ = run(provider + [mixed])
        rows = [c for cid, c in claims(doc).items() if cid.startswith("d1::")]
        self.assertEqual({(c["verdict"], c["x-state"]) for c in rows}, {("not_evaluable", "conflicting_roles")})

    def test_no_claim_carries_an_amount_a_node_id_or_a_payment_hash(self):
        for node in ("payer", "provider"):
            capsules = load(node)
            doc, _ = run(capsules)
            text = json.dumps({k: v for k, v in doc.items()})
            forbidden = set()
            for c in capsules:
                o = observation(c) or {}
                forbidden |= {o.get("payment_hash"), o.get("exchange_id")}
                prov = (deals._attestation(c).get(deals.EXCHANGE) or {}).get("serving_provenance") or {}
                forbidden |= {prov.get("served_by_node_id"), prov.get("requesting_party"), prov.get("exchange_id")}
                if "settlement" in c:
                    forbidden.add((c["settlement"].get("payment_ref") or {}).get("value"))
            # Ids and hashes only: a short placeholder such as "unknown" is no identifier.
            for value in sorted(v for v in forbidden if v and len(v) >= 12):
                self.assertNotIn(value, text, f"{node}: the Result carries {value!r}")
            self.assertNotRegex(text, r"amount|msat|payment_hash|peer_id|node_id")


class PackDigestCited(unittest.TestCase):
    """capsules-plugin#271: a deal whose records cite another inference-deals
    digest than the pack this evaluator runs is not judged, and the sealed
    Result says why."""

    def cite(self, capsules, digest):
        for c in capsules:
            m = deals._attestation(c).get(deals.EXCHANGE)
            if m is not None:
                m[deals.PACK_DIGEST_MEMBER] = digest

    def test_the_packs_digest_is_the_one_the_plugin_pins(self):
        # Mesh-LLM/capsules-plugin crates/evidence-plugin/src/agreement.rs
        # INFERENCE_DEALS_DIGEST must equal this value. A pack recompile changes
        # it: release the plugin with the new constant in the same batch, or
        # nodes refuse each other's proposals and this judge refuses their deals.
        self.assertEqual(compiled()["pack_source_digest"],
                         "57770b7ef126e97b46f5abd41472c9649ea097e4994114dfe995f513c6e33281")

    def test_records_citing_the_packs_own_digest_are_judged_as_before(self):
        provider = load("provider")
        before, _ = run(provider)
        self.cite(provider, compiled()["pack_source_digest"])
        after, _ = run(provider)
        self.assertEqual([c["verdict"] for c in after["claims"]], [c["verdict"] for c in before["claims"]])
        self.assertNotIn("digest_mismatch_deals", after["x-window"])

    def test_records_citing_none_are_judged_as_before(self):
        doc, _ = run(load("provider"))
        self.assertNotIn("digest_mismatch_deals", doc["x-window"])
        self.assertNotIn(deals.MISMATCH, {c.get("x-reason") for c in doc["claims"]})

    def test_a_mismatched_digest_is_not_judged_and_carries_the_reason(self):
        provider = load("provider")
        self.cite(provider, "0" * 64)
        doc, summary = run(provider)
        rows = doc["claims"]
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual((row["verdict"], row["x-reason"]), ("not_evaluable", deals.MISMATCH))
            self.assertEqual(row["x-cited-inference-deals-digests"], ["0" * 64])
            self.assertEqual(row["x-pack-digest"], compiled()["pack_source_digest"])
        self.assertEqual(doc["x-window"]["digest_mismatch_deals"], doc["x-window"]["deals_counted"])
        self.assertEqual(summary["states"], {deals.MISMATCH: doc["x-window"]["deals_counted"]})

    def test_one_mismatching_record_is_enough(self):
        provider = load("provider")
        self.cite(provider, compiled()["pack_source_digest"])
        one = next(c for c in provider if deals._attestation(c).get(deals.EXCHANGE) is not None)
        deals._attestation(one)[deals.EXCHANGE][deals.PACK_DIGEST_MEMBER] = "1" * 64
        doc, _ = run(provider)
        self.assertEqual(doc["x-window"]["digest_mismatch_deals"], 1)


def deal_capsule_ids(capsules, exchange_id, kind=None):
    """Book ids of a deal's records; kind "obs" or "exch" narrows them."""
    ids = []
    for c in deal_records(capsules, exchange_id):
        is_obs = observation(c) is not None
        if kind is None or (kind == "obs") == is_obs:
            ids.append(c["capsule_id"])
    return ids


class SignaturesVerifiedPerDeal(unittest.TestCase):
    """evidencebook-skills#187: a capsule that does not verify makes its deal
    evidence unavailable for that deal alone, and the run still gives a Result."""

    def test_no_unverified_capsule_changes_nothing(self):
        provider = load("provider")
        plain, _ = run(provider)
        same, _ = deals.build_result(records(provider), compiled(), DATE, GENERATED_AT, None, {})
        self.assertEqual(json.dumps(plain, sort_keys=True), json.dumps(same, sort_keys=True))
        for key in ("unverified_capsules", "signature_unverified_deals", "signer_untrusted_deals"):
            self.assertNotIn(key, plain["x-window"])

    def judged(self, unverified, capsules=None):
        capsules = capsules or load("provider")
        return deals.build_result(records(capsules), compiled(), DATE, GENERATED_AT, None, unverified)

    def test_a_tampered_observation_makes_only_its_deal_unavailable(self):
        provider = load("provider")
        victim = deal_capsule_ids(provider, "p-deal-settled", "obs")[0]
        before, _ = run(provider)
        doc, summary = self.judged({victim: deals.UNVERIFIED})
        self.assertEqual(doc["x-window"]["signature_unverified_deals"], 1)
        self.assertEqual(doc["x-window"]["unverified_capsules"], 1)
        self.assertEqual(summary["states"][deals.UNVERIFIED], 1)
        bad = [c for c in doc["claims"] if c.get("x-reason") == deals.UNVERIFIED]
        self.assertEqual({c["verdict"] for c in bad}, {"not_evaluable"})
        self.assertEqual({tuple(c["x-unverified-capsules"]) for c in bad}, {(victim,)})
        # every other deal is judged exactly as before
        bad_deals = {c["id"].split("::")[0] for c in bad}
        self.assertEqual(len(bad_deals), 1)
        other = [(c["id"], c["verdict"]) for c in doc["claims"] if c["id"].split("::")[0] not in bad_deals]
        expected = [(c["id"], c["verdict"]) for c in before["claims"] if c["id"].split("::")[0] not in bad_deals]
        self.assertEqual(other, expected)
        self.assertTrue(other)

    def test_an_untrusted_signer_is_unavailable_and_not_called_tampered(self):
        provider = load("provider")
        victim = deal_capsule_ids(provider, "p-deal-short", "obs")[0]
        doc, summary = self.judged({victim: deals.UNTRUSTED})
        reasons = {c.get("x-reason") for c in doc["claims"]}
        self.assertIn(deals.UNTRUSTED, reasons)
        self.assertNotIn(deals.UNVERIFIED, reasons)
        self.assertEqual(doc["x-window"]["signer_untrusted_deals"], 1)
        self.assertNotIn("signature_unverified_deals", doc["x-window"])
        self.assertEqual(summary["states"][deals.UNTRUSTED], 1)

    def test_a_mixed_run_counts_each_kind_and_a_deal_with_both_reads_tampered(self):
        provider = load("provider")
        a = deal_capsule_ids(provider, "p-deal-settled", "obs")[0]
        b = deal_capsule_ids(provider, "p-deal-settled", "exch")[0]
        c = deal_capsule_ids(provider, "p-deal-short", "obs")[0]
        doc, summary = self.judged({a: deals.UNTRUSTED, b: deals.UNVERIFIED, c: deals.UNTRUSTED})
        self.assertEqual(doc["x-window"]["signature_unverified_deals"], 1)  # settled: tampered wins
        self.assertEqual(doc["x-window"]["signer_untrusted_deals"], 1)      # short
        self.assertEqual(doc["x-window"]["unverified_capsules"], 3)
        self.assertEqual(summary["states"][deals.UNVERIFIED], 1)
        self.assertEqual(summary["states"][deals.UNTRUSTED], 1)
        self.assertGreater(sum(summary["states"].values()), 2, "the other deals are still judged")

    def test_unverified_wins_over_a_digest_mismatch(self):
        provider = load("provider")
        for cap in provider:
            m = deals._attestation(cap).get(deals.EXCHANGE)
            if m is not None:
                m[deals.PACK_DIGEST_MEMBER] = "0" * 64
        victim = deal_capsule_ids(provider, "p-deal-settled", "obs")[0]
        doc, _ = self.judged({victim: deals.UNVERIFIED}, provider)
        settled = {c.get("x-reason") for c in doc["claims"] if c.get("x-reason") == deals.UNVERIFIED}
        self.assertEqual(settled, {deals.UNVERIFIED})
        self.assertEqual(doc["x-window"]["digest_mismatch_deals"] + 1, doc["x-window"]["deals_counted"])

    def test_a_tampered_payer_record_makes_a_payer_deal_unavailable(self):
        payer = load("payer")
        victim = deal_capsule_ids(payer, "deal-settled", "obs")[0]
        before, _ = run(payer)
        doc, _ = self.judged({victim: deals.UNVERIFIED}, payer)
        paid = [c for c in doc["claims"] if c["id"].endswith("paid_as_agreed")
                and c.get("x-reason") == deals.UNVERIFIED]
        self.assertEqual(len(paid), 1)
        self.assertEqual(paid[0]["verdict"], "not_evaluable")
        bad_deal = paid[0]["id"].split("::")[0]
        self.assertEqual([(c["id"], c["verdict"]) for c in doc["claims"] if not c["id"].startswith(bad_deal)],
                         [(c["id"], c["verdict"]) for c in before["claims"] if not c["id"].startswith(bad_deal)])

    def test_a_tampered_record_never_moves_a_verified_deals_window_or_creates_a_deal(self):
        provider = load("provider")
        before, _ = run(provider)
        ids = deal_capsule_ids(provider, "p-deal-settled", "obs")
        by_id = {c["capsule_id"]: c for c in provider}
        unverified = {}
        # a backdated record, a future one and one with no readable time, all unverified
        by_id[ids[0]]["timestamp"] = "2001-01-01T00:00:00Z"
        by_id[ids[1]]["timestamp"] = "2999-01-01T00:00:00Z"
        by_id[ids[2]].pop("timestamp")
        unverified.update({i: deals.UNVERIFIED for i in ids[:3]})
        # a new exchange id named only by an unverified record: no phantom deal
        phantom = copy.deepcopy(by_id[ids[3]])
        phantom["capsule_id"] = "phantom"
        observation(phantom)["exchange_id"] = "p-deal-phantom"
        provider.append(phantom)
        unverified["phantom"] = deals.UNVERIFIED
        doc, _ = self.judged(unverified, provider)
        self.assertEqual(doc["x-window"]["deals_counted"], before["x-window"]["deals_counted"])
        self.assertEqual(doc["x-window"]["unverified_capsules"], 3)  # the future-dated one is not read
        self.assertEqual(doc["x-window"]["signature_unverified_deals"], 1)

    def test_an_unverified_record_dated_after_the_window_decides_nothing(self):
        provider = load("provider")
        plain, _ = run(provider)
        late = copy.deepcopy(next(c for c in provider if observation(c)
                                  and observation(c).get("exchange_id") == "p-deal-settled"))
        late["capsule_id"], late["timestamp"] = "late", "2999-01-01T00:00:00Z"
        provider.append(late)
        doc, _ = self.judged({"late": deals.UNTRUSTED}, provider)
        self.assertEqual(doc, plain)

    def test_a_malformed_unverified_record_never_stops_the_run(self):
        provider = load("provider")
        provider.append({"capsule_id": "junk1", "model_attestation": [1, 2]})
        provider.append({"capsule_id": "junk2", "model_attestation": {"compute_attestation": "x"}})
        junk3 = copy.deepcopy(next(c for c in provider if any(b in deals._attestation(c)
                                                              for b in deals.ADJUDICATION_BLOCKS)))
        junk3["capsule_id"] = "junk3"
        for block in deals.ADJUDICATION_BLOCKS:
            if block in deals._attestation(junk3):
                deals._attestation(junk3)[block]["halves"] = 5
        provider.append(junk3)
        doc, _ = self.judged({"junk1": deals.UNVERIFIED, "junk2": deals.UNVERIFIED, "junk3": deals.UNVERIFIED},
                             provider)
        self.assertEqual(doc["x-window"]["unverified_capsules"], 3)
        self.assertNotIn("signature_unverified_deals", doc["x-window"])

    def test_a_tampered_record_cannot_exclude_a_deal_as_shop_preauth_or_change_other_grades(self):
        provider = load("provider")
        victim = deal_capsule_ids(provider, "p-deal-short", "obs")[0]
        by_id = {c["capsule_id"]: c for c in provider}
        by_id[victim]["counterparty_class"] = "shop_preauth"
        by_id[victim]["key_id"] = "f" * 64
        trusted, _ = self.judged({}, copy.deepcopy(provider))  # were the forged class believed
        self.assertEqual(trusted["x-window"]["not_counted_shop_preauth"], 1)
        doc, _ = self.judged({victim: deals.UNVERIFIED}, provider)
        plain, _ = run(load("provider"))
        self.assertEqual(doc["x-window"]["not_counted_shop_preauth"], 0)
        self.assertEqual(doc["x-window"]["deals_counted"], plain["x-window"]["deals_counted"])
        # the forged key_id on the unverified record is not one of the node's own keys
        self.assertEqual([(c["id"], c.get("grade")) for c in doc["claims"] if c.get("x-reason") is None],
                         [(c["id"], c.get("grade")) for c in plain["claims"] if not c["id"].startswith("d2::")])

    def test_a_leg_that_does_not_verify_never_makes_a_payment_countersigned(self):
        payer, provider = load("payer"), load("provider")
        named = {c["settlement"]["terms_ref"] for c in provider if "settlement" in c}
        book = provider + [c for c in payer if c["capsule_id"] in named]
        plain, _ = run(book)
        self.assertIn("countersigned", {c.get("grade") for c in plain["claims"]}, "fixture has a countersigned row")
        legs = {c["capsule_id"]: deals.UNVERIFIED for c in book if isinstance(c.get("settlement"), dict)}
        doc, _ = self.judged(legs, book)
        self.assertNotIn("countersigned", {c.get("grade") for c in doc["claims"]})
        self.assertEqual(doc["x-window"]["unverified_capsules"], len(legs))
        self.assertNotIn("signature_unverified_deals", doc["x-window"])

    def test_an_unverified_adjudication_is_not_read_as_adjudicated(self):
        provider = load("provider")
        plain, _ = run(provider)
        self.assertGreater(plain["x-window"]["adjudicated_deals"], 0, "fixture has an adjudicated deal")
        adjudications = {c["capsule_id"]: deals.UNVERIFIED for c in provider
                         if any(b in deals._attestation(c) for b in deals.ADJUDICATION_BLOCKS)}
        doc, _ = self.judged(adjudications)
        self.assertEqual(doc["x-window"]["adjudicated_deals"], 0)
        self.assertGreaterEqual(doc["x-window"]["signature_unverified_deals"], 1)


FAKE_CAPSULECTL = r'''#!/usr/bin/env python3
"""A capsulectl that serves one book from $FAKE_BOOK: {"records": [...], "verify": {capsule_id: mode}}.
Messages are the ones capsule-cli prints (cli/command.go, cli/verify_capsule.go)."""
import json, os, pathlib, sys
book = json.load(open(os.environ["FAKE_BOOK"]))
by_id = {r["capsule_id"]: r for r in book["records"]}
a = sys.argv[1:]
def opt(name):
    return a[a.index(name) + 1]
if a[:2] == ["cll", "list"]:
    after = int(opt("--after"))
    entries = [{"capsule_id": r["capsule_id"]} for r in book["records"][after:]]
    print(json.dumps({"entries": entries, "next_after": len(book["records"])}))
elif a[0] == "get" and "--raw" in a:
    cid = opt("--capsule-id")
    if book["verify"].get(cid) == "get_fails":
        print("boom", file=sys.stderr); sys.exit(1)
    pathlib.Path(opt("--output")).write_text(json.dumps(by_id[cid]))
elif a[0] == "get":
    print(json.dumps({"artifacts": [{"name": "payload", "content": by_id[opt("--capsule-id")]}]}))
elif a[0] == "verify":
    cid = pathlib.Path(opt("--capsule")).stem
    mode = book["verify"].get(cid, "ok")
    if mode == "ok":
        print(json.dumps({"producer_signature_and_trust": "passed"}))
    elif mode == "bad":
        print(json.dumps({"producer_signature": "failed"}))
        print("capsule verification failed: the signature does not verify under the capsule's key_id", file=sys.stderr); sys.exit(1)
    elif mode == "untrusted_bare":
        print("capsule verification failed: the signature verifies, but its key_id is not among the profile's trusted keys", file=sys.stderr); sys.exit(1)
    elif mode == "untrusted_record":
        print("producer is not authorized by the profile trusted_keys", file=sys.stderr); sys.exit(1)
    elif mode == "crash":
        print("operation failed; check input, selected profile, permissions and service availability (sensitive details suppressed)", file=sys.stderr); sys.exit(1)
    elif mode == "no_trusted_key":
        print(json.dumps({"producer_signature": "passed", "producer_trust": "not_performed: no trusted key"})); sys.exit(3)
'''


class ReadBookVerifiesEveryCapsule(unittest.TestCase):
    """read_book and main against a fake capsulectl: the verdicts above come
    from `capsulectl verify`, and one bad capsule never costs the whole run."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = pathlib.Path(self.tmp.name)
        self.ctl = d / "capsulectl"
        self.ctl.write_text(FAKE_CAPSULECTL)
        self.ctl.chmod(0o755)
        self.book = d / "book.json"
        self.provider = load("provider")

    def start(self, verify):
        self.book.write_text(json.dumps({"records": self.provider, "verify": verify}))
        os.environ["FAKE_BOOK"] = str(self.book)
        self.addCleanup(os.environ.pop, "FAKE_BOOK", None)

    def read(self, verify):
        self.start(verify)
        return deals.read_book(str(self.ctl), "p")

    def test_every_capsule_verified_gives_no_unverified(self):
        records_, unverified = self.read({})
        self.assertEqual(len(records_), len(self.provider))
        self.assertEqual(unverified, {})

    def test_each_failure_is_classified(self):
        ids = deal_capsule_ids(self.provider, "p-deal-settled", "obs")
        _, unverified = self.read({ids[0]: "bad", ids[1]: "untrusted_bare", ids[2]: "untrusted_record",
                                   ids[3]: "no_trusted_key"})
        self.assertEqual(unverified, {ids[0]: deals.UNVERIFIED, ids[1]: deals.UNTRUSTED,
                                      ids[2]: deals.UNTRUSTED, ids[3]: deals.UNTRUSTED})

    def test_a_record_that_is_no_mesh_capsule_is_not_verified(self):
        self.provider.append({"capsule_id": "other", "kind": "a sealed Result"})
        _, unverified = self.read({"other": "bad"})
        self.assertEqual(unverified, {})

    def test_a_capsulectl_that_cannot_get_a_capsule_stops_the_run(self):
        victim = deal_capsule_ids(self.provider, "p-deal-settled", "obs")[0]
        with self.assertRaises(deals.EvidenceUnavailable):
            self.read({victim: "get_fails"})

    def run_main(self, verify):
        self.start(verify)
        out = pathlib.Path(self.tmp.name) / "out"
        proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "evaluators" / "inference_deals.py"),
                               "--profile", "p", "--spec", str(COMPILED), "--capsulectl", str(self.ctl),
                               "--date", "2026-11-01", "--generated-at", GENERATED_AT, "--out", str(out),
                               "--now", "2026-12-01T00:00:00Z"],
                              capture_output=True, text=True, env={**os.environ, "FAKE_BOOK": str(self.book)})
        return proc, out

    def test_a_run_with_one_tampered_and_one_untrusted_capsule_still_gives_a_result(self):
        a = deal_capsule_ids(self.provider, "p-deal-settled", "obs")[0]
        b = deal_capsule_ids(self.provider, "p-deal-short", "obs")[0]
        proc, out = self.run_main({a: "bad", b: "untrusted_bare"})
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        summary = json.loads(proc.stdout)
        self.assertEqual(summary["window"]["signature_unverified_deals"], 1)
        self.assertEqual(summary["window"]["signer_untrusted_deals"], 1)
        self.assertEqual(summary["window"]["unverified_capsules"], 2)
        self.assertTrue(list(out.glob("result-v0-*.json")))

    def test_a_run_with_everything_verified_is_the_unverified_free_result(self):
        proc, _ = self.run_main({})
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn("unverified_capsules", json.loads(proc.stdout)["window"])

    def test_a_malformed_capsule_that_does_not_verify_is_set_aside_and_one_that_does_stops_nothing_new(self):
        junk = {"capsule_id": "junk", "model_attestation": [1, 2]}
        self.provider.append(junk)
        proc, _ = self.run_main({"junk": "bad"})
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["window"]["unverified_capsules"], 1)

    def test_a_verify_that_gives_no_verdict_is_a_tool_failure_not_a_finding(self):
        victim = deal_capsule_ids(self.provider, "p-deal-settled", "obs")[0]
        proc, _ = self.run_main({victim: "crash"})
        self.assertEqual(proc.returncode, 2)
        self.assertIn("no verdict", json.loads(proc.stdout)["error"])

    def test_a_capsulectl_that_cannot_get_one_exits_2(self):
        victim = deal_capsule_ids(self.provider, "p-deal-settled", "obs")[0]
        proc, _ = self.run_main({victim: "get_fails"})
        self.assertEqual(proc.returncode, 2)
        self.assertIn("error", json.loads(proc.stdout))


class ReportShFlags(unittest.TestCase):
    def report_sh(self, *args):
        return subprocess.run(["bash", str(ROOT / "scripts" / "report.sh"), "--profile", "p",
                               "--out", "/dev/null", "--capsulectl", "/bin/false", *args],
                              capture_output=True, text=True,
                              env={**os.environ, "PATH": f"{pathlib.Path(sys.executable).parent}:{os.environ['PATH']}"})

    def test_to_is_refused_for_a_deterministic_pack(self):
        proc = self.report_sh("--spec", str(COMPILED), "--date", "2026-10-01", "--to", "2026-10-31")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("--to does not apply to a deterministic pack", proc.stderr)

    def test_window_flags_are_refused_for_any_other_spec(self):
        spec = ROOT / "scripts" / "specs" / "tau2-airline-no-judge.yaml"
        for flag, value in (("--period-policy", "/dev/null"), ("--now", "2026-11-02T00:00:00Z")):
            proc = self.report_sh("--spec", str(spec), "--date", "2026-10-01", flag, value)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("apply only to a deterministic pack", proc.stderr)


class EvaluatorRefusesAnOpenPeriod(unittest.TestCase):
    def test_an_anchor_after_now_is_refused(self):
        proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "evaluators" / "inference_deals.py"),
                               "--profile", "p", "--spec", str(COMPILED), "--capsulectl", "/bin/false",
                               "--date", "2026-11-01", "--generated-at", GENERATED_AT, "--out", "/dev/null",
                               "--now", "2026-11-01T12:00:00Z"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("that period has not closed", proc.stdout)


if __name__ == "__main__":
    unittest.main()
