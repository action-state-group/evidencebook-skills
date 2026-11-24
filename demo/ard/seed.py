# SPDX-License-Identifier: Apache-2.0
"""The sample history, run before the demo (design §7): 24 deals between each seller and the sample
buyer, real seals at real times, a synthetic payment reference labelled sample, no money moved."""
from __future__ import annotations

from datetime import datetime, timezone

import deals
from world import CURRENCY, DEALS_EACH, ITEM, RAIL, SAMPLE_COUNTS, SELLERS, World
from world import terms as world_terms


#: Kestrel deals that carry the owner's outcome_note: the same count as its hand-written sample card.
SENTINEL_DEALS = SAMPLE_COUNTS["kestrel"]


_deal_ids = deals.deal_ids


def seed(world: World, say=print, kestrel_card: str = "sample") -> None:
    """Run the sample deals each seller lacks, then (sentinel mode) the owner's note on two of Kestrel's
    first deals, then a checkpoint. Each part is checked on its own, so a repeat run finishes an
    interrupted one; a run cut off in the middle of a deal needs ``demo.py reset`` first."""
    buyer = world.nodes["sample-buyer"]
    for name, seller in SELLERS.items():
        node = world.nodes[name]
        have = len(_deal_ids(node))
        if have:  # a home seeded at another price would assess this seller in the wrong band: start over instead
            made, _ = deals._agreed(node.deal_payloads(_deal_ids(node)[0]))
            if made != seller["price_msat"]:
                raise SystemExit(f"{name}'s sample history was made at {made:,} msat, but {name} now sells at "
                                 f"{seller['price_msat']:,} msat: run `demo.py reset`, then `demo.py seed`")
        if have >= DEALS_EACH:
            say(f"{name}: sample history already there ({have} deals)")
        else:
            if have == 0:
                deals.admit(buyer, node, reason=deals.SAMPLE_REASON)
                deals.admit(node, buyer, reason=deals.SAMPLE_REASON)
            terms = world_terms(ITEM, seller["price_msat"], CURRENCY, RAIL)
            for i in range(have, DEALS_EACH):
                deals.run_deal(buyer, node, terms, "sample deal", deals.SAMPLE_PAYMENT)
                if (i + 1) % 12 == 0:
                    say(f"{name}: {i + 1}/{DEALS_EACH} sample deals")
        if name == "kestrel" and kestrel_card == "sentinel":
            try:
                for deal_id in _deal_ids(node)[:SENTINEL_DEALS]:
                    if not deals.noted(node, deal_id):
                        deals.note_did_not_hold(node, deal_id, "other")
            except Exception as exc:
                raise SystemExit(f"sentinel mode needs an evidencebook with the outcome_note record "
                                 f"(evidencebook#464): {exc}") from None
            say(f"{name}: {SENTINEL_DEALS} deals carry the owner's own outcome_note (sample)")
        node.tick(datetime.now(timezone.utc))
        buyer.tick(datetime.now(timezone.utc))
