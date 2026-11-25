# SPDX-License-Identifier: Apache-2.0
"""A party's own receipt for a deal: in words (:func:`receipt_text`, from capsulectl's report of the deal) and as a page
(:func:`receipt_page`, capsule-viewer's receipt module drawing the party's own copy of the deal, with nothing added).

The copy is ``capsulectl deal report --deal D --bundle F``: the party's own deal book at its checkpoint with the sealed
report beside it. ``capsulectl verify --bundle`` checks it. capsule-viewer's x-deal-v1 receipt module is JavaScript only
and draws a copy only once the page's verifier runs the x-deal-v1 profile rule, which is not released yet (lane
eb-viewer025, after capsule-viewer#398); its Python receipt path covers x-deal-v0 only. Until then the page says it is not
available, and :func:`receipt_text` gives the receipt in words. Nothing here computes a row's status: every line is read
from capsulectl's report."""
from __future__ import annotations

import hashlib
import json
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
    lines = [f"{name}: its receipt for deal {deal_id[5:13]}, from its own records (capsulectl's report, as of {report.get('as_of', '')})"]
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
    if seller and real:
        owed = next((r.get("owed", {}).get("amount_minor") for r in report.get("rows", []) if r["id"] == pt.PAID), None)
        if owed:
            lines.append("  " + screens.seller_credit_note(owed))
    if not real:
        lines.append("  Test money: this deal's payment was on a simulated rail. No real money moved.")
    return "\n".join(lines)


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
    """Write the party's receipt page for a deal, and return its path."""
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
