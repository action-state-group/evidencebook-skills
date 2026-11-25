"""`scope.kind: admission` pack sources (scripts/admission_pack.py, admission
pack profile v0): the baseline pack and its fixtures, the design rules the lint
holds, and the Evidence Contract an admission pack compiles to. The fixtures'
expected decisions are checked against the evaluator in capsule-engine#265's
CI; here they are checked for shape and against the pack.
"""
import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import rfc8785  # noqa: E402
import yaml  # noqa: E402

import admission_pack  # noqa: E402
import evidence_contract as ec  # noqa: E402
import pack_compile  # noqa: E402

try:
    import jsonschema
except ImportError:
    jsonschema = None

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
BASELINE = REPO_ROOT / "packs/admission-baseline"
SCHEMA = REPO_ROOT / "tests/fixtures/capsule-engine/evidence-contract-v0.json"

INPUT_KEYS = {"now", "amount", "currency", "platform", "card", "selection", "own", "operator", "vouches",
              "subject", "judged", "asks", "asks_made", "stake"}


def baseline_text():
    return (BASELINE / "pack-source.yaml").read_text()


def load(text):
    return pack_compile.load_source(text)


RAIL_DIGEST = "5" * 64
LADDER_PARAMS = "    params: {k: 3, step_decades: 1, max_adverse_permille: 50}"
LADDER_ROW = f"""  - id: ladder
    statement: The card earns this deal's band, or collateral on a pinned rail covers it.
    source: card
    check: card.band_history_or_stake
{LADDER_PARAMS}
    from: T1
    on_fail: "LIMIT"
    ask: {{derivation: served_summary/1}}
"""


def ladder_text():
    """The baseline with a rail pinned and a ladder row: profile §2's
    card.band_history_or_stake, which the baseline itself does not use yet."""
    text = baseline_text().replace("  judges: [placeholder-judge]\n",
                                   f"  judges: [placeholder-judge]\n  rails: [{{id: x402-v0, digest: \"{RAIL_DIGEST}\"}}]\n")
    return text.replace("rows:\n", "rows:\n" + LADDER_ROW, 1)


