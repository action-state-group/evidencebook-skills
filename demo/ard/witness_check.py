#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check that Action State's witness takes a real stamp (evidencebook-skills#359).

A witness whose home page answers can still refuse or drop every stamp (Steven's run at 2fa6abe: "Its home page answered
in 0.15 s all night, but stamps timed out or were refused"). So this check makes a real stamp and waits for the
witness's receipt:

1. A throwaway capsulectl-deal profile in a new temporary folder (``deal init``, which names Action State's hosted
   witness, capsulectl's default). Its log id is random per ``deal init`` (evidencebook
   ``capsulectl/internal/deal/deal.go``), so the check never touches a person's or a demo deal's log and cannot advance
   or fork one. The folder is deleted afterwards.
2. On-demand stamps (``deal tick --now``) for up to :data:`WAIT_S` seconds, until one tick reports a checkpoint
   ``delivered``: the witness answered it with a receipt capsulectl checked.
3. A refusal for good (any answered 4xx but 403, which capsulectl records as "not retried", capsule-cli
   ``cli/checkpoint.go``) fails at once; a witness not reached, timing out or answering 403 or 5xx fails once the wait
   is over. Each failure is one plain line; capsulectl's own output goes to a log file, never to the screen.

What one check writes to the witness: the checkpoints of one new, empty log (hashes, a size and a time, never content).

    python demo/ard/witness_check.py      # exit 0 when the witness took the stamp, 1 when not

It needs ``ARD_EVIDENCEBOOK`` (the Goose reference's ``Ctl``) and ``CAPSULECTL_DEAL``, as the demo does. With
``ARD_WITNESS=off`` the demo names no witness, so there is nothing to check and it says so."""
from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _paths  # noqa: E402

#: How long the check waits for the witness to take a stamp. A well witness takes one in 3 to 6 s (party.STAMP_TRY_S).
WAIT_S = 30
#: The witness's name in what a person reads (party.WITNESS_NAME, kept here so the check needs none of the demo's
#: heavier modules).
WITNESS_NAME = "Action State's witness"
PROFILE = "ard-witness-check"
_HTTP = re.compile(r"HTTP (\d{3})")


@dataclass
class Result:
    ok: bool
    line: str


def _status(text: str) -> str:
    m = _HTTP.search(text or "")
    return m.group(1) if m else ""


def classify(tick: dict) -> Result | None:
    """What one ``deal tick --now`` result says about the witness: taken, refused for good, or ``None`` (not yet: try
    again while the wait lasts)."""
    # A refusal first: a tick can deliver an older checkpoint and have the witness refuse the newer one for good, which
    # is the failure this check is for (capsulectl keeps each row's result, evidencebook deal_cadence.go).
    for p in tick.get("pending") or []:
        text = p.get("text", "")
        if p.get("reason") == "witness_error" and "not retried" in text:
            code = _status(text)
            return Result(False, f"{WITNESS_NAME} answered but refused a test stamp"
                          + (f" (HTTP {code})" if code else "")
                          + ". Its home page may still load, but the demo's records would not be time-stamped.")
    if tick.get("delivered"):
        return Result(True, f"{WITNESS_NAME} took a test stamp.")
    return None


def last_reason(tick: dict) -> str:
    """The plain line for a wait that ended without a stamp taken, from the last tick's pending rows."""
    reasons = {p.get("reason"): p.get("text", "") for p in tick.get("pending") or []}
    if "network_consent_needed" in reasons:
        return f"{WITNESS_NAME} could not be reached: check this Mac's network."
    if "witness_timeout" in reasons:
        return f"{WITNESS_NAME} did not answer a test stamp in time."
    for reason, text in reasons.items():
        if reason in ("witness_error", "refused") and (code := _status(text)):
            return f"{WITNESS_NAME} answered a test stamp with an error (HTTP {code})."
    return f"{WITNESS_NAME} took no test stamp."


def check(say: Callable[[str], None] = print, log: Path | None = None, endpoint: str = "",
          wait_s: float = WAIT_S) -> Result:
    """Make a real stamp on a throwaway log and wait for the witness to take it. ``endpoint`` (tests only) points the
    throwaway profile at another witness; ``log`` collects capsulectl's own output."""
    if os.environ.get("ARD_WITNESS", "public") == "off":
        return Result(True, "ARD_WITNESS=off: this run names no witness, so there is none to check.")
    _paths.setup()
    from ctl import Ctl, Refused  # noqa: E402

    home = Path(tempfile.mkdtemp(prefix="ard-witness-check-"))

    def note(line: str) -> None:
        if log is not None:
            with open(log, "a") as fh:
                fh.write(line.rstrip() + "\n")

    try:
        ctl = Ctl(home, PROFILE, os.environ.get("CAPSULECTL_DEAL"))
        try:
            ctl.run("init", "--dir", str(home / "deal"))
            if endpoint:
                prof = home / ".config" / "capsule" / "profiles" / f"{PROFILE}.yaml"
                prof.write_text(re.sub(r"(?m)^(\s*endpoint:).*$", rf"\1 {endpoint}", prof.read_text()))
        except Refused as exc:
            note(f"deal init: {exc}")
            return Result(False, "The witness check could not make its test log: capsulectl-deal refused "
                                 "(is the set-up done?).")
        stop, tick = time.monotonic() + wait_s, {}
        while True:
            try:
                tick = ctl.run("tick", "--now")
            except Refused as exc:
                tick = {}
                note(f"deal tick --now: {exc}")
            else:
                note(f"deal tick --now: {tick}")
            if (r := classify(tick)) is not None:
                return r
            if time.monotonic() >= stop:
                return Result(False, last_reason(tick))
            time.sleep(min(2.0, max(0.0, stop - time.monotonic())))
    finally:
        shutil.rmtree(home, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    log = Path(tempfile.mkstemp(prefix="ard-witness-check-", suffix=".log")[1])
    try:
        r = check(log=log)
    except _paths.SetupError as exc:
        print(f"The witness check cannot run: {exc}.", file=sys.stderr)
        return 1
    if r.ok:
        log.unlink(missing_ok=True)
        print(r.line)
        return 0
    print(r.line, file=sys.stderr)
    print(f"The details are in {log}.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
