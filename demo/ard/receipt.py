# SPDX-License-Identifier: Apache-2.0
"""A party's own receipt for a deal: in words (:func:`receipt_text`, from capsulectl's report of the deal) and as a page
(:func:`receipt_page`, capsulectl's own ``deal report --html``, evidencebook#935).

The page is drawn by capsulectl from its own verify report of the party's copy, with capsule-viewer's receipt page: it says
the other side's half and the book's witness time as capsulectl verified them, and adds nothing. Nothing here computes a
row's status: every line is read from capsulectl's report."""
from __future__ import annotations

import hashlib
import json
import time
import warnings
from pathlib import Path

import pages
import party as pt
import screens

AUDIENCE = "keep"
#: This demo's plainer words for capsule-viewer's example wording (hand run 2026-11-24).
PLAIN = {
    "page.title": "Order receipt",
    "sides.missing.none": "Only this side's records are in this receipt: the other party keeps its own copy.",
    "seller.handover.none": "Not tracked here",
}
#: How each row status reads (evidencebook ``rowstatus``), in this demo's words.
STATUS = {
    "agreed": "met, as both sides said", "agreed_so_far": "met so far, as both sides said (still open to dispute)",
    "uncontested": "met, as one side said and the other did not contest", "waiting": "one side has said; waiting for the other",
    "in_disagreement": "the two sides disagree", "in_dispute": "in dispute, before the adjudicator",
    "ruled": "ruled by the adjudicator", "not_due": "not due yet", "no_statement": "no one said",
    "not_reached": "its date was never set",
}
ROWS = {pt.PAID: "payment", pt.DELIVERED: "delivery"}


#: On since evidencebook#935, whose page is drawn by capsule-viewer 130877b1 (#420, #421) from the binary's own verify
#: report: it says the other side's half and the book's witness time as capsulectl verified them (#242). It was off for
#: the 2026-11-25 run, when capsulectl's first v1 page (64da5152) said "no witness" and "not countersigned" for a
#: witnessed two-sided deal.
DRAW_V1_PAGE = True

#: How long the receipt page waits for the witness to take the checkpoint it stamps first.
PAGE_WAIT_S = 30

NOT_YET = "a receipt page for this kind of deal can't be drawn yet; the receipt in words is complete"


class ReceiptError(RuntimeError):
    """No receipt page: the copy did not verify or render."""


def receipt_text(p: pt.Party, name: str, deal_id: str, *, real: bool, seller: bool) -> str:
    """The party's receipt for one deal in words: each row's status as capsulectl reports it now."""
    try:
        rep = p.report(deal_id)
    except pt.Refused as exc:
        return f"{name}: its receipt for deal {deal_id[5:13]} is not ready yet: {exc}"
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
    lines += proof_lines(p, deal_id)
    if seller and real:
        owed = next((r.get("owed", {}).get("amount_minor") for r in report.get("rows", []) if r["id"] == pt.PAID), None)
        if owed:
            lines.append("  " + screens.seller_credit_note(owed))
    if not real:
        lines.append("  Test money: this deal's payment was on a simulated rail. No real money moved.")
    return "\n".join(lines)


def proof_lines(p: pt.Party, deal_id: str) -> list[str]:
    """What the party's own copy proves, in the receipt's words (Sherlock2's what-confirmation on #242):

    - "Signed by both sides" only when ``capsulectl deal verify --bundle`` passes on the whole copy and its
      ``counterparty_half`` verifies (evidencebook #885-#887); never "countersigned".
    - "Time-stamped by Action State's witness at <time>" only when ``capsulectl deal checkpoint proof`` holds a receipt
      from a witness the agreement names for the checkpoint the copy rests on, which covers the copy's last record; the
      time is the witness's own (the receipt's ``iat``)."""
    try:
        copy = p.bundle(deal_id)
        checked = p.verify(copy)
    except pt.Refused as exc:
        return [f"  This copy is not ready to check yet: {exc}"]
    half = next((e.get("counterparty_half") for e in checked.get("extensions", []) if e.get("counterparty_half")), None)
    if checked.get("verdict") != "VALID":
        lines = [f"  This copy did not verify (capsulectl deal verify: {checked.get('verdict')})."]
    elif half and half.get("status") == "verified":
        lines = ["  Signed by both sides: the other side's half verifies (capsulectl deal verify)."]
    else:
        lines = ["  The other side's half is not in this copy."]
    stamped, when = False, ""
    try:
        out = p.tmp("proof.json")
        got = p.run("checkpoint", "proof", "--deal", deal_id, "--copy", str(copy), "--out", out)
        if got.get("named_witness_receipts"):
            stamped, when = True, witness_time(json.loads(Path(out).read_text()))
    except (pt.Refused, OSError, ValueError):
        stamped, when = False, ""
    if stamped and when:
        lines.append(f"  Time-stamped by {pt.WITNESS_NAME} at {screens.local_time(when, date=True)}.")
    elif stamped:  # a receipt that verifies but carries no time: stamped, its time not stated
        lines.append(f"  Time-stamped by {pt.WITNESS_NAME}; its receipt states no time.")
    else:
        lines.append(f"  Not time-stamped yet: the next checkpoint sends it to {pt.WITNESS_NAME}.")
    return lines