class Ladder(unittest.TestCase):
    """The per-band ladder and rails in trust_roots (#79)."""

    def test_validates(self):
        self.assertEqual(pack_compile.validate_source(load(ladder_text())), [])

    def test_rails_are_compiled(self):
        doc = admission_pack.compile_pack(load(ladder_text()))
        self.assertEqual(doc["trust_roots"]["rails"], [{"id": "x402-v0", "digest": RAIL_DIGEST}])
        row = next(r for r in doc["rows"] if r["id"] == "ladder")
        self.assertEqual(row["params"], {"k": 3, "step_decades": 1, "max_adverse_permille": 50})

    def test_a_pack_that_pins_no_rail_keeps_its_bytes(self):
        # rails is written only when a rail is pinned, so the baseline compiles
        # to the bytes it did before rails existed, and its pin still holds.
        self.assertNotIn("rails", admission_pack.compile_pack(load(baseline_text()))["trust_roots"])
        empty = baseline_text().replace("  judges: [placeholder-judge]\n", "  judges: [placeholder-judge]\n  rails: []\n")
        self.assertEqual(admission_pack.compiled_bytes(load(empty)), admission_pack.compiled_bytes(load(baseline_text())))

    def test_open_disputes_beside_the_ladder(self):
        row = """  - id: open-disputes-limit
    statement: The card shows at most one open dispute raised about the counterparty.
    source: card
    check: card.open_disputes
    params: {max: 1}
    from: T1
    on_fail: "LIMIT"
"""
        text = ladder_text().replace("rows:\n", "rows:\n" + row, 1)
        self.assertEqual(pack_compile.validate_source(load(text)), [])
        issues = pack_compile.validate_source(load(text.replace("params: {max: 1}", "params: {}")))
        self.assertTrue(any("needs params.max" in i for i in issues), issues)
        issues = pack_compile.validate_source(load(text.replace(
            "check: card.open_disputes\n    params: {max: 1}\n    from: T1\n    on_fail: \"LIMIT\"",
            "check: card.open_disputes\n    params: {max: 1}\n    from: T1\n    on_fail: \"NO\"")))
        self.assertTrue(any("a card row may not decide NO" in i for i in issues), issues)

    def test_disputes_against_with_on_unread(self):
        # #280: a shown loss limits; a card with no dispute tally is recorded.
        row = """  - id: disputes-against-test
    statement: The counterparty's card shows no dispute about it decided against it, out of the disputes decided.
    source: card
    check: card.disputes_against
    params: {max: 0}
    from: T1
    on_fail: "LIMIT"
    on_unread: "record"
"""
        text = baseline_text().replace("rows:\n", "rows:\n" + row, 1)
        self.assertEqual(pack_compile.validate_source(load(text)), [])
        compiled = admission_pack.compile_pack(load(text))
        got = next(r for r in compiled["rows"] if r["id"] == "disputes-against-test")
        self.assertEqual(got["on_unread"], "record")
        # Written only when set, so every other row keeps its bytes.
        self.assertNotIn("on_unread", next(r for r in compiled["rows"] if r["id"] == "card-verified"))
        rule = next(q for q in admission_pack.from_admission(load(text))["requirements"]
                    if q["id"] == "disputes-against-test")
        self.assertIn("carries no dispute tally, recorded", json.dumps(rule))

        def issues_for(old, new):
            return pack_compile.validate_source(load(text.replace(old, new, 1)))

        issues = issues_for('on_unread: "record"', 'on_unread: "LIMIT"')
        self.assertTrue(any("on_unread must be \"record\"" in i for i in issues), issues)
        issues = issues_for('on_fail: "LIMIT"\n    on_unread', 'on_fail: "record"\n    on_unread')
        self.assertTrue(any("only a LIMIT row may carry on_unread" in i for i in issues), issues)
        issues = issues_for('on_unread: "record"\n', 'on_unread: "record"\n    ask: {derivation: standard_history/1}\n')
        self.assertTrue(any("a row with on_unread carries no ask" in i for i in issues), issues)
        issues = issues_for("params: {max: 0}", "params: {}")
        self.assertTrue(any("needs params.max" in i for i in issues), issues)
        # Only the lost-disputes row may carry it: an unwitnessed, stale or
        # missing card must still limit.
        old = """    check: card.witnessed
    from: T1
    on_fail: "LIMIT"
"""
        self.assertIn(old, baseline_text())
        witnessed = baseline_text().replace(old, old + '    on_unread: "record"\n', 1)
        issues = pack_compile.validate_source(load(witnessed))
        self.assertTrue(any("only a card.disputes_against row may carry on_unread" in i for i in issues), issues)

    def test_not_stapled_row_asks_above_t0(self):
        # A stapled card decides T0 only (capsule-engine#277).
        row = """  - id: card-asked
    statement: The card was asked for, not stapled to the holder's message.
    source: card
    check: card.not_stapled
    from: T1
    on_fail: "LIMIT"
    ask: {derivation: history_card/1}
"""
        text = ladder_text().replace("rows:\n", "rows:\n" + row, 1)
        self.assertEqual(pack_compile.validate_source(load(text)), [])
        issues = pack_compile.validate_source(load(text.replace(
            "check: card.not_stapled\n", "check: card.not_stapled\n    params: {max: 1}\n", 1)))
        self.assertTrue(any("check card.not_stapled takes no params.max" in i for i in issues), issues)
        self.assertTrue(issues, issues)

    def test_pin_and_witness_label_rows(self):
        # Witness label, log key, first-use pin and dropped streams (capsule-engine#304).
        for check in ("card.witness_label", "card.log_key_accepted", "card.not_behind_pin",
                      "card.no_dropped_stream"):
            row = f"""  - id: r-{check.split('.')[1].replace('_', '-')}
    statement: A card row.
    source: card
    check: {check}
    from: T1
    on_fail: "LIMIT"
"""
            text = ladder_text().replace("rows:\n", "rows:\n" + row, 1)
            self.assertEqual(pack_compile.validate_source(load(text)), [], check)
            issues = pack_compile.validate_source(load(text.replace(
                f"check: {check}\n", f"check: {check}\n    params: {{max: 1}}\n", 1)))
            self.assertTrue(any(f"check {check} takes no params.max" in i for i in issues), (check, issues))
            issues = pack_compile.validate_source(load(text.replace('on_fail: "LIMIT"', 'on_fail: "NO"', 1)))
            self.assertTrue(any("a card row may not decide NO" in i for i in issues), (check, issues))

    def test_self_reported_served_periods(self):
        # A Mesh node's inference-service-history/0 card (capsule-engine#273).
        row = """  - id: served-periods
    statement: The node's own counts show served exchanges in at least 3 of the last 4 weeks.
    source: card
    check: card.self_reported_served_periods
    params: {window: 4, min_periods: 3}
    from: T1
    on_fail: "LIMIT"
"""
        text = ladder_text().replace("rows:\n", "rows:\n" + row, 1)
        self.assertEqual(pack_compile.validate_source(load(text)), [])
        for params, want in [("{window: 4}", "needs params.min_periods"),
                             ("{window: 4, min_periods: 5}", "params.min_periods must be at most params.window"),
                             ("{window: 0, min_periods: 0}", "params.window 0 must be from 1 to 10000"),
                             ("{window: 4, min_periods: 0}", "params.min_periods 0 must be from 1 to 10000"),
                             ("{window: 10001, min_periods: 1}", "params.window 10001 must be from 1 to 10000")]:
            issues = pack_compile.validate_source(load(text.replace("{window: 4, min_periods: 3}", params)))
            self.assertTrue(any(want in i for i in issues), (params, issues))
        issues = pack_compile.validate_source(load(text.replace(
            "params: {window: 4, min_periods: 3}\n    from: T1\n    on_fail: \"LIMIT\"",
            "params: {window: 4, min_periods: 3}\n    from: T1\n    on_fail: \"NO\"")))
        self.assertTrue(any("a card row may not decide NO" in i for i in issues), issues)

    def test_referee_verdicts_and_witness_receipts(self):
        # The units of a Mesh node's card beside its served periods
        # (capsule-engine#276).
        rows = """  - id: referee-verdicts
    statement: The node's own counts show referee verdicts in at least 2 of the last 4 weeks.
    source: card
    check: card.referee_verdicts
    params: {window: 4, min_periods: 2}
    from: T1
    on_fail: "LIMIT"
  - id: witness-receipts
    statement: The verifier counted at least one witness receipt.
    source: card
    check: card.witness_receipts
    params: {min: 1}
    from: T1
    on_fail: "LIMIT"
"""
        text = ladder_text().replace("rows:\n", "rows:\n" + rows, 1)
        self.assertEqual(pack_compile.validate_source(load(text)), [])
        for old, new, want in [("{window: 4, min_periods: 2}", "{window: 1, min_periods: 2}",
                                "params.min_periods must be at most params.window"),
                               ("{window: 4, min_periods: 2}", "{window: 4}", "needs params.min_periods"),
                               ("params: {min: 1}\n    from: T1\n    on_fail: \"LIMIT\"\n  - id: ladder",
                                "params: {window: 4}\n    from: T1\n    on_fail: \"LIMIT\"\n  - id: ladder",
                                "takes no params.window")]:
            issues = pack_compile.validate_source(load(text.replace(old, new, 1)))
            self.assertTrue(any(want in i for i in issues), (new, issues))

    def test_the_baseline_has_no_ladder_yet(self):
        # No served card carries per-band counts of corroborated, net-settled
        # subjects yet (profile §6).
        checks = {r["check"] for r in load(baseline_text())["rows"]}
        self.assertNotIn("card.band_history_or_stake", checks)


