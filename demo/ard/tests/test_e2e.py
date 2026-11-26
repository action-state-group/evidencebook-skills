# SPDX-License-Identifier: Apache-2.0
"""The whole story, end to end, with the real binaries: capsulectl-deal (``CAPSULECTL_DEAL``), capsule-engine
(``CAPSULE_ENGINE``); capsulectl-deal also rules as the adjudicator's own profile) and a witness every agreement names:
Action State's hosted one in CI, or the one ``ARD_E2E_WITNESS_URL`` and ``ARD_E2E_WITNESS_KEY`` name (scripts/check.sh
starts one on this machine; :func:`_local_witness`). It seeds a home (about a minute), then runs
deal 1 (Maya buys from Kestrel, Kestrel's own delivery record says 150 of 200, Maya disputes, the adjudicator rules
against Kestrel, both enter the ruling) and deal 2 (Kestrel's card counts the lost dispute; Maya's own ruling makes it
NO; a buyer who holds no ruling sees LIMIT from the card alone; Alder is GO and paid).

With the hosted witness it needs the network. It runs only with ``ARD_E2E=1`` (CI's ard-demo job sets it). The approval dialogs are answered in
the test, as ``demo.py run --auto`` does: never on a real rail."""
from __future__ import annotations

import contextlib
import json
import os
import re
import time

import pytest
from _stampwait import stamp_wait, try_tick

pytestmark = pytest.mark.skipif(os.environ.get("ARD_E2E") != "1" or not all(
    os.environ.get(v) for v in ("CAPSULECTL_DEAL", "CAPSULE_ENGINE", "ARD_EVIDENCEBOOK")),
    reason="ARD_E2E=1 with CAPSULECTL_DEAL, CAPSULE_ENGINE and ARD_EVIDENCEBOOK set")


def _local_witness(mp: pytest.MonkeyPatch) -> None:
    """Name the witness ``ARD_E2E_WITNESS_URL`` and ``ARD_E2E_WITNESS_KEY`` give, instead of the hosted one, in every
    place the demo names a witness: scripts/check.sh starts one on this machine (capsule-anchor's ci/local-witness,
    evidencebook-skills#371), so parallel local checks neither wait on nor load Action State's service. Test-only: a
    person's run, and CI's on main and nightly, keep the hosted witness. ``deal init`` can name only the hosted witness
    (evidencebook capsulectl ``deal.go``, ``DealDefaultWitness``), so it runs with ``--no-witness`` and the profile then
    names this one, as :meth:`party.Party.add_witness` does for a profile made without a witness. The buyer's pack
    trusts this witness's key in place of the hosted one's, or no card would read as witnessed."""
    import buyer
    import pack as packs
    import party as pt

    url, key = os.environ.get("ARD_E2E_WITNESS_URL", ""), os.environ.get("ARD_E2E_WITNESS_KEY", "")
    if bool(url) != bool(key):
        raise pytest.UsageError("set both ARD_E2E_WITNESS_URL and ARD_E2E_WITNESS_KEY, or neither")
    if not url:
        return
    hosted = pt.WITNESS_KEY
    mp.setattr(pt, "WITNESS_URL", url)
    mp.setattr(pt, "WITNESS_KEY", key)
    mp.setitem(buyer.OPERATOR_FACTS, "witness", key)

    def starting():  # the pack's witness trust root is the hosted witness's key (pack-source.yaml trust_roots)
        text = packs.source_path().read_text()
        assert text.count(hosted) == 1, "the pack names the hosted witness's key once, in trust_roots"
        return packs.compile_source(text.replace(hosted, key), packs.version_of(text))
    mp.setattr(packs, "starting", starting)
    run = pt.Party.run

    def init_then_name(self, *args):
        if args[:1] != ("init",) or "--no-witness" in args:
            return run(self, *args)
        out = run(self, *args, "--no-witness")
        self.add_witness()
        return out
    mp.setattr(pt.Party, "run", init_then_name)


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

    with pytest.MonkeyPatch.context() as mp:  # undone however the fixture ends, a failed set-up too
        _local_witness(mp)
        home = tmp_path_factory.mktemp("ard-e2e")
        seed.seed(home, say=lambda *_: None)
        st = stage.Stage(home)
        agents = {n: flow.SellerAgent(home, n) for n in SELLERS}
        entries = ard.lookup(stage.REGISTRY_URL, stage.ORIGINS, stage.QUERY)
        w = {"home": home, "stage": st, "agents": agents, "maya": pt.Party(home, "maya"), "adj": adj.Adjudicator(home),
             "pack": packs.starting(), "entries": entries,
             "keys": {e["id"]: e["commitment"]["key_id"] for e in entries}}
        yield w
        for a in agents.values():
            a.stop()
        st.close()


