# SPDX-License-Identifier: Apache-2.0
"""The demo's adjudicator: ledger-cloud's adjudicator service (``ledger_cloud/adjudicator``), run on this Mac with a
directory store, as Steven runs it now (ops u211 item 5, "Option A"). It holds no deal rule of its own: its front
takes cases and books (``POST /v1/cases``, ``POST /v1/cases/{case}/books``) and serves rulings to the parties they
name (``GET /v1/cases/{case}/rulings/{digest}``, signed by the party's record key); its operator, the one process that
holds the key, rules (``rule``), registers its stamp with the witness (``witness``) and checks each party's entry of a
ruling (``entry``). Every rule it applies is evidencebook's (``xdealv1.CheckCase``, ``SealRuling``, ``EntryOf``).

This module starts the front (the stage does, :mod:`stage`), wraps the operator and the client as the demo's parties
and the Adjudicator window use them, and serves the rules page the agreements name. The binaries are ledger-cloud's,
built at the commit the run sheet pins, in ``ARD_ADJUDICATOR_BIN``."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import party as pt

PORT = int(os.environ.get("ARD_STAGE_PORT", "47481")) + 2  # the stage's port + 2: 47483 by default
URL = f"http://127.0.0.1:{PORT}"
PRINCIPAL = "demo-operator"
#: The challenge window: 7 days (Steven, ops u214, 2026-11-24: "was 30; agents act fast"). The rules page and the
#: ruling dialog say it; the operator keeps a ruled case's copies this long.
CHALLENGE_WINDOW = "168h"
#: The conflict determination every ruling records (ops u120: whether Action State is, or acts for, a party). In this
#: demo the operator runs every party, so it is not independent of them; the dialog shows these words.
CONFLICT = "the operator runs this adjudicator and every party here, so it is not independent of the parties"
#: The rules the agreements name: what the demo adjudicator rules on. The page is served by the stage; its SHA-256 is
#: the agreement's ``rules_digest``.
RULES_TEXT = """Adjudicator: rules

The operator runs this adjudicator and every party here, so it is not independent of the parties.

1. It rules on one row of an x-deal-v1 deal whose agreement names it, when a party disputes that row.
2. It reads the books the parties send it, and rules against a side only on records that side signed itself. A side
   whose book was not shown is not ruled against.
3. Its ruling says whether the row was met. It is final for the row; either side may challenge it within 7 days,
   and a challenge is recorded beside the ruling and never replaces it.
