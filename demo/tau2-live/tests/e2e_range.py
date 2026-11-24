# SPDX-License-Identifier: Apache-2.0
"""The range report through released capsulectl only, on the ended-window fixture.

    uv run python tests/e2e_range.py WORK_DIR

Runs range_report.py's recipe (deal window chain, one deal window respond per window and per
placed deal, book report derive --chain, book report coverage) and checks that coverage names
each placed deal, and that a range answered without its deals' answers is refused with each
missing answer named and no bundle written. Needs capsulectl with the deal and book plugins on
PATH (or CAPSULECTL_PLUGIN_ROOTS). Exits non-zero on the first failed check.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import range_report  # noqa: E402


def check(cond: bool, what: str) -> None:
    print(("ok   " if cond else "FAIL ") + what, flush=True)
    if not cond:
        sys.exit(1)


def main() -> None:
    root = Path(sys.argv[1]).resolve()
    root.mkdir(parents=True, exist_ok=True)

    full = range_report.range_report(root / "full")
    windows = full["chain"]["windows"]
    check([w["label"] for w in windows] == ["2026-09", "2026-10"], "the chain covers the fixture's two ended months")
    deals = [(w["label"], d["log_id"]) for w in windows for d in w["deals"]]
    check(len(deals) == 2, "each window places one deal")
    check(full["bundle"] is not None and full["bundle"].is_file(), "derive --chain wrote the bundle")
    cov = full["coverage"]
    check(cov["covered"] is True, "coverage: the range is covered")
    check(len(cov["deals"]) == 2, "coverage prints one line per placed deal")
    for line, (label, log_id) in zip(cov["deals"], deals):
        check(log_id in line and f"window {label}" in line, f"coverage names deal {log_id} placed in window {label}")
        check("no answer" not in line, f"deal {log_id} has its answer")

    gap = range_report.range_report(root / "gap", answer_deals=False)
    check(gap["bundle"] is None and not (root / "gap" / "bundle.json").exists(),
          "without the deals' answers derive refuses and writes no bundle")
    for label, log_id in deals:
        check(f"{log_id} of window {label} has no answer" in gap["derive_refusal"],
              f"the refusal names the missing answer of deal {log_id} in window {label}")
    print("range report: all checks passed")


if __name__ == "__main__":
    main()
