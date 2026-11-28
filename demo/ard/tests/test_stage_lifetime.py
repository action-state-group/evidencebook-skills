# SPDX-License-Identifier: Apache-2.0
"""evidencebook-skills#453: a stage a window starts (stage.ensure_stage) stops once no process it serves is alive, so a
run that ends or is interrupted leaves no stage behind; a stage started by hand runs until stopped."""
from __future__ import annotations

import fcntl
import os
import random
import signal
import socket
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

import stage

HERE = Path(__file__).resolve().parents[1]


def _sleeper() -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], stdin=subprocess.DEVNULL)


def test_owners_are_recorded_and_a_dead_ones_file_is_removed(tmp_path):
    live, dead = _sleeper(), _sleeper()
    try:
        stage.add_owner(tmp_path, live.pid)
        stage.add_owner(tmp_path, dead.pid)
        dead.kill()
        dead.wait()
        assert stage.live_owners(tmp_path) == {live.pid}
        assert sorted(p.name for p in (tmp_path / "stage" / stage.OWNERS).iterdir()) == [str(live.pid)]
    finally:
        live.kill()
        live.wait()


def test_a_pid_given_to_another_process_since_is_not_an_owner(tmp_path):
    stage.add_owner(tmp_path, os.getpid())
    (tmp_path / "stage" / stage.OWNERS / str(os.getpid())).write_text("Thu Jan  1 00:00:00 1970")  # an earlier process's
    assert stage.live_owners(tmp_path) == set()


def _wait(tmp_path: Path, closed: list) -> threading.Thread:
    t = threading.Thread(target=stage.owned_wait, args=(tmp_path, lambda: closed.append(_lock_free(tmp_path)), 0.05),
                         daemon=True)
    t.start()
    return t


