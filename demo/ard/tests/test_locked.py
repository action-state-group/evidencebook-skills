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


# -- the adjudicator's window: its answers are its tools' output alone (#446) ------------------------------------------

def adjudicator_args() -> list[str]:
    return lock.locked_args(["--mcp-config", json.dumps({"mcpServers": {"ard_adjudicator": {}, "developer": {}}})])


def test_only_the_adjudicators_window_is_quiet():
    args = adjudicator_args()
    assert args[-7:-2] == lock.LOCKED and args[-2] == "--settings" and lock.is_quiet(args)
    hooks = json.loads(args[-1])["hooks"]
    assert hooks["PostToolUse"][0]["matcher"] == "mcp__ard_adjudicator__.*"
    for role in ("maya", "alder", "kestrel"):
        args = lock.locked_args(["--mcp-config", json.dumps({"mcpServers": {f"ard_{role}": {}}})])
        assert args[-5:] == lock.LOCKED and not lock.is_quiet(args), role


def _hook(cmd: str, event: dict) -> dict:
    run = subprocess.run(cmd, shell=True, input=json.dumps(event), capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def test_each_tool_ends_the_turn_and_a_turn_with_no_tool_is_sent_back_once():
    hooks = json.loads(adjudicator_args()[-1])["hooks"]
    assert _hook(hooks["PostToolUse"][0]["hooks"][0]["command"], {}) == {"continue": False, "stopReason": ""}
    stop = hooks["Stop"][0]["hooks"][0]["command"]
    assert _hook(stop, {"stop_hook_active": False}) == {"decision": "block", "reason": lock.STOP_REASON}
    assert _hook(stop, {"stop_hook_active": True}) == {}  # never a loop
    assert "ard_ruling" in lock.STOP_REASON and "independence" in lock.STOP_REASON


def _line(msg: dict) -> bytes:
    return (json.dumps(msg) + "\n").encode()


def test_the_agents_own_text_never_reaches_the_adapter_and_everything_else_does():
    delta = {"type": "stream_event", "event": {"type": "content_block_delta", "index": 0,
                                               "delta": {"type": "text_delta", "text": "Both sides agree"}}}
    assert lock.quiet(_line(delta)) is None
    start = {"type": "stream_event", "event": {"type": "content_block_start", "index": 0,
                                               "content_block": {"type": "text", "text": "It doesn't matter"}}}
    assert json.loads(lock.quiet(_line(start)))["event"]["content_block"] == {"type": "text", "text": ""}
    whole = {"type": "assistant", "message": {"content": [
        {"type": "text", "text": "That doesn't change the outcome"},
        {"type": "tool_use", "id": "t1", "name": "mcp__ard_adjudicator__ard_ruling", "input": {}}]}}
    content = json.loads(lock.quiet(_line(whole)))["message"]["content"]
    assert content[0] == {"type": "text", "text": ""} and content[1] == whole["message"]["content"][1]  # indexes kept
    result = {"type": "result", "subtype": "success", "result": "Both sides agree"}
    assert json.loads(lock.quiet(_line(result))) == {**result, "result": ""}
    for same in ({"type": "stream_event", "event": {"type": "content_block_delta", "index": 1,
                                                    "delta": {"type": "input_json_delta", "partial_json": "{}"}}},
                 {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1",
                                                           "content": "This adjudicator is run by the operator"}]}},
                 {"type": "system", "subtype": "init"}):
        assert lock.quiet(_line(same)) == _line(same)
    assert lock.quiet(b"not json\n") == b"not json\n"