def witness_time(proof: dict) -> str:
    """The witness's own time on Action State's witness's receipt in a ``checkpoint proof`` file (capsulectl counts it
    in ``named_witness_receipts`` only once it verifies under the profile's pinned key): the ``iat`` claim (6) in the CWT
    claims (header label 15, RFC 9597) of the COSE receipt's protected header, as UTC; "" when it carries none."""
    import base64
    from datetime import datetime, timezone
    for r in proof.get("witness_receipts", []):
        if r.get("ts_url", "").rstrip("/") != pt.WITNESS_URL:
            continue  # a receipt from another witness: its time is not Action State's witness's
        try:
            raw = base64.b64decode(r["receipt"] + "=" * (-len(r["receipt"]) % 4))
            sign1, _ = _cbor(raw, 0)
            protected = sign1[0] if isinstance(sign1, list) and sign1 and isinstance(sign1[0], bytes) else b""
            header, _ = _cbor(protected, 0) if protected else ({}, 0)
        except (ValueError, KeyError, TypeError):
            continue  # a receipt this reader cannot read gives no time; capsulectl already verified it
        claims = header.get(15, {}) if isinstance(header, dict) else {}
        iat = claims.get(6) if isinstance(claims, dict) else None
        if isinstance(iat, int):
            try:
                return datetime.fromtimestamp(iat, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except (OverflowError, OSError, ValueError):
                continue  # a time no clock can show
    return ""


def _cbor(b: bytes, i: int, depth: int = 0):
    """A small CBOR reader (RFC 8949) for a COSE receipt's header: integers, byte and text strings, arrays, maps, tags.
    Any input it cannot read (truncated, too deep, an indefinite length) raises ValueError."""
    if depth > 16:
        raise ValueError("CBOR nested too deep")
    if i >= len(b):
        raise ValueError("CBOR truncated")
    major, info = b[i] >> 5, b[i] & 31
    i += 1
    if info < 24:
        n = info
    elif info in (24, 25, 26, 27):
        size = 1 << (info - 24)
        if i + size > len(b):
            raise ValueError("CBOR truncated")
        n, i = int.from_bytes(b[i:i + size], "big"), i + size
    else:
        raise ValueError("indefinite or reserved CBOR length")
    if major == 0:
        return n, i
    if major == 1:
        return -1 - n, i
    if major in (2, 3):
        if i + n > len(b):
            raise ValueError("CBOR truncated")
        v = b[i:i + n]
        try:
            return (v if major == 2 else v.decode()), i + n
        except UnicodeDecodeError:
            raise ValueError("CBOR text is not UTF-8") from None
    if major == 4:
        out = []
        for _ in range(n):
            v, i = _cbor(b, i, depth + 1)
            out.append(v)
        return out, i
    if major == 5:
        m = {}
        for _ in range(n):
            k, i = _cbor(b, i, depth + 1)
            v, i = _cbor(b, i, depth + 1)
            m[k if not isinstance(k, (list, dict)) else str(k)] = v
        return m, i
    if major == 6:
        return _cbor(b, i, depth + 1)
    return None, i  # simple values and floats: not read here


def render(bundle: dict, output: dict) -> str:
    """capsule-viewer's receipt page for the keep copy, from what the verifier reported for it."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)  # the Python receipt modules (capsule-viewer#71)
        from capsule_viewer.composed import composition_from_capsulectl
        from capsule_viewer.receipt import example_wording_pack, receipt_page
        from capsule_viewer.verifier_report import VerifierReportError, context_from_capsulectl

    try:
        context, assurance = context_from_capsulectl(bundle, output)
        composition = composition_from_capsulectl(bundle, output)
    except VerifierReportError as exc:
        raise ReceiptError(f"the verifier's report does not fit this copy: {exc}") from None
    wording = json.loads(example_wording_pack())
    wording["id"] = "evidencebook.receipt-wording.ard/v1"
    wording["entries"].update(PLAIN)
    pack = json.dumps(wording, sort_keys=True).encode()
    page = receipt_page(context, assurance, pack, hashlib.sha256(pack).hexdigest(), audience=AUDIENCE,
                        composition=composition)
    if "wording-refused" in page:
        raise ReceiptError("capsule-viewer refused this demo's receipt wording pack")
    if 'data-level="L0"' not in page:
        raise ReceiptError(NOT_YET)
    return page


def receipt_page(p: pt.Party, name: str, deal_id: str, *, rail: str, seller: bool) -> Path:
    """Write the party's receipt page for a deal, and return its path: capsulectl's own page
    (``capsulectl deal report --html``, evidencebook#935). With :data:`DRAW_V1_PAGE` off, capsule-viewer's page of the
    party's own copy, which has no x-deal-v1 form, so it says the page can't be drawn (:data:`NOT_YET`)."""
    if DRAW_V1_PAGE:
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
    try:
        copy = p.bundle(deal_id, "keep", wait=30)
    except pt.Refused as exc:
        raise ReceiptError(str(exc)) from None
    output = p.verify(copy)
    if output.get("verdict") != "VALID":
        raise ReceiptError(f"capsulectl verify --bundle says {output.get('verdict')}")
    try:
        page = render(json.loads(copy.read_text()), output)
    except ReceiptError as exc:
        # say what the verifier said of this copy, read from its own report
        raise ReceiptError(f"{exc} (this copy's records were checked: capsulectl verify --bundle says "
                           f"{output.get('verdict')})") from None
    return pages.write(p.name, f"receipt-{deal_id}", page)
