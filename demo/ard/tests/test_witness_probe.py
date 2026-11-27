# SPDX-License-Identifier: Apache-2.0
"""witness_probe's exit status (evidencebook-skills#378): 0 only when every profile took every stamp in time."""
from __future__ import annotations

import party as pt
import pytest
import witness_probe


class FakeParty:
    """A profile whose stamps the witness takes, or not, as ``outcome(name)`` says."""
    outcome = staticmethod(lambda name: "taken")

    def __init__(self, home, name):
        self.name = name

    def create(self, holder_kind, witness=True):
        if FakeParty.outcome(self.name) == "no profile":
            raise pt.Refused("capsulectl-deal init refused")
        return self

    def wait_checkpoint(self, seconds):
        if FakeParty.outcome(self.name) == "slow":
            raise pt.WitnessSlow(f"{pt.WITNESS_NAME} took no stamp within {int(seconds)} s")
        return {"state": "ticked"}


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(pt, "Party", FakeParty)
    monkeypatch.delenv("ARD_E2E_WITNESS_URL", raising=False)
    monkeypatch.delenv("ARD_E2E_WITNESS_KEY", raising=False)
    monkeypatch.setenv("ARD_WITNESS", "off")  # main sets it to public; monkeypatch restores it afterwards
    return FakeParty


def test_every_stamp_taken_passes(fake, monkeypatch, capsys):
    monkeypatch.setattr(fake, "outcome", staticmethod(lambda name: "taken"))
    assert witness_probe.main(["--stamps", "2", "--parallel", "2"]) == 0
    out = capsys.readouterr().out
    assert f"{pt.WITNESS_URL}: 4 of 4 stamps taken within 30 s" in out


@pytest.mark.parametrize("how, status", [("slow", 1), ("no profile", witness_probe.CANNOT_MEASURE)])
def test_a_slow_stamp_or_a_failed_profile_fails_and_names_the_witness(fake, monkeypatch, capsys, how, status):
    # a slow stamp is 1; a profile that could not be made did not measure the witness, 2 (#382)
    monkeypatch.setattr(fake, "outcome", staticmethod(lambda name: how if name == "probe-1" else "taken"))
    assert witness_probe.main(["--stamps", "2", "--parallel", "2"]) == status
    out = capsys.readouterr().out
    assert f"{pt.WITNESS_URL}: 2 of 4 stamps not taken within 30 s: probe-1" in out


def test_no_checkout_cannot_measure(monkeypatch, capsys):
    def missing():
        raise witness_probe._paths.SetupError("ARD_EVIDENCEBOOK is not set")
    monkeypatch.setattr(witness_probe._paths, "setup", missing)
    assert witness_probe.main([]) == witness_probe.CANNOT_MEASURE
    assert "could not measure the witness: ARD_EVIDENCEBOOK is not set" in capsys.readouterr().out
