"""evidencebook-skills#350: a seller's History card carries its witness's receipt for the card's anchor, and
``verify --bundle`` reports that check as ``reader_witnesses`` (evidencebook#957); the core ``witnesses`` row beside it
is about the card bundle's own log and reads ``withheld``. What Maya is told follows ``reader_witnesses`` only."""
from __future__ import annotations

import html
import json
import time

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

    def verify(self, bundle, report_on_fail=False):
        assert report_on_fail  # the report of a failed verdict says which check failed
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
    # any other failed verdict says capsulectl reported it (Sherlock2 on #350)
    with pytest.raises(pt.Refused) as exc:
        flow.fetch_card(tmp_path, Reader(tmp_path, report(None, verdict="INVALID")), "alder", "k")
    assert str(exc.value) == "Alder Print Co.'s card does not verify: capsulectl deal verify reported it INVALID."
    with pytest.raises(pt.Refused) as exc:
        flow.fetch_card(tmp_path, Reader(tmp_path, report(None, verdict="INCOMPLETE")), "alder", "k")
    assert str(exc.value) == ("Alder Print Co.'s card could not be fully checked: capsulectl deal verify reported it "
                              "INCOMPLETE, because part of what it covers is withheld or missing from the file.")


def test_a_failed_card_with_no_disclosed_card_is_refused_not_read(tmp_path):
    # Codex on #350: verify reports INVALID with reader_witnesses fail for a bundle missing its agent_input
    path = flow.stage_dir(tmp_path) / "cards" / "alder.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"records": [{"capsule_id": "c1", "key_id": "k"}], "disclosures": {}}))
    with pytest.raises(pt.Refused, match="does not verify: its time-stamp receipt does not check out$"):
        flow.fetch_card(tmp_path, Reader(tmp_path, report("fail", verdict="INVALID")), "alder", "k")


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


SAMPLE_DEALS = [{"deal": "deal-0123456789abcdef", "role": "provided", "agreed_at": "2026-11-25T17:00:00Z",
                 "amount": {"value": "10.00", "currency": "USD"}, "rows": [], "happened": "stamped_by_both"}]
ABSENT = object()


class OwnCard:
    name = "alder"

    def __init__(self, tmp_path, out: dict, deals=SAMPLE_DEALS):
        self.tmp_path, self.out, self.deals = tmp_path, out, deals

    def stamp(self):
        pass

    def card_bundle(self, shared):
        card = {"outcomes": {"of": 1, "held": 1, "did_not_hold": 0, "undecided": 0}}
        doc = {"records": [{"capsule_id": "c1"}], "disclosures": {"c1": {"agent_input": card}},
               "extensions": {"x-standard-history/v0": {"as_of": {"anchor_time": "2026-11-25T18:00:00Z"}}}}
        if self.deals is not ABSENT:
            doc["extensions"]["x-standard-history/v0"]["deals"] = self.deals
        path = self.tmp_path / "card.json"
        path.write_text(json.dumps(doc))
        return path

    def verify(self, bundle, report_on_fail=False):
        assert report_on_fail  # the report of a failed verdict says which check failed
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


@pytest.mark.parametrize("deals", [None, ABSENT, []], ids=["null", "absent", "empty"])
def test_a_partys_own_card_page_before_its_first_deal_is_an_empty_history(monkeypatch, tmp_path, deals):
    # #449: capsulectl writes `deals: null` in the own copy of a card that counts no deal; the buyer who opens her
    # History card before her first deal gets an empty History page, not a refusal
    monkeypatch.setattr(pages, "home", lambda: tmp_path)
    card = OwnCard(tmp_path, report("pass"), deals=deals)
    card.name = "maya"
    text = pages.card_page(card, "Maya", rail="simulated", seller=False).read_text()
    assert '"rows": []' in text
    assert '{"id": "second_signature", "status": "not_run"}' in text
    assert '{"id": "witness", "status": "not_run"}' in text


