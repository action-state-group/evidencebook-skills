# SPDX-License-Identifier: Apache-2.0
"""Discovery through the demo's stand-ins: each seller serves its own ard.json, the stand-in registry answers
POST /search, and the buyer checks each result against the seller's own entry and commitment. No engine needed."""
from __future__ import annotations

import json
import urllib.request

import pytest

import ard
import commitment as cm
from discovery import Discovery

SELLERS = {"alder": {"label": "Alder Print Co.", "price_msat": 289, "item": "200 conference badges"},
           "kestrel": {"label": "Kestrel Print", "price_msat": 268, "item": "200 conference badges"}}


@pytest.fixture
def docs(monkeypatch):
    monkeypatch.setattr(cm, "verify", lambda doc: None)  # the commitment's own check has its tests in the Goose reference
    return {n: {"key_id": f"{n}-key", "profile": "evidence-commitment/1"} for n in SELLERS}


@pytest.fixture
def disc(docs):
    d = Discovery(SELLERS, lambda n: docs.get(n))
    yield d
    d.close()


def test_each_seller_serves_its_own_entry_with_a_test_publisher(disc):
    with urllib.request.urlopen(disc.sellers["alder"].origin + ard.WELL_KNOWN) as r:
        m = json.loads(r.read())
    (e,) = m["entries"]
    assert e["identifier"] == "urn:air:alder.ard-demo.test:print:alder"
    assert e["trustManifest"]["identity"] == "alder.ard-demo.test"
    assert {"identifier", "displayName", "type", "url"} <= set(e)


def test_the_registry_answers_search_and_the_buyer_verifies_each_seller(disc):
    found = ard.lookup(disc.registry.url, disc.origins, "conference badges print")
    assert sorted(f["id"] for f in found) == ["alder", "kestrel"]
    for f in found:
        assert "problem" not in f and f["commitment"]["key_id"] == f"{f['id']}-key"
        assert any("pointer only" in c for c in f["checks"]) and any("matches the seller's own entry" in c for c in f["checks"])


def test_the_search_carries_only_the_item_query(disc, monkeypatch):
    sent = []
    real = ard._fetch
    monkeypatch.setattr(ard, "_fetch", lambda url, body=None: (sent.append(body), real(url, body))[1])
    ard.search(disc.registry.url, "conference badges")
    assert json.loads(sent[0]) == {"query": {"text": "conference badges"}, "federation": "none", "pageSize": 10}


def test_an_entry_whose_identity_names_another_domain_is_refused(disc, monkeypatch):
    real = ard.entry
    monkeypatch.setattr(ard, "entry", lambda n, s, d, o: {**real(n, s, d, o), "trustManifest": {
        **real(n, s, d, o)["trustManifest"], "identity": "evil.example"}} if n == "kestrel" else real(n, s, d, o))
    found = {f["id"]: f for f in ard.lookup(disc.registry.url, disc.origins, "conference badges print")}
    assert "commitment" in found["alder"]
    assert "does not name its publisher" in found["kestrel"]["problem"] and "commitment" not in found["kestrel"]


def test_a_commitment_whose_digest_differs_from_the_entry_is_refused(disc, monkeypatch):
    real = ard.entry

    def tampered(n, s, d, o):
        e = real(n, s, d, o)
        if n == "kestrel":
            tm = e["trustManifest"]
            e = {**e, "trustManifest": {**tm, "attestations": [{**a, "digest": "sha256:" + "0" * 64} for a in tm["attestations"]]}}
        return e

    monkeypatch.setattr(ard, "entry", tampered)
    found = {f["id"]: f for f in ard.lookup(disc.registry.url, disc.origins, "conference badges print")}
    assert "commitment" in found["alder"] and "commitment digest matches the seller's entry" in found["alder"]["checks"]
    assert "digest differs" in found["kestrel"]["problem"] and "commitment" not in found["kestrel"]


def test_an_unreachable_publisher_is_refused(disc):
    found = ard.lookup(disc.registry.url, {"alder.ard-demo.test": disc.origins["alder.ard-demo.test"]}, "badges print")
    by = {f["id"]: f for f in found}
    assert "not one the buyer can reach" in by["kestrel"]["problem"]


def test_a_search_without_text_gets_an_error(disc):
    req = urllib.request.Request(disc.registry.url, data=b'{"query": {}}', headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        assert "query.text" in json.loads(r.read())["error"]
