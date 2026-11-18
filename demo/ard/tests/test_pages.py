# SPDX-License-Identifier: Apache-2.0
"""The History card page (pages.py): capsule-viewer's own History view, pinned, drawing the party's own card with
every demo label, offline. With node on the path the view's own script draws each model, so a model the view would
refuse fails here. The engine test renders Kestrel's page from a seeded node."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from types import SimpleNamespace

import pytest

import pages
import screens
from conftest import engine_only

NODE = shutil.which("node")


def standard_history(bad: int = 1) -> dict:
    deals = [{"deal": f"d{i}", "agreed_at": f"2026-11-17T10:0{i}:00Z", "role": "provided",
              "amount": {"value": "268", "assetCode": "BTC", "assetScale": 11},
              "outcome": "did_not_hold" if i < bad else "held", "happened": "stamped_by_both", "disputes": []}
             for i in range(3)]
    card = {"outcomes": {"of": 3, "held": 3 - bad, "did_not_hold": bad, "undecided": 0}}
    return {"card": json.dumps(card), "deals": deals}


def model(sh: dict, seconds=True) -> dict:
    return pages.history_input(sh, name="Kestrel Print", seller=True, last_at={"d0": "2026-11-17T10:05:00Z"},
                               seconds={d["deal"]: ("the other party (key ab12)", "2026-11-17T10:06:00Z")
                                        for d in sh["deals"]} if seconds else {},
                               built_at="2026-11-17T11:00:00Z")


def draw(view_input: dict) -> str:
    """The view's own static HTML for this model, from the pinned script under node."""
    js = (pages.VIEWER_SCRIPT.read_text() + "\nprocess.stdout.write(HistoryView.historyViewHtml("
          "JSON.parse(require('fs').readFileSync(0,'utf8'))));")
    run = subprocess.run([NODE, "-e", js], input=json.dumps(view_input), capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    return run.stdout


def test_the_vendored_script_is_the_pinned_release():
    assert hashlib.sha256(pages.VIEWER_SCRIPT.read_bytes()).hexdigest() == pages.VIEWER_SHA256
    assert (pages.VIEWER_DIR / "history-view.iife.js.sha256").read_text().split()[0] == pages.VIEWER_SHA256


def test_the_page_carries_only_the_labels_its_count_needs():
    # No demo banner (Ethan, 2026-11-17); a count from the owner's own note keeps its label (u597).
    sh = standard_history()
    card = json.loads(sh["card"])
    for rail in ("fake", "lightning", "local"):
        page = pages.history_page(model(sh), pages.labels(card, rail, True, True, "Kestrel Print"), "History · Kestrel Print")
        for banner in (screens.BANNER_FAKE, screens.BANNER, screens.BANNER_LOCAL):
            assert pages.html.escape(banner) not in page
        assert "did not hold counted from the seller&#x27;s own note, not confirmed by the buyer or a ruling" in page
        # no scaffolding of ours on what the product draws: no sample-card notice, no (DEMO) title (Ethan, 2026-11-17)
        assert "sample card" not in page and "ard-demo" not in page and "(DEMO)" not in page
    quiet = pages.labels({"outcomes": {"of": 3, "did_not_hold": 0}}, "fake", True, False, "Alder Print Co.")
    assert quiet == []
    assert 'class="ard-labels"' not in pages.history_page(model(sh), quiet, "t")


def test_a_row_resting_on_the_partys_own_note_says_so():
    rows = model(standard_history())["rows"]
    assert [r["record"] for r in rows] == ["d2", "d1", "d0"]  # newest first
    bad = [r for r in rows if r["outcome"].startswith("did not hold")]
    assert len(bad) == 1 and pages.OWN_NOTE in bad[0]["outcome"] and "not confirmed by the buyer or a ruling" in bad[0]["outcome"]
    assert bad[0]["money"] == "268 msat" and bad[0]["last_at"] == "2026-11-17T10:05:00Z"


def test_a_second_signature_fills_only_from_a_half_this_node_verified():
    sh = standard_history()
    assert all(r["second_signature"]["state"] == "passed" for r in model(sh)["rows"])
    assert model(sh)["checks"][0] == {"id": "second_signature", "status": "pass"}
    unverified = model(sh, seconds=False)
    assert all(r["second_signature"] == {"state": "none"} for r in unverified["rows"])
    assert unverified["checks"][0]["status"] == "not_run"


def test_the_page_is_self_contained_and_fetches_nothing():
    page = pages.history_page(model(standard_history()), ["DEMO"], "t")
    assert "default-src 'none'" in page
    assert not re.search(r"<(link|img|iframe|object|embed)\b", page, re.I)
    assert not re.search(r"<script[^>]*\bsrc=", page, re.I)
    assert pages.viewer_script() in page


def test_caller_text_cannot_close_the_model_script():
    sh = standard_history()
    view = model(sh)
    view["holder"]["name"] = "</script><script>alert(1)</script>"
    page = pages.history_page(view, ["<b>x</b>"], "t")
    assert "</script><script>alert(1)" not in page and "<b>x</b>" not in page
    got = re.search(r'<script type="application/json" id="history-input">(.*?)</script>', page, re.S).group(1)
    assert json.loads(got) == view


def test_a_tampered_script_is_refused(tmp_path, monkeypatch):
    bad = tmp_path / "history-view.iife.js"
    bad.write_text("var HistoryView = {};")
    monkeypatch.setattr(pages, "VIEWER_SCRIPT", bad)
    with pytest.raises(pages.PageError):
        pages.viewer_script()


@pytest.mark.skipif(NODE is None, reason="node draws the view's own script")
def test_the_view_draws_the_model_with_its_labels():
    out = draw(model(standard_history()))
    assert "refused" not in out.lower()
    assert "Your History" in out and "3 deals, newest first" in out
    assert pages.OWN_NOTE in out and "268 msat" in out
    assert "the other party (key ab12) signed this record too" in out


@pytest.mark.skipif(NODE is None, reason="node draws the view's own script")
def test_an_empty_store_draws_its_own_hero():
    out = draw(model({"card": "{}", "deals": []}))
    assert "There are no deals in this store yet." in out


def test_card_page_writes_under_the_demo_home_and_opens_only_when_asked(tmp_path, monkeypatch):
    sh = standard_history()
    note = SimpleNamespace(header=SimpleNamespace(committed_at="2026-11-17T10:06:00Z"))
    node = SimpleNamespace(
        tick=lambda now: None, standard_history=lambda: sh,
        deal_payloads=lambda deal_id: [json.dumps({"x-deal-v0": {"at": "2026-11-17T10:05:00Z"}}).encode()],
        notes=lambda kind: [(note, {"deal_id": "d0", "key_id": "ab" * 32, "close_half_digest": "cd" * 32})])
    monkeypatch.setenv("ARD_HOME", str(tmp_path))
    monkeypatch.setenv("ARD_OPEN_PAGES", "0")
    monkeypatch.setattr(pages.subprocess, "run", lambda *a, **k: pytest.fail("ARD_OPEN_PAGES=0 opens nothing"))
    path = pages.card_page(node, "kestrel", "Kestrel Print", rail="fake", seller=True, sample_card=False)
    assert path.parent == tmp_path / "pages" and path.name.startswith("kestrel-history-")
    page = path.read_text()
    assert pages.html.escape(screens.BANNER_FAKE) not in page and "sample card" not in page
    assert pages.open_page(path) is False
    monkeypatch.setenv("ARD_OPEN_PAGES", "1")
    calls = []
    monkeypatch.setattr(pages.subprocess, "run", lambda argv, **k: calls.append(argv) or SimpleNamespace(returncode=0))
    assert pages.open_page(path) is True and calls == [["open", str(path)]]


@engine_only
def test_kestrels_own_page_from_a_seeded_node(tmp_path, monkeypatch):
    import seed
    from world import DEALS_EACH, World

    monkeypatch.setenv("ARD_HOME", str(tmp_path))
    with World(tmp_path / "home") as world:
        seed.seed(world, say=lambda *_: None, kestrel_card="sentinel")
        path = pages.card_page(world.nodes["kestrel"], "kestrel", "Kestrel Print", rail="fake", seller=True, sample_card=False)
        sh = world.nodes["kestrel"].standard_history()
        import deals

        def notes(node) -> int:  # u597: the owner's own note, never in the other party's books
            return sum(deals.noted(node, d) for d in deals.deal_ids(node))

        assert notes(world.nodes["kestrel"]) == 2 and notes(world.nodes["sample-buyer"]) == 0 and notes(world.nodes["alder"]) == 0
        seed.seed(world, say=lambda *_: None, kestrel_card="sentinel")  # a repeat seed notes no deal twice
        assert notes(world.nodes["kestrel"]) == 2
        assert sum(k == deals.OUTCOME_NOTE for d in deals.deal_ids(world.nodes["kestrel"])
                   for _, k, _ in world.nodes["kestrel"].deal(d).records) == 2
    page = path.read_text()
    assert "did not hold counted from the seller&#x27;s own note, not confirmed by the buyer or a ruling" in page
    view = json.loads(re.search(r'id="history-input">(.*?)</script>', page, re.S).group(1))
    assert len(view["rows"]) == len(sh["deals"]) == DEALS_EACH
    if NODE:
        out = draw(view)
        assert f"{DEALS_EACH} deals, newest first" in out and pages.OWN_NOTE in out
