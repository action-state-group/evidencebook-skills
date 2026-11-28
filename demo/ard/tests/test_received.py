# SPDX-License-Identifier: Apache-2.0
"""Run finding F10 (evidencebook-skills#304): Maya's statement that she received what she paid for is sealed only after
her own yes. A delivery's arrival, in the payment tool or when her agent picks it up later, says nothing in her name.
No binary is run: Maya's party is a stand-in that records every statement and note."""
from __future__ import annotations

import pytest

import buyer
import desktop_server as ds
import flow


class FakeMaya:
    name = "maya"

    def __init__(self):
        self.statements, self._notes = [], []

    def statement(self, deal_id, rows):
        self.statements.append((deal_id, rows))
        return "statement.json"

    def note(self, record_type, statement, **kw):
        self._notes.append({"type": record_type, "statement": statement})

    def notes(self, record_type=""):
        return [n for n in self._notes if not record_type or n["type"] == record_type]


DEAL = buyer.Deal(deal_id="deal-0123456789abcdef", seller="alder", seller_key="k" * 64, price_msat=2000, offer="o",
                  rail="simulated", me="maya")


@pytest.fixture
def sent(monkeypatch):
    out = []
    monkeypatch.setattr(buyer.wire, "send", lambda home, to, deal_id, kind, f: out.append((to, deal_id, kind)))
    return out


def test_a_full_delivery_picked_up_seals_nothing_in_mayas_name(tmp_path, monkeypatch, sent):
    maya = FakeMaya()
    monkeypatch.setattr(buyer, "deals_from_notes", lambda m: [DEAL])
    monkeypatch.setattr(buyer, "paid", lambda home, deal: True)
    monkeypatch.setattr(buyer, "take_delivery", lambda home, m, deal: "delivered:badges_200_of_200")
    said = []
    assert buyer.pick_up_deliveries(tmp_path, maya, said.append) == [DEAL.deal_id]
    assert maya.statements == [] and sent == []
    assert "Nothing has been sent in Maya's name" in said[-1]


@pytest.fixture
def session(tmp_path, monkeypatch):
    maya = FakeMaya()
    import threading
    s = type("S", (), {})()
    s.home, s.maya, s.deals, s.pay_lock = tmp_path, maya, [DEAL], threading.Lock()  # as Session: never taken twice
    s.ask = "200 badges by Friday"  # her ask, as ard_find_sellers keeps it
    s.latest = lambda key=None: s.deals[-1]
    monkeypatch.setattr(ds, "session", lambda: s)
    monkeypatch.setattr(buyer, "take_delivery", lambda home, m, deal: "delivered:badges_200_of_200")
    monkeypatch.delenv("ARD_APPROVAL", raising=False)
    return s


@pytest.mark.parametrize("how,words", [(ds.NO, "Maya chose Cancel"), (ds.NO_ANSWER, "Maya did not answer in time"),
                                       (ds.NOT_SHOWN, "the dialog could not be shown")])
def test_no_yes_seals_no_received_statement(session, monkeypatch, sent, how, words):
    monkeypatch.setattr(ds, "dialog_answer", lambda *a, **k: how)
    out = ds.ard_confirm_received("alder")
    assert f"REFUSED: {words}, so nothing was sent in Maya's name" in out and "presenter" not in out, out
    assert session.maya.statements == [] and sent == []


def test_her_yes_seals_it_once(session, monkeypatch, sent):
    asked = []
    monkeypatch.setattr(ds, "dialog_answer", lambda title, text, yes, no="Cancel": asked.append(text) or "yes")
    assert "Maya's statement sent to Alder Print Co." in ds.ard_confirm_received("alder")
    assert "already said she received it" in ds.ard_confirm_received("alder")  # a second ask seals nothing more
    assert session.maya.statements == [(DEAL.deal_id, {buyer.pt.PAID: "met", buyer.pt.DELIVERED: "met"})]
    assert sent == [("alder", DEAL.deal_id, "statement")] and len(asked) == 1
    assert asked[0] == ("Did you receive what you paid for from Alder Print Co.? Its delivery record says 200 of 200 badges "
                        "were shipped. Choosing Received sends Alder Print Co. your statement that you received it.")


