"""evidencebook-skills#350: a seller's History card carries its witness's receipt for the card's anchor, and
``verify --bundle`` reports that check as ``reader_witnesses`` (evidencebook#957); the core ``witnesses`` row beside it
is about the card bundle's own log and reads ``withheld``. What Maya is told follows ``reader_witnesses`` only."""
from __future__ import annotations

import html
import json

import pytest

import buyer
import flow
import pages
import party as pt
import screens
from test_received import FakeMaya

SELLER = {"id": "alder", "name": "Alder Print Co.", "commitment": {"key_id": "k"}}


def report(stamp: str | None, verdict: str = "VALID") -> dict:
    """verify's report of a card: the core row is always withheld; ``reader_witnesses`` only when a receipt is carried."""
    out = {"verdict": verdict, "witnesses": {"status": "withheld"}}
    if stamp is not None:
        out["reader_witnesses"] = {"status": stamp, "receipts": [{"via": "card_anchor"}] if stamp == "pass" else []}
    return out


class Reader:
    """A buyer's party as fetch_card uses it: a scratch path and ``verify``."""

    def __init__(self, tmp_path, out: dict):
        self.tmp_path, self.out = tmp_path, out

    def tmp(self, name: str) -> str:
        return str(self.tmp_path / name)

    def verify(self, bundle):
        return self.out


def stage_card(home, seller: str = "alder") -> None:
    card = {"derivation": pt.CARD_DERIVATION, "outcomes": {}}
    doc = {"records": [{"capsule_id": "c1", "key_id": "k"}], "disclosures": {"c1": {"agent_input": card}},
           "extensions": {"x-standard-history/v0": {"as_of": {"anchor": "a" * 64,
                                                              "anchor_time": "2026-11-25T22:00:00Z"}}}}
    path = flow.stage_dir(home) / "cards" / f"{seller}.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(doc))


@pytest.mark.parametrize("stamp, status", [("pass", "pass"), ("withheld", "withheld"), (None, "")])
def test_fetch_card_reads_the_cards_stamp_from_reader_witnesses_never_the_core_row(tmp_path, stamp, status):
    stage_card(tmp_path)
    read = flow.fetch_card(tmp_path, Reader(tmp_path, report(stamp)), "alder", "k")
    assert read.witness_status == status


def test_a_stamp_receipt_that_does_not_check_out_refuses_the_card_in_words(tmp_path):
    stage_card(tmp_path)
    with pytest.raises(pt.Refused) as exc:
        flow.fetch_card(tmp_path, Reader(tmp_path, report("fail", verdict="INVALID")), "alder", "k")
    assert str(exc.value) == "Alder Print Co.'s card does not verify: its time-stamp receipt does not check out"
    # any other INVALID still names the verdict
    with pytest.raises(pt.Refused, match="does not verify: INVALID$"):
        flow.fetch_card(tmp_path, Reader(tmp_path, report(None, verdict="INVALID")), "alder", "k")


def gathered(monkeypatch, tmp_path, status: str) -> list[str]:
    read = flow.CardRead(card={"outcomes": {}}, anchor="a" * 64, anchor_time="2026-11-25T22:00:00Z", signer="k",
                         verdict="VALID", witness_status=status, file=tmp_path / "c.json")
    monkeypatch.setattr(flow, "fetch_card", lambda home, m, seller, key: read)
    m = FakeMaya()
    m.note = lambda *a, **k: {"record_id": "r"}
    return screens.check_lines(buyer.gather(tmp_path, m, SELLER))[1:]


def test_a_card_whose_stamp_receipt_passed_reads_time_stamped(monkeypatch, tmp_path):
    assert gathered(monkeypatch, tmp_path, "pass") == [
        "✓ witness: time-stamped by Action State's witness: its receipt verifies under the witness's key"]


def test_a_card_whose_stamp_receipt_could_not_be_checked_says_so(monkeypatch, tmp_path):
    assert gathered(monkeypatch, tmp_path, "withheld") == [
        "– witness: not checked: the card carries a time-stamp receipt this buyer could not check"]


def test_a_card_with_no_stamp_receipt_says_so(monkeypatch, tmp_path):
    assert gathered(monkeypatch, tmp_path, "") == [
        "– witness: not checked: the card carries no time-stamp receipt"]


def test_no_line_still_says_no_receipt_is_available_to_the_buyer(monkeypatch, tmp_path):
    # the #891 line, false since evidencebook#957
    for status in ("pass", "withheld", ""):
        assert not any("available to the buyer" in line for line in gathered(monkeypatch, tmp_path, status))


def test_the_operator_note_names_the_witness_only_for_cards_whose_receipt_is_not_checked():
    # Sherlock2 on #350 (option c): a passing receipt shows only that the stamp came from the key the operator named
    assert screens.operator_note(0, 2) == screens.OPERATOR_NOTE  # PM's words, unchanged when none was checked
    assert screens.operator_note(0, 0) == screens.OPERATOR_NOTE
    assert screens.operator_note(1, 2) == (
        "Some inputs were set by the operator and not checked: which marketplace the seller is on, the list of sellers "
        "this pack accepts, who time-stamps a seller's card whose receipt is not checked, which key belongs to the "
        "witness, and who controls the seller's key.")
    assert screens.operator_note(2, 2) == (
        "Some inputs were set by the operator and not checked: which marketplace the seller is on, the list of sellers "
        "this pack accepts, which key belongs to the witness, and who controls the seller's key.")


class OwnCard:
    name = "alder"

    def __init__(self, tmp_path, out: dict):
        self.tmp_path, self.out = tmp_path, out

    def stamp(self):
        pass

    def card_bundle(self, shared):
        card = {"outcomes": {"of": 1, "held": 1, "did_not_hold": 0, "undecided": 0}}
        doc = {"records": [{"capsule_id": "c1"}], "disclosures": {"c1": {"agent_input": card}},
               "extensions": {"x-standard-history/v0": {"as_of": {"anchor_time": "2026-11-25T18:00:00Z"}, "deals": [
                   {"deal": "deal-0123456789abcdef", "role": "provided", "agreed_at": "2026-11-25T17:00:00Z",
                    "amount": {"value": "10.00", "currency": "USD"}, "rows": [], "happened": "stamped_by_both"}]}}}
        path = self.tmp_path / "card.json"
        path.write_text(json.dumps(doc))
        return path

    def verify(self, bundle):
        return self.out


@pytest.mark.parametrize("stamp, witnessed", [("pass", True), ("withheld", False), (None, False)])
def test_a_partys_own_card_page_is_time_stamped_only_when_its_receipt_passed(monkeypatch, tmp_path, stamp, witnessed):
    monkeypatch.setattr(pages, "home", lambda: tmp_path)
    text = pages.card_page(OwnCard(tmp_path, report(stamp)), "Alder Print Co.", rail="simulated", seller=True).read_text()
    assert (html.escape(pages.WITNESS_NOTE) in text) is witnessed
    assert ('{"id": "witness", "status": "pass"}' in text) is witnessed


def test_a_partys_own_card_page_never_draws_a_failed_receipt_as_not_run(monkeypatch, tmp_path):
    monkeypatch.setattr(pages, "home", lambda: tmp_path)
    with pytest.raises(pt.Refused) as exc:
        pages.card_page(OwnCard(tmp_path, report("fail", verdict="INVALID")), "Alder Print Co.", rail="simulated",
                        seller=True)
    assert str(exc.value) == "Your History card does not verify: its time-stamp receipt does not check out."
