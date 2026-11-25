# SPDX-License-Identifier: Apache-2.0
"""``demo.py reset``: it refuses unsafe targets and a running Goose, stops only Python running the demo's own scripts
while holding the home's own lock files, refuses if anything else holds the home or listens on the demo's ports,
deletes the home, and clears Goose's recipe trust. Real processes stand in for the stage and the servers; no Goose."""
from __future__ import annotations

import json
import os
import random
import shutil
import signal
import socket
import subprocess
import sys
import types
from pathlib import Path

import pytest

import reset

needs_lsof = pytest.mark.skipif(not shutil.which("lsof"), reason="reset finds the home's holders with lsof")


def _bindable(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
        return True


def _use_free_demo_ports(monkeypatch) -> None:
    """Point the demo at a relay and stage port whose four ports (``reset.demo_ports``) are free, chosen where no other
    test process listens. Reset refuses when anything else listens on those ports, and under pytest-xdist the other
    workers listen on ports the OS hands out from its ephemeral range (from 32768 on Linux, 49152 on macOS), so a port
    from that range, or the stage port's +10 and +11 beside it, can be taken by another worker mid-test (#267). Each
    worker draws from a band of its own below 32768 instead."""
    worker = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
    band = 20000 + (int(worker.removeprefix("gw") or 0) % 30) * 400
    for _ in range(100):
        relay = band + random.randrange(0, 400 - 12)
        monkeypatch.setenv("ARD_RELAY_PORT", str(relay))
        monkeypatch.setenv("ARD_STAGE_PORT", str(relay + 1))
        if all(map(_bindable, reset.demo_ports())):
            return
    raise RuntimeError(f"no free demo ports in {band}-{band + 399}")


def _holder(tmp: Path, script: str, *args: str, hold: Path | None = None, cwd: Path | None = None,
            ignore_term: bool = False, listen: int | None = None, folder_name: str | None = None,
            options: tuple[str, ...] = ()) -> subprocess.Popen:
    """Python running a script named ``script`` with ``args``: holding ``hold`` open, working in ``cwd``, ignoring
    SIGTERM or listening on ``listen``, as asked."""
    code = "import signal, socket, sys, time\n"
    if ignore_term:
        code += "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
    if hold:
        code += f"f = open({str(hold)!r}, 'a')\n"
    if listen:
        code += f"s = socket.socket(); s.bind(('127.0.0.1', {listen})); s.listen()\n"
    code += "print('up', flush=True)\ntime.sleep(60)\n"
    n = len(list((tmp / "scripts").glob("*"))) if (tmp / "scripts").exists() else 0
    folder = tmp / "scripts" / (folder_name or str(n))
    folder.mkdir(parents=True)
    (folder / script).write_text(code)
    p = subprocess.Popen([sys.executable, *options, str(folder / script), *args], cwd=cwd, stdout=subprocess.PIPE,
                         stdin=subprocess.DEVNULL, text=True)
    assert p.stdout.readline().strip() == "up"
    return p


def _done(*procs: subprocess.Popen) -> None:
    for p in procs:
        p.kill()
        p.wait()


MINE, DEMO_A, DEMO_B = "a" * 64, "b" * 64, "c" * 64
#: A recipe open-windows.py builds for Maya (paths made neutral, the skill text left out), and the name of the trust file
#: Goose Desktop 1.59.2 made when its link was opened and trusted (2026-11-25 09:10:13Z, on the Mac of the by-hand run).
FIXTURE = Path(__file__).parent / "fixtures" / "goose-trust-recipe.json"
FIXTURE_HASH = "9da4a35c36d5212244208afcf1dfd3f7efb54c33b5dc0aee0925fe406b515425"


@pytest.fixture
def mac(tmp_path, monkeypatch):
    """A home, a user folder with Goose's recipe trust, its settings and two saved recipes, and free demo ports."""
    monkeypatch.setenv("HOME", str(tmp_path / "user"))
    _use_free_demo_ports(monkeypatch)
    monkeypatch.setattr(reset, "goose_running", lambda: False)
    hashes = tmp_path / "user" / "Library" / "Application Support" / "Goose" / "recipe_hashes"
    hashes.mkdir(parents=True)
    for h in (MINE, DEMO_A, DEMO_B):
        (hashes / f"{h}.hash").write_text("2026-11-18T00:00:00Z")
    (hashes.parent / "settings.json").write_text("{}")
    saved = tmp_path / "user" / ".config" / "goose" / "recipes" / reset.SAVED_RECIPE
    saved.parent.mkdir(parents=True)
    saved.write_text("title: x")
    (saved.parent / "other.yaml").write_text("title: y")
    home = tmp_path / "ard"
    (home / "stage").mkdir(parents=True)
    root = tmp_path / "goose-root"  # the demo's Goose root notes the demo's two recipes; MINE is the person's own
    root.mkdir()
    (root / reset.DEMO_TRUST).write_text(json.dumps([DEMO_A, DEMO_B, "f" * 64]))  # f…: a noted recipe no longer trusted
    monkeypatch.setenv("ARD_GOOSE_ROOT", str(root))
    return home, hashes, saved


def test_the_stage_lock_name_is_the_stages_own():
    import parties

    assert reset.STAGE_LOCK == parties.STAGE_LOCK


def test_refuses_while_goose_runs_and_changes_nothing(mac, monkeypatch):
    home, hashes, saved = mac
    monkeypatch.setattr(reset, "goose_running", lambda: True)
    monkeypatch.setattr(reset, "GOOSE_WAIT_S", 0.2)
    with pytest.raises(reset.ResetRefused, match="still running after 0 s: quit it first"):
        reset.reset(home, say=lambda *_: None)
    assert home.exists() and len(list(hashes.glob("*.hash"))) == 3 and saved.exists()


@needs_lsof
def test_reset_waits_for_a_goose_that_is_still_quitting(mac, monkeypatch):
    # osascript -e 'quit app "Goose"' returns before Goose exits; the reset right after it must wait, not refuse
    home, hashes, _ = mac
    answers = iter([True, True, True])
    monkeypatch.setattr(reset, "goose_running", lambda: next(answers, False))
    monkeypatch.setattr(reset.time, "sleep", lambda s: None)
    assert reset.reset(home, say=lambda *_: None) == 0
    assert not home.exists() and _left(hashes) == [f"{MINE}.hash"]


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


def test_refuses_a_symlinked_lock_file(mac, tmp_path):
    home, _, _ = mac
    (tmp_path / "elsewhere.lock").write_text("")
    (home / "stage" / reset.STAGE_LOCK).symlink_to(tmp_path / "elsewhere.lock")
    with pytest.raises(reset.ResetRefused, match="not a plain file"):
        reset.reset(home, say=lambda *_: None)
    assert home.exists()


def test_refuses_when_lsof_is_missing(mac, monkeypatch):
    home, hashes, _ = mac
    monkeypatch.setattr(reset.shutil, "which", lambda name: None)
    with pytest.raises(reset.ResetRefused, match="lsof is needed"):
        reset.reset(home, say=lambda *_: None)
    assert home.exists() and len(list(hashes.glob("*.hash"))) == 3


def test_any_lsof_complaint_refuses(mac, monkeypatch):
    home, _, _ = mac
    monkeypatch.setattr(reset.shutil, "which", lambda name: "/usr/sbin/lsof")
    monkeypatch.setattr(reset.subprocess, "run",
                        lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="p1\nfcwd\nn/x\n", stderr="lsof: WARNING: can't stat()"))
    with pytest.raises(reset.ResetRefused, match="lsof could not finish"):
        reset.reset(home, say=lambda *_: None)
    assert home.exists()


