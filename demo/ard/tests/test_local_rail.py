# SPDX-License-Identifier: Apache-2.0
"""The local rail (``pay.LocalRail``) against a stand-in for ``ard-pay-local``: the invoice's own amount is checked, the
buyer's answer is checked, nothing about a wallet is read here. No wallet and no money."""
from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pay  # noqa: E402

INVOICE_289 = "lnbc2890p1pnexample"  # 2890 pico-BTC = 289 msat (the amount is read from the human-readable part)


def program(tmp_path: Path, invoice: str = INVOICE_289, pay_answer: dict | None = None, fail: str = "") -> str:
    answer = {"status": "succeeded", "amount_msat": 289, "fee_msat": 0, "payment_hash": "ab" * 32}
    answer.update(pay_answer or {})
    script = tmp_path / "ard-pay-local"
    script.write_text(f"""#!{sys.executable}
import json, sys
cmd = sys.argv[1]
if {fail!r} == cmd:
    sys.stderr.write('boom'); sys.exit(1)
if cmd == "invoice":
    print(json.dumps({{"invoice": {invoice!r}, "amount_msat": int(sys.argv[2])}}))
elif cmd == "pay":
    print(json.dumps({answer!r}))
elif cmd == "balance":
    print(json.dumps({{"spendable_msat": 5000}}))
""")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def rail(tmp_path: Path, **kw) -> pay.LocalRail:
    return pay.LocalRail(program(tmp_path, **kw), str(tmp_path / "buyer"), str(tmp_path / "seller"))


def test_pays_the_invoice_the_seller_made(tmp_path):
    p = rail(tmp_path).pay(289)
    assert (p.invoice_msat, p.status, p.fee_msat, p.reference) == (289, "succeeded", 0, "ab" * 32)


def test_refuses_an_invoice_for_another_amount(tmp_path):
    with pytest.raises(pay.RailError, match="is for 500 msat"):
        rail(tmp_path, invoice="lnbc5000p1pnexample").pay(289)


def test_refuses_a_payment_that_did_not_succeed(tmp_path):
    with pytest.raises(pay.RailError, match="status failed"):
        rail(tmp_path, pay_answer={"status": "failed"}).pay(289)


def test_refuses_a_payment_of_another_amount(tmp_path):
    with pytest.raises(pay.RailError, match="paid 300 msat"):
        rail(tmp_path, pay_answer={"amount_msat": 300}).pay(289)


def test_a_failing_program_is_a_rail_error_without_its_output(tmp_path):
    with pytest.raises(pay.RailError, match="invoice: exit 1"):
        rail(tmp_path, fail="invoice").pay(289)


@pytest.mark.parametrize("kw", [{"invoice": "lnbc5000p1pnexample"}, {"fail": "invoice"}])
def test_a_failure_before_the_send_says_nothing_was_sent(tmp_path, kw):
    # #289: only a failure before the buyer's send may tell the seller the order is off
    with pytest.raises(pay.NotSent):
        rail(tmp_path, **kw).pay(289)


@pytest.mark.parametrize("kw", [{"pay_answer": {"status": "failed"}}, {"pay_answer": {"amount_msat": 300}}, {"fail": "pay"}])
def test_a_failure_during_or_after_the_send_is_not_called_unsent(tmp_path, kw):
    with pytest.raises(pay.RailError) as err:
        rail(tmp_path, **kw).pay(289)
    assert not isinstance(err.value, pay.NotSent)  # money may have moved


def test_balances_name_both_wallets(tmp_path):
    assert rail(tmp_path).balances() == {"seller": {"spendable_msat": 5000}, "buyer": {"spendable_msat": 5000}}


def test_from_env_builds_each_rail_and_says_what_the_local_rail_needs(tmp_path, monkeypatch):
    assert isinstance(pay.from_env("fake"), pay.FakeRail)
    for k in ("ARD_PAY_LOCAL", "ARD_WALLET_BUYER", "ARD_WALLET_SELLER"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))  # no ln-pay-local on the PATH
    with pytest.raises(pay.RailError, match="ARD_WALLET_BUYER, ARD_WALLET_SELLER"):
        pay.from_env("local")
    monkeypatch.setenv("ARD_WALLET_BUYER", "b")
    monkeypatch.setenv("ARD_WALLET_SELLER", "s")
    with pytest.raises(pay.RailError, match="needs the ln-pay-local program"):
        pay.from_env("local")
    monkeypatch.setenv("ARD_PAY_LOCAL", program(tmp_path))
    assert isinstance(pay.from_env("local"), pay.LocalRail)
    with pytest.raises(pay.RailError, match="unknown rail"):
        pay.from_env("nope")
