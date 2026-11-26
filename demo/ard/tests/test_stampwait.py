# SPDX-License-Identifier: Apache-2.0
"""The end-to-end test's witness waits (evidencebook-skills#370): a slow witness reads as the witness not having stamped
yet, a wait that ends with nothing pending does not read as the witness, and a refused tick is tried again. No network:
stub ticks and a stub clock."""
from __future__ import annotations

import pytest

from _stampwait import stamp_wait, try_tick, witness_line
from party import Refused

# A tick as capsulectl-deal's `deal tick --now` gives it with a slow witness (2026-11-26, a throwaway log).
SLOW = {"checkpoint": 7, "delivered": [], "pending": [
    {"checkpoint": 3, "reason": "witness_timeout", "text": "pending: the witness was reached but its answer did not come in time"},
    {"checkpoint": 4, "reason": "not_attempted", "not_tried_this_run": True},
    {"checkpoint": 7, "reason": "not_attempted", "not_tried_this_run": True}]}
TAKEN = {"checkpoint": 9, "delivered": [3, 4, 7, 9], "pending": []}


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.now += s


def test_a_slow_witness_reads_as_the_witness_not_having_stamped_yet():
    clock, calls = Clock(), []
    with pytest.raises(pytest.fail.Exception) as e:
        stamp_wait(lambda: calls.append(1), "Kestrel's card counting the ruling", 180, step=2, tick=lambda: SLOW,
                   clock=clock, sleep=clock.sleep)
    assert str(e.value) == ("Action State's witness had not stamped Kestrel's card counting the ruling within 180 s "
                            "(checkpoint 3: witness_timeout; 2 more not sent yet)")
    assert clock.now == 180 and len(calls) == 91  # tried every 2 s up to the bound, and once at it


def test_nothing_pending_does_not_read_as_a_slow_witness():
    clock = Clock()
    with pytest.raises(pytest.fail.Exception) as e:
        stamp_wait(lambda: None, "Kestrel's card counting the ruling", 180, tick=lambda: TAKEN,
                   detail=lambda: "The card read did_not_hold 0.", clock=clock, sleep=clock.sleep)
    assert str(e.value) == ("Kestrel's card counting the ruling: not seen within 180 s; the last stamp left nothing "
                            "pending at Action State's witness. The card read did_not_hold 0.")
    assert "had not stamped" not in str(e.value)


def test_no_tick_says_only_what_the_caller_saw():
    assert witness_line("both parties' entries of the ruling", 180, None, "The entry check read ['entered'].") == (
        "both parties' entries of the ruling: not seen within 180 s. The entry check read ['entered'].")


def test_a_stamp_that_could_not_be_made_says_so():
    assert witness_line("x", 30, {"error": "capsulectl-deal: profile locked"}) == (
        "x: not seen within 30 s; the last stamp could not be made: capsulectl-deal: profile locked")


def test_it_returns_as_soon_as_the_wait_is_met():
    clock, seen = Clock(), iter([None, None, {"ok": 1}])
    assert stamp_wait(lambda: next(seen), "x", 180, clock=clock, sleep=clock.sleep) == {"ok": 1}
    assert clock.now == 4


def test_a_refused_tick_is_kept_for_the_next_round_and_the_wait_goes_on():
    clock, answers = Clock(), iter([Refused("capsulectl-deal: profile locked"), TAKEN])
    last: list[dict] = []

    def tick() -> dict:
        a = next(answers)
        if isinstance(a, Exception):
            raise a
        return a

    def pred():
        last.append(try_tick(tick))
        return last[-1] if last[-1].get("delivered") else None
    assert stamp_wait(pred, "x", 180, clock=clock, sleep=clock.sleep) == TAKEN
    assert last[0] == {"error": "capsulectl-deal: profile locked"} and clock.now == 2
