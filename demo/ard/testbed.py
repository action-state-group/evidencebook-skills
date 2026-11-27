#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The multi-role testbed (evidencebook-skills#382): every role of the ARD deal, each on its own screen, in one step.

    python testbed.py up [--witness public|local|off] [--no-probe]
                                     # measure the hosted witness, reset, start the witness, seed, start the
                                     # countersigner, open every screen
    python testbed.py reopen                             # open the screens again (after quitting Goose), same witness
    python testbed.py down                               # close the screens, reset, stop the witness
    python testbed.py env                                # the export lines for this testbed's witness

The roles and their choices are in ``testbed.yaml``. The four agents (Alder and Kestrel, the sellers; Maya, the buyer;
the adjudicator) each get a Goose window (``goose/open-windows.py``); the witness, the payment rail, the catalog
stand-in and the countersigner, which run no agent, each get a window of the tmux session ``ard-testbed`` showing what the parties sent that role and got back (``watch.py``). ``up`` runs,
in this order: if Goose is running, ask before quitting it; ``demo.py reset`` (which also stops the screens of an
earlier run); stop the witness an earlier ``up`` started; start the witness (``witness: local``), ``demo.py seed``, open the
screens in tmux, open the Goose windows. A failure or Ctrl-C before the windows open stops the witness this run
started, and so does a window that does not open. ``testbed.sh`` runs the set-up script first and then this, so one command does all of it.