def test_a_disputed_delivery_cannot_be_confirmed(session, monkeypatch, sent):
    session.maya.note(buyer.flow.CASE, {"deal_id": DEAL.deal_id})
    monkeypatch.setattr(ds, "dialog_answer", lambda *a, **k: "yes")
    out = ds.ard_confirm_received("alder")
    assert "REFUSED:" in out and "her dispute stands" in out, out
    assert session.maya.statements == [] and sent == []
    with pytest.raises(buyer.pt.Refused, match="dispute stands"):
        buyer.close_received(session.home, session.maya, DEAL)


def test_two_deals_to_confirm_ask_which(session, monkeypatch, sent):
    import dataclasses
    second = dataclasses.replace(DEAL, deal_id="deal-fedcba9876543210")
    session.deals.append(second)
    asked = []
    monkeypatch.setattr(ds, "dialog_answer", lambda *a, **k: asked.append(a) or "yes")
    out = ds.ard_confirm_received("alder")
    assert "REFUSED:" in out and "01234567" in out and "fedcba98" in out and asked == [], out
    assert "statement sent" in ds.ard_confirm_received("alder", "deal-0123")
    assert session.maya.statements == [(DEAL.deal_id, {buyer.pt.PAID: "met", buyer.pt.DELIVERED: "met"})]


def test_the_payment_tool_seals_nothing_after_a_full_delivery(session, monkeypatch, sent):
    import types
    a = types.SimpleNamespace(price_msat=2000)
    session.picked, session.assessed, session.keys, session.declined = {"alder": ""}, {"alder": a}, {"alder": "k"}, {}
    session.rail = None
    session.adjudicator = types.SimpleNamespace(named=lambda: {})
    monkeypatch.setenv("ARD_APPROVAL", "none")
    monkeypatch.setattr(ds, "_real", lambda: False)
    pay = types.SimpleNamespace(invoice_msat=2000, status="succeeded", fee_msat=0)
    monkeypatch.setattr(buyer, "open_and_pay", lambda *a, **k: (DEAL, pay))
    monkeypatch.setattr(buyer, "await_delivery", lambda *a, **k: "delivered:badges_200_of_200")
    out = ds.ard_pay("alder")
    assert "REFUSED" not in out and "Nothing has been sent in Maya's name" in out, out
    assert session.maya.statements == [] and sent == []


@pytest.mark.parametrize("yes", [False, True])
def test_the_run_scripts_receipt_question(tmp_path, sent, yes):
    maya, said = FakeMaya(), []
    assert buyer.confirm_by_question(tmp_path, maya, DEAL, "Alder Print Co.", lambda q: yes, said.append) is yes
    assert len(maya.statements) == (1 if yes else 0) and len(sent) == (1 if yes else 0)
    assert said == (["Maya's statement sent: she received what she paid for."] if yes else ["Nothing was sent in Maya's name."])


@pytest.mark.parametrize("named", ["", "deal-0123456789abcdef", "0123"])
def test_a_disputed_deal_named_or_not_is_reported_as_disputed(session, monkeypatch, sent, named):
    session.maya.note(buyer.flow.CASE, {"deal_id": DEAL.deal_id})
    monkeypatch.setattr(ds, "dialog_answer", lambda *a, **k: "yes")
    out = ds.ard_confirm_received("alder", named)
    assert "REFUSED:" in out and "her dispute stands" in out and "already said" not in out, out
    assert session.maya.statements == [] and sent == []


@pytest.mark.parametrize("named", ["deal-ffff", "nope"])
def test_an_unknown_deal_is_refused_not_reported_confirmed(session, monkeypatch, sent, named):
    monkeypatch.setattr(ds, "dialog_answer", lambda *a, **k: "yes")
    out = ds.ard_confirm_received("alder", named)
    assert "REFUSED:" in out and "no deal with Alder Print Co. matches" in out and "already said" not in out, out
    assert session.maya.statements == [] and sent == []


def test_the_pick_result_names_no_tool(monkeypatch):
    # Steven's 2fa6abe run (#362): the pick said "Call ard_pay" and the agent repeated the tool name to the person
    import types
    s = types.SimpleNamespace(assessed={"alder": types.SimpleNamespace(price_msat=2000, verdict="GO")}, keys={"alder": "k"},
                              maya=FakeMaya(), picked={})
    monkeypatch.setattr(ds, "session", lambda: s)
    monkeypatch.setattr(buyer, "seal_pick", lambda *a, **k: None)
    out = ds.ard_pick("alder")
    assert "REFUSED" not in out and s.picked == {"alder": ""}, out
    assert "ard_" not in out and "is within its limit. Ask Maya whether to pay it; nothing is paid until she says yes." in out, out
