# SPDX-License-Identifier: Apache-2.0
"""What the testbed's roles without an agent saw, for their own screens (evidencebook-skills#382).

The witness and the payment rail run no agent and keep no book of the demo's, so their screens are fed from where the
demo already knows the facts: each stamp a party sends the witness (:meth:`party.Party.tick` and ``stamp``, from
capsulectl's own ``deal tick`` output), and each invoice and payment where Maya's agent pays (:func:`buyer.open_and_pay`,
which knows who pays whom). Each event is one JSON line in ``<home>/feeds/<role>.jsonl``; ``demo.py watch <role>``
prints them in plain words as they come. A feed never holds a record's content, a payment preimage or a key: the
witness's line carries only what the witness receives (a stamp's number and size, never a record), the rail's only the
amount, who pays whom, and a payment reference cut short. Writing a feed never fails the step it reports."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

ROLES = ("witness", "rail", "catalog")


def path(home: Path, role: str) -> Path:
    return Path(home).expanduser() / "feeds" / f"{role}.jsonl"


def _append(home: Path, role: str, event: dict) -> None:
    try:
        f = path(home, role)
        f.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with open(f, "a") as fh:
            fh.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **event}) + "\n")
    except Exception:  # noqa: BLE001 - a screen's feed is never worth failing the deal step it reports
        pass


def stamp(home: Path, party: str, witness: str, tick: dict) -> None:
    """One ``deal tick`` a party ran: what it sent the witness and what the witness took. A tick with nothing due and
    nothing delivered says nothing the witness saw, so it is left out."""
    if tick.get("witness") == "not_configured" or "error" in tick:
        return
    delivered, pending = tick.get("delivered") or [], tick.get("pending") or []
    if tick.get("state") != "ticked" and not delivered:
        return
    _append(home, "witness", {"party": party, "witness": witness, "stamp": tick.get("tick") if tick.get("state") == "ticked" else None,
                              "covers": tick.get("checkpoint"), "taken": len(delivered), "waiting": len(pending)})


def payment(home: Path, kind: str, payer: str, payee: str, amount_msat: int, reference: str, rail: str) -> None:
    """One step on the rail: ``invoice`` (the payee's invoice for the amount), ``paid``, ``sent`` (not confirmed yet) or
    ``not_paid``."""
    _append(home, "rail", {"kind": kind, "payer": payer, "payee": payee, "amount_msat": amount_msat,
                           "reference": reference[:12], "rail": rail})


def catalog_read(home: Path, seller: str, product: str) -> None:
    """One read of a seller's product from the catalog stand-in (a buyer's agent checking a listing)."""
    _append(home, "catalog", {"kind": "read", "seller": seller, "product": product})


def catalog_lines(products: dict[str, dict[str, dict]], label: Callable[[str], str]) -> list[str]:
    """What the catalog stand-in lists: each seller's products, titles and prices."""
    return [f"  {label(seller)}: product {pid}, {p['title']}, {p['price_msat']:,} msat"
            for seller, items in products.items() for pid, p in items.items()]


def words(role: str, event: dict, label: Callable[[str], str]) -> str:
    """One event as the role's screen says it."""
    at = datetime.fromisoformat(event["at"]).astimezone().strftime("%H:%M:%S")
    if role == "witness":
        who, witness_name = label(event["party"]), event["witness"]
        parts = []
        if event.get("stamp") is not None:
            parts.append(f"{who}'s book sent its hash no. {event['stamp']}")
        if event.get("taken"):
            parts.append(f"{witness_name} took {event['taken']} of {who}'s stamps and signed a receipt for each")
        if event.get("waiting"):
            parts.append(f"{event['waiting']} of {who}'s stamps are still waiting for {witness_name}")
        return f"{at}  " + "; ".join(parts) + "."
    if role == "catalog":
        return f"{at}  A buyer's agent read {label(event['seller'])}'s product {event['product']} to check its listing."
    simulated = " (simulated: no money moves)" if event["rail"] == "simulated" else ""
    amount = f"{event['amount_msat']:,} msat"
    if event["kind"] == "invoice":
        line = f"{label(event['payee'])} made an invoice for {amount} to {label(event['payer'])}"
    elif event["kind"] == "paid":
        line = f"{label(event['payer'])} paid {label(event['payee'])} {amount}"
    elif event["kind"] == "sent":
        line = f"{label(event['payer'])} sent {label(event['payee'])} {amount}; the rail has not confirmed it yet"
    else:
        line = f"{label(event['payer'])}'s payment of {amount} to {label(event['payee'])} did not go through; no money moved"
    return f"{at}  {line}{simulated}, reference {event['reference']}."


HEADINGS = {
    "witness": "The witness, as each party's book reports it: each party sends it a hash over its own book (never a "
               "record), and it signs back the time it saw that hash. The names are this demo's labels: the witness "
               "sees only each book's key and log id.",
    "rail": "The payment rail, as the buyer's agent reports each invoice and payment.",
    "catalog": "The catalog, a stand-in for a store platform's product catalog (not a real store), as the demo's stage "
               "that serves it reports: what it lists, and each time an agent reads a product from it.",
}


def follow(home: Path, role: str, poll_s: float = 0.5) -> Iterator[dict]:
    """The role's events from the start of its feed, then each new one as it comes; never ends."""
    f, pos = path(home, role), 0
    while True:
        if f.is_file():
            with open(f) as fh:
                fh.seek(pos)
                while line := fh.readline():
                    if not line.endswith("\n"):
                        break  # a line still being written: read it whole next time
                    pos = fh.tell()
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue
        time.sleep(poll_s)
