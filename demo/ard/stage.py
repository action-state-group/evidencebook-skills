#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The stage the demo's windows share, on localhost: the discovery stand-ins (each seller's own origin and the stand-in
registry, :mod:`discovery`) and the adjudicator's rules page (:mod:`adjudicator`). Usually started by the first party that needs it (:func:`ensure_stage`); ``python stage.py <demo
home>`` runs it by hand. It keeps no keys and no records of its own: the sellers' commitments and shared cards, and
the files the parties hand each other, are files under ``<demo home>/stage``."""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import adjudicator as adj  # noqa: E402
import ard  # noqa: E402
import feeds  # noqa: E402
from cast import SELLERS  # noqa: E402

HTTP_PORT = int(os.environ.get("ARD_STAGE_PORT", "47481"))  # the stand-in registry's POST /search, and the rules page
#: Each seller's own origin (its /.well-known/ard.json and commitment), a port of its own.
SELLER_PORTS = {"alder": HTTP_PORT + 10, "kestrel": HTTP_PORT + 11}
REGISTRY_URL = f"http://127.0.0.1:{HTTP_PORT}/search"
#: The fixed table from each seller's publisher domain to the address it is served at (the demo's DNS stand-in).
ORIGINS = {ard.publisher(n): f"http://127.0.0.1:{p}" for n, p in SELLER_PORTS.items()}
#: What the buyer searches for: the item only (the budget and deadline stay with her agent).
QUERY = "conference badges print"
#: The one form of ``lcap.policy_uri`` a seller's commitment carries (evidencebook ``commitment.build``): a file under
#: ``commitments/policies/``, never a path out of it.
POLICY_URI = re.compile(r"policies/[0-9a-f]{64}\.json")
#: Where the catalog stand-in serves a seller's product (#382), on the registry's port.
CATALOG_PATH = re.compile(r"/catalog/([a-z0-9-]+)/([a-z0-9-]+)\.json")


#: The catalog stand-in's origin: the stage serves it beside the registry, and the buyer checks offers only there.
CATALOG_ORIGIN = f"http://127.0.0.1:{HTTP_PORT}"


def catalog_url(seller: str, product: str) -> str:
    return f"{CATALOG_ORIGIN}/catalog/{seller}/{product}.json"


#: Where a stage says which demo home it serves (:func:`serves`).
HOME_PATH = "/stage/home"
#: The file a stage holds open under ``<home>/stage`` for as long as it runs (``demo.py reset`` finds it by it).
STAGE_LOCK = ".stage.lock"


class Stage:
    """The discovery stand-ins and the adjudicator's rules page, over files under ``home/stage``."""

    def __init__(self, home: Path):
        from discovery import Discovery

        self.home = Path(home).expanduser().resolve()  # what it says it serves (HOME_PATH): one spelling per folder
        self.dir = self.home / "stage"
        for sub in ("commitments", "cards", "wire"):
            (self.dir / sub).mkdir(parents=True, exist_ok=True)
        self._held = open(self.dir / STAGE_LOCK, "a")
        self.adjudicator = adj.Adjudicator(self.home).create()
        # each seller's listing links its product in the catalog stand-in, which this stage serves (#382)
        sellers = {n: {**s, "catalog_url": catalog_url(n, s["product"])} for n, s in SELLERS.items()}
        self.discovery = Discovery(sellers, self.commitment, HTTP_PORT, SELLER_PORTS, get=self.page, policy=self.policy)
        self.url = self.discovery.registry.url

    def commitment(self, name: str) -> dict | None:
        f = self.dir / "commitments" / f"{name}.json"
        return json.loads(f.read_bytes()) if f.is_file() else None

    def policy(self, uri: str) -> bytes | None:
        """A seller's signed disclosure policy, at the ``policy_uri`` its commitment names (``policies/<node_id>.json``)."""
        if not POLICY_URI.fullmatch(uri):
            return None
        f = self.dir / "commitments" / uri
        return f.read_bytes() if f.is_file() else None

    def page(self, path: str) -> bytes | None:
        """The adjudicator's published rules, whose SHA-256 every agreement names; and the catalog stand-in's products
        (``/catalog/<seller>/<product>.json``), each read also shown on the catalog's screen (:mod:`feeds`)."""
        if path == "/adjudicator/rules":
            return adj.RULES_TEXT.encode()
        if path == HOME_PATH:  # which home this stage serves (ensure_stage), so a window never takes another's
            return str(self.home).encode()
        m = CATALOG_PATH.fullmatch(path)
        seller = SELLERS.get(m.group(1)) if m else None  # the catalog as this stage read it at its start
        if seller is None or seller["product"] != m.group(2):
            return None
        feeds.catalog_read(self.home, m.group(1), m.group(2))
        return json.dumps({"seller": m.group(1), "product": m.group(2), "title": seller["item"],
                           "price_msat": seller["price_msat"], "currency": "msat", "stand_in": True},
                          sort_keys=True).encode()

    def serve_forever(self) -> None:
        try:
            threading.Event().wait()
        finally:
            self.close()

    def close(self) -> None:
        self.discovery.close()


