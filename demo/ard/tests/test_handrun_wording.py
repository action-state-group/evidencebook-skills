# SPDX-License-Identifier: Apache-2.0
"""Wording fixes from the 2026-11-24 hand run of the runbook."""
import json

import receipt
import screens


def test_the_hold_dialog_asks_before_it_says_anything_happened():
    ask = screens.rules_ask(["over the limit 2,000 msat"])
    assert "Nothing has been paid yet" in ask and ask.endswith("Approve this order anyway, or decline?")
    assert "Held for your OK at deal check" not in ask
    assert screens.rules_approved(["over the limit 2,000 msat"]).startswith("You approved this order over your limit")


def test_approval_lines_say_who_approved_in_plain_words():
    assert receipt._line("approval", {"approver": "user"}, True) == "Approved by you"
    assert "instructions you gave your agent" in receipt._line("approval", {"approver": "standing_intent"}, True)
    assert "standing_intent" not in receipt._line("approval", {"approver": "standing_intent"}, True)


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
