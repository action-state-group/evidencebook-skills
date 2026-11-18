# SPDX-License-Identifier: Apache-2.0
"""Where the demo finds what it does not hold itself.

The demo lives in evidencebook-skills (``demo/ard``) beside the skills it runs and its pack. It uses
evidencebook's Goose loop reference (``python/examples/goose``: the node, its x-deal-v0 deal chains,
the mailbox carriage) and that repository's x-deal-v0 reference checker, from a pinned evidencebook
checkout named by ``ARD_EVIDENCEBOOK``. Nothing is copied (design note
``docs/design/ard-buyer-seller-skills.md`` §3.6 item 9)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

#: This repository's root: the skills, the packs and the pack compiler.
ROOT = Path(__file__).resolve().parents[2]


class SetupError(RuntimeError):
    pass


def is_checkout(path: str | Path) -> bool:
    """Whether ``path`` is an evidencebook checkout the demo can use (it holds the Goose reference)."""
    return (Path(path) / "python" / "examples" / "goose" / "goose_node.py").is_file()


def evidencebook() -> Path:
    """The pinned evidencebook checkout (``ARD_EVIDENCEBOOK``)."""
    path = os.environ.get("ARD_EVIDENCEBOOK")
    if not path or not is_checkout(path):
        raise SetupError("set ARD_EVIDENCEBOOK to an evidencebook checkout at the commit the run sheet pins "
                         "(it holds python/examples/goose and dealprofile/x-deal-v0)")
    return Path(path)


def setup() -> None:
    """Put the Goose reference on the import path and point its node at the x-deal-v0 checker."""
    root = evidencebook()
    goose = str(root / "python" / "examples" / "goose")
    if goose not in sys.path:
        sys.path.insert(0, goose)
    os.environ.setdefault("GOOSE_CHECK_PROFILE", str(root / "dealprofile" / "x-deal-v0" / "check_profile.py"))
