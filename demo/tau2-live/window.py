# SPDX-License-Identifier: Apache-2.0
"""The demo's window books: which book (deal profile) a record time falls in.

The report side splits a holder's records into books by a configurable window
(evidencebook#689). The library does not do this yet, so the demo does it here
and nowhere else: one capsulectl deal profile per window, named
``<holder>-<window id>``. When #689 lands this module is the one to replace.

Not here (#689 requirements 2 and 4): a link from one window's book to the
next, and a check that consecutive books cover a period with no gap.
"""
from __future__ import annotations

from datetime import datetime, timezone

WINDOWS = ("day", "month", "year")


def window_id(at: datetime, window: str) -> str:
    """The window an instant falls in, read in UTC: ``2026-11-23``, ``2026-11`` or ``2026``."""
    if window not in WINDOWS:
        raise ValueError(f"window must be one of {', '.join(WINDOWS)}, not {window!r}")
    if at.tzinfo is None:
        raise ValueError("a naive time has no window: give it a timezone")
    at = at.astimezone(timezone.utc)
    if window == "day":
        return at.strftime("%Y-%m-%d")
    if window == "month":
        return at.strftime("%Y-%m")
    return at.strftime("%Y")


def book_name(holder: str, at: datetime, window: str) -> str:
    """The deal profile that holds a record sealed at ``at``."""
    return f"{holder}-{window_id(at, window)}"
