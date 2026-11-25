# SPDX-License-Identifier: Apache-2.0
"""Fail when the vendored capsule-viewer History script is older than capsule-viewer's newest release
(evidencebook-skills#316): a viewer fix then never reaches the demo's pages, as happened with 0.25.0 twice (#264,
#271). capsule-viewer tags each npm release ``ts/vX.Y.Z``; CI runs this with network, against the repository's tags.

    python demo/ard/viewer_drift.py     # exit 0 when the vendored copy is the newest release, 1 when it is behind
"""
from __future__ import annotations

import re
import subprocess
import sys

REPO = "https://github.com/action-state-group/capsule-viewer"


def version(text: str) -> tuple[int, ...]:
    return tuple(int(x) for x in text.split("."))


def newest(tags: list[str]) -> str | None:
    """The newest ``X.Y.Z`` among tag names of the form ``ts/vX.Y.Z`` (refs and peeled ``^{}`` names allowed)."""
    found = [m.group(1) for t in tags if (m := re.search(r"ts/v(\d+\.\d+\.\d+)(\^\{\})?$", t.strip()))]
    return max(found, key=version) if found else None


def behind(vendored: str, tags: list[str]) -> str | None:
    """The newest release when the vendored version is older than it, else None."""
    latest = newest(tags)
    return latest if latest and version(vendored) < version(latest) else None


def vendored_version() -> str:
    """The version pages.VIEWER names, read from pages.py's text (importing pages needs the demo's environment)."""
    from pathlib import Path
    text = (Path(__file__).resolve().parent / "pages.py").read_text()
    m = re.search(r'^VIEWER = "capsule-viewer-(\d+\.\d+\.\d+)"$', text, re.M)
    if not m:
        raise SystemExit("pages.py names no VIEWER = \"capsule-viewer-X.Y.Z\"")
    return m.group(1)


def main() -> int:
    vendored = vendored_version()
    out = subprocess.run(["git", "ls-remote", "--tags", REPO, "ts/v*"], capture_output=True, text=True,
                         stdin=subprocess.DEVNULL, timeout=60, check=True).stdout
    latest = behind(vendored, out.splitlines())
    if latest:
        print(f"demo/ard vendors capsule-viewer {vendored}, but {latest} is released: vendor "
              f"@action-state-group/capsule-viewer@{latest}'s dist/history-view.iife.js with its .sha256 and licences, "
              f"and update pages.VIEWER and pages.VIEWER_SHA256", file=sys.stderr)
        return 1
    print(f"capsule-viewer {vendored} is the newest release ({newest(out.splitlines())})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