4. It orders no payment and moves no money.
"""


class AdjudicatorError(RuntimeError):
    pass


def rules_digest() -> str:
    return hashlib.sha256(RULES_TEXT.encode()).hexdigest()


def rules_url() -> str:
    return f"http://127.0.0.1:{int(os.environ.get('ARD_STAGE_PORT', '47481'))}/adjudicator/rules"


def binary(name: str) -> str:
    d = os.environ.get("ARD_ADJUDICATOR_BIN", "")
    path = Path(d) / name
    if not d or not os.access(path, os.X_OK):
        raise AdjudicatorError(f"set ARD_ADJUDICATOR_BIN to the folder holding ledger-cloud's {name} (the run sheet "
                               "builds it)")
    return str(path)


@dataclass(frozen=True)
class Adjudicator:
    """The adjudicator's state under the demo home: ``<home>/adjudicator`` (its key, the operator's shelf, the
    intake, read and export folders, the witness directory)."""

    home: Path

    @property
    def dir(self) -> Path:
        return Path(self.home).expanduser() / "adjudicator"

    @property
    def key_file(self) -> Path:
        return self.dir / "adjudicator.key"

    def create(self) -> Adjudicator:
        """Make the key once (``capsulectl key generate``), and the witness directory the operator pins."""
        self.dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not self.key_file.exists():
            run = subprocess.run([os.environ.get("CAPSULECTL_DEAL", "capsulectl-deal"), "key", "generate", "--output",
                                  str(self.key_file)], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
            if run.returncode != 0:
                raise AdjudicatorError(f"capsulectl key generate failed: {run.stderr.strip()}")
        (self.dir / "witnesses.json").write_text(json.dumps(pt.witness_directory()))
        return self

    @property
    def key_id(self) -> str:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        seed = bytes.fromhex(self.key_file.read_text().strip())
        return Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes_raw().hex()

    def named(self) -> dict:
        """How an agreement names this adjudicator: its key and its published rules."""
        return {"key_id": self.key_id, "rules_digest": rules_digest(), "rules_url": rules_url()}

    # -- the front ------------------------------------------------------------------------------

    def start_front(self) -> subprocess.Popen:
        """Start ``adjudicator-front`` on localhost for the stage (it holds no key)."""
        log = open(self.dir / "front.log", "a")
        return subprocess.Popen([binary("adjudicator-front"), "-addr", f"127.0.0.1:{PORT}", "-adjudicator-key", self.key_id,
                                 "-rules-digests", rules_digest(), "-intake", str(self.dir / "intake"),
                                 "-read", str(self.dir / "read"), "-xff-hop", "0"],
                                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)

    # -- the operator (the Adjudicator window's process only) ----------------------------------

    def operator(self, *args: str) -> dict:
        env_args = [binary("adjudicator-operator"), "-dir", str(self.dir / "op"), "-key-file", str(self.key_file),
                    "-witness-directory", str(self.dir / "witnesses.json"), "-intake", str(self.dir / "intake"),
                    "-read", str(self.dir / "read"), "-export", str(self.dir / "export"), "-principal", PRINCIPAL,
                    "-challenge-window", CHALLENGE_WINDOW]
        if pt.witnessed():
            env_args += ["-witness-ids", pt.WITNESS_URL, "-witness-urls", pt.WITNESS_URL]
        run = subprocess.run([*env_args, *args], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120)
        if run.returncode != 0:
            raise AdjudicatorError(f"adjudicator-operator {args[0]}: {(run.stderr or run.stdout).strip()}")
        out = run.stdout.strip()
        try:
            return json.loads(out) if out else {}
        except ValueError:
            return {"raw": out}

    def cases(self) -> list[dict]:
        """The cases the front took, read from its intake folder (ledger-cloud ``layout``: ``cases/case/<id>/`` with
        ``disputes``, ``copies``, ``books`` and ``descriptors``, each object stored once as ``{received_at, body}``):
        each case's deal, row, the parties' keys, its dispute, the copies sent and when each arrived."""
        out = []
        root = self.dir / "intake" / "cases" / "case"
        for case in sorted(p for p in root.glob("*") if p.is_dir()) if root.is_dir() else []:
            def objs(kind: str) -> list[dict]:
                d = case / kind
                found = []
                for f in sorted(d.glob("*")) if d.is_dir() else []:
                    try:
                        env = json.loads(f.read_bytes())
                    except ValueError:
                        env = {}
                    found.append({"digest": f.name, "received_at": env.get("received_at", ""), "body": env.get("body")})
                return found
            desc = next(iter(sorted((case / "descriptors").glob("*"))), None) if (case / "descriptors").is_dir() else None
            deal_id, row, buyer, seller = (desc.name.split("~") + ["", "", "", ""])[:4] if desc else ("", "", "", "")
            out.append({"case": case.name, "deal_id": deal_id, "row": bytes.fromhex(row).decode() if row else "",
                        "buyer": buyer, "seller": seller, "disputes": objs("disputes"), "copies": objs("copies"),
                        "books": objs("books")})
        return out

    def rule(self, case: str, dispute: str, copies: list[str], row: str, value: str, against: str) -> dict:
        args = ["rule", "-case", case, "-dispute", dispute]
        for c in copies:
            args += ["-copy", c]
        return self.operator(*args, "-row", row, "-value", value, "-against", against, "-final", "-conflict", CONFLICT)

    def witness(self, seconds: float = 60) -> int:
        """Register the stamps the operator holds with the witness, retrying for up to ``seconds``; how many it
        delivered (0 when the witness took none in that time)."""
        stop = time.time() + seconds
        while True:
            n = int(self.operator("witness").get("delivered", 0) or 0)
            if n or time.time() >= stop:
                return n
            time.sleep(5)

    def rulings(self, case: str) -> list[dict]:
        """The case's published rulings, as the operator wrote them for the parties to fetch: each one's digest and
        what it found (its value and against whom), read from the ruling record's payload."""
        out = []
        d = self.dir / "read" / "rulings" / "case" / case
        for f in sorted(d.glob("*.json")) if d.is_dir() else []:
            found = _walk_ruling(json.loads(f.read_bytes()))
            out.append({"digest": f.stem, **found})
        return out

    def entry(self, case: str, ruling: str) -> list[dict]:
        out = self.operator("entry", "-case", case, "-ruling", ruling)
        return out if isinstance(out, list) else out.get("answers", [])


