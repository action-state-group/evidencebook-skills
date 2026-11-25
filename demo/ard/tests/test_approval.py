# SPDX-License-Identifier: Apache-2.0
"""The approval dialog's reading of osascript's answer: only the Pay button approves; everything else refuses.
osascript is stubbed here, so no dialog appears and no engine is needed."""
from __future__ import annotations

import subprocess
import types

import pytest

import desktop_server as ds


def answer(monkeypatch, returncode=0, stdout="", raises=None):
    def run(cmd, **kw):
        if raises:
            raise raises
        assert cmd[0] == "osascript" and "Cancel" in cmd[2] and 'default button "Cancel"' in cmd[2]
        return types.SimpleNamespace(returncode=returncode, stdout=stdout)

    monkeypatch.setattr(subprocess, "run", run)


def test_only_the_pay_button_approves(monkeypatch):
    answer(monkeypatch, stdout="button returned:Pay, gave up:false\n")
    assert ds.approve_payment("Pay Alder 289 msat") is True


@pytest.mark.parametrize("kw", [
    {"returncode": 1, "stdout": ""},                                  # Cancel ("User canceled")
    {"stdout": "button returned:Cancel, gave up:false\n"},
    {"stdout": "button returned:Pay, gave up:true\n"},               # timed out
    {"returncode": 1, "stdout": "button returned:Pay"},              # osascript failed
    {"raises": OSError("no osascript")},
    {"raises": subprocess.TimeoutExpired("osascript", 200)},
])
def test_anything_else_refuses(monkeypatch, kw):
    answer(monkeypatch, **kw)
    assert ds.approve_payment("Pay Alder 289 msat") is False


def test_quotes_in_the_summary_cannot_break_out_of_the_script(monkeypatch):
    seen = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: seen.append(cmd[2]) or types.SimpleNamespace(returncode=1, stdout=""))
    ds.approve_payment('x" & (do shell script "id") & "')
    assert 'do shell script "id"' not in seen[0] and "x' & (do shell script 'id') & '" in seen[0]


def test_the_dialog_gives_up_after_three_minutes(monkeypatch):
    seen = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: seen.append(cmd[2]) or types.SimpleNamespace(returncode=1, stdout=""))
    ds.approve_payment("Pay X")
    assert f"giving up after {ds.parties.DIALOG_GIVE_UP_S}" in seen[0]


def test_summary_wording_names_the_rail():
    # the text the presenter reads: real money on the real rails, none on the simulated one, and no word of a demo
    src = open(ds.__file__).read()
    assert 'over Lightning: this moves real money, to a wallet {shared} share"' in src and '"on the simulated rail: no money moves"' in src
    assert '"over Lightning, which moves real money?"' in src and "REAL Lightning rail" not in src
    assert "settles to the demo" not in src and "ARD demo: approve" not in src


def test_the_dialog_title_names_no_demo(monkeypatch):
    seen = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: seen.append(cmd[2]) or types.SimpleNamespace(returncode=1, stdout=""))
    ds.approve_payment("Pay Alder Print Co. 289 msat over Lightning: this moves real money.")
    assert 'with title "Approve this payment"' in seen[0] and "demo" not in seen[0].lower()


def test_the_assess_tool_description_names_no_demo():
    # the agent may repeat its tool description on screen
    assert "demo" not in (ds.ard_assess.__doc__ or "").lower()


def hold_answer(monkeypatch, returncode=0, stdout="", raises=None):
    def run(cmd, **kw):
        if raises:
            raise raises
        assert cmd[0] == "osascript" and 'buttons {"Don\'t buy", "Buy anyway"}' in cmd[2]
        assert 'default button "Don\'t buy"' in cmd[2] and 'cancel button "Don\'t buy"' in cmd[2]
        assert 'with title "This order goes over your weekly limit"' in cmd[2]
        return types.SimpleNamespace(returncode=returncode, stdout=stdout)

    monkeypatch.setattr(subprocess, "run", run)


def test_only_the_buy_anyway_button_approves_a_held_order(monkeypatch):
    hold_answer(monkeypatch, stdout="button returned:Buy anyway, gave up:false\n")
    assert ds.approve_hold("This order goes over your weekly limit", "200 badges ...") is True


@pytest.mark.parametrize("kw", [
    {"returncode": 1, "stdout": ""},
    {"stdout": "button returned:Don't buy, gave up:false\n"},
    {"stdout": "button returned:Buy anyway, gave up:true\n"},
    {"returncode": 1, "stdout": "button returned:Buy anyway"},
    {"raises": OSError("no osascript")},
    {"raises": subprocess.TimeoutExpired("osascript", 200)},
])
def test_anything_else_declines_a_held_order(monkeypatch, kw):
    hold_answer(monkeypatch, **kw)
    assert ds.approve_hold("This order goes over your weekly limit", "200 badges ...") is False
