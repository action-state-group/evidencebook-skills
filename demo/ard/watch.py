#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The screen of a testbed role that runs no agent: the witness or the payment rail (evidencebook-skills#382).

    python watch.py witness|rail [--home DIR] [--once]

Prints what that role saw so far, then each new event as it comes (:mod:`feeds`), until Ctrl-C or ``demo.py reset``,
which stops it like the demo's other processes (it holds ``<home>/.watch-<role>.lock``). ``--once`` prints what is
there and ends. ``testbed.py up`` opens one Terminal window for each."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
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
    print(feeds.HEADINGS[args.role] + "\n")
    if args.once:
        if feeds.path(home, args.role).is_file():
            for line in feeds.path(home, args.role).read_text().splitlines():
                print(feeds.words(args.role, json.loads(line), label))
        return 0
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = open(home / f".watch-{args.role}.lock", "w")  # held while this runs, so reset finds and stops it
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"The {args.role}'s screen is already open in another window.")
        return 1
    try:
        for event in feeds.follow(home, args.role):
            print(feeds.words(args.role, event, label))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
