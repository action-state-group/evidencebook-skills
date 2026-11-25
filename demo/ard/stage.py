#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The stage the demo's windows share, on localhost: the discovery stand-ins (each seller's own origin and the stand-in
registry, :mod:`discovery`) and the adjudicator's rules page (:mod:`adjudicator`). Usually started by the first party that needs it (:func:`ensure_stage`); ``python stage.py <demo
home>`` runs it by hand. It keeps no keys and no records of its own: the sellers' commitments and shared cards, and
the files the parties hand each other, are files under ``<demo home>/stage``."""
from __future__ import annotations

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
#: The file a stage holds open under ``<home>/stage`` for as long as it runs (``demo.py reset`` finds it by it).
STAGE_LOCK = ".stage.lock"


class Stage:
    """The discovery stand-ins and the adjudicator's rules page, over files under ``home/stage``."""

    def __init__(self, home: Path):
        from discovery import Discovery

        self.home = Path(home).expanduser()
        self.dir = self.home / "stage"
        for sub in ("commitments", "cards", "wire"):
            (self.dir / sub).mkdir(parents=True, exist_ok=True)
        self._held = open(self.dir / STAGE_LOCK, "a")
        self.adjudicator = adj.Adjudicator(self.home).create()
        self.discovery = Discovery(SELLERS, self.commitment, HTTP_PORT, SELLER_PORTS, get=self.page, policy=self.policy)
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
        """The adjudicator's published rules, whose SHA-256 every agreement names."""
        return adj.RULES_TEXT.encode() if path == "/adjudicator/rules" else None

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


def ensure_stage(home: Path) -> None:
    """Start the stage as its own process if none listens, so it outlives any one window."""
    if stage_up():
        return
    subprocess.Popen([sys.executable, str(HERE / "stage.py"), str(home)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(75):
        if stage_up():
            return
        time.sleep(0.2)
    raise RuntimeError("the stage (seller origins and registry) did not start")


def main(argv: list[str]) -> int:
    home = Path(argv[1] if len(argv) > 1 else "~/.config/ard-commerce-demo").expanduser()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))  # so the stage closes its listeners on a stop
    stage = Stage(home)
    print(f"stage: registry {stage.url}, adjudicator rules {adj.rules_url()}", flush=True)
    try:
        stage.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