def _lock_free(tmp_path: Path) -> bool:
    """Whether the owners' lock could be taken now, from another open of its file."""
    with open(tmp_path / "stage" / stage.OWNERS / stage.OWNERS_LOCK, "a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        fcntl.flock(f, fcntl.LOCK_UN)
        return True


def test_the_stage_stops_only_once_its_last_owner_is_gone_and_closes_under_the_lock(tmp_path):
    first, second = _sleeper(), _sleeper()
    stage.add_owner(tmp_path, first.pid)
    stage.add_owner(tmp_path, second.pid)
    closed: list = []
    t = _wait(tmp_path, closed)
    try:
        first.kill()
        first.wait()
        t.join(0.5)
        assert t.is_alive() and not closed  # the second still runs
    finally:
        second.kill()
        second.wait()
    t.join(5)
    assert not t.is_alive() and closed == [False]  # closed while it held the lock: no window recorded itself between


def test_ensure_stage_records_its_caller_and_starts_an_owned_stage(tmp_path, monkeypatch):
    started = []
    monkeypatch.setattr(stage, "stage_up", lambda: bool(started))
    monkeypatch.setattr(stage, "serves", lambda: str(tmp_path))
    monkeypatch.setattr(stage, "_spawn", started.append)
    stage.ensure_stage(tmp_path)
    assert started[0][2:] == ["--owned", str(tmp_path)] and stage.live_owners(tmp_path) == {os.getpid()}


def test_a_window_that_reuses_the_stage_is_recorded_too(tmp_path, monkeypatch):
    monkeypatch.setattr(stage, "stage_up", lambda: True)
    monkeypatch.setattr(stage, "serves", lambda: str(tmp_path))
    monkeypatch.setattr(stage, "_spawn", lambda argv: pytest.fail("a running stage is not started again"))
    stage.ensure_stage(tmp_path)
    assert stage.live_owners(tmp_path) == {os.getpid()}


def test_a_stage_of_another_home_is_refused_not_reused(tmp_path, monkeypatch):
    """Codex on #459: a window of home B must not take home A's stage on the same port, which would never see it as an
    owner (and serves A's files)."""
    monkeypatch.setattr(stage, "stage_up", lambda: True)
    monkeypatch.setattr(stage, "serves", lambda: "/elsewhere/home-a")
    with pytest.raises(RuntimeError, match="taken by the stage of another demo home \\(/elsewhere/home-a\\)"):
        stage.ensure_stage(tmp_path)


def test_two_windows_starting_at_once_start_one_stage(tmp_path, monkeypatch):
    """Codex on #459: the second window waits under the owners' lock for the stage the first started (it answers only
    after a while), instead of starting another."""
    spawned, up_at = [], []
    monkeypatch.setattr(stage, "_spawn", lambda argv: (spawned.append(argv), up_at.append(time.monotonic() + 0.6)))
    monkeypatch.setattr(stage, "stage_up", lambda: bool(up_at) and time.monotonic() >= up_at[0])
    monkeypatch.setattr(stage, "serves", lambda: str(tmp_path))
    errors = []

    def window():
        try:
            stage.ensure_stage(tmp_path)
        except Exception as exc:  # noqa: BLE001 - reported below
            errors.append(exc)
    ts = [threading.Thread(target=window) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(20)
    assert not errors and len(spawned) == 1


def _run_main(tmp_path: Path, *args: str) -> subprocess.Popen:
    """stage.main in its own process, its Stage a stand-in (no listeners, no binaries): what main does with --owned."""
    code = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(HERE)!r})
        import stage
        class Fake:
            url = "fake"
            def __init__(self, home): pass
            def serve_forever(self):
                import time; time.sleep(120)
            def close(self): print("closed", flush=True)
        stage.Stage = Fake
        stage.adj.rules_url = lambda: "fake"
        stage.OWNER_CHECK_S = 0.05
        sys.exit(stage.main(["stage.py", *{list(args)!r}]))
    """)
    return subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True)


def test_an_owned_stage_process_stops_when_its_owner_is_killed(tmp_path):
    owner = _sleeper()
    stage.add_owner(tmp_path, owner.pid)
    st = _run_main(tmp_path, "--owned", str(tmp_path))
    try:
        time.sleep(0.5)
        assert st.poll() is None  # its owner lives
        owner.send_signal(signal.SIGKILL)  # the run is interrupted
        owner.wait()
        out, _ = st.communicate(timeout=10)
        assert st.returncode == 0 and "closed" in out and "no process it serves is running; stopped" in out
    finally:
        owner.kill()
        st.kill()


def test_a_stage_started_by_hand_runs_until_stopped(tmp_path):
    st = _run_main(tmp_path, str(tmp_path))  # no --owned, and no owner recorded
    try:
        time.sleep(0.5)
        assert st.poll() is None
    finally:
        st.kill()
        st.wait()


def _free_base() -> int:
    """A port P with P, P+10 and P+11 free: the stage's registry and its two seller origins."""
    for _ in range(50):
        base = random.randint(20000, 60000)
        try:
            for p in (base, base + 10, base + 11):
                with socket.socket() as s:
                    s.bind(("127.0.0.1", p))
            return base
        except OSError:
            continue
    raise RuntimeError("no free ports")


@pytest.mark.skipif(not os.environ.get("CAPSULECTL_DEAL"), reason="CAPSULECTL_DEAL makes the stage's adjudicator")
def test_the_real_stage_a_window_started_stops_once_the_window_is_killed(tmp_path):
    """End to end: a window's process starts the real stage.py (ensure_stage) and is then killed, as a run interrupted
    mid-way; the stage stops and frees its port."""
    port, home = _free_base(), tmp_path / "home"
    env = {**os.environ, "ARD_STAGE_PORT": str(port), "ARD_WITNESS": "off"}
    window = subprocess.Popen(
        [sys.executable, "-c", f"import sys, time; sys.path.insert(0, {str(HERE)!r}); import stage; "
         f"stage.ensure_stage(__import__('pathlib').Path({str(home)!r})); print('up', flush=True); time.sleep(120)"],
        env=env, stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True)
    try:
        assert window.stdout.readline().strip() == "up"
        window.kill()
        window.wait()
        end = time.monotonic() + 4 * stage.OWNER_CHECK_S + 10
        while time.monotonic() < end:
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", port)) != 0:
                    break
            time.sleep(0.2)
        else:
            pytest.fail("the stage still listens after the window that started it was killed")
    finally:
        window.kill()
        subprocess.run(["pkill", "-f", f"stage.py --owned {home}"], check=False)
