# SPDX-License-Identifier: Apache-2.0
"""``demo.py reset``: put this Mac back to before the demo ran.

In order: refuse while Goose Desktop runs (its windows hold servers on the home and would trust the recipes again);
stop the demo's own processes on the home (``stage.py``, which names the home in its command line, and any
``desktop_server.py`` with a file open under it); refuse if anything else holds the home; delete the home; then clear
Goose's recipe trust, so each window asks Trust and Execute again.

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

OURS = ("demo/ard/stage.py", "desktop_server.py")
SAVED_RECIPE = "maya-buys-conference-badges.yaml"


class ResetRefused(SystemExit):
    """The reset changed nothing: the message says why and what to do."""


def goose_running() -> bool:
    """Whether Goose Desktop runs (its main binary, not the ``goose`` CLI)."""
    run = subprocess.run(["pgrep", "-f", "Goose.app/Contents/MacOS/Goose"], capture_output=True, stdin=subprocess.DEVNULL)
    return run.returncode == 0


def _commands() -> dict[int, str]:
    run = subprocess.run(["ps", "-axww", "-o", "pid=,command="], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    out = {}
    for line in run.stdout.splitlines():
        pid, _, command = line.strip().partition(" ")
        if pid.isdigit() and int(pid) != os.getpid():
            out[int(pid)] = command.strip()
    return out


def _holding(home: Path) -> set[int]:
    """Processes with a file open under the home (lsof; none found if lsof is missing)."""
    if not shutil.which("lsof"):
        return set()
    run = subprocess.run(["lsof", "-t", "+D", str(home)], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return {int(p) for p in run.stdout.split() if p.isdigit()} - {os.getpid()}


def processes_on(home: Path) -> tuple[dict[int, str], dict[int, str]]:
    """``(ours, others)`` on this home: the demo's own processes, and anything else holding a file under it."""
    commands = _commands()
    ours, others = {}, {}
    names = {str(home), str(home.resolve())}  # the stage names the home as it was given (/tmp is /private/tmp on macOS)
    for pid, command in commands.items():
        if "demo/ard/stage.py" in command and any(n in command for n in names):
            ours[pid] = command
    if home.exists():
        for pid in _holding(home):
            command = commands.get(pid, "")
            (ours if any(o in command for o in OURS) else others)[pid] = command
    return ours, others


def _stop(pids: list[int], wait_s: float = 5.0) -> None:
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + wait_s
    alive = list(pids)
    while alive and time.monotonic() < deadline:
        alive = [p for p in alive if _alive(p)]
        time.sleep(0.1)
    for pid in alive:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:  # a child that exited but was not reaped yet is gone for our purposes
        done, _ = os.waitpid(pid, os.WNOHANG)
        return done == 0
    except ChildProcessError:
        return True


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


def reset(home: Path, say=print) -> int:
    if goose_running():
        raise ResetRefused("Goose Desktop is running: quit it first (osascript -e 'quit app \"Goose\"'), then reset again. "
                           "Nothing was changed.")
    ours, others = processes_on(home)
    if others:
        listed = "; ".join(f"{pid}: {cmd}" for pid, cmd in sorted(others.items()))
        raise ResetRefused(f"other processes hold files under {home}: {listed}. Stop them (kill <pid>), then reset again. "
                           "Nothing was changed.")
    if ours:
        _stop(sorted(ours))
        say("stopped the demo's own processes on this home: " + ", ".join(f"pid {pid}" for pid in sorted(ours)))
    if home.exists():
        shutil.rmtree(home)
    say(f"removed {home}")
    gone = clear_recipe_trust()
    say(f"cleared Goose's trust in all {gone} recipes it had trusted, not only the demo's three (each asks Trust and Execute "
        "again), and the saved Maya recipe")
    return 0
