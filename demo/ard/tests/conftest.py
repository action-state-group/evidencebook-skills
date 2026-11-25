# SPDX-License-Identifier: Apache-2.0
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import _paths  # noqa: E402

_paths.setup()
os.environ.setdefault("CAPSULE_WITNESS", "off")
# Every agreement names Action State's hosted witness by default (party.WITNESS_URL); the unit tests never reach it, and
# only tests/test_e2e.py turns it back on.
os.environ.setdefault("ARD_WITNESS", "off")
# pytest-xdist workers compile the pack at the same time: each compiles into a folder of its own (pack.compile_source),
# and the servers a test starts inherit it.
if os.environ.get("PYTEST_XDIST_WORKER"):
    os.environ["ARD_PACK_WORK"] = os.environ["PYTEST_XDIST_WORKER"]


def needs_engine() -> bool:
    return bool(os.environ.get("CAPSULE_ENGINE"))


engine_only = pytest.mark.skipif(not needs_engine(), reason="CAPSULE_ENGINE names the evaluator")

_SEEDED: dict[str, Path] = {}


@pytest.fixture(scope="session")
def seeded_home(tmp_path_factory):
    """``seeded_home(dest, kestrel_card)`` fills ``dest`` with a copy of a seeded demo home. Seeding the sample
    history takes about 35 s on CI, so each test process seeds once per ``kestrel_card`` mode and every module gets
    its own copy (nodes open their books by paths under the home, so a copy is a home of its own)."""
    import fcntl
    import shutil

    # Under pytest-xdist the workers share the parent of their base temp, so they seed each mode once between them.
    root = tmp_path_factory.getbasetemp()
    if os.environ.get("PYTEST_XDIST_WORKER"):
        root = root.parent

    def make(dest: Path, kestrel_card: str = "sentinel") -> Path:
        if kestrel_card not in _SEEDED:
            home, done = root / f"seeded-{kestrel_card}", root / f"seeded-{kestrel_card}.done"
            with open(root / f"seeded-{kestrel_card}.lock", "w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)  # one process seeds; the others wait, then copy
                if not done.exists():
                    import seed
                    from world import World

                    shutil.rmtree(home, ignore_errors=True)  # a seed cut off part way is not reused
                    with World(home) as world:
                        seed.seed(world, say=lambda *_: None, kestrel_card=kestrel_card)
                    done.touch()
            _SEEDED[kestrel_card] = home
        shutil.copytree(_SEEDED[kestrel_card], dest, dirs_exist_ok=True)
        return dest

    return make
