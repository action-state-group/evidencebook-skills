# SPDX-License-Identifier: Apache-2.0
"""The Goose Desktop extension (desktop_server.py) on a fake rail: the tools in the story's order, a
refusal out of order, the LIMIT pick that pays nothing, and the pay step only after a sealed pick.

Needs ``CAPSULE_ENGINE`` and ``ARD_EVIDENCEBOOK`` like test_demo.py; the 48 sample deals take about 20 seconds."""
from __future__ import annotations

import os

import pytest

from conftest import engine_only

pytestmark = engine_only


@pytest.fixture(scope="module")
def tools(tmp_path_factory, seeded_home):
    import os

    home = seeded_home(tmp_path_factory.mktemp("desktop-home"))
    os.environ["ARD_HOME"], os.environ["ARD_RAIL"] = str(home), "fake"
    import desktop_server as ds

    yield ds
    if ds._session is not None:
        ds._session.server.close()
        ds._session.world.close()
        ds._session = None


def test_out_of_order_calls_are_refused_and_change_nothing(tools):
    assert "REFUSED: call ard_find_sellers first" in tools.ard_show_history()
    assert "REFUSED: call ard_show_history first" in tools.ard_assess()


def test_the_story_find_history_assess_limit_then_pay(tools, monkeypatch):
    found = tools.ard_find_sellers()
    assert "Alder Print Co." in found and "Kestrel Print" in found and "commitment verified" in found
    import screens
    assert screens.BANNER_FAKE not in found and "DEMO ·" not in found  # no demo line on the tool's output (Ethan, 2026-11-17)
    history = tools.ard_show_history()
    assert "24 deals counted" in history and "✗" not in history
    assert "History cards" in history and "2 of 24 deals did not hold" in history
    assessed = tools.ard_assess(50)
    assert "Alder Print Co.    GO:" in assessed.split("4b  Assessment again")[1]
    assert "Kestrel Print      LIMIT:" in assessed.split("4b  Assessment again")[1]

    assert "REFUSED: no sealed pick of Alder" in tools.ard_pay("alder")
    limit = tools.ard_pick("kestrel")
    assert "over this seller's limit" in limit and "no deal opens and nothing is paid" in limit
    monkeypatch.setattr(tools, "approve_payment", lambda summary: pytest.fail("a refused pay must not ask for approval"))
    assert "REFUSED: no sealed pick of Kestrel" in tools.ard_pay("kestrel")
    assert tools._session.run.rail.paid == []

    assert "within its limit" in tools.ard_pick("alder")
    # The approval gate: the presenter's dialog decides, never the agent. A refusal pays nothing and can be retried.
    monkeypatch.setattr(tools, "approve_payment", lambda summary: False)
    refused = tools.ard_pay("alder")
    assert "the presenter did not approve" in refused and tools._session.run.rail.paid == []
    # The first call after a refusal opens no dialog: it hands the agent the question to ask Maya first.
    monkeypatch.setattr(tools, "approve_payment", lambda summary: pytest.fail("the call after a refusal must not open the dialog"))
    reask = tools.ard_pay("alder")
    assert reask.startswith("REFUSED: the presenter did not approve the last payment to Alder Print Co.")
    assert 'The question is: "Pay Alder Print Co. 2,000 msat on the simulated rail, where no money moves?"' in reask
    assert "If you asked Maya exactly that since the refusal and she said yes, call ard_pay again now." in reask
    assert "call ard_pay again only after she says yes" in reask and tools._session.run.rail.paid == []
    # A second refusal sets it again: each Cancel is followed by the question before the next dialog.
    monkeypatch.setattr(tools, "approve_payment", lambda summary: False)
    assert "the presenter did not approve" in tools.ard_pay("alder")
    monkeypatch.setattr(tools, "approve_payment", lambda summary: pytest.fail("the call after a refusal must not open the dialog"))
    assert "REFUSED: the presenter did not approve the last payment" in tools.ard_pay("alder")
    asked: list[str] = []
    monkeypatch.setattr(tools, "approve_payment", lambda summary: asked.append(summary) or True)
    paid = tools.ard_pay("alder")
    assert asked == ["Pay Alder Print Co. 2,000 msat on the simulated rail: no money moves."]
    assert "invoice 2,000 msat" in paid and "Alder Print Co.'s card now counts 25 deals" in paid
    assert tools._session.run.rail.paid == [2000]
    assert "REFUSED: Alder Print Co. was already paid" in tools.ard_pay("alder")
    # An attempt that the rail did not confirm is not "paid": the next try says so and sends the presenter to the wallet.
    sess = tools._session
    sess.paid.discard("alder")
    unconfirmed = tools.ard_pay("alder")
    assert "already attempted in this run and is not confirmed" in unconfirmed and "was already paid" not in unconfirmed
    assert tools._session.run.rail.paid == [2000]
    # Maya's own History card as a page: written under the demo home, not opened in a test.
    monkeypatch.setenv("ARD_OPEN_PAGES", "0")
    page = tools.ard_open_card_page()
    assert "Maya: its History card page written (not opened)" in page and "/pages/maya-history-" in page
    # Her receipt as a page: the copy is verified by the capsulectl-deal binary CAPSULECTL_DEAL names.
    receipt_page = tools.ard_open_receipt_page()
    if os.environ.get("CAPSULECTL_DEAL"):
        assert "Maya: its receipt page written (not opened)" in receipt_page and "/pages/maya-receipt-" in receipt_page
    else:
        assert "Maya: no receipt page yet: set CAPSULECTL_DEAL" in receipt_page


