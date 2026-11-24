# SPDX-License-Identifier: Apache-2.0
"""A Goose node whose card counts a deal as *held* when this node checked, at reconcile, that both
closes name the same amount and currency (the claim of ``ec:deal-reconcile@1``, deal profile
``terms-result``).

The Goose reference seals no Result, so every deal on its card is ``undecided``. The Python deal
profile has no Result producer yet, so this node seals its own check as a node-book note
(:data:`RECONCILED`) and hands the card a Result document of the same shape the profile reads
(``claims[].verdict``). The Result is this node's own check, not a signed record of the results
book; the demo says so wherever it shows the card."""
from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from datetime import timedelta
from typing import Any

from agent_action_capsule.canonical import jcs
from evidencebook import Ed25519Signer

import goose_node as gn
from evidencebook import deal

#: A note: this node compared its close with the counterparty's and found them the same (or not).
RECONCILED = "ard_deal_reconciled"

#: The witness the demo names: capsule-anchor at witness.agentactioncapsule.org, run by Action State Group, the
#: default witness of ``capsulectl deal init``. It is the demo operator's own service, so a witnessed card here
#: shows a hosted witness, not one independent of us (coordinator, 2026-11-23). It receives checkpoint hashes only.
#: The key is the one the service publishes at /.well-known/did.json (its Ed25519 ``x``, as hex).
CADENCE_LOG_PREFIX = "goose/cadence"
_LOG_ID_LOCK = threading.Lock()
WITNESS_NAME = "Action State's hosted witness"
WITNESS_DIRECTORY = {"witnesses": [{"name": WITNESS_NAME, "endpoint": "https://witness.agentactioncapsule.org",
                                    "key_ids": ["39bb654c9dc0afe1c0edef0deffaa69099b8518836c9ba26e0491535840f96b5"]}]}


def witnessing() -> bool:
    """True unless ``ARD_WITNESS=off``: a run on a Mac with no network can still run, its card unwitnessed."""
    return os.environ.get("ARD_WITNESS", "public") != "off"