def test_the_adjudicators_cli_runs_through_the_filter(tmp_path):
    """claude-locked runs the adjudicator's CLI with its output filtered: the tool's result passes, the agent's text
    does not, and the CLI's exit status is the lock's."""
    lines = [{"type": "assistant", "message": {"content": [{"type": "text", "text": "SECRET-REASON"}]}},
             {"type": "stream_event", "event": {"type": "content_block_delta", "index": 0,
                                                "delta": {"type": "text_delta", "text": "SECRET-REASON"}}},
             {"type": "user", "message": {"content": [{"type": "tool_result", "content": "Ruled without a person"}]}}]
    cli = tmp_path / "node_modules" / "@anthropic-ai" / "claude-agent-sdk-darwin-arm64" / "claude"
    cli.parent.mkdir(parents=True)
    cli.write_text(f"#!{sys.executable}\nimport json, sys\n"
                   + "".join(f"print(json.dumps({m!r}), flush=True)\n" for m in lines) + "sys.exit(3)\n")
    cli.chmod(0o755)
    env = {"PATH": os.environ["PATH"], "ARD_ACP_PREFIX": str(tmp_path), "ARD_PYTHON": sys.executable}
    cfg = json.dumps({"mcpServers": {"ard_adjudicator": {}}})
    run = subprocess.run([str(LOCKED / "claude-locked"), "--mcp-config", cfg], env=env, capture_output=True, text=True,
                         timeout=30, stdin=subprocess.DEVNULL)
    assert run.returncode == 3, run.stderr
    assert "SECRET-REASON" not in run.stdout and "Ruled without a person" in run.stdout
    assert len(run.stdout.splitlines()) == 2


def test_an_adapters_own_settings_do_not_make_a_window_quiet():
    args = lock.locked_args(["--settings", "{}", "--mcp-config", json.dumps({"mcpServers": {"ard_maya": {}}})])
    assert not lock.is_quiet(args)


def test_the_agents_thinking_never_reaches_the_adapter_either():
    """Codex's round 1: the adapter sends thinking as thought chunks, which Goose can show."""
    delta = {"type": "stream_event", "event": {"type": "content_block_delta", "index": 0,
                                               "delta": {"type": "thinking_delta", "thinking": "Maya agrees, so"}}}
    assert lock.quiet(_line(delta)) is None
    start = {"type": "stream_event", "event": {"type": "content_block_start", "index": 0,
                                               "content_block": {"type": "thinking", "thinking": "it hardly matters"}}}
    assert json.loads(lock.quiet(_line(start)))["event"]["content_block"]["thinking"] == ""
    whole = {"type": "assistant", "message": {"content": [
        {"type": "thinking", "thinking": "it hardly matters", "signature": "sig"}]}}
    assert json.loads(lock.quiet(_line(whole)))["message"]["content"] == [
        {"type": "thinking", "thinking": "", "signature": "sig"}]
    sig = {"type": "stream_event", "event": {"type": "content_block_delta", "index": 0,
                                             "delta": {"type": "signature_delta", "signature": "sig"}}}
    assert lock.quiet(_line(sig)) == _line(sig)


def test_when_the_adapter_stops_reading_the_cli_is_ended(tmp_path):
    """Codex's round 1: a closed output pipe ends the CLI too, so no session runs on with no one to answer."""
    pid = tmp_path / "pid"
    cli = tmp_path / "node_modules" / "@anthropic-ai" / "claude-agent-sdk-darwin-arm64" / "claude"
    cli.parent.mkdir(parents=True)
    cli.write_text(f"#!{sys.executable}\nimport json, os, signal, sys, time\n"
                   f"open({str(pid)!r}, 'w').write(str(os.getpid()))\n"
                   "signal.signal(signal.SIGPIPE, signal.SIG_IGN)\n"
                   "while True:\n"
                   "    try:\n"
                   "        print(json.dumps({'type': 'system', 'subtype': 'tick'}), flush=True)\n"
                   "    except BrokenPipeError:\n"
                   "        pass\n"
                   "    time.sleep(0.05)\n")
    cli.chmod(0o755)
    env = {"PATH": os.environ["PATH"], "ARD_ACP_PREFIX": str(tmp_path), "ARD_PYTHON": sys.executable}
    cfg = json.dumps({"mcpServers": {"ard_adjudicator": {}}})
    proc = subprocess.Popen([str(LOCKED / "claude-locked"), "--mcp-config", cfg], env=env, stdout=subprocess.PIPE,
                            stdin=subprocess.DEVNULL)
    assert proc.stdout.readline()
    proc.stdout.close()
    assert proc.wait(timeout=30) != 0
    child = int(pid.read_text())
    import time
    for _ in range(100):
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        os.kill(child, 9)
        pytest.fail("the CLI was left running")