def test_an_unknown_seller_is_refused(tools):
    assert "REFUSED: unknown seller" in tools.ard_pick("nobody")


def test_a_second_server_on_the_same_home_is_refused(tools):
    tools.session()  # the first server holds the home
    with pytest.raises(RuntimeError, match="another Goose chat already runs"):
        tools.Session()


def test_the_approval_gate_cannot_be_turned_off_on_a_real_rail(tools, monkeypatch):
    monkeypatch.setenv("ARD_APPROVAL", "none")
    for rail in ("lightning", "local"):
        with pytest.raises(RuntimeError, match=f"ARD_APPROVAL=none is refused on the {rail} rail"):
            tools.approval_gate(True, rail, "Pay")
    tools.approval_gate(False, "fake", "Pay")  # the simulated rail may run without the dialog (the tests do)


def test_a_seller_server_keeps_its_lock(tools, monkeypatch):
    from types import SimpleNamespace

    # A stand-in world: this module's own session already holds Alder's shelf.
    books = [f"deal/d{i}" for i in range(tools.demo.DEALS_EACH)]
    world = SimpleNamespace(nodes={"alder": SimpleNamespace(shelf=SimpleNamespace(books=lambda: books))}, close=lambda: None)
    monkeypatch.setattr(tools.parties, "ProcessWorld", lambda home, roles: SimpleNamespace(open=lambda: world))
    monkeypatch.setattr(tools, "ROLE", "alder")
    monkeypatch.setattr(tools.parties, "ensure_stage", lambda home: None)
    monkeypatch.setattr(tools.parties, "Seller", lambda w, role, card: w)
    try:
        assert tools.seller() is world
        import gc
        gc.collect()  # a dropped handle would be closed here, freeing the lock
        with pytest.raises(RuntimeError, match="another Goose chat already runs the alder side"):
            tools._lock("alder")
    finally:
        tools._seller, tools._seller_lock = None, None


