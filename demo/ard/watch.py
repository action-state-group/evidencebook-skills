#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The screen of a testbed role that runs no agent: the witness, the payment rail, the catalog stand-in or the
countersigner (evidencebook-skills#382).

    python watch.py witness|rail|catalog|countersigner [--home DIR] [--once]

Prints what that role saw so far, then each new event as it comes (:mod:`feeds`), until Ctrl-C or ``demo.py reset``,
which stops it like the demo's other processes (it holds ``<home>/.watch-<role>.lock``). The witness's screen gives each
deal's stamp a line and folds each party's routine stamps into one line at the bottom (:func:`feeds.witness_screen`).
``--once`` prints what is there and ends. ``testbed.py up`` opens one Terminal window for each."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import feeds  # noqa: E402
from cast import label  # noqa: E402

DEFAULT_HOME = "~/.config/ard-commerce-demo"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="watch.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("role", choices=feeds.ROLES)
    ap.add_argument("--home", default=DEFAULT_HOME)
    ap.add_argument("--once", action="store_true", help="print what the role saw so far and end")
    args = ap.parse_args(argv)
    home = Path(os.environ.get("ARD_HOME", args.home)).expanduser()
    sys.stdout.reconfigure(line_buffering=True)
    print(feeds.HEADINGS[args.role])
    if args.role == "catalog":
        from cast import catalog

        print("\n".join(feeds.catalog_lines(catalog(), label)))
    print()
    if args.once:
        if feeds.path(home, args.role).is_file():
            events = [json.loads(line) for line in feeds.path(home, args.role).read_text().splitlines()]
            if args.role == "witness":
                deals, routine = feeds.witness_screen(events, label)
                print("\n".join(deals + ([""] if deals and routine else []) + routine))
            else:
                for event in events:
                    print(feeds.words(args.role, event, label))
        return 0
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = open(home / f".watch-{args.role}.lock", "w")  # held while this runs, so reset finds and stops it
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"The {args.role}'s screen is already open in another window.")
        return 1
    try:
        if args.role == "witness":
            witness(home, sys.stdout)
        for event in feeds.follow(home, args.role):
            print(feeds.words(args.role, event, label))
    except KeyboardInterrupt:
        return 0
    return 0


def witness(home: Path, out, poll_s: float = 0.5) -> None:
    """The witness's screen as its feed grows: each deal's stamp line once, as it comes, so the terminal keeps them
    all in its scrollback, and below them each party's folded routine line, written over in place on a terminal (on
    anything else, again each time it changes). A deal stamp's line is printed again when it changes (sent, then
    time-stamped). Never ends."""
    events: list[dict] = []
    printed: set[str] = set()
    footer: list[str] = []
    tty = out.isatty()
    for batch in feeds.batches(home, "witness", poll_s):
        events += batch
        deals, routine = feeds.witness_screen(events, label)
        new = [line for line in deals if line not in printed]
        if not new and routine == footer:
            continue
        if tty and footer:
            out.write(f"\x1b[{_rows(footer)}A\x1b[J")  # up over the old footer, and clear to the end of the screen
        for line in new:
            out.write(line + "\n")
        printed.update(new)
        if tty or routine != footer:
            for line in routine:
                out.write(line + "\n")
        footer = routine
        out.flush()


def _rows(lines: list[str]) -> int:
    """How many terminal rows the lines take, wrapped at the terminal's width now."""
    width = max(shutil.get_terminal_size().columns, 1)
    return sum(max(1, -(-len(line) // width)) for line in lines)


if __name__ == "__main__":
    sys.exit(main())