@needs_lsof
def test_stops_this_homes_stage_and_server_leaves_a_prefix_home_alone_and_clears_the_trust(mac, tmp_path):
    home, hashes, saved = mac
    sibling = home.parent / (home.name + "-2")  # a home whose path starts with this one's
    (sibling / "stage").mkdir(parents=True)
    stage = _holder(tmp_path, "stage.py", str(home), hold=home / "stage" / reset.STAGE_LOCK)  # as if started by hand
    server = _holder(tmp_path, "desktop_server.py", hold=home / ".desktop-maya.lock")
    other = _holder(tmp_path, "stage.py", str(sibling), hold=sibling / "stage" / reset.STAGE_LOCK)
    said = []
    try:
        assert reset.reset(home, say=said.append) == 0
        stage.wait(timeout=10), server.wait(timeout=10)
        assert other.poll() is None  # the other home's stage is not this home's
    finally:
        _done(stage, server, other)
    assert not home.exists() and sibling.exists()
    assert _left(hashes) == [f"{MINE}.hash"] and (hashes.parent / "settings.json").exists()  # only the demo's trust files
    assert not saved.exists() and (saved.parent / "other.yaml").exists()
    assert any("stopped stage.py and desktop_server.py on this home" in s for s in said)
    assert any("cleared Goose's trust in 2 of the demo's recipes" in s and "other recipes keep theirs" in s for s in said)


