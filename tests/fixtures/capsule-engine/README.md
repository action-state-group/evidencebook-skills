# Vendored capsule-engine judge_pin validation

Two layers, both at `capsule-engine` (`action-state-group/capsule-engine`)
commit `9069cf70aa562b42c9983d7277ec1ce2e1e34ce5` (PR #96, "packs: judge_pin
for mode: judged obligations"):

1. **The real loader** -- `tests/test_judge_pin_capsule_engine_96.py`'s
   `RealLoaderAccepts` class installs `capsule-engine` itself at the pinned
   commit (`pip install "git+https://github.com/action-state-group/
   capsule-engine.git@9069cf70aa562b42c9983d7277ec1ce2e1e34ce5"`, requirements.txt)
   and calls `capsule_engine.packs.loader._parse_judge_pin()` directly on
   every pin this repo's real call site (`scripts/judge_bundle.py`)
   actually builds. This is the authoritative
   check: no reimplementation, no excluded rule. Requires Python >= 3.11
   (capsule-engine's own dependency chain uses `typing.NotRequired`, not
   available on 3.10) and network access to install it.

2. **The portable subset** -- `judge_pin_validate.py` reimplements the same
   rules as a dependency-free, offline fast-path (no pip install, no network):
   `capsule_engine/packs/loader.py`'s `_parse_judge_pin()` and the
   `judge_pin`-scoped half of its `_refuse_prompt_text()`, plus
   `capsule_engine/packs/schema.py`'s `JudgePin`/`JudgePinDict`/
   `JUDGE_PIN_HOSTING_VALUES`/`NORMALIZED_ACTION_FIELDS`. Covers the exact key
   set, `model_id` non-empty, `prompt_template_hash`/`schema_hash` format (64
   lowercase hex), `input_refs` a non-empty list of unique strings each in
   `NORMALIZED_ACTION_FIELDS`, `model_hosting` in the closed `{hosted,
   self_hosted}` set, and no key named `...prompt...` other than
   `prompt_template_hash` -- the full rule set, not a subset that excludes the
   closed vocabulary: this repo's own `input_refs` is now the normalized
   action fields a judged clause declares it reads
   (`packs/everyday-rules/pack-source.yaml`'s `judge_input_refs`,
   `scripts/pack_compile.py`'s own vendored copy of the same closed set), so
   there is no rule left to exclude. Kept alongside the real loader because it
   runs in any Python >= 3.8, offline, in milliseconds -- useful as a fast
   local check; the real loader (above) is still what a pin is actually
   checked against before trusting the result.

Not a byte-for-byte copy of `loader.py` (it imports from sibling packages
this repo does not depend on at runtime) -- reimplemented here with the same
rules, cited line by line in `judge_pin_validate.py`'s own docstring.
