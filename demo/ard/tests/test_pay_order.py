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

    def wait_file(path, seconds, unless=None):
        waits.append((path.name, seconds, unless and unless.name))
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
    assert waits == [("d1.m2.json", parties.SELLER_PAID_HALF_WAIT_S, "d1.withdrawn.json")]


def test_the_sellers_wait_covers_every_step_between_its_half_and_the_paid_half_at_its_own_timeout():
    import pay
    import rules

    # the deal check, the dialog (and its osascript slack) and the slowest rail's payment, each at its own timeout
    worst = rules.CHECK_TIMEOUT_S + parties.DIALOG_GIVE_UP_S + parties.DIALOG_SLACK_S + pay.MAX_PAY_S
    assert parties.SELLER_PAID_HALF_WAIT_S > worst
    assert pay.MAX_PAY_S >= pay.INVOICE_TIMEOUT_S + pay.SEND_TIMEOUT_S and pay.MAX_PAY_S >= 2 * pay.CONTROL_TIMEOUT_S


def test_wait_file_returns_none_when_the_order_is_withdrawn(tmp_path):
    (tmp_path / "d1.withdrawn.json").write_text("{}")
    assert parties.wait_file(tmp_path / "d1.m2.json", 5, unless=parties.withdrawn(tmp_path, "d1")) is None
    (tmp_path / "d1.m2.json").write_text('{"x": 1}')
    assert parties.wait_file(tmp_path / "d1.m2.json", 5, unless=parties.withdrawn(tmp_path, "d1")) == {"x": 1}


@pytest.mark.parametrize("stop", [parties.rules.RuleHeld("declined", []), parties.rules.RulesError("could not ask")])
def test_an_order_the_buyer_does_not_pay_is_withdrawn_so_the_seller_stops_waiting(tmp_path, monkeypatch, stop):
    # a Don't buy, no answer or a check that could not run: nothing is paid, and the seller must not stay blocked on
    # the paid half (it handles one order at a time, so a reorder right after would find it busy)
    monkeypatch.setattr(parties.deals, "_reconcile", lambda *a, **k: None)
    monkeypatch.setattr(parties, "wait_file", lambda *a, **k: {})
    def gate(*a, **k):
        raise stop
    monkeypatch.setattr(parties.rules, "gate", gate)
    maya = types.SimpleNamespace(half=lambda d: {}, deal=lambda d: None)
    peer = types.SimpleNamespace(home=tmp_path, id="alder")
    chain = types.SimpleNamespace(deal_id="d1")
    rail = types.SimpleNamespace(pay=lambda msat: pytest.fail("nothing may be paid"))
    with pytest.raises(type(stop)):
        parties.buyer_deal(maya, peer, chain, rail, 2000, limit=2000)
    assert parties.withdrawn(tmp_path / "stage" / "wire" / "alder", "d1").is_file()


def test_a_withdrawn_order_frees_the_seller_without_an_error(tmp_path, monkeypatch):
    said = []
    monkeypatch.setattr(parties, "wait_file", lambda path, seconds, unless=None: None)
    monkeypatch.setattr(parties, "write_atomic", lambda *a, **k: None)
    monkeypatch.setattr(parties.deals, "admit", lambda *a, **k: None)
    monkeypatch.setattr(parties, "world_terms", lambda item, price, currency, rail, refundable: types.SimpleNamespace(
        item=item, price_minor=price))
    chain = types.SimpleNamespace(respond=lambda *a: None)
    node = types.SimpleNamespace(verify_peer_half=lambda m1: {"key_id": "k", "records": [{"digest": "d"}]},
                                 new_deal=lambda *a: chain, open_deal=lambda *a: None, half=lambda d: {},
                                 close_deal=lambda *a: pytest.fail("a withdrawn order is not closed as a sale"))
    seller = types.SimpleNamespace(node=node, dir=tmp_path, name="alder", say=said.append, deal_ids=[])
    body = {"terms": {"item": "badges", "price_minor": parties.SELLERS["alder"]["price_msat"], "currency": "BTC"},
            "recourse": {"rail": "fake", "refundable": False}}
    m1 = {"steps": [{"capsule": {"key_id": "k"}, "payload": {"body": body}}], "checkpoint": {"key_id": "c"}}
    parties.Seller.deal(seller, "d1", m1)
    assert said[-1].startswith("the buyer ended this order before paying: nothing was paid")