@needs_lsof
def test_a_reader_of_a_lock_file_is_not_ours_and_is_not_killed(mac, tmp_path):
    home, _, _ = mac
    (home / "stage" / reset.STAGE_LOCK).write_text("")
    reader = _holder(tmp_path, "tail.py", "-f", str(home / "stage" / reset.STAGE_LOCK), hold=home / "stage" / reset.STAGE_LOCK)
    try:
        with pytest.raises(reset.ResetRefused, match=f"pid {reader.pid} .*a lock file of this home.*Nothing was changed"):
            reset.reset(home, say=lambda *_: None)
        assert reader.poll() is None
    finally:
        _done(reader)
    assert home.exists()


@needs_lsof
def test_refuses_a_process_that_only_names_our_script_and_kills_nothing(mac, tmp_path):
    home, hashes, _ = mac
    editor = _holder(tmp_path, "vim.py", "/x/demo/ard/desktop_server.py", hold=home / "stage" / "notes.txt")
    try:
        with pytest.raises(reset.ResetRefused, match=f"pid {editor.pid} "):
            reset.reset(home, say=lambda *_: None)
        assert editor.poll() is None
    finally:
        _done(editor)
    assert home.exists() and len(list(hashes.glob("*.hash"))) == 3


@needs_lsof
def test_a_shell_inside_the_home_is_told_to_cd_out_not_killed(mac, tmp_path):
    home, _, _ = mac
    shell = _holder(tmp_path, "zsh.py", cwd=home)
    try:
        with pytest.raises(reset.ResetRefused, match="cd out of it"):
            reset.reset(home, say=lambda *_: None)
        assert shell.poll() is None
    finally:
        _done(shell)
    assert home.exists()


@needs_lsof
def test_an_old_stage_without_a_lock_that_names_this_home_is_stopped(mac, tmp_path):
    # Ethan's reset test (2026-11-18): a stage.py started before stages held a lock, serving this home on the port
    home, hashes, _ = mac
    port = int(reset.demo_ports()[0])
    server = _holder(tmp_path, "desktop_server.py", hold=home / ".desktop-maya.lock")
    old = _holder(tmp_path, "stage.py", str(home), listen=port)
    try:
        assert reset.holders(home)[0] == {server.pid, old.pid}
        assert reset.reset(home, say=lambda *_: None) == 0
        server.wait(timeout=10)
        old.wait(timeout=10)
    finally:
        _done(server, old)
    assert not home.exists() and _left(hashes) == [f"{MINE}.hash"]


