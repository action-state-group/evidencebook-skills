# SPDX-License-Identifier: Apache-2.0
"""The receipt page (receipt.py): each party's own copy of a closed deal, drawn by capsule-viewer's receipt module
after capsulectl verify --bundle checks it, with nothing of the demo's added. One seeded home and one deal of Maya's with Alder on
the simulated rail. The pages need ``CAPSULECTL_DEAL`` (the capsulectl-deal binary) and the capsule-viewer package;
the refusal and the unchanged reads need neither."""
from __future__ import annotations

import html
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

import pages
import pay
import receipt
import screens

ASK = "Maya: I need 200 conference badges by Friday, under 3,000 msat."


def _viewer() -> bool:
    try:
        import capsule_viewer  # noqa: F401
    except ImportError:
        return False
    return True


pages_only = pytest.mark.skipif(not os.environ.get("CAPSULECTL_DEAL") or not _viewer(),
                                reason="CAPSULECTL_DEAL names the verifier, and the capsule-viewer package draws the page")


def _reads(world, deal_id: str, now: datetime | None = None) -> dict:
    """What the other readers of the two books see: each card's counts, the deal's chain and Maya's half. Pass the
    same ``now`` to compare two reads: a checkpoint is due once a minute, so two reads at different times can see a
    newer card for a reason that has nothing to do with what ran between them."""
    import deals

    now = now or datetime.now(timezone.utc)
    out = {}
    for name in ("maya", "alder"):
        n = world.nodes[name]
        n.tick(now)
        out[f"card_{name}"] = json.loads(n.standard_history()["card"])["outcomes"]
        out[f"chain_{name}"] = n.deal(deal_id).records
        out[f"deals_{name}"] = deals.deal_ids(n)
    out["half_steps"] = len(world.nodes["maya"].half(deal_id)["steps"])
    return out


@pytest.fixture(scope="module")
def seeded(tmp_path_factory, seeded_home):
    import deals
    from world import CURRENCY, ITEM, SELLERS, World, terms

    home = seeded_home(tmp_path_factory.mktemp("receipt"))
    with pytest.MonkeyPatch.context() as mp, World(home) as world:
        mp.setenv("ARD_HOME", str(home))
        mp.setenv("ARD_OPEN_PAGES", "0")
        maya, alder = world.nodes["maya"], world.nodes["alder"]
        deals.admit(maya, alder, reason="the buyer's pick (test)")
        deals.admit(alder, maya, reason="buyer who picked this seller (test)")
        rail = pay.FakeRail()
        price = SELLERS["alder"]["price_msat"]
        deal_id = deals.run_deal(maya, alder, terms(ITEM, price, CURRENCY, rail.SEALED), ASK, "",
                                 pay=lambda: rail.pay(price).reference)
        yield world, deal_id


def test_a_simulated_deal_seals_the_simulated_rail_and_the_profile_allows_it(seeded):
    import goose_node as gn

    world, deal_id = seeded
    for name in ("maya", "alder"):
        payloads = [json.loads(p) for p in world.nodes[name].deal_payloads(deal_id)]
        assert payloads[0]["body"]["recourse"]["rail"] == "simulated"
        assert "demo" not in payloads[0]["body"]  # no demo flag in the baseline (Ethan, 2026-11-17)
        checker = gn._profile_checker()
        for p in payloads:
            checker.check_record(p)
        checker.check_chain(payloads)
    pay_step = [json.loads(p)["body"] for p in world.nodes["maya"].deal_payloads(deal_id)
                if json.loads(p).get("body", {}).get("action") == "pay" and "rail" in json.loads(p)["body"]]
    assert [b["rail"] for b in pay_step] == ["simulated"]
    assert pay.Rail.SEALED == pay.LightningRail.SEALED == pay.LocalRail.SEALED == "lightning"


