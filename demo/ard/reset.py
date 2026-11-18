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
    if run.returncode not in (0, 1) or (run.returncode == 1 and run.stderr.strip() and "No such file" not in run.stderr):
        raise ResetRefused(f"lsof failed ({run.stderr.strip() or run.returncode}). Nothing was changed.")
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


def _locks(home: Path) -> list[Path]:
    found = sorted(home.glob(".desktop-*.lock"))
    if (home / "stage" / STAGE_LOCK).exists():
        found.append(home / "stage" / STAGE_LOCK)
    return found


def _ours(home: Path) -> set[int]:
    """The pids holding one of the home's own lock files: its stage and its desktop servers."""
    locks = _locks(home)
    if not locks:
        return set()
    return {pid for pid, _, _ in _lsof(*map(str, locks))} - {os.getpid()}


def holders(home: Path) -> tuple[set[int], dict[int, str], set[int]]:
    """``(ours, others, inside)`` for this home: the demo's own processes, any other process holding a file under it
    (pid: file), and processes whose working directory is in it (a shell, say)."""
    if not home.exists():
        return set(), {}, set()
    ours = _ours(home)
    others, inside = {}, set()
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


def _refuse_on(others: dict[int, str], inside: set[int], home: Path) -> None:
    if others:
        listed = "; ".join(f"pid {pid} ({_command(pid) or 'gone'}) holds {name}" for pid, name in sorted(others.items()))
        raise ResetRefused(f"other processes hold files under {home}: {listed}. Close them, then reset again. Nothing was changed.")
    if inside:
        listed = ", ".join(f"pid {pid} ({_command(pid) or 'gone'})" for pid in sorted(inside))
        raise ResetRefused(f"these are working in {home}: {listed}. cd out of it (a terminal: cd ~), then reset again. "
                           "Nothing was changed.")


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
    ours, others, inside = holders(home)  # again: nothing may have taken the home meanwhile
    if ours:
        raise ResetRefused(f"the demo's processes {sorted(ours)} did not stop; the home was kept. Stop them (kill -9 <pid>), "
                           "then reset again.")
    _refuse_on(others, inside, home)
    if home.exists():
        shutil.rmtree(home)
    say(f"removed {home}")
    gone = clear_recipe_trust()
    say(f"cleared Goose's trust in all {gone} recipes it had trusted, not only the demo's three (each asks Trust and Execute "
        "again), and the saved Maya recipe")
    return 0