class Seller:
    """A seller's party as publish_card and republish use it: its newest card, stamped or not, and its ticks."""
    name = "alder"

    def __init__(self, tmp_path, stamped: bool, slow: bool = False, deals: int = 1):
        self.tmp_path, self.stamped, self.slow, self.deals, self.calls = tmp_path, stamped, slow, deals, []

    def card_bundle(self, shared):
        assert shared is True
        n = len(self.calls)
        ext = {"x-standard-history/v0": {"as_of": {"anchor": f"{n:064x}"}}}
        if self.stamped:
            ext[pt.CARD_ANCHOR_WITNESS] = {"witnesses": [{}]}
        card = {"anchor": f"{n:064x}", "outcomes": {"of": self.deals, "held": self.deals}}
        path = self.tmp_path / "card-shared.json"
        path.write_text(json.dumps({"records": [{"capsule_id": "c1", "key_id": "k"}],
                                    "disclosures": {"c1": {"agent_input": card}}, "extensions": ext, "n": n}))
        return path

    def tick(self):
        self.calls.append("tick")

    def wait_checkpoint(self, seconds, say=None):
        self.calls.append(("wait", seconds))
        if self.slow:
            raise pt.WitnessSlow("slow")


def published(home) -> dict:
    return json.loads((flow.stage_dir(home) / "cards" / "alder.json").read_text())


def test_a_due_checkpoint_the_witness_has_not_taken_keeps_the_stamped_card(monkeypatch, tmp_path):
    monkeypatch.setenv("ARD_WITNESS", "public")
    flow.publish_card(tmp_path, Seller(tmp_path, stamped=True))
    newer = Seller(tmp_path, stamped=False)
    newer.calls = ["x"]
    flow.publish_card(tmp_path, newer, keep_stamped=True)
    assert pt.CARD_ANCHOR_WITNESS in published(tmp_path)["extensions"] and published(tmp_path)["n"] == 0
    # once the witness has taken it, the next round publishes it
    taken = Seller(tmp_path, stamped=True)
    taken.calls = ["x", "y"]
    flow.publish_card(tmp_path, taken, keep_stamped=True)
    assert published(tmp_path)["n"] == 2


def test_a_card_whose_counts_changed_replaces_the_stamped_card_at_once(monkeypatch, tmp_path):
    # Codex on #350: a ruling or a deal the witness has not stamped yet still reaches the buyer; only its receipt waits
    monkeypatch.setenv("ARD_WITNESS", "public")
    flow.publish_card(tmp_path, Seller(tmp_path, stamped=True))
    newer = Seller(tmp_path, stamped=False, deals=2)
    newer.calls = ["x"]
    flow.publish_card(tmp_path, newer, keep_stamped=True)
    assert published(tmp_path)["n"] == 1 and pt.CARD_ANCHOR_WITNESS not in published(tmp_path)["extensions"]


def test_an_unstamped_card_is_published_when_none_stamped_is_there_or_no_witness_is_named(monkeypatch, tmp_path):
    monkeypatch.setenv("ARD_WITNESS", "public")
    flow.publish_card(tmp_path, Seller(tmp_path, stamped=False), keep_stamped=True)
    assert pt.CARD_ANCHOR_WITNESS not in published(tmp_path)["extensions"]
    monkeypatch.setenv("ARD_WITNESS", "off")
    flow.publish_card(tmp_path, Seller(tmp_path, stamped=True))
    newer = Seller(tmp_path, stamped=False)
    newer.calls = ["x"]
    flow.publish_card(tmp_path, newer, keep_stamped=True)
    assert published(tmp_path)["n"] == 1


@pytest.mark.parametrize("slow", [False, True])
def test_an_on_demand_publish_waits_for_the_witness_then_publishes_its_new_counts(monkeypatch, tmp_path, slow):
    monkeypatch.setenv("ARD_WITNESS", "public")
    flow.publish_card(tmp_path, Seller(tmp_path, stamped=True))
    agent = flow.SellerAgent.__new__(flow.SellerAgent)
    agent.home, agent.party = tmp_path, Seller(tmp_path, stamped=False, slow=slow)
    agent.party.calls = ["x"]
    agent.failed = lambda what, exc: pytest.fail(f"{what}: {exc}")
    agent.republish(now=True)
    assert agent.party.calls == ["x", ("wait", flow.CARD_STAMP_WAIT_S)]
    assert published(tmp_path)["n"] == 2  # asked for its new counts: published even without its receipt