def test_no_page_before_the_close(tmp_path):
    import deals
    from demo_node import DemoNode
    from world import CURRENCY, ITEM, terms

    buyer, seller = DemoNode.open(tmp_path / "b", operator="b"), DemoNode.open(tmp_path / "s", operator="s")
    try:
        deals.admit(buyer, seller)
        chain = buyer.new_deal(f"deal-{os.urandom(8).hex()}", "buyer", seller.key_id, terms(ITEM, 289, CURRENCY, "simulated"))
        buyer.open_deal(chain, chain.open(datetime.now(timezone.utc), ASK))
        with pytest.raises(receipt.ReceiptError, match="not closed yet"):
            receipt.receipt_page(buyer, "maya", "Maya", chain.deal_id, rail="fake", seller=False)
        with pytest.raises(receipt.ReceiptError, match="holds no deal"):
            receipt.ready(buyer, "deal-none")
        assert not (tmp_path / "b" / "receipts").exists()
    finally:
        buyer.close()
        seller.close()


def test_the_report_changes_nothing_another_reader_sees(seeded):
    world, deal_id = seeded
    now = datetime.now(timezone.utc)
    before = _reads(world, deal_id, now)
    for name, seller in (("maya", False), ("alder", True)):
        node = world.nodes[name]
        copy = receipt.keep_copy(node, deal_id, seller=seller, real=False)
        block = copy["extensions"]["x-deal-report/v0"]
        assert copy["extensions"]["x-deal-v0"] == {"sealed_report": block["record"]["capsule_id"]}
        assert block["record"]["capsule_id"] not in {r["capsule_id"] for r in copy["records"]}
        # A second copy at the same checkpoint reuses the sealed report.
        again = receipt.keep_copy(node, deal_id, seller=seller, real=False)
        assert again["extensions"]["x-deal-report/v0"] == block
        # The report's words are this demo's: no claim that capsulectl wrote them, and no real payment.
        text = json.dumps(block["agent_input"]["report"])
        assert "simulated" in text.lower(), name
        assert [w for w in ("capsulectl", "Lightning", "lightning") if w in text] == [], (name, text)
    assert _reads(world, deal_id, now) == before


def test_a_reopened_seller_reads_the_same_deal_and_the_same_report(seeded, tmp_path):
    import deals
    from demo_node import DemoNode

    world, deal_id = seeded
    alder = world.nodes["alder"]
    sealed = receipt.keep_copy(alder, deal_id, seller=True, real=False)["extensions"]["x-deal-report/v0"]
    chain, ids = alder.deal(deal_id).records, deals.deal_ids(alder)
    home = alder.home
    alder.close()
    world.nodes["alder"] = alder = DemoNode.open(home, operator="ard-alder")
    assert alder.deal(deal_id).records == chain and deals.deal_ids(alder) == ids
    assert receipt.keep_copy(alder, deal_id, seller=True, real=False)["extensions"]["x-deal-report/v0"] == sealed


@pages_only
@pytest.mark.parametrize("name,party,seller", [("maya", "Maya", False), ("alder", "Alder Print Co.", True)])
def test_each_party_gets_its_own_receipt_page(seeded, name, party, seller):
    from world import ITEM

    world, deal_id = seeded
    now = datetime.now(timezone.utc)
    before = _reads(world, deal_id, now)
    path = receipt.receipt_page(world.nodes[name], name, party, deal_id, rail="fake", seller=seller)
    assert path.parent == pages.home() / "pages" and path.name.startswith(f"{name}-receipt-")
    page = path.read_text()
    for banner in (screens.BANNER_FAKE, screens.BANNER, screens.BANNER_LOCAL):  # no banner of ours (Ethan, 2026-11-17)
        assert html.escape(banner) not in page
    assert "ard-demo" not in page and ">DEMO<" not in page  # nothing marks the page: no banner, no demo flag to badge
    assert html.escape(ITEM) in page and "2,000 msat" in page
    assert ("Sale receipt" in page) == seller and 'data-level="L0"' in page
    assert "Paid by lightning" not in page and "over lightning" not in page
    assert "no witness receipt is in this report" not in page and "no other party has signed" not in page
    assert "This copy carries no witness receipt." in page and "the other party&#x27;s signed half is in their own copy" in page.replace("&#39;", "&#x27;")
    # capsule-viewer 0.25.0 (#374): the top line names the verifier and its checks
    assert "Checked by capsulectl verify --bundle: graph closure" in page
    if not seller:  # 0.25.0 says test money once, at the top (a seller's copy holds no payment step)
        assert page.replace("&#39;", "&#x27;").count("Test money: this deal&#x27;s payment was on a simulated rail.") == 1
    if seller:  # where the proof is, then the seller's own sealed sentence, attributed and tagged simulated (#243)
        assert "Not recorded in this copy" not in page
        assert "The payment proof is in the buyer&#x27;s records, not this copy." in page.replace("&#39;", "&#x27;")
        assert "as this seller&#x27;s own outcome record states it (simulated rail: no money moved)" in page.replace("&#39;", "&#x27;")
        assert "paid" not in page.lower().split("payment proof")[1].split("</p>")[0]
    else:
        assert "Simulated payment of 2,000 msat: no money moved" in page
    assert _reads(world, deal_id, now) == before


