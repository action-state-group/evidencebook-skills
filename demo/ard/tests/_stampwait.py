# SPDX-License-Identifier: Apache-2.0
"""The end-to-end test's waits on Action State's hosted witness (evidencebook-skills#370).

A step that needs a stamp the witness has taken waits as long as the demo itself waits for that stamp, never a fixed
30 s: on 2026-11-26 a witness request took about 13-30 s, over capsulectl's 5 s delivery budget per tick, after which
capsulectl backs off (1 s, doubling), so one stamp took about 70 s through the demo's path. When the wait ends, the
failure says whether the witness had not taken the stamp yet (the last tick's pending checkpoints and their reasons) or
had nothing pending, so a slow witness reads as slow and any other cause does not read as the witness."""
from __future__ import annotations

import time
from typing import Any, Callable

import pytest

from party import Refused, WITNESS_NAME


def try_tick(tick: Callable[[], dict]) -> dict:
    """One ``deal tick``: its result, or ``{"error": ...}`` when capsulectl-deal refused it (tried again on the wait's
    next round, as the seller's agent does)."""
    try:
        return tick()
    except Refused as exc:
        return {"error": str(exc)}


def pending_line(tick: dict) -> str:
    """The pending checkpoints of one ``deal tick`` result, in a few words: the ones capsulectl tried and why each is
    still pending, and how many it has not tried yet (each waits for the oldest)."""
    pending = tick.get("pending") or []
    tried = [p for p in pending if p.get("reason") != "not_attempted" and not p.get("not_tried_this_run")]
    words = [f"checkpoint {p.get('checkpoint')}: {p.get('reason')}" for p in tried[:3]]
    if len(pending) > len(words):
        words.append(f"{len(pending) - len(words)} more not sent yet")
    return "; ".join(words)


def witness_line(what: str, seconds: float, tick: dict | None, detail: str = "") -> str:
    """Why ``what`` was not seen within ``seconds``, from the last tick of the profile the wait stamps: its checkpoints
    the witness had not taken yet and why, the stamp it could not make, or that it left nothing pending (which says
    only that this profile's stamps reached the witness, not that the step waited for is the witness's to finish)."""
    s = f"{int(seconds)} s"
    if tick is None:  # the caller's detail says what it saw
        line = f"{what}: not seen within {s}"
    elif tick.get("error"):
        line = f"{what}: not seen within {s}; the last stamp could not be made: {tick['error']}"
    elif tick.get("pending"):
        line = f"{WITNESS_NAME} had not stamped {what} within {s} ({pending_line(tick)})"
    else:
        line = f"{what}: not seen within {s}; the last stamp left nothing pending at {WITNESS_NAME}"
    return f"{line}. {detail}" if detail else line


def stamp_wait(pred: Callable[[], Any], what: str, seconds: float, step: float = 2,
               tick: Callable[[], dict | None] = lambda: None, detail: Callable[[], str] = lambda: "",
               clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> Any:
    """``pred()``'s first truthy value, tried every ``step`` seconds for up to ``seconds``; otherwise the test fails with
    :func:`witness_line` on the last tick ``tick()`` gives (None when the caller has none) and ``detail()``."""
    stop = clock() + seconds
    while True:
        got = pred()
        if got:
            return got
        if clock() >= stop:
            break
        sleep(step)
    pytest.fail(witness_line(what, seconds, tick(), detail()), pytrace=False)
