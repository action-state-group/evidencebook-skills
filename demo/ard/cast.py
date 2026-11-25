# SPDX-License-Identifier: Apache-2.0
"""Who is in the demo and what they sell: the facts every process reads, in one place."""
from __future__ import annotations

from pathlib import Path

import yaml

#: What Maya asks for (her words, sealed as each deal's intent).
ASK = "I need 200 conference badges by Friday, under 3,000 msat."
BUDGET_MSAT = 3000

#: Each seller's own file (``sellers/<name>.yaml``, #299): its label, its offer and what it discloses to a buyer.
SELLERS_DIR = Path(__file__).resolve().parent / "sellers"
#: What each seller's own delivery record says when it ships: the run's story, not a term the seller offers. Kestrel ships
#: 150 of the 200 badges, and its own delivery record says so: the dispute in deal 1 rests on that record.
SHIPS = {"alder": ("delivered:badges_200_of_200", "200 of 200 badges"),
         "kestrel": ("partial:badges_150_of_200", "150 of 200 badges")}
DISCLOSES = ("subjects", "derivations", "human_gated", "answers_within")


def seller_file(name: str) -> dict:
    """One seller's file, refused unless it has exactly the members the commitment and the ARD entry read."""
    f = SELLERS_DIR / f"{name}.yaml"
    s = yaml.safe_load(f.read_text())
    try:
        offer, discloses = s["offer"], s["discloses"]
        ok = (set(s) == {"label", "offer", "discloses"} and set(offer) == {"item", "price_msat"}
              and set(discloses) == set(DISCLOSES) and isinstance(s["label"], str) and isinstance(offer["item"], str)
              and type(offer["price_msat"]) is int and offer["price_msat"] > 0
              and type(discloses["human_gated"]) is bool and isinstance(discloses["answers_within"], str)
              and all(isinstance(v, list) and v and all(isinstance(x, str) for x in v)
                      for v in (discloses["subjects"], discloses["derivations"])))
    except (TypeError, KeyError):
        ok = False
    if not ok:
        raise ValueError(f"{f}: needs label, offer (item, price_msat > 0) and discloses ({', '.join(DISCLOSES)}) only")
    if "history_card/2" not in discloses["derivations"]:
        # the signed disclosure policy and the card stapled to the commitment are always history_card/2 (evidencebook
        # commitment.POLICY and build): a list without it would contradict them
        raise ValueError(f"{f}: discloses.derivations keeps history_card/2, the card the commitment staples")
    return {"label": s["label"], "item": offer["item"], "price_msat": offer["price_msat"], "discloses": discloses}


SELLERS = {n: {**seller_file(n), "observed": observed, "shipped": shipped} for n, (observed, shipped) in SHIPS.items()}
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
