# SPDX-License-Identifier: Apache-2.0
"""The countersign upgrade (evidencebook-skills#383): who the demo's countersigner admits and how its directory names
it, the receipt's countersign line from capsulectl's report (Sherlock2's words, Buzz f903059c), and stopping only the
countersigner a folder started. The upgrade itself, with the real capsule-anchor and capsulectl, is in
tests/test_e2e.py."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import countersigner as cs
import receipt
import reset

# capsulectl's report of a deal countersigned through every record (`deal report --read-only` -> countersign, run
# 2026-11-26 against capsule-anchor with capsulectl-deal at evidencebook 63f2d61; directory path shortened)
COUNTERSIGNED = {"rung": "countersigned", "signer": "the demo's countersigner", "recomputed_at": "2026-11-26T18:46:50.731966Z",
                 "through_step": 4, "steps": 4,
                 "covers": "The countersignature covers your deal book through record 4 of 4, as the records' digests: not this report, and not the other side's records.",
                 "directory": "/home/countersigner/directory.json",
                 "entries": [{"state": "resolved", "signer": "the demo's countersigner", "key_id": "c9c1" * 16,
                              "recomputed_at": "2026-11-26T18:46:50.731966Z", "receipt": "verified", "through_step": 4,
                              "steps": 4, "bundle_digest": "134f" * 16}]}


def _party(tmp_path: Path, name: str, log_id: str, key: str):
    d = tmp_path / name
    prof = d / ".config" / "capsule" / "profiles"
    prof.mkdir(parents=True)
    (prof / f"ard-{name}.yaml").write_text(f"name: ard-{name}\ntype: sqlite\nlog_id: {log_id}\nnamespace: deal\n")
    return SimpleNamespace(name=name, dir=d, profile=f"ard-{name}", key_id=key)


def test_the_allowlist_pins_each_partys_log_id_to_its_signing_key(tmp_path):
    maya = _party(tmp_path, "maya", "deal-cadence/aaaa", "11" * 32)
    alder = _party(tmp_path, "alder", "deal-cadence/bbbb", "22" * 32)
    assert cs.issuers([maya, alder]) == [{"ledger_id": "deal-cadence/aaaa", "pubkey_hex": "11" * 32},
                                         {"ledger_id": "deal-cadence/bbbb", "pubkey_hex": "22" * 32}]


def test_a_profile_without_a_log_id_is_refused(tmp_path):
    p = _party(tmp_path, "maya", "x", "11" * 32)
    (p.dir / ".config" / "capsule" / "profiles" / "ard-maya.yaml").write_text("name: ard-maya\n")
    with pytest.raises(cs.CountersignerError, match="names no log id"):
        cs.issuers([p])


def test_the_directory_names_only_the_demos_countersigner():
    assert cs.directory("ab" * 32) == {"countersigners": [{"name": "the demo's countersigner", "key_ids": ["ab" * 32]}]}


def test_the_folder_is_inside_the_demo_home_so_reset_forgets_it(tmp_path):
    assert cs.default_dir(tmp_path) == tmp_path / "countersigner"


def test_countersigned_in_sherlock2s_words():
    line = receipt.countersign_line(COUNTERSIGNED, "Maya", "Alder Print Co.")
    assert line.startswith("Countersigned by the demo's countersigner at 2026-11-26 ")
    assert line.endswith(", as capsulectl reports. It signed Maya's records of this deal, 1 to 4 of 4, as digests only, "
                         "and does not cover Alder Print Co.'s records. In this demo the operator runs it and every party, "
                         "so it is not independent of them.")
    assert "not countersigned yet" not in line


def test_countersigned_in_part_names_the_records_after_it():
    part = {**COUNTERSIGNED, "rung": "countersigned_in_part", "through_step": 4, "steps": 6}
    line = receipt.countersign_line(part, "Maya", "Alder Print Co.")
    assert "1 to 4 of 6" in line and line.endswith(" Records 5 to 6 are not countersigned yet.")


def test_before_the_step():
    line = receipt.countersign_line({"finding": "not_countersigned", "directory": "/d"}, "Maya", "Alder Print Co.")
    assert line == "Not countersigned yet: no countersigner has signed Maya's records of this deal."


@pytest.mark.parametrize("finding", ["unchecked", "unverified", "unresolved_signer", "self_countersigned"])
def test_a_countersignature_that_does_not_count_is_never_a_rung_nor_nothing(finding):
    line = receipt.countersign_line({"finding": finding}, "Maya", "Alder Print Co.")
    assert line.startswith("Not countersigned: capsulectl holds a countersignature") and finding.replace("_", " ") in line
    assert "Countersigned by" not in line


def test_no_report_yet():
    assert "not ready yet" in receipt.countersign_line(None, "Maya", "Alder Print Co.")


@pytest.fixture
def decoy(tmp_path):
    """A process that is not a countersigner, and one that looks like another folder's countersigner."""
    procs = []

    def spawn(*argv: str) -> int:
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", *argv])
        procs.append(p)
        return p.pid
    yield spawn
    for p in procs:
        p.kill()
        p.wait()


