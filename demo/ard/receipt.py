# SPDX-License-Identifier: Apache-2.0
"""A party's own deal receipt as a page: capsule-viewer's receipt module drawing this party's own copy of the deal
(audience ``keep``), with nothing added, offline.

The copy is an ``evidence-bundle/v2`` of the party's own deal book: every step disclosed, and the party's sealed
report in the ``x-deal-report/v0`` extension, which the ``x-deal-v0`` extension names (capsule-cli#294, the
standalone form). The report is on no log, so sealing it changes nothing the deal book holds: the halves, the History
card and a seller's re-entry read the same records after it as before. It binds the deal checkpoint the copy is made
at, so a book that grew since (an outcome note, say) gets a new report.

The report's lines are this demo's own words, read from the party's own records: a seller's payment line says what
its own outcome record states, and on a simulated rail, or for a seeded sample deal, nothing says money moved. ``capsulectl verify --bundle`` (the
binary ``CAPSULECTL_DEAL`` names) checks the copy, and capsule-viewer's receipt module renders it from that report."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import warnings
from datetime import datetime, timezone
from pathlib import Path

import goose_node as gn
from capsule_emit import produce
from evidencebook import deal
from evidencebook.deal import report as rp
from evidencebook.deal.names import REPORT_EXTENSION, REPORT_POINTER

import pages
import screens
from deals import OUTCOME_NOTE, SAMPLE_REASON

AUDIENCE = "keep"
#: The step kinds the typed records (a seller's chain) stand for.
_TYPED = {"proposed-action/v0": "check", "action-evaluation/v0": "verdict", "action-approval/v0": "approval",
          "action-record/v0": "action", "task-authority/v0": "task_authority", "action-outcome/v0": "outcome"}
#: The report's step kind for each record kind (capsule-viewer places a step by it).
_KIND = {"baseline": "open", "check": "check", "verdict": "check", "approval": "approval", "action": "act",
         "task_authority": "open", "outcome": "outcome", "close": "close", OUTCOME_NOTE: "outcome"}


class ReceiptError(RuntimeError):
    """No receipt page: the deal is not closed yet, or the copy did not verify or render."""


def _kind(payload: dict) -> str:
    return payload.get("x-deal-v0", {}).get("record_type") or _TYPED.get(payload.get("type", ""), payload.get("type", "record"))


def _at(payload: dict) -> str:
    return payload.get("x-deal-v0", {}).get("at") or payload.get("at", "")


def ready(node: gn.Node, deal_id: str) -> None:
    """Refuse unless the deal is closed on this party's book and this party holds the other party's closing half."""
    if not node.has_deal(deal_id):
        raise ReceiptError(f"this party holds no deal {deal_id}")
    if not any(_kind(json.loads(p)) == "close" for p in node.deal_payloads(deal_id)):
        raise ReceiptError(f"deal {deal_id} is not closed yet: its receipt page is made after the close")
    if not any(s.get("deal_id") == deal_id and s.get("close_half_digest") for _, s in node.notes(gn.HALF_RECEIVED)):
        raise ReceiptError(f"deal {deal_id} is closed here, but the other party's closing half has not arrived yet: "
                           "the receipt page is made once both halves are exchanged")


def _line(kind: str, body: dict, simulated: bool) -> str:
    amount = body.get("amount_minor")
    action = body.get("action")
    if kind == "baseline":
        return f"Opened: {body['terms']['item']} at {screens.msat(body['terms']['price_minor'])}"
    if kind == "task_authority":
        return "Authorised the sale"
    if kind == "check":
        return {"pay": f"About to pay {screens.msat(amount)}", "offer": f"About to offer {screens.msat(amount)}",
                "commit": f"About to commit to the sale at {screens.msat(amount)}"}.get(action, f"Proposed: {action}")
    if kind == "verdict":
        result = body.get("result") or body.get("disposition")
        return f"Checked: {result}, {len(body.get('differences') or body.get('findings') or [])} difference(s)"
    if kind == "approval":
        if body.get("kind") == "counterparty-acceptance-observation":
            return "The buyer accepted the offer"
        return f"Went ahead: {body.get('approver', 'approved')}"
    if kind == "action":
        if action == "pay":
            return (f"Simulated payment of {screens.msat(amount)}: no money moved" if simulated
                    else f"Paid {screens.msat(amount)} over {body.get('rail')}")
        return {"offer": f"Offered {screens.msat(amount)}",
                "commit": f"Committed to the sale at {screens.msat(amount)}"}.get(action, f"Did: {action}")
    if kind == "outcome":
        return f"Outcome: {body.get('status') or body.get('outcome')}"
    if kind == "close":
        return f"Closed: {body.get('outcome')}"
    return kind


def is_sample(node: gn.Node, deal_id: str) -> bool:
    """Whether this deal is one of the seeded sample deals: the deal's peer is a buyer this node admitted for the
    sample history (the seed's admission reason). A sample deal seals ``lightning`` as its rail but no money moved."""
    admission = node.admission(node.deal(deal_id).peer)
    return bool(admission) and admission.get("reason") == SAMPLE_REASON


def seller_payment(payloads: list[dict], real: bool, sample: bool = False) -> str:
    """A seller's payment line, from its own records: the outcome its own outcome record states (a seller's book
    holds no payment step; the payment is the buyer's act), and on a simulated rail that no money moved. A sample
    deal is said to be sample history made up for the demo, with no money moved, and names no rail. Only a seller's
    page can be of a sample deal: the sample buyer has no window or card, and Maya's book holds only her live deal."""
    first = payloads[0]["body"]
    price, item = first["terms"]["price_minor"], first["terms"]["item"]
    status = next((p["body"].get("status") for p in reversed(payloads) if _kind(p) == "outcome"), None)
    stated = f"{status}, as this seller's own outcome record states it" if status else "not stated in this seller's records"
    line = f"Agreed {screens.msat(price)} for {item}. Payment: {stated}"
    if sample:
        # Sherlock2's wording (#256): the sealed rail is left out, since "lightning" is what made this read as real.
        return f"Sample history: {line} (sample deal made up for this demo: no money moved)."
    if not real:
        return line + " (simulated rail: no money moved)."
    return f"{line} (rail {first['recourse']['rail']}). {screens.seller_credit_note(price)}"


def report_body(node: gn.Node, deal_id: str, *, seller: bool, real: bool, as_of: str, sample: bool = False) -> dict:
    """The keep copy's report, in this demo's own words, from this party's own deal book."""
    book = node.shelf.open(f"deal/{deal_id}")
    records = list(book.records())
    payloads = [json.loads(p) for p in node.deal_payloads(deal_id)]
    simulated = not real
    first = payloads[0]["body"]
    item = first["terms"]["item"]
    steps = [{"capsule_id": r.record_id, "kind": _KIND.get(_kind(p), "other"), "n": i + 1, "at": _at(p),
              "line": _line(_kind(p), p.get("body", {}), simulated)}
             for i, (r, p) in enumerate(zip(records, payloads))]
    acts = [(r, p) for r, p in zip(records, payloads) if _kind(p) == "action"]
    close = next(p for p in reversed(payloads) if _kind(p) == "close")
    did = [{"kind": "act", "at": _at(p), "steps": [r.record_id], "text": _line("action", p["body"], simulated)} for r, p in acts]
    rail_note = "simulated rail: no money moved" if simulated else f"rail {first['recourse']['rail']}"
    if seller:
        money = seller_payment(payloads, real, sample)
    else:
        paid = next((p["body"]["amount_minor"] for _, p in acts if p["body"].get("action") == "pay"), None)
        money = (f"Simulated payment of {screens.msat(paid)} for {item}: no money moved." if simulated and paid is not None
                 else f"Paid {screens.msat(paid)} for {item} ({rail_note})." if paid is not None else "No payment is recorded.")
    body = {
        "audience": AUDIENCE, "deal_id": deal_id, "steps": steps, "did": did,
        "money": {"currency": first["terms"]["currency"], "text": money},
        "lifecycle": {"state": "closed", "as_of": as_of, "later": [], "text": f"Closed: {close['body'].get('outcome')}.",
                      "may_change": "Records sealed on this deal after this receipt was made are not in it; open the page "
                                    "again to see them."},
        "scope": "This receipt covers this one deal, from this party's own records. It is not a record of everything "
                 "the agent did.",
        "told": [], "representations": [], "anomalies": [], "merchant": [], "withheld": [],
        "asked_step": records[0].record_id,
    }
    opening = json.loads(book.opening(records[0].record_id, deal.LOCAL_FIELD).text)
    asked, nonce = opening.get("open", {}).get("asked"), opening.get("nonces", {}).get("verbatim")
    if isinstance(asked, str) and isinstance(nonce, str):
        body["asked"], body["asked_opening"] = asked, {"nonce": nonce, "text": asked}
    return body


def _bundle(node: gn.Node, deal_id: str, extensions: dict | None) -> dict:
    """The deal book as an ``evidence-bundle/v2``, every step disclosed, under the book's newest checkpoint."""
    from agent_action_capsule import bundle as aac

    book = node.shelf.open(f"deal/{deal_id}")
    records = list(book.records())
    disclosures = {r.record_id: {"agent_input": json.loads(p)} for r, p in zip(records, node.deal_payloads(deal_id))}
    try:
        built = aac.build_evidence_bundle(aac.proof_source_from_cll(book._substrate.backend, gn._BookRecords(book)),
                                          root=records[-1].record_id, interval_from=1, disclosures=disclosures,
                                          extensions=extensions)
    except aac.BundleBuildError as exc:
        raise ReceiptError(f"no copy of deal {deal_id}: {exc}") from None
    return built


def _stored(node: gn.Node, deal_id: str) -> Path:
    return node.home / "receipts" / f"{deal_id}.{AUDIENCE}.json"


def keep_copy(node: gn.Node, deal_id: str, *, seller: bool, real: bool, sample: bool = False) -> dict:
    """The party's keep copy of a closed deal: its deal book's bundle carrying its sealed report. The report is sealed
    once per deal checkpoint and kept under the party's home (``receipts/``); a copy at a newer checkpoint seals a new
    one."""
    ready(node, deal_id)
    with node._lock:
        node.shelf.open(f"deal/{deal_id}").checkpoint()  # a checkpoint over every record, as Node.half takes
        plain = _bundle(node, deal_id, None)
        cp = plain["checkpoint"]
        bound = {"log_id": cp["log_id"], "mmr_size": cp["mmr_size"], "root": cp["root"]}
        path = _stored(node, deal_id)
        block = json.loads(path.read_text()) if path.exists() else None
        # The verifier holds the report to this checkpoint and its signed time (capsule-cli#294).
        body = report_body(node, deal_id, seller=seller, real=real, as_of=cp["timestamp"], sample=sample)
        # A report sealed before the demo's words changed is sealed again: the page must not mix old and new words.
        if (block is None or block["agent_input"].get("deal_checkpoint") != bound
                or block["agent_input"]["report"]["lifecycle"]["as_of"] != cp["timestamp"]
                or block["agent_input"]["report"]["money"] != body["money"]):
            payload = rp.report_payload(rp.Report(deal_id, AUDIENCE, secrets.token_hex(32), body,
                                                  checkpoint=rp.Checkpoint(**bound)))
            at = datetime.now(timezone.utc).replace(microsecond=0)
            sealed = produce.seal(produce.SealInput(capsule=deal.emit_input(rp.report_capsule(node.operator, node.developer, at)),
                                                    identity=node._identity, payload=json.loads(payload)))
            record = {**json.loads(sealed.payload), "signature": bytes(sealed.envelope).hex(), "key_id": node.key_id}
            block = {"record": record, "agent_input": json.loads(payload)}
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.write_text(json.dumps(block, sort_keys=True))
        extensions = {"x-deal-v0": {REPORT_POINTER: block["record"]["capsule_id"]}, REPORT_EXTENSION: block}
        if seller:
            extensions["x-deal-seller/v0"] = {}
        return _bundle(node, deal_id, extensions)


def verify(bundle_path: Path) -> dict:
    """What ``capsulectl verify --bundle`` reports for the file (``CAPSULECTL_DEAL``, the binary's path)."""
    binary = os.environ.get("CAPSULECTL_DEAL")
    if not binary:
        raise ReceiptError("set CAPSULECTL_DEAL to the capsulectl-deal binary the run sheet pins: it verifies the copy")
    try:
        run = subprocess.run([binary, "verify", "--bundle", str(bundle_path)], capture_output=True, text=True,
                             stdin=subprocess.DEVNULL, timeout=120)
        output = json.loads(run.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise ReceiptError(f"capsulectl verify --bundle gave no report: {exc}") from None
    if output.get("verdict") != "VALID":
        failed = {k: v.get("findings") for k, v in output.items() if isinstance(v, dict) and v.get("status") == "fail"}
        raise ReceiptError(f"capsulectl verify --bundle says {output.get('verdict')}: {failed}")
    return output


#: The receipt wording this demo gives capsule-viewer's receipt module in place of three of its example lines, each
#: limited to this copy and saying where the proof is (Sherlock2's rulings on #242 and #243, 2026-11-23). The viewer
#: reads a caller's pack (bytes and sha256); nothing else of the page changes.
WITNESS_NONE = "This copy carries no witness receipt."
#: Added only when the History checkpoint the card is anchored on is witnessed and covers every record of this deal
#: (:func:`witnessed_checkpoint`); the stamp itself is on the card, not in this copy (Sherlock2, #242).
WITNESS_ON_CARD = (" The hosted witness stamped the History checkpoint taken at {at} UTC (checkpoint {n}), which covers this deal "
                   "as of that checkpoint; the card shows the newest checkpoint.")
COUNTERSIGN_NONE = "Not countersigned in this copy: the other party's signed half is in their own copy, not this one."
PAYMENT_PROOF = "The payment proof is in the buyer's records, not this copy."


def witnessed_checkpoint(node: gn.Node, deal_id: str) -> tuple[int, str] | None:
    """The tick number and time (UTC, to the second) of the node's newest History checkpoint when a verified witness
    receipt covers it and its extent for this deal's book is the whole book, else ``None``: a record sealed on the deal
    after that tick is not covered. The sentence built from it names the tick, so a page kept past a newer tick still
    says which checkpoint it means."""
    witnessed_tick = getattr(node, "witnessed_tick", None)
    if witnessed_tick is None:
        return None
    with node._lock:
        anchor = node.cadence.standard_history_anchor()
        stamped = witnessed_tick(anchor.tick.n)
        if stamped is None:
            return None
        whole = len(node.shelf.open(f"deal/{deal_id}").records())
    if anchor.extents.get(f"deal/{deal_id}", 0) < whole:
        return None
    return anchor.tick.n, stamped.at.strftime("%Y-%m-%d %H:%M:%S")


def wording_pack(bundle: dict, *, on_card: tuple[int, str] | None = None) -> bytes:
    """The example English wording pack with this demo's lines. On a seller's copy the payment line also carries the
    seller's own sealed ``money.text``, read from the sealed report in the copy and never composed here."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)  # as in render
        from capsule_viewer.receipt import example_wording_pack

    pack = json.loads(example_wording_pack())
    pack["id"] = "evidencebook.receipt-wording.ard/v0"
    pack["entries"].update({"rung.unwitnessed": WITNESS_NONE + (WITNESS_ON_CARD.format(n=on_card[0], at=on_card[1]) if on_card else ""), "countersign.none": COUNTERSIGN_NONE})
    if "x-deal-seller/v0" in bundle["extensions"]:
        sealed = bundle["extensions"][REPORT_EXTENSION]["agent_input"]["report"]["money"]["text"]
        pack["entries"]["seller.payment.not_recorded"] = f"{PAYMENT_PROOF} {sealed}"
    return json.dumps(pack, sort_keys=True).encode()


def render(bundle: dict, output: dict, *, on_card: tuple[int, str] | None = None) -> str:
    """capsule-viewer's receipt page for the keep copy, from what the verifier reported for it."""
    with warnings.catch_warnings():
        # The Python receipt modules are deprecated in favour of the TypeScript build (capsule-viewer#71); this demo
        # uses them until the page is drawn there.
        warnings.simplefilter("ignore", DeprecationWarning)
        from capsule_viewer.composed import composition_from_capsulectl
        from capsule_viewer.receipt import receipt_page
        from capsule_viewer.verifier_report import VerifierReportError, context_from_capsulectl

    try:
        context, assurance = context_from_capsulectl(bundle, output)
        composition = composition_from_capsulectl(bundle, output)
    except VerifierReportError as exc:
        raise ReceiptError(f"the verifier's report does not fit this copy: {exc}") from None
    pack = wording_pack(bundle, on_card=on_card)
    page = receipt_page(context, assurance, pack, hashlib.sha256(pack).hexdigest(), audience=AUDIENCE,
                        composition=composition)
    if "wording-refused" in page:  # a refused pack would draw the page with bare keys
        raise ReceiptError("capsule-viewer refused this demo's receipt wording pack")
    if 'data-level="L0"' not in page:
        raise ReceiptError("capsule-viewer's receipt module declined this copy")
    return page


def sealed_real(node: gn.Node, deal_id: str) -> bool:
    """Whether the deal's own sealed rail is a real one, read from its own sealed terms (``pay.Rail.SEALED``): a deal
    sealed "simulated" stays simulated whatever rail the window was reopened on (Codex, #173). A seeded sample deal seals
    ``lightning`` yet moved no money: see :func:`is_sample`."""
    first = json.loads(node.deal_payloads(deal_id)[0])["body"]
    return first["recourse"]["rail"] != "simulated"


def receipt_page(node: gn.Node, name: str, party: str, deal_id: str, *, rail: str, seller: bool) -> Path:
    """Write the party's receipt page for a closed deal, and return its path. Whether money moved is the
    deal's own sealed rail, not this run's ``rail`` (``ARD_RAIL``)."""
    real = sealed_real(node, deal_id)
    bundle = keep_copy(node, deal_id, seller=seller, real=real, sample=seller and is_sample(node, deal_id))
    bundle_path = pages.home() / "pages" / f"{name}-receipt-{deal_id}.bundle.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(json.dumps(bundle, sort_keys=True))
    # The page is capsule-viewer's own, with nothing added (no banner, and the baseline seals no demo flag, so no
    # DEMO badge): the presenter says "sample history, simulated payment" once at the start (Ethan, 2026-11-17).
    # A seller's page says where the payment proof is and gives the seller's own sealed payment sentence, attributed
    # to the seller and never as verified (Sherlock2, #243, narrowing #173). The buyer's page shows the payment.
    return pages.write(name, "receipt", render(bundle, verify(bundle_path),
                                               on_card=witnessed_checkpoint(node, deal_id)))
