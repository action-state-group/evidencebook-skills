# SPDX-License-Identifier: Apache-2.0
"""The set-up's witness check makes a real stamp (evidencebook-skills#359): taken, refused (409 and another 4xx) and
not reached, each against capsulectl-deal itself, with a local witness the throwaway profile is pointed at."""
from __future__ import annotations

import http.server
import os
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
from pathlib import Path

import pytest

import witness_check as wc

#: A tick as capsulectl-deal (evidencebook 4c07d0f) printed it when Action State's witness took the stamp.
TAKEN = {"cadence_log": "deal-cadence/bacb0c7fa7cfa304", "checkpoint": 4, "delivered": [3], "pending": [
    {"checkpoint": 4, "not_tried_this_run": True, "reason": "not_attempted",
     "text": "pending: not sent yet; it goes at the next tick."}], "published_this_run": 1, "state": "ticked"}

needs_ctl = pytest.mark.skipif(not os.environ.get("CAPSULECTL_DEAL") or not shutil.which("openssl"),
                               reason="CAPSULECTL_DEAL names capsulectl-deal, and openssl makes the local witness's cert")


@pytest.fixture
def witness_on(monkeypatch):
    monkeypatch.setenv("ARD_WITNESS", "public")


def test_off_checks_nothing(monkeypatch):
    """With ARD_WITNESS=off no stamp is made: not even a throwaway profile."""
    import ctl

    monkeypatch.setenv("ARD_WITNESS", "off")
    monkeypatch.setattr(ctl, "Ctl", lambda *a, **k: pytest.fail("no profile is made with ARD_WITNESS=off"))
    r = wc.check()
    assert r.ok and "ARD_WITNESS=off" in r.line


def test_taken(witness_on, monkeypatch):
    """A tick that delivered a checkpoint passes, and the throwaway folder is gone afterwards."""
    homes: list[Path] = []

    class Ctl:
        def __init__(self, home, profile, binary=None):
            homes.append(Path(home))

        def run(self, *args):
            return TAKEN if args[0] == "tick" else {}

    import ctl

    monkeypatch.setattr(ctl, "Ctl", Ctl)
    r = wc.check(say=lambda _: None)
    assert r == wc.Result(True, "Action State's witness took a test stamp.")
    assert homes and not homes[0].exists()


REFUSED_409 = {"checkpoint": 7, "delivered": [], "state": "ticked", "pending": [{"checkpoint": 7, "reason": "witness_error",
    "text": "not delivered: the witness answered with an error (HTTP 409); this delivery is not retried."}]}


def test_classify():
    assert wc.classify(TAKEN).ok
    # an older checkpoint taken while the witness refuses the newer one for good is the failure this check is for
    assert not wc.classify({**REFUSED_409, "delivered": [4]}).ok
    assert "(HTTP 409)" in wc.classify(REFUSED_409).line
    assert wc.classify({"delivered": [], "pending": [{"reason": "not_attempted", "text": "pending: not sent yet"}]}) is None
    assert wc.classify({"delivered": [], "pending": [{"reason": "refused", "text": "pending: ... (HTTP 403) ..."}]}) is None


# -- against capsulectl-deal, with a local witness -------------------------------------------------------------------


@pytest.fixture(scope="module")
def cert(tmp_path_factory):
    d = tmp_path_factory.mktemp("cert")
    subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes",
                    "-keyout", str(d / "k.pem"), "-out", str(d / "c.pem"), "-days", "2", "-subj", "/CN=127.0.0.1",
                    "-addext", "subjectAltName=IP:127.0.0.1"], check=True, capture_output=True)
    return d


def serve(cert: Path, status: int, hang: threading.Event | None = None):
    """A witness on 127.0.0.1 that answers every stamp with ``status`` (or, with ``hang``, not until it is set); its
    home page answers 200."""
    posts: list[str] = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            posts.append(self.path)
            if hang is not None:
                hang.wait(120)
            self.send_response(status)
            self.end_headers()
            self.wfile.write(b"refused")

        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"home")

        def log_message(self, *_):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert / "c.pem", cert / "k.pem")
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, posts


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def made_folders() -> set[str]:
    return {p.name for p in Path(tempfile.gettempdir()).glob("ard-witness-check-*") if p.is_dir()}


@needs_ctl
@pytest.mark.parametrize("status", [409, 400])
def test_refused(witness_on, monkeypatch, cert, tmp_path, status):
    """A witness whose home page answers but that refuses stamps fails at once, in plain words, with the details in
    the log only."""
    monkeypatch.setenv("SSL_CERT_FILE", str(cert / "c.pem"))
    srv, posts = serve(cert, status)
    before = made_folders()
    try:
        log = tmp_path / "check.log"
        r = wc.check(log=log, endpoint=f"https://127.0.0.1:{srv.server_address[1]}", wait_s=20)
    finally:
        srv.shutdown()
    assert not r.ok
    assert r.line == (f"Action State's witness answered but refused a test stamp (HTTP {status}). Its home page may "
                      "still load, but the demo's records would not be time-stamped.")
    assert posts, "the check sent a stamp"
    assert "deal tick --now" in log.read_text()
    assert made_folders() <= before


@needs_ctl
def test_not_reached(witness_on, monkeypatch, cert, tmp_path):
    monkeypatch.setenv("SSL_CERT_FILE", str(cert / "c.pem"))
    r = wc.check(log=tmp_path / "check.log", endpoint=f"https://127.0.0.1:{free_port()}", wait_s=3)
    assert r == wc.Result(False, "Action State's witness could not be reached: check this Mac's network.")


@needs_ctl
def test_no_answer(witness_on, monkeypatch, cert, tmp_path):
    """A witness that takes the connection but never answers a stamp fails once the wait is over."""
    monkeypatch.setenv("SSL_CERT_FILE", str(cert / "c.pem"))
    hang = threading.Event()
    srv, posts = serve(cert, 200, hang)
    try:
        r = wc.check(log=tmp_path / "check.log", endpoint=f"https://127.0.0.1:{srv.server_address[1]}", wait_s=3)
    finally:
        hang.set()
        srv.shutdown()
    assert posts
    assert r == wc.Result(False, "Action State's witness did not answer a test stamp within 3 seconds.")


def test_main_says_one_line(witness_on, monkeypatch, capsys):
    """The command prints one plain line and where the details are; exit 1."""
    monkeypatch.setattr(wc, "check", lambda log: wc.Result(False, "Action State's witness took no test stamp."))
    assert wc.main([]) == 1
    err = capsys.readouterr().err.splitlines()
    assert err[0] == "Action State's witness took no test stamp."
    assert err[1].startswith("The details are in ") and err[1].endswith(".log.")
