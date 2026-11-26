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
def calls(monkeypatch, tmp_path):
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
    monkeypatch.setattr(ow, "link", lambda role, rail, placeholders=False: f"goose://recipe?config={role}")
    monkeypatch.setattr(ow.envhelp, "message", lambda *a, **k: None)
    monkeypatch.setattr(ow, "recipe", lambda role, rail, placeholders=False: {"title": role})
    monkeypatch.setattr(ow, "to_link", lambda r: f"goose://recipe?config={r['title']}")
    monkeypatch.setattr(ow.reset, "note_trust", lambda recipes, root: made.append(["note", [r["title"] for r in recipes], str(root)]))
    # Goose is not running until the script starts it with `open -a Goose`
    monkeypatch.setattr(ow.reset, "goose_running", lambda: any(c[:3] == ["open", "-a", "Goose"] for c in made))
    monkeypatch.setenv("ARD_GOOSE_ROOT", str(tmp_path / "goose-root"))
    monkeypatch.setenv("ARD_HOME", str(tmp_path / "home"))
    acp = tmp_path / "acp" / "node_modules" / ".bin"
    acp.mkdir(parents=True)
    (acp / "claude-agent-acp").write_text("#!/bin/sh\n")
    monkeypatch.setenv("ARD_ACP_PREFIX", str(tmp_path / "acp"))
    # the demo Goose set to Claude Code ACP, with no system layer and nothing in launchd's environment (#340)
    (tmp_path / "goose-root" / "config").mkdir(parents=True)
    (tmp_path / "goose-root" / "config" / "config.yaml").write_text("active_provider: claude-acp\n")
    monkeypatch.setattr(ow, "SYSTEM_CONFIG", tmp_path / "no-system.yaml")
    monkeypatch.setattr(ow, "launchd_env", lambda name: "")
    made.result = result
    return made


def test_the_sellers_open_first_maya_last_then_the_windows_are_tiled(calls, capsys):
    assert ow.main(["--rail", "fake"]) == 0
    assert calls[0][:2] == ["note", ["alder", "kestrel", "adjudicator", "maya"]]  # the trust note comes before any window can be trusted
    assert calls[0][2].endswith("goose-root")  # in the demo's Goose root, which every home shares and reset keeps
    assert calls[1][:4] == ["open", "-a", "Goose", "--env"] and calls[1][4].startswith("GOOSE_PATH_ROOT=")
    assert calls[1][4].endswith("goose-root")  # the demo's own Goose root, never the user's ~/.config/goose
    import json as _json
    assert calls[1][5] == "--env" and calls[1][6].startswith("GOOSE_SEARCH_PATHS=")
    assert _json.loads(calls[1][6].split("=", 1)[1]) == [str(ow.LOCKED_DIR)]  # the demo's locked adapter (#276)
    assert calls[1][7:11] == ["--env", f"ARD_ACP_PREFIX={ow.acp_prefix()}", "--env", f"ARD_PYTHON={ow.sys.executable}"]
    assert [c[1] for c in calls[2:6]] == [f"goose://recipe?config={r}" for r in ("alder", "kestrel", "adjudicator", "maya")]
    assert calls[6] == ow.TILE and len(calls) == 7
    assert 'click menu item "Quarters" of menu "Move & Resize"' in ow.TILE[-1]
    assert all('tell application "System Events"' in line for line in ow.TILE[2::2])  # one permission: System Events only
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("code,stderr,exc,why,grant", [
    (1, "execution error: osascript is not allowed assistive access. (-1719)", None, "not allowed assistive access", True),
    (1, "execution error: Not authorized to send Apple events to System Events. (-1743)", None, "(-1743)", True),
    (0, "", subprocess.TimeoutExpired("osascript", 30), "timed out", True),  # a pending permission prompt
    (1, "execution error: Can't get menu item \"Quarters\".\n(-1728)", None, "Can't get menu item", False),
    (1, "", None, "osascript exit 1", False),
    (0, "", FileNotFoundError("osascript"), "osascript", False),
])
def test_a_failed_tile_prints_one_line_with_the_manual_fallback_and_the_open_still_succeeds(calls, capsys, code, stderr, exc, why, grant):
    calls.result.update(code=code, stderr=stderr, **{"raise": exc})
    assert ow.main(["--rail", "fake"]) == 0
    assert sum(c[0] == "osascript" for c in calls) == 3  # the first try and two retries, 10 s apart
    err = capsys.readouterr().err.splitlines()
    assert len(err) == 5 and all("trying again in 10 s" in line for line in err[:2])
    assert why in err[2]  # the message on one line even when osascript printed two
    assert ("System Settings, Privacy & Security, Accessibility" in err[2]) is grant  # the grant only for a permission
    assert err[2].endswith("tile by hand: Window, Move & Resize, Quarters.")
    assert err[3] == "" and shlex.split(err[4]) == ow.TILE  # a blank line, then the exact command to paste


def test_a_tile_that_works_on_a_retry_prints_only_the_retry_note(calls, capsys, monkeypatch):
    answers = iter([(False, "not allowed assistive access (-1719)", True), (True, "", False)])
    monkeypatch.setattr(ow, "_tile_once", lambda: next(answers))
    assert ow.main(["--rail", "fake"]) == 0
    err = capsys.readouterr().err.splitlines()
    assert err == ["could not tile the windows yet (not allowed assistive access (-1719)); trying again in 10 s: "
                   "allow the access macOS asks for."]