def test_a_due_republish_ticks_and_keeps_the_stamped_card(monkeypatch, tmp_path):
    monkeypatch.setenv("ARD_WITNESS", "public")
    flow.publish_card(tmp_path, Seller(tmp_path, stamped=True))
    agent = flow.SellerAgent.__new__(flow.SellerAgent)
    agent.home, agent.party = tmp_path, Seller(tmp_path, stamped=False)
    agent.failed = lambda what, exc: pytest.fail(f"{what}: {exc}")
    agent.republish()
    assert agent.party.calls == ["tick"] and published(tmp_path)["n"] == 0


def test_routine_ticks_end_after_their_bound_and_a_deal_step_starts_them_again(monkeypatch, tmp_path):
    """evidencebook-skills#453: a window left open stops cutting routine checkpoints ROUTINE_TICKS_S after its last
    deal step, says so once, and still publishes its card; a deal step later (any step marked done) starts them again,
    so that deal reaches the card; an on-demand stamp goes either way."""
    monkeypatch.setenv("ARD_WITNESS", "public")
    agent = flow.SellerAgent.__new__(flow.SellerAgent)
    agent.home, agent.party = tmp_path, Seller(tmp_path, stamped=False)
    agent.party.dir = tmp_path / "alder"
    agent.party.dir.mkdir()
    agent.failed = lambda what, exc: pytest.fail(f"{what}: {exc}")
    said = []
    agent.say = said.append
    agent.active = time.monotonic()
    agent.republish()
    assert agent.party.calls == ["tick"] and not said  # within the bound: a routine tick
    agent.active = time.monotonic() - flow.ROUTINE_TICKS_S - 1
    agent.republish()
    agent.republish()
    assert agent.party.calls == ["tick"]  # past it: no routine tick, the card still published each round
    assert said == ["routine time-stamps stopped: no deal for 2 hours. The next deal starts them again."]
    agent.republish(now=True)
    assert agent.party.calls == ["tick", ("wait", flow.CARD_STAMP_WAIT_S)]  # an on-demand stamp still goes
    agent._mark("deal-1", "offer")  # a buyer's offer taken
    agent.republish()
    assert agent.party.calls[-1] == "tick" and said[-1] == "routine time-stamps started again with this deal"


def fake_ctl(tmp_path, stdout: str, code: int):
    """A ``Ctl`` whose binary prints ``stdout`` and exits ``code``, as capsulectl-deal ``verify`` does."""
    import stat

    from ctl import Ctl

    binary = tmp_path / "capsulectl-deal"
    binary.write_text(f"#!/bin/sh\ncat <<'OUT'\n{stdout}\nOUT\necho refused >&2\nexit {code}\n")
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    return Ctl(tmp_path, "p", str(binary))


def test_a_failed_verdict_keeps_verifys_report_so_the_reader_hears_which_check_failed(tmp_path):
    # Codex on #350: verify prints its report, then exits non-zero; Ctl.run alone drops the report
    out = json.dumps(report("fail", verdict="INVALID"))
    assert pt.verify_report(fake_ctl(tmp_path, out, 1), ["verify"]) == json.loads(out)
    assert pt.verify_report(fake_ctl(tmp_path, json.dumps(report("pass")), 0), ["verify"])["verdict"] == "VALID"


def test_a_verify_failure_with_no_report_still_refuses(tmp_path):
    with pytest.raises(pt.Refused, match="^bad bundle$"):
        pt.verify_report(fake_ctl(tmp_path, json.dumps({"error": "bad bundle"}), 2), ["verify"])
    with pytest.raises(pt.Refused, match="^refused$"):
        pt.verify_report(fake_ctl(tmp_path, "", 2), ["verify"])


@pytest.mark.parametrize("verdict, said", [
    ("INVALID", "Your History card does not verify: capsulectl deal verify reported it INVALID."),
    ("INCOMPLETE", "Your History card could not be fully checked: capsulectl deal verify reported it INCOMPLETE, "
                   "because part of what it covers is withheld or missing from the file.")])
def test_a_partys_own_card_page_refuses_any_other_failed_verdict(monkeypatch, tmp_path, verdict, said):
    monkeypatch.setattr(pages, "home", lambda: tmp_path)
    with pytest.raises(pt.Refused) as exc:
        pages.card_page(OwnCard(tmp_path, report(None, verdict=verdict)), "Alder Print Co.", rail="simulated",
                        seller=True)
    assert str(exc.value) == said