@needs_lsof
def test_a_stage_from_an_older_commit_of_this_checkout_is_stopped(mac, tmp_path, monkeypatch):
    # run from this checkout's demo/ard by a relative path, naming no home: its script is ours whatever commit it was
    home, _, _ = mac
    folder = tmp_path / "scripts" / "checkout-demo-ard"
    monkeypatch.setattr(reset, "HERE", folder.resolve())
    port = int(reset.demo_ports()[1])
    folder.mkdir(parents=True)
    (folder / "stage.py").write_text(f"import socket, time\ns = socket.socket(); s.bind(('127.0.0.1', {port})); s.listen()\n"
                                     "print('up', flush=True)\ntime.sleep(60)\n")
    rel = subprocess.Popen([sys.executable, "stage.py"], cwd=folder, stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True)
    assert rel.stdout.readline().strip() == "up"
    try:
        assert reset.holders(home)[0] == {rel.pid}
        assert reset.reset(home, say=lambda *_: None) == 0
        rel.wait(timeout=10)
    finally:
        _done(rel)
    assert not home.exists()


@needs_lsof
def test_a_stranger_on_the_stage_port_refuses_before_anything_is_stopped(mac, tmp_path):
    home, hashes, _ = mac
    port = int(reset.demo_ports()[1])
    server = _holder(tmp_path, "desktop_server.py", hold=home / ".desktop-maya.lock")
    stranger = _holder(tmp_path, "stage.py", str(tmp_path / "another-home"), listen=port)  # our name, not our home
    other = _holder(tmp_path, "tail.py", listen=int(reset.demo_ports()[0]))
    try:
        with pytest.raises(reset.ResetRefused, match=f"not this demo's stage.*pid {stranger.pid} .*on port {port}.*Nothing was changed"):
            reset.reset(home, say=lambda *_: None)
        assert server.poll() is None and stranger.poll() is None and other.poll() is None
    finally:
        _done(server, stranger, other)
    assert home.exists() and len(list(hashes.glob("*.hash"))) == 3


@needs_lsof
def test_an_inline_program_named_like_our_script_on_the_port_is_refused_not_killed(mac, tmp_path):
    home, hashes, _ = mac
    port = int(reset.demo_ports()[1])
    code = f"import socket, time; s = socket.socket(); s.bind(('127.0.0.1', {port})); s.listen(); print('up', flush=True); time.sleep(60)"
    inline = subprocess.Popen([sys.executable, f"-c{code}", "stage.py", str(home)], stdout=subprocess.PIPE,
                              stdin=subprocess.DEVNULL, text=True)
    assert inline.stdout.readline().strip() == "up"
    try:
        with pytest.raises(reset.ResetRefused, match=f"pid {inline.pid} .*Nothing was changed"):
            reset.reset(home, say=lambda *_: None)
        assert inline.poll() is None
    finally:
        _done(inline)
    assert home.exists() and len(list(hashes.glob("*.hash"))) == 3


def test_an_argument_that_cannot_be_read_as_a_path_is_no_match(monkeypatch, tmp_path):
    monkeypatch.setattr(reset, "_argv", lambda pid: ["/usr/bin/python3", "/elsewhere/stage.py", "~nosuchuser-ard/x"])
    assert reset._started_for(1, tmp_path) is False


@needs_lsof
def test_reset_runs_with_no_evidencebook_or_engine_set(mac, tmp_path):
    # reset needs no evidencebook checkout: demo.py must not stop at its setup first. The child runs its own pgrep,
    # so a stub on the PATH stands in for "Goose is not running" on a Mac where Goose is open.
    home, hashes, saved = mac
    stub = tmp_path / "stub-bin"
    stub.mkdir()
    (stub / "pgrep").write_text("#!/bin/sh\nexit 1\n")
    (stub / "pgrep").chmod(0o755)
    env = {k: v for k, v in os.environ.items()
           if k not in ("ARD_EVIDENCEBOOK", "CAPSULE_ENGINE", "CAPSULECTL_DEAL", "ARD_HOME")}
    env["PATH"] = f"{stub}:{env.get('PATH', '')}"
    run = subprocess.run([sys.executable, str(Path(reset.__file__).with_name("demo.py")), "reset", "--home", str(home)],
                         env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120)
    assert run.returncode == 0, run.stderr
    assert "removed" in run.stdout and not home.exists() and not saved.exists() and _left(hashes) == [f"{MINE}.hash"]


