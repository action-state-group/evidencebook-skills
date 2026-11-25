# SPDX-License-Identifier: Apache-2.0
"""The whole story, end to end, with the real binaries: capsulectl-deal (``CAPSULECTL_DEAL``), capsule-engine
(``CAPSULE_ENGINE``), ledger-cloud's adjudicator (``ARD_ADJUDICATOR_BIN``) and Action State's hosted witness, which
every agreement names. It seeds a home (about eight minutes: the sample deals' contest windows must end), then runs
deal 1 (Maya buys from Kestrel, Kestrel's own delivery record says 150 of 200, Maya disputes, the adjudicator rules
against Kestrel, both enter the ruling) and deal 2 (Kestrel's card counts the lost dispute; Maya's own ruling makes it
NO; a buyer who holds no ruling sees LIMIT from the card alone; Alder is GO and paid).

It needs the network and runs only with ``ARD_E2E=1`` (CI's ard-demo job sets it). The approval dialogs are answered in
the test, as ``demo.py run --auto`` does: never on a real rail."""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("ARD_E2E") != "1" or not all(
    os.environ.get(v) for v in ("CAPSULECTL_DEAL", "CAPSULE_ENGINE", "ARD_ADJUDICATOR_BIN", "ARD_EVIDENCEBOOK")),
    reason="ARD_E2E=1 with CAPSULECTL_DEAL, CAPSULE_ENGINE, ARD_ADJUDICATOR_BIN and ARD_EVIDENCEBOOK set")


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    os.environ["ARD_WITNESS"] = "public"
    os.environ.setdefault("ARD_STAGE_PORT", "47681")
    import adjudicator as adj
    import ard
    import flow
    import pack as packs
    import party as pt
    import seed
    import stage
    from cast import SELLERS

    home = tmp_path_factory.mktemp("ard-e2e")
    seed.seed(home, say=lambda *_: None)
    st = stage.Stage(home)
    agents = {n: flow.SellerAgent(home, n) for n in SELLERS}
    entries = ard.lookup(stage.REGISTRY_URL, stage.ORIGINS, stage.QUERY)
    w = {"home": home, "stage": st, "agents": agents, "maya": pt.Party(home, "maya"), "adj": adj.Adjudicator(home),
         "pack": packs.starting(), "entries": entries, "keys": {e["id"]: e["commitment"]["key_id"] for e in entries}}
    yield w
    for a in agents.values():
        a.stop()
    st.close()


def _assess(w, buyer_party):
    import buyer

    out = {}
    for e in w["entries"]:
        ev = buyer.gather(w["home"], buyer_party, e)
        out[e["id"]] = (ev, buyer.assess(buyer_party, ev, w["keys"][e["id"]], e["offer"]["price_msat"], w["pack"]))
    return out


def _buy(w, key, a, who=None):
    import buyer
    import pay

    who = who or w["maya"]
    rail = pay.FakeRail()
    deal = buyer.open_deal(w["home"], who, key, w["keys"][key], a, w["adj"].named(), lambda *_: None, rail=rail.SEALED,
                           me=who.name)
    inv = rail.invoice(a.price_msat)
    check = buyer.check_payment(who, deal, inv.payment_hash)
    if not check.get("proceed"):
        who.approve(deal.deal_id, check, "proceed", "Pay (test)\nAnswer: Pay")
    payment = rail.pay_invoice(inv)
    buyer.pay(w["home"], who, deal, check, payment.reference, simulated=True)
    return deal, buyer.shipped(buyer.await_delivery(w["home"], who, deal))


def _until(pred, seconds, step=3):
    stop = time.time() + seconds
    while time.time() < stop:
        got = pred()
        if got:
            return got
        time.sleep(step)
    return pred()


