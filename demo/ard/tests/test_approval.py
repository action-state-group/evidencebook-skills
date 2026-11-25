# SPDX-License-Identifier: Apache-2.0
"""The presenter's dialogs (the payment's and the ruling's): only the yes button approves; everything else refuses.
osascript is stubbed here, so no dialog appears and no engine is needed."""
from __future__ import annotations

import subprocess
import types

import pytest

import desktop_server as ds


def pay_dialog(summary: str) -> bool:
    return ds.ask_person("Approve this payment", summary, "Pay")


def answer(monkeypatch, returncode=0, stdout="", raises=None):
    def run(cmd, **kw):
        if raises:
            raise raises
        assert cmd[0] == "osascript" and "Cancel" in cmd[2] and 'default button "Cancel"' in cmd[2]
        return types.SimpleNamespace(returncode=returncode, stdout=stdout)

    monkeypatch.setattr(subprocess, "run", run)


def test_only_the_pay_button_approves(monkeypatch):
    answer(monkeypatch, stdout="button returned:Pay, gave up:false\n")
    assert pay_dialog("Pay Alder 289 msat") is True


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
    assert pay_dialog("Pay Alder 289 msat") is False


def test_quotes_in_the_summary_cannot_break_out_of_the_script(monkeypatch):
    seen = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: seen.append(cmd[2]) or types.SimpleNamespace(returncode=1, stdout=""))
    pay_dialog('x" & (do shell script "id") & "')
    assert 'do shell script "id"' not in seen[0] and "x' & (do shell script 'id') & '" in seen[0]


def test_the_dialog_gives_up_after_ten_minutes(monkeypatch):
    seen = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: seen.append(cmd[2]) or types.SimpleNamespace(returncode=1, stdout=""))
    pay_dialog("Pay X")
    assert f"giving up after {ds.DIALOG_GIVE_UP_S}" in seen[0] and ds.DIALOG_GIVE_UP_S == 600


def test_summary_wording_names_the_rail():
    # the text the presenter reads: real money on the real rails, none on the simulated one, and no word of a demo
    src = open(ds.__file__).read()
    assert 'over Lightning: this moves real money, to a wallet {shared} share"' in src and '"on the simulated rail: no money moves"' in src
    assert '"over Lightning, which moves real money?"' in src and "REAL Lightning rail" not in src
    assert "settles to the demo" not in src and "ARD demo: approve" not in src


def test_the_dialog_title_names_no_demo(monkeypatch):
    seen = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: seen.append(cmd[2]) or types.SimpleNamespace(returncode=1, stdout=""))
    pay_dialog("Pay Alder Print Co. 289 msat over Lightning: this moves real money.")
    assert 'with title "Approve this payment"' in seen[0] and "demo" not in seen[0].lower()


def test_the_assess_tool_description_names_no_demo():
    # the agent may repeat its tool description on screen
    assert "demo" not in (ds.ard_assess.__doc__ or "").lower()


def test_the_ruling_dialog_is_the_presenters_and_defaults_to_cancel(monkeypatch):
    seen = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: seen.append(cmd[2]) or types.SimpleNamespace(
        returncode=0, stdout="button returned:Rule, gave up:false\n"))
    assert ds.ask_person("Rule on this case", "Rule on deal x", "Rule") is True
    assert 'buttons {"Cancel", "Rule"}' in seen[0] and 'default button "Cancel"' in seen[0]


def test_approval_none_is_refused_on_a_real_rail(monkeypatch):
    monkeypatch.setenv("ARD_APPROVAL", "none")
    monkeypatch.setenv("ARD_RAIL", "local")
    with pytest.raises(RuntimeError, match="refused on the local rail"):
        ds.gate_off()


@pytest.mark.parametrize("returncode,stdout,stderr,raises,expected", [
    (0, "button returned:Pay, gave up:false\n", "", None, "yes"),
    (0, "button returned:, gave up:true\n", "", None, ds.NO_ANSWER),  # nobody clicked before it gave up
    (1, "", "execution error: User canceled. (-128)", None, ds.NO),  # the cancel button
    (0, "button returned:Cancel, gave up:false\n", "", None, ds.NO),  # a cancel button that returns instead of raising
    (1, "", "execution error: no display", None, ds.NOT_SHOWN),
    (0, "", "", OSError("no osascript"), ds.NOT_SHOWN),
    (0, "", "", subprocess.TimeoutExpired("osascript", 200), ds.NO_ANSWER),  # hung past its own give-up
])
def test_the_dialog_says_how_it_ended_so_a_timeout_is_never_called_a_decline(monkeypatch, returncode, stdout, stderr,
                                                                               raises, expected):
    # #239 finding 11 (ported from #292): a dialog that timed out was reported as "declined"
    def run(cmd, **kw):
        if raises:
            raise raises
        return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)
    monkeypatch.setattr(subprocess, "run", run)
    assert ds.dialog_answer("Approve this payment", "Pay X", "Pay") == expected
    assert ds.ask_person("Approve this payment", "Pay X", "Pay") is (expected == "yes")
    assert expected == "yes" or "declined" not in ds.NOT_YES[expected] or expected == ds.NO