class DemoNode(gn.Node):
    #: The cadence's tick interval: the shortest the profile allows, so a card counts a sale one
    #: minute after the last tick instead of five (the stage waits for the next checkpoint).
    CADENCE_OPTIONS = {"interval": timedelta(minutes=1), "no_jitter": True}

    @classmethod
    def open(cls, home, *, operator: str, **kw):
        """As :meth:`goose_node.Node.open`, with the demo's witness directory unless ``ARD_WITNESS=off``, and a cadence
        log id of this node's own.

        The witness keeps one chain per log id. The Goose reference names every node's cadence log ``goose/cadence``, so
        the demo's nodes (and every earlier run) share one chain there: a node's second checkpoint then names a
        predecessor the witness does not hold as its last and is refused with HTTP 409 ("fork or misordered
        checkpoint"), and the card reads unwitnessed. The id carries the first 16 hex of this node's checkpoint key,
        which is made here if the home is new and never changes after (a reset makes new keys, so a new chain)."""
        if witnessing():
            kw.setdefault("witnesses", WITNESS_DIRECTORY)
        path = Path(home).expanduser()
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        key = Ed25519Signer(gn._key(path / "checkpoint.key")).public_key().hex()
        with _LOG_ID_LOCK:
            was, gn.CADENCE_LOG = gn.CADENCE_LOG, f"{CADENCE_LOG_PREFIX}/{key[:16]}"
            try:
                return super().open(home, operator=operator, **kw)
            finally:
                gn.CADENCE_LOG = was

    def tick(self, now=None):
        """As :meth:`goose_node.Node.tick`; a tick that was cut is then offered to the witness. A witness that cannot
        be reached leaves the tick unwitnessed (``witness_error`` says why) and the card says so; nothing else changes."""
        result = super().tick(now)
        if result.ticked and self.witness_directory is not None:
            self.witness_error = None
            try:
                self._witness_tick(result.tick)
            except Exception as exc:  # the card then reads unwitnessed; never a failed run
                self.witness_error = f"{type(exc).__name__}: {exc}"
                print(f"(the hosted witness gave no receipt for this checkpoint: {self.witness_error}; the card reads unwitnessed)")
        return result

    witness_error: str | None = None

    def _witness_tick(self, tick) -> None:
        from cll.checkpoint.witness import HttpWitnessClient
        from evidencebook.cadence import WitnessReceipt

        endpoint = WITNESS_DIRECTORY["witnesses"][0]["endpoint"]
        got = (self._witness_client or HttpWitnessClient)(endpoint).submit(tick.checkpoint)
        receipt = WitnessReceipt(endpoint, got.entry_hash, bytes(got.bytes), got.leaf_index, got.tree_size)
        with self._lock:
            self.cadence.witnessed(tick.n, receipt)

    def witnessed_tick(self, n: int):
        """The cadence tick ``n`` when a verified witness receipt covers it, else ``None``."""
        with self._lock:
            tick = self.cadence.get(n)
            return tick if tick.witnessed else None

    def _results(self, deal_id: str, extent: int) -> tuple[deal.HistoryResult, ...]:
        """The Results this node holds for ``deal_id`` among its node book's first ``extent`` records."""
        found = []
        for record, statement in self.notes(RECONCILED):
            if record.seq <= extent and statement["deal_id"] == deal_id:
                doc = {"contract": "ec:deal-reconcile@1", "deal_id": deal_id,
                       "claims": [{"claim": "closes name the same amount and currency",
                                   "verdict": "met" if statement["met"] else "not_met"}]}
                found.append(deal.HistoryResult(json.dumps(doc, sort_keys=True).encode(), True))
        return tuple(found)

    def profile_payee(self, peer: str) -> dict:
        """The counterparty block of ``peer`` keyed per profile (``counterparty_profile`` of the ``guard check`` input):
        one seller has the same fingerprint across all this node's deals, so the Everyday Rules recognise a seller paid
        in an earlier deal. The key stays in this node: only the fingerprint leaves."""
        key = deal.profile_key(self._store_secret)
        return {"fp_alg": deal.PROFILE_FP_ALG, "ids": {"payee": deal.fingerprint(key, "payee", peer)}}

    def deal_payloads(self, deal_id: str) -> list[bytes]:
        """The JCS payloads of this node's own deal book, in order."""
        return self._payloads(self.shelf.open(f"deal/{deal_id}"))

    def standard_history(self, tick: int = 0) -> dict:
        """As :meth:`goose_node.Node.standard_history`, with the Results of :meth:`_results`."""
        with self._lock:
            anchor = self.cadence.standard_history_anchor(tick)
            node_extent = anchor.extents.get(gn.NODE_BOOK, 0)
            received = self._halves_received(node_extent)
            deals = []
            for book_id, extent in sorted(anchor.extents.items()):
                if not book_id.startswith("deal/") or book_id.count("/") != 1:
                    continue
                book = self.shelf.open(book_id)
                records = book.records()[:extent]
                payloads = self._payloads(book)[:extent]
                deal_id = book_id[len("deal/"):]
                inputs = deal.HistoryInput(
                    tuple(deal.HistoryRecord(p, gn._parse_time(r.header.committed_at)) for p, r in zip(payloads, records)),
                    self._results(deal_id, node_extent), deal_id in received)
                entry = deal.standard_history_deal(inputs)
                if entry is not None:
                    deals.append(entry)
            as_of = {"anchor": anchor.anchor, "anchor_time": anchor.anchor_time,
                     "first_checkpoint_time": anchor.first_checkpoint_time}
            policy = {"digest": hashlib.sha256(jcs(gn.POLICY)).hexdigest(), "window": gn.POLICY["window"]}
            card = gn.sh.derive_card(holder_kind=gn.HOLDER_KIND, controller_class=gn.sh.CONTROLLER_CLASSES[gn.HOLDER_KIND],
                                     policy=policy, deals=deals, **as_of)
            properties = gn.sh.check_card(card, policy=policy, as_of=as_of, deals=deals)
            if not all(v == "PASS" for v in properties.values()):
                raise gn.Refused(f"the card fails its own inputs: {properties}")
            return {"card": jcs(card).decode(), "tick": anchor.tick.n, "as_of": as_of, "policy": policy,
                    "deals": deals, "properties": properties}
