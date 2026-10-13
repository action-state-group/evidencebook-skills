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
criterion is met, and every criterion that applies to it is met. An out_of_scope
criterion -- one that does not apply to this conversation -- is neither met nor
not_met: it is set aside, never counted toward satisfaction, so it can never be
the "at least one met", and a conversation on which every criterion came back
out_of_scope resolves nothing. out_of_scope is not not_evaluable either:
not_evaluable means the criterion applies and could not be determined, and it
holds a conversation back from resolving; the two are never folded into each
other here. `not_applicable` is not a verdict in this vocabulary at all (Evidence
Result v0 uses that word only for its own population exclusion,
aggregate.coverage.excluded_not_applicable) and is refused by name.
A criterion a pack marks `never_out_of_scope` (e.g. done_in_full,
no_invented_policy -- something always happened that they test) may never be
out_of_scope; such a verdict is refused, not counted.
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


def never_out_of_scope_from_clauses(clauses):
    """The clause ids a pack marks never_out_of_scope. Pure, derived from clauses[]."""
    return frozenset(clause["id"] for clause in clauses if clause.get("never_out_of_scope"))


VERDICTS = ("met", "not_met", "not_evaluable")

# The out_of_scope_verdict switch (a compiled contract's "switches"): off by
# default, so every function below defaults allow_out_of_scope=False unless a
# caller opts in. An out_of_scope verdict is set aside before combining: it is
# never counted as met, and a group whose verdicts are ALL out_of_scope combines
# to out_of_scope, never to met -- nothing in it was checked. See
# scripts/result_v0.py's "excluded_not_applicable".
OUT_OF_SCOPE = "out_of_scope"
VERDICTS_WITH_OOS = VERDICTS + (OUT_OF_SCOPE,)

# The retired spelling, refused by name rather than as "not a verdict": it has
# meant three different things in this stack, and a reader that sees it cannot
# tell which one was meant. Also refused by name in scripts/run_daily.py's
# checked_answer and scripts/result_v0.py's build_result_v0_for_day.
RETIRED_NOT_APPLICABLE = "not_applicable"
RETIRED_NOT_APPLICABLE_REASON = ("not_applicable is not an adjudicator verdict: use out_of_scope (the criterion "
                                 "does not apply here) or not_evaluable (it applies and could not be determined)")


def refuse_unknown_verdicts(verdicts, valid):
    """RollupError naming every verdict outside `valid`, with not_applicable
    called out so its writer learns which word replaces it."""
    if RETIRED_NOT_APPLICABLE in verdicts:
        raise RollupError(RETIRED_NOT_APPLICABLE_REASON)
    bad = [v for v in verdicts if v not in valid]
    if bad:
        raise RollupError(f"not a verdict: {bad!r}")


def combine(verdicts, allow_out_of_scope=False):
    """AND semantics over the verdicts that apply: not_met beats not_evaluable
    beats met. out_of_scope (when allowed) is set aside first -- it never counts
    as met and never as not_met -- so a set that is all out_of_scope is
    out_of_scope, never met."""
    verdicts = list(verdicts)
    if not verdicts:
        raise RollupError("combine() needs at least one verdict")
    refuse_unknown_verdicts(verdicts, VERDICTS_WITH_OOS if allow_out_of_scope else VERDICTS)
    in_scope = [v for v in verdicts if v != OUT_OF_SCOPE]
    if not in_scope:
        return OUT_OF_SCOPE
    if "not_met" in in_scope:
        return "not_met"
    if "not_evaluable" in in_scope:
        return "not_evaluable"
    return "met"


def check_verdicts(criterion_verdicts, checks, allow_out_of_scope=False):
    """One verdict per check, each the AND of its own criteria. Refuses a check
    with a missing criterion rather than combining over what happens to be present.

    `checks`: dict[check_id -> tuple of criterion ids], e.g. from
    checks_from_clauses() over the compiled contract this day was judged against."""
    out = {}
    for check_id, criteria in checks.items():
        missing = [c for c in criteria if c not in criterion_verdicts]
        if missing:
            raise RollupError(f"check {check_id!r} is missing criteria {missing!r}")
        out[check_id] = combine((criterion_verdicts[c] for c in criteria), allow_out_of_scope)
    return out


def all_required_met(criterion_verdicts, all_criteria, allow_out_of_scope=False,
                     never_out_of_scope=frozenset()):
    """The all-required rollup: a conversation is resolved only when at least one
    criterion is met and every required criterion that applies to it is met.
    When the out_of_scope_verdict switch is on, an out_of_scope criterion does
    not apply to this conversation: it is set aside, never counted toward
    satisfaction -- it cannot be the one met, so all out_of_scope is NOT
    resolved. Refuses unless criterion_verdicts carries exactly the known
    criteria -- missing ones are never treated as passing, and unrecognized ones
    are never silently ignored -- and refuses an out_of_scope verdict on any
    criterion in `never_out_of_scope`.

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
    forbidden = sorted(c for c in never_out_of_scope if criterion_verdicts.get(c) == OUT_OF_SCOPE)
    if forbidden:
        raise RollupError(f"criteria that may never be out_of_scope came back out_of_scope: {forbidden!r}")
    return combine(criterion_verdicts.values(), allow_out_of_scope) == "met"