def _book(status: str | None, rail: str = "simulated") -> list[dict]:
    first = {"body": {"terms": {"item": "badges", "price_minor": 2000}, "recourse": {"rail": rail}}}
    return [first] + ([{"type": "action-outcome/v0", "body": {"status": status}}] if status else [])


def test_the_sellers_payment_line_attributes_the_status_and_tags_the_simulated_rail():
    line = receipt.seller_payment(_book("received"), real=False)
    assert line == ("Agreed 2,000 msat for badges. Payment: received, as this seller's own outcome record states it "
                    "(simulated rail: no money moved).")
    assert "paid" not in line.lower() and "verified" not in line.lower()


def test_a_seller_with_no_outcome_record_does_not_cite_one():
    line = receipt.seller_payment(_book(None), real=False)
    assert "Payment: not stated in this seller's records (simulated rail" in line and "outcome record" not in line


def test_the_real_rail_sellers_line_names_the_rail_and_keeps_the_credit_note():
    line = receipt.seller_payment(_book("received", rail="lightning"), real=True)
    assert "as this seller's own outcome record states it (rail lightning). " in line and screens.seller_credit_note(2000) in line
    assert "simulated" not in line


def test_a_sample_deals_seller_line_says_sample_names_no_rail_and_no_money_moved():
    line = receipt.seller_payment(_book("received", rail="lightning"), real=True, sample=True)
    assert line == ("Sample history: Agreed 2,000 msat for badges. Payment: received, as this seller's own outcome record "
                    "states it (sample deal made up for this demo: no money moved).")
    assert "paid" not in line.lower() and "verified" not in line.lower() and "credited" not in line and "lightning" not in line


def test_a_seeded_sample_deal_receipt_is_sample_history_and_a_live_deal_is_not(seeded):
    import deals

    world, live_id = seeded
    alder = world.nodes["alder"]
    sample_id = next(d for d in deals.deal_ids(alder) if d != live_id)
    assert receipt.is_sample(alder, sample_id) and not receipt.is_sample(alder, live_id)
    first = json.loads(alder.deal_payloads(sample_id)[0])["body"]
    assert first["recourse"]["rail"] == "lightning"  # the sample record seals lightning; the page must not read it as money
    assert receipt.sealed_real(alder, sample_id)
    sealed = receipt.keep_copy(alder, sample_id, seller=True, real=True, sample=True)["extensions"]["x-deal-report/v0"]
    text = sealed["agent_input"]["report"]["money"]["text"]
    assert text.startswith("Sample history: ") and "sample deal made up for this demo: no money moved" in text
    assert "credited" not in text and "paid" not in text.lower() and "lightning" not in text
    assert deals.deal_ids(world.nodes["maya"]) == [live_id]  # no buyer page for a sample deal can exist: Maya holds only her live deal


