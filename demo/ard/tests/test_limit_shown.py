# SPDX-License-Identifier: Apache-2.0
"""evidencebook-skills#331 (carrying #335): the buyer's first turn shows her own card and the spending limit she set,
and the assessment shows that limit and whether each price fits it, or says none is set and names the pack's limits.
evidencebook-skills#361: that limit is the amount she confirmed when her agent proposed it, sealed with her answer in
her own records (u550); every tool reads the sealed one. The words are general: the non-demo tests use a buyer,
sellers and amounts outside the demo cast. No binary is run."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

import limits
import screens


def test_a_set_limit_is_shown_as_the_person_set_it():
    assert screens.limit_line(4500, [10, 1000]) == ("Your spending limit: 4,500 msat for any one order, and 4,500 msat "
                                                    "in total over 7 days. Each payment is checked against it.")


def test_no_limit_names_every_limit_of_the_pack_from_the_pack():
    assert screens.limit_line(None, [10000, 10, 1000]) == ("No spending limit is set yet, so only this pack's limits apply: "
                                                          "deals under 10 msat, 1,000 msat or 10,000 msat, depending on the "
                                                          "seller's history.")


@pytest.mark.parametrize("price,want", [
    (2999, " Within your limit of 3,000 msat for one order; your 7-day total is checked at payment."),
    (3000, " Within your limit of 3,000 msat for one order; your 7-day total is checked at payment."),  # over fails only
    (3001, " Over your limit of 3,000 msat for one order: the order would wait for your OK at payment."),
])
def test_each_price_is_read_against_the_limit_for_one_order(price, want):
    assert screens.within_limit(price, 3000) == want
    assert screens.within_limit(price, None) == ""


def test_a_buyer_and_sellers_outside_the_demo_cast():
    """Any personal agent: the lines name no party and carry only the amounts they are given."""
    for line in (screens.limit_line(750, [5, 50, 500]), screens.limit_line(None, [5, 50, 500]),
                 screens.within_limit(600, 750), screens.within_limit(800, 750)):
        assert not any(n in line for n in ("Maya", "Alder", "Kestrel", "3,000", "badges"))
    assert "under 5 msat, 50 msat or 500 msat" in screens.limit_line(None, [500, 5, 50])


def test_the_pack_limits_come_from_the_pack():
    import desktop_server as ds
    import pack as packs
    p = packs.starting()
    assert ds._ceilings(p) == [p.ceiling_msat(t["id"]) for t in p.tiers()] and len(ds._ceilings(p)) == len(p.tiers())


class Book:
    """A buyer's own records, as limits.seal and limits.sealed use them (party.Party.note and notes)."""
    name = "rin"

    def __init__(self):
        self.records = []

    def note(self, record_type, statement, **kw):
        self.records.append({"type": record_type, "statement": statement})

    def notes(self, record_type=""):
        return [n for n in self.records if not record_type or n["type"] == record_type]

    def approve(self, deal_id, check, choice, said):
        self.records.append({"type": "approval", "statement": {"choice": choice, "said": said}})


def test_no_limit_until_the_person_confirms_one():
    book = Book()
    assert limits.sealed(book) is None  # a proposal the person has not answered sets nothing
    for bad in (0, -5, True, "4500", 45.0):
        with pytest.raises(limits.LimitError):
            limits.seal(book, bad, "Set your spending limit?\nAnswer: Set limit")
    with pytest.raises(limits.LimitError):
        limits.seal(book, 4500, "  ")
    assert book.records == []
    limits.seal(book, 4500, "Set your spending limit to 4,500 msat?\nAnswer: Set limit")
    assert limits.sealed(book) == 4500
    assert book.records[-1]["statement"] == {"limit_msat": 4500,
                                             "said": "Set your spending limit to 4,500 msat?\nAnswer: Set limit"}
    limits.seal(book, 750, "Set your spending limit to 750 msat?\nAnswer: Set limit")
    assert limits.sealed(book) == 750  # a later confirmed limit replaces it


