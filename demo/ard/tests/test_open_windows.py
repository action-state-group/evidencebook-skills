# SPDX-License-Identifier: Apache-2.0
"""``goose/open-windows.py`` opens the sellers first and Maya last, then tiles the windows with the Move & Resize menu;
a failed tile prints one line with the permission to grant and the manual fallback, and never fails the open.
No Goose and no osascript run: ``subprocess.run`` is recorded."""
from __future__ import annotations

import importlib.util
import shlex
import subprocess
import types
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("open_windows_tile", HERE / "goose" / "open-windows.py")
ow = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ow)


@pytest.fixture
def calls(monkeypatch):
    """Every subprocess.run the script makes, with a link per role and no waiting; osascript answers as ``result``."""
    class Made(list):
        result: dict

    made = Made()
    result = {"code": 0, "stderr": "", "raise": None}

    def run(cmd, **kw):
        made.append(list(cmd))
        if cmd[0] == "osascript":
            if result["raise"]:
                raise result["raise"]
            return types.SimpleNamespace(returncode=result["code"], stdout="", stderr=result["stderr"])
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(ow.subprocess, "run", run)
    monkeypatch.setattr(ow.time, "sleep", lambda s: None)
    monkeypatch.setattr(ow, "link", lambda role, rail: f"goose://recipe?config={role}")
    monkeypatch.setattr(ow.envhelp, "message", lambda *a, **k: None)
    monkeypatch.setattr(ow.reset, "snapshot_trust", lambda home: made.append(["snapshot", str(home)]))
    made.result = result
    return made


def test_the_sellers_open_first_maya_last_then_the_windows_are_tiled(calls, capsys):
    assert ow.main(["--rail", "fake"]) == 0
    assert calls[0][0] == "snapshot"  # the trust note comes before any window can be trusted
    assert [c[1] for c in calls[1:4]] == [f"goose://recipe?config={r}" for r in ("alder", "kestrel", "maya")]
    assert calls[4] == ow.TILE and len(calls) == 5
    assert 'click menu item "Left & Quarters" of menu "Move & Resize"' in ow.TILE[-1]
    assert all('tell application "System Events"' in line for line in ow.TILE[2::2])  # one permission: System Events only
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("code,stderr,exc,why,grant", [
    (1, "execution error: osascript is not allowed assistive access. (-1719)", None, "not allowed assistive access", True),
    (1, "execution error: Not authorized to send Apple events to System Events. (-1743)", None, "(-1743)", True),
    (0, "", subprocess.TimeoutExpired("osascript", 30), "timed out", True),  # a pending permission prompt
    (1, "execution error: Can't get menu item \"Left & Quarters\".\n(-1728)", None, "Can't get menu item", False),
    (1, "", None, "osascript exit 1", False),
    (0, "", FileNotFoundError("osascript"), "osascript", False),
])
def test_a_failed_tile_prints_one_line_with_the_manual_fallback_and_the_open_still_succeeds(calls, capsys, code, stderr, exc, why, grant):
    calls.result.update(code=code, stderr=stderr, **{"raise": exc})
    assert ow.main(["--rail", "fake"]) == 0
    err = capsys.readouterr().err.strip().splitlines()
    assert len(err) == 2 and why in err[0]  # the message on one line even when osascript printed two, then the retry
    assert ("System Settings, Privacy & Security, Accessibility" in err[0]) is grant  # the grant only for a permission
    assert err[0].endswith("tile by hand: Window, Move & Resize, Left & Quarters.")
    assert shlex.split(err[1]) == ow.TILE  # the exact command, ready to paste into a shell


@pytest.mark.parametrize("args", [["--print"], ["--only", "maya"]])
def test_print_and_a_single_window_tile_nothing(calls, args):
    assert ow.main(["--rail", "fake", *args]) == 0
    assert all(c[0] != "osascript" for c in calls)
    assert any(c[0] == "snapshot" for c in calls) is (args[0] == "--only")  # --print opens nothing, so it notes nothing