def stage_up() -> bool:
    """Whether this demo's stage listens. A listener that does not answer ``POST /search`` as the stand-in registry
    does (an old demo's stage, say) is refused rather than taken for this one."""
    try:
        with socket.create_connection(("127.0.0.1", HTTP_PORT), timeout=0.5):
            pass
    except OSError:
        return False
    req = urllib.request.Request(REGISTRY_URL, data=b"{}", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:  # the demo's own localhost stage
            if "query.text" in json.loads(r.read()).get("error", ""):
                return True
    except Exception:
        pass
    raise RuntimeError(f"port {HTTP_PORT} is taken by something that is not this run's stage.py (an earlier "
                       "stage.py, say): stop it, or set ARD_STAGE_PORT to a free port")


#: Under ``<home>/stage``: one file per process that started or reused a stage (:func:`ensure_stage`), named by its pid
#: and holding its start time, so a pid the system gave to another process since is not taken for it. A stage started
#: that way stops once none of them is alive (:func:`owned_wait`), so a run that ends or is interrupted (its windows quit
#: or killed) leaves no stage behind (evidencebook-skills#453).
OWNERS = "owners"
#: Held while a process records itself and looks for a stage (:func:`ensure_stage`), and while an owned stage decides to
#: stop and closes its listeners (:func:`owned_wait`): a window either is seen by the stage, or finds no stage and starts one.
OWNERS_LOCK = ".owners.lock"
#: How often an owned stage looks for a live owner; it stops after two looks in a row find none.
OWNER_CHECK_S = 2.0


def _owners(home: Path) -> Path:
    return Path(home).expanduser() / "stage" / OWNERS


@contextlib.contextmanager
def _owners_locked(home: Path):
    d = _owners(home)
    d.mkdir(parents=True, exist_ok=True)
    with open(d / OWNERS_LOCK, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _started(pid: int) -> str:
    """The process's start time as ``ps`` gives it, or "" when no process has that pid."""
    run = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return run.stdout.strip() if run.returncode == 0 else ""


def add_owner(home: Path, pid: int | None = None) -> None:
    """Record ``pid`` (this process by default) as one the stage serves."""
    pid = pid or os.getpid()
    d = _owners(home)
    d.mkdir(parents=True, exist_ok=True)
    (d / str(pid)).write_text(_started(pid))


def live_owners(home: Path) -> set[int]:
    """The recorded owners still alive (the same pid and start time); a gone owner's file is removed."""
    alive = set()
    d = _owners(home)
    for f in d.iterdir() if d.is_dir() else ():
        if not f.name.isdigit():
            continue
        try:
            recorded = f.read_text()
        except OSError:
            continue
        now = _started(int(f.name))
        if now and now == recorded:
            alive.add(int(f.name))
        else:
            f.unlink(missing_ok=True)
    return alive


def owned_wait(home: Path, close, every: float = OWNER_CHECK_S) -> None:
    """Return once two looks in a row, ``every`` seconds apart, find no live owner, having called ``close`` (which
    closes the stage's listeners) under the owners' lock, so no window records itself in between and then finds the
    stage gone."""
    empty = 0
    while True:
        with _owners_locked(home):
            empty = 0 if live_owners(home) else empty + 1
            if empty >= 2:
                close()
                return
        time.sleep(every)


def _spawn(argv: list[str]) -> None:
    """Start ``argv`` in a session of its own, so it outlives the window that started it."""
    subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def serves() -> str:
    """The demo home the stage on :data:`HTTP_PORT` serves, or "" when it does not say (one from before #453)."""
    try:
        with urllib.request.urlopen(f"{CATALOG_ORIGIN}{HOME_PATH}", timeout=5) as r:  # the demo's own localhost stage
            return r.read().decode()
    except Exception:
        return ""


def ensure_stage(home: Path) -> None:
    """Start the stage as its own process if none listens, so it outlives any one window; it stops once no process
    that started or reused it is alive (:data:`OWNERS`). This process is recorded first, and the owners' lock is held
    until the stage answers, so a second window starting at the same time waits for this stage instead of starting
    another. A stage that serves another home is refused, not reused: it would not see this window as its owner."""
    home = Path(home).expanduser().resolve()  # as the stage names it (Stage.home): one spelling for one folder
    with _owners_locked(home):
        add_owner(home)
        if not stage_up():
            _spawn([sys.executable, str(HERE / "stage.py"), "--owned", str(home)])
            for _ in range(75):
                if stage_up():
                    break
                time.sleep(0.2)
            else:
                raise RuntimeError("the stage (seller origins and registry) did not start")
        other = serves()
        if other != str(home):
            whose = other or "an earlier version of the demo"
            raise RuntimeError(f"port {HTTP_PORT} is taken by the stage of another demo home ({whose}): stop it "
                               "(demo.py reset on that home), or set ARD_STAGE_PORT to a free port")


def main(argv: list[str]) -> int:
    """``stage.py [--owned] [home]``. ``--owned`` (:func:`ensure_stage`): stop once no recorded owner is alive. By
    hand, without it, the stage runs until stopped."""
    args = argv[1:]
    owned = "--owned" in args
    args = [a for a in args if a != "--owned"]
    home = Path(args[0] if args else "~/.config/ard-commerce-demo").expanduser()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))  # so the stage closes its listeners on a stop
    stage = Stage(home)
    print(f"stage: registry {stage.url}, adjudicator rules {adj.rules_url()}", flush=True)
    try:
        if owned:
            owned_wait(home, stage.close)
            print("stage: no process it serves is running; stopped", flush=True)
        else:
            stage.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
