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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

ROLES = ("witness", "rail", "catalog", "countersigner")


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


def stamp(home: Path, party: str, witness: str, tick: dict, kind: str = "routine") -> None:
    """One ``deal tick`` a party ran, as capsulectl reports it: the stamp it cut, if any, and each stamp it delivered to
    the witness or still has waiting, each by its checkpoint's size and, where capsulectl names it, its number.
    ``kind`` is why the tick ran: ``routine`` for the cadence's poll, ``deal`` for a stamp a deal step asked for. A tick
    with nothing due and nothing delivered says nothing the witness saw, so it is left out."""
    if tick.get("witness") == "not_configured" or "error" in tick:
        return
    delivered, pending = tick.get("delivered") or [], tick.get("pending") or []
    ticked = tick.get("state") == "ticked"
    if not ticked and not delivered:
        return
    numbers = _numbers(tick)
    _append(home, "witness", {
        "party": party, "witness": witness, "kind": kind,
        "cut": {"no": tick.get("tick"), "size": tick.get("checkpoint")} if ticked else None,
        "delivered": [{"size": s, "no": numbers.get(s)} for s in delivered if isinstance(s, int)],
        "pending": [{"size": p["checkpoint"], "no": numbers.get(p["checkpoint"]), "tried": not p.get("not_tried_this_run")}
                    for p in pending if isinstance(p, dict) and isinstance(p.get("checkpoint"), int)]})


def _numbers(tick: dict) -> dict[int, int]:
    """Each delivered or pending checkpoint's stamp number, by its size, as ``deal tick`` reports it: ``delivered_ticks``
    (``{"checkpoint": size, "tick": N}`` for each delivered size) and the ``tick`` of each ``pending`` row
    (evidencebook#1083). A capsulectl without them (v0.1.1) gives none, and the demo never works a number out from the
    sizes: the cadence's numbering is capsulectl's alone."""
    out: dict[int, int] = {}
    for row in [*(tick.get("delivered_ticks") or []), *(tick.get("pending") or [])]:
        if isinstance(row, dict) and isinstance(row.get("checkpoint"), int) and isinstance(row.get("tick"), int):
            out[row["checkpoint"]] = row["tick"]
    return out


def payment(home: Path, kind: str, payer: str, payee: str, amount_msat: int, reference: str, rail: str) -> None:
    """One step on the rail: ``invoice`` (the payee's invoice for the amount), ``paid``, ``sent`` (not confirmed yet) or
    ``not_paid``."""
    _append(home, "rail", {"kind": kind, "payer": payer, "payee": payee, "amount_msat": amount_msat,
                           "reference": reference[:12], "rail": rail})


def countersigned(home: Path, party: str, deal_id: str, stamp: dict) -> None:
    """One countersign upgrade a party asked for: what capsulectl's report says the countersigner signed (the rung, how
    far into the party's records), never a record, a digest or a payment's detail."""
    _append(home, "countersigner", {"party": party, "deal": deal_id[5:13], "rung": stamp.get("rung"),
                                    "finding": stamp.get("finding"), "through": stamp.get("through_step"),
                                    "steps": stamp.get("steps")})


def catalog_read(home: Path, seller: str, product: str) -> None:
    """One read of a seller's product from the catalog stand-in (a buyer's agent checking a listing)."""
    _append(home, "catalog", {"kind": "read", "seller": seller, "product": product})


def catalog_lines(products: dict[str, dict[str, dict]], label: Callable[[str], str]) -> list[str]:
    """What the catalog stand-in lists: each seller's products, titles and prices."""
    return [f"  {label(seller)}: product {pid}, {p['title']}, {p['price_msat']:,} msat"
            for seller, items in products.items() for pid, p in items.items()]


@dataclass
class Hash:
    """One stamp of a party's book as the witness's screen tells it: its number (None when the feed cannot tell it),
    why it was cut, and what became of it."""
    party: str
    witness: str
    size: int
    no: int | None = None
    kind: str = "deal"  # a size no tick of the feed cut was cut inside `deal agree` or `deal ruling`: a deal's stamp
    seen: str = ""  # when the feed first reported it
    taken: str = ""  # when the witness time-stamped it, "" while it has not
    tried: bool = False  # sent at least once while it waits


def witness_hashes(events: list[dict]) -> list[Hash]:
    """Every stamp the witness feed reports, each party's in the order they were cut (checkpoint sizes only grow). A
    stamp's number is the one capsulectl gave it (the tick that cut it, or the tick that delivered it or has it
    waiting); a stamp cut inside ``deal agree`` or ``deal ruling`` that no report numbers keeps none. This reads the
    whole feed, so the order its lines were written in changes nothing."""
    by_party: dict[str, dict[int, Hash]] = {}
    for e in events:
        if "party" not in e or not isinstance(e.get("delivered"), list):
            continue  # a line of the feed's earlier shape (before #458): it names no checkpoint by size
        seen = by_party.setdefault(e["party"], {})

        def get(size: int, no: int | None) -> Hash:
            h = seen.get(size)
            if h is None:
                h = seen[size] = Hash(e["party"], e["witness"], size, seen=e["at"])
            h.seen = min(h.seen, e["at"])
            if no is not None:
                h.no = no
            return h

        cut = e.get("cut") or {}
        if isinstance(cut.get("size"), int):
            get(cut["size"], cut.get("no") if isinstance(cut.get("no"), int) else None).kind = e.get("kind", "routine")
        for d in e["delivered"]:
            h = get(d["size"], d.get("no"))
            h.taken = min(h.taken, e["at"]) if h.taken else e["at"]
        for p in e["pending"]:
            get(p["size"], p.get("no")).tried |= p["tried"]
    return [h for seen in by_party.values() for _, h in sorted(seen.items())]