@pages_only
def test_a_sample_deals_seller_page_says_sample_history_with_no_money_moved(seeded):
    import deals

    world, live_id = seeded
    alder = world.nodes["alder"]
    sample_id = next(d for d in deals.deal_ids(alder) if d != live_id)
    page = receipt.receipt_page(alder, "alder", "Alder Print Co.", sample_id, rail="lightning", seller=True).read_text()
    assert "Sample history: Agreed 2,000 msat" in page and "sample deal made up for this demo: no money moved" in page
    assert "lightning" not in page.lower() and "wallet provider" not in page and "paid" not in page.lower().split("payment proof")[1].split("</p>")[0]


@pages_only
def test_a_refused_wording_pack_raises_instead_of_drawing_bare_keys(seeded, monkeypatch):
    world, deal_id = seeded
    monkeypatch.setattr(receipt, "wording_pack", lambda bundle, **kw: b"{}")
    with pytest.raises(receipt.ReceiptError, match="refused this demo's receipt wording pack"):
        receipt.receipt_page(world.nodes["maya"], "maya", "Maya", deal_id, rail="fake", seller=False)


@pages_only
def test_a_report_sealed_with_older_words_is_sealed_again(seeded):
    world, deal_id = seeded
    node = world.nodes["alder"]
    receipt.keep_copy(node, deal_id, seller=True, real=False)
    path = receipt._stored(node, deal_id)
    block = json.loads(path.read_text())
    block["agent_input"]["report"]["money"]["text"] = "Payment: the buyer's payment, as this seller's own outcome record states it: received"
    path.write_text(json.dumps(block, sort_keys=True))
    again = receipt.keep_copy(node, deal_id, seller=True, real=False)["extensions"]["x-deal-report/v0"]
    assert again["agent_input"]["report"]["money"]["text"].startswith("Agreed 2,000 msat")


def test_the_checkpoint_sentence_needs_a_witnessed_newest_tick_that_covers_the_whole_deal_book(seeded):
    from types import SimpleNamespace

    world, deal_id = seeded
    node = world.nodes["alder"]
    node.tick(datetime.now(timezone.utc) + timedelta(minutes=2))
    n = node.cadence.standard_history_anchor().tick.n
    assert receipt.witnessed_checkpoint(node, deal_id) is None  # tests run with the witness off: no receipt held
    at = datetime(2026, 11, 24, 6, 30, 5, tzinfo=timezone.utc)
    stamped = SimpleNamespace(at=at)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(node, "witnessed_tick", lambda k: stamped if k == n else None)
        assert receipt.witnessed_checkpoint(node, deal_id) == (n, "2026-11-24 06:30:05")
        mp.setattr(node, "witnessed_tick", lambda k: None)
        assert receipt.witnessed_checkpoint(node, deal_id) is None
        mp.setattr(node, "witnessed_tick", lambda k: stamped)
        book = node.shelf.open(f"deal/{deal_id}")
        real_records = book.records
        mp.setattr(type(book), "records", lambda self: real_records() + [object()], raising=False)  # a record the tick lacks
        assert receipt.witnessed_checkpoint(node, deal_id) is None
    assert receipt.witnessed_checkpoint(SimpleNamespace(), deal_id) is None  # a node that never witnesses


def test_the_witness_line_points_at_the_card_only_when_asked():
    bundle = {"extensions": {}}
    plain = json.loads(receipt.wording_pack(bundle))["entries"]["rung.unwitnessed"]
    on_card = json.loads(receipt.wording_pack(bundle, on_card=(4, "2026-11-24 06:30:05")))["entries"]["rung.unwitnessed"]
    assert plain == receipt.WITNESS_NONE
    assert on_card == (receipt.WITNESS_NONE + " The hosted witness stamped the History checkpoint taken at 2026-11-24 06:30:05 UTC "
                       "(checkpoint 4), which covers this deal as of that checkpoint; the card shows the newest checkpoint.")


