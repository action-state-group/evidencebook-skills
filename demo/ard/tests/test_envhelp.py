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
                 "export ARD_EVIDENCEBOOK=/path/to/evidencebook CAPSULECTL_DEAL=/path/to/capsulectl-deal "
                 "CAPSULE_ENGINE=/path/to/capsule-engine"):
        assert text in out, text
    assert "Traceback" not in run.stderr


@pytest.mark.parametrize("command,rail,missing", [
    ("seed", "fake", ["ARD_EVIDENCEBOOK", "CAPSULECTL_DEAL", "CAPSULE_ENGINE"]),
    ("run", "fake", ["ARD_EVIDENCEBOOK", "CAPSULECTL_DEAL", "CAPSULE_ENGINE"]),
    ("run", "local", ["ARD_EVIDENCEBOOK", "CAPSULECTL_DEAL", "CAPSULE_ENGINE", "ARD_WALLET_BUYER",
                      "ARD_WALLET_SELLER"]),
])
def test_a_missing_variable_is_one_message_with_the_export_line_not_a_traceback(command, rail, missing):
    run = _run("demo.py", command, "--rail", rail)
    assert run.returncode != 0 and "Traceback" not in run.stderr
    assert f"{command} needs these environment variables, which are not set: {', '.join(missing)}." in run.stderr
    export = next(line for line in run.stderr.splitlines() if line.strip().startswith("export "))
    assert export.split()[1:] == [f"{v.name}={v.example}" for v in envhelp.VARS if v.name in missing]


@pytest.mark.parametrize("value", ["{tmp}", "~nosuchuser-ard/checkout", "~/{rel}"])
def test_a_set_variable_that_points_nowhere_is_named(tmp_path, value):
    # a quoted ~ reaches the demo unexpanded, so the check does not expand it either: named, never a traceback
    value = value.format(tmp=tmp_path, rel=tmp_path.name)
    run = _run("demo.py", "seed", ARD_EVIDENCEBOOK=value)
    assert run.returncode != 0 and "Traceback" not in run.stderr
    assert f"ARD_EVIDENCEBOOK={value} is not an evidencebook checkout" in run.stderr


def test_a_set_environment_passes_the_check(tmp_path, monkeypatch):
    goose = tmp_path / "eb" / "python" / "examples" / "goose"
    goose.mkdir(parents=True)
    (goose / "ctl.py").write_text("")
    exe = tmp_path / "bin"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    monkeypatch.setenv("ARD_EVIDENCEBOOK", str(tmp_path / "eb"))
    monkeypatch.setenv("CAPSULE_ENGINE", str(exe))
    monkeypatch.delenv("CAPSULECTL_DEAL", raising=False)
    for command in ("run", "seed", "windows"):  # every deal record is capsulectl-deal's
        assert "CAPSULECTL_DEAL" in envhelp.message(command)
    monkeypatch.setenv("CAPSULECTL_DEAL", str(exe))
    assert envhelp.message("run") is None and envhelp.message("seed") is None and envhelp.message("windows") is None
    assert "ARD_WALLET_BUYER" in envhelp.message("run", "local")
    wallet = tmp_path / "w"
    wallet.mkdir()
    monkeypatch.setenv("ARD_WALLET_BUYER", str(wallet))
    monkeypatch.setenv("ARD_WALLET_SELLER", str(wallet))
    for bad in (str(tmp_path / "nowhere"), str(tmp_path / "eb")):  # missing, and not an executable file
        monkeypatch.setenv("ARD_PAY_LOCAL", bad)
        assert f"ARD_PAY_LOCAL={bad} is not an executable file" in envhelp.message("run", "local")
    monkeypatch.setenv("ARD_PAY_LOCAL", str(exe))
    assert envhelp.message("run", "local") is None
    assert envhelp.message("run") is None  # the fake rail never reads it
    monkeypatch.delenv("ARD_EVIDENCEBOOK")
    assert envhelp.message("reset") is None  # reset needs none


@pytest.mark.parametrize("script", ["demo.py", "goose/open-windows.py"])
def test_the_help_export_line_sets_every_variable_the_table_lists_as_needed(script):
    out = _run(script, "--help").stdout
    table = out.split("Environment:", 1)[1].split("Set them", 1)[0]
    needed = [line.split()[0] for line in table.splitlines() if "needed by" in line and "--rail local" not in line]
    export = next(line for line in out.splitlines() if line.strip().startswith("export ") and "--rail local" not in line)
    assert needed and [w.split("=")[0] for w in export.split()[1:]] == needed


