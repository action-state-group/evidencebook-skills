# SPDX-License-Identifier: Apache-2.0
"""``demo.py reset``: put this Mac back to before the demo ran.

In order, and changing nothing until every check passes: refuse a home that is ``/``, your user folder or a folder
above it, or a symlink; refuse while Goose Desktop runs (its windows hold servers on the home and would trust the
recipes again); find who holds files under the home or listens on the stage's ports (``lsof``; refuse if that cannot
be checked). The demo's own processes are Python running ``stage.py`` or ``desktop_server.py`` that either hold one of
the home's lock files (a ``desktop_server.py`` holds ``.desktop-<role>.lock``, a ``stage.py`` holds
``stage/.stage.lock``, :data:`parties.STAGE_LOCK`), or, like a stage started before stages held a lock, hold a file
under the home or listen on the stage's ports and either name this home in their arguments or run from this
checkout's ``demo/ard``, whatever commit started them. Anything else holding the home or listening on those ports stops
the reset. Then stop ours (SIGTERM, then SIGKILL, each pid checked again just before each signal), check again, delete
the home, and clear Goose's trust in the recipes the demo's windows opened, so each window asks Trust and Execute
again.

Goose Desktop 1.59.2 keeps one file per trusted recipe, ``<userData>/recipe_hashes/<sha256>.hash`` (one folder for
every Goose on the Mac, the demo's included). :func:`trust_hash` computes that name the way Goose does, so
``open-windows.py`` notes the hash of each recipe it opens (:func:`note_trust`, in the demo's own Goose root, which
every home shares and reset keeps) and reset deletes exactly those files: never a recipe the person trusted, and never
by time. When no noted hash names a file (nothing trusted yet, or a Goose that names its files differently), it deletes
nothing and says so."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

SAVED_RECIPE = "maya-buys-conference-badges.yaml"
DEFAULT_HOME = "~/.config/ard-commerce-demo"  # demo.DEFAULT_HOME, kept here so reset needs no evidencebook checkout
HERE = Path(__file__).resolve().parent  # this checkout's demo/ard: a stage or server run from here is ours
STAGE_LOCK = ".stage.lock"  # parties.STAGE_LOCK, kept here so reset needs none of the demo's heavier modules
#: The demo's own Goose root: Goose 1.59.2 keeps its config (provider, extensions), data and state under
#: ``GOOSE_PATH_ROOT`` when it is set (crates/goose/src/config/paths.rs), and Goose Desktop reads it from its own
#: environment at launch (ui/desktop/src/main.ts). So the demo starts Goose itself with this root and never writes the
#: user's own ~/.config/goose. It lives outside the demo home, so reset keeps it and the provider setup is done once.
GOOSE_ROOT_DEFAULT = "~/.config/ard-commerce-goose"


def goose_root() -> Path:
    return Path(os.environ.get("ARD_GOOSE_ROOT", GOOSE_ROOT_DEFAULT)).expanduser()


class ResetRefused(SystemExit):
    """The reset changed nothing: the message says why and what to do."""


def goose_running() -> bool:
    """Whether Goose Desktop runs (its main binary, not the ``goose`` CLI)."""
    run = subprocess.run(["pgrep", "-f", "Goose.app/Contents/MacOS/Goose"], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if run.returncode not in (0, 1):
        raise ResetRefused(f"could not check whether Goose runs (pgrep: {run.stderr.strip() or run.returncode}).")
    return run.returncode == 0


#: How long reset waits for Goose to exit: `osascript -e 'quit app "Goose"'` returns before Goose has gone.
GOOSE_WAIT_S = 15.0


def goose_quitting(wait_s: float | None = None) -> bool:
    """Whether Goose Desktop still runs after waiting up to ``wait_s`` for a quit already asked for to finish."""
    end = time.monotonic() + (GOOSE_WAIT_S if wait_s is None else wait_s)
    while goose_running():
        if time.monotonic() >= end:
            return True
        time.sleep(0.5)
    return False


def _lsof(*args: str) -> list[tuple[int, str, str]]:
    """``(pid, fd, name)`` for each open file ``lsof`` reports; refuses if lsof is missing or fails."""
    if not shutil.which("lsof"):
        raise ResetRefused("lsof is needed to see what holds the home, and it is not on PATH.")
    run = subprocess.run(["lsof", "-F", "pfn", *args], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if run.returncode not in (0, 1) or run.stderr.strip():  # any complaint means the scan may be partial
        raise ResetRefused(f"lsof could not finish ({run.stderr.strip() or run.returncode}). Run reset again; if it keeps failing, "
                           "stop stage.py and desktop_server.py yourself.")
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
            raise ResetRefused(f"{lock} is not a plain file, so who holds it says nothing about this home.")
    return found


def _argv(pid: int) -> list[str] | None:
    """The process's own argument list, word boundaries kept (``ps`` joins them with spaces, so a path with a space
    in it would split): ``/proc/<pid>/cmdline`` on Linux, ``KERN_PROCARGS2`` on macOS. None if it cannot be read."""
    proc = Path(f"/proc/{pid}/cmdline")
    if proc.exists():
        try:
            return [a.decode(errors="replace") for a in proc.read_bytes().split(b"\0") if a]
        except OSError:
            return None
    try:
        import ctypes
        import ctypes.util

        libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        mib = (ctypes.c_int * 3)(1, 49, pid)  # CTL_KERN, KERN_PROCARGS2
        size = ctypes.c_size_t(0)
        if libc.sysctl(mib, 3, None, ctypes.byref(size), None, 0) != 0:
            return None
        buf = ctypes.create_string_buffer(size.value)
        if libc.sysctl(mib, 3, buf, ctypes.byref(size), None, 0) != 0:
            return None
        raw = buf.raw[: size.value]
        argc = int.from_bytes(raw[:4], "little")
        rest = raw[4:]
        rest = rest[rest.index(b"\0"):].lstrip(b"\0")  # skip the executable path and its padding
        return [a.decode(errors="replace") for a in rest.split(b"\0")[:argc]]
    except (OSError, ValueError, AttributeError):
        return None


#: Python's long options that take the next word as their value.
_VALUE_OPTIONS = {"--check-hash-based-pycs"}


def _script_at(argv: list[str] | None) -> int | None:
    """Where in ``argv`` Python's script is, when ``argv`` is Python running one of :data:`SCRIPTS` (not ``-c`` or
    ``-m``)."""
    if not argv or "python" not in Path(argv[0]).name.lower():
        return None
    i = 1
    while i < len(argv) and argv[i].startswith("-"):
        arg = argv[i]
        i += 1
        if arg == "--":
            break
        if arg == "-":  # the program comes from stdin
            return None
        if arg.startswith("--"):
            i += 1 if arg in _VALUE_OPTIONS else 0
            continue
        # Short options group (-Bu) and the last may take its value attached (-Wignore, -ccode) or as the next word.
        for k, flag in enumerate(arg[1:], start=1):
            if flag in "cm":  # -c, -m and their grouped or attached forms (-Ic, -c'…'): not a script
                return None
            if flag in "WX":
                i += 0 if arg[k + 1:] else 1
                break
    return i if i < len(argv) and Path(argv[i]).name in SCRIPTS else None


def _runs_our_script(pid: int) -> bool:
    """Whether ``pid`` is Python running one of :data:`SCRIPTS` as its script."""
    return _script_at(_argv(pid)) is not None


def _cwd(pid: int) -> Path | None:
    """The process's working directory, to read the relative paths in its arguments."""
    for _, fd, name in _lsof("-a", "-p", str(pid), "-d", "cwd"):
        if fd == "cwd":
            return Path(name)
    return None


