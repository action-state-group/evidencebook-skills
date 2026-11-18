# SPDX-License-Identifier: Apache-2.0
"""``demo.py reset``: it refuses unsafe targets and a running Goose, stops only the processes holding the home's own
lock files, refuses if anything else holds the home, deletes the home, and clears Goose's recipe trust. Real processes
stand in for the stage and the servers; no Goose runs."""
from __future__ import annotations

import shutil
import signal
import subprocess
import sys
import types
from pathlib import Path

import pytest

import reset

needs_lsof = pytest.mark.skipif(not shutil.which("lsof"), reason="reset finds the home's holders with lsof")


def _holder(*argv: str, hold: Path | None = None, cwd: Path | None = None, ignore_term: bool = False) -> subprocess.Popen:
    """A process with ``argv`` on its command line, holding ``hold`` open and/or working in ``cwd``."""
    code = "import signal, sys, time\n"
    if ignore_term:
        code += "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
    if hold:
        code += f"f = open({str(hold)!r}, 'a')\n"
    code += "print('up', flush=True)\ntime.sleep(60)\n"
    p = subprocess.Popen([sys.executable, "-c", code, *argv], cwd=cwd, stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True)
    assert p.stdout.readline().strip() == "up"
    return p


def _done(*procs: subprocess.Popen) -> None:
    for p in procs:
        p.kill()
        p.wait()


@pytest.fixture
def mac(tmp_path, monkeypatch):
    """A home, and a user folder with Goose's recipe trust, its settings and two saved recipes."""
    monkeypatch.setenv("HOME", str(tmp_path / "user"))
    monkeypatch.setattr(reset, "goose_running", lambda: False)
    hashes = tmp_path / "user" / "Library" / "Application Support" / "Goose" / "recipe_hashes"
    hashes.mkdir(parents=True)
    for h in ("aa", "bb", "cc"):
        (hashes / f"{h}.hash").write_text("2026-11-18T00:00:00Z")
    (hashes.parent / "settings.json").write_text("{}")
    saved = tmp_path / "user" / ".config" / "goose" / "recipes" / reset.SAVED_RECIPE
    saved.parent.mkdir(parents=True)
    saved.write_text("title: x")
    (saved.parent / "other.yaml").write_text("title: y")
    home = tmp_path / "ard"
    (home / "stage").mkdir(parents=True)
    return home, hashes, saved


def test_the_stage_lock_name_is_the_stages_own():
    import parties

    assert reset.STAGE_LOCK == parties.STAGE_LOCK


def test_refuses_while_goose_runs_and_changes_nothing(mac, monkeypatch):
    home, hashes, saved = mac
    monkeypatch.setattr(reset, "goose_running", lambda: True)
    with pytest.raises(reset.ResetRefused, match="quit it first"):
        reset.reset(home, say=lambda *_: None)
    assert home.exists() and len(list(hashes.glob("*.hash"))) == 3 and saved.exists()


def test_a_failed_goose_check_refuses(monkeypatch):
    monkeypatch.setattr(reset.subprocess, "run", lambda *a, **k: types.SimpleNamespace(returncode=3, stderr="boom", stdout=""))
    with pytest.raises(reset.ResetRefused, match="could not check whether Goose runs"):
        reset.goose_running()


@pytest.mark.parametrize("target", ["/", "HOME", "HOME_PARENT"])
def test_refuses_root_and_the_user_folder_before_anything(mac, target):
    home = {"/": Path("/"), "HOME": Path.home(), "HOME_PARENT": Path.home().parent}[target]
    with pytest.raises(reset.ResetRefused, match="your user folder or above"):
        reset.reset(home, say=lambda *_: None)


def test_refuses_a_symlinked_home(mac, tmp_path):
    home, _, _ = mac
    link = tmp_path / "ard-link"
    link.symlink_to(home)
    with pytest.raises(reset.ResetRefused, match="symbolic link"):
        reset.reset(link, say=lambda *_: None)
    assert home.exists()


def test_refuses_when_lsof_is_missing(mac, monkeypatch):
    home, hashes, _ = mac
    monkeypatch.setattr(reset.shutil, "which", lambda name: None)
    with pytest.raises(reset.ResetRefused, match="lsof is needed"):
        reset.reset(home, say=lambda *_: None)
    assert home.exists() and len(list(hashes.glob("*.hash"))) == 3


@needs_lsof
def test_stops_this_homes_stage_and_server_leaves_a_prefix_home_alone_and_clears_the_trust(mac):
    home, hashes, saved = mac
    sibling = home.parent / (home.name + "-2")  # a home whose path starts with this one's
    (sibling / "stage").mkdir(parents=True)
    stage = _holder("stage.py", str(home), hold=home / "stage" / reset.STAGE_LOCK)  # started by hand: python stage.py <home>
    server = _holder("/x/demo/ard/desktop_server.py", hold=home / ".desktop-maya.lock")
    other = _holder("/x/demo/ard/stage.py", str(sibling), hold=sibling / "stage" / reset.STAGE_LOCK)
    said = []
    try:
        assert reset.reset(home, say=said.append) == 0
        stage.wait(timeout=10), server.wait(timeout=10)
        assert other.poll() is None  # the other home's stage is not this home's
    finally:
        _done(stage, server, other)
    assert not home.exists() and sibling.exists()
    assert list(hashes.glob("*.hash")) == [] and (hashes.parent / "settings.json").exists()  # only the trust files
    assert not saved.exists() and (saved.parent / "other.yaml").exists()
    assert any("stopped the demo's own processes" in s for s in said)
    assert any("all 3 recipes" in s and "not only the demo's three" in s for s in said)


@needs_lsof
def test_refuses_a_process_that_only_names_our_script_and_kills_nothing(mac):
    home, hashes, _ = mac
    editor = _holder("vim", "/x/demo/ard/desktop_server.py", hold=home / "stage" / "notes.txt")
    try:
        with pytest.raises(reset.ResetRefused, match=f"pid {editor.pid} "):
            reset.reset(home, say=lambda *_: None)
        assert editor.poll() is None
    finally:
        _done(editor)
    assert home.exists() and len(list(hashes.glob("*.hash"))) == 3


@needs_lsof
def test_a_shell_inside_the_home_is_told_to_cd_out_not_killed(mac):
    home, _, _ = mac
    shell = _holder("-zsh", cwd=home)
    try:
        with pytest.raises(reset.ResetRefused, match="cd out of it"):
            reset.reset(home, say=lambda *_: None)
        assert shell.poll() is None
    finally:
        _done(shell)
    assert home.exists()


@needs_lsof
def test_a_process_that_ignores_term_is_killed_after_the_wait(mac):
    home, _, _ = mac
    stage = _holder("stage.py", str(home), hold=home / "stage" / reset.STAGE_LOCK, ignore_term=True)
    try:
        reset._stop(home, {stage.pid}, wait_s=0.5)
        assert stage.wait(timeout=10) == -signal.SIGKILL
    finally:
        _done(stage)


@needs_lsof
def test_a_pid_that_holds_no_lock_of_this_home_is_never_signalled(mac):
    home, _, _ = mac
    stranger = _holder("sleep-forever")  # stands for a pid reused after our process exited
    try:
        assert reset._signal_ours(home, {stranger.pid}, signal.SIGTERM) == set()
        assert stranger.poll() is None
    finally:
        _done(stranger)


def test_a_missing_home_and_no_goose_folder_still_reset(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "user"))
    monkeypatch.setattr(reset, "goose_running", lambda: False)
    said = []
    assert reset.reset(tmp_path / "never-made", say=said.append) == 0
    assert any("all 0 recipes" in s for s in said)
