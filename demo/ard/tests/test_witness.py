# SPDX-License-Identifier: Apache-2.0
"""The hosted witness on the demo's checkpoints (demo_node.py): off in tests, a witness that cannot be reached leaves
the card unwitnessed and the run going, and (opt in, needs the network) the real witness's receipt verifies."""
from __future__ import annotations

import os

import pytest

import demo_node
import goose_node as gn
from demo_node import DemoNode


def test_the_witness_is_off_in_tests_and_on_by_default_outside_them(monkeypatch):
    assert demo_node.witnessing() is False  # conftest.py sets ARD_WITNESS=off
    monkeypatch.delenv("ARD_WITNESS")
    assert demo_node.witnessing() is True
    monkeypatch.setenv("ARD_WITNESS", "public")
    assert demo_node.witnessing() is True


def test_the_directory_names_the_hosted_witness_and_its_published_key():
    row = demo_node.WITNESS_DIRECTORY["witnesses"][0]
    assert row["endpoint"] == "https://witness.agentactioncapsule.org" and row["name"] == demo_node.WITNESS_NAME
    # the key witness.agentactioncapsule.org/.well-known/did.json publishes (Ed25519 x, base64url ObtlTJ3A...), as hex
    assert row["key_ids"] == ["39bb654c9dc0afe1c0edef0deffaa69099b8518836c9ba26e0491535840f96b5"]


class Down:
    def __init__(self, endpoint):
        pass

    def submit(self, statement):
        raise OSError("no route to the witness")


def test_a_witness_that_cannot_be_reached_leaves_the_tick_unwitnessed_and_the_run_going(tmp_path, monkeypatch):
    monkeypatch.setenv("ARD_WITNESS", "public")
    with DemoNode.open(tmp_path / "n", operator="ard-n", witness_client=Down) as node:
        node.note(gn.JOINED, {"operator": node.operator, "key_id": node.key_id})
        result = node.tick()
        assert result.ticked and "no route to the witness" in node.witness_error
        assert node.witnessed_tick(result.tick.n) is None


@pytest.mark.skipif(os.environ.get("ARD_WITNESS_LIVE") != "1", reason="reaches witness.agentactioncapsule.org: set ARD_WITNESS_LIVE=1")
def test_the_hosted_witness_receipt_verifies_under_its_published_key(tmp_path, monkeypatch):
    monkeypatch.setenv("ARD_WITNESS", "public")
    with DemoNode.open(tmp_path / "n", operator="ard-n") as node:
        node.note(gn.JOINED, {"operator": node.operator, "key_id": node.key_id})
        result = node.tick()
        assert node.witness_error is None and node.witnessed_tick(result.tick.n) is not None
