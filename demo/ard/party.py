# SPDX-License-Identifier: Apache-2.0
"""One party of the demo on its own capsulectl-deal profile: Maya, Alder, Kestrel or the sample buyer.

Every operation is one verb of the ``capsulectl-deal`` plugin, run through the Goose reference's ``Ctl``
(evidencebook ``python/examples/goose/ctl.py``, at the commit the run sheet pins), with the party's directory as
the profile's ``HOME``. The node book (what the party did outside a deal: its assessments, its pick, the cards it
read) is the Goose reference's ``goose/node`` book through its :class:`goose_node.Node`. Nothing here keeps a deal
record of its own or computes a row's status: capsulectl seals, keeps and counts.

The demo's deals are x-deal-v1 deals that name the demo's adjudicator and Action State's hosted witness in the
agreement both sides sign (:func:`offer_members`). #833's own ``Node.open_deal`` names neither, so the offer is
written here and every other step uses the same verbs the Goose reference does."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import _paths

_paths.setup()

import feeds  # noqa: E402
import goose_node as gn  # noqa: E402
import ctl as ctl_mod  # noqa: E402
from ctl import Ctl, Refused  # noqa: E402

# The Goose reference's Ctl and engine read their binaries from these; the demo's own variables name them.
os.environ.setdefault("GOOSE_CAPSULECTL_DEAL", os.environ.get("CAPSULECTL_DEAL", "capsulectl-deal"))
os.environ.setdefault("GOOSE_CAPSULE_ENGINE", os.environ.get("CAPSULE_ENGINE", "capsule-engine"))

__all__ = ["Party", "Refused", "WitnessSlow", "HOSTED_WITNESS_KEY", "HOSTED_WITNESS_URL", "WITNESS_KEY", "WITNESS_URL",
           "WITNESS_NAME", "witnessed"]

#: Action State's hosted witness, ``deal init``'s default (capsulectl ``DealDefaultWitness``, ``DealDefaultWitnessKey``,
#: evidencebook ``capsulectl/internal/deal/deal_verify_names.go``). Run by Action State, so not independent of the demo's
#: parties, all of which the demo operator runs. It receives checkpoint hashes only.
HOSTED_WITNESS_URL = "https://witness.agentactioncapsule.org"
HOSTED_WITNESS_KEY = "39bb654c9dc0afe1c0edef0deffaa69099b8518836c9ba26e0491535840f96b5"


def _witness() -> tuple[str, str, str]:
    """The witness this run names: the hosted one, or with ``ARD_WITNESS=local`` the one ``ARD_WITNESS_URL`` and
    ``ARD_WITNESS_KEY`` give (a capsule-anchor witness the testbed starts on this Mac, ``testbed.py``). Also run by
    Action State, so no more independent of the parties than the hosted one."""
    if os.environ.get("ARD_WITNESS") != "local":
        return HOSTED_WITNESS_URL, HOSTED_WITNESS_KEY, "Action State's witness"
    url, key = os.environ.get("ARD_WITNESS_URL", ""), os.environ.get("ARD_WITNESS_KEY", "")
    if not (url and key):
        raise SystemExit("ARD_WITNESS=local needs both ARD_WITNESS_URL and ARD_WITNESS_KEY (testbed.py sets them)")
    return url, key, "Action State's test witness"


WITNESS_URL, WITNESS_KEY, WITNESS_NAME = _witness()
#: The demo's cadence: one checkpoint a minute (capsulectl's shortest, ``cadence.go``), no jitter. A step that needs its
#: records stamped does not wait for it: it stamps on demand (:meth:`Party.stamp`).
CADENCE = "cadence:\n  interval: 1m\n  jitter: 0s\n"
#: The History card's derivation every party makes and every buyer accepts: the one constant a move to
#: ``standard_history/4`` changes (AAC standard-history §12: /3 with one rule changed).
#: How long one stamp takes the hosted witness to take, at most, when it is well (measured 3 to 6 s): a stamp is tried
#: again only with this long left of its wait.
STAMP_TRY_S = 6
CARD_DERIVATION = "standard_history/3"
#: The one forum the demo's agreements accept: the demo adjudicator, an outside party to the deal.
FORUM = "external:ard-demo"
#: The two rows of every demo deal (the Goose reference's own, ``goose_node.ROW`` and ``DELIVERED``).
PAID, DELIVERED = gn.ROW, gn.DELIVERED
CURRENCY = "BTC"  # capsulectl reads a BTC amount_minor in msat (deal_rules.go msatCurrency)


class WitnessSlow(Refused):
    """The witness took no stamp of this party's within a wait. Its words are a person's (evidencebook-skills#327): the
    last tick's output goes to the party's own log (:meth:`Party.log`), never into a chat."""


#: The card bundle's extension that carries its witness's receipt for its anchor (evidencebook#957).
CARD_ANCHOR_WITNESS = "x-standard-history-anchor-witness/v0"
#: Said when the card's time-stamp receipt does not check out under the witness's key.
STAMP_FAILED = "its time-stamp receipt does not check out"


def not_verified(subject: str, verdict: str) -> str:
    """Said when ``subject`` (``Your History card``, ``Alder Print Co.'s card``) fails verify on a verdict other than
    its time-stamp receipt (Sherlock2 on #350). INCOMPLETE is not a failed signature: capsulectl also reads it when a
    member is a refusal (capsule-cli ``composed.go``)."""
    if verdict == "INCOMPLETE":
        return (f"{subject} could not be fully checked: capsulectl deal verify reported it INCOMPLETE, because part of "
                "what it covers is withheld or missing from the file.")
    return f"{subject} does not verify: capsulectl deal verify reported it {verdict}."


def anchor_witness(out: dict) -> str:
    """The status of a History card's time-stamp, as ``verify --bundle`` reports it (evidencebook#957):
    ``reader_witnesses`` checks the witness's receipt for the card's anchor (pass; withheld when it could not be checked
    under the directory given; fail), and is absent when the card carries no receipt (""). The core ``witnesses`` row
    beside it is about the card bundle's own log, which no witness sees, so it is never read for a card."""
    return (out.get("reader_witnesses") or {}).get("status", "")


def witnessed() -> bool:
    """True unless ``ARD_WITNESS=off``: a Mac with no network can still run, its records then timed locally only."""
    return os.environ.get("ARD_WITNESS", "public") != "off"


class StampWait:
    """The stamps one wait cut, and whether the witness took any of them. A checkpoint covers every record before it,
    so any checkpoint cut during the wait that the witness took times every record sealed before the wait began; an
    older or a newer one left pending (the witness answered it with an error) does not undo that."""

    def __init__(self) -> None:
        self.first: int | None = None  # the first checkpoint this wait cut
        self.taken = False

    def add(self, tick: dict) -> bool:
        if not witnessed() or tick.get("witness") == "not_configured":
            self.taken = self.taken or tick.get("state") == "ticked"
            return self.taken
        if tick.get("state") == "ticked" and self.first is None:
            self.first = tick.get("checkpoint")
        if self.first is not None and any(d >= self.first for d in (tick.get("delivered") or [])):
            self.taken = True
        return self.taken


def witness_directory() -> dict:
    """The witness directory ``verify --bundle --witness-directory`` and the adjudicator take: the one hosted witness."""
    return {"witnesses": [{"name": WITNESS_NAME, "endpoint": WITNESS_URL, "key_ids": [WITNESS_KEY]}]}


def _iso(at: datetime) -> str:
    return at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Party:
    """A party's directory under the demo home (its profile's ``HOME``)."""

    def __init__(self, home: Path, name: str) -> None:
        self.name = name
        self.dir = Path(home).expanduser() / name
        self.profile = f"ard-{name}"
        self.dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.ctl = Ctl(self.dir, self.profile)
        self.node = gn.Node(self.dir, self.profile, "ard-demo@v2", self.ctl)
        self._lock = threading.RLock()

    # -- set-up -----------------------------------------------------------------------------

    @property
    def exists(self) -> bool:
        return (self.dir / "deal" / "signing.seed").is_file()

    def create(self, holder_kind: str, key_file: str = "", neutral: bool = False, witness: bool = True) -> Party:
        """Make the profile once: keys, the store, the hosted witness unless ``ARD_WITNESS=off``, a one-minute cadence,
        and who holds the card (``person`` for a buyer, ``node`` for a shop). ``neutral`` pins capsulectl's
        ``builtin:neutral`` materiality predicate, so a check pauses only on what the predicate finds material, not on
        every attribute the agent picked: a seller's process delivers without a person at the keyboard."""
        if self.exists:
            return self
        self.dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        args = ["init", "--dir", str(self.dir / "deal")]
        # ``deal init`` can name only the hosted witness (capsulectl ``DealDefaultWitness``): any other is named after it
        other = witnessed() and witness and WITNESS_URL != HOSTED_WITNESS_URL
        if not witnessed() or not witness or other:
            args.append("--no-witness")
        if key_file:
            args += ["--signing-key-file", key_file, "--checkpoint-key-file", key_file]
        if neutral:
            args += ["--materiality", "builtin:neutral"]
        self.run(*args)
        prof = self.dir / ".config" / "capsule" / "profiles" / f"{self.profile}.yaml"
        with open(prof, "a") as fh:
            fh.write(CADENCE)
        self.run("standard-history", "declare", "--holder-kind", holder_kind)
        if other:
            self.add_witness()
        return self

    def add_witness(self) -> None:
        """Name the run's witness (:data:`WITNESS_URL`) in a profile made without one (``create(witness=False)``, or
        :meth:`create` for a witness other than the hosted one): its next stamp, which covers
        every record before it, is the first the witness sees. Unless ``ARD_WITNESS=off``."""
        if not witnessed():
            return
        prof = self.dir / ".config" / "capsule" / "profiles" / f"{self.profile}.yaml"
        text = prof.read_text()
        if "endpoint: " + WITNESS_URL in text:
            return
        if "\ncheckpoint:\n" not in text:
            raise Refused(f"{self.name}: its profile has no checkpoint section to name the witness in")
        # The same two lines ``deal init`` writes when it names the witness (endpoint and the witness's key).
        prof.write_text(text.replace("\ncheckpoint:\n",
                                     f"\ncheckpoint:\n    endpoint: {WITNESS_URL}\n    public_key: {WITNESS_KEY}\n", 1))

    def log(self, line: str) -> None:
        """Append a line to this party's own log (``<party>/agent.log``): what a chat line leaves out, such as a verb's
        raw output, for whoever looks into a failure (evidencebook-skills#327). Never raises."""
        if getattr(self, "dir", None) is None:  # a Party made without __init__ (tests) has no folder
            return
        try:
            with open(self.dir / "agent.log", "a") as fh:
                fh.write(f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}  {line}\n")
        except OSError:
            pass

    def run(self, *args: str) -> Any:
        with self._lock:
            return self.ctl.run(*args)

    def close(self) -> None:
        self.node.close()

    @property
    def key_id(self) -> str:
        return self.node.key_id

    @property
    def checkpoint_key_id(self) -> str:
        return self.node.checkpoint_key_id

    @property
    def seed_file(self) -> Path:
        """The record key's seed file (64 hex)."""
        return self.dir / "deal" / "signing.seed"

    def tmp(self, name: str) -> str:
        """A new path under the party's own scratch folder for a file a verb writes."""
        d = self.dir / "tmp"
        d.mkdir(exist_ok=True, mode=0o700)
        return str(d / f"{uuid.uuid4().hex[:12]}-{name}")

    def write(self, name: str, content: Any) -> str:
        path = self.tmp(name)
        Path(path).write_text(content if isinstance(content, str) else json.dumps(content))
        return path

    # -- the node book ------------------------------------------------------------------------

    def note(self, record_type: str, statement: dict, **kw: Any) -> dict:
        with self._lock:
            return self.node.note(record_type, statement, **kw)

    def notes(self, record_type: str = "") -> list[dict]:
        with self._lock:
            return self.node.notes(record_type)

    # -- the cadence and the card -------------------------------------------------------------

    def tick(self) -> dict:
        """The cadence's poll: a checkpoint when one is due (a minute after the last), else nothing new."""
        return self._fed(self.run("tick"))

    def stamp(self) -> dict:
        """A checkpoint now, whatever the cadence (``deal tick --now``, evidencebook's on-demand stamp, as ``deal agree``
        takes): for a step that needs its records stamped, so no one waits for the cadence. The witness then sees a stamp
        off the cadence; the demo's parties accept that."""
        return self._fed(self.run("tick", "--now"))

    def _fed(self, tick: dict) -> dict:
        """A tick, also written to the witness's screen (:func:`feeds.stamp`)."""
        feeds.stamp(self.dir.parent, self.name, WITNESS_NAME, tick)
        return tick

    def wait_checkpoint(self, seconds: float = 30, say=None) -> dict:
        """Take a checkpoint now (:meth:`stamp`) that the witness takes (:class:`StampWait`: any checkpoint this wait
        cut), taken again while it does not
        (it answers slowly or with an error under load). A new try starts only with :data:`STAMP_TRY_S` left of
        ``seconds``, so the whole wait stays near ``seconds``; a try already under way is not cut off (capsulectl is
        then mid-delivery), and what it did not deliver goes with the next tick."""
        stop, wait, failed = time.monotonic() + seconds, StampWait(), None
        while True:
            try:
                t, failed = self.stamp(), None
            except Refused as exc:
                t, failed = {"error": str(exc)}, exc
            if wait.add(t):
                return t
            time.sleep(1)
            if stop - time.monotonic() < STAMP_TRY_S:
                self.log(f"no stamp taken in {int(seconds)} s; last tick: {json.dumps(t)}")
                if failed is not None and wait.first is None:  # no checkpoint was cut: this party's own failure
                    raise failed
                raise WitnessSlow(f"{WITNESS_NAME} took no stamp within {int(seconds)} s")
            if say:
                say("this party's checkpoint did not go through; trying again")
                say = None

    def card_bundle(self, shared: bool) -> Path:
        """The party's :data:`CARD_DERIVATION` card as a bundle, as of its newest checkpoint: the shared copy (the card,
        its policy and its anchor) or its own copy (with the deal entries it counts)."""
        out = self.tmp("card-shared.json" if shared else "card.json")
        self.run("standard-history", "card", "--derivation", CARD_DERIVATION, "--out", out,
                 *(["--shared"] if shared else []))
        return Path(out)

    # -- deals --------------------------------------------------------------------------------

    def offer(self, to_key: str, item: str, price_msat: int, pack_digest: str, adjudicator: dict,
              due_s: int = 86400, window_s: int = 7 * 86400) -> dict:
        """As the buyer: the offer to ``to_key``, naming the adjudicator, the forum and (unless ``ARD_WITNESS=off``) the
        hosted witness, written to a file for the seller to keep with ``deal receive``. The two rows are the Goose
        reference's: the buyer owes the price, the seller owes delivery, both due ``due_s`` after now, contested up to
        ``window_s`` after now."""
        now = datetime.now(timezone.utc)
        due, end = _iso(now + timedelta(seconds=due_s)), _iso(now + timedelta(seconds=window_s))
        members = {
            "role": "buyer", "to": to_key, "terms": {"item": item, "price_minor": price_msat, "currency": CURRENCY},
            "pack_digest": pack_digest,
            "agree_by": _iso(now + timedelta(days=2)),
            "terms_rows": {"rows": [
                {"id": PAID, "owed_by": "buyer", "owed": {"amount_minor": price_msat, "currency": CURRENCY},
                 "due": {"at": due}, "window_end": {"at": end}},
                {"id": DELIVERED, "owed_by": "seller", "owed": {}, "due": {"at": due}, "window_end": {"at": end}}],
                "named": {}},
            "adjudicator": adjudicator, "forums": [FORUM],
            "witnesses": [{"key_id": WITNESS_KEY, "url": WITNESS_URL}] if witnessed() else [],
        }
        out = self.tmp("offer.json")
        done = self.run("offer", "--input", self.write("offer-in.json", members), "--out", out)
        return {"deal_id": done["deal_id"], "offer": done["offer"], "file": out}

    def receive(self, file: str | Path, out: str = "") -> dict:
        return self.run("receive", str(file), *(["--out", out] if out else []))

    def admit(self, deal_id: str, decision: dict) -> str:
        """Seal capsule-engine's admitting decision for the deal (``deal admit``); a retry finds it."""
        try:
            return self.run("admit", "--deal", deal_id, "--input", self.write("admit.json", decision))["admit"]
        except Refused as exc:
            if "already" not in str(exc):
                raise
            return ""

    def intent(self, deal_id: str, words: str, kind: str, allowed: list[str], limit_msat: int | None,
               who: str, refundable: bool = False, rail: str = "lightning", domain: str = "") -> str:
        """Seal what the person asked for this deal (``deal note --kind intent``)."""
        said: dict = {"verbatim": words, "allowed": allowed}
        if limit_msat is not None:
            said["max_total_minor"] = limit_msat
        opening = {"type": kind, "who": {"name": who, "domain": domain or f"{who[:12]}.invalid"},
                   "recourse": {"rail": rail, "refundable": refundable}}
        try:
            return self.run("note", "--deal", deal_id, "--kind", "intent", "--input", self.write("intent.json", said),
                            "--opening", self.write("opening.json", opening))["intent"]
        except Refused as exc:
            if "already open" not in str(exc):
                raise
            return ""

    def agree(self, offer_digest: str, intent: str = "") -> dict:
        out = self.tmp("agree.json")
        done = self.run("agree", offer_digest, *(["--intent", intent] if intent else []), "--out", out)
        return {**done, "file": out}

    def check(self, deal_id: str, action: str, item: str, price_msat: int, who: str, extra: dict | None = None,
              rail: str = "lightning", domain: str = "") -> dict:
        """The final review of an act (``deal check``): ``proceed``, or a pause with the card the person must see."""
        body = {"action": action, "terms": {"item": item, "price_minor": price_msat, "currency": CURRENCY},
                "who": {"name": who, "domain": domain or f"{who[:12]}.invalid"}, "recourse": {"rail": rail, "refundable": False},
                **(extra or {})}
        return self.run("check", "--deal", deal_id, "--input", self.write("check.json", body))

    def approve(self, deal_id: str, check: dict, choice: str, said: str) -> dict:
        """The person's answer to a check that paused, sealed with the card they were shown."""
        return self.run("note", "--deal", deal_id, "--kind", "approval", "--check", check["check_id"], "--choice", choice,
                        "--said", said, "--shown-card", self.write("card.txt", check["card"]))

    def sending(self, deal_id: str, check_id: str) -> None:
        """Count the buyer's payment as in flight (``deal settle --sent``) before any money moves: capsulectl checks it
        against the rules again here (a payment since the check may have used up the limit), and a refusal sends
        nothing. Running it again for a payment already counted is not a refusal."""
        try:
            self.run("settle", "--deal", deal_id, "--sent", "--check", check_id, "--payment-ref-type", "ln.payment_hash")
        except Refused as exc:
            if not any(w in str(exc) for w in ("in flight", "is used")):
                raise

    def payment_failed(self, deal_id: str, check_id: str) -> None:
        """Close a payment counted as sent that the rail says failed (``deal settle --status failed``): no spend is
        counted for it, and the approval it used stays used."""
        self.run("settle", "--deal", deal_id, "--check", check_id, "--status", "failed", "--out", self.tmp("failed-leg.json"))

    def pay_leg(self, deal_id: str, check_id: str) -> str:
        """The buyer's payment: counted as in flight (:meth:`sending`, a no-op once done), then the payer leg settled,
        written for the seller. The payment reference is the one the check bound."""
        self.sending(deal_id, check_id)
        out = self.tmp("payer-leg.json")
        self.run("settle", "--deal", deal_id, "--check", check_id, "--status", "settled", "--out", out)
        return out

    def received_leg(self, deal_id: str, amount_msat: int, payment_ref: str) -> str:
        out = self.tmp("payee-leg.json")
        self.run("settle", "--deal", deal_id, "--received", str(amount_msat), "--receive-fee", "0", "--status", "settled",
                 "--payment-ref-type", "ln.payment_hash", "--payment-ref", payment_ref, "--out", out)
        return out

    def perform(self, deal_id: str, check_id: str, observed: str) -> str:
        out = self.tmp("act.json")
        self.run("perform", "--deal", deal_id, "--act", "delivered", "--check", check_id, "--observed", observed, "--out", out)
        return out

    def statement(self, deal_id: str, rows: dict[str, str]) -> str:
        out = self.tmp("statement.json")
        args = ["statement", "--deal", deal_id, "--out", out]
        for row, value in sorted(rows.items()):
            args += ["--statement", f"{row}={value}"]
        self.run(*args)
        return out

    def dispute(self, deal_id: str, row: str) -> dict:
        out = self.tmp("dispute.json")
        done = self.run("dispute", "--deal", deal_id, "--row", row, "--out", out)
        return {**done, "file": out}

    def report(self, deal_id: str) -> dict:
        """The deal's report as it stands (``deal report --read-only``): each row's status, read from capsulectl."""
        return self.run("report", "--deal", deal_id, "--read-only")

    def bundle(self, deal_id: str, share: str = "keep", to: str = "", wait: float = 0, say=None) -> Path:
        """The deal's report as an Evidence Bundle: the party's own copy (``keep``), or a copy shared with the
        ``adjudicator`` or the ``counterparty`` (put on record first). A report rests on a checkpoint, so with ``wait``
        it waits for the tick that covers the deal."""
        stop = time.monotonic() + wait
        while True:
            out = self.tmp(f"{share}-copy.json")
            args = ["report", "--deal", deal_id, "--bundle", out]
            if share != "keep":
                args += ["--share", share, "--to", to or share]
            try:
                self.run(*args)
                return Path(out)
            except Refused as exc:
                if "after its last checkpoint" not in str(exc) or time.monotonic() >= stop:
                    raise
            try:
                self.wait_checkpoint(max(stop - time.monotonic(), 1), say)
            except WitnessSlow:
                # the stamp was cut, and a report needs only that checkpoint, not the witness's receipt of it (a proof
                # sent later carries the receipt, adjudicator.send_proof_once_witnessed): the report is tried once more
                stop = time.monotonic()
            say = None

    def proof(self, deal_id: str, copy: Path) -> Path:
        """The file of the stamp proof and witness receipts behind a copy, for the adjudicator's entry check."""
        out = self.tmp("proof.json")
        self.run("checkpoint", "proof", "--deal", deal_id, "--copy", str(copy), "--out", out)
        return Path(out)

    def deals(self) -> list[dict]:
        return self.run("list", "--json")

    def verify(self, bundle: Path, proof: Path | None = None, report_on_fail: bool = False) -> dict:
        """``capsulectl verify --bundle`` on a file, with the hosted witness's directory so its receipts are checked. With
        ``proof`` (``deal checkpoint proof`` of that same copy), its x-deal-v1 entry also says the book's witness time,
        ``witnessed: {status, witness, at}``, as ``deal report --html`` draws it (evidencebook ``deal_v1_witnessed.go``).
        With ``report_on_fail``, a verdict other than VALID returns verify's report (it prints it, then exits non-zero:
        capsule-cli ``verify_bundle.go``), so the caller can say which check failed (#350); any other failure raises."""
        args = ["verify", "--bundle", str(bundle)]
        if witnessed():
            args += ["--witness-directory", self.write("witnesses.json", witness_directory())]
            if proof is not None:
                args += ["--stamp-proof", str(proof)]
        if not report_on_fail:
            return self.run(*args)
        with self._lock:
            return verify_report(self.ctl, args)


def verify_report(c: Ctl, args: list[str]) -> dict:
    """``Ctl.run`` for ``verify``, keeping the report verify prints before a non-zero verdict exit (``Ctl.run`` drops it
    and raises). A failure with no report (no such file, a bundle verify cannot read) raises :class:`Refused`."""
    env = {**os.environ, "HOME": str(c.home), "XDG_CONFIG_HOME": str(c.home / ".config")}
    try:
        done = subprocess.run([c.binary, "--profile", c.profile, *args], env=env, capture_output=True,
                              timeout=ctl_mod.TIMEOUT, check=False)
    except FileNotFoundError:
        raise Refused(f"{c.binary} is not installed") from None
    except subprocess.TimeoutExpired:
        raise Refused(f"capsulectl-deal {args[0]} did not finish in {ctl_mod.TIMEOUT}s") from None
    try:
        out = json.loads(done.stdout.decode("utf-8", "replace").strip() or "{}")
    except ValueError:
        out = {}
    if done.returncode == 0 or (isinstance(out, dict) and out.get("verdict")):
        return out
    why = out.get("error") if isinstance(out, dict) else None
    raise Refused(why or done.stderr.decode("utf-8", "replace").strip() or f"capsulectl-deal {args[0]} failed")


def decide(pack: Path, inputs: dict, admit_refs: dict | None = None) -> dict:
    """``capsule-engine admission evaluate`` on ``inputs`` under ``pack``; with ``admit_refs`` the output carries the
    x-deal-v1 admit body ``deal admit`` seals."""
    files = []
    try:
        d = tempfile.mkdtemp(prefix="ard-engine-")
        files.append(d)
        inp = Path(d) / "input.json"
        inp.write_text(json.dumps(inputs))
        args = ["admission", "evaluate", "--pack", str(pack), "--input", str(inp)]
        if admit_refs is not None:
            refs = Path(d) / "refs.json"
            refs.write_text(json.dumps(admit_refs))
            args += ["--admit", str(refs)]
        return gn.engine(*args)
    finally:
        for f in files:
            shutil.rmtree(f, ignore_errors=True)


def empty_refs() -> dict:
    """The ``--admit`` refs of a decision made on no card and no asks (the digest of the empty document)."""
    return {"asks": [], "answers": [], "card_digest": hashlib.sha256(b"{}").hexdigest()}