def test_two_deals_a_ruled_dispute_limits_the_seller_in_deal_2(world):
    import buyer
    import flow
    import party as pt
    import screens

    w = world
    # deal 1: both clean, both GO
    made = _assess(w, w["maya"])
    for key, (ev, a) in made.items():
        assert ev.card["outcomes"] == {"of": 24, "held": 24, "did_not_hold": 0, "undecided": 0}, key
        assert a.verdict == "GO", (key, a.reasons)
    deal, shipped = _buy(w, "kestrel", made["kestrel"][1])
    assert shipped == "150 of 200 badges"

    # the dispute, the case with both books, the ruling
    buyer.dispute(w["home"], w["maya"], deal, lambda *_: None)
    case = _until(lambda: next((c for c in w["adj"].cases() if c["deal_id"] == deal.deal_id and len(c["copies"]) >= 2),
                               None), 300)
    names = {w["maya"].key_id: "Maya", w["keys"]["kestrel"]: "Kestrel Print"}
    view = flow.case_view(case, names)
    assert {b["side"] for b in view.books} == {"buyer", "seller"}
    assert "Kestrel Print's own signed delivery record: partial:badges_150_of_200" in view.deciding
    r = w["adj"].rule(view.case, view.dispute, view.copies, view.row, "not_met", "seller")
    assert r["sealed"]
    w["adj"].witness()

    # each side enters it in its own records and sends its book; the entry check reads both
    _until(lambda: (flow.enter_rulings(w["home"], w["maya"], "kestrel", lambda *_: None) or True)
           and w["maya"].notes(flow.BOOK_SENT), 300)
    _until(lambda: w["agents"]["kestrel"].party.notes(flow.BOOK_SENT), 300)
    assert {x["words"] for x in w["adj"].entry(view.case, r["ruling"])} == {"entered"}

    # Kestrel's own card counts it after its next checkpoint
    def kestrel_card():
        w["agents"]["kestrel"].republish()
        c, _, _ = flow.read_card(w["home"] / "stage" / "cards" / "kestrel.json")
        return c if c["disputes"]["received"]["by_outcome"]["against"] else None
    card = _until(kestrel_card, 180, step=5)
    assert card["outcomes"]["did_not_hold"] == 1 and flow.decided(card)["decided"] == {"against": 1, "of": 1}

    # deal 2: Maya's own ruling makes Kestrel NO, and the card's count shows with it
    made = _assess(w, w["maya"])
    ev, a = made["kestrel"]
    assert a.verdict == "NO" and "adverse-adjudication" in a.reasons and "disputes-against" in a.reasons
    line = screens.decision_line(a, ev)
    assert line.startswith("NO: you hold a ruling against this seller") and "the card does not say which deal" in line
    assert made["alder"][1].verdict == "GO"

    # a buyer who holds no ruling: LIMIT from the card alone (Steven's #280 rule)
    second = pt.Party(w["home"], "second-buyer").create("person")
    ev2, a2 = _assess(w, second)["kestrel"]
    assert a2.verdict == "LIMIT" and a2.reasons == ["disputes-against"], a2.reasons
    assert screens.decision_line(a2, ev2).startswith("LIMIT: a dispute about this seller was decided against it (1 of 1")

    # Alder is paid, delivers all 200, and Maya says she received it
    deal2, shipped2 = _buy(w, "alder", made["alder"][1])
    assert shipped2 == "200 of 200 badges"
    buyer.close_received(w["home"], w["maya"], deal2)


def test_a_seller_that_sends_no_book_cannot_be_ruled_against_yet(world):
    """A second buyer buys from Alder; Alder's agent stops before it answers the dispute. The case holds the buyer's
    copy only, which does not carry Alder's own delivery record (four books need evidencebook#861 PR 2), so the
    adjudicator's window refuses a ruling against Alder from it."""
    import buyer
    import flow
    import party as pt

    w = world
    second = pt.Party(w["home"], "second-buyer").create("person")
    ev, a = _assess(w, second)["alder"]
    assert a.verdict == "GO"
    deal, shipped = _buy(w, "alder", a, second)
    assert shipped == "200 of 200 badges"
    w["agents"]["alder"].stop()  # silent from here on
    buyer.dispute(w["home"], second, deal, lambda *_: None)
    time.sleep(90)  # longer than a seller's checkpoint wait: it would have sent its copy by now
    case = next(c for c in w["adj"].cases() if c["deal_id"] == deal.deal_id)
    view = flow.case_view(case, {second.key_id: "the second buyer", w["keys"]["alder"]: "Alder Print Co."})
    assert {b["side"] for b in view.books} == {"buyer"}
    assert not [d for d in view.deciding if "delivery record" in d]


def test_a_checkpoint_the_witness_did_not_get_is_delivered_by_a_later_tick_after_a_re_entry(world, monkeypatch):
    """evidencebook-skills#287: a checkpoint whose delivery failed (here, a proxy that answers nothing) stays pending, and
    the next tick, run by a new process on the same home as a reopened window does, is accepted by the witness and
    leaves nothing pending (capsulectl delivers the newest checkpoint, which extends the last one the witness took)."""
    import party as pt

    w = world
    p = pt.Party(w["home"], "kestrel")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")  # nothing listens: the delivery fails
    failed = _until(lambda: (lambda t: t if t.get("state") == "ticked" else None)(p.tick()), 120, step=5)
    assert failed["pending"], failed
    monkeypatch.delenv("HTTPS_PROXY")
    again = pt.Party(w["home"], "kestrel")  # a reopened window: a new object, each verb a new process
    done = _until(lambda: (lambda t: t if t.get("state") == "ticked" else None)(again.tick()), 120, step=5)
    assert done["delivered"] and not done["pending"], (failed, done)