@pytest.mark.skipif(not __import__("test_rules").has_limits_flag(), reason="CAPSULE_ENGINE has no `guard check --limits` (capsule-engine#314)")
def test_with_a_spending_limit_a_second_order_is_held_for_the_persons_ok_and_a_decline_pays_nothing(tools, monkeypatch):
    """Runs after the story: Alder was paid 2,000 msat once. With the person's limit set at that amount, ard_pay takes
    a second order as a new deal; the Everyday Rules hold it at the deal check, the person is asked and declines, and
    the rail is not called."""
    assert tools._session.run.rail.paid == [2000]
    tools._session.paid.add("alder")  # as after a payment the rail reported succeeded (the story test cleared it)
    monkeypatch.setenv("ARD_LIMIT_MSAT", "2000")
    monkeypatch.setattr(tools, "approve_payment", lambda summary: True)
    asked = []
    monkeypatch.setattr(tools, "approve_hold", lambda summary: asked.append(summary) or False)
    second = tools.ard_pay("alder")
    assert "REFUSED:" in second and "Held for your OK at deal check, nothing paid" in second and "limit you set" in second
    assert "limit 2,000 msat" in second and "4,000 msat" in second and "declined" in second
    assert len(asked) == 1 and "Approve this order anyway, or decline?" in asked[0]
    assert tools._session.run.rail.paid == [2000]
    # a held order the person declines is not an attempted payment, and the earlier order stays paid
    assert "alder" not in tools._session.attempted and "alder" in tools._session.paid
    # the same when the check cannot run at all (no engine): nothing paid, the session as it was, and a retry is possible
    monkeypatch.setenv("CAPSULE_ENGINE", "/nonexistent/capsule-engine")
    failed = tools.ard_pay("alder")
    assert "REFUSED:" in failed and "could not run" in failed and "Nothing was paid" in failed
    assert tools._session.run.rail.paid == [2000]
    assert "alder" not in tools._session.attempted and "alder" in tools._session.paid


@pytest.mark.skipif(not __import__("test_rules").has_limits_flag(), reason="CAPSULE_ENGINE has no `guard check --limits` (capsule-engine#314)")
def test_a_declined_payment_dialog_on_a_second_order_keeps_the_seller_paid_and_an_approved_hold_pays(tools, monkeypatch):
    s = tools._session
    assert s.run.rail.paid == [2000] and "alder" in s.paid
    monkeypatch.setenv("ARD_LIMIT_MSAT", "2000")
    # the presenter cancels the payment dialog of the second order: nothing started, the first order still counts as paid
    monkeypatch.setattr(tools, "approve_payment", lambda summary: False)
    assert "the presenter did not approve" in tools.ard_pay("alder")
    assert "alder" in s.paid and "alder" not in s.attempted and s.run.rail.paid == [2000]
    # the next call opens no dialog (it hands the agent the question), and still leaves the seller paid
    assert "opens no dialog" in tools.ard_pay("alder") and "alder" in s.paid
    # now the person clicks Pay, the rules hold the order, and the person approves: the payment goes on
    monkeypatch.setattr(tools, "approve_payment", lambda summary: True)
    monkeypatch.setattr(tools, "approve_hold", lambda summary: True)
    tools.ard_pay("alder")
    assert s.run.rail.paid == [2000, 2000] and "alder" in s.paid


def test_a_declined_or_failed_order_on_the_multi_window_path_leaves_no_deal_id_behind(monkeypatch):
    import types

    import rules as rules_module

    seen = types.SimpleNamespace(opened=[])
    s = types.SimpleNamespace(assessed={"alder": types.SimpleNamespace(price_msat=2000)}, bworld=types.SimpleNamespace(nodes={"alder": object()}),
                              run=types.SimpleNamespace(maya=object(), rail=types.SimpleNamespace(SEALED="simulated"), banner="x"),
                              picked={"alder": "pick"}, deal_ids=["deal-earlier"], paid=set())
    monkeypatch.setattr(tools_module(), "ROLE", "maya")
    monkeypatch.setattr(tools_module().buyer, "open_deal", lambda *a, **k: types.SimpleNamespace(deal_id="deal-new"))
    for stopped in (rules_module.RuleHeld("held", ["why"]), rules_module.RulesError("could not run")):
        def buyer_deal(*a, _stopped=stopped, **k):
            raise _stopped
        monkeypatch.setattr(tools_module().parties, "buyer_deal", buyer_deal)
        with pytest.raises(type(stopped)):
            tools_module()._pay(s, "alder", 2000)
        assert s.deal_ids == ["deal-earlier"] and s.paid == set()


def tools_module():
    import desktop_server

    return desktop_server