``witness: local`` starts capsule-anchor at the release Action State's hosted witness runs, with capsule-anchor's own
``ci/local-witness/start.sh`` (its own venv, an in-memory store, a throwaway key, ``https://localhost:<port>`` with a
self-signed certificate), under ``$ARD_TESTBED`` (default ``~/ard-demo/testbed``), and writes the variables every
process of the run needs (``ARD_WITNESS=local``, ``ARD_WITNESS_URL``, ``ARD_WITNESS_KEY``, ``SSL_CERT_FILE``) to
``$ARD_TESTBED/witness.env``, which ``reopen`` and ``env`` read. The witness keeps nothing across a restart, so every
``up`` resets and seeds again."""
from __future__ import annotations

import argparse
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "testbed.yaml"
AGENTS = ("alder", "kestrel", "adjudicator", "maya")
SCREENS = ("witness", "rail", "catalog", "countersigner")
#: A screen's window title where the role's name alone would say too little once its heading scrolls away.
TITLES = {"countersigner": "Countersigner (testbed, not independent)"}
WITNESSES = ("public", "local", "off")
RAILS = ("fake",)  # a rail that moves real money stays behind the RUNBOOK's real-rail steps
#: capsule-anchor at the release Action State's hosted witness runs (v0.1.4: Cloud Run capsule-witness, label
#: git-sha=78a69853bc83, read 2026-11-26, evidencebook-skills#371), and the commit whose ci/local-witness/start.sh
#: starts it (capsule-anchor#118). tests.yml pins the same two for CI and scripts/check.sh (#378).
CAPSULE_ANCHOR_PIN = "78a69853bc83c9c65b9fe79a8270b83727c55304"
LOCAL_WITNESS_START_PIN = "42f5fab488d2edc1fe7338f7da09a31de1b0d5b7"
CAPSULE_ANCHOR_REPO = "https://github.com/action-state-group/capsule-anchor"


class Stop(SystemExit):
    """The testbed stopped: the message says why and what to do."""


def config(path: Path = CONFIG) -> dict:
    """``testbed.yaml``, refused unless it names known roles, all four agents among them, and known choices."""
    c = yaml.safe_load(path.read_text()) or {}
    roles = c.get("roles")
    if set(c) != {"roles", "witness", "rail"} or not isinstance(roles, list):
        raise Stop(f"{path}: needs roles, witness and rail only")
    unknown = [r for r in roles if r not in AGENTS + SCREENS]
    if unknown or len(set(roles)) != len(roles):
        raise Stop(f"{path}: roles are {', '.join(AGENTS + SCREENS)}, each once; not {', '.join(map(str, unknown)) or 'a repeat'}")
    if missing := [a for a in AGENTS if a not in roles]:
        raise Stop(f"{path}: the deal needs all four agents; {', '.join(missing)} is missing")
    if c["witness"] not in WITNESSES or c["rail"] not in RAILS:
        raise Stop(f"{path}: witness is one of {', '.join(WITNESSES)}; rail is {', '.join(RAILS)}")
    return c


def state_dir() -> Path:
    return Path(os.environ.get("ARD_TESTBED", "~/ard-demo/testbed")).expanduser()


def home() -> Path:
    return Path(os.environ.get("ARD_HOME", "~/.config/ard-commerce-demo")).expanduser()


def witness_env_file() -> Path:
    return state_dir() / "witness.env"


def read_env(f: Path) -> dict[str, str]:
    out = {}
    if f.is_file():
        for line in f.read_text().splitlines():
            if line.startswith("export ") and "=" in line:
                k, v = line[len("export "):].split("=", 1)
                out[k] = shlex.split(v)[0] if v else ""
    return out


def write_env(f: Path, env: dict[str, str]) -> None:
    f.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    f.write_text("".join(f"export {k}={shlex.quote(v)}\n" for k, v in env.items()))


# -- the local witness -------------------------------------------------------------------------------------------------

def _pid_file() -> Path:
    return state_dir() / "local-witness" / "pid"


def _is_our_witness(pid: int) -> bool:
    """Whether ``pid`` is the witness this testbed started: uvicorn serving capsule-anchor from our own venv."""
    run = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True,
                         stdin=subprocess.DEVNULL)
    cmd = run.stdout.strip()
    return run.returncode == 0 and str(state_dir() / "local-witness" / "venv") in cmd and "capsule_anchor" in cmd


def stop_witness(say=print) -> None:
    """Stop the witness an earlier ``up`` started, if it still runs; never another process that took its pid."""
    f = _pid_file()
    try:
        pid = int(f.read_text().strip())
    except (OSError, ValueError):
        pid = None
    if pid and _is_our_witness(pid):
        os.kill(pid, signal.SIGTERM)
        for _ in range(50):
            if not _is_our_witness(pid):
                break
            time.sleep(0.1)
        else:
            os.kill(pid, signal.SIGKILL)
        say(f"stopped the testbed's local witness (pid {pid})")
    f.unlink(missing_ok=True)
    witness_env_file().unlink(missing_ok=True)


def _checkout() -> Path:
    """capsule-anchor at :data:`CAPSULE_ANCHOR_PIN`, under ``~/ard-demo`` beside the demo's other checkouts."""
    src = Path(os.environ.get("ARD_CAPSULE_ANCHOR", "~/ard-demo/capsule-anchor")).expanduser()
    git = ["git", "-C", str(src)]
    if not (src / ".git").is_dir():
        subprocess.run(["git", "clone", "--quiet", CAPSULE_ANCHOR_REPO, str(src)], check=True, stdin=subprocess.DEVNULL)
    have = lambda ref: subprocess.run([*git, "cat-file", "-e", f"{ref}^{{commit}}"], capture_output=True).returncode == 0
    if not (have(CAPSULE_ANCHOR_PIN) and have(LOCAL_WITNESS_START_PIN)):
        subprocess.run([*git, "fetch", "--quiet", "origin"], check=True, stdin=subprocess.DEVNULL)
    if subprocess.run([*git, "status", "--porcelain"], capture_output=True, text=True).stdout.strip():
        raise Stop(f"{src} has changes of its own; the testbed does not move it. Commit or remove them, or set "
                   "ARD_CAPSULE_ANCHOR to another folder")
    subprocess.run([*git, "checkout", "--quiet", "--detach", CAPSULE_ANCHOR_PIN], check=True, stdin=subprocess.DEVNULL)
    return src


