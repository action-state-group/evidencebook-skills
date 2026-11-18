# SPDX-License-Identifier: Apache-2.0
"""The Goose Desktop extension (desktop_server.py) on a fake rail: the tools in the story's order, a
refusal out of order, the LIMIT pick that pays nothing, and the pay step only after a sealed pick.

Needs ``CAPSULE_ENGINE`` and ``ARD_EVIDENCEBOOK`` like test_demo.py; the 48 sample deals take about 20 seconds."""
from __future__ import annotations

import pytest

from conftest import engine_only

pytestmark = engine_only


@pytest.fixture(scope="module")
def tools(tmp_path_factory):
    import os

    import seed
    from world import World

    home = tmp_path_factory.mktemp("desktop-home")
    with World(home) as world:
        seed.seed(world, say=lambda *_: None, kestrel_card="sentinel")
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
    asked: list[str] = []
    monkeypatch.setattr(tools, "approve_payment", lambda summary: asked.append(summary) or True)
    paid = tools.ard_pay("alder")
    assert asked == ["Pay Alder Print Co. 289 msat on the simulated rail: no money moves."]
    assert "invoice 289 msat" in paid and "Alder Print Co.'s card now counts 25 deals" in paid
    assert tools._session.run.rail.paid == [289]
    assert "REFUSED: Alder Print Co. was already paid" in tools.ard_pay("alder")
    # An attempt that the rail did not confirm is not "paid": the next try says so and sends the presenter to the wallet.
    sess = tools._session
    sess.paid.discard("alder")
    unconfirmed = tools.ard_pay("alder")
    assert "already attempted in this run and is not confirmed" in unconfirmed and "was already paid" not in unconfirmed
    assert tools._session.run.rail.paid == [289]
    # Maya's own History card as a page: written under the demo home, not opened in a test.
    monkeypatch.setenv("ARD_OPEN_PAGES", "0")
    page = tools.ard_open_card_page()
    assert "Maya: its History card page written (not opened)" in page and "/pages/maya-history-" in page


def test_an_unknown_seller_is_refused(tools):
    assert "REFUSED: unknown seller" in tools.ard_pick("nobody")


def test_a_second_server_on_the_same_home_is_refused(tools):
    tools.session()  # the first server holds the home
    with pytest.raises(RuntimeError, match="another Goose chat already runs"):
        tools.Session()