@pages_only
def test_a_covered_deal_s_receipt_page_says_where_the_witness_stamp_is(seeded):
    from types import SimpleNamespace

    world, deal_id = seeded
    node = world.nodes["maya"]
    node.tick(datetime.now(timezone.utc) + timedelta(minutes=3))
    stamped = SimpleNamespace(at=datetime.now(timezone.utc))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(node, "witnessed_tick", lambda k: stamped)
        page = receipt.receipt_page(node, "maya", "Maya", deal_id, rail="fake", seller=False).read_text()
    assert "This copy carries no witness receipt. The hosted witness stamped the History checkpoint taken at " in page
    assert "which covers this deal as of that checkpoint; the card shows the newest checkpoint." in page


@pages_only
def test_a_simulated_deal_stays_simulated_when_the_window_reopens_on_a_real_rail(seeded):
    """Money moved or not is the deal's own sealed rail, not the rail the window runs on now (Codex, #173)."""
    world, deal_id = seeded
    assert receipt.sealed_real(world.nodes["maya"], deal_id) is False
    page = receipt.receipt_page(world.nodes["maya"], "maya", "Maya", deal_id, rail="lightning", seller=False).read_text()
    assert html.escape(screens.BANNER) not in page  # nothing on the page says real money moved
    assert "Simulated payment of 2,000 msat: no money moved" in page and "Paid 2,000" not in page


@pages_only
def test_a_copy_that_does_not_verify_draws_no_page(seeded, tmp_path, monkeypatch):
    world, deal_id = seeded
    bad = tmp_path / "bundle.json"
    copy = receipt.keep_copy(world.nodes["maya"], deal_id, seller=False, real=False)
    copy["extensions"]["x-deal-report/v0"]["agent_input"]["report"]["money"]["text"] = "Paid in full."
    bad.write_text(json.dumps(copy))
    with pytest.raises(receipt.ReceiptError, match="verify --bundle says"):
        receipt.verify(bad)
    monkeypatch.delenv("CAPSULECTL_DEAL")
    with pytest.raises(receipt.ReceiptError, match="set CAPSULECTL_DEAL"):
        receipt.verify(bad)


@pages_only
def test_a_sample_deal_its_owner_marked_did_not_hold_says_so_on_its_receipt(seeded):
    """Hand run 2026-11-24: Kestrel's receipt for a deal with a did_not_hold note still led with "Closed: matches what
    was agreed" and listed the note's step as its bare record type."""
    import deals

    world, _ = seeded
    kestrel = world.nodes["kestrel"]
    noted = [d for d in (b.split("/")[1] for b in kestrel.shelf.books() if b.startswith("deal/") and b.count("/") == 1)
             if any(receipt._kind(json.loads(p)) == deals.OUTCOME_NOTE for p in kestrel.deal_payloads(d))]
    assert noted, "the sentinel seed should carry a did_not_hold note on Kestrel"
    import html

    page = html.unescape(receipt.receipt_page(kestrel, "kestrel", "Kestrel Print", noted[0], rail="fake", seller=True).read_text())
    assert receipt.NOT_HELD in page and "not held up by the seller's owner (reason:" in page
    assert "matches what was agreed" not in page