def witness_python() -> str:
    """A Python 3.11 or later for the local witness's own venv, which the countersigner needs too (both run
    capsule-anchor; the set-up accepts 3.10): this one, else the newest ``python3.N`` on the PATH. Refused before
    anything changes when there is none."""
    if sys.version_info >= (3, 11):
        return sys.executable
    for name in ("python3.14", "python3.13", "python3.12", "python3.11", "python3"):
        exe = shutil.which(name)
        if exe and subprocess.run([exe, "-c", "import sys; sys.exit(sys.version_info < (3, 11))"],
                                  capture_output=True, stdin=subprocess.DEVNULL).returncode == 0:
            return exe
    raise Stop("the local witness and the countersigner need Python 3.11 or later (brew install python); nothing "
               "was changed")


def start_witness(say=print) -> dict[str, str]:
    """Start the local witness with capsule-anchor's own start script; return the variables naming it."""
    src = _checkout()
    d = state_dir()
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    script = d / "start.sh"
    script.write_bytes(subprocess.run(["git", "-C", str(src), "show", f"{LOCAL_WITNESS_START_PIN}:ci/local-witness/start.sh"],
                                      check=True, capture_output=True).stdout)
    out = d / "start.out"
    out.write_text("")
    env = {k: v for k, v in os.environ.items() if not k.upper().endswith("_PROXY")}  # its own localhost checks
    env.update(RUNNER_TEMP=str(d), SRC=str(src), GITHUB_OUTPUT=str(out), BLOCK="false")
    env["PYTHON"] = witness_python()
    say("starting the testbed's local witness (capsule-anchor at the hosted witness's release; about a minute)")
    log = d / "start.log"
    with open(log, "w") as fh:
        run = subprocess.run(["bash", str(script)], env=env, stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    if run.returncode != 0:
        raise Stop(f"the local witness did not start; the details are in {log}")
    got = dict(line.split("=", 1) for line in out.read_text().splitlines() if "=" in line)
    w = {"ARD_WITNESS": "local", "ARD_WITNESS_URL": got["url"], "ARD_WITNESS_KEY": got["public-key"],
         "SSL_CERT_FILE": got["ca-bundle"]}
    write_env(witness_env_file(), w)
    say(f"the local witness answers at {w['ARD_WITNESS_URL']}; its log is {got['log']}")
    return w


# -- the screens -------------------------------------------------------------------------------------------------------

def _python() -> str:
    return sys.executable


def run_env(witness: dict[str, str]) -> dict[str, str]:
    """This shell's environment with the run's witness: ``witness`` as given, else the hosted one (any witness variable
    this shell carries from an earlier run is dropped, so it cannot name a witness that is gone)."""
    env = {k: v for k, v in os.environ.items() if k not in ("ARD_WITNESS", "ARD_WITNESS_URL", "ARD_WITNESS_KEY")}
    env.update(witness or {"ARD_WITNESS": "public"})
    return env


#: The tmux session that holds the testbed's screens, one window each (Ethan, 2026-11-26: no Terminal windows).
TMUX_SESSION = "ard-testbed"


def _tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", *args], capture_output=True, text=True, stdin=subprocess.DEVNULL)


def close_screens() -> None:
    """End the testbed's tmux session, if one is left from an earlier run (its screens' processes go with it)."""
    if shutil.which("tmux"):
        _tmux("kill-session", "-t", f"={TMUX_SESSION}")


def open_screen(role: str, env: dict[str, str]) -> None:
    """One window of the testbed's tmux session (:data:`TMUX_SESSION`) running ``watch.py <role>``, named for the role."""
    if not shutil.which("tmux"):
        raise Stop("tmux is not installed, and the testbed's screens run in it: brew install tmux, then run this again")
    keep = ("ARD_HOME",)
    exports = "".join(f"export {k}={shlex.quote(env[k])}; " for k in keep if env.get(k))
    cmd = f"{exports}exec {shlex.quote(_python())} {shlex.quote(str(HERE / 'watch.py'))} {role}"
    name = TITLES.get(role, role.capitalize() + " (testbed)")
    if _tmux("has-session", "-t", f"={TMUX_SESSION}").returncode == 0:
        run = _tmux("new-window", "-d", "-t", f"={TMUX_SESSION}:", "-n", name, cmd)
    else:
        run = _tmux("new-session", "-d", "-s", TMUX_SESSION, "-n", name, "-x", "160", "-y", "48", cmd)
    if run.returncode != 0:
        raise Stop(f"could not open the {role} screen in tmux: {' '.join(run.stderr.split()) or run.returncode}")


def open_windows(env: dict[str, str], rail: str) -> int:
    return subprocess.run([_python(), str(HERE / "goose" / "open-windows.py"), "--rail", rail], env=env).returncode


def _goose_check(ask=input) -> None:
    import reset

    if not reset.goose_running():
        return
    answer = ask("Goose Desktop is running, and the testbed opens its own. Quit Goose now? [y/N] ").strip().lower()
    if answer not in ("y", "yes"):
        raise Stop("Goose is still running: quit it, then run this again. Nothing was changed.")
    subprocess.run(["osascript", "-e", 'quit app "Goose"'], check=False, stdin=subprocess.DEVNULL)
    if reset.goose_quitting():
        raise Stop("Goose did not quit: quit it yourself, then run this again. Nothing was changed.")


#: The hosted witness's probe (evidencebook-skills#378): one stamp from each of four fresh profiles at once, about the
#: load of the four parties of a run, each given the receipt page's wait (``receipt.PAGE_WAIT_S``).
PROBE = [str(HERE / "tests" / "witness_probe.py"), "--stamps", "1", "--parallel", "4"]


def probe_hosted(say=print) -> str:
    """``"ok"`` when the hosted witness took every probe stamp within the receipt page's wait, ``"slow"`` when it did
    not, ``"unmeasured"`` when the probe could not measure it (exit 2, ``witness_probe.CANNOT_MEASURE``); the probe's
    lines go to the screen."""
    say("measuring Action State's hosted witness: one test stamp from each of four throwaway profiles at once, as a "
        "run's four parties would send (up to a minute)")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ARD_E2E_WITNESS", "ARD_WITNESS"))}
    rc = subprocess.run([_python(), *PROBE], env=env).returncode
    return {0: "ok", 1: "slow"}.get(rc, "unmeasured")


#: What up asks when the probe did not pass, by its outcome.
SWITCH = {
    "slow": "The hosted witness did not take every test stamp within the 30 seconds a receipt page waits, so receipts "
            "may show no witness time.",
    "unmeasured": "The hosted witness could not be measured (the reason is above).",
}


def up(c: dict, say=print, ask=input, probe: bool = True) -> int:
    _goose_check(ask)
    if c["witness"] == "public" and probe and (outcome := probe_hosted(say)) != "ok":
        answer = ask(f"{SWITCH[outcome]} Bring the testbed up on the local test witness instead? Receipts will then "
                     "name it, not Action State's witness. [Y/n] ")
        if answer.strip().lower() in ("", "y", "yes"):
            c["witness"] = "local"
    if c["witness"] == "local" or "countersigner" in c["roles"]:
        witness_python()  # both run capsule-anchor, which needs 3.11: refused here, before the reset, not after it
    if subprocess.run([_python(), str(HERE / "demo.py"), "reset"], env=os.environ).returncode != 0:
        raise Stop("reset refused (it says why above); nothing else was done")
    stop_witness(say)  # only once the reset went through: a refused reset leaves the earlier run as it was
    witness: dict[str, str] = {}
    started, ok, countersigner = False, False, False
    try:
        if c["witness"] == "local":
            started = True  # from here: start.sh may leave its witness running even when it fails
            witness = start_witness(say)
        elif c["witness"] == "off":
            witness = {"ARD_WITNESS": "off"}
            write_env(witness_env_file(), witness)
        env = run_env(witness)
        if subprocess.run([_python(), str(HERE / "demo.py"), "seed"], env=env).returncode != 0:
            raise Stop("seed failed (it says why above)")
        # the countersign upgrade's countersigner (countersigner.py, evidencebook-skills#383): after the seed, which makes
        # the parties it admits; it trusts the run's witness certificate through env's SSL_CERT_FILE; reset stops it
        if "countersigner" in c["roles"]:
            countersigner = True  # from here: a failed start leaves nothing, but a later failure leaves it running
            if subprocess.run([_python(), str(HERE / "countersigner.py"), "up"], env=env).returncode != 0:
                raise Stop("the countersigner did not start (it says why above)")
        close_screens()  # an earlier run's screens, stopped by the reset
        for role in SCREENS:
            if role in c["roles"]:
                open_screen(role, env)
        if any(role in c["roles"] for role in SCREENS):
            say(f"the screens are in tmux: tmux attach -t {TMUX_SESSION} (Ctrl-b n for the next one)")
        rc = open_windows(env, c["rail"])
        ok = rc == 0  # the windows are open: the witness and the screens now belong to them, until `down`
        if not ok:
            say("the windows did not all open; stopping this run's screens and witness. Run testbed.py up again")
        return rc
    except KeyboardInterrupt:
        say("\ninterrupted")
        return 130
    finally:
        if not ok:  # a failed or interrupted run leaves nothing of its own running
            stop_screens(home())
            close_screens()
            if countersigner:
                subprocess.run([_python(), str(HERE / "countersigner.py"), "down"], env=os.environ)
            if started:
                stop_witness(say)


def stop_screens(h: Path) -> None:
    """Stop the screens (``watch.py``) open on this home: each holds ``.watch-<role>.lock``, and only a process running
    our ``watch.py`` is signalled, as reset does."""
    import reset

    for lock in sorted(h.glob(".watch-*.lock")):
        for pid, _, _ in reset._lsof(str(lock)):
            if pid != os.getpid() and reset._runs_our_script(pid):
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass


def reopen(c: dict) -> int:
    """The Goose windows again, on the witness ``up`` started (``witness.env``), or the hosted one."""
    witness = read_env(witness_env_file())
    if witness.get("ARD_WITNESS") == "local":
        try:
            pid = int(_pid_file().read_text().strip())
        except (OSError, ValueError):
            pid = 0
        if not (pid and _is_our_witness(pid)):
            raise Stop("the testbed's local witness is no longer running, and the records already made name it: run "
                       "testbed.py up again (it resets and seeds)")
    return open_windows(run_env(witness), c["rail"])


def down(say=print, ask=input) -> int:
    _goose_check(ask)
    rc = subprocess.run([_python(), str(HERE / "demo.py"), "reset"], env=os.environ).returncode
    if rc != 0:  # the home and its windows' records stay, so the witness they name stays too
        raise Stop("reset refused (it says why above); the witness was left running")
    close_screens()
    stop_witness(say)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="testbed.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["up", "reopen", "down", "env"])
    ap.add_argument("--witness", choices=WITNESSES, help="override testbed.yaml's witness for this run")
    ap.add_argument("--no-probe", action="store_true",
                    help="with the hosted witness, skip measuring it before the run (up only)")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(line_buffering=True)
    try:
        c = config()
        if args.witness:
            c["witness"] = args.witness
        if args.command == "env":
            sys.stdout.write(witness_env_file().read_text() if witness_env_file().is_file() else "")
            return 0
        return {"up": lambda: up(c, probe=not args.no_probe), "reopen": lambda: reopen(c), "down": down}[args.command]()
    except Stop as e:
        print(f"testbed: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
