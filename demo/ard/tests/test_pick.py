# SPDX-License-Identifier: Apache-2.0
"""evidencebook-skills#454: Maya's own pick is sealed as hers, so capsulectl's card never says the agent picked what she
picked; a pick the agent made stays the agent's, and the card says so. No binary is run: Maya's party is a stand-in that
records what it seals (test_e2e's spending-limit test reads the card from the real capsulectl)."""
from __future__ import annotations

import threading
import types

import pytest

import buyer
import desktop_server as ds
from cast import SELLERS


class FakeMaya:
    """Records the notes and intents Maya's party seals."""
    name = "maya"

    def __init__(self):
        self.notes, self.intents, self.picks = [], [], []

    def note(self, record_type, statement, **kw):
        self.notes.append((record_type, statement))
        return {"record_id": f"rec-{len(self.notes)}"}

    def offer(self, to_key, item, price_msat, pack_digest, adjudicator):
        return {"deal_id": "deal-0123456789abcdef", "offer": "o", "file": "offer.json"}

    def intent(self, deal_id, words, kind, allowed, limit_msat, who, **kw):
        self.intents.append((deal_id, words, limit_msat))
        return "intent-1"

    def picked(self, deal_id, words, item):
        self.picks.append((deal_id, words, item))
        return "intent-2"


@pytest.mark.parametrize("words,seller,named", [
    ("Pick Kestrel Print, the cheaper one.", "kestrel", True),
    ("Pick Alder Print Co.", "alder", True),
    ("alder please", "alder", True),
    ("the cheaper one", "kestrel", False),  # no seller named: the agent's pick
    ("Choose between Alder and Kestrel yourself.", "alder", False),  # two sellers named
    ("Not Alder; pick Kestrel.", "alder", False),
    ("Pick Kestrel Print.", "alder", False),  # another seller
    ("Print", "kestrel", False),  # a word both labels share names neither
])
def test_her_words_are_her_pick_only_when_they_name_that_seller_alone(words, seller, named):
    assert buyer.names_only(words, seller) is named


def _assessment(verdict="GO"):
    return types.SimpleNamespace(price_msat=1000, verdict=verdict, record_id="assess-1", pack_digest="p", cap_msat=None)


@pytest.mark.parametrize("said,by", [("Pick Kestrel Print, the cheaper one.", "maya"), ("", "agent")])
def test_the_sealed_pick_names_who_picked(said, by):
    maya = FakeMaya()
    buyer.seal_pick(maya, "k" * 64, _assessment(), [], said)
    (kind, st), = maya.notes
    assert kind == buyer.PICKED and st["by"] == by
    assert st.get("said") == (said or None)


@pytest.mark.parametrize("picked", ["Pick Kestrel Print, the cheaper one.", ""])
def test_her_pick_is_sealed_after_her_ask_with_the_checks_own_item(picked):
    """purchase.md, "The user picked from options": the opening intent holds her ask and her limit; her pick follows as
    its own intent, her words and the item exactly as the check writes it. The agent's pick seals no such intent."""
    maya = FakeMaya()
    deal = buyer.draft_deal(maya, "kestrel", "k" * 64, _assessment(), {}, rail="simulated", me="maya", limit=3000,
                            request="I need 200 conference badges by Friday, under 3,000 msat.", picked=picked)
    assert maya.intents == [(deal.deal_id, "I need 200 conference badges by Friday, under 3,000 msat.", 3000)]
    assert deal.intent == "intent-1"  # the agreement cites the opening intent, as before
    assert maya.picks == ([(deal.deal_id, picked, SELLERS["kestrel"]["item"])] if picked else [])


@pytest.fixture
def session(monkeypatch):
    maya = FakeMaya()
    s = types.SimpleNamespace(maya=maya, home=None, keys={"alder": "ka", "kestrel": "kk"}, ask="200 badges by Friday",
                              assessed={"alder": _assessment(), "kestrel": _assessment()}, picked={}, declined={},
                              adjudicator=types.SimpleNamespace(named=dict), rail=None, pay_lock=threading.Lock(),
                              deals=[], log=[])
    monkeypatch.setattr(ds, "session", lambda: s)
    monkeypatch.setattr(ds, "_session", None)
    monkeypatch.setattr(ds, "_real", lambda: False)
    monkeypatch.setattr(ds, "gate_off", lambda: True)
    paid = []

    def open_and_pay(home, maya, seller, key, chosen, adjudicator, rail, summary, ask, say, **kw):
        paid.append((seller, kw.get("picked")))
        ask(buyer.Question("Approve this payment", "text", "Pay", "Cancel"))
        return None
    monkeypatch.setattr(buyer, "open_and_pay", open_and_pay)
    s.paid = paid
    return s


@pytest.mark.parametrize("said", ["Pick Kestrel Print, the cheaper one.", ""])
def test_the_pick_travels_from_ard_pick_to_the_payment(session, said):
    """The words ard_pick takes reach the payment, on every ard_pay for that pick (a retry after a no included); with
    none, the payment carries none, so the card says the agent picked."""
    out = ds.ard_pick("kestrel", said)
    assert "REFUSED" not in out, out
    assert session.picked == {"kestrel": said}
    assert session.maya.notes[-1][1]["by"] == ("maya" if said else "agent")
    ds.ard_pay("kestrel")
    ds.ard_pay("kestrel")
    assert session.paid == [("kestrel", said), ("kestrel", said)]


def test_words_that_do_not_name_the_seller_alone_are_refused_and_seal_nothing(session):
    out = ds.ard_pick("alder", "Choose between Alder and Kestrel yourself.")
    assert out.startswith("REFUSED") and "do not name Alder Print Co. alone" in out, out
    assert session.maya.notes == [] and session.picked == {}


def test_a_new_search_clears_the_pick_and_its_words(session, monkeypatch):
    ds.ard_pick("kestrel", "Pick Kestrel Print.")
    monkeypatch.setattr(ds.ard, "lookup", lambda *a: [])
    monkeypatch.setattr(buyer, "record_search", lambda *a: None)
    ds.ard_find_sellers("30 lanyards by Monday")
    assert session.picked == {}
