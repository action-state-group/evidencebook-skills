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


def test_each_node_has_a_cadence_log_of_its_own_so_the_witness_keeps_one_chain_per_node(tmp_path):
    """The witness keeps one chain per log id (HTTP 409 on a second checkpoint whose predecessor is not its last for
    that id, 2026-11-23): nodes must not share the reference's ``goose/cadence``."""
    ids = []
    for name in ("a", "b"):
        with DemoNode.open(tmp_path / name, operator=f"ard-{name}") as node:
            node.note(gn.JOINED, {"operator": node.operator, "key_id": node.key_id})
            node.tick()
            ids.append(node.cadence._cfg.log_id)
            assert node.key_id and gn.CADENCE_LOG == "goose/cadence", "the module constant is put back"
    assert ids[0] != ids[1] and all(i.startswith("goose/cadence/") and len(i) == len("goose/cadence/") + 16 for i in ids)
    with DemoNode.open(tmp_path / "a", operator="ard-a") as again:  # reopened: the same id
        assert again.cadence._cfg.log_id == ids[0]


@pytest.mark.skipif(os.environ.get("ARD_WITNESS_LIVE") != "1", reason="reaches witness.agentactioncapsule.org: set ARD_WITNESS_LIVE=1")
def test_two_nodes_each_get_a_second_checkpoint_witnessed_when_their_ticks_interleave(tmp_path, monkeypatch):
    """The failure of 2026-11-23: with a shared log id the second node's tick 2 was refused (HTTP 409)."""
    from datetime import datetime, timedelta, timezone

    monkeypatch.setenv("ARD_WITNESS", "public")
    t0 = datetime.now(timezone.utc)
    nodes = [DemoNode.open(tmp_path / n, operator=f"ard-{n}") for n in ("a", "b")]
    try:
        for n in nodes:
            n.note(gn.JOINED, {"operator": n.operator, "key_id": n.key_id})
        for step in (0, 1):  # tick 1 of both, then a new record each and tick 2 of both
            for i, n in enumerate(nodes):
                if step:
                    n.note(gn.JOINED, {"operator": n.operator, "key_id": f"{n.key_id}-again"})
                r = n.tick(t0 + timedelta(minutes=2 * step))
                assert r.ticked and n.witness_error is None, (step, i, n.witness_error)
                assert n.witnessed_tick(r.tick.n) is not None
    finally:
        for n in nodes:
            n.close()
