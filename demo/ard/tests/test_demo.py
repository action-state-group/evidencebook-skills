# SPDX-License-Identifier: Apache-2.0
"""The demo end to end on a fake rail: sample history, ARD lookup, the evidence requests over the
mailbox, the assessments under both packs, the pick, the deal and the card.

Needs ``CAPSULE_ENGINE`` (a capsule-engine binary) and ``ARD_EVIDENCEBOOK`` (an evidencebook
checkout); without them every test here is skipped. The 48 sample deals take about 20 seconds, so
the world is built once for the module."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from conftest import engine_only

pytestmark = engine_only


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    import ard
    import pack as packs
    import pay
    import seed
    from demo import Run
    from server import Server
    from world import SELLERS, World

    world = World(tmp_path_factory.mktemp("home")).open()
    seed.seed(world, say=lambda *_: None)
    server = Server()
    for name in SELLERS:
        world.advertise(name)
        world.serve(name)
    from discovery import Discovery
    disc = Discovery(SELLERS, lambda n: world.commitments.get(n))
    server.registry_url, server.origins, server.query = disc.registry.url, disc.origins, "conference badges print"
    r = Run(world, server, pay.FakeRail(), True, False)
    r.discover()
    r.collect()
    r.start = packs.starting()
    r.tight = packs.compile_source(packs.edited(packs.source_path().read_text(), 50, "1.1.0"), "1.1.0")
    yield r
    server.close()
    world.close()


def test_catalogue_lists_two_sellers_with_verified_commitments(run):
    assert {e["id"]: e["offer"]["price_msat"] for e in run.entries} == {"alder": 289, "kestrel": 268}
    assert all("commitment" in e and e["digest_matches"] for e in run.entries)
    for e in run.entries:  # the signed commitment says what the demo's seller process does
        c = e["commitment"]
        assert c["human_gated"] is False and {"standard_history/1", "selection/1"} <= set(c["answers"]["derivations"])


def test_every_evidence_check_passes_and_kestrels_card_is_the_sample(run):
    for ev in run.evidence.values():
        assert [c.name for c in ev.checks if not c.ok] == []
    assert run.evidence["alder"].card["outcomes"]["held"] == 24
    k = run.evidence["kestrel"]
    assert (k.card["outcomes"]["held"], k.card["outcomes"]["did_not_hold"]) == (22, 2) and k.sample_card


def test_both_are_go_under_the_starting_pack_and_kestrel_is_limit_after_the_edit(run):
    first = run.assess(run.start)
    assert {k: (a.verdict, a.tier) for k, a in first.items()} == {"alder": ("GO", "T2"), "kestrel": ("GO", "T2")}
    run.made = run.assess(run.tight)
    assert run.made["alder"].verdict == "GO"
    k = run.made["kestrel"]
    assert (k.verdict, k.tier, k.cap_msat, k.reasons) == ("LIMIT", "T1", 100, ["band-history"])
    assert run.start.digest != run.tight.digest and k.pack_digest == run.tight.digest and k.sample_card


def test_a_pick_of_a_limit_seller_opens_no_deal_and_pays_nothing(run):
    import buyer
    from demo import Run  # noqa: F401
    from world import SELLERS  # noqa: F401
    made = run.assess(run.tight)
    kestrel = run.w.nodes["kestrel"]
    pick = buyer.seal_pick(run.maya, kestrel, made["kestrel"], [made["alder"]])
    import goose_node as gn
    with pytest.raises(gn.Refused, match="LIMIT: deals under 100 msat"):
        buyer.open_deal(run.maya, kestrel, pick, made["kestrel"], "ask")
    assert run.rail.paid == []


def test_a_deal_needs_a_sealed_pick(run):
    import buyer
    import goose_node as gn
    made = run.assess(run.tight)
    with pytest.raises(gn.Refused, match="no sealed pick"):
        buyer.open_deal(run.maya, run.w.nodes["alder"], "0" * 64, made["alder"], "ask")


def test_picking_alder_pays_289_and_alders_card_reads_49_held(run):
    import buyer
    import deals
    made = run.assess(run.tight)
    alder = run.w.nodes["alder"]
    pick = buyer.seal_pick(run.maya, alder, made["alder"], [made["kestrel"]])
    deals.admit(alder, run.maya)
    chain = buyer.open_deal(run.maya, alder, pick, made["alder"], "ask")
    deals.run_deal(run.maya, alder, chain.terms, "ask", "", opened=chain, pay=lambda: run.rail.pay(289).reference)
    assert run.rail.paid == [289]
    later = datetime.now(timezone.utc) + timedelta(minutes=2)
    assert alder.tick(later).ticked
    card = alder.standard_history()
    assert len(card["deals"]) == 25 and sum(d["outcome"] == "held" for d in card["deals"]) == 25
    assert json.loads(card["card"])["bands"][0]["held"] == 25


def test_a_request_pinned_to_an_unknown_anchor_gets_no_card_and_no_selection(run):
    import buyer
    entry = next(e for e in run.entries if e["id"] == "alder")
    ev = buyer.gather(run.w, run.maya, entry, "ab" * 32, wait=3)
    assert ev.card is None and not ev.selection_ok
    assert [(c.name, c.ok) for c in ev.checks if not c.ok] == [("standard_history/1", False)]


def test_the_deal_cites_the_pick_and_mayas_book_holds_no_loop_admission(run):
    import buyer
    import deals
    import goose_node as gn
    made = run.assess(run.tight)
    alder = run.w.nodes["alder"]
    pick = buyer.seal_pick(run.maya, alder, made["alder"], [made["kestrel"]])
    deals.admit(alder, run.maya)
    chain = buyer.open_deal(run.maya, alder, pick, made["alder"], "ask")
    first = run.maya.shelf.open(f"deal/{chain.deal_id}").records()[0]
    assert pick in first.header.links_to("cites")
    assert run.maya.notes(gn.ADMITTED) == []
    assessment = next(r for r, s in run.maya.notes("ard_assessment") if r.record_id == made["alder"].record_id)
    assert assessment.header.links_to("cites"), "the assessment cites the card answer it read"


def test_no_buyer_side_book_holds_an_outcome_note(run):
    """u597: the outcome note is the seller's own, never in a shared copy. Only Kestrel's own books carry it."""
    import deals

    def notes(node) -> int:
        return sum(r.header.record_type == deals.OUTCOME_NOTE
                   for b in node.shelf.books() for r in node.shelf.open(b).records())

    assert notes(run.w.nodes["sample-buyer"]) == 0 and notes(run.maya) == 0 and notes(run.w.nodes["alder"]) == 0
    assert notes(run.w.nodes["kestrel"]) == 2