#: How long a test waits for a seller's published card to carry its witness's receipt: longer than an on-demand publish
#: waits (flow.CARD_STAMP_WAIT_S); the seller's loop publishes the stamped card once the witness has taken it (#350).
CARD_STAMPED_WAIT_S = 120


def _wait_stamped(w, seller: str) -> None:
    import flow

    card = flow.stage_dir(w["home"]) / "cards" / f"{seller}.json"
    stamp_wait(lambda: card.is_file() and flow.stamped(card), f"{seller}'s published card carrying its receipt",
               CARD_STAMPED_WAIT_S)


def _assess(w, buyer_party):
    import buyer

    out = {}
    for e in w["entries"]:
        _wait_stamped(w, e["id"])
        ev = buyer.gather(w["home"], buyer_party, e)
        # #350: a real verify of each seeded shared card checks its witness's receipt for the card's anchor
        # (reader_witnesses, evidencebook#957), so Maya is told it is time-stamped
        assert ev.read is not None and ev.read.witness_status == "pass", (e["id"], ev.checks)
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
    import adjudicator as adj
    import buyer
    import flow
    import party as pt
    import screens

    w = world
    # deal 1: both clean, both GO
    made = _assess(w, w["maya"])
    from cast import SAMPLE_DEALS
    for key, (ev, a) in made.items():
        n = SAMPLE_DEALS[key]  # each seller's own sample history (#317)
        assert ev.card["outcomes"] == {"of": n, "held": n, "did_not_hold": 0, "undecided": 0}, key
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
    w["adj"].stamp(_fresh(w, deal.deal_id))  # a slow witness: the stamp is taken later, in the background (#307)

    # each side enters it in its own records and sends its book back; the entry check reads both
    _until(lambda: (flow.enter_rulings(w["home"], w["maya"], "buyer", "kestrel", lambda *_: None) or True)
           and w["maya"].notes(flow.BOOK_SENT), 300)
    _until(lambda: w["agents"]["kestrel"].party.notes(flow.BOOK_SENT), 300)
    # the ruling's witnessed time reaches Maya: with the ruling, or on the ruling file sent again once stamped (#307)
    def ruling_stamp_line() -> str:
        later = [t for t in adj.LATER if t.name == f"ruling-stamp-{deal.deal_id[5:13]}"]
        if not later:
            return "The adjudicator's stamp was delivered in time, so the ruling's receipt did not reach Maya's records."
        if later[-1].is_alive():
            # the thread stamps, then sends the ruling again (adjudicator._send_ruling): alive is either step
            return (f"The adjudicator's background stamp was still running: waiting for {pt.WITNESS_NAME} to take the "
                    "ruling's stamp, or sending the stamped ruling again.")
        return "The adjudicator's wait for the ruling's stamp had ended."
    stamp_wait(lambda: (flow.enter_rulings(w["home"], w["maya"], "buyer", "kestrel", lambda *_: None) or True) and (
        w["maya"].notes(flow.RULING_ENTERED)[0]["statement"]["stamped_at"] or w["maya"].notes(flow.RULING_STAMPED)),
        "the ruling's witnessed time in Maya's records", adj.LATER_S + 30, detail=ruling_stamp_line)
    # both entries read time-stamped once the witness has taken each side's book: Maya's proof goes on a later round of
    # her entering (flow.enter_rulings), Kestrel's with its agent's; as long as the demo waits for a stamp taken later
    read: list[str] = []

    def both_witnessed():
        flow.enter_rulings(w["home"], w["maya"], "buyer", "kestrel", lambda *_: None)
        read[:] = sorted({x["words"] for x in w["adj"].entries(_fresh(w, deal.deal_id))})
        return read == ["entered"]
    stamp_wait(both_witnessed, "both parties' entries of the ruling", adj.LATER_S, step=5,
               detail=lambda: f"The adjudicator's entry check read {read}" + (
                   f": {pt.WITNESS_NAME} had not stamped every book sent with an entry yet."
                   if any("not witnessed" in x for x in read) else "."))

    # a reopened window remembers Maya's deals from her own records, and routes the ruling to that deal's seller
    import buyer as b
    assert [d.deal_id for d in b.deals_from_notes(w["maya"])] == [deal.deal_id]
    assert b.seller_of(w["maya"])(deal.deal_id) == "kestrel"
    assert _fresh(w, deal.deal_id)["ruling"]["against"] == "seller"

    # Kestrel's ruling line, from its own report and the stamp time its agent noted (#360): the remedy Maya's card shows
    kestrel, ticks = w["agents"]["kestrel"].party, [None]
    entered = flow.rulings_entered(kestrel)
    assert list(entered) == [deal.deal_id]
    rep = kestrel.report(deal.deal_id)
    seller_line = screens.ruled_for_seller(rep.get("report", rep), entered[deal.deal_id])
    assert len(seller_line) == 1 and seller_line[0].startswith("Ruled against you: delivery not met. ")
    assert seller_line[0].endswith(screens.NO_REFUND)

    # Kestrel's own card counts it once Kestrel stamps (on demand: no wait for the cadence), as its agent's
    # republish(now=True) does; the tick is kept to say whether the witness had taken the stamp
    def kestrel_card():
        ticks[0] = try_tick(kestrel.stamp)  # a refusal is tried again next round, as the agent's republish does
        published = try_tick(lambda: {"card": flow.publish_card(w["home"], kestrel)})
        if "error" in published:
            ticks[0] = {"error": f"publishing the card: {published['error']}"}
            return None
        c, _, _ = flow.read_card(published["card"])
        # the dispute's count and the deal's outcome can come one checkpoint apart: wait for both
        return c if c["disputes"]["received"]["by_outcome"]["against"] and c["outcomes"]["did_not_hold"] else None
    card = stamp_wait(kestrel_card, "Kestrel's card counting the ruling", adj.LATER_S, tick=lambda: ticks[0])
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

    # Alder is paid, delivers all 200, and Maya says she received it. The person answers the payment dialog late, after
    # 185 s: within its 10-minute wait (desktop_server.DIALOG_GIVE_UP_S) but longer than any wait for the other side
    # (flow.WAIT_S): nothing reaches the seller before the yes (evidencebook-skills#289), so the deal still goes through.
    assert 185 > flow.WAIT_S
    deal2, shipped2 = _buy(w, "alder", made["alder"][1], answer_after=185)
    assert shipped2 == "200 of 200 badges"
    buyer.close_received(w["home"], w["maya"], deal2)

    # #242: Maya's receipt page is capsulectl's own (deal report --html), drawn with the hosted witness's directory
    import receipt
    page = receipt.receipt_page(w["maya"], "Maya", deal2.deal_id, rail="simulated", seller=False)
    html = page.read_text()
    assert page.stat().st_size > 10000 and "<html" in html.lower()
    assert '"status":"verified","witness":"Action State\'s witness"' in html, "the page carries the witness time capsulectl verified"
    # #273: the page carries its bundle, so `capsulectl verify --bundle RECEIPT.html` checks it as capsulectl's help
    # says, and finds the same bundle the page's own verify report names.
    checked = w["maya"].verify(page)
    assert checked["verdict"] == "VALID", checked
    carried = json.loads(re.search(r"capsulectlDealPage = Object\.freeze\((.*?)\);\n", html).group(1))
    assert checked["bundle_digest"] == carried["verifier_report"]["bundle_digest"]


