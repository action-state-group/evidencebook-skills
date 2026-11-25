# SPDX-License-Identifier: Apache-2.0
"""Maya's spending limit (``ARD_LIMIT_MSAT``) on x-deal-v1 deals: capsule-engine's Everyday Rules
(``guard check --limits``, capsule-engine go/v0.7.0 and later) pinned as her profile's rules checker, so capsulectl's
``deal check`` runs them on every payment and seals what they said in the check's verdict (evidencebook#890).

The limit is the most Maya may spend in a rolling week and on one order, both the same here. Unset, no checker is
pinned and the demo behaves as before. The limits file is Maya's own configuration, read at each check: the pin hashes
the engine alone, and the ruleset's digest is the pack's with or without it. So what shows her limit was applied is each
caps finding's ``limit``, which :func:`read` holds to her figure, refusing an order whose findings carry another.

A failing caps finding on a person-set limit holds the order for the person's OK (Steven, ops u325, 2026-10-12), and
so does any other failing ASK rule: one ask that lists every reason, each in the rule's own words (Sherlock2,
2026-11-23, rules doc section 4.5). This module reads the check's sealed findings into those reasons; the question is
:func:`screens.hold_question`."""
from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import party as pt

#: The action class Everyday Rules 0.3.8 caps a purchase under (capsulectl seals it on a pay check).
ACTION_CLASS = "money.purchase"
#: The caps findings' periods (everyday-0.3.8 r05), by the suffix of the finding's id, and the name the question uses.
CAPS_PERIODS = {"7d": "weekly", "per_purchase": "per_order"}
#: A finding the ruleset declares and the checker does not measure: never a reason.
DECLARED = "declared, not measured"
#: The rules whose disposition is ASK (Everyday Rules 27 v0.2): a failing one holds the order. Rules 1 to 4 are DO (a
#: failing one only withholds an allowance) and 23 to 25 are NEVER (capsulectl refuses those; nothing is asked).
ASK_RULES = frozenset(range(5, 23)) | {26, 27}


class LimitError(RuntimeError):
    """The limit could not be applied: a bad ``ARD_LIMIT_MSAT``, no engine, or a check whose caps findings do not carry
    the person's figure. Nothing was paid."""


def limit_msat() -> int | None:
    """The person's spending limit in msat, from ``ARD_LIMIT_MSAT``; ``None`` when none is set."""
    raw = os.environ.get("ARD_LIMIT_MSAT", "").strip()
    if not raw:
        return None
    if not raw.isdigit() or int(raw) <= 0:
        raise LimitError(f"ARD_LIMIT_MSAT must be a whole number of msat above 0, not {raw!r}")
    return int(raw)


def limits_profile(limit: int) -> dict:
    """The person's limits as capsule-engine's ``policy-profile/v0``: the most for one order and over 7 days."""
    return {"format": "policy-profile/v0", "packs": [{"pack": "asg/everyday", "parameters": {"caps": {
        "caps_minor": {ACTION_CLASS: limit}, "per_action_minor": {ACTION_CLASS: limit}}}}]}


def engine() -> str:
    path = os.environ.get("CAPSULE_ENGINE", "")
    if not path or not Path(path).is_file():
        raise LimitError("set CAPSULE_ENGINE to a capsule-engine binary (go/v0.7.0 or later) to use ARD_LIMIT_MSAT")
    return str(Path(path).resolve())


def pin(maya: pt.Party, limit: int) -> None:
    """Pin the Everyday Rules with Maya's limit as her profile's rules checker (``profile update --rules-checker``).
    capsulectl runs a checker only from a trusted plugin root, and runs Maya's profile with her folder as its home, so
    the engine is copied into her own root (``<her folder>/.local/lib/capsulectl/plugins``); the limits file goes in
    her folder too, at an absolute path, written fresh with ``limit``."""
    root = maya.dir / ".local" / "lib" / "capsulectl" / "plugins"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    for d in (maya.dir / ".local", maya.dir / ".local" / "lib", maya.dir / ".local" / "lib" / "capsulectl", root):
        d.chmod(0o700)
    copy = root / "capsule-engine"
    shutil.copyfile(engine(), copy)
    copy.chmod(0o700)
    limits = (maya.dir / "spending-limit.json").resolve()
    limits.write_text(json.dumps(limits_profile(limit)))
    limits.chmod(0o600)
    pin_file = maya.write("rules-checker.json", {"command": [str(copy.resolve()), "guard", "check", "--limits", str(limits)]})
    maya.run("profile", "update", "--rules-checker", pin_file)


