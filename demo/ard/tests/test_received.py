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
    s = type("S", (), {})()
    s.home, s.maya, s.deals = tmp_path, maya, [DEAL]
    s.latest = lambda key=None: DEAL
    monkeypatch.setattr(ds, "session", lambda: s)
    monkeypatch.setattr(buyer, "take_delivery", lambda home, m, deal: "delivered:badges_200_of_200")
    monkeypatch.delenv("ARD_APPROVAL", raising=False)
    return s


@pytest.mark.parametrize("how", [ds.NO, ds.NO_ANSWER, ds.NOT_SHOWN])
def test_no_yes_seals_no_received_statement(session, monkeypatch, sent, how):
    monkeypatch.setattr(ds, "dialog_answer", lambda *a, **k: how)
    out = ds.ard_confirm_received("alder")
    assert "REFUSED:" in out and "nothing was sent in Maya's name" in out, out
    assert session.maya.statements == [] and sent == []


def test_her_yes_seals_it_once(session, monkeypatch, sent):
    asked = []
    monkeypatch.setattr(ds, "dialog_answer", lambda title, text, yes, no="Cancel": asked.append(text) or "yes")
    assert "Maya's statement sent to Alder Print Co." in ds.ard_confirm_received("alder")
    assert "already said she received it" in ds.ard_confirm_received("alder")  # a second ask seals nothing more
    assert session.maya.statements == [(DEAL.deal_id, {buyer.pt.PAID: "met", buyer.pt.DELIVERED: "met"})]
    assert sent == [("alder", DEAL.deal_id, "statement")] and len(asked) == 1
    assert "200 of 200 badges" in asked[0] and asked[0].startswith("Did you receive what you paid for from Alder Print Co.")
