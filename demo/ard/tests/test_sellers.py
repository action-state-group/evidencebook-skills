# SPDX-License-Identifier: Apache-2.0
"""Each seller's own file (#299): what it discloses and what it offers are read from ``sellers/<name>.yaml``, and the
signed disclosure policy its commitment's ``lcap.policy_uri`` names is served where that URI points."""
from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request

import pytest

import ard
import cast
import commitment as cm
from discovery import Discovery

needs_ctl = pytest.mark.skipif(not os.environ.get("CAPSULECTL_DEAL"), reason="CAPSULECTL_DEAL names capsulectl-deal")


def test_each_seller_file_holds_the_terms_the_code_used_to_fix():
    for name, price in (("alder", 2000), ("kestrel", 1000)):
        s = cast.SELLERS[name]
        assert s["price_msat"] == price and s["item"] == "200 conference badges, delivered by Friday"
        assert s["discloses"] == {"subjects": ["checkpoints", "full_history"], "derivations": ["history_card/2"],
                                  "human_gated": False, "answers_within": "PT1H"}
    assert cast.SELLERS["kestrel"]["shipped"] == "150 of 200 badges"  # the run's story stays in the code, not the file


def test_each_seller_file_says_it_holds_placeholders_and_only_disclosure_terms_and_the_offer():
    for name in cast.SHIPS:
        text = (cast.SELLERS_DIR / f"{name}.yaml").read_text()
        assert text.startswith("# Demo placeholders:")
        assert "Disclosure terms and the offer only" in text


@pytest.mark.parametrize("body", [
    "label: X\noffer: {item: x, price_msat: 0}\ndiscloses: {subjects: [a], derivations: [b], human_gated: false, "
    "answers_within: PT1H}\n",
    "label: X\noffer: {item: x, price_msat: 5}\ndiscloses: {subjects: [], derivations: [b], human_gated: false, "
    "answers_within: PT1H}\n",
    "label: X\noffer: {item: x, price_msat: 5}\ndiscloses: {subjects: [a], derivations: [b], human_gated: 'no', "
    "answers_within: PT1H}\n",
    "label: X\noffer: {item: x, price_msat: 5, discount: 1}\ndiscloses: {subjects: [a], derivations: [b], "
    "human_gated: false, answers_within: PT1H}\n",
    "just text\n",
    "label: X\noffer: {item: x, price_msat: 5}\ndiscloses: {subjects: [a], derivations: [b], human_gated: false, "
    "answers_within: PT1H}\n",
])
def test_a_seller_file_with_a_wrong_or_extra_member_is_refused(tmp_path, monkeypatch, body):
    (tmp_path / "x.yaml").write_text(body)
    monkeypatch.setattr(cast, "SELLERS_DIR", tmp_path)
    with pytest.raises(ValueError, match="needs label, offer|keeps history_card/2"):
        cast.seller_file("x")


def test_an_edited_seller_file_is_what_the_sellers_own_entry_lists(tmp_path, monkeypatch):
    (tmp_path / "alder.yaml").write_text(
        "label: Alder Print Co.\noffer: {item: 300 lanyards, price_msat: 1500}\n"
        "discloses: {subjects: [checkpoints], derivations: [history_card/2], human_gated: true, answers_within: PT2H}\n")
    monkeypatch.setattr(cast, "SELLERS_DIR", tmp_path)
    alder = cast.seller_file("alder")
    assert alder["discloses"] == {"subjects": ["checkpoints"], "derivations": ["history_card/2"], "human_gated": True,
                                  "answers_within": "PT2H"}
    monkeypatch.setattr(cm, "verify", lambda doc: None)
    d = Discovery({"alder": alder}, lambda n: {"key_id": "k", "profile": cm.PROFILE})
    try:
        with urllib.request.urlopen(d.sellers["alder"].origin + ard.WELL_KNOWN) as r:
            (e,) = json.loads(r.read())["entries"]
    finally:
        d.close()
    assert e["x-demo-offer"] == {"item": "300 lanyards", "price_msat": 1500, "currency": "msat"}