def test_open_windows_help_and_missing_variables():
    help_run = _run("goose/open-windows.py", "--help")
    assert help_run.returncode == 0 and "Environment:" in help_run.stdout and "needed by open-windows.py" in help_run.stdout
    run = _run("goose/open-windows.py", "--rail", "local")
    assert run.returncode == 2 and "Traceback" not in run.stderr
    assert ("open-windows.py needs these environment variables, which are not set: ARD_EVIDENCEBOOK, CAPSULECTL_DEAL, "
            "CAPSULE_ENGINE, ARD_WALLET_BUYER, ARD_WALLET_SELLER.") in run.stderr
    assert "export ARD_EVIDENCEBOOK=/path/to/evidencebook" in run.stderr


def test_the_ln_pay_local_hint_is_the_pinned_install_everywhere(monkeypatch, tmp_path):
    # never an unpinned `cargo install --git`: the same clone, checkout and install the runbook pins
    import pay

    assert envhelp.LN_PAY_LOCAL_COMMIT in envhelp.LN_PAY_LOCAL_INSTALL and "--git" not in envhelp.LN_PAY_LOCAL_INSTALL
    wallet = tmp_path / "w"
    wallet.mkdir()
    monkeypatch.setenv("ARD_WALLET_BUYER", str(wallet))
    monkeypatch.setenv("ARD_WALLET_SELLER", str(wallet))
    monkeypatch.delenv("ARD_PAY_LOCAL", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))  # no ln-pay-local on it
    with pytest.raises(pay.RailError, match=envhelp.LN_PAY_LOCAL_COMMIT):
        pay.from_env("local")
    assert any(envhelp.LN_PAY_LOCAL_INSTALL in w for w in envhelp.problems("run", "local")[1])


def test_print_needs_no_wallet_and_writes_placeholders(tmp_path):
    goose = tmp_path / "eb" / "python" / "examples" / "goose"
    goose.mkdir(parents=True)
    (goose / "ctl.py").write_text("")
    exe = tmp_path / "bin"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    run = _run("goose/open-windows.py", "--rail", "local", "--print",
               ARD_EVIDENCEBOOK=str(tmp_path / "eb"), CAPSULE_ENGINE=str(exe), CAPSULECTL_DEAL=str(exe))
    assert run.returncode == 0, run.stderr
    assert "placeholder paths for ARD_WALLET_BUYER, ARD_WALLET_SELLER" in run.stderr
    import base64
    import json
    maya = run.stdout.strip().splitlines()[3].split("config=", 1)[1]  # alder, kestrel, the adjudicator, then maya
    recipe = json.loads(base64.urlsafe_b64decode(maya + "=" * (-len(maya) % 4)))
    args = recipe["extensions"][0]["args"]
    assert "ARD_WALLET_BUYER=<buyer wallet dir>" in args and "ARD_WALLET_SELLER=<seller wallet dir>" in args
    opened = _run("goose/open-windows.py", "--rail", "local",
                  ARD_EVIDENCEBOOK=str(tmp_path / "eb"), CAPSULE_ENGINE=str(exe), CAPSULECTL_DEAL=str(exe))
    assert opened.returncode == 2 and "ARD_WALLET_BUYER" in opened.stderr  # opening still needs them


def test_the_ln_pay_local_pin_is_the_runbooks():
    # #320 review: the recovery command installs the commit the RUNBOOK pins, and can be run again
    runbook = (Path(__file__).resolve().parent.parent / "RUNBOOK.md").read_text()
    assert f"git -C $HOME/ard-demo/ln-pay-local checkout -q {envhelp.LN_PAY_LOCAL_COMMIT}" in runbook
    assert envhelp.LN_PAY_LOCAL_INSTALL.startswith("([ -d $HOME/ard-demo/ln-pay-local ] ||")


def test_the_help_names_capsulectl_for_the_countersign_upgrade():
    """Hand run of #396: the run's countersign step uses capsule-cli's capsulectl, so the help names it (optional:
    set-up puts it on the PATH)."""
    text = envhelp.help_text({"run": "the two deals"})
    line = next(x for x in text.splitlines() if x.strip().startswith("CAPSULECTL "))
    assert "countersign" in line and "optional" in text.split("CAPSULECTL ", 1)[1].split("\n  ARD_", 1)[0]