@pytest.mark.parametrize("error,withdraws", [(parties.pay.NotSent("no invoice"), True),
                                             (parties.pay.RailError("send timed out"), False)])
def test_a_payment_that_failed_before_the_send_withdraws_and_any_other_failure_does_not(tmp_path, monkeypatch, error,
                                                                                          withdraws):
    monkeypatch.setattr(parties.deals, "_reconcile", lambda *a, **k: None)
    monkeypatch.setattr(parties, "wait_file", lambda *a, **k: {})
    maya = types.SimpleNamespace(half=lambda d: {})
    peer = types.SimpleNamespace(home=tmp_path, id="alder")
    chain = types.SimpleNamespace(deal_id="d1")
    def failing(msat):
        raise error
    with pytest.raises(type(error)):
        parties.buyer_deal(maya, peer, chain, types.SimpleNamespace(pay=failing), 2000)
    assert parties.withdrawn(tmp_path / "stage" / "wire" / "alder", "d1").is_file() is withdraws


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def time(self):
        return self.now


def _late_order(tmp_path, monkeypatch, answer_after: float):
    """A held order whose person answers ``answer_after`` seconds after the buyer asked the seller to deal."""
    clock = _Clock()
    monkeypatch.setattr(parties.time, "time", clock.time)
    monkeypatch.setattr(parties.deals, "_reconcile", lambda *a, **k: None)
    monkeypatch.setattr(parties, "wait_file", lambda *a, **k: {})
    def gate(*a, **k):
        clock.now += answer_after  # the dialog, then the person's yes
        return None
    monkeypatch.setattr(parties.rules, "gate", gate)
    paid = []
    rail = types.SimpleNamespace(pay=lambda msat: paid.append(msat) or types.SimpleNamespace(status="succeeded", reference="r"))
    maya = types.SimpleNamespace(half=lambda d: {}, deal=lambda d: None)
    peer = types.SimpleNamespace(home=tmp_path, id="alder")
    return maya, peer, rail, paid


def test_a_yes_at_the_dialogs_last_second_is_still_paid_inside_the_sellers_wait(tmp_path, monkeypatch):
    # #289's case: the person answers just before the dialog gives up; the seller must still be waiting for the payment
    maya, peer, rail, paid = _late_order(tmp_path, monkeypatch,
                                         parties.rules.CHECK_TIMEOUT_S + parties.DIALOG_GIVE_UP_S + parties.DIALOG_SLACK_S)
    with pytest.raises(AttributeError):  # the stub has no seal: the steps after the payment are not under test here
        parties.buyer_deal(maya, peer, types.SimpleNamespace(deal_id="d1"), rail, 2000, limit=2000)
    assert paid == [2000] and not parties.withdrawn(tmp_path / "stage" / "wire" / "alder", "d1").exists()


def test_the_buyer_never_pays_when_the_seller_may_have_stopped_waiting(tmp_path, monkeypatch):
    # if a step ever takes longer than its bound, the buyer withdraws instead of paying a seller that may be gone
    maya, peer, rail, paid = _late_order(tmp_path, monkeypatch, parties.SELLER_PAID_HALF_WAIT_S - parties.pay.MAX_PAY_S - parties.AFTER_PAY_S + 1)
    with pytest.raises(parties.gn.Refused, match="too late to pay safely"):
        parties.buyer_deal(maya, peer, types.SimpleNamespace(deal_id="d1"), rail, 2000, limit=2000)
    assert paid == [] and parties.withdrawn(tmp_path / "stage" / "wire" / "alder", "d1").is_file()
