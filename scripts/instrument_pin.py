"""The judged-instrument pin: the model identity a verdict carries on
scripts/judge_bundle.py's Result v0 claims.

The key set matches capsule-engine's `judge_pin` (capsule-engine PR #96,
"judge_pin for mode: judged obligations", head commit
9069cf70aa562b42c9983d7277ec1ce2e1e34ce5, `capsule_engine/packs/schema.py`'s
`JudgePin`/`JudgePinDict` and `capsule_engine/packs/loader.py`'s
`_parse_judge_pin`): `model_id`, `prompt_template_hash`, `schema_hash`,
`input_refs`, `model_hosting`.

  - model_id: the judge model id this run actually used (overridable by an
    auditor's re-run under a different model id; same input, same clauses),
    with the backend stamped on it whenever that is not the real one
    (jev_judge.sealed_model_id): a mock's answer never seals under a bare
    real model name.
  - prompt_template_hash: jev_judge.compiled_prompt_digest(clauses, ...) --
    the SHA-256 hex digest of the prompt actually sent for the judged clauses:
    the instruction template plus each clause's compiled question and answer
    options (never a record's own content), so rewording a question moves the
    pin.
  - schema_hash: jev_judge.answer_schema_digest() -- the SHA-256 hex digest of
    the canonical JSON answer schema the judge must return. #96 fixes this
    field's FORMAT (64 lowercase hex characters, `loader.py`'s
    `_SHA256_HEX_RE`) but not the hashing algorithm or input bytes -- that is
    `capsule-judge`'s own `prompt_digest`/schema machinery, a different repo
    not vendored here. [open]: raw-byte SHA-256 over the canonical
    (sort_keys) JSON serialization of jev_judge.ANSWER_SCHEMA is this repo's
    own choice, not read from any authoritative source for this exact field.
  - input_refs: the normalized action fields (#96's own closed vocabulary,
    `capsule_engine.packs.schema.NORMALIZED_ACTION_FIELDS`) that the judged
    clauses actually being judged this call declare their prompt reads --
    packs/everyday-rules/pack-source.yaml's own `judge_input_refs` per
    criterion, passed through by scripts/pack_compile.py onto each compiled
    clause, unioned across the clauses in this call by
    scripts/judge_bundle.py's `declared_input_refs()`. This is a STATIC,
    pack-declared fact about what a clause's prompt asks about -- never a
    record or capsule_id, and never derived from which records a particular
    bundle happened to disclose. Record/capsule ids that actually contributed
    facts to a verdict stay where they always have: each Result v0 claim's
    own `evidence[]`, built from
    the same target_ids this module never sees. A call whose selected clauses
    declare no normalized field at all cannot honestly populate this list;
    scripts/judge_bundle.py refuses to seal a pin in that case (see its own
    docstring) rather than inventing a field name or silently building a pin
    capsule-engine's own loader would refuse.
  - model_hosting: "hosted" | "self_hosted", #96's own closed set
    (JUDGE_PIN_HOSTING_VALUES) -- always "hosted" for jev_judge.py's pinned
    judge (jev_judge.MODEL_HOSTING), never inferred per call.

Every pin this module builds from a real call site is checked against
capsule-engine's own, real `judge_pin` loader at the commit above by
tests/test_judge_pin_capsule_engine_96.py -- not merely asserted here.

This is a DIFFERENT pin from scripts/judge_pin.py's pin_input(), which stays
byte-for-byte what it always was: that one covers the airline path's transcript
mode (model_id, a prompt file's digest, an axes file's digest, sampling_params)
and run_daily.py/rollup_day.py still build and seal it exactly as before. The
two are not interchangeable and this module does not touch that one.
"""
import hashlib
import json

PIN_KEYS = ("model_id", "prompt_template_hash", "schema_hash", "input_refs", "model_hosting")


def build_pin(model_id, prompt_template_hash, schema_hash, input_refs, model_hosting):
    """(pin, pin_digest). pin_digest is the SHA-256 of pin's own JSON (sorted
    keys), the same construction judge_pin's airline-path digest uses, so a
    reader checking either pin's integrity does it the same way. The pin's own
    keys are exactly PIN_KEYS -- capsule-engine #96's judge_pin key set -- in
    that order, nothing added, nothing dropped. Refuses an empty or a
    repeated input_ref itself, rather than depending on every future caller
    never passing one -- the same two rules #96's own loader enforces
    (loader.py:_parse_judge_pin)."""
    if not input_refs:
        raise ValueError("input_refs must be a non-empty list of normalized action fields")
    if len(set(input_refs)) != len(input_refs):
        raise ValueError(f"input_refs lists a ref more than once: {sorted(input_refs)!r}")
    pin = {
        "model_id": model_id,
        "prompt_template_hash": prompt_template_hash,
        "schema_hash": schema_hash,
        "input_refs": sorted(input_refs),
        "model_hosting": model_hosting,
    }
    digest = hashlib.sha256(json.dumps(pin, sort_keys=True).encode()).hexdigest()
    return pin, digest
