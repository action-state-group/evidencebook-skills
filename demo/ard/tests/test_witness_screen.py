# SPDX-License-Identifier: Apache-2.0
"""The witness's screen (evidencebook-skills#458): every stamp a party's book cuts reaches it with its party, the ones
``deal agree`` and ``deal ruling`` cut inside capsulectl included, numbered only as capsulectl numbers them; each deal's
stamp has its own line in Sherlock2's words, and each party's routine stamps fold into one line."""
from __future__ import annotations

import io
import json
import os
import random
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
import feeds  # noqa: E402
import watch  # noqa: E402
from cast import label  # noqa: E402

W = "Action State's witness"


def _ticked(no, size, delivered=(), numbered=True, pending=()):
    """``deal tick`` output that cut stamp ``no`` at ``size`` and delivered ``delivered`` (sizes, with their numbers)."""
    out = {"state": "ticked", "tick": no, "checkpoint": size, "delivered": [s for s, _ in delivered],
           "pending": [dict(p) for p in pending]}
    if numbered:
        out["delivered_ticks"] = [{"checkpoint": s, "tick": n} for s, n in delivered]
    return out


def _not_due(delivered=(), numbered=True, pending=()):
    out = {"state": "not_due", "delivered": [s for s, _ in delivered], "pending": [dict(p) for p in pending]}
    if numbered:
        out["delivered_ticks"] = [{"checkpoint": s, "tick": n} for s, n in delivered]
    return out


def _run(home, numbered=True):
    """A run's ticks as each party's book reports them, with a stamp cut inside ``deal agree`` (Kestrel's no. 20) and
    one inside ``deal ruling`` (the adjudicator's no. 7), each delivered by a later tick."""
    st = lambda party, tick, kind: feeds.stamp(home, party, W, tick, kind)  # noqa: E731
    st("kestrel", _ticked(18, 100, [(100, 18)], numbered), "routine")
    st("kestrel", _ticked(19, 110, [(110, 19)], numbered), "routine")
    # `deal agree` cut no. 20 at size 125 and wrote nothing to the feed; the cadence's next poll delivers it
    st("kestrel", _not_due([(125, 20)], numbered), "routine")
    st("kestrel", _ticked(21, 130, [(130, 21)], numbered), "routine")
    # `deal ruling` cut the adjudicator's no. 7 at size 60; its stamp for the ruling (`deal tick --now`) delivers both
    st("adjudicator", _ticked(8, 70, [(60, 7), (70, 8)], numbered), "deal")
    return [json.loads(x) for x in feeds.path(home, "witness").read_text().splitlines()]


def test_stamps_cut_inside_agree_and_ruling_reach_the_screen_numbered_with_their_party(tmp_path):
    deals, routine = feeds.witness_screen(_run(tmp_path), label)
    assert any(line.endswith("Kestrel Print's book sent hash no. 20; Action State's witness time-stamped it.")
               for line in deals)
    assert any(line.endswith("the adjudicator's book sent hash no. 7; Action State's witness time-stamped it.")
               for line in deals)
    assert any(line.endswith("the adjudicator's book sent hash no. 8; Action State's witness time-stamped it.")
               for line in deals)
    for line in deals:  # every line names whose book: none starts with the witness
        assert re.fullmatch(r"\d\d:\d\d:\d\d  (Kestrel Print|the adjudicator)'s book sent hash no\. \d+; "
                            r"Action State's witness time-stamped it\.", line), line
    # no number skipped: Kestrel's 18 to 21 and the adjudicator's 7 and 8 are all on the screen
    nos = {(h.party, h.no) for h in feeds.witness_hashes(_run(tmp_path / "again"))}
    assert nos == {("kestrel", n) for n in (18, 19, 20, 21)} | {("adjudicator", 7), ("adjudicator", 8)}
    assert routine == ["Kestrel Print's routine stamps, one a minute: its book sent 3 hashes, the last no. 21 at "
                       f"{feeds._clock(_run(tmp_path / 'third')[-2]['at'])}; Action State's witness time-stamped each."]


def test_a_capsulectl_that_does_not_number_what_it_delivers_says_an_earlier_hash(tmp_path):
    # capsulectl v0.1.1 names a delivered checkpoint only by its size: the demo never works its number out from sizes
    deals, _ = feeds.witness_screen(_run(tmp_path, numbered=False), label)
    assert any(line.endswith("Kestrel Print's book sent an earlier hash; Action State's witness time-stamped it.")
               for line in deals)
    assert any(line.endswith("the adjudicator's book sent an earlier hash; Action State's witness time-stamped it.")
               for line in deals)
    assert not any("no. 20" in line or "no. 7" in line for line in deals)
    assert any(line.endswith("the adjudicator's book sent hash no. 8; Action State's witness time-stamped it.")
               for line in deals)  # the stamp a tick cuts carries its own number


def test_the_screen_is_the_same_whatever_order_the_lines_were_written_in(tmp_path):
    events = _run(tmp_path)
    shuffled = events[:]
    random.Random(458).shuffle(shuffled)
    assert feeds.witness_screen(shuffled, label) == feeds.witness_screen(events, label)


