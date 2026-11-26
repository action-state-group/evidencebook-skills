# SPDX-License-Identifier: Apache-2.0
"""evidencebook-skills#331 (carrying #335): the buyer's first turn shows her own card and the spending limit she set,
and the assessment shows that limit and whether each price fits it, or says none is set and names the pack's limits.
The words are general: the non-demo test uses a buyer, sellers and amounts outside the demo cast. No binary is run."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

import limits
import screens


def test_a_set_limit_is_shown_as_the_person_set_it():
    assert screens.limit_line(4500, [10, 1000]) == ("Your spending limit: 4,500 msat for one order and over 7 days; each "
                                                    "payment is checked against it.")


def test_no_limit_names_every_limit_of_the_pack_from_the_pack():
    assert screens.limit_line(None, [10000, 10, 1000]) == ("No spending limit is set, so only this pack's limits apply: "
                                                          "deals under 10 msat, 1,000 msat, 10,000 msat, by the seller's "
                                                          "history.")


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
    assert "under 5 msat, 50 msat, 500 msat" in screens.limit_line(None, [500, 5, 50])


def test_the_pack_limits_come_from_the_pack():
    import desktop_server as ds
    import pack as packs
    p = packs.starting()
    assert ds._ceilings(p) == [p.ceiling_msat(t["id"]) for t in p.tiers()] and len(ds._ceilings(p)) == len(p.tiers())


def test_a_bad_limit_refuses_rather_than_reading_as_none(monkeypatch):
    monkeypatch.setenv("ARD_LIMIT_MSAT", "2k")
    with pytest.raises(limits.LimitError):
        limits.limit_msat()


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
    assert "msat" not in maya["facts"]  # her limit is ARD_LIMIT_MSAT; what she will pay comes in her own words


def test_opening_the_windows_refuses_a_bad_limit(monkeypatch, capsys, tmp_path):
    ow = _open_windows()
    monkeypatch.setenv("ARD_LIMIT_MSAT", "-5")
    monkeypatch.setattr(ow.envhelp, "message", lambda *a, **k: "")
    monkeypatch.setattr(ow, "goose_root", lambda: tmp_path / "goose")
    monkeypatch.setattr(ow.reset, "goose_running", lambda: pytest.fail("refused before Goose is looked at"))
    assert ow.main(["--print"]) == 2
    assert "ARD_LIMIT_MSAT must be a whole number" in capsys.readouterr().err
