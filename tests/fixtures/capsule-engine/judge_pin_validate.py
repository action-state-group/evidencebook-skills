"""The portable subset of capsule-engine PR #96's judge_pin validation,
reimplemented from `action-state-group/capsule-engine` at commit
9069cf70aa562b42c9983d7277ec1ce2e1e34ce5 -- see this directory's README.md
for the full citation, and for why this coexists with the real loader
(tests/test_judge_pin_capsule_engine_96.py's RealLoaderAccepts).

Reimplemented, not imported: capsule-engine is a separate repo this one does
not depend on at runtime, read-only, for this cross-check alone.

  - `_JUDGE_PIN_KEYS` (loader.py) -- the pin's key set is exactly
    {model_id, prompt_template_hash, schema_hash, input_refs, model_hosting}.
  - `_SHA256_HEX_RE` (loader.py: `^[0-9a-f]{64}$`) -- prompt_template_hash
    and schema_hash's format.
  - `JUDGE_PIN_HOSTING_VALUES` (schema.py: `frozenset({"hosted",
    "self_hosted"})`) -- model_hosting's closed set.
  - `NORMALIZED_ACTION_FIELDS` (schema.py) -- input_refs' own closed
    vocabulary.
  - `_parse_judge_pin`'s own checks (loader.py): model_id a non-empty str;
    prompt_template_hash/schema_hash each a 64-lowercase-hex string;
    input_refs a non-empty list with no duplicate, each entry in
    NORMALIZED_ACTION_FIELDS; model_hosting in the closed set; no key
    outside the five.
  - `_refuse_prompt_text`'s judge_pin-scoped half (loader.py): no pin key
    whose name contains "prompt" (case-insensitive) other than
    prompt_template_hash.
"""
import re

JUDGE_PIN_KEYS = frozenset({"model_id", "prompt_template_hash", "schema_hash", "input_refs", "model_hosting"})
JUDGE_PIN_HOSTING_VALUES = frozenset({"hosted", "self_hosted"})
NORMALIZED_ACTION_FIELDS = frozenset(
    {
        "amount_minor",
        "currency",
        "target",
        "cited_mandate_capsule_id",
        "equivalence_key",
        "model_id",
        "provider",
        "rail",
        "counterparty_account_ref",
        "outgoing_content",
        "recurrence",
    }
)
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


class JudgePinRefused(Exception):
    """Raised with the same reason loader.py's PackDefinitionError would carry."""


def assert_accepted(pin):
    """Raises JudgePinRefused on the first rule `pin` fails, exactly as
    capsule-engine #96's loader.py:_parse_judge_pin (plus its judge_pin-
    scoped prompt-text refusal) would refuse it. Returns None on acceptance
    (by every rule reimplemented here -- see README.md for the one rule this
    cross-check intentionally does not enforce)."""
    if not isinstance(pin, dict):
        raise JudgePinRefused(f"judge_pin must be a mapping, got {type(pin).__name__}")

    unknown = sorted(str(key) for key in pin if key not in JUDGE_PIN_KEYS)
    if unknown:
        raise JudgePinRefused(f"judge_pin carries unknown keys {unknown}; the pin is exactly {sorted(JUDGE_PIN_KEYS)}")

    prompt_named = [key for key in pin if isinstance(key, str) and "prompt" in key.lower() and key != "prompt_template_hash"]
    if prompt_named:
        raise JudgePinRefused(f"judge_pin carries {prompt_named!r}; prompt text never enters a pack")

    model_id = pin.get("model_id")
    if not isinstance(model_id, str) or not model_id:
        raise JudgePinRefused("judge_pin.model_id must be a non-empty string")

    for key in ("prompt_template_hash", "schema_hash"):
        value = pin.get(key)
        if not isinstance(value, str) or not _SHA256_HEX_RE.match(value):
            raise JudgePinRefused(f"judge_pin.{key} must be 64 lowercase hex characters (SHA-256)")

    input_refs = pin.get("input_refs")
    if not isinstance(input_refs, list) or not input_refs:
        raise JudgePinRefused("judge_pin.input_refs must be a non-empty list of normalized action fields")
    for ref in input_refs:
        if not isinstance(ref, str) or ref not in NORMALIZED_ACTION_FIELDS:
            raise JudgePinRefused(
                f"judge_pin.input_refs entry {ref!r} must be one of {sorted(NORMALIZED_ACTION_FIELDS)}"
            )
    if len(set(input_refs)) != len(input_refs):
        raise JudgePinRefused("judge_pin.input_refs lists a ref more than once")

    model_hosting = pin.get("model_hosting")
    if model_hosting not in JUDGE_PIN_HOSTING_VALUES:
        raise JudgePinRefused(
            f"judge_pin.model_hosting={model_hosting!r} must be one of {sorted(JUDGE_PIN_HOSTING_VALUES)}"
        )
