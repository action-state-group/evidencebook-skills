# SPDX-License-Identifier: Apache-2.0
"""The RUNBOOK's steps that Steven's hand run of 2026-11-26 found missing or wrong, held to the code's own words, so
the walkthrough and Maya's tools cannot drift apart (evidencebook-skills#411, #412, #413, #414)."""
from __future__ import annotations

import re
from pathlib import Path

import screens

RUNBOOK = (Path(__file__).resolve().parents[1] / "RUNBOOK.md").read_text()


def _step(n: int, section: str = "## The run") -> str:
    """Step ``n`` of a section, up to the next step or section."""
    body = RUNBOOK.split(section, 1)[1].split("\n## ", 1)[0]
    m = re.search(rf"^{n}\. (.*?)(?=^\d+\. |\Z)", body, re.M | re.S)
    assert m, f"no step {n} under {section!r}"
    return m.group(1)


def test_maya_opens_her_kestrel_receipt_after_the_ruling_before_ordering_again():
    """#411: after the adjudicator's not-met ruling (step 10) and its entry (step 11), Maya opens her receipt as a page
    while her latest deal is Kestrel's, so the seal shows; then the second order."""
    assert "Rule against Kestrel" in _step(10)
    step = _step(13)
    page, order = step.index("Open your receipt as a page."), step.index("Order 200 more badges.")
    assert page < order
    assert "Didn't go as agreed" in step and "Ruled: Delivery not met" in step


def test_the_limit_question_comes_after_the_search_and_one_yes_sets_only_the_limit():
    """#413."""
    step = _step(2)
    assert "no History card and no assessment yet" in step
    assert "your yes sets the limit and nothing more" in step


def test_dont_buy_quotes_the_holds_sentence_and_the_order_again_question(monkeypatch):
    """#412 and #414: the spending-limit section quotes what Maya says after Don't buy, from the code's own words, on
    the simulated rail the RUNBOOK's run uses (Codex on #415: not the caller's ARD_RAIL)."""
    import desktop_server as ds

    monkeypatch.setenv("ARD_RAIL", "fake")

    reasons = ["over your 7-day limit: 3,000 msat with this order, limit 2,000 msat",
               "no earlier payment to this merchant from this profile", "the payment is not refundable"]
    step = _step(3, "## The spending limit: an order over it")
    assert f'"{screens.rules_held(reasons)}"' in step
    question = re.search(r'"(Want me to order again from [^"]*)"', ds.held_declined("Alder Print Co.", 2000)).group(1)
    assert f'"{question}"' in step
    assert "does not offer to change your spending limit" in step
    assert _step(4, "## The spending limit: an order over it").startswith("Answer her question:")


def test_the_order_again_question_says_real_money_on_a_real_rail(monkeypatch):
    import desktop_server as ds

    monkeypatch.setenv("ARD_RAIL", "lightning")
    assert "for 2,000 msat, over Lightning, which moves real money?" in ds.held_declined("Alder Print Co.", 2000)