def test_the_approval_line_says_who_approved_and_names_the_hold_only_for_a_limit():
    """#261 (Sherlock2's wording): the person's click reads "Approved by you"; after a hold by their spending limit it
    reads "Held by your spending limit, then approved by you"; a pause for the pack's other asks names no limit (#230:
    the one dialog comes after the check and lists every reason, so no click came before it)."""
    caps = {"result": "pause", "rules": {"status": "evaluated", "ruleset_id": "asg/everyday/0.3.8", "verdict": "escalate",
                      "findings": [{"id": "r05-spending-limits#7d", "check": "caps/5.1.0", "verdict": "fail"}]}}
    other = {"result": "pause", "rules": {"status": "evaluated", "ruleset_id": "asg/everyday/0.3.8", "verdict": "escalate",
                       "findings": [{"id": "r06-new-merchant", "check": "counterparty_seen_before/4.0.0", "verdict": "fail"},
                                    {"id": "r05-spending-limits#7d", "check": "caps/5.1.0", "verdict": "pass"}]}}
    user = {"approver": "user"}
    assert receipt._line("approval", user, True, caps) == "Held by your spending limit, then approved by you"
    assert receipt._line("approval", user, True, other) == "Held for your approval, then approved by you"
    assert receipt._line("approval", user, True, {"rules": {"status": "not_configured"}}) == "Approved by you"
    assert receipt._line("approval", user, True, {"result": "pass", "rules": {"status": "evaluated", "verdict": "allow"}}) \
        == "Approved by you"
    assert receipt._line("verdict", caps, True) == ("Checked against the Everyday Rules (0.3.8) and your spending limit: "
                                                    "over your limit, so the order was held for your approval")
    both = {"result": "pause", "rules": {**caps["rules"], "findings": caps["rules"]["findings"] + other["rules"]["findings"]}}
    assert receipt._line("verdict", both, True).endswith(  # the limit with the other failing checks, each named once
        ": over your limit and a seller you have not paid before, so the order was held for your approval")
    assert receipt._line("verdict", other, True) == ("Checked against the Everyday Rules (0.3.8) and your spending limit: "
                                                     "a seller you have not paid before, which needs your approval")
    first = {"rules": {"status": "evaluated", "ruleset_id": "asg/everyday/0.3.8", "verdict": "escalate", "findings": [
        {"id": "r02", "check": "counterparty_seen_before/4.0.0", "verdict": "fail"},
        {"id": "r06", "check": "counterparty_seen_before/4.0.0", "verdict": "fail"},
        {"id": "r08", "check": "refundability/1.1.0", "verdict": "fail"}]}}
    assert receipt._line("verdict", first, True).endswith(
        ": a seller you have not paid before and a payment that cannot be undone, which need your approval")
    unnamed = {"rules": {"status": "evaluated", "ruleset_id": "asg/everyday/0.3.8", "verdict": "escalate", "findings": []}}
    assert receipt._line("verdict", unnamed, True).endswith(": one of the rules' checks, which needs your approval")
    allow = {"rules": {"status": "evaluated", "ruleset_id": "asg/everyday/0.3.8", "verdict": "allow", "findings": []}}
    assert receipt._line("verdict", allow, True) == "Checked against the Everyday Rules (0.3.8) and your spending limit: allowed"
    assert receipt._line("verdict", {"result": "pass", "differences": [], "rules": {"status": "not_configured"}}, True) \
        == "Checked: pass, 0 difference(s)"


def test_rules_22_and_27_have_plain_words_and_rule_22_names_the_limit_its_amounts_fail():
    """Sherlock2 on #237: rule 27 "a repeat of a recent payment to this seller"; rule 22 by the limit it failed (above
    25% of the price, or above 100.00), read from the sealed check's amounts since the sealed finding does not say."""
    found = {"rules": {"status": "evaluated", "ruleset_id": "asg/everyday/0.3.8", "verdict": "escalate", "findings": [
        {"id": "r05-spending-limits#7d", "check": "caps/5.1.0", "verdict": "fail"},
        {"id": "r08", "check": "refundability/1.1.0", "verdict": "fail"},
        {"id": "r22", "check": "upfront_amount/1.1.0", "verdict": "fail"},
        {"id": "r27", "check": "dedupe/1.0.0", "verdict": "fail"}]}}
    whole = {"upfront_amount_minor": 2000, "terms": {"price_minor": 2000}}
    assert receipt._line("verdict", found, True, whole).endswith(
        ": over your limit, a payment that cannot be undone, more than a quarter of the price paid up front and a repeat "
        "of a recent payment to this seller, so the order was held for your approval")
    assert receipt._upfront_words({"upfront_amount_minor": 501, "terms": {"price_minor": 2000}}).startswith("more than a quarter")
    assert receipt._upfront_words({"upfront_amount_minor": 500, "terms": {"price_minor": 2000}}) == "another of the rules' checks"
    assert receipt._upfront_words({"upfront_amount_minor": 10_001, "terms": {"price_minor": 100_000}}) == "a large amount paid up front"
    assert receipt._upfront_words(None) == "another of the rules' checks"


