# SPDX-License-Identifier: Apache-2.0
"""The sample history, made before the demo: 24 deals between each seller and the sample buyer, each a real x-deal-v1
deal made with capsulectl-deal (offer, admission, intent, agreement, payment legs, delivery, both sides' statements),
naming the demo's adjudicator and Action State's witness like every live deal. No money moves: the payment reference is
a made-up sample one. Every deal holds.

A /3 card counts a deal as held only once its rows are agreed after their contest window (AAC standard-history §11.3),
and capsulectl takes no other clock than the real one, so each sample deal's rows are due two minutes and contested up
to five minutes after its offer; ``seed`` waits for the last window to end and for a checkpoint, then checks that each
seller's own card counts 24 deals held before it says done (about eight minutes in all)."""
from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path
from typing import Callable

import adjudicator as adj
import flow
import party as pt
from cast import DEALS_EACH, ITEM, SAMPLE_BUYER, SELLERS

#: A row's statements count only when their time (the witnessed checkpoint that covers them, up to a minute or two
#: after they are sealed) falls inside the contest window, so the window leaves room for that.
SAMPLE_DUE_S, SAMPLE_WINDOW_S = 120, 300
#: The longest wait, after the windows end, for every seller's card to count all its deals held (a few checkpoints).
HELD_WAIT_S = 600
#: The sample buyer's answer to its own payment check: the demo operator's, for the sample buyer it runs.
SAMPLE_APPROVAL = "Sample deal: the operator approves this payment for the sample buyer it runs. No money moves."


def parties(home: Path) -> dict[str, pt.Party]:
    """Every party's profile, made once: Maya (a person), the sellers and the sample buyer (whose processes act on their
    own, so their checks pin ``builtin:neutral`` materiality), and the adjudicator's key."""
    adj.Adjudicator(home).create()
    out = {"maya": pt.Party(home, "maya").create("person")}
    for name in (*SELLERS, SAMPLE_BUYER):
        out[name] = pt.Party(home, name).create("node" if name in SELLERS else "person", neutral=True)
    return out


def sample_deal(buyer: pt.Party, seller: pt.Party, price_msat: int, adjudicator: dict) -> str:
    """One sample deal, both sides run here, handing each other the files each verb writes."""
    decision = flow.seller_decision(price_msat)
    o = buyer.offer(seller.key_id, ITEM, price_msat, decision["pack"]["digest"], adjudicator,
                    due_s=SAMPLE_DUE_S, window_s=SAMPLE_WINDOW_S)
    deal_id = o["deal_id"]
    seller.receive(o["file"])
    seller.admit(deal_id, decision)
    seller.intent(deal_id, "sell at the listed price (sample deal)", "service", ["commit"], None, "the buyer")
    buyer.receive(seller.agree(o["offer"])["file"])
    buyer.admit(deal_id, decision)
    intent = buyer.intent(deal_id, "sample deal", "purchase", ["pay"], price_msat, "the seller")
    seller.receive(buyer.agree(o["offer"], intent)["file"])
    ref = hashlib.sha256(f"sample payment, no money moved: {deal_id}".encode()).hexdigest()
    check = buyer.check(deal_id, "pay", ITEM, price_msat, "the seller", {"amount_minor": price_msat, "payment_ref": ref})
    if not check.get("proceed"):
        # A payment pauses for a person whatever the materiality predicate says. The sample buyer is the demo
        # operator's own stand-in, so its answer is the operator's, in words that say so.
        buyer.approve(deal_id, check, "proceed", SAMPLE_APPROVAL)
    seller.receive(buyer.pay_leg(deal_id, check["check_id"]))
    buyer.receive(seller.received_leg(deal_id, price_msat, ref))
    commit = seller.check(deal_id, "commit", ITEM, price_msat, "the buyer")
    if not commit.get("proceed"):
        raise pt.Refused(f"the seller's delivery check paused: {commit.get('verdict')}")
    buyer.receive(seller.perform(deal_id, commit["check_id"], "delivered:badges_200_of_200"))
    met = {pt.PAID: "met", pt.DELIVERED: "met"}
    buyer.receive(seller.statement(deal_id, met))
    seller.receive(buyer.statement(deal_id, met))
    return deal_id


