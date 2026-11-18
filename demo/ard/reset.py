# SPDX-License-Identifier: Apache-2.0
"""``demo.py reset``: put this Mac back to before the demo ran.

In order, and changing nothing until every check passes: refuse a home that is ``/``, your user folder or a folder
above it, or a symlink; refuse while Goose Desktop runs (its windows hold servers on the home and would trust the
recipes again); find who holds files under the home (``lsof``; refuse if that cannot be checked). The demo's own
processes are the ones holding the home's own lock files: a ``desktop_server.py`` holds ``.desktop-<role>.lock``, a
``stage.py`` holds ``stage/.stage.lock`` (:data:`parties.STAGE_LOCK`), however either was started. Anything else
holding the home stops the reset. Then stop ours (SIGTERM, then SIGKILL, each pid checked again just before each
signal), check the home again, delete it, and clear Goose's recipe trust, so each window asks Trust and Execute again.

Goose Desktop 1.59.2 keeps one file per trusted recipe, ``<userData>/recipe_hashes/<sha256>.hash``, the sha256 of the
recipe as its own server decodes the ``goose://`` link (``ui/desktop/src/utils/recipeHash.ts``). That hash could not be
reproduced from our recipe's JSON (checked against real files on 2026-11-18), so this clears the trust of every Goose
recipe, and says so."""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

SAVED_RECIPE = "maya-buys-conference-badges.yaml"
STAGE_LOCK = ".stage.lock"  # parties.STAGE_LOCK, kept here so reset needs none of the demo's heavier modules


class ResetRefused(SystemExit):
    """The reset changed nothing: the message says why and what to do."""


