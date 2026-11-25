# SPDX-License-Identifier: Apache-2.0
"""parties.buyer_deal tells its caller the moment the rail reports a payment, before the steps that can still fail:
money that moved must be recorded as paid even if the seller's half or the close never comes."""
from __future__ import annotations

import types

import pytest

import parties


def test_on_paid_runs_before_the_steps_after_the_payment(tmp_path, monkeypatch):
    monkeypatch.setattr(parties.deals, "_reconcile", lambda *a, **k: None)
    monkeypatch.setattr(parties, "wait_file", lambda *a, **k: {})
    monkeypatch.setattr(parties, "write_atomic", lambda *a, **k: None)
    maya = types.SimpleNamespace(half=lambda d: {})  # no seal: the step after the payment fails
    peer = types.SimpleNamespace(home=tmp_path, id="alder")
    chain = types.SimpleNamespace(deal_id="d1")
    payment = types.SimpleNamespace(status="succeeded", reference="r")
    rail = types.SimpleNamespace(pay=lambda msat: payment)
    seen = []
    with pytest.raises(AttributeError):
        parties.buyer_deal(maya, peer, chain, rail, 289, on_paid=seen.append)
    assert seen == [payment]


class _Waited(Exception):
    pass


def test_the_seller_waits_for_the_paid_half_longer_than_the_buyers_dialog_can_take(tmp_path, monkeypatch):
    # evidencebook-skills#289: the buyer asks the person (a dialog that gives up after DIALOG_GIVE_UP_S) only after the
    # seller has sent its first half, then pays; a seller that stopped waiting first left a paid order with no deal.
    waits = []

    def wait_file(path, seconds):
        waits.append((path.name, seconds))
        raise _Waited

    monkeypatch.setattr(parties, "wait_file", wait_file)
    monkeypatch.setattr(parties, "write_atomic", lambda *a, **k: None)
    monkeypatch.setattr(parties.deals, "admit", lambda *a, **k: None)
    monkeypatch.setattr(parties, "world_terms", lambda item, price, currency, rail, refundable: types.SimpleNamespace(
        item=item, price_minor=price))
    chain = types.SimpleNamespace(respond=lambda *a: None)
    node = types.SimpleNamespace(verify_peer_half=lambda m1: {"key_id": "k", "records": [{"digest": "d"}]},
                                 new_deal=lambda *a: chain, open_deal=lambda *a: None, half=lambda d: {})
    seller = types.SimpleNamespace(node=node, dir=tmp_path, name="alder", say=lambda *a: None, deal_ids=[])
    body = {"terms": {"item": "badges", "price_minor": parties.SELLERS["alder"]["price_msat"], "currency": "BTC"},
            "recourse": {"rail": "fake", "refundable": False}}
    m1 = {"steps": [{"capsule": {"key_id": "k"}, "payload": {"body": body}}], "checkpoint": {"key_id": "c"}}
    with pytest.raises(_Waited):
        parties.Seller.deal(seller, "d1", m1)
    assert waits == [("d1.m2.json", parties.SELLER_PAID_HALF_WAIT_S)]
    assert parties.SELLER_PAID_HALF_WAIT_S >= parties.DIALOG_GIVE_UP_S + 60  # room for the payment after a late yes
