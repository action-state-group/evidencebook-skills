# SPDX-License-Identifier: Apache-2.0
"""evidencebook-skills#342 (carried by #340): the RUNBOOK's header is the one place for the pins, so the set-up commands,
the ard-demo CI job and the code's own pins must agree with it."""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import envhelp

HERE = Path(__file__).resolve().parents[1]
RUNBOOK = (HERE / "RUNBOOK.md").read_text()
HEADER = next(line for line in RUNBOOK.splitlines() if line.startswith("This guide runs evidencebook-skills main."))
SETUP = RUNBOOK.split("## Set up, once", 1)[1].split("\n## ", 1)[0]
CI = (HERE.parents[1] / ".github" / "workflows" / "tests.yml").read_text()


def _commit(repo: str, text: str) -> str:
    """The 40-hex commit a set-up line checks out for ``repo``."""
    m = re.search(rf"git -C {repo} checkout -q (?:--detach )?([0-9a-f]{{40}})", text)
    assert m, f"no pinned checkout of {repo} in the set-up"
    return m.group(1)


def test_every_set_up_checkout_is_the_header_pin():
    for repo in ("evidencebook", "capsule-cli", "capsule-engine"):
        full = _commit(repo, SETUP)
        assert f"{repo} {full[:7]}" in HEADER, f"the header names another {repo} than the set-up checks out ({full[:7]})"


def test_the_build_line_uses_the_same_commits():
    assert f"CORE_SHA={_commit('capsule-cli', SETUP)}" in SETUP
    assert f"EB_SHA={_commit('evidencebook', SETUP)}" in SETUP
    assert f"capsulectl v0.1.0-main.{_commit('capsule-cli', SETUP)[:8]}" in HEADER


def test_ci_runs_the_header_evidencebook():
    m = re.search(r"EVIDENCEBOOK_REF: ([0-9a-f]{40})", CI.split("ard-demo:", 1)[1])
    assert m and m.group(1) == _commit("evidencebook", SETUP)


def test_the_code_pins_are_in_the_header():
    spec = importlib.util.spec_from_file_location("ow", HERE / "goose" / "open-windows.py")
    ow = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ow)
    assert f"adapter {ow.ACP_PIN}" in HEADER
    assert f"ln-pay-local {envhelp.LN_PAY_LOCAL_COMMIT[:7]}" in HEADER
    goose = re.search(r"releases/download/v([0-9.]+)/Goose-darwin-arm64.zip", SETUP).group(1)
    assert f"Goose Desktop {goose}" in HEADER
