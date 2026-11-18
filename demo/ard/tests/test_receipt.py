# SPDX-License-Identifier: Apache-2.0
"""The receipt page (receipt.py): each party's own copy of a closed deal, drawn by capsule-viewer's receipt module
after capsulectl verify --bundle checks it, with the demo labels. One seeded home and one deal of Maya's with Alder on
the simulated rail. The pages need ``CAPSULECTL_DEAL`` (the capsulectl-deal binary) and the capsule-viewer package;
the refusal and the unchanged reads need neither."""
from __future__ import annotations

import html
import json
import os
from datetime import datetime, timezone

import pytest

import pages
import pay
import receipt
import screens

ASK = "Maya: I need 200 conference badges by Friday, under 300 msat."


def _viewer() -> bool:
    try:
        import capsule_viewer  # noqa: F401
    except ImportError:
        return False
    return True


pages_only = pytest.mark.skipif(not os.environ.get("CAPSULECTL_DEAL") or not _viewer(),
                                reason="CAPSULECTL_DEAL names the verifier, and the capsule-viewer package draws the page")


def _reads(world, deal_id: str) -> dict:
    """What the other readers of the two books see: each card's counts, the deal's chain and Maya's half."""
    import deals

    out = {}
    for name in ("maya", "alder"):
        n = world.nodes[name]
        n.tick(datetime.now(timezone.utc))
        out[f"card_{name}"] = json.loads(n.standard_history()["card"])["outcomes"]
        out[f"chain_{name}"] = n.deal(deal_id).records
        out[f"deals_{name}"] = deals.deal_ids(n)
    out["half_steps"] = len(world.nodes["maya"].half(deal_id)["steps"])
    return out


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    import deals
    import seed
    from world import CURRENCY, ITEM, SELLERS, World, terms

    home = tmp_path_factory.mktemp("receipt")
    with pytest.MonkeyPatch.context() as mp, World(home) as world:
        mp.setenv("ARD_HOME", str(home))
        mp.setenv("ARD_OPEN_PAGES", "0")
        seed.seed(world, say=lambda *_: None, kestrel_card="sentinel")
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
        assert payloads[0]["body"]["demo"] is True  # the pinned Goose reference seals it (evidencebook#514)
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
    before = _reads(world, deal_id)
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
    assert _reads(world, deal_id) == before


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
    before = _reads(world, deal_id)
    path = receipt.receipt_page(world.nodes[name], name, party, deal_id, rail="fake", seller=seller)
    assert path.parent == pages.home() / "pages" and path.name.startswith(f"{name}-receipt-")
    page = path.read_text()
    for banner in (screens.BANNER_FAKE, screens.BANNER, screens.BANNER_LOCAL):  # no banner of ours (Ethan, 2026-11-17)
        assert html.escape(banner) not in page
    assert "ard-demo" not in page and ">DEMO<" in page  # the viewer's own DEMO badge, from demo: true
    assert html.escape(ITEM) in page and "289 msat" in page
    assert ("Sale receipt" in page) == seller and 'data-level="L0"' in page
    assert "Paid by lightning" not in page and "over lightning" not in page
    if seller:  # one payment line only, the viewer's: the copy records no payment the seller received
        assert page.count("Payment:") == 1 and "Not recorded in this copy" in page and "own outcome record" not in page
    else:
        assert "Simulated payment of 289 msat: no money moved" in page
    assert _reads(world, deal_id) == before


@pages_only
def test_a_simulated_deal_stays_simulated_when_the_window_reopens_on_a_real_rail(seeded):
    """Money moved or not is the deal's own sealed rail, not the rail the window runs on now (Codex, #173)."""
    world, deal_id = seeded
    assert receipt.sealed_real(world.nodes["maya"], deal_id) is False
    page = receipt.receipt_page(world.nodes["maya"], "maya", "Maya", deal_id, rail="lightning", seller=False).read_text()
    assert html.escape(screens.BANNER) not in page  # nothing on the page says real money moved
    assert "Simulated payment of 289 msat: no money moved" in page and "Paid 289" not in page


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
