"""Cross-check: every judged-instrument pin this repo emits (scripts/
instrument_pin.py, scripts/judge_bundle.py) is
accepted by capsule-engine PR #96's own judge_pin rules -- for every real
call-site pin these tests build. Two layers (tests/fixtures/capsule-engine/
README.md): `RealLoaderAccepts` runs capsule-engine's own, real,
unmodified `_parse_judge_pin()` (pip-installed at the pinned commit,
requirements.txt) -- the authoritative check; `RealPinsAreAccepted` and
`MalformedPinsAreRefused` run the same rules reimplemented as a portable,
offline fast-path (tests/fixtures/capsule-engine/judge_pin_validate.py).
Neither claims to cover every pin this repo could ever build (a --rule-ids
subset whose clauses declare no judge_input_refs at all cannot build a pin;
scripts/judge_bundle.py refuses that case before calling the judge -- see
its own run()) -- only the ones these tests actually construct, listed test
by test.

#96 ("packs: judge_pin for mode: judged obligations", `action-state-group/
capsule-engine` commit 9069cf70aa562b42c9983d7277ec1ce2e1e34ce5).

    python3 -m unittest discover -s tests -p 'test_*.py'
"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "judges"))
sys.path.insert(0, str(ROOT / "tests" / "fixtures" / "capsule-engine"))

import jevals  # noqa: E402
import jev_judge  # noqa: E402
import pack_compile  # noqa: E402
import judge_bundle  # noqa: E402
import instrument_pin  # noqa: E402
import yaml  # noqa: E402

from judge_pin_validate import JudgePinRefused, assert_accepted  # noqa: E402

try:
    from capsule_engine.packs.errors import PackDefinitionError
    from capsule_engine.packs.loader import _parse_judge_pin
    _CAPSULE_ENGINE_IMPORT_ERROR = None
except ImportError as e:  # pragma: no cover -- exercised only when the optional dependency is absent
    _CAPSULE_ENGINE_IMPORT_ERROR = e

PACK_SOURCE = ROOT / "packs" / "everyday-rules" / "pack-source.yaml"
CAPSULE_ID = "a" * 64
FACTS = {"action": "pay", "action_class": "money.transfer", "amount_minor": 4500,
         "currency": "USD", "rail": "card", "counterparty": "Example Merchant LLC", "recurrence": "none"}

# Literal, pinned values (item 5): these two digests seal every judge_pin
# this repo's "disclosed_facts" mode call sites build. A change to either
# one -- jev_judge.ANSWER_SCHEMA, or the disclosed_facts instruction
# template -- is a real behavior change to what the judge is asked and what
# it must answer, so these tests pin the literal hex, not merely "it's some
# 64-char hex string": a change here should be a deliberate, reviewed edit to
# this test, never a silent side effect of an unrelated change.
DISCLOSED_FACTS_PROMPT_TEMPLATE_HASH = "6fdab8f50fac6a98420f5092d328bab4e91caeacb0006c0e74f1be62a3a37102"
ANSWER_SCHEMA_HASH = "69fa84e81389a9544d456b189411048e32ab5b36071ef3d0136accd1db465434"
# The pin's prompt_template_hash for a call judging rule 9 alone: the template
# above plus rule 9's compiled question (jev_judge.compiled_prompt_digest).
# Rewording rule 9's question moves this literal, by design.
RULE9_PROMPT_TEMPLATE_HASH = "c7a000b03f57c2021314813f78f2ee72b397075fcf6e84d6ddabda0bc5696358"


def compiled_pack():
    source = pack_compile._strip_strings(yaml.safe_load(PACK_SOURCE.read_text()))
    compiled, _axes, _prompt, _presentation = pack_compile.compile_pack(source, "packs/everyday-rules/compiled")
    return compiled


def fixed_backend(verdict):
    return jevals.MockBackend(fn=lambda qid, q, state: verdict)


def rule9_clauses():
    return judge_bundle.select_clauses(compiled_pack(), ["9"])


def pin_for(model_id, input_refs):
    """judge_bundle.build_judge_pin() over rule 9's compiled clause: the pin's
    prompt_template_hash depends on which questions were sent, so every pin
    built here names the clauses it covers."""
    return judge_bundle.build_judge_pin(model_id, input_refs, rule9_clauses())



class LiteralPinHashes(unittest.TestCase):
    """schema_hash and the disclosed_facts prompt_template_hash, pinned to
    their literal value -- not merely "is 64 lowercase hex" (MalformedPinsAreRefused
    below already covers the format rule); this catches an unintended change
    to jev_judge.ANSWER_SCHEMA or the disclosed_facts instruction template
    itself, which the format check alone would not."""

    def test_schema_hash_is_the_pinned_literal(self):
        self.assertEqual(jev_judge.answer_schema_digest(), ANSWER_SCHEMA_HASH)

    def test_disclosed_facts_prompt_template_hash_is_the_pinned_literal(self):
        self.assertEqual(
            jev_judge.instruction_template_digest(mode="disclosed_facts"),
            DISCLOSED_FACTS_PROMPT_TEMPLATE_HASH,
        )

    def test_a_real_judge_bundle_pin_carries_the_pinned_literals(self):
        pack = compiled_pack()
        document = judge_bundle.run(pack, {
            "bundle_kind": judge_bundle.BUNDLE_KIND, "root": "literal-hash-check",
            "records": [{"capsule_id": CAPSULE_ID}],
            "disclosures": {CAPSULE_ID: FACTS}, "completeness": {"payloads_mode": "selected", "missing": []},
        }, ["9"], None, "jev-1.13.0", "2026-10-08T00:00:00Z", backend=fixed_backend("met"))
        pin = document["claims"][0]["judge_pin"]
        self.assertEqual(pin["prompt_template_hash"], RULE9_PROMPT_TEMPLATE_HASH)
        self.assertEqual(pin["schema_hash"], ANSWER_SCHEMA_HASH)


class PinCoversTheQuestions(unittest.TestCase):
    """prompt_template_hash covers each judged clause's compiled question, not
    the template alone: before this, rewording r9/r10's questions left the pin
    unchanged."""

    def _pin_hash(self, clauses):
        pin, _digest = judge_bundle.build_judge_pin("jev-1.13.0", ["amount_minor"], clauses)
        return pin["prompt_template_hash"]

    def test_a_one_word_change_to_a_question_moves_the_pin(self):
        clauses = rule9_clauses()
        reworded = [dict(c) for c in clauses]
        words = reworded[0]["claim"].split(" ")
        words[0] = words[0] + "x"
        reworded[0]["claim"] = " ".join(words)
        self.assertNotEqual(self._pin_hash(clauses), self._pin_hash(reworded))

    def test_the_template_digest_alone_is_unchanged(self):
        self.assertEqual(jev_judge.instruction_template_digest(mode="disclosed_facts"),
                         DISCLOSED_FACTS_PROMPT_TEMPLATE_HASH)
        self.assertNotEqual(self._pin_hash(rule9_clauses()), DISCLOSED_FACTS_PROMPT_TEMPLATE_HASH)

    def test_clause_order_does_not_move_the_pin(self):
        clauses = judge_bundle.select_clauses(compiled_pack(), ["9", "10"])
        self.assertEqual(self._pin_hash(clauses), self._pin_hash(list(reversed(clauses))))

    def test_the_evidence_never_enters_the_pin(self):
        pack = compiled_pack()
        pins = []
        for facts in (FACTS, {**FACTS, "note": "different evidence"}):
            document = judge_bundle.run(pack, {
                "bundle_kind": judge_bundle.BUNDLE_KIND, "root": "evidence-independence",
                "records": [{"capsule_id": CAPSULE_ID}],
                "disclosures": {CAPSULE_ID: facts}, "completeness": {"payloads_mode": "selected", "missing": []},
            }, ["9"], None, "jev-1.13.0", "2026-10-08T00:00:00Z", backend=fixed_backend("met"))
            pins.append(document["claims"][0]["judge_pin"]["prompt_template_hash"])
        self.assertEqual(pins[0], pins[1])


@unittest.skipIf(_CAPSULE_ENGINE_IMPORT_ERROR is not None,
                 f"capsule-engine not installed ({_CAPSULE_ENGINE_IMPORT_ERROR}); "
                 "pip install \"git+https://github.com/action-state-group/"
                 "capsule-engine.git@9069cf70aa562b42c9983d7277ec1ce2e1e34ce5\" "
                 "(requirements.txt) in a Python >= 3.11 environment")
class RealLoaderAccepts(unittest.TestCase):
    """capsule-engine's own, real, unmodified `_parse_judge_pin()`
    (`capsule_engine.packs.loader`, commit 9069cf70aa562b42c9983d7277ec1ce2e1e34ce5)
    called directly on every pin this repo's real call sites actually build.
    No reimplementation here -- this is the authoritative check the portable
    subset below (judge_pin_validate.py) stands in for when this optional
    dependency is not installed."""

    def _assert_real_loader_accepts(self, pin):
        try:
            _parse_judge_pin(pin, what="test")
        except PackDefinitionError as e:
            self.fail(f"capsule-engine's real loader refused a pin this repo built: {e}")

    def test_judge_bundle_default_whole_pack_pin_is_accepted(self):
        pack = compiled_pack()
        document = judge_bundle.run(pack, {
            "bundle_kind": judge_bundle.BUNDLE_KIND, "root": "real-loader-check",
            "records": [{"capsule_id": CAPSULE_ID}],
            "disclosures": {CAPSULE_ID: FACTS}, "completeness": {"payloads_mode": "selected", "missing": []},
        }, None, None, "jev-1.13.0", "2026-10-08T00:00:00Z", backend=fixed_backend("met"))
        for claim in document["claims"]:
            self._assert_real_loader_accepts(claim["judge_pin"])

    def test_judge_bundle_rule9_pin_is_accepted(self):
        pin, _digest = pin_for("jev-1.13.0", judge_bundle.declared_input_refs(
            judge_bundle.select_clauses(compiled_pack(), ["9"])
        ))
        self._assert_real_loader_accepts(pin)



    def test_an_auditor_rerun_under_a_different_model_id_is_still_accepted(self):
        pin, _digest = pin_for("jev-2.0.0", judge_bundle.declared_input_refs(
            judge_bundle.select_clauses(compiled_pack(), ["9"])
        ))
        self._assert_real_loader_accepts(pin)
        self.assertEqual(pin["model_id"], "jev-2.0.0")

    def test_the_pin_shape_this_repo_emitted_before_this_fix_is_refused(self):
        """Record capsule_ids as input_refs (this repo's pin shape before
        this fix) fails #96's own NORMALIZED_ACTION_FIELDS rule -- proving
        this is a real alignment, not a rename that happens to look like one."""
        pin, _digest = instrument_pin.build_pin(
            "jev-1.13.0", DISCLOSED_FACTS_PROMPT_TEMPLATE_HASH, ANSWER_SCHEMA_HASH, [CAPSULE_ID], "hosted"
        )
        with self.assertRaises(PackDefinitionError):
            _parse_judge_pin(pin, what="test")


class RealPinsAreAccepted(unittest.TestCase):
    """The same pins as RealLoaderAccepts, above, run through the portable,
    offline reimplementation (judge_pin_validate.py) instead of the real
    loader -- runs even where capsule-engine itself is not installed."""

    def test_judge_bundle_pin_is_accepted(self):
        pin, _digest = pin_for("jev-1.13.0", ["amount_minor", "currency", "recurrence"])
        assert_accepted(pin)



    def test_an_auditor_rerun_under_a_different_model_id_is_still_accepted(self):
        pin, _digest = pin_for("jev-2.0.0", judge_bundle.declared_input_refs(
            judge_bundle.select_clauses(compiled_pack(), ["9"])
        ))
        assert_accepted(pin)
        self.assertEqual(pin["model_id"], "jev-2.0.0")


class MalformedPinsAreRefused(unittest.TestCase):
    """Mirrors capsule-engine #96's own
    test_pack_obligation_judge_pin.py::test_a_malformed_pin_is_refused
    parametrization."""

    def _pin(self, **overrides):
        pin, _digest = pin_for("jev-1.13.0", ["amount_minor"])
        pin.update(overrides)
        return pin

    def test_empty_model_id_is_refused(self):
        with self.assertRaises(JudgePinRefused):
            assert_accepted(self._pin(model_id=""))

    def test_uppercase_hash_is_refused(self):
        with self.assertRaises(JudgePinRefused):
            assert_accepted(self._pin(prompt_template_hash="A" * 64))

    def test_short_hash_is_refused(self):
        with self.assertRaises(JudgePinRefused):
            assert_accepted(self._pin(prompt_template_hash="a" * 63))

    def test_missing_schema_hash_is_refused(self):
        with self.assertRaises(JudgePinRefused):
            assert_accepted(self._pin(schema_hash=None))

    def test_empty_input_refs_is_refused(self):
        with self.assertRaises(JudgePinRefused):
            assert_accepted(self._pin(input_refs=[]))

    def test_duplicate_input_refs_is_refused(self):
        with self.assertRaises(JudgePinRefused):
            assert_accepted(self._pin(input_refs=["amount_minor", "amount_minor"]))

    def test_input_ref_outside_the_closed_vocabulary_is_refused(self):
        with self.assertRaises(JudgePinRefused):
            assert_accepted(self._pin(input_refs=[CAPSULE_ID]))

    def test_hosting_outside_the_closed_set_is_refused(self):
        with self.assertRaises(JudgePinRefused):
            assert_accepted(self._pin(model_hosting="cloud"))

    def test_unknown_key_is_refused(self):
        with self.assertRaises(JudgePinRefused):
            assert_accepted(self._pin(temperature=0))

    def test_old_template_id_key_is_refused(self):
        """The pin this repo emitted before this change (template_id,
        prompt_template_digest, no schema_hash, no model_hosting) would NOT
        have been accepted by #96's rules -- confirming this is a real
        alignment, not a no-op."""
        with self.assertRaises(JudgePinRefused):
            assert_accepted({"template_id": "disclosed_facts",
                             "prompt_template_digest": "a" * 64,
                             "model_id": "jev-1.13.0",
                             "input_refs": ["amount_minor"]})

    def test_a_prompt_named_key_other_than_prompt_template_hash_is_refused(self):
        with self.assertRaises(JudgePinRefused):
            assert_accepted(self._pin(interpolated_prompt="Rule (14): ..."))


class KeySetAndHostingMatchCapsuleEngine96(unittest.TestCase):
    def test_pin_keys_are_exactly_96s_five(self):
        self.assertEqual(
            instrument_pin.PIN_KEYS,
            ("model_id", "prompt_template_hash", "schema_hash", "input_refs", "model_hosting"),
        )

    def test_jev_is_always_hosted_never_self_hosted(self):
        self.assertEqual(jev_judge.MODEL_HOSTING, "hosted")
        pin, _digest = pin_for("jev-1.13.0", ["amount_minor"])
        self.assertEqual(pin["model_hosting"], "hosted")

    def test_no_prompt_named_key_other_than_prompt_template_hash(self):
        """#96's loader refuses any judge_pin key named "...prompt..." other
        than prompt_template_hash outright -- confirm a real built pin never
        carries one."""
        pin, _digest = pin_for("jev-1.13.0", ["amount_minor"])
        prompt_named = [key for key in pin if "prompt" in key.lower()]
        self.assertEqual(prompt_named, ["prompt_template_hash"])