@pytest.mark.parametrize("args", [["--print"], ["--only", "maya"]])
def test_print_and_a_single_window_tile_nothing(calls, args):
    assert ow.main(["--rail", "fake", *args]) == 0
    assert all(c[0] != "osascript" for c in calls)
    assert any(c[0] == "note" for c in calls) is (args[0] == "--only")  # --print opens nothing, so it notes nothing


def test_a_running_goose_is_refused_and_nothing_opens(calls, capsys, monkeypatch):
    # a running Goose (the user's own) would take the recipes into its own settings
    monkeypatch.setattr(ow.reset, "goose_running", lambda: True)
    assert ow.main(["--rail", "fake"]) == 2
    assert calls == []
    assert "Goose Desktop is running: quit it first" in capsys.readouterr().err


def test_goose_only_starts_the_demo_goose_and_opens_no_window(calls, capsys):
    assert ow.main(["--goose-only"]) == 0
    assert [c[:4] for c in calls] == [["open", "-a", "Goose", "--env"]]
    assert "started the demo's own Goose on" in capsys.readouterr().out


def test_a_goose_root_inside_the_demo_home_is_refused(calls, capsys, monkeypatch, tmp_path):
    # reset deletes the demo home: the provider setup must not live there
    monkeypatch.setenv("ARD_GOOSE_ROOT", str(tmp_path / "home" / "goose"))
    assert ow.main(["--rail", "fake"]) == 2 and calls == []
    assert "inside the demo home" in capsys.readouterr().err


def test_the_default_goose_root_is_outside_the_default_home():
    root, home = Path(ow.GOOSE_ROOT_DEFAULT).expanduser(), Path(ow.reset.DEFAULT_HOME).expanduser()
    assert home not in root.parents and root != home


def test_a_missing_demo_adapter_refuses_with_the_pinned_local_install(calls, capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("ARD_ACP_PREFIX", str(tmp_path / "no-acp"))
    assert ow.main(["--rail", "fake"]) == 1  # the windows need the adapter with Claude Code ACP (#340)
    assert not any(c[:3] == ["open", "-a", "Goose"] for c in calls)
    err = capsys.readouterr().err
    assert f"npm install --prefix {tmp_path / 'no-acp'} @agentclientprotocol/claude-agent-acp@{ow.ACP_PIN}" in err
    assert "never npm install -g" in err and " -g " not in ow.acp_install()


def test_the_search_path_env_is_valid_json_with_an_expanded_absolute_path(calls, monkeypatch):
    # Goose parses GOOSE_SEARCH_PATHS from the environment as JSON; a literal $HOME or ~ would never resolve
    import json as _json

    monkeypatch.delenv("ARD_ACP_PREFIX")
    monkeypatch.setattr(ow, "acp_prefix", lambda: Path(ow.ACP_PREFIX_DEFAULT).expanduser())
    monkeypatch.setattr(ow.Path, "exists", lambda self: True)
    assert ow.main(["--goose-only"]) == 0
    value = next(arg for arg in calls[0] if arg.startswith("GOOSE_SEARCH_PATHS="))
    paths = _json.loads(value.split("=", 1)[1])
    assert isinstance(paths, list) and len(paths) == 1
    assert Path(paths[0]).is_absolute() and "$" not in paths[0] and "~" not in paths[0]
    assert paths[0].endswith("demo/ard/goose/locked")
    prefix = next(arg for arg in calls[0] if arg.startswith("ARD_ACP_PREFIX="))
    assert prefix.endswith("ard-demo/acp") and "~" not in prefix and "$" not in prefix


def test_a_recipe_reset_could_not_clear_opens_nothing(calls, capsys, monkeypatch):
    def refuse(recipes, root):
        raise ValueError("trust_hash covers the demo's recipe shape only")
    monkeypatch.setattr(ow.reset, "note_trust", refuse)
    assert ow.main(["--rail", "fake"]) == 2
    assert calls == []  # no Goose started, no window opened
    assert "the demo's recipe shape only; nothing was opened" in capsys.readouterr().err


def test_only_mayas_window_carries_the_spending_limit(monkeypatch):
    # evidencebook#890: ARD_LIMIT_MSAT set where the windows are opened reaches Maya's server, and no other window's
    for var, value in (("CAPSULE_ENGINE", "/e"), ("ARD_EVIDENCEBOOK", "/b"), ("CAPSULECTL_DEAL", "/d"), ("ARD_LIMIT_MSAT", "2000")):
        monkeypatch.setenv(var, value)
    monkeypatch.setattr(ow, "instructions", lambda role, rail: "")
    args = {role: ow.recipe(role, "fake")["extensions"][0]["args"] for role in ("maya", "alder", "kestrel", "adjudicator")}
    assert "ARD_LIMIT_MSAT=2000" in args["maya"]
    assert all("ARD_LIMIT_MSAT=2000" not in a for role, a in args.items() if role != "maya")
    monkeypatch.delenv("ARD_LIMIT_MSAT")
    assert not any(a.startswith("ARD_LIMIT_MSAT=") for a in ow.recipe("maya", "fake")["extensions"][0]["args"])