def _started_for(pid: int, home: Path) -> bool:
    """Whether ``pid`` is our script for this home with no lock to show it (a stage started before stages held one):
    its arguments name this home, or its script is this checkout's own, whatever commit started it."""
    argv = _argv(pid)
    i = _script_at(argv)
    if i is None:
        return False
    base = None

    def path(arg: str) -> Path | None:
        nonlocal base
        try:  # a stranger's argument (~nosuchuser, a symlink loop) is no match, never a traceback
            p = Path(arg).expanduser()
            if not p.is_absolute():
                base = base or _cwd(pid)
                if base is None:
                    return None
                p = base / p
            return p.resolve()
        except (RuntimeError, OSError):
            return None

    if (script := path(argv[i])) is not None and script.parent == HERE:
        return True
    target = home.resolve()
    return any(path(a) == target for a in argv[i + 1:] if not a.startswith("-"))


def _lock_holders(home: Path) -> set[int]:
    locks = _locks(home)
    return {pid for pid, _, _ in _lsof(*map(str, locks))} - {os.getpid()} if locks else set()


def _ours(home: Path) -> set[int]:
    """The demo's own processes on this home (see the module's docstring)."""
    return holders(home)[0]


def holders(home: Path) -> tuple[set[int], dict[int, str], set[int]]:
    """``(ours, others, inside)`` for this home: the demo's own processes, any other process holding a file under it
    (pid: file), and processes whose working directory is in it (a shell, say). Listeners on the stage's ports that
    are ours count in ``ours``; :func:`_listeners` names the rest."""
    holding_locks = _lock_holders(home) if home.exists() else set()
    ours = {pid for pid in holding_locks if _runs_our_script(pid)}
    others, inside = {pid: "a lock file of this home" for pid in holding_locks - ours}, set()
    found = _lsof("+D", str(home)) if home.exists() else []
    near = {pid for pid, _, _ in found} | set(_listeners())
    ours |= {pid for pid in near - ours - holding_locks - {os.getpid()} if _started_for(pid, home)}
    for pid, fd, name in found:
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
    """Send ``sig`` to each pid that is still ours right now (a pid that let go may have been reused); return the
    ones signalled."""
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
        raise ResetRefused(f"{home} is a symbolic link: reset deletes only a real folder.")
    target, user = home.resolve(), Path.home().resolve()
    if target == Path(target.anchor) or target == user or target in user.parents:
        raise ResetRefused(f"refusing to reset {home}: it is / or your user folder or above it.")