def test_a_declined_or_unanswered_payment_leaves_the_sellers_card_as_it_was(world):
    """evidencebook-skills#295: an order the person declined, or a dialog nobody answered, must not show on the seller's
    card as a sale. The dialog comes before anything reaches the seller (#289), so the seller's own card counts the same
    deals and rows after both, and no offer reached its folder."""
    import buyer
    import flow
    import pay
    import wire

    w = world
    seller = w["agents"]["alder"].party

    def card():
        seller.stamp()  # a stamp now: the card counts everything sealed before it
        c, _, _ = flow.read_card(seller.card_bundle(shared=True))
        return c["outcomes"], c["disputes"]["received"]["of"]
    # the seller's deal list (no checkpoint lag) and its card once a checkpoint covers the earlier tests' deals
    deals, before, offers = len(seller.deals()), card(), wire.pending(w["home"], "alder", "offer")
    a = _assess(w, w["maya"])["alder"][1]
    for how in ("declined", "no answer in time"):
        made = buyer.open_and_pay(w["home"], w["maya"], "alder", w["keys"]["alder"], a, w["adj"].named(), pay.FakeRail(),
                                  f"Pay (test, {how})", lambda summary: False, lambda *_: None, simulated=True)
        assert made is None
    assert len(seller.deals()) == deals and wire.pending(w["home"], "alder", "offer") == offers
    assert card() == before


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
    assert any("200 of 200" in x for x in said) and any(x.startswith("Nothing has been sent in Maya's name") for x in said)
    assert not second.notes(buyer.RECEIVED_SAID)  # F10: nothing said in her name without her yes
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