def test_a_deal_names_the_item_the_chosen_sellers_file_lists(monkeypatch):
    import buyer

    monkeypatch.setitem(cast.SELLERS, "kestrel", {**cast.SELLERS["kestrel"], "item": "300 lanyards"})
    seen = []

    class Maya:
        def check(self, deal_id, action, item, *a, **kw):
            seen.append(item)
            return {}

    buyer.check_payment(Maya(), buyer.Deal("deal-1", "kestrel", "k", 1000, "o", "simulated"), "ref")
    assert seen == ["300 lanyards"]


def test_the_policy_uri_resolves_against_the_commitment_url_on_the_sellers_own_origin(monkeypatch):
    monkeypatch.setattr(cm, "verify", lambda doc: None)
    node = "ab" * 32
    docs = {n: {"key_id": f"{n}-key", "profile": cm.PROFILE, "lcap": {"policy_uri": f"policies/{node}.json"}}
            for n in cast.SHIPS}
    served = {f"policies/{node}.json": b'{"profile":"disclosure-policy/0"}\n'}
    d = Discovery({n: cast.SELLERS[n] for n in cast.SHIPS}, docs.get, policy=served.get)
    try:
        url = d.sellers["alder"].origin + "/commitments/alder.json"
        with urllib.request.urlopen(urllib.parse.urljoin(url, docs["alder"]["lcap"]["policy_uri"])) as r:
            assert r.read() == served[f"policies/{node}.json"]
        with pytest.raises(urllib.error.HTTPError):  # only the URI the commitment names
            urllib.request.urlopen(d.sellers["alder"].origin + f"/commitments/policies/{'cd' * 32}.json")
    finally:
        d.close()


def test_the_stage_serves_only_a_policy_file_under_its_commitments(tmp_path):
    import stage

    st = stage.Stage.__new__(stage.Stage)
    st.dir = tmp_path
    (tmp_path / "commitments" / "policies").mkdir(parents=True)
    (tmp_path / "commitments" / "policies" / f"{'ab' * 32}.json").write_bytes(b"policy")
    (tmp_path / "secret.json").write_bytes(b"secret")
    assert st.policy(f"policies/{'ab' * 32}.json") == b"policy"
    assert st.policy("../secret.json") is None and st.policy("policies/../../secret.json") is None
    assert st.policy(f"policies/{'cd' * 32}.json") is None


@needs_ctl
def test_a_changed_seller_file_changes_the_signed_commitment_the_entry_and_the_served_policy(tmp_path, monkeypatch):
    import flow
    import party as pt
    import stage

    alder = {**cast.SELLERS["alder"], "price_msat": 1500,
             "discloses": {"subjects": ["checkpoints"], "derivations": ["history_card/2"], "human_gated": True,
                           "answers_within": "PT2H"}}
    monkeypatch.setitem(cast.SELLERS, "alder", alder)
    monkeypatch.setattr(flow, "SELLERS", cast.SELLERS)
    pt.Party(tmp_path, "alder").create("node", neutral=True, witness=False)
    agent = flow.SellerAgent(tmp_path, "alder", start=False)
    doc = json.loads((flow.stage_dir(tmp_path) / "commitments" / "alder.json").read_bytes())
    assert doc["key_id"] == agent.party.key_id
    assert doc["answers"] == {"subjects": ["checkpoints"], "derivations": ["history_card/2"]}
    assert doc["human_gated"] is True and doc["answers_within"] == "PT2H"
    cm.verify(doc)
    assert ard.entry("alder", alder, doc, "http://x")["x-demo-offer"]["price_msat"] == 1500

    st = stage.Stage.__new__(stage.Stage)
    st.dir = flow.stage_dir(tmp_path)
    d = Discovery({"alder": alder}, lambda n: doc if n == "alder" else None, policy=st.policy)
    try:
        url = d.sellers["alder"].origin + "/commitments/alder.json"
        with urllib.request.urlopen(urllib.parse.urljoin(url, doc["lcap"]["policy_uri"])) as r:
            policy = r.read()
    finally:
        d.close()
    assert hashlib.sha256(policy).hexdigest() == doc["lcap"]["policy_digest"]
    assert json.loads(policy)["key_id"] == doc["key_id"]
