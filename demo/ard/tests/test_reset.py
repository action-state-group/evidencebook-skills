# SPDX-License-Identifier: Apache-2.0
"""``demo.py reset``: it refuses while Goose runs, stops the demo's own processes on the home, refuses if anything
else holds the home, deletes the home, and clears Goose's recipe trust. Real processes, no Goose."""
from __future__ import annotations

import shutil
import subprocess
import sys
import time

import pytest

import reset


def _sleeper(*argv: str, hold: str | None = None) -> subprocess.Popen:
    """A process whose command line carries ``argv`` (as a real stage or server would), optionally holding a file open."""
    code = "import sys, time\n" + (f"f = open({hold!r}, 'a')\n" if hold else "") + "print('up', flush=True)\ntime.sleep(60)\n"
    p = subprocess.Popen([sys.executable, "-c", code, *argv], stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True)
    assert p.stdout.readline().strip() == "up"
    return p


@pytest.fixture
def mac(tmp_path, monkeypatch):
    """A home, and a user folder with Goose's recipe trust and the saved Maya recipe in it."""
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
    home = tmp_path / "ard-home"
    (home / "stage").mkdir(parents=True)
    return home, hashes, saved


def test_refuses_while_goose_runs_and_changes_nothing(mac, monkeypatch):
    home, hashes, saved = mac
    monkeypatch.setattr(reset, "goose_running", lambda: True)
    with pytest.raises(reset.ResetRefused, match="quit it first"):
        reset.reset(home, say=lambda *_: None)
    assert home.exists() and len(list(hashes.glob("*.hash"))) == 3 and saved.exists()


def test_stops_a_stage_on_this_home_deletes_it_and_clears_the_trust(mac):
    home, hashes, saved = mac
    stage = _sleeper("/x/demo/ard/stage.py", str(home))
    other_home = _sleeper("/x/demo/ard/stage.py", str(home.parent / "another-home"))
    said = []
    try:
        assert reset.reset(home, say=said.append) == 0
        stage.wait(timeout=10)  # stopped
        assert other_home.poll() is None  # a stage on another home is left alone
    finally:
        for p in (stage, other_home):
            p.kill()
            p.wait()
    assert not home.exists()
    assert list(hashes.glob("*.hash")) == [] and (hashes.parent / "settings.json").exists()  # only the trust files
    assert not saved.exists() and (saved.parent / "other.yaml").exists()
    assert any("stopped the demo's own processes" in s for s in said)
    assert any("all 3 recipes" in s and "not only the demo's three" in s for s in said)


@pytest.mark.skipif(not shutil.which("lsof"), reason="lsof finds the processes holding the home")
def test_stops_a_desktop_server_holding_the_home(mac):
    home, _, _ = mac
    server = _sleeper("/x/demo/ard/desktop_server.py", hold=str(home / ".desktop-maya.lock"))
    try:
        reset.reset(home, say=lambda *_: None)
        server.wait(timeout=10)
    finally:
        server.kill()
        server.wait()
    assert not home.exists()


@pytest.mark.skipif(not shutil.which("lsof"), reason="lsof finds the processes holding the home")
def test_refuses_when_something_else_holds_the_home(mac):
    home, hashes, _ = mac
    editor = _sleeper("an-editor", hold=str(home / "stage" / "notes.txt"))
    try:
        with pytest.raises(reset.ResetRefused, match=f"{editor.pid}: "):
            reset.reset(home, say=lambda *_: None)
        assert editor.poll() is None  # not ours, not killed
    finally:
        editor.kill()
        editor.wait()
    assert home.exists() and len(list(hashes.glob("*.hash"))) == 3


def test_a_missing_home_and_no_goose_folder_still_reset(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "user"))
    monkeypatch.setattr(reset, "goose_running", lambda: False)
    said = []
    assert reset.reset(tmp_path / "never-made", say=said.append) == 0
    assert any("all 0 recipes" in s for s in said)


def test_the_stop_waits_then_kills_a_process_that_ignores_term(mac):
    home, _, _ = mac
    code = "import signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\nprint('up', flush=True)\ntime.sleep(60)\n"
    p = subprocess.Popen([sys.executable, "-c", code, "/x/demo/ard/stage.py", str(home)], stdout=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "up"
    try:
        t = time.monotonic()
        reset._stop([p.pid], wait_s=0.5)
        p.wait(timeout=10)
        assert time.monotonic() - t < 5
    finally:
        p.kill()
        p.wait()
