# SPDX-License-Identifier: Apache-2.0
"""Who is in the demo and what they sell: the facts every process reads, in one place."""
from __future__ import annotations

ITEM = "200 conference badges, delivered by Friday"
#: What Maya asks for (her words, sealed as each deal's intent).
ASK = "I need 200 conference badges by Friday, under 3,000 msat."
BUDGET_MSAT = 3000

#: Each seller's listed price and what its own delivery record says when it ships. Kestrel ships 150 of the 200
#: badges, and its own delivery record says so: the dispute in deal 1 rests on that record.
SELLERS = {
    "alder": {"label": "Alder Print Co.", "price_msat": 2000, "item": ITEM, "observed": "delivered:badges_200_of_200",
              "shipped": "200 of 200 badges"},
    "kestrel": {"label": "Kestrel Print", "price_msat": 1000, "item": ITEM, "observed": "partial:badges_150_of_200",
                "shipped": "150 of 200 badges"},
}
DEALS_EACH = 12
BUYER = "maya"
SAMPLE_BUYER = "sample-buyer"


def sample_buyer(seller: str) -> str:
    """The sample buyer of one seller's sample history: one per seller, so both histories are made at once (one buyer's
    store takes one deal step at a time) and each store stays small."""
    return f"{SAMPLE_BUYER}-{seller}"
ADJUDICATOR = "adjudicator"
#: The file in the demo home that says when the sample deals can first count as held (seconds since the epoch): the start
#: of the first minute after their contest windows end (a stamp's time is cut to the minute).
HELD_FROM = "sample-held-from"


def label(name: str) -> str:
    return {**{k: v["label"] for k, v in SELLERS.items()}, BUYER: "Maya", ADJUDICATOR: "the adjudicator"}.get(name, name)
