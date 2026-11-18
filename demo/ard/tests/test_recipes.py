# SPDX-License-Identifier: Apache-2.0
"""Each Goose window's recipe is thin: the party's facts and the rail, then the skill it follows, read from this
repository's skills (#169). No engine needed."""
from __future__ import annotations

import base64
import importlib.util
import json
import re
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]
_spec = importlib.util.spec_from_file_location("open_windows", HERE / "goose" / "open-windows.py")
ow = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ow)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("CAPSULE_ENGINE", "/bin/true")
    monkeypatch.setenv("ARD_EVIDENCEBOOK", "/nonexistent/evidencebook")


def _recipe(link: str) -> dict:
    config = link.split("config=", 1)[1]
    return json.loads(base64.urlsafe_b64decode(config + "=" * (-len(config) % 4)))


def test_no_recipe_link_ends_in_base64_padding():
    # Goose Desktop drops a link whose config ends in "=": every window must open, whatever its recipe's length.
    for role in ("alder", "kestrel", "maya"):
        for rail in ("fake", "lightning"):
            link = ow.link(role, rail)
            assert not link.endswith("=") and "=" not in link.split("config=", 1)[1]
            assert _recipe(link)["extensions"][0]["name"] == f"ard_{role}"


def _skill_body(name: str) -> str:
    return (ROOT / "skills" / name / "SKILL.md").read_text().split("\n---\n", 1)[1].strip()


def test_maya_follows_the_buyer_skill_with_her_facts_and_the_rail():
    text = _recipe(ow.link("maya", "fake"))["instructions"]
    assert text.startswith("You are Maya's buying agent. Maya needs 200 conference badges by Friday, under 300 msat.")
    assert "no money moves" in text and "Follow the buy-with-evidence skill below" in text
    assert _skill_body("buy-with-evidence") in text and "name: buy-with-evidence" not in text


def test_maya_is_given_the_registry_the_stage_serves(monkeypatch):
    # parties.py (which needs the Goose reference to import) serves POST /search on the same variable and default
    assert 'HTTP_PORT = int(os.environ.get("ARD_STAGE_PORT", "47481"))' in (HERE / "parties.py").read_text()
    text = _recipe(ow.link("maya", "fake"))["instructions"]
    assert "The ARD registry to search is http://127.0.0.1:47481/search" in text
    assert "registry to search" not in _recipe(ow.link("alder", "fake"))["instructions"]
    monkeypatch.setenv("ARD_STAGE_PORT", "48000")
    r = _recipe(ow.link("maya", "fake"))
    assert "http://127.0.0.1:48000/search" in r["instructions"] and "ARD_STAGE_PORT=48000" in r["extensions"][0]["args"]


def test_a_real_rail_says_real_money_moves():
    assert "real money moves" in _recipe(ow.link("maya", "lightning"))["instructions"]


def test_the_sellers_follow_the_seller_skill():
    for role in ("alder", "kestrel"):
        r = _recipe(ow.link(role, "fake"))
        assert "Follow the sell-with-evidence skill below" in r["instructions"]
        assert _skill_body("sell-with-evidence") in r["instructions"]
        assert r["extensions"][0]["name"] == f"ard_{role}"


def test_the_recipe_carries_nothing_of_its_own_beyond_the_facts():
    text = _recipe(ow.link("maya", "fake"))["instructions"]
    own = text.split("Follow the buy-with-evidence skill below", 1)[0]
    assert len(own.splitlines()) <= 3, own


def test_every_demo_tool_a_skill_names_is_a_tool_of_this_demo():
    tools = set(re.findall(r'^def (ard_\w+)\(', (HERE / "desktop_server.py").read_text(), re.M))
    for name in ("buy-with-evidence", "sell-with-evidence"):
        named = set(re.findall(r"`(ard_\w+)`", (ROOT / "skills" / name / "SKILL.md").read_text()))
        assert named and named <= tools, (name, named - tools)
