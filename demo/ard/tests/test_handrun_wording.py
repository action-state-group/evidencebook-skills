# SPDX-License-Identifier: Apache-2.0
"""Wording fixes from the 2026-11-24 hand run of the runbook."""
import json

import receipt
import screens


ITEM = "200 conference badges, delivered by Friday"
SIM = "on the simulated rail: no money moves"


def test_the_spending_limit_question_is_steven_s_design_with_the_sealed_figures():
    """evidencebook-skills#270 item 2: title, the item line, three figures from the sealed #7d finding, the foot."""
    title, text = screens.hold_question(ITEM, 2000, {"weekly": (2000, 4000)},
                                        ["over your weekly limit: 4,000 msat with this order, limit 2,000 msat"], True,
                                        seller="Alder Print Co.", rail=SIM)
    assert title == "This order goes over your weekly limit"
    assert text.split("\n") == [
        "200 conference badges, delivered by Friday from Alder Print Co. for 2,000 msat, on the simulated rail: no money "
        "moves. Nothing has been paid yet.",
        "Spent this week: 2,000 msat", "With this order: 4,000 msat", "Your weekly limit: 2,000 msat",
        "Your answer is saved on the receipt. Change your limit any time in Everyday Rules."]
    assert "Held for your OK at deal check" not in text
    assert screens.rules_approved(["over your weekly limit"]).startswith("You approved this order over your limit")


def test_only_the_per_order_limit_names_that_limit_and_its_two_figures():
    title, text = screens.hold_question(ITEM, 3000, {"per_order": (2000, 3000)}, ["over your per-order limit"], True)
    assert title == "This order goes over your per-order limit"
    assert text.split("\n")[1:3] == ["This order: 3,000 msat", "Your per-order limit: 2,000 msat"]
    assert text.startswith(f"{ITEM} for 3,000 msat. Nothing has been paid yet.")


def test_another_rule_holding_the_order_lists_every_reason_with_a_capital_in_place_of_the_figures():
    """#270 item 3 (Sherlock2): the same layout, the reasons in place of the figures, the limit as its figures."""
    reasons = ["over your weekly limit: 4,000 msat with this order, limit 2,000 msat", "no earlier payment to this merchant"]
    title, text = screens.hold_question(ITEM, 2000, {"weekly": (2000, 4000)}, reasons, False, seller="Alder Print Co.",
                                        rail=SIM)
    assert title == "The Everyday Rules held this order for your OK"
    assert text.split("\n")[1:] == [
        "Over your weekly limit: 4,000 msat with this order, limit 2,000 msat", "No earlier payment to this merchant",
        "Your answer is saved on the receipt. Change your rules any time in Everyday Rules."]
    assert "Nothing has been paid yet." in text.split("\n")[0]


def test_approval_lines_say_who_approved_in_plain_words():
    assert receipt._line("approval", {"approver": "user"}, True) == "Approved by you"
    assert "instructions you gave your agent" in receipt._line("approval", {"approver": "standing_intent"}, True)
    assert "standing_intent" not in receipt._line("approval", {"approver": "standing_intent"}, True)
    # #261: no click is claimed or denied under standing intent: that approver now means no one clicked
    assert "click" not in receipt._line("approval", {"approver": "standing_intent"}, True)


def test_a_did_not_hold_note_reads_as_words_not_the_record_type():
    line = receipt._line(receipt.OUTCOME_NOTE, {"outcome": "did_not_hold", "reason": "other"}, True)
    assert line != receipt.OUTCOME_NOTE and "not held up" in line and "other" in line


def test_the_pack_overrides_the_headline_only_when_the_report_says_the_deal_did_not_hold():
    def pack(text):
        bundle = {"extensions": {receipt.REPORT_EXTENSION: {"agent_input": {"report": {"lifecycle": {"text": text}}}}}}
        return json.loads(receipt.wording_pack(bundle))["entries"]

    assert pack(receipt.NOT_HELD + ".")["seller.outcome.completed"] == receipt.NOT_HELD
    plain = pack("Closed: completed.")
    assert plain["seller.outcome.completed"] != receipt.NOT_HELD
    assert plain["page.title"] == "Order receipt" and "No record" not in plain["sides.missing.none"]