def test_stop_never_signals_a_process_that_is_not_this_folders_countersigner(tmp_path, decoy):
    d = tmp_path / "countersigner"
    d.mkdir()
    for argv in ((), (cs.APP, "--ssl-certfile", str(tmp_path / "other" / "tls.crt"))):
        pid = decoy(*argv)
        (d / cs.STATE).write_text(f'{{"pid": {pid}, "url": "https://localhost:1", "key": "k", "issuers": []}}')
        assert cs.running(d) is None
        assert cs.stop(d) is False
        assert not (d / cs.STATE).exists()
        os.kill(pid, 0)  # still running


def test_stop_ends_this_folders_countersigner_and_is_safe_to_repeat(tmp_path, decoy):
    d = tmp_path / "countersigner"
    d.mkdir()
    pid = decoy(cs.APP, "--ssl-certfile", str(d / "tls.crt"))
    (d / cs.STATE).write_text(f'{{"pid": {pid}, "url": "https://localhost:1", "key": "k", "issuers": []}}')
    assert cs.running(d)["pid"] == pid
    assert cs.is_ours(d, pid)
    assert cs.stop(d) is True
    assert not cs.is_ours(d, pid)
    assert cs.stop(d) is False


def test_env_says_how_to_start_it_when_none_runs(tmp_path):
    with pytest.raises(cs.CountersignerError, match="countersigner.py up"):
        cs.env(tmp_path / "countersigner")


def test_env_gives_the_countersign_surface_and_the_folders_files(tmp_path, decoy):
    d = tmp_path / "countersigner"
    d.mkdir()
    pid = decoy(cs.APP, "--ssl-certfile", str(d / "tls.crt"))
    (d / cs.STATE).write_text(f'{{"pid": {pid}, "url": "https://localhost:5", "key": "kk", "issuers": []}}')
    assert cs.env(d) == {"ARD_COUNTERSIGN_URL": "https://localhost:5/countersign/register", "ARD_COUNTERSIGN_KEY": "kk",
                         "ARD_COUNTERSIGN_DIRECTORY": str(d / "directory.json"), "SSL_CERT_FILE": str(d / "ca-bundle.pem")}


def test_reset_counts_the_homes_countersigner_as_the_demos_own(tmp_path):
    """The service holds its log under the home; reset stops it as the demo's own, never refuses on it."""
    import time

    d = cs.default_dir(tmp_path / "home")
    d.mkdir(parents=True)
    log = d / "countersigner.log"
    log.write_text("")
    holder = subprocess.Popen([sys.executable, "-c", f"import time; f = open({str(log)!r}); time.sleep(60)", cs.APP,
                               "--ssl-certfile", str(d / "tls.crt")])
    try:
        time.sleep(1)
        ours, others, _ = reset.holders(tmp_path / "home")
        assert holder.pid in ours and holder.pid not in others
    finally:
        holder.kill()
        holder.wait()


@pytest.fixture
def fake_start(tmp_path, monkeypatch):
    """start() with every slow part stubbed; the 'service' is a sleeping process whose argv looks like this folder's
    countersigner, so stop() and is_ours() treat it as the real one."""
    fake = tmp_path / "fakepy"
    fake.write_text(f"#!/bin/sh\nexec {sys.executable} -c 'import time; time.sleep(60)' \"$@\"\n")
    fake.chmod(0o755)
    started = []
    real = subprocess.Popen

    def popen(*a, **k):
        p = real(*a, **k)
        started.append(p)
        return p
    monkeypatch.setattr(cs, "_python", lambda d: fake)
    monkeypatch.setattr(cs, "_keys", lambda d: ("seed", "ab" * 32))
    monkeypatch.setattr(cs, "_certificate", lambda d: None)
    monkeypatch.setattr(cs, "_ca_bundle", lambda d, ca: None)
    monkeypatch.setattr(cs, "_wait_healthy", lambda d, proc, url, key: None)
    monkeypatch.setattr(cs.subprocess, "Popen", popen)
    yield started
    for p in started:
        p.kill()
        p.wait()


def test_a_start_that_fails_after_the_service_is_up_leaves_nothing_running(tmp_path, monkeypatch, fake_start):
    """Codex, round 1: naming the directory in a profile can fail after the service answered; start then stops it and
    keeps no state, and the next start works."""
    d = tmp_path / "countersigner"
    d.mkdir()
    maya = _party(tmp_path, "maya", "deal-cadence/aaaa", "11" * 32)

    def refuse(d, parties):
        raise RuntimeError("profile update refused")
    monkeypatch.setattr(cs, "_name_directory", refuse)
    with pytest.raises(RuntimeError, match="profile update refused"):
        cs.start(d, [maya], say=lambda *_: None)
    first = fake_start[0]
    assert first.poll() is not None and not (d / cs.STATE).exists() and cs.running(d) is None
    monkeypatch.setattr(cs, "_name_directory", lambda d, parties: None)
    assert cs.start(d, [maya], say=lambda *_: None)["ARD_COUNTERSIGN_KEY"] == "ab" * 32
    assert cs.running(d)["pid"] == fake_start[1].pid
    assert cs.stop(d) is True
