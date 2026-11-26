# SPDX-License-Identifier: Apache-2.0
"""Maya's tool ard_countersign (evidencebook-skills#383, Codex round 1 on #396): which deal it countersigns, what it
says when the deal or the countersigner is not there, and that its line is the receipt's line from capsulectl's
report. No binary is run: Maya's party is a stand-in that records the deal it was asked to countersign."""
from __future__ import annotations

import threading

import pytest

import buyer
import countersigner as cs
import desktop_server as ds
import receipt


def _deal(n: str, seller: str = "alder") -> buyer.Deal:
    return buyer.Deal(deal_id=f"deal-{n}", seller=seller, seller_key="k" * 64, price_msat=2000, offer="o",
                      rail="simulated", me="maya")


STAMP = {"rung": "countersigned", "signer": cs.NAME, "recomputed_at": "2026-11-26T18:46:50Z", "through_step": 4,
         "steps": 4}
SERVICE = {"ARD_COUNTERSIGN_URL": "https://localhost:5/countersign/register", "SSL_CERT_FILE": "ca.pem"}


class FakeMaya:
    def __init__(self):
        self.asked = []

    def countersign(self, deal_id, service):
        self.asked.append((deal_id, service))
        return STAMP


@pytest.fixture
def maya(tmp_path, monkeypatch):
    m = FakeMaya()
    s = type("S", (), {})()
    s.home, s.maya, s.pay_lock = tmp_path, m, threading.Lock()
    s.deals = [_deal("aaaa1111aaaa1111"), _deal("bbbb2222bbbb2222", "kestrel"), _deal("aaaa3333aaaa3333")]
    monkeypatch.setattr(ds, "session", lambda: s)
    monkeypatch.delenv("ARD_COUNTERSIGN_DIR", raising=False)
    looked = []
    monkeypatch.setattr(cs, "env", lambda d: looked.append(d) or SERVICE)
    m.looked, m.s = looked, s
    return m


def test_it_countersigns_her_latest_deal_with_that_seller_and_says_the_receipts_line(maya, tmp_path):
    out = ds.ard_countersign("Alder")
    assert maya.asked == [("deal-aaaa3333aaaa3333", SERVICE)]
    assert maya.looked == [cs.default_dir(tmp_path)]
    assert out.strip() == "Maya's deal aaaa3333 with Alder Print Co.: " + receipt.countersign_line(STAMP, "Maya",
                                                                                                    "Alder Print Co.")


def test_a_deal_prefix_picks_that_deal(maya):
    ds.ard_countersign("alder", deal="aaaa1")
    assert maya.asked[0][0] == "deal-aaaa1111aaaa1111"


@pytest.mark.parametrize("deal,words", [("cccc", "no deal with Alder Print Co. matches"),
                                        ("aaaa", "more than one deal with Alder Print Co. matches")])
def test_a_prefix_that_names_no_deal_or_two_is_refused(maya, deal, words):
    out = ds.ard_countersign("alder", deal=deal)
    assert words in out and maya.asked == []


def test_no_deal_with_that_seller_is_refused(maya):
    maya.s.deals = [d for d in maya.s.deals if d.seller != "kestrel"]
    out = ds.ard_countersign("kestrel")
    assert "Maya has no deal with" in out and maya.asked == []


def test_no_countersigner_running_says_how_to_start_it(maya, monkeypatch):
    def none(d):
        raise cs.CountersignerError("no countersigner runs; start it with `python demo/ard/countersigner.py up`")
    monkeypatch.setattr(cs, "env", none)
    out = ds.ard_countersign("alder")
    assert "countersigner.py up" in out and maya.asked == []


def test_ard_countersign_dir_names_another_folder(maya, monkeypatch, tmp_path):
    monkeypatch.setenv("ARD_COUNTERSIGN_DIR", str(tmp_path / "elsewhere"))
    ds.ard_countersign("alder")
    assert maya.looked == [tmp_path / "elsewhere"]