# -- what a party does with the adjudicator ---------------------------------------------------------

def _post(path: str, body: dict) -> dict:
    req = urllib.request.Request(URL + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:  # the demo's own localhost adjudicator
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        raise AdjudicatorError(f"the adjudicator refused it ({exc.code}): {exc.read().decode(errors='replace')[:300]}") from None
    except OSError as exc:
        raise AdjudicatorError(f"the adjudicator is not reachable at {URL}: {exc}") from None


def open_case(dispute_file: Path, copy: Path) -> dict:
    """Send the dispute with this party's adjudicator copy (``POST /v1/cases``). The other side sends the same dispute
    with its own copy; the front keeps each object once, so both land in one case."""
    return _post("/v1/cases", {"dispute": json.loads(Path(dispute_file).read_text()), "copies": [json.loads(copy.read_text())]})


def send_book(case: str, copy: Path, proof: dict) -> dict:
    """Send this party's book after it entered a ruling, with its stamp proof and witness receipts, for the entry check."""
    return _post(f"/v1/cases/{case}/books", {"bundle": json.loads(copy.read_text()), "stamp_proof": proof["stamp_proof"],
                                             "witness_receipts": proof.get("witness_receipts") or []})


def fetch_ruling(p: pt.Party, case: str, ruling: str) -> Path:
    """Fetch a ruling with the party's record key (``adjudicator-client``)."""
    out = p.tmp("ruling.json")
    run = subprocess.run([binary("adjudicator-client"), "-url", URL, "-case", case, "-ruling", ruling, "-key-file",
                          str(p.seed_file), "-out", out], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
    if run.returncode != 0:
        raise AdjudicatorError(f"could not fetch the ruling: {(run.stderr or run.stdout).strip()}")
    return Path(out)


def list_rulings(p: pt.Party, case: str) -> dict:
    """The case's rulings and refusals, as the party may read them (``adjudicator-client`` with no ``-ruling``)."""
    out = str(p.dir / "tmp" / "rulings-list.json")  # one file, rewritten each read
    Path(out).parent.mkdir(exist_ok=True, mode=0o700)
    run = subprocess.run([binary("adjudicator-client"), "-url", URL, "-case", case, "-key-file", str(p.seed_file), "-out", out],
                         capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
    if run.returncode != 0:
        return {"rulings": [], "refusals": []}
    return json.loads(Path(out).read_text())


def _walk_ruling(doc) -> dict:
    """The ruling body's ``value`` and ``against``, wherever the published file carries them (encoded payloads too)."""
    import base64
    if isinstance(doc, dict):
        if "against" in doc and "value" in doc:
            return {"value": doc["value"], "against": doc["against"]}
        for v in doc.values():
            got = _walk_ruling(v)
            if got:
                return got
    elif isinstance(doc, list):
        for v in doc:
            got = _walk_ruling(v)
            if got:
                return got
    elif isinstance(doc, str) and len(doc) > 40:
        try:
            return _walk_ruling(json.loads(base64.b64decode(doc + "==")))
        except Exception:
            return {}
    return {}


def wait_front(seconds: float = 10) -> bool:
    stop = time.time() + seconds
    while time.time() < stop:
        try:
            with urllib.request.urlopen(URL + "/status.json", timeout=1):
                return True
        except Exception:
            time.sleep(0.2)
    return False
