# SPDX-License-Identifier: Apache-2.0
"""The whole story, end to end, with the real binaries: capsulectl-deal (``CAPSULECTL_DEAL``), capsule-engine
(``CAPSULE_ENGINE``); capsulectl-deal also rules as the adjudicator's own profile) and Action State's hosted witness, which every
agreement names. It seeds a home (about eight minutes: the sample deals' contest windows must end), then runs
deal 1 (Maya buys from Kestrel, Kestrel's own delivery record says 150 of 200, Maya disputes, the adjudicator rules
against Kestrel, both enter the ruling) and deal 2 (Kestrel's card counts the lost dispute; Maya's own ruling makes it
NO; a buyer who holds no ruling sees LIMIT from the card alone; Alder is GO and paid).

It needs the network and runs only with ``ARD_E2E=1`` (CI's ard-demo job sets it). The approval dialogs are answered in
the test, as ``demo.py run --auto`` does: never on a real rail."""
from __future__ import annotations

import os
import time

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("ARD_E2E") != "1" or not all(
    os.environ.get(v) for v in ("CAPSULECTL_DEAL", "CAPSULE_ENGINE", "ARD_EVIDENCEBOOK")),
    reason="ARD_E2E=1 with CAPSULECTL_DEAL, CAPSULE_ENGINE and ARD_EVIDENCEBOOK set")


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


def _buy(w, key, a, who=None, answer_after: float = 0):
    """Ask, open the deal and pay (buyer.open_and_pay). ``answer_after`` is how long the person takes to answer the
    payment dialog: nothing reaches the seller meanwhile."""
    import buyer
    import pay
    import wire

    who = who or w["maya"]
    rail = pay.FakeRail()

    def ask(summary: str) -> bool:
        before = wire.pending(w["home"], key, "offer")
        time.sleep(answer_after)
        assert wire.pending(w["home"], key, "offer") == before  # the seller hears nothing before the yes
        return True
    deal, _ = buyer.open_and_pay(w["home"], who, key, w["keys"][key], a, w["adj"].named(), rail, "Pay (test)", ask,
                                 lambda *_: None, simulated=True)
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

    # the dispute; the adjudicator asks both sides for their books; each answers in full; the ruling
    buyer.dispute(w["home"], w["maya"], deal, lambda *_: None)
    case = _case(w, w["maya"], deal.deal_id, 2)
    names = flow.case_names(case)
    assert names == {"buyer": "Maya", "seller": "Kestrel Print"}
    view = flow.case_view(case, names)
    assert set(view.answered) == {"buyer", "seller"}
    assert "Kestrel Print's own signed delivery record: 150 of 200 badges" in view.deciding
    r = w["adj"].rule(case, view.row, "not_met", "seller")
    assert r["sealed"] and set(r["books"]) == {"buyer", "seller"}
    assert w["adj"].stamp(_fresh(w, deal.deal_id))

    # each side enters it in its own records and sends its book back; the entry check reads both
    _until(lambda: (flow.enter_rulings(w["home"], w["maya"], "buyer", "kestrel", lambda *_: None) or True)
           and w["maya"].notes(flow.BOOK_SENT), 300)
    _until(lambda: w["agents"]["kestrel"].party.notes(flow.BOOK_SENT), 300)
    assert w["maya"].notes(flow.RULING_ENTERED)[0]["statement"]["stamped_at"]
    assert {x["words"] for x in w["adj"].entries(_fresh(w, deal.deal_id))} == {"entered"}

    # a reopened window remembers Maya's deals from her own records, and routes the ruling to that deal's seller
    import buyer as b
    assert [d.deal_id for d in b.deals_from_notes(w["maya"])] == [deal.deal_id]
    assert b.seller_of(w["maya"])(deal.deal_id) == "kestrel"
    assert _fresh(w, deal.deal_id)["ruling"]["against"] == "seller"

    # Kestrel's own card counts it after its next checkpoint
    def kestrel_card():
        w["agents"]["kestrel"].republish()
        c, _, _ = flow.read_card(w["home"] / "stage" / "cards" / "kestrel.json")
        # the dispute's count and the deal's outcome can come one checkpoint apart: wait for both
        return c if c["disputes"]["received"]["by_outcome"]["against"] and c["outcomes"]["did_not_hold"] else None
    card = _until(kestrel_card, 240, step=5)
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

    # Alder is paid, delivers all 200, and Maya says she received it. The person answers the payment dialog at its last
    # second (it waits up to 3 minutes, desktop_server.ask_person), longer than any wait for the other side
    # (flow.WAIT_S): nothing reaches the seller before the yes (evidencebook-skills#289), so the deal still goes through.
    assert 185 > flow.WAIT_S
    deal2, shipped2 = _buy(w, "alder", made["alder"][1], answer_after=185)
    assert shipped2 == "200 of 200 badges"
    buyer.close_received(w["home"], w["maya"], deal2)