class Baseline(unittest.TestCase):
    def test_validates(self):
        self.assertEqual(pack_compile.validate_source(load(baseline_text())), [])

    def test_every_number_is_a_placeholder(self):
        # #51's added acceptance: every amount is marked as a placeholder.
        for line in baseline_text().splitlines():
            if any(k in line for k in ("max_decade:", "max_asks:", "deadline_s:", "params:")):
                self.assertIn("placeholder", line, line)

    def test_stake_is_a_recorded_source_only(self):
        rows = [r for r in load(baseline_text())["rows"] if r["source"] == "stake"]
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual(r["on_fail"], "record")
            self.assertEqual(set(r), {"id", "statement", "source", "check", "from", "on_fail"})
        roots = load(baseline_text())["trust_roots"]
        self.assertNotIn("stake", roots)

    def test_not_the_mesh_default(self):
        # u137: a Mesh pack keeps own_history from deciding NO. The baseline
        # does let it, so it says it is not the Mesh default.
        self.assertIn("Not the Mesh default", baseline_text())

    def test_the_climb_rests_on_the_counterpartys_evidence(self):
        # Design §4: our own book gates no tier above T0; the card gates T1
        # and the bound selection T2.
        rows = load(baseline_text())["rows"]
        gating = {r["source"] for r in rows if r["from"] != "T0" and r.get("on_fail") == "LIMIT"}
        self.assertLessEqual(gating, {"card", "bound", "own_history"})
        own_gates = [r["id"] for r in rows if r["source"] == "own_history" and r.get("on_fail") == "LIMIT"]
        self.assertEqual(own_gates, ["no-conflicting-deal"])

    def test_compiles_to_a_contract(self):
        contract = ec.from_pack(load(baseline_text()))
        self.assertEqual(ec.contract_ref(contract), "asg/admission_baseline/1.1.0@1.1.0")
        self.assertEqual([r["id"] for r in contract["requirements"]],
                         [r["id"] for r in load(baseline_text())["rows"]])
        judged = [r for r in contract["requirements"] if r["id"] == "adjacent-domain"]
        self.assertEqual(judged[0]["backward_verdict"], "MODEL-ASSISTED")
        if jsonschema is not None:
            jsonschema.validate(contract, json.loads(SCHEMA.read_text()))

    def test_compile_writes_the_contract_and_the_pinned_artifact(self):
        with tempfile.TemporaryDirectory(dir=REPO_ROOT / "packs") as tmp:
            out = pathlib.Path(tmp).relative_to(REPO_ROOT)
            run = subprocess.run([sys.executable, "scripts/pack_compile.py", "compile",
                                  str(BASELINE / "pack-source.yaml"), "--out", str(out)],
                                 cwd=REPO_ROOT, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            answer = json.loads(run.stdout)
            self.assertEqual(answer["scope"], "admission")
            self.assertEqual(sorted(p.name for p in pathlib.Path(tmp).iterdir()), ["contract.json", "pack-definition.json"])
            pinned = (pathlib.Path(tmp) / "pack-definition.json").read_bytes()
            self.assertEqual(hashlib.sha256(pinned).hexdigest(), answer["definition_digest"])

    def test_the_committed_artifact_is_the_compiled_source(self):
        # packs/admission-baseline/compiled/ is what a consumer pins and copies;
        # it must be exactly what the source compiles to.
        source = load(baseline_text())
        self.assertEqual((BASELINE / "compiled/pack-definition.json").read_bytes(), admission_pack.compiled_bytes(source))
        self.assertEqual((BASELINE / "compiled/contract.json").read_bytes(), ec.to_bytes(admission_pack.from_admission(source)))

    def test_the_artifact_is_jcs_and_complete(self):
        pinned = admission_pack.compiled_bytes(load(baseline_text()))
        doc = json.loads(pinned)
        self.assertEqual(rfc8785.dumps(doc), pinned)
        self.assertEqual(doc["format"], "admission-pack/v0")
        self.assertEqual(set(doc["trust_roots"]), {"controllers", "witnesses", "judges"})
        self.assertTrue(all("params" in r for r in doc["rows"]))

class NodeBaseline(unittest.TestCase):
    NODE = REPO_ROOT / "packs/admission-node-baseline"

    def test_the_committed_artifact_is_the_compiled_source(self):
        source = load((self.NODE / "pack-source.yaml").read_text())
        self.assertEqual(pack_compile.validate_source(source), [])
        self.assertEqual((self.NODE / "compiled/pack-definition.json").read_bytes(), admission_pack.compiled_bytes(source))
        self.assertEqual((self.NODE / "compiled/contract.json").read_bytes(), ec.to_bytes(admission_pack.from_admission(source)))


MUSE = REPO_ROOT / "packs/admission-muse-buyer"


def muse_text():
    return (MUSE / "pack-source.yaml").read_text()


def reference_decide(pack, inp):
    """A small reading of profile section 4, for the predicates and the USD
    band the Muse buyer pack uses, so its fixtures are checked against the
    lift of section 4.1 and not only for shape. capsule-engine is the real
    evaluator; this is the reference the lift is specified by."""
    from datetime import datetime, timedelta
    parse = lambda t: datetime.fromisoformat(t.replace("Z", "+00:00"))
    now, tiers = parse(inp["now"]), [t["id"] for t in pack["tiers"]]
    whole, _, frac = inp["amount"].partition(".")
    if whole.strip("0"):
        decade = len(whole.lstrip("0")) - 1
    else:
        decade = -(len(frac) - len(frac.lstrip("0")) + 1)
    unit = pack["accept"][inp["currency"]]
    decade += unit["scale"]
    deal = next((i for i, t in enumerate(pack["tiers"]) if unit["band"] in t["max_decade"]
                 and decade <= t["max_decade"][unit["band"]]), len(tiers))  # len(tiers): above the unit's top tier
    top = max(i for i, t in enumerate(pack["tiers"]) if unit["band"] in t["max_decade"])
    own, card, op = inp["own"], inp["card"], inp["operator"]
    roots = pack["trust_roots"]
    MISSING = "missing"
    # Rows that read not_read because a verified card carries no dispute
    # tally (profile section 3.3, reason no_dispute_tally).
    no_tally = set()

    def read(r):
        p = r.get("params") or {}
        c = r["check"]
        if c.startswith("own.") and own is None:
            return MISSING
        if c == "own.settled":
            return "pass" if own["settled"] >= p["min"] else "fail"
        if c == "own.held_halves":
            return "pass" if own["held_halves"] >= p["min"] else "fail"
        if c == "own.no_conflicting":
            return "pass" if own["conflicting"] == 0 else "fail"
        if c == "own.no_adverse_adjudication":
            if not own["verdicts"]:
                return "not_read"
            recent = [v for v in own["verdicts"] if now - parse(v["at"]) <= timedelta(days=p["window_days"])]
            return "fail" if any(v["adverse"] for v in recent) else "pass"
        if c == "operator.not_deny_listed":
            return "fail" if op["deny_listed"] else "pass"
        if c == "operator.allow_listed":
            return "fail" if op.get("allow_listed") is False else "pass"
        if c.startswith("card."):
            if card.get("state") != "verified" and card.get("state") != "unverifiable":
                return "not_read"
            if c == "card.verified":
                return "pass" if card["state"] == "verified" else "fail"
            if card["state"] != "verified":
                return "not_read"
            if c == "card.fresh":
                age = (now - parse(card["latest_checkpoint_at"])).total_seconds()
                return "pass" if 0 <= age <= p["max_age_s"] else "fail"  # not after now (profile section 2)
            if c == "card.witnessed":
                return "pass" if card.get("witness") in roots["witnesses"] else "fail"
            if c == "card.claims_held":
                return "pass" if card["claims"]["held"] >= p["min"] else "fail"
            if c == "card.controller_declared":
                return "pass" if card.get("controller") else "fail"
            if c == "card.open_disputes":
                d = card.get("disputes")
                return "not_read" if d is None else ("pass" if d["open"] <= p["max"] else "fail")
            if c == "card.disputes_against":
                decided = (card.get("disputes") or {}).get("decided")
                if decided is None:
                    no_tally.add(r["id"])
                    return "not_read"
                return "pass" if decided["against"] <= p["max"] else "fail"
        return "not_read"  # selection, vouch, stake, judged rows: none are in these cases

    used = [r for r in pack["rows"] if tiers.index(r["from"]) <= min(deal, top)]
    res = {r["id"]: read(r) for r in used}
    for r in used:
        if r["on_fail"] == "NO" and res[r["id"]] == "fail":
            return "NO", r["id"], None
    for r in used:
        if r["on_fail"] == "NO" and res[r["id"]] == MISSING:
            return pack["missing"], r["id"], "T0"
    res = {k: ("not_read" if v == MISSING else v) for k, v in res.items()}
    # Section 4.1: nothing served, and a lifting row passes with no unless_fail row failing.
    lifted = set()
    for r in used:
        lift = r.get("lift")
        if not lift or res[r["id"]] != "pass" or deal > tiers.index(lift["tier"]):
            continue
        if any(res.get(x) == "fail" for x in lift["unless_fail"]):
            continue
        cards = [x for x in pack["rows"] if x["source"] == "card" and tiers.index(x["from"]) <= tiers.index(lift["tier"])]
        if all(res.get(x["id"], "not_read") == "not_read" for x in cards):
            lifted |= {x["id"] for x in cards}
    admitted, unmet = min(deal, top), []
    for r in used:
        if r.get("on_unread") == "record" and r["id"] in no_tally:
            continue  # section 4, step 4: recorded, lowering nothing
        if r["on_fail"] == "LIMIT" and res[r["id"]] != "pass" and r["id"] not in lifted:
            admitted = min(admitted, tiers.index(r["from"]) - 1)
            unmet.append(r)
    if admitted >= deal:
        return "GO", "rows", tiers[admitted]
    if deal == len(tiers) and admitted == top:
        return pack["missing"], "above_tier", tiers[admitted]
    asked = set(inp["asks"])
    if any(r.get("ask") and r["ask"]["derivation"] not in asked for r in unmet) \
            and inp["asks_made"] < pack["budget"]["max_asks"]:
        return "ASK", "rows", tiers[admitted]
    return "LIMIT", "rows", tiers[admitted]


class MuseBuyer(unittest.TestCase):
    """admission-muse-buyer@1 (#154): the baseline without platform rows, plus
    Steven's narrow own-settled lift (profile section 4.1)."""

    def setUp(self):
        self.pack = load(muse_text())

    def test_validates(self):
        self.assertEqual(pack_compile.validate_source(self.pack), [])

    def test_the_committed_artifact_is_the_compiled_source(self):
        self.assertEqual((MUSE / "compiled/pack-definition.json").read_bytes(), admission_pack.compiled_bytes(self.pack))
        self.assertEqual((MUSE / "compiled/contract.json").read_bytes(), ec.to_bytes(admission_pack.from_admission(self.pack)))

    def test_no_platform_rows(self):
        # Muse reads no release attestation: a platform row there would LIMIT every offer.
        self.assertNotIn("platform", {r["source"] for r in self.pack["rows"]})

    def test_the_lift_is_steven_ruling_narrow(self):
        row = next(r for r in self.pack["rows"] if "lift" in r)
        self.assertEqual(row["check"], "own.settled")
        self.assertEqual(row["params"], {"min": 3})
        self.assertEqual(row["lift"]["tier"], "T1")
        self.assertEqual(set(row["lift"]["unless_fail"]), {"adverse-adjudication", "no-conflicting-deal"})
        # T1 is the tier under $10.
        t1 = next(t for t in self.pack["tiers"] if t["id"] == "T1")
        self.assertEqual(t1["max_decade"]["USD"], 0)

    def test_the_baseline_bytes_are_unchanged_by_the_lift_field(self):
        base = load(baseline_text())
        self.assertNotIn(b'"lift"', admission_pack.compiled_bytes(base))
        self.assertIn(b'"lift"', admission_pack.compiled_bytes(self.pack))

    def test_fixtures_match_the_reference_reading(self):
        doc = json.loads((MUSE / "fixtures/cases.json").read_text())
        self.assertEqual(doc["pack"], self.pack["pack_id"])
        for c in doc["cases"]:
            verdict, source, tier = reference_decide(self.pack, c["input"])
            e = c["expected"]
            self.assertEqual((verdict, source, tier), (e["verdict"], e["source"], e["tier"]), c["case"])

    def test_every_case_input_is_well_formed(self):
        doc = json.loads((MUSE / "fixtures/cases.json").read_text())
        names = [c["case"] for c in doc["cases"]]
        self.assertEqual(len(names), len(set(names)))
        for c in doc["cases"]:
            self.assertLessEqual(set(c["input"]), INPUT_KEYS, c["case"])

    def assertRefused(self, old, new, want):
        issues = pack_compile.validate_source(load(muse_text().replace(old, new, 1)))
        self.assertTrue(any(want in i for i in issues), issues)

    def test_lift_on_a_row_that_is_not_own_settled(self):
        self.assertRefused("    check: own.held_halves\n", "    check: own.held_halves\n    lift: {tier: T1, unless_fail: [deny-list]}\n",
                           "only an own.settled row may lift")

    def test_lift_on_a_deciding_row(self):
        text = muse_text().replace('    on_fail: "record"\n    lift:', '    on_fail: "LIMIT"\n    lift:', 1)
        self.assertTrue(any("must be \"record\"" in i for i in pack_compile.validate_source(load(text))))

    def test_lift_unless_fail_must_name_own_history_rows(self):
        self.assertRefused("unless_fail: [adverse-adjudication, no-conflicting-deal]",
                           "unless_fail: [deny-list]", "must be an own_history row")
        self.assertRefused("unless_fail: [adverse-adjudication, no-conflicting-deal]",
                           "unless_fail: [nope]", "which is no row")
        self.assertRefused("unless_fail: [adverse-adjudication, no-conflicting-deal]",
                           "unless_fail: []", "non-empty list")
        self.assertRefused("unless_fail: [adverse-adjudication, no-conflicting-deal]",
                           "unless_fail: [own-settled]", "the lifting row itself")

    def test_lift_needs_a_card_verified_row(self):
        text = muse_text()
        a = text.index("  - id: card-verified")
        b = text.index("  - id: card-fresh")
        issues = pack_compile.validate_source(load(text[:a] + text[b:]))
        self.assertTrue(any("needs a card.verified row" in i for i in issues), issues)

    def test_the_card_verified_row_is_read_wherever_a_card_row_is(self):
        # Moving card.verified above card-fresh's tier leaves T1 reading a card row with no verification.
        text = muse_text()
        a = text.index("  - id: card-verified")
        b = text.index("  - id: card-fresh")
        row = text[a:b].replace("from: T1", "from: T2")
        issues = pack_compile.validate_source(load(text[:a] + text[b:] + "\n" + row.rstrip("\n") + "\n"))
        self.assertTrue(any("needs a card.verified row" in i for i in issues), issues)

    def test_unless_fail_row_above_the_lift_tier(self):
        self.assertRefused("unless_fail: [adverse-adjudication, no-conflicting-deal]",
                           "unless_fail: [adverse-adjudication, no-conflicting-deal, late]", "which is no row")
        text = muse_text().replace("  - id: selection\n", "  - id: late\n    statement: Late.\n    source: own_history\n"
                                   "    check: own.no_conflicting\n    from: T2\n    on_fail: \"record\"\n  - id: selection\n", 1)
        text = text.replace("unless_fail: [adverse-adjudication, no-conflicting-deal]",
                            "unless_fail: [adverse-adjudication, no-conflicting-deal, late]", 1)
        issues = pack_compile.validate_source(load(text))
        self.assertTrue(any("above the lift tier" in i for i in issues), issues)

    def test_sat_ceilings_hold_the_lift_under_ten_dollars(self):
        # Sherlock2 on #168: the baseline's sat ceilings (T1 up to 99,999 sat) would reach about $60-100.
        ceilings = {t["id"]: t["max_decade"] for t in self.pack["tiers"]}
        self.assertEqual(ceilings["T1"]["sat"], 3)
        self.assertEqual(ceilings["T0"]["sat"], 2)

    def test_lift_tier_must_be_a_tier(self):
        self.assertRefused("lift: {tier: T1,", "lift: {tier: T9,", "is not a tier")

    def test_lift_has_exactly_its_two_fields(self):
        self.assertRefused("lift: {tier: T1, unless_fail", "lift: {tier: T1, also: [x], unless_fail", "must be exactly")


class Fixtures(unittest.TestCase):
    def setUp(self):
        self.doc = json.loads((BASELINE / "fixtures/cases.json").read_text())
        self.pack = load(baseline_text())

    def test_name_the_pack(self):
        self.assertEqual(self.doc["pack"], self.pack["pack_id"])

    def test_cases_are_well_formed(self):
        tiers = {t["id"] for t in self.pack["tiers"]}
        rows = {r["id"] for r in self.pack["rows"]}
        names = [c["case"] for c in self.doc["cases"]]
        self.assertEqual(len(names), len(set(names)))
        for c in self.doc["cases"]:
            self.assertLessEqual(set(c["input"]), INPUT_KEYS, c["case"])
            e = c["expected"]
            self.assertIn(e["verdict"], self.pack["outcomes"], c["case"])
            self.assertIn(e["source"], rows | {"rows", "above_tier", "missing"}, c["case"])
            if e["verdict"] == "NO":
                self.assertIsNone(e["tier"], c["case"])
            else:
                self.assertIn(e["tier"], tiers, c["case"])

    def test_every_outcome_is_exercised(self):
        self.assertEqual({c["expected"]["verdict"] for c in self.doc["cases"]}, set(self.pack["outcomes"]))

    def test_no_comes_only_from_rows_that_may_decide_it(self):
        sources = {r["id"]: r["source"] for r in self.pack["rows"]}
        for c in self.doc["cases"]:
            if c["expected"]["verdict"] == "NO" and c["expected"]["source"] in sources:
                self.assertIn(sources[c["expected"]["source"]], admission_pack.MAY_DECIDE_NO, c["case"])


class Refusals(unittest.TestCase):
    """Each edit of the baseline must be refused, naming the rule it breaks."""

    def assertRefused(self, old, new, want):
        text = baseline_text() if old in baseline_text() else ladder_text()
        self.assertTrue(old in text, f"the baseline has no {old!r}")
        issues = pack_compile.validate_source(load(text.replace(old, new, 1)))
        self.assertTrue(any(want in i for i in issues), issues)

    def test_a_card_row_deciding_no(self):
        self.assertRefused("    check: card.verified\n    from: T1\n    on_fail: \"LIMIT\"",
                           "    check: card.verified\n    from: T1\n    on_fail: \"NO\"", "a card row may not decide NO")

    def test_a_vouch_row_deciding_no(self):
        self.assertRefused("    check: vouch.distinct_controllers\n    params: {min: 3}            # placeholder\n"
                           "    from: T2\n    on_fail: \"record\"",
                           "    check: vouch.distinct_controllers\n    params: {min: 3}\n    from: T2\n    on_fail: \"NO\"",
                           "a vouch row may not decide NO")

    def test_a_stake_row_deciding_no(self):
        self.assertRefused("    check: stake.covers_deal\n    from: T2\n    on_fail: \"record\"",
                           "    check: stake.covers_deal\n    from: T2\n    on_fail: \"NO\"", "a stake row may not decide NO")

    def test_a_judged_row_deciding_no(self):
        self.assertRefused("    on_fail: {cap: T1}", "    on_fail: \"NO\"", "a judged row's on_fail must be {cap: <tier>}")

    def test_missing_go(self):
        self.assertRefused('missing: "LIMIT"', 'missing: "GO"', "never a silent GO")

    def test_an_unquoted_no(self):
        self.assertRefused('    on_fail: "NO"', "    on_fail: NO", "YAML 1.1 reads a plain NO as false")

    def test_a_score(self):
        self.assertRefused("budget:\n", "score: {weights: [1]}\nbudget:\n", "score is not an admission pack field")

    def test_a_row_weight(self):
        self.assertRefused("    check: own.settled\n", "    check: own.settled\n    weight: 2\n", "weight is not a row field")

    def test_limit_on_the_lowest_tier(self):
        self.assertRefused("    check: operator.allow_listed\n    from: T0\n    on_fail: \"NO\"",
                           "    check: operator.allow_listed\n    from: T0\n    on_fail: \"LIMIT\"", "cannot LIMIT")

    def test_an_unknown_predicate(self):
        self.assertRefused("check: own.settled", "check: own.reputation", "is not an admission predicate")

    def test_a_wrong_param(self):
        self.assertRefused("    params: {max_age_s: 604800}", "    params: {max_age: 604800}", "needs params.max_age_s")

    def test_decades_that_do_not_rise(self):
        self.assertRefused("max_decade: {sat: 4, USD: 0}", "max_decade: {sat: 3, USD: 0}", "does not rise")

    def test_an_ask_without_ask(self):
        self.assertRefused('outcomes: ["GO", "ASK", "LIMIT", "NO"]', 'outcomes: ["GO", "LIMIT", "NO"]',
                           "ASK is not in outcomes")

    def test_a_judged_row_in_a_pack_without_limit(self):
        text = baseline_text().replace('outcomes: ["GO", "ASK", "LIMIT", "NO"]', 'outcomes: ["GO", "ASK", "NO"]')
        issues = pack_compile.validate_source(load(text))
        self.assertIn("rows[19] ('adjacent-domain'): a judged row caps a tier, so LIMIT must be in outcomes", issues)

    def test_a_cap_that_lowers_nothing(self):
        self.assertRefused("    on_fail: {cap: T1}", "    on_fail: {cap: T2}", "cap T2 must be a tier below from T2")

    def test_an_ask_on_a_no_row(self):
        self.assertRefused("    check: platform.attestation_not_invalid\n    from: T0\n    on_fail: \"NO\"",
                           "    check: platform.attestation_not_invalid\n    from: T0\n    on_fail: \"NO\"\n"
                           "    ask: {derivation: history_card/1}", "only a LIMIT row may carry an ask")

    def test_a_ceiling_in_a_unit_accept_does_not_name(self):
        self.assertRefused("max_decade: {USD: 2}", "max_decade: {USD: 2, Sat: 9}", "max_decade.Sat is not a band unit in accept")

    def test_a_ceiling_that_falls_across_a_skipped_tier(self):
        text = baseline_text().replace("max_decade: {sat: 4, USD: 0}", "max_decade: {USD: 0}") \
            .replace("max_decade: {USD: 2}", "max_decade: {USD: 2, sat: 2}")
        issues = pack_compile.validate_source(load(text))
        self.assertIn("tier T2: max_decade.sat 2 does not rise above the tier below (3)", issues)

    def test_no_ask_deadline(self):
        self.assertRefused("  deadline_s: 86400", "  max_wait: 86400", "deadline_s: 1 to")

    def test_an_unknown_trust_root(self):
        self.assertRefused("  judges: [placeholder-judge]", "  rivers: [x402]", "trust_roots must map some of")

    def test_a_rail_named_not_pinned(self):
        self.assertRefused("  judges: [placeholder-judge]", "  rails: [x402]", "trust_roots.rails[0] must be exactly")

    def test_a_rail_pin_with_a_short_digest(self):
        self.assertRefused("  judges: [placeholder-judge]", "  rails: [{id: x402, digest: abc}]",
                           "trust_roots.rails[0] must be exactly")

    def test_a_rail_digest_with_a_trailing_newline(self):
        # Python's $ matches before a final newline; Go's RE2 and Rust's
        # length check do not, so the lint must refuse what they refuse.
        self.assertRefused("  judges: [placeholder-judge]", "  rails: [{id: x402, digest: \"" + "a" * 64 + "\\n\"}]",
                           "trust_roots.rails[0] must be exactly")

    def test_ids_with_a_trailing_newline(self):
        self.assertRefused("  - id: attestation\n", "  - id: \"attestation\\n\"\n", "id must be lowercase")
        self.assertRefused("pack_id: asg/admission_baseline/1.1.0", "pack_id: \"asg/admission_baseline/1.1.0\\n\"",
                           "must be owner/name/version")

    def test_a_rail_pin_with_an_uppercase_digest(self):
        self.assertRefused("  judges: [placeholder-judge]", "  rails: [{id: x402, digest: \"" + "A" * 64 + "\"}]",
                           "trust_roots.rails[0] must be exactly")

    def test_a_rail_pin_with_no_id(self):
        self.assertRefused("  judges: [placeholder-judge]", "  rails: [{id: \"\", digest: \"" + "a" * 64 + "\"}]",
                           "trust_roots.rails[0] must be exactly")

    def test_a_rail_pin_with_another_key(self):
        self.assertRefused("  judges: [placeholder-judge]",
                           "  rails: [{id: x402, digest: \"" + "a" * 64 + "\", weight: 2}]",
                           "trust_roots.rails[0] must be exactly")

    def test_a_rail_pinned_twice(self):
        pin = "{id: x402, digest: \"" + "a" * 64 + "\"}"
        self.assertRefused("  judges: [placeholder-judge]", f"  rails: [{pin}, {pin}]", "x402 is listed twice")

    def test_a_ladder_that_earns_from_no_subject(self):
        self.assertRefused(LADDER_PARAMS, LADDER_PARAMS.replace("k: 3", "k: 0"), "params.k 0 must be from 1")

    def test_a_ladder_step_out_of_range(self):
        self.assertRefused(LADDER_PARAMS, LADDER_PARAMS.replace("step_decades: 1", "step_decades: 61"),
                           "params.step_decades 61 must be from 0 to 60")

    def test_a_ladder_dispute_rate_out_of_range(self):
        self.assertRefused(LADDER_PARAMS, LADDER_PARAMS.replace("max_adverse_permille: 50", "max_adverse_permille: 1001"),
                           "params.max_adverse_permille 1001 must be from 0 to 1000")

    def test_a_ladder_row_deciding_no(self):
        self.assertRefused(LADDER_PARAMS + "\n    from: T1\n    on_fail: \"LIMIT\"",
                           LADDER_PARAMS + "\n    from: T1\n    on_fail: \"NO\"", "a card row may not decide NO")

    def test_wrong_types_are_reported_not_raised(self):
        text = baseline_text().replace("  - id: attestation\n", "  - id: [attestation]\n") \
            .replace("check: platform.owner_signed", "check: [platform.owner_signed]") \
            .replace('source: "evidencebook-skills#51', 'source_was: "x"\nsource: {by: "evidencebook-skills#51')
        text = text.replace('#280"\n', '#280"}\n', 1)
        issues = pack_compile.validate_source(load(text))
        self.assertTrue(any("id must be lowercase" in i for i in issues), issues)
        self.assertTrue(any("is not an admission predicate" in i for i in issues), issues)
        self.assertIn("source must be provenance text (a string)", issues)

    def test_a_scale_out_of_range(self):
        self.assertRefused("scale: -3}", "scale: -300}", "scale -300 must be from -30 to 30")

    def test_a_ceiling_out_of_range(self):
        self.assertRefused("max_decade: {USD: 2}", "max_decade: {USD: 99}", "max_decade.USD 99 must be from -60 to 60")

    def test_a_budget_out_of_range(self):
        self.assertRefused("  deadline_s: 86400", "  deadline_s: 9007199254740993", "deadline_s: 1 to")
        self.assertRefused("  max_asks: 3", "  max_asks: 9007199254740993", "max_asks: 0 to 1000")

    def test_a_numeric_currency(self):
        self.assertRefused("  USDT: {band: USD, scale: 0}", "  840: {band: USD, scale: 0}", "must be written as a string")

    def test_a_unit_no_tier_names(self):
        self.assertRefused("  USD: {band: USD, scale: 0}\n", "  USD: {band: USD, scale: 0}\n  EUR: {band: EUR, scale: 0}\n",
                           "band unit EUR is named by no tier")

    def test_a_negative_threshold(self):
        self.assertRefused("params: {min: 10}", "params: {min: -1}", "params.min -1 must be from 0")

    def test_a_threshold_whose_duration_wraps(self):
        self.assertRefused("params: {max_age_s: 604800}", "params: {max_age_s: 99999999999}",
                           "params.max_age_s 99999999999 must be from 0")

    def test_an_unknown_scope_kind_still_names_admission(self):
        issues = pack_compile.validate_source(load(baseline_text().replace("kind: admission", "kind: admit")))
        self.assertIn("scope.kind 'admit' must be one of ['live', 'after_the_fact', 'admission', 'deal', 'conduct']", issues)


class GoNoPack(unittest.TestCase):
    """A pack shaped like the Mesh default under u137: GO and NO only, NO from
    the operator alone, the other rows recorded. Its evaluator vectors, above
    the top tier among them, are capsule-engine#265's (mesh-go-no.yaml)."""

    SOURCE = """
pack_id: asg/mesh_admission_example/0.1.0
pack_version: 0.1.0
scope: {kind: admission}
outcomes: ["GO", "NO"]
missing: "NO"
accept:
  msat: {band: sat, scale: -3}
tiers:
  - {id: T0, max_decade: {sat: 6}}
budget: {max_asks: 0, deadline_s: 86400}
rows:
  - {id: deny-list, statement: Not on the deny list., source: operator, check: operator.not_deny_listed, from: T0, on_fail: "NO"}
  - {id: disputes, statement: No adverse adjudication in 30 days., source: own_history, check: own.no_adverse_adjudication, params: {window_days: 30}, from: T0, on_fail: "record"}
"""

    def test_validates(self):
        self.assertEqual(pack_compile.validate_source(load(self.SOURCE)), [])

    def test_refuses_a_limit_or_an_ask(self):
        self.assertTrue(pack_compile.validate_source(load(self.SOURCE.replace('on_fail: "record"', 'on_fail: "LIMIT"'))))
        self.assertTrue(pack_compile.validate_source(load(self.SOURCE.replace(
            'on_fail: "record"}', 'on_fail: "record", ask: {derivation: history_card/1}}'))))


class TextIssues(unittest.TestCase):
    """What the evaluator's loader refuses in the text, before any mapping."""

    def issues(self, old, new):
        text = baseline_text()
        self.assertTrue(old in text, old)
        return admission_pack.text_issues(text.replace(old, new, 1))

    def test_the_baseline_has_none(self):
        self.assertEqual(admission_pack.text_issues(baseline_text()), [])

    def test_accepted_plain_forms(self):
        # A version, a decimal, words and text read alike everywhere; the
        # non-specific tag ! is ignored, as yaml.v3 ignores it.
        for doc in ("v: 1.0.0", "v: -3", "v: 0", "v: asg/admission_baseline/1.0.0", "v: history_card/1",
                    "v: The card is 7 days old.", "v: ! text", 'v: "NO"', "v:"):
            self.assertEqual(admission_pack.text_issues(doc), [], doc)

    def test_refused(self):
        for old, new, want in [
            ('on_fail: "NO"', "on_fail: NO", "quote 'NO'"),
            ('on_fail: "NO"', "on_fail: y", "quote 'y'"),
            ('on_fail: "NO"', "on_fail: null", "quote 'null'"),
            ("scale: -3}", "scale: -3.5}", "quote '-3.5'"),
            ("max_asks: 3", "max_asks: 0x3", "quote '0x3'"),
            ("max_asks: 3", "max_asks: 03", "quote '03'"),
            ("max_asks: 3", "max_asks: 1_0", "quote '1_0'"),
            ("max_asks: 3", "max_asks: -0", "quote '-0'"),
            ("max_asks: 3", "max_asks: +3", "quote '+3'"),
            ("  - id: attestation\n", "  - id: true\n", "quote 'true'"),
            ("  - id: attestation\n", "  - id: 1e3\n", "quote '1e3'"),
            ("  - id: attestation\n", "  - id: 1E-2\n", "quote '1E-2'"),
            ("  - id: attestation\n", "  - id: 0o10\n", "quote '0o10'"),
            ("  - id: attestation\n", "  - id: 2026-1-2\n", "quote '2026-1-2'"),
            ("  - id: attestation\n", "  - id: 1:30\n", "quote '1:30'"),
            ("  - id: attestation\n", "  - id: .inf\n", "quote '.inf'"),
            ("  - id: T0 ", "  - &t0 id: T0 ", "anchors and aliases"),
            ("  - id: attestation\n", "  - id: !!str attestation\n", "tags are not read"),
            ("max_asks: 3", 'max_asks: !!int "3"', "tags are not read"),
            ("source: \"evidencebook", "source: 2026-10-30\nx: \"evidencebook", "quote '2026-10-30'"),
        ]:
            got = self.issues(old, new)
            self.assertTrue(any(want in i for i in got), (new, got))

    def test_the_shared_probes(self):
        # The source's plain scalar rule: PyYAML, in the compiler, is the one
        # YAML reader an admission pack has (the evaluator reads the compiled
        # pack-definition.json), so this guards what it would misread.
        probes = json.loads((REPO_ROOT / "tests/fixtures/admission-plain-scalars.json").read_text())
        for doc in probes["accepted"]:
            self.assertEqual(admission_pack.text_issues(doc), [], doc)
        for doc in probes["refused"]:
            try:
                got = admission_pack.text_issues(doc)
            except yaml.YAMLError:
                continue
            self.assertTrue(got, doc)

    def test_malformed_yaml_is_reported(self):
        got = admission_pack.text_issues("rows: [a, {b: ]\n")
        self.assertTrue(got and "not YAML" in got[0], got)

    def test_the_cli_reports_them(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", dir=REPO_ROOT / "packs", delete=False) as f:
            f.write(baseline_text().replace("max_asks: 3", "max_asks: 0x3", 1))
        try:
            run = subprocess.run([sys.executable, "scripts/pack_compile.py", "validate", f.name],
                                 cwd=REPO_ROOT, capture_output=True, text=True)
        finally:
            pathlib.Path(f.name).unlink()
        self.assertEqual(run.returncode, 1)
        self.assertTrue(any("quote '0x3'" in i for i in json.loads(run.stdout)["issues"]), run.stdout)


if __name__ == "__main__":
    unittest.main()


ARD_DEMO = REPO_ROOT / "demo/ard/pack"


class ArdDemoBuyer(unittest.TestCase):
    """ard-demo-buyer (#169): the ARD two-seller demo's pack, kept in demo/ard/pack (moved out of packs/ by #192).
    It differs from admission-baseline@1 only in its documented demo fields."""

    def setUp(self):
        self.pack = load((ARD_DEMO / "pack-source.yaml").read_text())
        self.base = load((BASELINE / "pack-source.yaml").read_text())

    def test_validates(self):
        self.assertEqual(pack_compile.validate_source(self.pack), [])

    def test_the_committed_artifact_is_the_compiled_source(self):
        self.assertEqual((ARD_DEMO / "compiled/pack-definition.json").read_bytes(), admission_pack.compiled_bytes(self.pack))
        self.assertEqual((ARD_DEMO / "compiled/contract.json").read_bytes(), ec.to_bytes(admission_pack.from_admission(self.pack)))

    def test_only_the_documented_demo_fields_differ_from_the_baseline(self):
        changed = {k for k in self.base if self.pack.get(k) != self.base[k]}
        self.assertEqual(changed, {"pack_id", "pack_version", "source", "accept", "tiers", "trust_roots", "rows"})
        self.assertEqual(set(self.pack), set(self.base))
        base_rows = {r["id"]: r for r in self.base["rows"]}
        demo_rows = {r["id"]: r for r in self.pack["rows"]}
        self.assertEqual(set(base_rows) - set(demo_rows), {"claims-held", "disputes-against", "open-disputes"})
        self.assertEqual(set(demo_rows) - set(base_rows), {"band-history"})
        self.assertEqual([i for i in base_rows if i in demo_rows and base_rows[i] != demo_rows[i]], [])

    def test_it_ships_at_100_per_1000_for_the_presenter_to_tighten(self):
        params = next(r["params"] for r in self.pack["rows"] if r["id"] == "band-history")
        self.assertEqual(params["max_adverse_permille"], 100)