@pages_only
def test_a_held_then_approved_order_s_receipt_says_the_limit_held_it_and_the_person_approved(seeded, tmp_path, monkeypatch):
    """#261: the buyer's receipt for an order the spending limit held and the person approved verifies, and its step
    lines say what the rules said and who approved; the seller's receipt is unchanged."""
    import deals
    import rules
    from test_rules import stub_engine
    from world import CURRENCY, ITEM, SELLERS, terms

    engine, _ = stub_engine(tmp_path)
    monkeypatch.setenv("CAPSULE_ENGINE", str(engine))
    world, _ = seeded
    maya, alder = world.nodes["maya"], world.nodes["alder"]
    price = SELLERS["alder"]["price_msat"]
    click = rules.Answer("Pay Alder Print Co. 2,000 msat on the simulated rail: no money moves.", "Pay")
    deal_id = deals.run_deal(maya, alder, terms(ITEM, price, CURRENCY, pay.FakeRail.SEALED), ASK, "", pay=lambda: "ref-held",
                             limit=price, approve=lambda o: True, clicked=click)
    lines = [s["line"] for s in receipt.report_body(maya, deal_id, seller=False, real=False, as_of="x")["steps"]]
    assert lines[2] == ("Checked against the Everyday Rules (0.3.8) and your spending limit: over your limit, so the order "
                        "was held for your approval")
    assert lines[3] == "Held by your spending limit, then approved by you"
    for n in (maya, alder):
        n.tick(datetime.now(timezone.utc))
    page = html.unescape(receipt.receipt_page(maya, "maya", "Maya", deal_id, rail="fake", seller=False).read_text())
    assert "Held by your spending limit, then approved by you" in page and "over your limit, so the order was held" in page
    seller = html.unescape(receipt.receipt_page(alder, "alder", "Alder Print Co.", deal_id, rail="fake", seller=True).read_text())
    assert "approved by you" not in seller.lower() and "spending limit" not in seller


@pages_only
@pytest.mark.parametrize("clicked,limit,approver", [(True, False, "user"), (False, True, "agent_card")])
def test_each_new_approval_shape_verifies_on_the_buyers_receipt(seeded, tmp_path, monkeypatch, clicked, limit, approver):
    """#265 review: capsulectl verify --bundle (the Go profile checker) takes a no-limit Pay click (`user`, the act
    disposed by the human) and a pause no one answered (`agent_card`, no decide Capsule on the act). Under a limit every
    escalate is now held and put to the person (#230), so that pause is forced here."""
    import deals
    import rules
    from test_rules import stub_engine
    from world import CURRENCY, ITEM, SELLERS, terms

    engine, _ = stub_engine(tmp_path, caps_fail_when_history=False, do_fail=True)
    monkeypatch.setenv("CAPSULE_ENGINE", str(engine))
    world, _ = seeded
    maya, alder = world.nodes["maya"], world.nodes["alder"]
    price = SELLERS["alder"]["price_msat"]
    real_check = rules.check
    monkeypatch.setattr(rules, "check", lambda *a, **k: __import__("dataclasses").replace(real_check(*a, **k), held=False))
    click = rules.Answer("Pay Alder Print Co. 2,000 msat on the simulated rail: no money moves.", "Pay") if clicked else None
    deal_id = deals.run_deal(maya, alder, terms(ITEM, price, CURRENCY, pay.FakeRail.SEALED), ASK, "", pay=lambda: "ref-x",
                             limit=price if limit else None, clicked=click)
    sealed = [json.loads(p)["body"] for p in maya.deal_payloads(deal_id) if json.loads(p)["x-deal-v0"]["record_type"] == "approval"]
    assert sealed[-1]["approver"] == approver
    for n in (maya, alder):
        n.tick(datetime.now(timezone.utc))
    page = html.unescape(receipt.receipt_page(maya, "maya", "Maya", deal_id, rail="fake", seller=False).read_text())
    assert ("Approved by you" in page) == clicked and ("Went ahead on the agent's card" in page) == (not clicked)