def test_a_seller_window_closed_at_pay_time_delivers_when_it_reopens(world):
    """The seller's window is closed when the buyer pays: the buyer's wait ends and says so, nothing is lost, and when the
    seller's window reopens its agent records the payment and delivers; the buyer's agent then picks the delivery up
    and closes the deal on the buyer's side (Maya's window does this every few seconds)."""
    import buyer
    import flow
    import party as pt
    import pay

    w = world
    second = pt.Party(w["home"], "second-buyer").create("person")
    ev, a = _assess(w, second)["alder"]
    assert a.verdict == "GO"
    w["agents"]["alder"].stop()  # the window closes
    rail = pay.FakeRail()
    w["agents"]["alder"] = flow.SellerAgent(w["home"], "alder")  # the offer needs the seller's agreement first
    deal = buyer.open_deal(w["home"], second, "alder", w["keys"]["alder"], a, w["adj"].named(), lambda *_: None,
                           rail=rail.SEALED, me=second.name)
    w["agents"]["alder"].stop()  # closed again before Maya pays
    inv = rail.invoice(a.price_msat)
    check = buyer.check_payment(second, deal, inv.payment_hash)
    if not check.get("proceed"):
        second.approve(deal.deal_id, check, "proceed", "Pay (test)\nAnswer: Pay")
    buyer.pay(w["home"], second, deal, check, rail.pay_invoice(inv).reference, simulated=True)
    with pytest.raises(pt.Refused, match="has not recorded the payment and the delivery yet"):
        buyer.await_delivery(w["home"], second, deal, seconds=5)
    assert buyer.pick_up_deliveries(w["home"], second, lambda *_: None) == []
    w["agents"]["alder"] = flow.SellerAgent(w["home"], "alder")  # the window reopens
    said: list[str] = []
    got = _until(lambda: buyer.pick_up_deliveries(w["home"], second, said.append), 300)
    assert got == [deal.deal_id]
    assert any("200 of 200" in x for x in said) and "Maya's statement sent: she received what she paid for." in said
    assert buyer.pick_up_deliveries(w["home"], second, said.append) == []  # once only


def test_a_silent_seller_is_read_from_the_records_it_signed_that_the_buyer_holds(world):
    """A second buyer buys from Alder; Alder's agent stops before the adjudicator asks for its books. The buyer's answer
    carries its own book and the copy it holds of Alder's, so the case still reads Alder's own signed delivery record
    (u211 item 2: a silent side is ruled on only from records it signed), and the ruling reads Alder's book from the
    buyer's held copy."""
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
    case = _case(w, second, deal.deal_id, 1, seconds=60)
    view = flow.case_view(case, flow.case_names(case))
    assert set(view.answered) == {"buyer"}
    assert "Alder Print Co.'s own signed delivery record: 200 of 200 badges" in view.deciding
    r = w["adj"].rule(case, view.row, "met", "none")
    seller_book = r["books"]["seller"]["records"]
    assert seller_book and {x["timed_by"] for x in seller_book} <= {"own_stamp", "holder_link"}


def _case(w, party, deal_id: str, answers: int, seconds: float = 300) -> dict:
    """The adjudicator asks; this buyer's agent answers (a seller's agent answers on its own); the case once ``answers``
    sides have answered."""
    import adjudicator as adj

    def ready():
        w["adj"].ask()
        adj.answer_requests(w["home"], party, party.name, "buyer", lambda *_: None)
        c = next((c for c in w["adj"].cases() if c["deal_id"] == deal_id), None)
        return c if c and len(c["answers"]) >= answers else None
    case = _until(ready, seconds)
    assert case, f"no {answers} answers for {deal_id}"
    return case


def _fresh(w, deal_id: str) -> dict:
    return next(c for c in w["adj"].cases() if c["deal_id"] == deal_id)


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