def held(p: pt.Party) -> tuple[int, int]:
    """The deals the party's own card counts, and how many of them held."""
    card, _, _ = flow.read_card(p.card_bundle(shared=True))
    return card["outcomes"]["of"], card["outcomes"]["held"]


def seed(home: Path, say: Callable[[str], None] = print) -> None:
    """Make the sample deals each seller lacks, then wait until each seller's card counts them all as held. A repeat
    run finishes an interrupted one; a run cut off in the middle of a deal needs ``demo.py reset`` first."""
    home = Path(home).expanduser()
    ps = parties(home)
    named = adj.Adjudicator(home).named()
    buyer = ps[SAMPLE_BUYER]
    errors: list[str] = []

    for name in SELLERS:  # a home a run has used is not seeded again: its cards count live deals and rulings
        try:
            card, _, _ = flow.read_card(ps[name].card_bundle(shared=True))
        except pt.Refused:
            continue
        if card["outcomes"]["did_not_hold"] or card["disputes"]["received"]["of"] or card["outcomes"]["of"] > DEALS_EACH:
            raise SystemExit(f"{name}'s card already counts deals of a run ({card['outcomes']['of']} deals, "
                             f"{card['disputes']['received']['of']} disputes): run `demo.py reset`, then `demo.py seed`")

    def run(name: str) -> None:
        seller, price = ps[name], SELLERS[name]["price_msat"]
        have = sum(1 for d in seller.deals() if d.get("version") == "x-deal-v1" and d.get("counterparty_key") == buyer.key_id)
        for i in range(have, DEALS_EACH):
            try:
                sample_deal(buyer, seller, price, named)
            except Exception as exc:
                errors.append(f"{name}: sample deal {i + 1}: {exc}")
                return
            if (i + 1) % 12 == 0:
                say(f"{name}: {i + 1}/{DEALS_EACH} sample deals")

    threads = [threading.Thread(target=run, args=(n,)) for n in SELLERS]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if errors:
        raise SystemExit("seed stopped: " + "; ".join(errors))
    say(f"waiting for the sample deals' contest windows to end ({SAMPLE_WINDOW_S // 60} minutes) and for a checkpoint")
    stop_at = time.monotonic() + SAMPLE_WINDOW_S + 2
    while time.monotonic() < stop_at:  # keep checkpoints coming, so every statement gets its witnessed time
        for p in (*[ps[n] for n in SELLERS], buyer):
            p.tick()
        time.sleep(15)
    # A deal counts as held once a witnessed checkpoint after its window's end covers it, so every party keeps
    # checkpointing until every seller's card counts all its deals held. All sellers are waited on together: waiting on
    # one at a time starved the next of checkpoints, and on a slow CI runner Kestrel, waited on second, ran out of time
    # at 18 of 24 (evidencebook-skills#288, CI at 10ac5bb). Ends as soon as all are held.
    stop = time.monotonic() + HELD_WAIT_S
    done: set[str] = set()
    counts: dict[str, tuple[int, int]] = {}
    while True:
        for p in (*[ps[n] for n in SELLERS if n not in done], buyer):
            p.tick()
        for name in SELLERS:
            if name in done:
                continue
            try:
                counts[name] = held(ps[name])
            except pt.Refused:
                counts[name] = (0, 0)
            if counts[name] == (DEALS_EACH, DEALS_EACH):
                done.add(name)
                say(f"{name}: {DEALS_EACH} deals, all held")
        if done == set(SELLERS):
            break
        if time.monotonic() > stop:
            left = "; ".join(f"{n}'s card counts {counts[n][1]} of {counts[n][0]} deals held" for n in SELLERS if n not in done)
            raise SystemExit(f"{left} after {HELD_WAIT_S // 60} minutes: check the network (the witness) and run "
                             "`demo.py seed` again")
        time.sleep(10)
    for p in ps.values():
        p.close()