def test_a_stamp_still_waiting_never_reads_as_time_stamped(tmp_path):
    feeds.stamp(tmp_path, "alder", W, _ticked(30, 200, pending=[{"checkpoint": 200, "tick": 30, "reason": "slow"}]),
                "deal")
    feeds.stamp(tmp_path, "alder", W, _ticked(31, 210, pending=[
        {"checkpoint": 200, "tick": 30, "reason": "slow"},
        {"checkpoint": 210, "tick": 31, "reason": "waiting", "not_tried_this_run": True}]), "deal")
    events = [json.loads(x) for x in feeds.path(tmp_path, "witness").read_text().splitlines()]
    deals, _ = feeds.witness_screen(events, label)
    assert [d[10:] for d in deals] == [
        "Alder Print Co.'s book sent hash no. 30; Action State's witness has not time-stamped it yet.",
        "Alder Print Co.'s book has hash no. 31 to send; Action State's witness has not received it yet."]
    feeds.stamp(tmp_path, "alder", W, _not_due([(200, 30), (210, 31)]), "routine")
    events = [json.loads(x) for x in feeds.path(tmp_path, "witness").read_text().splitlines()]
    deals, _ = feeds.witness_screen(events, label)
    assert [d[10:] for d in deals] == [
        "Alder Print Co.'s book sent hash no. 30; Action State's witness time-stamped it.",
        "Alder Print Co.'s book sent hash no. 31; Action State's witness time-stamped it."]


def test_routine_stamps_fold_into_one_line_per_party_with_any_still_waiting(tmp_path):
    for n in range(1, 6):
        feeds.stamp(tmp_path, "alder", W, _ticked(n, 10 * n, [(10 * n, n)]), "routine")
    feeds.stamp(tmp_path, "kestrel", W, _ticked(1, 10, [(10, 1)]), "routine")
    feeds.stamp(tmp_path, "kestrel", W, _ticked(2, 20, pending=[{"checkpoint": 20, "tick": 2}]), "routine")
    events = [json.loads(x) for x in feeds.path(tmp_path, "witness").read_text().splitlines()]
    deals, routine = feeds.witness_screen(events, label)
    assert deals == []
    assert len(routine) == 2
    assert re.fullmatch(r"Alder Print Co\.'s routine stamps, one a minute: its book sent 5 hashes, the last no\. 5 at "
                        r"\d\d:\d\d:\d\d; Action State's witness time-stamped each\.", routine[0]), routine[0]
    assert re.fullmatch(r"Kestrel Print's routine stamps, one a minute: its book sent 1 hash, the last no\. 1 at "
                        r"\d\d:\d\d:\d\d; Action State's witness time-stamped it; no\. 2 is waiting for Action State's "
                        r"witness\.", routine[1]), routine[1]


def test_the_feed_never_holds_a_record_and_skips_what_the_witness_never_saw(tmp_path):
    feeds.stamp(tmp_path, "kestrel", W, {**_ticked(4, 27, [(27, 4)]), "witness_sees": "x"}, "routine")
    feeds.stamp(tmp_path, "kestrel", W, {"state": "not_due", "delivered": [], "pending": []})
    feeds.stamp(tmp_path, "kestrel", W, {"state": "ticked", "witness": "not_configured"})
    feeds.stamp(tmp_path, "kestrel", W, {"error": "refused"})
    lines = feeds.path(tmp_path, "witness").read_text().splitlines()
    assert len(lines) == 1  # nothing due, no witness, and an error are no event the witness saw
    assert set(json.loads(lines[0])) == {"at", "party", "witness", "kind", "cut", "delivered", "pending"}


def test_a_feed_line_of_the_earlier_shape_is_left_out(tmp_path):
    old = {"at": "2026-11-27T18:56:49+00:00", "party": "kestrel", "witness": W, "stamp": None, "covers": 9,
           "taken": 1, "waiting": 0}
    assert feeds.witness_screen([old], label) == ([], [])


def test_watch_once_prints_the_folded_witness_screen(tmp_path):
    _run(tmp_path)
    run = subprocess.run([sys.executable, str(HERE / "watch.py"), "witness", "--once", "--home", str(tmp_path)],
                         capture_output=True, text=True, env={k: v for k, v in os.environ.items() if k != "ARD_HOME"})
    assert run.returncode == 0, run.stderr
    assert "Kestrel Print's book sent hash no. 20; Action State's witness time-stamped it." in run.stdout
    assert run.stdout.count("routine stamps, one a minute:") == 1
    assert run.stdout.rstrip().splitlines()[-1].startswith("Kestrel Print's routine stamps")


class _Tty(io.StringIO):
    def isatty(self):
        return True


def test_follow_keeps_deal_lines_and_writes_the_routine_line_over_in_place(tmp_path, monkeypatch):
    events = _run(tmp_path)
    monkeypatch.setattr(watch.feeds, "batches", lambda home, role, poll_s=0.5: iter([events[:2], events[2:4], events[4:]]))
    monkeypatch.setattr(watch.shutil, "get_terminal_size", lambda: os.terminal_size((160, 48)))
    out = _Tty()
    watch.witness(tmp_path, out)
    text = out.getvalue()
    assert text.count("\x1b[1A\x1b[J") == 2  # the routine line written over twice, never piled up
    assert text.count("Kestrel Print's book sent hash no. 20;") == 1  # each deal line once, kept in the scrollback
    shown = re.sub(r"[^\n]*\n\x1b\[1A\x1b\[J", "", text)  # what the terminal shows once each overwrite is applied
    assert shown.count("routine stamps, one a minute:") == 1 and shown.rstrip().splitlines()[-1].startswith("Kestrel Print's routine")


def test_follow_off_a_terminal_writes_the_routine_line_again_only_when_it_changes(tmp_path, monkeypatch):
    events = _run(tmp_path)
    monkeypatch.setattr(watch.feeds, "batches", lambda home, role, poll_s=0.5: iter([events, events[:0] or [events[-1]]]))
    out = io.StringIO()
    watch.witness(tmp_path, out)
    assert "\x1b" not in out.getvalue() and out.getvalue().count("routine stamps, one a minute:") == 1
