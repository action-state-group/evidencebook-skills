"""Pure functions: combine criterion verdicts into check verdicts, and the
all-required rollup a resolved conversation needs. No I/O, no capsulectl,
no model calls -- everything here is a function of the verdicts (and the
clause/check shape) you hand it.

Pack-driven, not hardcoded: `checks_from_clauses()`/`all_criteria_from_clauses()`
derive the check groupings and the full criteria set from a compiled contract's own
`clauses[]` (each clause already carries `id` and `check_id` --
scripts/pack_compile.py writes both). `check_verdicts()`/`all_required_met()` take
that shape as an explicit argument rather than assuming any fixed count or set of
criteria, so a pack that adds, removes or renames a criterion rolls up correctly
without a code change here -- only scripts/rollup_day.py's caller needs to derive
the shape from the spec it already loaded.

The rollup treats every criterion the same way regardless of tier: it never reads
a clause's tier/recompute_eligible fields, only the verdicts a day's judging
produced.

A conversation resolves only when something was actually checked: at least one
criterion is met, and every other is met or (when allowed) not_applicable. A
conversation on which every criterion came back not_applicable resolves nothing.
A criterion a pack marks `never_not_applicable` (e.g. done_in_full,
no_invented_policy -- something always happened that they test) may never be
not_applicable; such a verdict is refused, not counted.
"""


class RollupError(ValueError):
    """A rollup was asked to combine something other than exactly the verdicts it
    needs -- refused rather than silently combined over the wrong shape (absent is
    never pass)."""


def checks_from_clauses(clauses):
    """check_id -> tuple of criterion/clause ids, in each check's first-seen order.
    Pure, derived from a compiled contract's clauses[] -- never hardcoded."""
    checks = {}
    for clause in clauses:
        checks.setdefault(clause["check_id"], []).append(clause["id"])
    return {check_id: tuple(ids) for check_id, ids in checks.items()}


def all_criteria_from_clauses(clauses):
    """Every clause id, in the contract's own order. Pure, derived from clauses[]."""
    return tuple(clause["id"] for clause in clauses)


def never_not_applicable_from_clauses(clauses):
    """The clause ids a pack marks never_not_applicable. Pure, derived from clauses[]."""
    return frozenset(clause["id"] for clause in clauses if clause.get("never_not_applicable"))


VERDICTS = ("met", "not_met", "not_evaluable")

# The not_applicable_verdict switch (a compiled contract's "switches"): off by
# default, so every function below defaults allow_not_applicable=False unless a
# caller opts in. Within a group that also has a met, not_applicable counts as
# passing; a group whose verdicts are ALL not_applicable combines to
# not_applicable, never to met -- nothing in it was checked. See
# scripts/result_v0.py's "excluded_not_applicable".
NOT_APPLICABLE = "not_applicable"
VERDICTS_WITH_NA = VERDICTS + (NOT_APPLICABLE,)


def combine(verdicts, allow_not_applicable=False):
    """AND semantics over a set of verdicts: not_met beats not_evaluable beats
    met; not_applicable (when allowed) passes beside a met, and a set that is
    all not_applicable is not_applicable -- never met."""
    verdicts = list(verdicts)
    if not verdicts:
        raise RollupError("combine() needs at least one verdict")
    valid = VERDICTS_WITH_NA if allow_not_applicable else VERDICTS
    bad = [v for v in verdicts if v not in valid]
    if bad:
        raise RollupError(f"not a verdict: {bad!r}")
    if any(v == "not_met" for v in verdicts):
        return "not_met"
    if any(v == "not_evaluable" for v in verdicts):
        return "not_evaluable"
    if all(v == NOT_APPLICABLE for v in verdicts):
        return NOT_APPLICABLE
    return "met"


def check_verdicts(criterion_verdicts, checks, allow_not_applicable=False):
    """One verdict per check, each the AND of its own criteria. Refuses a check
    with a missing criterion rather than combining over what happens to be present.

    `checks`: dict[check_id -> tuple of criterion ids], e.g. from
    checks_from_clauses() over the compiled contract this day was judged against."""
    out = {}
    for check_id, criteria in checks.items():
        missing = [c for c in criteria if c not in criterion_verdicts]
        if missing:
            raise RollupError(f"check {check_id!r} is missing criteria {missing!r}")
        out[check_id] = combine((criterion_verdicts[c] for c in criteria), allow_not_applicable)
    return out


def all_required_met(criterion_verdicts, all_criteria, allow_not_applicable=False,
                     never_not_applicable=frozenset()):
    """The all-required rollup: a conversation is resolved only when at least one
    criterion is met and every other required criterion is met (or, when the
    not_applicable_verdict switch is on, not_applicable). All not_applicable is
    NOT resolved. Refuses unless criterion_verdicts carries exactly the known
    criteria -- missing ones are never treated as passing, and unrecognized ones
    are never silently ignored -- and refuses a not_applicable verdict on any
    criterion in `never_not_applicable`.

    `all_criteria`: tuple of every criterion id the contract defines, e.g. from
    all_criteria_from_clauses() over the compiled contract this day was judged
    against. This is deliberately a parameter, not a module constant: a pack that
    adds, removes or renames a criterion changes what "all required" means, and
    that change must come from the compiled contract, never from code here."""
    missing = [c for c in all_criteria if c not in criterion_verdicts]
    extra = [c for c in criterion_verdicts if c not in all_criteria]
    if missing:
        raise RollupError(f"missing criteria: {missing!r}")
    if extra:
        raise RollupError(f"unrecognized criteria: {extra!r}")
    forbidden = sorted(c for c in never_not_applicable if criterion_verdicts.get(c) == NOT_APPLICABLE)
    if forbidden:
        raise RollupError(f"criteria that may never be not_applicable came back not_applicable: {forbidden!r}")
    return combine(criterion_verdicts.values(), allow_not_applicable) == "met"
