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
