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


def needs_engine() -> bool:
    return bool(os.environ.get("CAPSULE_ENGINE"))


engine_only = pytest.mark.skipif(not needs_engine(), reason="CAPSULE_ENGINE names the evaluator")

_SEEDED: dict[str, Path] = {}


@pytest.fixture(scope="session")
def seeded_home(tmp_path_factory):
    """``seeded_home(dest, kestrel_card)`` fills ``dest`` with a copy of a seeded demo home. Seeding the sample
    history takes about 35 s on CI, so each test process seeds once per ``kestrel_card`` mode and every module gets
    its own copy (nodes open their books by paths under the home, so a copy is a home of its own)."""
    import shutil

    def make(dest: Path, kestrel_card: str = "sentinel") -> Path:
        if kestrel_card not in _SEEDED:
            import seed
            from world import World

            home = tmp_path_factory.mktemp(f"seeded-{kestrel_card}")
            with World(home) as world:
                seed.seed(world, say=lambda *_: None, kestrel_card=kestrel_card)
            _SEEDED[kestrel_card] = home
        shutil.copytree(_SEEDED[kestrel_card], dest, dirs_exist_ok=True)
        return dest

    return make
