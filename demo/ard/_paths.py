# SPDX-License-Identifier: Apache-2.0
"""Where the demo finds what it does not hold itself.

The demo lives in evidencebook-skills (``demo/ard``) beside the skills it runs and its pack. It uses
evidencebook's Goose loop reference (``python/examples/goose``: its ``Ctl``, the one door to the ``capsulectl-deal``
plugin, its ``Node`` for a party's node book, and its commitment), from a pinned evidencebook checkout named by
``ARD_EVIDENCEBOOK``. Nothing is copied (design note ``docs/design/ard-buyer-seller-skills.md`` §3.6 item 9). Every deal
record is capsulectl-deal's."""
from __future__ import annotations

import os
import sys
from pathlib import Path

#: This repository's root: the skills, the packs and the pack compiler.
ROOT = Path(__file__).resolve().parents[2]


class SetupError(RuntimeError):
    pass


def is_checkout(path: str | Path) -> bool:
    """Whether ``path`` is an evidencebook checkout the demo can use: the Goose reference on capsulectl-deal (its
    ``ctl.py``, evidencebook#833 and later)."""
    return (Path(path) / "python" / "examples" / "goose" / "ctl.py").is_file()


def evidencebook() -> Path:
    """The pinned evidencebook checkout (``ARD_EVIDENCEBOOK``)."""
    path = os.environ.get("ARD_EVIDENCEBOOK")
    if not path or not is_checkout(path):
        raise SetupError("set ARD_EVIDENCEBOOK to an evidencebook checkout at the commit the run sheet pins "
                         "(it holds python/examples/goose on capsulectl-deal)")
    return Path(path)


def setup() -> None:
    """Put the Goose reference on the import path."""
    goose = str(evidencebook() / "python" / "examples" / "goose")
    if goose not in sys.path:
        sys.path.insert(0, goose)
