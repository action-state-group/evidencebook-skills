# SPDX-License-Identifier: Apache-2.0
"""``demo.py`` and ``goose/open-windows.py`` with no command, ``--help`` or a missing variable: a help message that
lists the commands and every variable with its export line, or one message naming what is missing, never a
traceback (Ethan, 2026-11-18)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import envhelp

DEMO = Path(__file__).resolve().parents[1]
SETUP = ("ARD_EVIDENCEBOOK", "CAPSULE_ENGINE", "CAPSULECTL_DEAL", "ARD_WALLET_BUYER", "ARD_WALLET_SELLER", "ARD_PAY_LOCAL", "ARD_HOME")


def _run(script: str, *args: str, **env: str) -> subprocess.CompletedProcess:
    clean = {k: v for k, v in os.environ.items() if k not in SETUP} | env
    return subprocess.run([sys.executable, str(DEMO / script), *args], env=clean, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=60)


@pytest.mark.parametrize("args", [(), ("--help",), ("-h",)])
def test_demo_with_no_command_or_help_prints_the_commands_and_the_environment(args):
    run = _run("demo.py", *args)
    assert run.returncode == (2 if not args else 0)
    out = run.stdout
    for text in ("seed", "run", "reset", "Environment:", "ARD_EVIDENCEBOOK", "CAPSULE_ENGINE", "CAPSULECTL_DEAL",
                 "ARD_WALLET_BUYER", "ARD_WALLET_SELLER", "needed by seed, run", "with --rail local", "reset needs none of them",
                 "export ARD_EVIDENCEBOOK=/path/to/evidencebook CAPSULE_ENGINE=/path/to/capsule-engine CAPSULECTL_DEAL=/path/to/capsulectl-deal"):
        assert text in out, text
    assert "Traceback" not in run.stderr


@pytest.mark.parametrize("command,rail,missing", [
    ("seed", "fake", ["ARD_EVIDENCEBOOK"]),
    ("run", "fake", ["ARD_EVIDENCEBOOK", "CAPSULE_ENGINE", "CAPSULECTL_DEAL"]),
    ("run", "local", ["ARD_EVIDENCEBOOK", "CAPSULE_ENGINE", "CAPSULECTL_DEAL", "ARD_WALLET_BUYER", "ARD_WALLET_SELLER"]),
])
def test_a_missing_variable_is_one_message_with_the_export_line_not_a_traceback(command, rail, missing):
    run = _run("demo.py", command, "--rail", rail)
    assert run.returncode != 0 and "Traceback" not in run.stderr
    assert f"{command} needs these environment variables, which are not set: {', '.join(missing)}." in run.stderr
    export = next(line for line in run.stderr.splitlines() if line.strip().startswith("export "))
    assert export.split()[1:] == [f"{v.name}={v.example}" for v in envhelp.VARS if v.name in missing]


def test_a_set_variable_that_points_nowhere_is_named(tmp_path):
    run = _run("demo.py", "seed", ARD_EVIDENCEBOOK=str(tmp_path))
    assert run.returncode != 0 and "Traceback" not in run.stderr
    assert f"ARD_EVIDENCEBOOK={tmp_path} is not an evidencebook checkout" in run.stderr


def test_a_set_environment_passes_the_check(tmp_path, monkeypatch):
    goose = tmp_path / "eb" / "python" / "examples" / "goose"
    goose.mkdir(parents=True)
    (goose / "goose_node.py").write_text("")
    exe = tmp_path / "bin"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    monkeypatch.setenv("ARD_EVIDENCEBOOK", str(tmp_path / "eb"))
    monkeypatch.setenv("CAPSULE_ENGINE", str(exe))
    monkeypatch.setenv("CAPSULECTL_DEAL", str(exe))
    assert envhelp.message("run") is None and envhelp.message("seed") is None
    assert "ARD_WALLET_BUYER" in envhelp.message("run", "local")
    monkeypatch.delenv("ARD_EVIDENCEBOOK")
    assert envhelp.message("reset") is None  # reset needs none


def test_open_windows_help_and_missing_variables():
    help_run = _run("goose/open-windows.py", "--help")
    assert help_run.returncode == 0 and "Environment:" in help_run.stdout and "needed by open-windows.py" in help_run.stdout
    run = _run("goose/open-windows.py", "--rail", "local")
    assert run.returncode == 2 and "Traceback" not in run.stderr
    assert ("open-windows.py needs these environment variables, which are not set: ARD_EVIDENCEBOOK, CAPSULE_ENGINE, "
            "CAPSULECTL_DEAL, ARD_WALLET_BUYER, ARD_WALLET_SELLER.") in run.stderr
    assert "export ARD_EVIDENCEBOOK=/path/to/evidencebook" in run.stderr