def _clock(at: str) -> str:
    return datetime.fromisoformat(at).astimezone().strftime("%H:%M:%S")


def witness_screen(events: list[dict], label: Callable[[str], str]) -> tuple[list[str], list[str]]:
    """The witness's screen (Sherlock2's ruling on #458): a line for each deal's stamp, in Sherlock2's words once the
    witness has time-stamped it, and one line for each party's routine stamps, folded."""
    hashes = witness_hashes(events)
    lines: list[tuple[str, str]] = []
    routine: dict[str, list[Hash]] = {}
    for h in hashes:
        if h.kind == "routine":
            routine.setdefault(h.party, []).append(h)
            continue
        who, name = label(h.party), f"hash no. {h.no}" if h.no is not None else "an earlier hash"
        if h.taken:
            lines.append((h.taken, f"{_clock(h.taken)}  {who}'s book sent {name}; {h.witness} time-stamped it."))
        elif h.tried:
            lines.append((h.seen, f"{_clock(h.seen)}  {who}'s book sent {name}; {h.witness} has not time-stamped it yet."))
        else:
            lines.append((h.seen, f"{_clock(h.seen)}  {who}'s book has {name} to send; {h.witness} has not received it yet."))
    folded = []
    for party, hs in routine.items():
        who, witness = label(party), hs[-1].witness
        taken = [h for h in hs if h.taken]
        last = taken[-1] if taken else None  # the newest: a party's hashes are in the order they were cut
        line = f"{who}'s routine stamps, one a minute: "
        if last is not None:
            line += (f"its book sent {len(taken)} hash{'es' if len(taken) != 1 else ''}, the last "
                     f"{'no. ' + str(last.no) if last.no is not None else 'one'} at {_clock(last.taken)}; "
                     f"{witness} time-stamped {'each' if len(taken) != 1 else 'it'}")
        else:
            line += f"{witness} has time-stamped none yet"
        waiting = [h for h in hs if not h.taken]
        if waiting:
            nos = ", ".join(f"no. {h.no}" if h.no is not None else "one" for h in waiting)
            line += f"; {nos} {'is' if len(waiting) == 1 else 'are'} waiting for {witness}"
        folded.append(line + ".")
    return [text for _, text in sorted(lines, key=lambda x: x[0])], folded


def words(role: str, event: dict, label: Callable[[str], str]) -> str:
    """One event as the role's screen says it (the witness's screen is :func:`witness_screen`)."""
    at = _clock(event["at"])
    if role == "countersigner":
        who = label(event["party"])
        sent = (f"{who}'s book sent its own records of deal {event['deal']} (digests and seal times, and its own "
                "payments' amounts, fees, references and status; never the other side's records)")
        if event.get("rung") in ("countersigned", "countersigned_in_part"):
            return (f"{at}  {sent}; the demo's countersigner signed records 1 to {event['through']} of "
                    f"{event['steps']}, as capsulectl reports.")
        return (f"{at}  {sent}; no countersignature counts yet (capsulectl's finding: "
                f"{event.get('finding') or 'not_countersigned'}).")
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
               "sees only each book's key and log id. Each deal's stamps have a line each; each party's routine stamps, "
               "one a minute, share one line at the bottom.",
    "rail": "The payment rail, as the buyer's agent reports each invoice and payment.",
    "countersigner": "The countersigner, as each party's book reports it: a party sends it its own records of one deal "
                     "as digests with their seal times, and for each of its own payments whether it sent or received "
                     "it, the amount, fees, payment reference, status and when it saw it (never a payment's secret, "
                     "never the other side's records), and it signs them. It is the demo's own, run by the operator, "
                     "who also runs every party here, so it is not independent of them.",
    "catalog": "The catalog, a stand-in for a store platform's product catalog (not a real store), as the demo's stage "
               "that serves it reports: what it lists, and each time an agent reads a product from it.",
}


def follow(home: Path, role: str, poll_s: float = 0.5) -> Iterator[dict]:
    """The role's events from the start of its feed, then each new one as it comes; never ends."""
    for batch in batches(home, role, poll_s):
        yield from batch


def batches(home: Path, role: str, poll_s: float = 0.5) -> Iterator[list[dict]]:
    """The role's events from the start of its feed, then the new ones, as each read finds them (a read that finds
    none yields nothing); never ends."""
    f, pos = path(home, role), 0
    while True:
        got = []
        if f.is_file():
            with open(f) as fh:
                fh.seek(pos)
                while line := fh.readline():
                    if not line.endswith("\n"):
                        break  # a line still being written: read it whole next time
                    pos = fh.tell()
                    try:
                        got.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        if got:
            yield got
        time.sleep(poll_s)