@contextlib.contextmanager
def _witness_unreachable(monkeypatch):
    """The witness answers nothing while inside, its endpoint unchanged. The hosted one: a proxy on a closed port. A
    local one (:func:`_local_witness`) is on localhost, which Go never sends through a proxy, so its certificate is left
    out of the trusted roots instead and every delivery fails before it reaches the witness."""
    with monkeypatch.context() as m:
        if os.environ.get("ARD_E2E_WITNESS_URL"):
            roots = next(f for f in ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt") if os.path.isfile(f))
            m.setenv("SSL_CERT_FILE", roots)  # the system roots alone (macOS's file, Ubuntu's), as start.sh reads them
        else:
            m.setenv("HTTPS_PROXY", "http://127.0.0.1:9")  # nothing listens: the delivery fails
        yield


def test_a_checkpoint_the_witness_did_not_get_is_delivered_by_a_later_tick_after_a_re_entry(world, monkeypatch):
    """evidencebook-skills#287: a checkpoint whose delivery failed (here, a proxy that answers nothing) stays pending, and
    a later tick, run by a new process on the same home as a reopened window does, is accepted by the witness and
    leaves nothing pending (capsulectl delivers the newest checkpoint, which extends the last one the witness took).
    "Later": after a failed delivery capsulectl waits out a growing retry delay before it tries the witness again, so the
    first tick after the network returns may deliver nothing (CI at 5deff10)."""
    import flow
    import party as pt

    w = world
    # Kestrel's agent ticks the same profile on its own cadence: closed for this test (as a closed window is), so the
    # failed delivery is this test's and the recovery is the reopened window's, never the agent's; reopened after.
    agent = w["agents"]["kestrel"]
    agent.stop()
    for t in agent.threads:
        t.join(60)
    assert not any(t.is_alive() for t in agent.threads), "Kestrel's agent did not stop"
    try:
        p = pt.Party(w["home"], "kestrel")
        p.note(flow.JOINED, {"operator": p.profile, "key_id": p.key_id})  # something new, so the next tick checkpoints
        with _witness_unreachable(monkeypatch):  # reachable again on every way out, before the agent reopens
            failed = _until(lambda: (lambda t: t if t.get("state") == "ticked" else None)(p.tick()), 120, step=5)
        assert failed["pending"], failed
        again = pt.Party(w["home"], "kestrel")  # a reopened window: a new object, each verb a new process
        ticks: list[dict] = []

        # done once this window's ticks have delivered and the newest leaves nothing pending: a slow witness may take
        # the failed checkpoint and its successors over more than one tick
        def delivered():
            ticks.append(try_tick(again.tick))
            return ticks[-1] if any(t.get("delivered") for t in ticks) and ticks[-1].get("pending") == [] else None
        stamp_wait(delivered, f"Kestrel's checkpoint {failed.get('checkpoint')} after its failed delivery", 420, step=10,
                   tick=lambda: ticks[-1] if ticks else None)
    finally:
        w["agents"]["kestrel"] = flow.SellerAgent(w["home"], "kestrel")


def test_a_spending_limit_holds_an_order_before_the_seller_hears_of_it(world, monkeypatch):
    """evidencebook#890: with ``ARD_LIMIT_MSAT`` set, Maya's profile pins capsule-engine's Everyday Rules
    (``guard check --limits``) as its rules checker, and capsulectl's ``deal check`` runs them on the payment, checked on
    her offer before it is sent. Over her limit, the order is held: one question that lists every reason, with
    capsulectl's card under it. Don't buy seals her no and cancels the unsent
    offer, so Alder's book is as it was; Buy anyway seals her yes on the card she saw, and the order is sent and paid."""
    import buyer
    import flow
    import pay
    import screens
    import wire

    w = world
    w["agents"]["alder"].stop()  # an earlier test may have closed its window: open it again
    w["agents"]["alder"] = flow.SellerAgent(w["home"], "alder")
    seller = w["agents"]["alder"].party
    a = _assess(w, w["maya"])["alder"][1]
    assert a.verdict == "GO"
    limit = a.price_msat // 2  # this order alone is over it
    monkeypatch.setenv("ARD_LIMIT_MSAT", str(limit))
    deals, offers = len(seller.deals()), wire.pending(w["home"], "alder", "offer")
    asked = []

    def answer(how):
        return lambda q: asked.append(q) or how
    assert buyer.open_and_pay(w["home"], w["maya"], "alder", w["keys"]["alder"], a, w["adj"].named(), pay.FakeRail(),
                              "Pay (test)", answer("no"), lambda *_: None, simulated=True) is None
    q = asked[-1]
    assert q.held is not None and (q.yes, q.no) == ("Buy anyway", "Don't buy")
    over = f"over your per-order limit: this order {a.price_msat:,} msat, limit {limit:,} msat"
    assert over in q.held.reasons and "per_order" in q.held.limits
    assert f"{screens.CARD_HEAD}\nPAUSED FOR YOU" in q.text  # capsulectl's card, in full, under the question
    assert len(seller.deals()) == deals and wire.pending(w["home"], "alder", "offer") == offers

    made = buyer.open_and_pay(w["home"], w["maya"], "alder", w["keys"]["alder"], a, w["adj"].named(), pay.FakeRail(),
                              "Pay (test)", answer("yes"), lambda *_: None, simulated=True)
    assert made is not None
    assert over in asked[-1].held.reasons
    deal, _ = made
    assert buyer.shipped(buyer.await_delivery(w["home"], w["maya"], deal))