def _open_windows():
    spec = importlib.util.spec_from_file_location("open_windows", Path(__file__).resolve().parents[1] / "goose" /
                                                  "open-windows.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_buyers_first_turn_asks_for_her_card_and_limit_and_her_recipe_names_no_amount():
    ow = _open_windows()
    maya = ow.PARTIES["maya"]
    assert "ard_show_card" in maya["prompt"] and "spending limit" in maya["prompt"]
    assert "msat" not in maya["facts"]  # what she will pay, and so her limit, comes in her own words (#361)


def test_only_a_seller_that_can_be_paid_gets_the_limit_words(monkeypatch, capsys):
    """Claude's round 1: a LIMIT or NO seller pays nothing, so its line says nothing about the limit."""
    import desktop_server as ds
    import buyer
    import pack as packs
    s = type("S", (), {})()
    s.entries = [{"id": "kestrel", "name": "Seller One", "commitment": {"key_id": "k"}, "offer": {"price_msat": 1000}},
                 {"id": "alder", "name": "Seller Two", "commitment": {"key_id": "k"}, "offer": {"price_msat": 400}}]
    s.evidence = {e["id"]: buyer.Evidence(e["id"], card={"outcomes": {}}) for e in s.entries}
    s.assessed, s.maya, s.pack = {}, Book(), packs.starting()
    limits.seal(s.maya, 500, "Set your spending limit to 500 msat?\nAnswer: Set limit")
    verdicts = {1000: "LIMIT", 400: "GO"}
    monkeypatch.setattr(ds, "session", lambda: s)
    monkeypatch.setattr(buyer, "assess", lambda m, ev, key, price, p: type("A", (), {
        "verdict": verdicts[price], "tier": None, "price_msat": price, "reasons": [], "cap_msat": 10, "rulings": []})())
    monkeypatch.setattr(ds.screens, "decision_line", lambda a, ev, ceiling=None: f"{a.verdict}: line")
    out = ds.ard_assess()  # the tool returns what it printed
    one = next(line for line in out.splitlines() if "Seller One" in line)
    two = next(line for line in out.splitlines() if "Seller Two" in line)
    assert "limit" not in one.lower().replace("limit: line", "")
    assert two.endswith("GO: line. Within your limit of 500 msat for one order; your 7-day total is checked at payment.")


@pytest.mark.parametrize("limit,want", [(4500, "Your spending limit: 4,500 msat for any one order, and 4,500 msat in total over 7 days"),
                                        (None, "No spending limit is set yet, so only this pack's limits apply")])
def test_the_buyers_card_shows_her_limit_even_when_the_witness_takes_no_stamp(monkeypatch, limit, want):
    """Codex's round 1: through the tool itself, with a buyer named outside the demo cast and a stamp that fails."""
    import desktop_server as ds
    import flow
    import pack as packs
    import party as pt
    logged = []

    class Buyer(Book):
        def stamp(self):
            raise pt.WitnessSlow("slow")

        def card_bundle(self, shared):
            return "card.json"

        def log(self, line):
            logged.append(line)
    s = type("S", (), {"deals": [], "pack": packs.starting()})()
    rin = Buyer()
    if limit is not None:
        limits.seal(rin, limit, f"Set your spending limit to {limit:,} msat?\nAnswer: Set limit")
    monkeypatch.setattr(ds, "_own", lambda: (rin, "Rin"))
    monkeypatch.setattr(ds, "session", lambda: s)
    monkeypatch.setattr(flow, "read_card", lambda f: ({"outcomes": {"of": 0, "held": 0, "did_not_hold": 0}},
                                                      {"anchor_time": "2026-11-25T22:00:00Z"}, "k"))
    out = ds.ard_show_card()
    assert out.startswith("Rin: its own History card, as of its checkpoint at") and want in out and "REFUSED" not in out
    assert "slow" in logged[0]


def test_the_limit_the_person_confirms_drives_her_card_assessment_and_held_order_question(monkeypatch):
    """evidencebook-skills#361: step 2's amount, proposed in chat and confirmed by her click in the limit dialog, is the
    one her card, the assessment, the payment check, her sealed intent and the held-order question use. A buyer,
    sellers, an ask and an amount outside the demo cast (4,500 msat, not 3,000), so nothing in code supplies them."""
    import threading
    import types

    import buyer
    import desktop_server as ds
    import pack as packs

    rin = Book()
    s = types.SimpleNamespace(maya=rin, pack=packs.starting(), log=[], deals=[], declined={}, picked=set(),
                              ask="", home=None, pay_lock=threading.Lock(),
                              entries=[{"id": "alder", "name": "Seller Two", "commitment": {"key_id": "k"},
                                        "offer": {"price_msat": 5000}}])
    s.evidence = {"alder": buyer.Evidence("alder", card={"outcomes": {}})}
    s.assessed, s.keys = {}, {"alder": "k"}
    s.adjudicator = types.SimpleNamespace(named=lambda: {})
    s.rail = types.SimpleNamespace(SEALED="simulated", checked_invoice=lambda msat: types.SimpleNamespace(payment_hash="h"))
    monkeypatch.setattr(ds, "session", lambda: s)
    monkeypatch.setattr(ds, "_session", None)
    monkeypatch.setattr(ds, "_real", lambda: False)
    monkeypatch.setattr(ds, "gate_off", lambda: False)
    a = types.SimpleNamespace(verdict="GO", tier=None, price_msat=5000, reasons=[], cap_msat=None, rulings=[])
    monkeypatch.setattr(buyer, "assess", lambda *args: a)
    monkeypatch.setattr(ds.screens, "decision_line", lambda a, ev, ceiling=None: "GO: line")
    assert not any(c.isdigit() for c in ds.ard_set_limit.__doc__)  # the tool's words carry no amount (#331)

    # her ask, in her own words, and the amount proposed in chat but not yet confirmed: no limit
    monkeypatch.setattr(ds.ard, "lookup", lambda *args: s.entries)
    monkeypatch.setattr(buyer, "record_search", lambda *args: None)
    found = ds.ard_find_sellers("Rin here: 30 lanyards by Monday, under 4,500 msat.")
    # #413: the search ends on the limit question, before any card or assessment (Steven's hand runs, 2026-11-26)
    assert found.endswith("\n\n" + ds.LIMIT_FIRST)
    unset = ds.ard_assess()
    assert "No spending limit is set yet" in unset and ds.NO_SUMS not in unset
    dialogs = []

    def answer(how):
        return lambda title, text, yes, no="Cancel": dialogs.append((title, text, yes)) or how
    for how, said in ((ds.NO, "Maya chose Cancel"), (ds.NO_ANSWER, "Maya did not answer in time")):
        monkeypatch.setattr(ds, "dialog_answer", answer(how))
        out = ds.ard_set_limit(4500)
        assert out.startswith(f"REFUSED: {said}, so no spending limit was set") and limits.sealed(rin) is None
    assert dialogs[-1] == ("Set your spending limit", "Set your spending limit to 4,500 msat for any one order, and "
                           "4,500 msat in total over 7 days? Each payment is then checked against it, and an order "
                           "over it waits for your OK.", "Set limit")
    assert ds.ard_set_limit(0).startswith("REFUSED: a spending limit is a whole number")

    # her click: sealed with the words she saw, and every tool reads it; never while a payment holds the lock
    monkeypatch.setattr(ds, "dialog_answer", answer("yes"))
    sealing = limits.seal
    monkeypatch.setattr(limits, "seal", lambda *args: (s.pay_lock.locked() or pytest.fail("sealed outside the lock"))
                        and sealing(*args))
    out = ds.ard_set_limit(4500)
    assert out == ("Your spending limit: 4,500 msat for any one order, and 4,500 msat in total over 7 days. "
                   "Each payment is checked against it.\n" + ds.LIMIT_SET_THEN)  # one yes sets it, nothing more (#413)
    assert ds.LIMIT_FIRST not in ds.ard_find_sellers(s.ask)  # set: no question again
    assert rin.notes(limits.LIMIT_SET)[-1]["statement"]["said"].endswith("waits for your OK.\nAnswer: Set limit")
    assessed = ds.ard_assess()
    assert "Your spending limit: 4,500 msat" in assessed
    assert ds.NO_SUMS in assessed  # the 7-day total is the payment check's to say (#415's hand run)
    assert assessed.splitlines()[-1].endswith("Over your limit of 4,500 msat for one order: the order would wait for "
                                              "your OK at payment.")

    # the payment: the Everyday Rules pinned with 4,500, her intent sealed with 4,500 and her own ask
    pinned, intents = [], []
    monkeypatch.setattr(buyer.limits, "pin", lambda maya, limit: pinned.append(limit))
    monkeypatch.setattr(buyer.limits, "unpin", lambda maya: pytest.fail("a confirmed limit is never unpinned"))

    def draft(maya, seller, key, chosen, adjudicator, rail="lightning", me="maya", limit=None, request=""):
        intents.append((limit, request))
        return buyer.Deal("deal-0123456789abcdef", seller, key, chosen.price_msat, "o", rail, me)
    monkeypatch.setattr(buyer, "draft_deal", draft)
    monkeypatch.setattr(buyer, "cancel_draft", lambda *args, **k: None)
    order = {"id": "r05-spending-limits#per_purchase", "check": "caps/5.1.0", "verdict": "fail", "limit": 4500,
             "value": 5000}
    week = {"id": "r05-spending-limits#7d", "check": "caps/5.1.0", "verdict": "fail", "limit": 4500, "value": 5000}
    monkeypatch.setattr(buyer, "check_payment", lambda *args: {
        "check_id": "c", "verdict": "pause", "proceed": False,
        "rules": {"status": "evaluated", "verdict": "escalate", "findings": [order, week]}})
    s.assessed, s.picked = {"alder": a}, {"alder"}
    monkeypatch.setattr(ds, "dialog_answer", answer("no"))
    out = ds.ard_pay("alder")
    assert pinned == [4500] and intents == [(4500, "Rin here: 30 lanyards by Monday, under 4,500 msat.")]
    title, text, _ = dialogs[-1]
    assert title == "The Everyday Rules held this order for your OK"
    assert "Over your per-order limit: this order 5,000 msat, limit 4,500 msat" in text
    assert "Over your 7-day limit: 5,000 msat with this order, limit 4,500 msat" in text
    assert "nothing was paid" in out and rin.notes("approval")[-1]["statement"]["choice"] == "hold"


def test_a_scripted_payment_reads_the_confirmed_limit_too(monkeypatch):
    """Codex's plan review: every entry to a payment reads the limit she confirmed, not only the window's tool."""
    import buyer
    book = Book()
    limits.seal(book, 750, "Set your spending limit to 750 msat?\nAnswer: Set limit")
    pinned = []
    monkeypatch.setattr(buyer.limits, "pin", lambda maya, limit: pinned.append(limit) or pytest.fail("stop here"))
    with pytest.raises(BaseException):
        buyer.open_and_pay(None, book, "alder", "k", None, {}, None, "Pay?", lambda q: "no", print, simulated=True)
    assert pinned == [750]


def _held_pay(monkeypatch, how, hold=True):
    """ard_pay on an order the Everyday Rules hold, its question answered ``how``: the over-limit run of the RUNBOOK's
    spending-limit section (three reasons), as Steven's hand run of 2026-11-26 reached it. With ``hold=False``, the same
    order's plain payment question, no rule holding it. ``ds.session().asked`` lists every dialog opened."""
    import threading
    import types

    import buyer
    import desktop_server as ds

    held = limits.Held(reasons=["over your 7-day limit: 3,000 msat with this order, limit 2,000 msat",
                                "no earlier payment to this merchant from this profile",
                                "the payment is not refundable"], limits={"weekly": (2000, 3000)})
    s = types.SimpleNamespace(maya=None, home=None, keys={"alder": "k"}, adjudicator=types.SimpleNamespace(named=dict),
                              rail=None, ask="", declined={}, picked={"alder"}, pay_lock=threading.Lock(), log=[],
                              assessed={"alder": types.SimpleNamespace(price_msat=2000)}, asked=[])
    monkeypatch.setattr(ds, "session", lambda: s)
    monkeypatch.setattr(ds, "_session", None)
    monkeypatch.setattr(ds, "_real", lambda: False)
    monkeypatch.setattr(ds, "gate_off", lambda: False)
    monkeypatch.setattr(ds, "dialog_answer", lambda *a: s.asked.append(a[0]) or how)

    def open_and_pay(home, maya, seller, key, chosen, adjudicator, rail, summary, ask, say, **kw):
        if hold:
            ask(buyer.Question(screens.HELD_TITLE, "text", "Buy anyway", "Don't buy", held))
        else:
            ask(buyer.Question("Approve this payment", "text", "Pay", "Cancel"))
        return None
    monkeypatch.setattr(buyer, "open_and_pay", open_and_pay)
    return ds.ard_pay("alder"), held


def test_dont_buy_on_a_held_order_tells_maya_the_holds_own_sentence(monkeypatch):
    """evidencebook-skills#412: Don't buy on an order over the limit reached Maya as "this step was refused (the reason
    is in this party's log, agent.log)", since the refusal ran past the raw-output guard's 400 characters (#327). She
    reads the hold's own sentence whole: the rule, nothing paid, every reason with the limit; then what to offer
    next, never a limit change (#414)."""
    import desktop_server as ds

    out, held = _held_pay(monkeypatch, ds.NO)
    assert "agent.log" not in out
    assert out.startswith("REFUSED: " + screens.rules_held(held.reasons) + " Maya chose Don't buy, so nothing was "
                          "sent to Alder Print Co. Do not retry")  # one period after "Co." (the hand run of #415)
    assert "over your 7-day limit: 3,000 msat with this order, limit 2,000 msat" in out
    assert ('Ask Maya, in one question: "Want me to order again from Alder Print Co. for 2,000 msat, on the simulated '
            'rail, where no money moves?", and say she can choose another seller instead.') in out
    assert "Never offer to change her spending limit" in out
    assert "On her yes to it, call ard_pay again: the dialog asks her once more." in out

    # her yes to that question, then the payment again: the dialog opens at once, with no second question in chat (the
    # hand run of #415 at 502bbc4: the declined guard's question as well made the agent ask her twice)
    assert not ds.session().declined
    again = ds.ard_pay("alder")
    assert ds.session().asked == [screens.HELD_TITLE, screens.HELD_TITLE]
    assert again.startswith("REFUSED: " + screens.rules_held(held.reasons))


def test_a_declined_payment_no_rule_held_asks_its_question_whole_before_the_dialog_opens_again(monkeypatch):
    """The declined guard stays for a payment no rule held: the next call opens no dialog and hands the agent the
    question, whole (Codex's plan review on #415: past 400 characters it read as the bare refusal; #421)."""
    import desktop_server as ds

    out, _ = _held_pay(monkeypatch, ds.NO, hold=False)
    assert "agent.log" not in out and set(ds.session().declined) == {"alder"}
    again = ds.ard_pay("alder")
    assert ds.session().asked == ["Approve this payment"]
    assert "agent.log" not in again and again.startswith("REFUSED: the presenter did not approve the last payment to "
                                                        "Alder Print Co., so this call opens no dialog")
    assert "If Maya said yes to it after the dialog was declined, call ard_pay again now" in again
    assert ds._refusal(ds.Said(again[len("REFUSED: "):])) == again[len("REFUSED: "):]


def test_a_held_order_nobody_answered_is_never_called_a_decline(monkeypatch):
    import desktop_server as ds

    out, held = _held_pay(monkeypatch, ds.NO_ANSWER)
    assert screens.rules_held(held.reasons) in out and "Maya did not answer in time" in out
    assert "Never say she declined it." in out and "order again" not in out
    assert not ds.session().declined


def test_a_refusal_the_demo_writes_stays_whole_and_raw_output_still_does_not(tmp_path, monkeypatch):
    import desktop_server as ds

    monkeypatch.setenv("ARD_HOME", str(tmp_path))  # the raw refusals go to this home's agent.log, not a real demo's

    long = "The Everyday Rules held this order for your OK, and nothing was paid: " + "a reason; " * 60
    assert ds._refusal(ds.Said(long)) == long
    assert ds._refusal(RuntimeError(long)) == "this step was refused (the reason is in this party's log, agent.log)"
    assert ds._refusal(RuntimeError('capsulectl: {"error": "x"}')).startswith("this step was refused")


def test_the_limit_tool_never_offers_a_limit_on_its_own():
    """#414: after Don't buy, Maya's agent offered to raise the limit. Its description says it changes only on the
    person's own ask."""
    import desktop_server as ds

    doc = " ".join(ds.ard_set_limit.__doc__.split())
    assert "Never propose a new or higher limit yourself, after a held order included" in doc


def test_maya_s_receipt_page_answer_says_the_ruling_the_page_shows(tmp_path, monkeypatch):
    """#411's hand run: after "Open your receipt as a page." on her ruled Kestrel deal, Maya said the update did not say
    how the adjudicator ruled. The answer now carries the ruling, as her card does (screens.ruled_for_buyer)."""
    import types

    import buyer
    import desktop_server as ds
    import pages
    import receipt

    deal = buyer.Deal("deal-0123456789abcdef", "kestrel", "k", 1000, "o", "fake", "maya")
    ruled = {"rows": [{"id": "delivered", "status": "ruled", "ruling": {"value": "not_met", "against": "seller"}}]}
    p = types.SimpleNamespace(report=lambda deal_id: {"report": ruled}, log=lambda line: None)
    monkeypatch.setattr(ds, "ROLE", "maya")
    monkeypatch.setattr(ds, "_own_deal", lambda: (p, "Maya", deal.deal_id))
    monkeypatch.setattr(ds, "session", lambda: types.SimpleNamespace(latest=lambda: deal, log=[]))
    monkeypatch.setattr(ds, "_session", None)
    monkeypatch.setattr(receipt, "receipt_page", lambda *a, **k: tmp_path / "page.html")
    monkeypatch.setattr(pages, "open_page", lambda path: True)
    out = ds.ard_open_receipt_page()
    assert out.endswith("deal 01234567: " + screens.ruled_for_buyer(ruled, "Kestrel Print")[0])


def test_a_report_that_fails_after_the_page_opened_says_no_ruling_and_no_error(tmp_path, monkeypatch):
    """Codex on #415: the page opened, then the report for the ruling line failed. The answer still says the page
    opened, names no ruling and no raw error, and the error goes to the party log."""
    import types

    import buyer
    import desktop_server as ds
    import pages
    import party as pt
    import receipt

    deal = buyer.Deal("deal-0123456789abcdef", "kestrel", "k", 1000, "o", "fake", "maya")
    logged = []

    def report(deal_id):
        raise pt.Refused("capsulectl: {\"error\": \"busy\"}")
    p = types.SimpleNamespace(report=report, log=logged.append)
    monkeypatch.setattr(ds, "ROLE", "maya")
    monkeypatch.setattr(ds, "_own_deal", lambda: (p, "Maya", deal.deal_id))
    monkeypatch.setattr(ds, "session", lambda: types.SimpleNamespace(latest=lambda: deal, log=[]))
    monkeypatch.setattr(ds, "_session", None)
    monkeypatch.setattr(receipt, "receipt_page", lambda *a, **k: tmp_path / "page.html")
    monkeypatch.setattr(pages, "open_page", lambda path: True)
    out = ds.ard_open_receipt_page()
    assert "its receipt page opened in the browser" in out and "REFUSED" not in out
    assert "Ruled" not in out and "busy" not in out and any("busy" in line for line in logged)
