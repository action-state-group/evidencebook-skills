# SPDX-License-Identifier: Apache-2.0
"""A card or receipt page opens in the browser only in a person's run (#465): ``pages.open_page`` runs ``open`` only on
``ARD_OPEN_PAGES=1``, which ``goose/open-windows.py`` puts only in the recipes it opens in Goose Desktop. Agent runs,
tests, the goose command line (``--print``) and scripts/check.sh leave it unset, so they write the page and never call
``open``. No browser runs: ``subprocess.run`` is recorded."""
from __future__ import annotations

import base64
import importlib.util
import json
import os
import types
from pathlib import Path

import pytest

import pages

HERE = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("open_windows_pages", HERE / "goose" / "open-windows.py")
ow = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ow)


@pytest.fixture
def opened(monkeypatch):
    made = []
    monkeypatch.setattr(pages.subprocess, "run",
                        lambda cmd, **kw: made.append(list(cmd)) or types.SimpleNamespace(returncode=0))
    return made


@pytest.mark.parametrize("value", [None, "0", "", "true", "yes"])
def test_a_page_is_written_but_not_opened_unless_the_run_says_1(opened, monkeypatch, tmp_path, value):
    if value is None:
        monkeypatch.delenv("ARD_OPEN_PAGES", raising=False)
    else:
        monkeypatch.setenv("ARD_OPEN_PAGES", value)
    assert pages.open_page(tmp_path / "page.html") is False
    assert opened == []


def test_a_persons_run_opens_the_page(opened, monkeypatch, tmp_path):
    monkeypatch.setenv("ARD_OPEN_PAGES", "1")
    assert pages.open_page(tmp_path / "page.html") is True
    assert opened == [["open", str(tmp_path / "page.html")]]


def test_the_tests_themselves_never_carry_it():
    # conftest drops it, so a shell that exported ARD_OPEN_PAGES=1 opens nothing from a test run
    assert "ARD_OPEN_PAGES" not in os.environ


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("CAPSULE_ENGINE", "/bin/true")
    monkeypatch.setenv("ARD_EVIDENCEBOOK", "/nonexistent/evidencebook")
    monkeypatch.setenv("CAPSULECTL_DEAL", "/opt/capsulectl-deal")
    monkeypatch.setattr(ow.envhelp, "message", lambda *a, **k: None)


def _server_env(link: str) -> list[str]:
    config = link.split("config=", 1)[1]
    recipe = json.loads(base64.urlsafe_b64decode(config + "=" * (-len(config) % 4)))
    return recipe["extensions"][0]["args"]


@pytest.mark.parametrize("value, opens", [(None, False), ("0", False), ("1", True)])
def test_printed_recipes_open_pages_only_when_the_shell_says_1(env, monkeypatch, capsys, value, opens):
    # --print is the goose command line's and an agent's path: its windows write pages and open none by default
    if value is not None:
        monkeypatch.setenv("ARD_OPEN_PAGES", value)
    assert ow.main(["--print"]) == 0
    links = capsys.readouterr().out.split()
    assert len(links) == 4
    for link in links:
        assert f"ARD_OPEN_PAGES={1 if opens else 0}" in _server_env(link)


@pytest.mark.parametrize("value, desktop, opens", [(None, True, True), ("1", True, True), ("0", True, False),
                                                    (None, False, False), ("0", False, False), ("1", False, True)])
def test_opens_pages(monkeypatch, value, desktop, opens):
    if value is not None:
        monkeypatch.setenv("ARD_OPEN_PAGES", value)
    assert ow.opens_pages(desktop=desktop) is opens


def test_a_recipe_says_1_only_when_asked_and_0_otherwise(env):
    # 0 is written, not left out: env(1) adds to the environment it inherits, so a window Goose starts from a process
    # that carries ARD_OPEN_PAGES=1 still opens nothing unless its recipe says 1
    for role in ("alder", "kestrel", "adjudicator", "maya"):
        on = [a for a in ow.recipe(role, "fake", open_pages=True)["extensions"][0]["args"] if a.startswith("ARD_OPEN_PAGES")]
        off = [a for a in ow.recipe(role, "fake")["extensions"][0]["args"] if a.startswith("ARD_OPEN_PAGES")]
        assert on == ["ARD_OPEN_PAGES=1"] and off == ["ARD_OPEN_PAGES=0"]


def test_a_window_started_from_a_process_with_1_still_opens_nothing_when_its_recipe_says_0(env, tmp_path):
    # the window's server runs as the recipe says: /usr/bin/env <assignments> python desktop_server.py
    import subprocess
    import sys
    args = ow.recipe("maya", "fake")["extensions"][0]["args"]
    assignments = [a for a in args if "=" in a and not a.startswith("/")]
    probe = "import os; print(os.environ.get('ARD_OPEN_PAGES'))"
    run = subprocess.run(["/usr/bin/env", *assignments, sys.executable, "-c", probe], capture_output=True, text=True,
                         env={**os.environ, "ARD_OPEN_PAGES": "1"}, stdin=subprocess.DEVNULL, timeout=30)
    assert run.stdout.strip() == "0"


@pytest.mark.parametrize("value, opens", [(None, False), ("1", True)])
def test_the_card_page_tool_says_written_with_its_path_and_opens_only_on_1(opened, monkeypatch, tmp_path, value, opens):
    import desktop_server as ds
    if value is not None:
        monkeypatch.setenv("ARD_OPEN_PAGES", value)
    page = tmp_path / "history.html"
    monkeypatch.setattr(ds, "ROLE", "alder")
    monkeypatch.setattr(ds, "_own", lambda: (types.SimpleNamespace(), "Alder Print Co."))
    monkeypatch.setattr(pages, "card_page", lambda *a, **k: page)
    out = ds.ard_open_card_page()
    assert out.endswith(f": {page}")
    assert ("written (not opened)" in out) is not opens
    assert opened == ([["open", str(page)]] if opens else [])


@pytest.mark.parametrize("value, opens", [(None, False), ("1", True)])
def test_the_receipt_page_tool_says_written_with_its_path_and_opens_only_on_1(opened, monkeypatch, tmp_path, value, opens):
    import desktop_server as ds
    import receipt
    if value is not None:
        monkeypatch.setenv("ARD_OPEN_PAGES", value)
    page = tmp_path / "receipt.html"
    monkeypatch.setattr(ds, "ROLE", "alder")  # a seller: the page line alone, no ruling lines after it
    monkeypatch.setattr(ds, "_own_deal", lambda: (types.SimpleNamespace(log=lambda line: None), "Alder Print Co.",
                                                  "deal-0123456789abcdef"))
    monkeypatch.setattr(receipt, "receipt_page", lambda *a, **k: page)
    out = ds.ard_open_receipt_page()
    assert out.rstrip().endswith(f": {page}")
    assert ("written (not opened)" in out) is not opens
    assert opened == ([["open", str(page)]] if opens else [])