#: In the demo's Goose root: the trust hashes of the recipes open-windows.py opened, for reset to delete.
DEMO_TRUST = "ard-recipe-trust.json"

#: The keys Goose Desktop 1.59.2 hashes, in its order (see :func:`trust_hash`): ``zRecipeDto`` and the stdio member of
#: ``zRecipeExtensionDto`` in ui/goose-acp-client/src/generated/zod.gen.ts at the v1.59.2 tag (9da692f).
_RECIPE_KEYS = ("version", "title", "description", "instructions", "prompt", "extensions", "settings", "activities",
                "author", "parameters", "response", "sub_recipes", "retry")
_STDIO_KEYS = ("name", "description", "cmd", "args", "envs", "env_keys", "timeout", "cwd", "bundled", "available_tools",
               "type")


def _hashes(user: Path | None = None) -> Path:
    return (user or Path.home()) / "Library" / "Application Support" / "Goose" / "recipe_hashes"


def trust_hash(recipe: dict) -> str:
    """The name Goose Desktop 1.59.2 gives the trust file of ``recipe`` (without ``.hash``).

    At the v1.59.2 tag (9da692f), ui/desktop/src/utils/recipeHash.ts hashes ``JSON.stringify(recipe)`` with sha256, and
    the recipe it gets (ui/desktop/src/sessions.ts ``ensureRecipeConsent``) is the server's decode of the link
    (``_goose/unstable/recipes/decode``) parsed by the client's zod schema: keys in the schema's order, absent ones left
    out, ``version`` defaulting to "1.0.0". The decode returns a recipe like the demo's as it came, but normalizes
    some others (an extension without a description gets "", empty ``args``, ``envs`` or ``env_keys`` are dropped,
    disallowed ``envs`` too), so any recipe outside the demo's shape is refused rather than guessed: only stdio
    extensions with a description, non-empty ``args`` and no ``envs`` or ``env_keys``. Checked against the three trust
    files the demo's windows made on 2026-11-25."""
    r = {"version": "1.0.0", **recipe}
    out = {k: r[k] for k in _RECIPE_KEYS if k in r}
    if out.get("extensions"):
        if any(e.get("type") != "stdio" or not e.get("description") or not e.get("args") or "envs" in e
               or "env_keys" in e for e in out["extensions"]):
            raise ValueError("trust_hash covers the demo's recipe shape only: stdio extensions with a description, "
                             "non-empty args and no envs or env_keys")
        out["extensions"] = [{k: e[k] for k in _STDIO_KEYS if k in e} for e in out["extensions"]]
    return hashlib.sha256(json.dumps(out, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _noted(root: Path) -> set[str]:
    try:
        names = json.loads((root / DEMO_TRUST).read_text())
    except (OSError, ValueError):
        return set()
    hexdigest = set("0123456789abcdef")
    return ({n for n in names if isinstance(n, str) and len(n) == 64 and set(n) <= hexdigest}
            if isinstance(names, list) else set())


def note_trust(recipes: list[dict], root: Path) -> None:
    """Add the trust hashes of the recipes about to open to the note in the demo's Goose root."""
    root.mkdir(parents=True, exist_ok=True)
    (root / DEMO_TRUST).write_text(json.dumps(sorted(_noted(root) | {trust_hash(r) for r in recipes})))


def clear_recipe_trust(root: Path, user: Path | None = None) -> int:
    """Delete the trust files named by the note (the recipes the demo's windows opened), then the note, and the saved
    Maya recipe; return how many trust files went. Nothing else in Goose's trust folder is touched."""
    base = user or Path.home()
    (base / ".config" / "goose" / "recipes" / SAVED_RECIPE).unlink(missing_ok=True)
    hashes, gone = _hashes(user), 0
    for h in sorted(_noted(root)):
        f = hashes / f"{h}.hash"
        if f.is_file():
            f.unlink()
            gone += 1
    (root / DEMO_TRUST).unlink(missing_ok=True)
    return gone


def demo_ports() -> list[int]:
    """The ports the demo's stage listens on (parties: the relay, the stand-in registry and the two seller sites)."""
    http = int(os.environ.get("ARD_STAGE_PORT", "47481"))
    return [int(os.environ.get("ARD_RELAY_PORT", "47480")), http, http + 10, http + 11]


def _listeners() -> dict[int, int]:
    """``{pid: port}`` for whatever listens on the demo's ports, ours or not."""
    out = {}
    for port in demo_ports():
        for pid, _, _ in _lsof("-iTCP:%d" % port, "-sTCP:LISTEN"):
            out.setdefault(pid, port)
    return out


def _refuse_on(others: dict[int, str], inside: set[int], home: Path, ours: set[int]) -> None:
    listening = {pid: port for pid, port in _listeners().items() if pid not in ours}
    if listening:
        listed = "; ".join(f"pid {pid} ({_command(pid) or 'gone'}) on port {port}" for pid, port in sorted(listening.items()))
        raise ResetRefused(f"something that is not this demo's stage listens on the stage's ports: {listed}. It neither "
                           f"names {home} nor runs from {HERE}, so reset leaves it alone: stop it, then reset again.")
    if others:
        listed = "; ".join(f"pid {pid} ({_command(pid) or 'gone'}) holds {name}" for pid, name in sorted(others.items()))
        raise ResetRefused(f"other processes hold files under {home}: {listed}. Close them, then reset again.")
    if inside:
        listed = ", ".join(f"pid {pid} ({_command(pid) or 'gone'})" for pid in sorted(inside))
        raise ResetRefused(f"these are working in {home}: {listed}. cd out of it (a terminal: cd ~), then reset again.")


def reset(home: Path, say=print, root: Path | None = None) -> int:
    """Each check refuses with its reason; this adds what was changed by then: nothing before the stop, the stopped
    processes (and the home kept) after it."""
    try:
        _check_target(home)
        if goose_quitting():
            raise ResetRefused(f"Goose Desktop is still running after {GOOSE_WAIT_S:.0f} s: quit it first "
                               "(osascript -e 'quit app \"Goose\"'), then reset again.")
        ours, others, inside = holders(home)
        _refuse_on(others, inside, home, ours)
    except ResetRefused as e:
        raise ResetRefused(f"{e} Nothing was changed.") from None
    try:
        if ours:
            _stop(home, ours)
            say("stopped stage.py and desktop_server.py on this home: " + ", ".join(f"pid {pid}" for pid in sorted(ours)))
        again, others, inside = holders(home)  # again: nothing may have taken the home meanwhile
        if again:
            raise ResetRefused(f"stage.py or desktop_server.py {sorted(again)} did not stop. Stop them (kill -9 <pid>), then reset again.")
        _refuse_on(others, inside, home, again)
    except ResetRefused as e:
        done = "stage.py and desktop_server.py on this home were stopped; the home was kept." if ours else "Nothing was changed."
        raise ResetRefused(f"{e} {done}") from None
    if home.exists():
        shutil.rmtree(home)
    say(f"removed {home}")
    gone = clear_recipe_trust(root or goose_root())
    if gone:
        say(f"cleared Goose's trust in {gone} of the demo's recipes (each window asks Trust and Execute again); other "
            "recipes keep theirs; removed the saved Maya recipe")
    else:
        say("deleted no Goose recipe trust: no trust file matches a recipe the demo's windows opened (none trusted "
            "since the last reset, or a Goose that names its trust files differently); removed the saved Maya recipe")
    return 0


def main(argv: list[str] | None = None) -> int:
    """``demo.py reset [--home DIR]``; ``ARD_HOME`` wins over ``--home``, as for the demo's other commands."""
    ap = argparse.ArgumentParser(prog="demo.py reset", description=__doc__.splitlines()[0])
    ap.add_argument("--home", default=DEFAULT_HOME)
    args = ap.parse_args(argv)
    return reset(Path(os.environ.get("ARD_HOME", args.home)).expanduser())
