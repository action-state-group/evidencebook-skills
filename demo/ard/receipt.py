# SPDX-License-Identifier: Apache-2.0
"""A party's own receipt for a deal: in words (:func:`receipt_text`, from capsulectl's report of the deal) and as a page
(:func:`receipt_page`, capsulectl's own ``deal report --html``, evidencebook#935).

The page is drawn by capsulectl from its own verify report of the party's copy, with capsule-viewer's receipt page: it says
the other side's half and the book's witness time as capsulectl verified them, and adds nothing. Nothing here computes a
row's status: every line is read from capsulectl's report."""
from __future__ import annotations

import json
from pathlib import Path

import pages
import party as pt
import screens

#: How each row status reads (evidencebook ``rowstatus``), in this demo's words.
STATUS = {
    "agreed": "met, as both sides said", "agreed_so_far": "met so far, as both sides said (still open to dispute)",
    "uncontested": "met, as one side said and the other did not contest", "waiting": "one side has said; waiting for the other",
    "in_disagreement": "the two sides disagree", "in_dispute": "in dispute, before the adjudicator",
    "ruled": "ruled by the adjudicator", "not_due": "not due yet", "no_statement": "no one said",
    "not_reached": "its date was never set",
}
ROWS = {pt.PAID: "payment", pt.DELIVERED: "delivery"}

#: How long the receipt page waits for the witness to take the checkpoint it stamps first.
PAGE_WAIT_S = 30


class ReceiptError(RuntimeError):
    """No receipt page: capsulectl refused to draw it."""


def receipt_text(p: pt.Party, name: str, deal_id: str, *, real: bool, seller: bool, counterparty: str = "") -> str:
    """The party's receipt for one deal in words: each row's status as capsulectl reports it now; on the buyer's, what
    a ruling for her means (:func:`screens.ruled_for_buyer`, naming ``counterparty``, the seller)."""
    try:
        rep = p.report(deal_id)
    except pt.Refused as exc:
        p.log(f"receipt of {deal_id}: {exc!r}")
        return f"{name}: its receipt for deal {deal_id[5:13]} is not ready yet; ask again in a minute."
    report = rep.get("report", rep)
    lines = [f"{name}: its receipt for deal {deal_id[5:13]}, from its own records (capsulectl's report, as of {screens.local_time(report.get('as_of', ''), date=True)})"]
    for row in report.get("rows", []):
        what = ROWS.get(row["id"], row["id"])
        status = STATUS.get(row.get("status", ""), row.get("status", ""))
        line = f"  {what}: {status}"
        if row.get("status") == "ruled" and row.get("ruling"):
            r = row["ruling"]
            line += f" ({'not met' if r.get('value') == 'not_met' else 'met'}, against the {r.get('against')})"
        elif row.get("value"):
            line += f" ({'met' if row['value'] == 'met' else 'not met'})"
        lines.append(line)
    if not seller:
        lines += ["  " + x for x in screens.ruled_for_buyer(report, counterparty or "the seller")]
    lines += proof_lines(p, deal_id, name)
    if seller and real:
        owed = next((r.get("owed", {}).get("amount_minor") for r in report.get("rows", []) if r["id"] == pt.PAID), None)
        if owed:
            lines.append("  " + screens.seller_credit_note(owed))
    if not real:
        lines.append("  Test money: this deal's payment was on a simulated rail. No real money moved.")
    return "\n".join(lines)


def proof_lines(p: pt.Party, deal_id: str, name: str = "this party") -> list[str]:
    """What the party's own copy proves, in the receipt's words (Sherlock2's what-confirmation on #242):

    - "Signed by both sides" only when ``capsulectl deal verify --bundle`` passes on the whole copy and its
      ``counterparty_half`` verifies (evidencebook #885-#887); never "countersigned".
    - The witness time exactly as the receipt page gets it (evidencebook-skills#329): a stamp waited for as the page
      waits (:data:`PAGE_WAIT_S`), then ``verify --bundle --stamp-proof --witness-directory`` on the copy and its own
      proof, whose ``witnessed`` result the page draws, said in attributed voice (u219, 2026-11-25: "as capsulectl verify
      reported on your own book")."""
    if pt.witnessed():
        try:
            p.wait_checkpoint(PAGE_WAIT_S)
        except pt.Refused:
            pass  # the copy below rests on the newest checkpoint; verify says whether the witness took it
    try:
        copy = p.bundle(deal_id)
        checked = p.verify(copy, p.proof(deal_id, copy) if pt.witnessed() else None)
    except pt.Refused as exc:
        p.log(f"receipt of {deal_id}: {exc!r}")
        return ["  This copy is not ready to check yet; ask again in a minute."]
    entries = checked.get("extensions", [])
    half = next((e.get("counterparty_half") for e in entries if e.get("counterparty_half")), None)
    if checked.get("verdict") != "VALID":
        lines = [f"  This copy did not verify (capsulectl deal verify: {checked.get('verdict')})."]
    elif half and half.get("status") == "verified":
        lines = ["  Signed by both sides: the other side's half verifies (capsulectl deal verify)."]
    else:
        lines = ["  The other side's half is not in this copy."]
    return lines + [witness_line(next((e.get("witnessed") for e in entries if e.get("witnessed")), None), name)]


def witness_line(witnessed: dict | None, name: str) -> str:
    """The receipt's witness line from verify's ``witnessed`` result for the copy (evidencebook ``deal_v1_witnessed.go``):
    ``verified`` with the witness's own time, ``withheld`` (no receipt held yet), ``failed`` (a receipt or the proof did
    not verify), kept apart."""
    if not pt.witnessed():
        return "  Not time-stamped: this run names no witness (ARD_WITNESS=off)."
    status = (witnessed or {}).get("status", "withheld")
    if status == "verified":
        at = witnessed.get("at", "")
        when = f" at {screens.local_time(at, date=True)}" if at else ""
        return f"  Time-stamped by {pt.WITNESS_NAME}{when}, as checked on {name}'s own book."
    if status == "failed":
        return (f"  No witness time: capsulectl verify could not check {pt.WITNESS_NAME}'s receipt for {name}'s own "
                "book.")
    if "no witness receipt is held" in (witnessed or {}).get("reason", ""):
        return f"  Not time-stamped yet: {pt.WITNESS_NAME} has not taken {name}'s latest stamp; ask again in a minute."
    # withheld for another reason (a receipt it could not check under the directory): no claim either way
    return f"  No witness time: capsulectl verify reported none it could check for {name}'s own book."


def receipt_page(p: pt.Party, name: str, deal_id: str, *, rail: str, seller: bool) -> Path:
    """Write the party's receipt page for a deal, and return its path: capsulectl's own page
    (``capsulectl deal report --html``, evidencebook#935), drawn with capsule-viewer's Go receipt package."""
    out = pages.path(p.name, f"receipt-{deal_id}")
    # with the hosted witness's directory, so the page says the book's witness time capsulectl verified
    args = ("report", "--deal", deal_id, "--html", str(out),
            "--witness-directory", p.write("witnesses.json", pt.witness_directory()))
    # A page rests on a checkpoint, and says the witness time only once the witness has taken it: stamp now and
    # wait for the witness, as the card page does. If it does not take the stamp in time the page is still drawn,
    # without the witness line, since capsulectl says only what it verified.
    try:
        p.wait_checkpoint(PAGE_WAIT_S)
    except pt.Refused:
        pass
    try:
        p.run(*args)
    except pt.Refused as exc:
        raise ReceiptError(str(exc)) from None
    return out