def unpin(maya: pt.Party) -> None:
    """With no limit set, remove the checker :func:`pin` set (``profile update --rules-checker ""``), so a profile used
    with a limit before does not keep it. Only the demo's own pin: a profile with no limits file of the demo's is left
    as it is."""
    limits = maya.dir / "spending-limit.json"
    if not limits.exists():
        return
    maya.run("profile", "update", "--rules-checker", "")
    limits.unlink()


def refusal(check: dict) -> list[str]:
    """Why the rules refused a check (its verdict ``deny``): each failing rule in its own words."""
    findings = (check.get("rules") or {}).get("findings") or []
    out = [words(f) for f in findings if f.get("verdict") == "fail"]
    return list(dict.fromkeys(out)) or ["the Everyday Rules refused it"]


@dataclass
class Held:
    """What the rules said about an order, read from the check's sealed rules block."""
    reasons: list[str] = field(default_factory=list)  # every failing ASK rule, in the rule's own words
    limits: dict = field(default_factory=dict)  # each failing caps finding's (limit, value): "weekly", "per_order"

    @property
    def over_limit(self) -> bool:
        """Every reason is a spending limit: the question shows the limit's figures."""
        return bool(self.limits) and len(self.limits) == len(self.reasons)


def _period(finding: dict) -> str:
    fid = str(finding.get("id", ""))
    return fid.rsplit("#", 1)[1] if str(finding.get("check", "")).startswith("caps/") and "#" in fid else ""


def _is_ask(finding: dict) -> bool:
    m = re.match(r"r(\d{2})", str(finding.get("id", "")))
    return str(finding.get("check", "")).startswith("caps/") or (bool(m) and int(m.group(1)) in ASK_RULES)


def words(finding: dict) -> str:
    """The rule's own words for the person: the engine's reason without a trailing parenthetical about how it looked
    (Sherlock2, 2026-11-23); a caps finding reads as its figures (Sherlock2 on evidencebook-skills#270); any other
    amount with commas and its unit."""
    limit, value = finding.get("limit"), finding.get("value")
    if isinstance(limit, int) and isinstance(value, int):
        if _period(finding) == "7d":
            return f"over your weekly limit: {value:,} msat with this order, limit {limit:,} msat"
        if _period(finding) == "per_purchase":
            return f"over your per-order limit: this order {value:,} msat, limit {limit:,} msat"
    words = re.sub(r"\s*\([^)]*\)$", "", str(finding.get("reason") or finding.get("id", "")))
    # an amount in the engine's words reads with commas and its unit, never a bare figure (Steven, #272 item 1)
    return re.sub(r"(?<![\w.,])(\d{4,})(?![\w.,])", lambda m: f"{int(m.group(1)):,} msat", words)


def read(check: dict, limit: int | None) -> Held | None:
    """The rules' hold on a check (``deal check``'s output), or ``None`` when the rules did not hold it. With a
    ``limit``, the check's rules must have been evaluated with that figure as every caps finding's ``limit``."""
    rules = check.get("rules") or {}
    if limit is None:
        return None
    if rules.get("status") != "evaluated":
        raise LimitError(f"your spending limit was not checked: {rules.get('reason') or 'no rules checker answered'}; "
                         "nothing was paid")
    findings = rules.get("findings") or []
    caps = [f for f in findings if _period(f)]
    if not caps or any(f.get("limit") != limit for f in caps):
        raise LimitError("the rules checker did not apply your spending limit (its caps findings carry another figure); "
                         "nothing was paid")
    # what the check acts on: capsulectl pauses on an escalation, and on a deny the counterparty's History alone
    # caused, which never refuses on its own (it asks); any other deny is refused before this (buyer.open_and_pay)
    if check.get("verdict") != "pause" or rules.get("verdict") not in ("escalate", "deny"):
        return None
    asking = [f for f in findings if f.get("verdict") == "fail" and _is_ask(f)]
    unchecked = [f for f in findings if f.get("verdict") == "not_evaluable" and f.get("reason") != DECLARED]
    reasons = list(dict.fromkeys([words(f) for f in asking] + [words(f) + " (could not be checked)" for f in unchecked]))
    held = Held(reasons=reasons or ["the Everyday Rules asked for your OK"])
    for f in asking:
        if _period(f) in CAPS_PERIODS and isinstance(f.get("limit"), int) and isinstance(f.get("value"), int):
            held.limits[CAPS_PERIODS[_period(f)]] = (f["limit"], f["value"])
    return held
