# SPDX-License-Identifier: Apache-2.0
"""The demo's locked adapter (goose/locked, evidencebook-skills#276): each window's agent gets only ToolSearch and
its own ard_* MCP servers, none of the person's own Claude Code settings, CLAUDE.md or claude.ai connectors."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

LOCKED = Path(__file__).resolve().parents[1] / "goose" / "locked"
sys.path.insert(0, str(LOCKED))
import lock  # noqa: E402


def test_only_the_windows_own_ard_server_reaches_the_agent():
    config = {"mcpServers": {"ard_maya": {"command": "x"}, "developer": {"command": "sh"}, "summon": {}}}
    assert json.loads(lock.ard_only(json.dumps(config))) == {"mcpServers": {"ard_maya": {"command": "x"}}}
    assert json.loads(lock.ard_only("{}")) == {"mcpServers": {}}


def test_another_partys_extension_left_on_refuses_the_session():
    with pytest.raises(lock.Refused, match="more than one demo extension"):
        lock.ard_only(json.dumps({"mcpServers": {"ard_maya": {}, "ard_alder": {}}}))


def test_the_lock_comes_last_so_it_wins_over_the_adapters_tools_and_filters_both_mcp_config_forms():
    cfg = json.dumps({"mcpServers": {"ard_alder": {}, "developer": {}}})
    out = lock.locked_args(["--output-format", "stream-json", "--tools=default", "--mcp-config", cfg,
                            f"--mcp-config={cfg}"])
    assert out[-5:] == ["--setting-sources", "", "--strict-mcp-config", "--tools", "ToolSearch"]
    assert out[:2] == ["--output-format", "stream-json"] and "--tools=default" not in out
    assert json.loads(out[3]) == {"mcpServers": {"ard_alder": {}}}
    assert json.loads(out[4].split("=", 1)[1]) == {"mcpServers": {"ard_alder": {}}}


def test_every_tools_option_the_adapter_passed_is_removed_so_only_the_lock_names_tools():
    out = lock.locked_args(["--tools", "Bash", "Read", "--verbose", "--tools=default"])
    assert out == ["--verbose", *lock.LOCKED]
    assert [a for a in out if a.startswith("--tools")] == ["--tools"]


def test_only_the_adapters_own_auth_calls_pass_through_unlocked():
    for argv in (["auth", "status", "--json"], ["--settings", "{}", "auth", "status", "--json"], ["auth", "logout"]):
        assert lock.locked_args(argv) == argv
    for argv in (["do something"], ["mcp", "serve"], ["auth", "login"]):
        assert lock.locked_args(argv)[-5:] == lock.LOCKED, argv


def test_both_scripts_are_executable():
    for name in ("claude-agent-acp", "claude-locked"):
        assert (LOCKED / name).stat().st_mode & stat.S_IXUSR, name


def test_the_adapter_runs_the_pinned_cli_through_the_lock(tmp_path):
    """claude-agent-acp starts the pinned adapter with CLAUDE_CODE_EXECUTABLE set to claude-locked, which starts the
    pinned CLI with the lock and the environment that turns off CLAUDE.md, memory and connectors."""
    seen = tmp_path / "seen.json"
    record = (f"#!{sys.executable}\nimport json, os, sys\n"
              f"json.dump({{'argv': sys.argv[1:], 'env': dict(os.environ)}}, open({str(seen)!r}, 'w'))\n")
    adapter = tmp_path / "node_modules" / ".bin" / "claude-agent-acp"
    cli = tmp_path / "node_modules" / "@anthropic-ai" / "claude-agent-sdk-darwin-arm64" / "claude"
    for path, body in ((cli, record), (adapter, f"#!/bin/sh\nexec \"$CLAUDE_CODE_EXECUTABLE\" --tools=default "
                                                 "--mcp-config '{\"mcpServers\":{\"ard_maya\":{},\"developer\":{}}}'\n")):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
        path.chmod(0o755)
    env = {"PATH": os.environ["PATH"], "ARD_ACP_PREFIX": str(tmp_path), "ARD_PYTHON": sys.executable}
    run = subprocess.run([str(LOCKED / "claude-agent-acp")], env=env, capture_output=True, text=True, timeout=30,
                         stdin=subprocess.DEVNULL)
    assert run.returncode == 0, run.stderr
    got = json.loads(seen.read_text())
    assert got["argv"][-5:] == ["--setting-sources", "", "--strict-mcp-config", "--tools", "ToolSearch"]
    assert json.loads(got["argv"][1]) == {"mcpServers": {"ard_maya": {}}} and "--tools=default" not in got["argv"]
    assert got["env"]["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1" and got["env"]["ENABLE_CLAUDEAI_MCP_SERVERS"] == "false"
    assert got["env"]["CLAUDE_CODE_EXECUTABLE"] == str(LOCKED / "claude-locked")


def test_without_the_demos_environment_the_adapter_refuses_to_start():
    run = subprocess.run([str(LOCKED / "claude-agent-acp")], env={"PATH": os.environ["PATH"]}, capture_output=True,
                         text=True, timeout=30, stdin=subprocess.DEVNULL)
    assert run.returncode != 0 and "open-windows.py" in run.stderr