def goose_running() -> bool:
    """Whether Goose Desktop runs (its main binary, not the ``goose`` CLI)."""
    run = subprocess.run(["pgrep", "-f", "Goose.app/Contents/MacOS/Goose"], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if run.returncode not in (0, 1):
        raise ResetRefused(f"could not check whether Goose runs (pgrep: {run.stderr.strip() or run.returncode}). Nothing was changed.")
    return run.returncode == 0


def _lsof(*args: str) -> list[tuple[int, str, str]]:
    """``(pid, fd, name)`` for each open file ``lsof`` reports; refuses if lsof is missing or fails."""
    if not shutil.which("lsof"):
        raise ResetRefused("lsof is needed to see what holds the home, and it is not on PATH. Nothing was changed.")
    run = subprocess.run(["lsof", "-F", "pfn", *args], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if run.returncode not in (0, 1) or run.stderr.strip():  # any complaint means the scan may be partial
        raise ResetRefused(f"lsof could not finish ({run.stderr.strip() or run.returncode}). Run reset again; if it keeps failing, "
                           "stop the demo's processes yourself.")
    out, pid, fd = [], None, ""
    for line in run.stdout.splitlines():
        tag, value = line[:1], line[1:]
        if tag == "p":
            pid = int(value)
        elif tag == "f":
            fd = value
        elif tag == "n" and pid is not None:
            out.append((pid, fd, value))
    return out


#: The demo's own scripts: a lock holder is ours only if it is Python running one of these.
SCRIPTS = ("stage.py", "desktop_server.py")


def _locks(home: Path) -> list[Path]:
    found = sorted(home.glob(".desktop-*.lock"))
    if (home / "stage" / STAGE_LOCK).exists() or (home / "stage" / STAGE_LOCK).is_symlink():
        found.append(home / "stage" / STAGE_LOCK)
    for lock in found:
        if lock.is_symlink() or not lock.is_file():
            raise ResetRefused(f"{lock} is not a plain file, so who holds it says nothing about this home. Nothing was changed.")
    return found


def _runs_our_script(pid: int) -> bool:
    """Whether ``pid`` is a Python process whose script (the first argument after the interpreter that is not an
    option) is one of :data:`SCRIPTS`."""
    words = _command(pid).split()
    if not words or "python" not in Path(words[0]).name.lower():  # macOS shows ".../Python.app/.../Python"
        return False
    script = next((w for w in words[1:] if not w.startswith("-")), "")
    return Path(script).name in SCRIPTS


def _lock_holders(home: Path) -> set[int]:
    locks = _locks(home)
    return {pid for pid, _, _ in _lsof(*map(str, locks))} - {os.getpid()} if locks else set()


def _ours(home: Path) -> set[int]:
    """The demo's own processes on this home: holding one of its lock files and running one of our scripts."""
    return {pid for pid in _lock_holders(home) if _runs_our_script(pid)}


def holders(home: Path) -> tuple[set[int], dict[int, str], set[int]]:
    """``(ours, others, inside)`` for this home: the demo's own processes, any other process holding a file under it
    (pid: file), and processes whose working directory is in it (a shell, say)."""
    if not home.exists():
        return set(), {}, set()
    holding_locks = _lock_holders(home)
    ours = {pid for pid in holding_locks if _runs_our_script(pid)}
    others, inside = {pid: "a lock file of this home" for pid in holding_locks - ours}, set()
    for pid, fd, name in _lsof("+D", str(home)):
        if pid == os.getpid() or pid in ours:
            continue
        if fd == "cwd":
            inside.add(pid)
        else:
            others.setdefault(pid, name)
    return ours, others, inside


def _command(pid: int) -> str:
    run = subprocess.run(["ps", "-ww", "-o", "command=", "-p", str(pid)], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return run.stdout.strip()


def _signal_ours(home: Path, pids: set[int], sig: int) -> set[int]:
    """Send ``sig`` to each pid that still holds one of the home's lock files right now (a pid that let go may have
    been reused); return the ones signalled."""
    still = _ours(home) & pids
    for pid in still:
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            pass
    return still


def _stop(home: Path, pids: set[int], wait_s: float = 5.0) -> None:
    left = _signal_ours(home, pids, signal.SIGTERM)
    deadline = time.monotonic() + wait_s
    while left and time.monotonic() < deadline:
        _reap(left)
        left = _ours(home) & left
        time.sleep(0.1)
    if left:
        _signal_ours(home, left, signal.SIGKILL)
        end = time.monotonic() + wait_s
        while _ours(home) & left and time.monotonic() < end:
            _reap(left)
            time.sleep(0.1)


def _reap(pids: set[int]) -> None:
    """Collect children of this process that exited (tests start their stand-ins as children)."""
    for pid in pids:
        try:
            os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            pass


def _check_target(home: Path) -> None:
    if home.is_symlink():
        raise ResetRefused(f"{home} is a symbolic link: reset deletes only a real folder. Nothing was changed.")
    target, user = home.resolve(), Path.home().resolve()
    if target == Path(target.anchor) or target == user or target in user.parents:
        raise ResetRefused(f"refusing to reset {home}: it is / or your user folder or above it. Nothing was changed.")


def clear_recipe_trust(home_dir: Path | None = None) -> int:
    """Delete every Goose recipe-trust file and the saved Maya recipe; return how many trust files went."""
    base = home_dir or Path.home()
    hashes = base / "Library" / "Application Support" / "Goose" / "recipe_hashes"
    gone = 0
    if hashes.is_dir():
        for f in hashes.glob("*.hash"):
            f.unlink()
            gone += 1
    (base / ".config" / "goose" / "recipes" / SAVED_RECIPE).unlink(missing_ok=True)
    return gone


def demo_ports() -> list[int]:
    """The ports the demo's stage listens on (parties: the relay, the stand-in registry and the two seller sites)."""
    http = int(os.environ.get("ARD_STAGE_PORT", "47481"))
    return [int(os.environ.get("ARD_RELAY_PORT", "47480")), http, http + 10, http + 11]


def _listeners() -> dict[int, int]:
    """``{pid: port}`` for whatever listens on the demo's ports."""
    out = {}
    for port in demo_ports():
        for pid, _, _ in _lsof("-iTCP:%d" % port, "-sTCP:LISTEN"):
            out.setdefault(pid, port)
    return out


def _refuse_on(others: dict[int, str], inside: set[int], home: Path, done: str = "Nothing was changed.") -> None:
    if others:
        listed = "; ".join(f"pid {pid} ({_command(pid) or 'gone'}) holds {name}" for pid, name in sorted(others.items()))
        raise ResetRefused(f"other processes hold files under {home}: {listed}. Close them, then reset again. {done}")
    if inside:
        listed = ", ".join(f"pid {pid} ({_command(pid) or 'gone'})" for pid in sorted(inside))
        raise ResetRefused(f"these are working in {home}: {listed}. cd out of it (a terminal: cd ~), then reset again. {done}")


def reset(home: Path, say=print) -> int:
    _check_target(home)
    if goose_running():
        raise ResetRefused("Goose Desktop is running: quit it first (osascript -e 'quit app \"Goose\"'), then reset again. "
                           "Nothing was changed.")
    ours, others, inside = holders(home)
    _refuse_on(others, inside, home)
    if ours:
        _stop(home, ours)
        say("stopped the demo's own processes on this home: " + ", ".join(f"pid {pid}" for pid in sorted(ours)))
    kept = "The demo's own processes were stopped; the home was kept." if ours else "Nothing was changed."
    try:
        again, others, inside = holders(home)  # again: nothing may have taken the home meanwhile
        listening = _listeners()
    except ResetRefused as e:
        raise ResetRefused(f"{e} {kept}") from None
    if again:
        raise ResetRefused(f"the demo's processes {sorted(again)} did not stop; the home was kept. Stop them (kill -9 <pid>), "
                           "then reset again.")
    _refuse_on(others, inside, home, kept)
    if listening:  # a stage from before stages held a lock (or another program) still on the demo's ports
        listed = "; ".join(f"pid {pid} ({_command(pid) or 'gone'}) on port {port}" for pid, port in sorted(listening.items()))
        raise ResetRefused(f"something still listens on the demo's ports: {listed}. An older stage.py? Stop it (kill <pid>), "
                           f"then reset again. {kept}")
    if home.exists():
        shutil.rmtree(home)
    say(f"removed {home}")
    gone = clear_recipe_trust()
    say(f"cleared Goose's trust in all {gone} recipes it had trusted, not only the demo's three (each asks Trust and Execute "
        "again), and the saved Maya recipe")
    return 0
