#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The demo's countersigner: a capsule-anchor instance on this Mac that countersigns only the demo parties' books
(evidencebook-skills#383).

    python countersigner.py up      # after seed: start it for the demo home's parties, print where it listens
    python countersigner.py down    # stop it (reset also stops it)

It is capsule-anchor at :data:`ANCHOR_REF` (capsule-anchor#123) with its countersign surface on (``CAPSULE_ANCHOR_REGISTRATION_POLICY=strict``
and ``CAPSULE_ANCHOR_COUNTERSIGN=1``, capsule-anchor ``COUNTERSIGN.md`` §4) and an issuer allowlist of the demo parties
only (§5-6): each row pins a party's log id, which ``capsulectl countersign request`` sends as ``requester.id``, to its
record signing key (capsule-cli ``cli/countersign.go``). Anyone else is refused. It serves HTTPS on a free localhost
port with its own self-signed certificate, which the parties' ``capsulectl`` trusts through ``SSL_CERT_FILE``
(:func:`env`). Never Action State's hosted service.

Its key and certificate are kept in its folder for the life of the demo home, so a countersignature made before a
``down`` and ``up`` still resolves against the same directory row afterwards (capsulectl resolves stored
countersignatures against the profile's directory on every report, evidencebook ``deal_grade.go``). The folder is
:func:`default_dir`, inside the demo home, so ``demo.py reset`` forgets it with the home.

The demo writes its own countersigner directory (:data:`NAME` and the key, ``directory.json``) and names it in each
party's profile (``countersign.directory``), so a party's report counts this countersigner and no other. The operator
runs it and every party, so it is not independent of them; the receipt says so (receipt.countersign_line)."""
from __future__ import annotations

import base64
import json
import os
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

#: capsule-anchor main at capsule-anchor#123: v0.1.4 (the release Action State's hosted witness runs) refuses the
#: withheld copy capsulectl writes (payloads_mode "selected"); #123 accepts it when the bundle discloses nothing.
ANCHOR_REF = "e117b23b5592e9a9badea22de5ab6ae7929e97d5"
ANCHOR_PIP = f"capsule-anchor @ git+https://github.com/action-state-group/capsule-anchor@{ANCHOR_REF}"
#: Its name in the demo's countersigner directory, as the receipt says it (Sherlock2 on #383).
NAME = "the demo's countersigner"
#: The marker in the service's command line that names it as this module's countersigner (:func:`is_ours`).
APP = "capsule_anchor.app:create_app"
HEALTH_WAIT_S = 60
STATE = "state.json"


class CountersignerError(RuntimeError):
    """The countersigner could not start, or is not running: the message says why and what to do."""


def default_dir(home: str | Path) -> Path:
    return Path(home).expanduser() / "countersigner"


# -- the parties it admits -----------------------------------------------------------------------

def log_id(party) -> str:
    """The party's profile log id (``log_id:`` in its capsulectl profile): the ``requester.id`` its requests carry."""
    prof = party.dir / ".config" / "capsule" / "profiles" / f"{party.profile}.yaml"
    for line in prof.read_text().splitlines():
        if line.startswith("log_id:"):
            return line.split(":", 1)[1].strip()
    raise CountersignerError(f"{party.name}: its profile names no log id ({prof})")


def issuers(parties) -> list[dict]:
    """capsule-anchor's issuer allowlist (COUNTERSIGN.md §6): one row per party, its log id pinned to its signing key."""
    return [{"ledger_id": log_id(p), "pubkey_hex": p.key_id} for p in parties]


def directory(key: str) -> dict:
    """The demo's countersigner directory: one row, this countersigner (capsule-cli reads ``{countersigners: [...]}``)."""
    return {"countersigners": [{"name": NAME, "key_ids": [key]}]}


# -- start and stop ------------------------------------------------------------------------------

def _state(d: Path) -> dict | None:
    try:
        return json.loads((d / STATE).read_text())
    except (OSError, ValueError):
        return None


def _argv(pid: int) -> str:
    run = subprocess.run(["ps", "-ww", "-o", "command=", "-p", str(pid)], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return run.stdout.strip() if run.returncode == 0 else ""


def is_ours(d: Path, pid: int) -> bool:
    """Whether ``pid`` is this folder's countersigner: a stale pid a later process reuses is never signalled."""
    argv = _argv(pid)
    return APP in argv and any(str(x / "tls.crt") in argv for x in {Path(d), Path(d).resolve()})


def running(d: str | Path) -> dict | None:
    """The state of the countersigner of folder ``d`` when its process is running, else None."""
    d = Path(d)
    st = _state(d)
    return st if st and is_ours(d, int(st["pid"])) else None


def env(d: str | Path) -> dict[str, str]:
    """What a party needs to reach the running countersigner: its URL, its key, the demo's directory file and a CA
    bundle that trusts its certificate (and every root the caller trusted)."""
    st = running(d)
    if st is None:
        raise CountersignerError("the demo's countersigner is not running: start it with "
                                 "`python demo/ard/countersigner.py up` (after `demo.py seed`)")
    d = Path(d)
    # capsule-cli posts to the URL as given: the countersign surface's own path (capsule-anchor countersign/router.py)
    return {"ARD_COUNTERSIGN_URL": st["url"] + "/countersign/register", "ARD_COUNTERSIGN_KEY": st["key"],
            "ARD_COUNTERSIGN_DIRECTORY": str(d / "directory.json"), "SSL_CERT_FILE": str(d / "ca-bundle.pem")}


def _python(d: Path) -> Path:
    """The service's own Python (3.11 or later, capsule-anchor's pyproject), with capsule-anchor at :data:`ANCHOR_REF`;
    made once per folder."""
    if given := os.environ.get("ARD_COUNTERSIGN_PYTHON"):  # one with capsule-anchor at ANCHOR_REF already (check.sh)
        return Path(given)
    py = d / "venv" / "bin" / "python"
    marker = d / "venv" / ".capsule-anchor-ref"
    if py.exists() and marker.exists() and marker.read_text().strip() == ANCHOR_REF:
        return py
    base = _python_311()
    subprocess.run([base, "-m", "venv", "--clear", str(d / "venv")], check=True, capture_output=True)
    done = subprocess.run([str(py), "-m", "pip", "install", "--quiet", "--disable-pip-version-check", ANCHOR_PIP],
                          capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if done.returncode != 0:
        raise CountersignerError(f"could not install capsule-anchor {ANCHOR_REF[:7]}: {done.stderr.strip()[-400:]}")
    marker.write_text(ANCHOR_REF)
    return py


def _python_311() -> str:
    """A Python 3.11 or later to make the service's environment from: this one, else one on the PATH (the demo itself
    runs on 3.10)."""
    if sys.version_info >= (3, 11):
        return sys.executable
    for name in ("python3.14", "python3.13", "python3.12", "python3.11"):
        if found := shutil.which(name):
            return found
    raise CountersignerError(f"capsule-anchor needs Python 3.11 or later; this is {sys.version.split()[0]} and none is "
                             "on the PATH (brew install python)")


def _keys(d: Path) -> tuple[str, str]:
    """The service's Ed25519 seed and public key, made once per folder (so its countersignatures keep resolving)."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    seed_file = d / "signing.seed"
    if not seed_file.exists():
        fd = os.open(seed_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(os.urandom(32).hex())
    seed = seed_file.read_text().strip()
    public = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(seed)).public_key().public_bytes_raw().hex()
    return seed, public


def _certificate(d: Path) -> None:
    """A self-signed certificate for localhost (Go reads the name from the SAN), made once per folder."""
    if (d / "tls.crt").exists() and (d / "tls.key").exists():
        return
    done = subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
                           "-nodes", "-days", "365", "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost",
                           "-keyout", str(d / "tls.key"), "-out", str(d / "tls.crt")], capture_output=True, text=True)
    if done.returncode != 0:
        raise CountersignerError(f"could not make the countersigner's certificate: {done.stderr.strip()}")
    os.chmod(d / "tls.key", 0o600)


def _ca_bundle(d: Path, ca_bundle: str | Path | None) -> None:
    """The roots a party's capsulectl trusts while it asks: the caller's bundle (the local witness's, say), else this
    process's ``SSL_CERT_FILE``, else the system roots, plus this countersigner's certificate."""
    base = ca_bundle or os.environ.get("SSL_CERT_FILE") or "/etc/ssl/cert.pem"
    roots = Path(base).read_text() if Path(base).is_file() else ""
    (d / "ca-bundle.pem").write_text(roots.rstrip("\n") + "\n" + (d / "tls.crt").read_text())


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get(url: str, cafile: Path) -> dict:
    with urllib.request.urlopen(url, context=ssl.create_default_context(cafile=str(cafile)), timeout=5) as r:
        return json.load(r)


def _kill(d: Path, pid: int, wait_s: float = 5.0) -> None:
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if not is_ours(d, pid):
            return
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            return
        stop = time.monotonic() + wait_s
        while time.monotonic() < stop and is_ours(d, pid):
            time.sleep(0.2)


def start(d: str | Path, parties, ca_bundle: str | Path | None = None, say=lambda *_: None) -> dict[str, str]:
    """Start the countersigner of folder ``d`` admitting ``parties`` (each a :class:`party.Party` already made), name
    the demo's directory in each party's profile, and return :func:`env`. A countersigner already running is restarted
    when the parties it admits changed, else kept."""
    d = Path(d).expanduser()
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    d = d.resolve()
    allow = issuers(parties)
    st = running(d)
    if st is not None and st.get("issuers") == allow:
        _name_directory(d, parties)
        return env(d)
    stop(d)
    say("installing capsule-anchor (once per demo home)")
    py = _python(d)
    seed, key = _keys(d)
    _certificate(d)
    _ca_bundle(d, ca_bundle)
    (d / "issuers.json").write_text(json.dumps(allow))
    (d / "directory.json").write_text(json.dumps(directory(key)))
    port = _free_port()
    url = f"https://localhost:{port}"
    # Only what capsule-anchor needs: an inherited CAPSULE_ANCHOR_* (a database URL, a public log) never reaches it.
    service_env = {"PATH": "/usr/bin:/bin", "HOME": str(d), "CAPSULE_ANCHOR_SIGNING_KEY": seed,
                   "CAPSULE_ANCHOR_PUBLIC_HOST": "localhost", "CAPSULE_ANCHOR_INSECURE_IN_MEMORY": "1",
                   "CAPSULE_ANCHOR_REGISTRATION_POLICY": "strict", "CAPSULE_ANCHOR_COUNTERSIGN": "1",
                   "CAPSULE_ANCHOR_COUNTERSIGN_ISSUERS_FILE": str(d / "issuers.json")}
    with open(d / "countersigner.log", "ab") as log:
        proc = subprocess.Popen([str(py), "-m", "uvicorn", "--factory", APP, "--host", "127.0.0.1", "--port", str(port),
                                 "--ssl-keyfile", str(d / "tls.key"), "--ssl-certfile", str(d / "tls.crt")],
                                env=service_env, cwd=d, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                start_new_session=True)
    try:
        _wait_healthy(d, proc, url, key)
    except BaseException:
        proc.kill()
        proc.wait()
        raise
    (d / STATE).write_text(json.dumps({"pid": proc.pid, "url": url, "key": key, "issuers": allow}))
    _name_directory(d, parties)
    return env(d)


def _wait_healthy(d: Path, proc: subprocess.Popen, url: str, key: str) -> None:
    stop_at = time.monotonic() + HEALTH_WAIT_S
    while True:
        if proc.poll() is not None:
            raise CountersignerError(f"the countersigner exited before it answered (its log: {d / 'countersigner.log'})")
        try:
            _get(f"{url}/health", d / "tls.crt")
            break
        except OSError:
            if time.monotonic() > stop_at:
                raise CountersignerError(f"the countersigner did not answer in {HEALTH_WAIT_S} s "
                                         f"(its log: {d / 'countersigner.log'})") from None
            time.sleep(0.5)
    # The key it signs with is the one the directory names (a mismatch would make every countersignature unresolved).
    x = _get(f"{url}/.well-known/did.json", d / "tls.crt")["verificationMethod"][0]["publicKeyJwk"]["x"]
    got = base64.urlsafe_b64decode(x + "=" * (-len(x) % 4)).hex()
    if got != key:
        raise CountersignerError(f"the countersigner signs under {got}, not the key its directory names ({key})")


def _name_directory(d: Path, parties) -> None:
    """Name the demo's countersigner directory in each party's profile (``capsulectl profile update
    --countersign-directory``): a party's report then counts this countersigner, and only it."""
    for p in parties:
        p.core("profile", "update", "--profile", p.profile, "--countersign-directory", str(d / "directory.json"))


def stop(d: str | Path) -> bool:
    """Stop the countersigner of folder ``d``; True when one was running. Safe to call when none is."""
    d = Path(d).expanduser()
    st = _state(d)
    if st is None:
        return False
    was = is_ours(d, int(st["pid"]))
    if was:
        _kill(d, int(st["pid"]))
    (d / STATE).unlink(missing_ok=True)
    return was


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="countersigner.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["up", "down"])
    ap.add_argument("--home", default=os.environ.get("ARD_HOME", "~/.config/ard-commerce-demo"))
    args = ap.parse_args(argv)
    home = Path(args.home).expanduser()
    d = default_dir(home)
    if args.command == "down":
        print("stopped the demo's countersigner" if stop(d) else "the demo's countersigner was not running")
        return 0
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _paths

    try:
        _paths.setup()
    except _paths.SetupError as exc:
        sys.exit(str(exc))
    import party as pt
    from cast import ADJUDICATOR, BUYER, SELLERS

    parties = [pt.Party(home, n) for n in (BUYER, *SELLERS, ADJUDICATOR)]
    missing = [p.name for p in parties if not p.exists]
    if missing:
        sys.exit(f"no party yet for {', '.join(missing)}: run `demo.py seed` first")
    try:
        got = start(d, parties, say=print)
    except CountersignerError as exc:
        sys.exit(str(exc))
    print(f"the demo's countersigner listens on {got['ARD_COUNTERSIGN_URL']}, admitting "
          f"{', '.join(p.name for p in parties)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
