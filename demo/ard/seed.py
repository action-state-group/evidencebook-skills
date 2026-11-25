# SPDX-License-Identifier: Apache-2.0
"""The sample history, made before the demo: 24 deals between each seller and the sample buyer, each a real x-deal-v1
deal made with capsulectl-deal (offer, admission, intent, agreement, payment legs, delivery, both sides' statements),
naming the demo's adjudicator and Action State's witness like every live deal. No money moves: the payment reference is
a made-up sample one. Every deal holds.

A /3 card counts a deal as held only once its rows are agreed after their contest window (AAC standard-history §11.3),
and capsulectl takes no other clock than the real one. Every sample deal is due, and its window ends, :data:`MAKE_S`
seconds after the seed starts. A statement counts only if its first stamp is inside the window (dealprofile/xdealv1
``carriedStatements``), so each party stamps on demand (``deal tick --now``) once its deals are made, and the seed is done.
A stamp's time is cut to the minute (evidencebook ``shelf_stamp.go``), so a card counts the deals held from the first
stamp in a later minute than the window's end, which each seller's agent takes as it starts (by then almost always
due). The seed is set-up, run before anyone watches."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

import adjudicator as adj
import flow
import party as pt
from cast import DEALS_EACH, HELD_FROM, ITEM, SELLERS, sample_buyer

#: Every sample deal is due, and its contest window ends, this many seconds after the seed starts: room to make all of
#: them and have the witness take their stamp, on a slow witness too. The seed itself ends as soon as the stamps are
#: taken; the cards count the deals held from the first minute after this.
MAKE_S = 90
#: The sample buyer's answer to its own payment check: the demo operator's, for the sample buyer it runs.
SAMPLE_APPROVAL = "Sample deal: the operator approves this payment for the sample buyer it runs. No money moves."


def parties(home: Path) -> dict[str, pt.Party]:
    """Every party's profile, made once: Maya (a person), the sellers and the sample buyer (whose processes act on their
    own, so their checks pin ``builtin:neutral`` materiality), and the adjudicator's key."""
    adj.Adjudicator(home).create()
    out = {"maya": pt.Party(home, "maya").create("person")}
    for name in SELLERS:
        # Made without the witness: each sample deal's agree stamps on its own (capsulectl deal_v1_agree.go), and with a
        # witness every such stamp is one more delivery, one after another, on the seed's path. The seller names the
        # witness once its deals are made (Party.add_witness), so one stamp covering them all is the one it sees.
        # The sample buyers never need it: only the sellers' cards are read.
        out[name] = pt.Party(home, name).create("node", neutral=True, witness=False)
        out[sample_buyer(name)] = pt.Party(home, sample_buyer(name)).create("person", neutral=True, witness=False)
    return out


def sample_deal(buyer: pt.Party, seller: pt.Party, price_msat: int, adjudicator: dict, window_end: float) -> str:
    """One sample deal, both sides run here, handing each other the files each verb writes. Its rows are due, and their
    window ends, at ``window_end`` (a ``time.time()``)."""
    decision = flow.seller_decision(price_msat)
    left = max(1, int(window_end - time.time()))
    o = buyer.offer(seller.key_id, ITEM, price_msat, decision["pack"]["digest"], adjudicator, due_s=left, window_s=left)
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


def not_held(p: pt.Party) -> str:
    """What a seller's own card says of each deal it does not count as held, and its checkpoint state: shown when the
    seed gives up, so the cause shows where it failed (a CI runner, say)."""
    try:
        state = p.tick()
        doc = json.loads(p.card_bundle(shared=False).read_text())
        sh = doc["extensions"]["x-standard-history/v0"]
        rows = [d for d in sh["deals"] if not all(r.get("status") == "agreed" for r in d.get("rows", []))]
        lines = [f"{p.name}: card as of {sh['as_of'].get('anchor_time')}, tick {json.dumps(state)[:300]}"]
        lines += [f"  {d['deal'][:12]} agreed {d.get('agreed_at')} happened {d.get('happened')} rows "
                  + ", ".join(f"{r.get('owed_by')}:{r.get('status')}/{r.get('value')}" for r in d.get("rows", []))
                  for d in rows[:30]]
        return "\n".join(lines)
    except Exception as exc:  # a report of the failure must not hide it
        return f"{p.name}: could not read its own card: {exc}"


def seed(home: Path, say: Callable[[str], None] = print) -> None:
    """Make the sample deals each seller lacks, then wait for the checkpoint that stamps each party's last one. A repeat
    run finishes an interrupted one; a run cut off in the middle of a deal needs ``demo.py reset`` first."""
    home = Path(home).expanduser()
    ps = parties(home)
    named = adj.Adjudicator(home).named()
    errors: list[str] = []

    for name in SELLERS:  # a home a run has used is not seeded again: its cards count live deals and rulings
        try:
            card, _, _ = flow.read_card(ps[name].card_bundle(shared=True))
        except pt.Refused:
            continue
        if card["outcomes"]["did_not_hold"] or card["disputes"]["received"]["of"] or card["outcomes"]["of"] > DEALS_EACH:
            raise SystemExit(f"{name}'s card already counts deals of a run ({card['outcomes']['of']} deals, "
                             f"{card['disputes']['received']['of']} disputes): run `demo.py reset`, then `demo.py seed`")

    started, window_end = time.monotonic(), time.time() + MAKE_S

    def run(name: str) -> None:
        seller, buyer, price = ps[name], ps[sample_buyer(name)], SELLERS[name]["price_msat"]
        have = sum(1 for d in seller.deals() if d.get("version") == "x-deal-v1" and d.get("counterparty_key") == buyer.key_id)
        for i in range(have, DEALS_EACH):
            try:
                sample_deal(buyer, seller, price, named, window_end)
            except Exception as exc:
                errors.append(f"{name}: sample deal {i + 1}: {exc}")
                return
        # One witnessed stamp times every statement of these deals. A statement's time is when the witness received the
        # stamp that covers it, so it must reach the witness before the window ends; one the witness did not take (it
        # answers slowly or with an error under load) is taken again. The sample buyer stamps nothing: the seller's stamp
        # covers the buyer's statements it holds.
        seller.add_witness()
        while True:
            try:
                got = seller.stamp()
            except pt.Refused as exc:
                got = {"error": str(exc)}
            if pt.taken(got):
                return
            if time.time() > window_end - 5:
                errors.append(f"{name}: its sample deals were not stamped by the witness within their window ({MAKE_S} s): "
                              f"{json.dumps(got)[:300]}")
                return
            time.sleep(1)

    say(f"making {DEALS_EACH} sample deals for each seller")
    threads = [threading.Thread(target=run, args=(n,)) for n in SELLERS]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if errors:
        raise SystemExit("seed stopped: " + "; ".join(errors) + ": run `demo.py reset`, then `demo.py seed` again")
    (home / HELD_FROM).write_text(str(_floor_minute(window_end) + 60))
    say(f"sample history made and stamped in {time.monotonic() - started:.0f} s. Each card counts it held from "
        f"{datetime.fromtimestamp(_floor_minute(window_end) + 60).strftime('%H:%M:%S')}, the first stamp after the "
        "windows end, which each seller's agent takes as it starts")
    for p in ps.values():
        p.close()


def _floor_minute(at: float) -> int:
    """The start of the minute ``at`` falls in: a stamp's time (evidencebook ``shelf_stamp.go``, cut to the minute)."""
    return int(at) // 60 * 60