@needs_lsof
def test_a_process_that_ignores_term_is_killed_after_the_wait(mac, tmp_path):
    home, _, _ = mac
    stage = _holder(tmp_path, "stage.py", str(home), hold=home / "stage" / reset.STAGE_LOCK, ignore_term=True)
    try:
        reset._stop(home, {stage.pid}, wait_s=0.5)
        assert stage.wait(timeout=10) == -signal.SIGKILL
    finally:
        _done(stage)


@needs_lsof
def test_a_pid_that_holds_no_lock_of_this_home_is_never_signalled(mac, tmp_path):
    home, _, _ = mac
    stranger = _holder(tmp_path, "stage.py", "elsewhere")  # our script's name, but no lock of this home: a reused pid, say
    try:
        assert reset._signal_ours(home, {stranger.pid}, signal.SIGTERM) == set()
        assert stranger.poll() is None
    finally:
        _done(stranger)


@needs_lsof
def test_ours_is_found_with_a_space_in_the_script_path_and_a_python_option(mac, tmp_path):
    home, _, _ = mac
    stage = _holder(tmp_path, "stage.py", str(home), hold=home / "stage" / reset.STAGE_LOCK,
                    folder_name="Demo Projects/demo/ard", options=("-W", "ignore"))
    try:
        assert reset.holders(home)[0] == {stage.pid}
        reset.reset(home, say=lambda *_: None)
        stage.wait(timeout=10)
    finally:
        _done(stage)
    assert not home.exists()


def test_python_c_and_m_are_never_our_script(monkeypatch):
    for argv in (["/usr/bin/python3", "-c", "print()", "stage.py"], ["/usr/bin/python3", "-m", "stage.py"],
                 ["/usr/bin/vim", "stage.py"], ["/usr/bin/python3", "-W", "ignore", "tail.py", "stage.py"],
                 ["/usr/bin/python3", "-cprint()", "stage.py"], ["/usr/bin/python3", "-Ic", "print()", "stage.py"],
                 ["/usr/bin/python3", "-um", "stage"], ["/usr/bin/python3", "-", "stage.py"]):
        monkeypatch.setattr(reset, "_argv", lambda pid, a=argv: a)
        assert not reset._runs_our_script(1), argv
    for argv in (["/usr/bin/python3", "-Wignore", "stage.py"], ["/usr/bin/python3", "-uW", "ignore", "stage.py"],
                 ["/usr/bin/python3", "-X", "dev", "--", "stage.py"], ["/usr/bin/python3", "-B", "/a/stage.py"]):
        monkeypatch.setattr(reset, "_argv", lambda pid, a=argv: a)
        assert reset._runs_our_script(1), argv
    monkeypatch.setattr(reset, "_argv", lambda pid: ["/x/Python.app/Contents/MacOS/Python", "-u", "/a b/desktop_server.py"])
    assert reset._runs_our_script(1)
    monkeypatch.setattr(reset, "_argv", lambda pid: None)  # unreadable: not ours, so the reset refuses
    assert not reset._runs_our_script(1)


@needs_lsof
def test_a_probe_failure_after_the_stop_says_the_processes_were_stopped(mac, tmp_path, monkeypatch):
    home, _, _ = mac
    server = _holder(tmp_path, "desktop_server.py", hold=home / ".desktop-maya.lock")
    checks = []
    real = reset._refuse_on

    def failing(*a):
        checks.append(1)
        if len(checks) > 1:  # the check after the stop
            raise reset.ResetRefused("lsof could not finish (boom).")
        return real(*a)
    monkeypatch.setattr(reset, "_refuse_on", failing)
    try:
        with pytest.raises(reset.ResetRefused) as e:
            reset.reset(home, say=lambda *_: None)
        server.wait(timeout=10)
    finally:
        _done(server)
    assert str(e.value).endswith("were stopped; the home was kept.") and "Nothing was changed" not in str(e.value)
    assert home.exists()


