# SPDX-License-Identifier: Apache-2.0
"""evidencebook-skills#342 (carried by #340): the RUNBOOK's header is the one place for the pins, so the set-up script
(setup.sh, #364), the ard-demo CI job and the code's own pins must agree with it."""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import envhelp

HERE = Path(__file__).resolve().parents[1]
RUNBOOK = (HERE / "RUNBOOK.md").read_text()
HEADER = next(line for line in RUNBOOK.splitlines() if line.startswith("This guide runs evidencebook-skills main."))
SETUP = (HERE / "setup.sh").read_text()
CI = (HERE.parents[1] / ".github" / "workflows" / "tests.yml").read_text()


def _pin(name: str) -> str:
    """A pin setup.sh sets at its top (``NAME=value``)."""
    m = re.search(rf"^{name}=(\S+)$", SETUP, re.M)
    assert m, f"setup.sh sets no {name}"
    return m.group(1)


def _commit(repo: str) -> str:
    """The 40-hex commit setup.sh pins for ``repo``: the one it checks out, or for capsule-cli the one the released
    capsulectl names."""
    full = _pin(repo.upper().replace("-", "_") + "_PIN")
    assert re.fullmatch(r"[0-9a-f]{40}", full), f"setup.sh's {repo} pin is not a full commit"
    return full


def test_every_set_up_checkout_is_the_header_pin():
    # capsule-cli is not checked out (#435): its pin is the commit the released capsulectl names in --version
    for repo in ("evidencebook", "capsule-cli", "capsule-engine"):
        full = _commit(repo)
        assert f"{repo} {full[:7]}" in HEADER, f"the header names another {repo} than setup.sh checks out ({full[:7]})"


def test_capsulectl_is_the_header_release():
    """#435: capsulectl and its plugins are installed from the release the header names; setup.sh checks each binary's
    --version against the commits the header names (capsule-cli's for capsulectl, evidencebook's for the plugins)."""
    version = _pin("CAPSULECTL_VERSION")
    assert re.fullmatch(r"v\d+\.\d+\.\d+", version), "the set-up installs a release, never a commit build"
    assert f"capsulectl {version}, installed from its two releases, capsule-cli {version} (capsule-cli " \
        f"{_commit('capsule-cli')[:7]}) and evidencebook capsulectl/{version}" in HEADER
    assert "CORE_V=$CAPSULECTL_VERSION" in SETUP


def test_ci_runs_the_header_evidencebook():
    m = re.search(r"EVIDENCEBOOK_REF: ([0-9a-f]{40})", CI.split("ard-demo:", 1)[1])
    assert m and m.group(1) == _commit("evidencebook")


def test_the_code_pins_are_in_the_header():
    spec = importlib.util.spec_from_file_location("ow", HERE / "goose" / "open-windows.py")
    ow = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ow)
    assert f"adapter {ow.ACP_PIN}" in HEADER and _pin("ACP_VERSION") == ow.ACP_PIN
    assert f"ln-pay-local {envhelp.LN_PAY_LOCAL_COMMIT[:7]}" in HEADER
    assert f"Goose Desktop {_pin('GOOSE_VERSION')}" in HEADER


def test_the_testbed_starts_the_witness_the_local_check_starts():
    # one witness release for the testbed's local witness and the local check's and CI's local leg (#371, #378): moved
    # together; scripts/check.sh reads them from tests.yml's ard-demo job
    import testbed

    pins = dict(re.findall(r"(?m)^      (LOCAL_WITNESS(?:_START)?_REF): ([0-9a-f]{40})", CI.split("ard-demo:", 1)[1]))
    assert pins == {"LOCAL_WITNESS_REF": testbed.CAPSULE_ANCHOR_PIN, "LOCAL_WITNESS_START_REF": testbed.LOCAL_WITNESS_START_PIN}


def test_ci_installs_the_header_capsulectl():
    """#383: the countersign upgrade's `countersign request` is capsulectl's own, the RUNBOOK's release (#435); the
    tau2-live job installs the same one."""
    for job in ("ard-demo:", "tau2-live:"):
        m = re.search(r"CAPSULECTL_VERSION: (\S+)", CI.split(f"\n  {job}", 1)[1])
        assert m and m.group(1) == _pin("CAPSULECTL_VERSION"), job
    tau2 = (HERE.parent / "tau2-live" / "README.md").read_text()
    assert f"V={_pin('CAPSULECTL_VERSION')};" in tau2, "tau2-live's README installs another capsulectl release"


def test_the_countersigner_is_the_header_capsule_anchor():
    import countersigner

    assert f"capsule-anchor {countersigner.ANCHOR_REF[:7]} " in HEADER
