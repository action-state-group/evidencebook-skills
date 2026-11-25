# SPDX-License-Identifier: Apache-2.0
"""How the parties hand each other files: a folder per receiver under the stage (``<home>/stage/wire/<to>/``), one
file per deal step, named ``<deal id>.<kind>.json``. A file is what a capsulectl verb wrote for the other side (an
offer, an agreement, a leg, an act, a statement, a dispute, a ruling's naming statement), copied whole; the receiver
keeps it with ``deal receive``, which checks it. Nothing here reads or changes a file's contents.

The kinds, in a deal's order: ``offer`` (buyer to seller), ``agree`` (each way), ``paid`` (the buyer's payer leg, with
the payment reference beside it), ``received`` (the seller's payee leg), ``act`` (the seller's delivery), ``dispute``
(the buyer's), ``case`` (the adjudicator case and ruling a party learned of), ``named`` (a party's statement naming
the ruling it entered)."""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from party import Refused


def _dir(home: Path, to: str) -> Path:
    d = Path(home).expanduser() / "stage" / "wire" / to
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def path(home: Path, to: str, deal_id: str, kind: str) -> Path:
    return _dir(home, to) / f"{deal_id}.{kind}.json"


def send(home: Path, to: str, deal_id: str, kind: str, file: str | Path) -> Path:
    """Hand ``file`` (what a verb wrote) to ``to``."""
    dest = path(home, to, deal_id, kind)
    tmp = dest.with_name(dest.name + ".tmp")
    shutil.copyfile(file, tmp)
    tmp.replace(dest)
    return dest


def send_json(home: Path, to: str, deal_id: str, kind: str, doc: dict) -> Path:
    dest = path(home, to, deal_id, kind)
    write_atomic(dest, json.dumps(doc).encode())
    return dest


def wait(home: Path, me: str, deal_id: str, kind: str, seconds: float) -> Path:
    """The file of ``kind`` for this deal, once it arrives in ``me``'s folder."""
    f = path(home, me, deal_id, kind)
    stop = time.time() + seconds
    while time.time() < stop:
        if f.is_file():
            return f
        time.sleep(0.3)
    raise Refused(f"no {kind} from the other side in {int(seconds)} s")


def pending(home: Path, me: str, kind: str) -> list[tuple[str, Path]]:
    """The deal ids and files of ``kind`` in ``me``'s folder, oldest first."""
    d = _dir(home, me)
    files = sorted(d.glob(f"*.{kind}.json"), key=lambda p: p.stat().st_mtime)
    return [(f.name[: -len(f".{kind}.json")], f) for f in files]
