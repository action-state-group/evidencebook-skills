# SPDX-License-Identifier: Apache-2.0
"""Who is in the demo and what they sell: the facts every process reads, in one place."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

#: What Maya asks for (her words, sealed as each deal's intent).
ASK = "I need 200 conference badges by Friday, under 3,000 msat."

#: Each seller's own file (``sellers/<name>.yaml``, #299): its label, its offer and what it discloses to a buyer.
SELLERS_DIR = Path(__file__).resolve().parent / "sellers"
#: What each seller's own delivery record says when it ships: the run's story, not a term the seller offers. Kestrel ships
#: 150 of the 200 badges, and its own delivery record says so: the dispute in deal 1 rests on that record.
SHIPS = {"alder": ("delivered:badges_200_of_200", "200 of 200 badges"),
         "kestrel": ("partial:badges_150_of_200", "150 of 200 badges")}
#: What a seller's own delivery record states on the delivered row, beside its words (Sherlock2, 2026-11-25, buzz 4ec88700):
#: Kestrel states its delivery not met, so the adjudicator rules on Kestrel's own signed word, without a person
#: (evidencebook ``xdealv1.DecideCase``; evidencebook-skills#416). Alder states its rows in a statement of its own.
STATES = {"kestrel": {"delivered": "not_met"}}
DISCLOSES = ("subjects", "derivations", "human_gated", "answers_within")


#: A product id: what the stage's catalog route serves (``stage.CATALOG_PATH``).
PRODUCT_ID = re.compile(r"[a-z0-9-]+")
#: The catalog stand-in (evidencebook-skills#382): each seller's products, their titles and prices.
CATALOG = Path(__file__).resolve().parent / "catalog.yaml"


def catalog(path: Path = CATALOG) -> dict[str, dict[str, dict]]:
    """``{seller: {product id: {title, price_msat}}}``, refused unless every product has a title and a price > 0."""
    c = yaml.safe_load(path.read_text()) or {}
    products = c.get("products") if isinstance(c, dict) else None
    try:
        ok = isinstance(c, dict) and set(c) == {"products"} and isinstance(products, dict) and all(
            isinstance(items, dict) and items and all(
                isinstance(pid, str) and PRODUCT_ID.fullmatch(pid) is not None and isinstance(p, dict) and set(p) == {"title", "price_msat"}
                and isinstance(p["title"], str) and p["title"] and type(p["price_msat"]) is int and p["price_msat"] > 0
                for pid, p in items.items())
            for items in products.values())
    except TypeError:
        ok = False
    if not ok:
        raise ValueError(f"{path}: needs products: <seller>: <product id (a-z, 0-9, -)>: title and price_msat > 0, only")
    return products


def seller_file(name: str, products: dict[str, dict[str, dict]] | None = None) -> dict:
    """One seller's file, refused unless it has exactly the members the commitment and the ARD entry read; its offer's
    title and price come from the catalog stand-in, by the product id the file names."""
    f = SELLERS_DIR / f"{name}.yaml"
    s = yaml.safe_load(f.read_text())
    products = catalog() if products is None else products
    try:
        offer, discloses = s["offer"], s["discloses"]
        ok = (set(s) == {"label", "offer", "discloses"} and set(offer) == {"product"} and isinstance(offer["product"], str)
              and set(discloses) == set(DISCLOSES) and isinstance(s["label"], str)
              and type(discloses["human_gated"]) is bool and isinstance(discloses["answers_within"], str)
              and all(isinstance(v, list) and v and all(isinstance(x, str) for x in v)
                      for v in (discloses["subjects"], discloses["derivations"])))
    except (TypeError, KeyError):
        ok = False
    if not ok:
        raise ValueError(f"{f}: needs label, offer (product) and discloses ({', '.join(DISCLOSES)}) only")
    if "history_card/2" not in discloses["derivations"]:
        # the signed disclosure policy and the card stapled to the commitment are always history_card/2 (evidencebook
        # commitment.POLICY and build): a list without it would contradict them
        raise ValueError(f"{f}: discloses.derivations keeps history_card/2, the card the commitment staples")
    listed = products.get(name, {}).get(offer["product"])
    if listed is None:
        raise ValueError(f"{f}: offers product {offer['product']!r}, which {CATALOG.name} does not list for {name}")
    return {"label": s["label"], "product": offer["product"], "item": listed["title"], "price_msat": listed["price_msat"],
            "discloses": discloses}


SELLERS = {n: {**seller_file(n), "observed": observed, "shipped": shipped, "states": STATES.get(n, {})}
           for n, (observed, shipped) in SHIPS.items()}
#: Each seller's sample history, made by ``demo.py seed`` (evidencebook-skills#317, Steven's ruling via Sherlock2):
#: different depths, so the cards give a choice. Kestrel keeps 10, the demo pack's band-history minimum (k=10 from
#: tier T1: pack-source.yaml ``band-history``); fewer would make it LIMIT before deal 1. Alder's count is the most that keeps
#: the seed near a minute.
SAMPLE_DEALS = {"alder": 15, "kestrel": 10}
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