@needs_lsof
def test_a_missing_home_and_no_goose_folder_still_reset(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "user"))
    _use_free_demo_ports(monkeypatch)
    monkeypatch.setattr(reset, "goose_running", lambda: False)
    said = []
    assert reset.reset(tmp_path / "never-made", say=said.append) == 0
    assert any("deleted no Goose recipe trust: no trust file matches a recipe the demo's windows opened" in s for s in said)


def _left(hashes: Path) -> list[str]:
    return sorted(p.name for p in hashes.glob("*.hash"))


def test_the_trust_hash_is_goose_1_59_2s_name_for_a_real_trust_file():
    # A recipe the demo's open-windows.py builds, with the paths of the Mac it ran on replaced (they change the hash, so
    # the expected name below was taken from the trust file Goose Desktop 1.59.2 made for this exact recipe).
    recipe = json.loads(FIXTURE.read_text())
    assert reset.trust_hash(recipe) == FIXTURE_HASH
    assert reset.trust_hash({k: v for k, v in recipe.items() if k != "version"}) == FIXTURE_HASH  # version defaults
    reordered = dict(reversed(list(recipe.items())))
    assert reset.trust_hash(reordered) == FIXTURE_HASH  # Goose's schema fixes the order, not the link's JSON
    ext = recipe["extensions"][0]
    for other in ({"type": "builtin", "name": "developer"}, {k: v for k, v in ext.items() if k != "description"},
                  {**ext, "args": []}, {**ext, "envs": {}}, {**ext, "env_keys": ["X"]}):
        with pytest.raises(ValueError, match="the demo's recipe shape only"):  # Goose would normalize these
            reset.trust_hash({**recipe, "extensions": [other]})


def test_reset_deletes_only_the_noted_recipes_trust_and_never_by_time(tmp_path):
    user, root = tmp_path / "user", tmp_path / "goose-root"
    hashes = reset._hashes(user)
    hashes.mkdir(parents=True)
    mine = {"title": "mine", "description": "the person's own"}
    demo = [{"title": "alder", "description": "d"}, {"title": "maya", "description": "d"}]
    (hashes / f"{reset.trust_hash(mine)}.hash").write_text("2026-11-25T00:00:00Z")  # trusted after the demo noted: kept
    reset.note_trust(demo[:1], root)
    reset.note_trust(demo, root)  # a second open adds, and notes each recipe once
    assert json.loads((root / reset.DEMO_TRUST).read_text()) == sorted(reset.trust_hash(r) for r in demo)
    assert reset.clear_recipe_trust(root, user) == 0  # nothing trusted yet: nothing deleted, whatever its age
    assert _left(hashes) == [f"{reset.trust_hash(mine)}.hash"] and not (root / reset.DEMO_TRUST).exists()
    reset.note_trust(demo, root)
    for r in demo:
        (hashes / f"{reset.trust_hash(r)}.hash").write_text("t")
    assert reset.clear_recipe_trust(root, user) == 2 and _left(hashes) == [f"{reset.trust_hash(mine)}.hash"]
    (root / reset.DEMO_TRUST).write_text("{not json")
    assert reset.clear_recipe_trust(root, user) == 0 and len(_left(hashes)) == 1  # an unreadable note deletes nothing
    outside = hashes.parent / "x.hash"
    outside.write_text("t")
    (root / reset.DEMO_TRUST).write_text(json.dumps(["../x" + "0" * 60]))  # 64 characters, not a hash: ignored
    assert reset.clear_recipe_trust(root, user) == 0 and outside.exists()