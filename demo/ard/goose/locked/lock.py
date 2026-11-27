# SPDX-License-Identifier: Apache-2.0
"""Start the pinned Claude CLI for a demo window's agent with only ToolSearch and the window's own ard_* tools
(evidencebook-skills#276). claude-locked runs this with the arguments the adapter gives the CLI.

- Built-in tools: ``--tools ToolSearch`` last on the line, so it wins over the adapter's ``--tools=default``.
  ToolSearch only loads the session's own deferred MCP tools.
- MCP servers: the ``--mcp-config`` the adapter passes keeps only servers named ``ard_*`` (the window's recipe
  extension), and ``--strict-mcp-config`` drops every other source, so a Goose extension left on, a server in the
  person's own Claude Code settings or a claude.ai connector never reaches the agent.
- The person's own Claude Code: ``--setting-sources ""`` reads no settings file (permissions, hooks, plugins), and the
  environment turns off CLAUDE.md, auto memory and claude.ai connectors. The sign-in stays the keychain's.
"""
from __future__ import annotations

import glob
import json
import os
import shlex
import signal
import subprocess
import sys

LOCKED = ["--setting-sources", "", "--strict-mcp-config", "--tools", "ToolSearch"]
ENV = {"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1", "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1", "ENABLE_CLAUDEAI_MCP_SERVERS": "false"}


class Refused(SystemExit):
    pass


def ard_only(config: str) -> str:
    """The ``--mcp-config`` JSON with only the window's own ``ard_*`` server; anything else in it is dropped. A window
    has one: two (another party's extension left on in this window) refuse the session, so no agent gets another
    party's tools."""
    servers = json.loads(config).get("mcpServers") or {}
    ours = {name: s for name, s in servers.items() if name.startswith("ard_")}
    if len(ours) > 1:
        raise Refused(f"claude-locked: more than one demo extension is on in this window ({', '.join(sorted(ours))}): "
                      "turn off every extension but the window's own, then start the chat again")
    return json.dumps({"mcpServers": ours})


#: The adapter's own CLI calls that start no session (claude-agent-acp 0.108.0, dist/auth-status-reporter.js): passed
#: through unchanged, since the CLI rejects global options after a subcommand. Anything else is locked.
PASS_THROUGH = (["auth", "status"], ["auth", "logout"])


def _subcommand(argv: list[str]) -> bool:
    for i, a in enumerate(argv):
        if a == "auth":
            return argv[i:i + 2] in PASS_THROUGH
    return False


#: The windows whose answers are their tools' output alone (evidencebook-skills#446): the adjudicator's. Its agent restated
#: the ruling in its own words, giving reasons the ruling does not rest on and saying the adjudicator's lack of
#: independence did not matter, through two rounds of skill wording. In this window, so that the ruling line and the
#: not-independent line reach the person only as the tool printed them:
#: - every tool ends the agent's turn when it returns (a PostToolUse hook answering ``continue: false``; Claude Code
#:   hooks: "continue: false" stops Claude after the hook runs);
#: - a turn that called no tool is not ended: a Stop hook tells the agent to call the window's tool (:func:`stop_hook`);
#: - the agent's own text never reaches the person: :func:`quiet` empties it in what the CLI sends the adapter, so the
#:   agent keeps its own record of the chat, and the person reads only the tools' output.
QUIET = {"ard_adjudicator"}
#: What the Stop hook tells the agent, once per turn (Claude Code sets ``stop_hook_active`` on the turn it continued).
STOP_REASON = ("In this window every answer is a tool's output, and your own text is not shown to the person: call "
               "ard_ruling for the ruling, its reason or the adjudicator's independence, ard_case for the case, or "
               "ard_case_activity for the parties' entries.")


def quiet_settings(server: str) -> str:
    """The ``--settings`` JSON of a quiet window: a tool ends the turn, and a turn with no tool call is sent back once."""
    end = {"type": "command", "command": "echo '{\"continue\": false, \"stopReason\": \"\"}'"}
    stop = {"type": "command", "command": f"{shlex.quote(sys.executable)} -I {shlex.quote(os.path.abspath(__file__))} "
                                          "--stop-hook"}
    return json.dumps({"hooks": {"PostToolUse": [{"matcher": f"mcp__{server}__.*", "hooks": [end]}],
                                 "Stop": [{"hooks": [stop]}]}})


def stop_hook(event: dict) -> dict:
    """The Stop hook's answer: send a turn that called no tool back with :data:`STOP_REASON`, once; a turn the hook
    already sent back ends, so the agent never loops."""
    return {} if event.get("stop_hook_active") else {"decision": "block", "reason": STOP_REASON}


def quiet(line: bytes) -> bytes | None:
    """One line of the CLI's stream-json output (claude-agent-acp 0.108.0 reads it, dist/v1/acp-agent.js) with the
    agent's own text taken out: a streamed text delta is dropped, and the text of a whole message or of the turn's
    result is emptied in place, so every block keeps its index. Anything else passes unchanged."""
    try:
        msg = json.loads(line)
    except ValueError:
        return line
    if not isinstance(msg, dict):
        return line
    kind, changed = msg.get("type"), False
    if kind == "stream_event":
        ev = msg.get("event") or {}
        if ev.get("type") == "content_block_delta" and (ev.get("delta") or {}).get("type") == "text_delta":
            return None
        block = ev.get("content_block") or {}
        if ev.get("type") == "content_block_start" and block.get("type") == "text" and block.get("text"):
            block["text"], changed = "", True
    elif kind == "assistant":
        for block in (msg.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                block["text"], changed = "", True
    elif kind == "result" and msg.get("result"):
        msg["result"], changed = "", True
    return (json.dumps(msg) + "\n").encode() if changed else line


def locked_args(argv: list[str]) -> list[str]:
    """The adapter's arguments with every ``--mcp-config`` reduced to the window's ard server, every ``--tools`` the
    adapter passed removed (so the CLI never has to choose between two), and the lock appended. Only the adapter's own
    ``auth status`` and ``auth logout`` (which start no session) pass through unchanged."""
    if _subcommand(argv):
        return list(argv)
    out, i, ours = [], 0, set()
    while i < len(argv):
        a = argv[i]
        if a == "--mcp-config" and i + 1 < len(argv):
            kept = ard_only(argv[i + 1])
            ours |= set(json.loads(kept)["mcpServers"])
            out += [a, kept]
            i += 2
            continue
        if a == "--tools":  # variadic: drop its values up to the next option
            i += 1
            while i < len(argv) and not argv[i].startswith("-"):
                i += 1
            continue
        if a.startswith("--tools="):
            pass
        elif a.startswith("--mcp-config="):
            kept = ard_only(a.split("=", 1)[1])
            ours |= set(json.loads(kept)["mcpServers"])
            out.append("--mcp-config=" + kept)
        else:
            out.append(a)
        i += 1
    quiet_ = sorted(ours & QUIET)
    return out + LOCKED + (["--settings", quiet_settings(quiet_[0])] if quiet_ else [])


def is_quiet(args: list[str]) -> bool:
    """Whether the locked arguments start a quiet window's session: its settings come last, after the lock, so an
    adapter's own ``--settings`` earlier on the line never counts."""
    return len(args) > len(LOCKED) + 1 and args[-len(LOCKED) - 2:-2] == LOCKED and args[-2] == "--settings"


def cli(prefix: str) -> str:
    """The Claude CLI the pinned adapter ships (@anthropic-ai/claude-agent-sdk-<platform>), under ``prefix``."""
    found = sorted(glob.glob(os.path.join(prefix, "node_modules", "@anthropic-ai", "claude-agent-sdk-*", "claude")))
    if not found:
        sys.exit(f"claude-locked: no Claude CLI under {prefix}/node_modules/@anthropic-ai: reinstall the demo's adapter")
    return found[0]


def run_quiet(cmd: list[str], env: dict[str, str]) -> int:
    """Run the CLI with its output through :func:`quiet`; its input and errors go straight through. A signal the adapter
    sends this process goes on to the CLI."""
    child = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE)
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, lambda n, _f: child.send_signal(n))
    out = sys.stdout.buffer
    for line in iter(child.stdout.readline, b""):
        kept = quiet(line)
        if kept is not None:
            out.write(kept)
            out.flush()
    return child.wait()


def main() -> None:
    if sys.argv[1:] == ["--stop-hook"]:
        print(json.dumps(stop_hook(json.load(sys.stdin))))
        return
    prog = cli(os.environ["ARD_ACP_PREFIX"])
    args = locked_args(sys.argv[1:])
    env = {**os.environ, **ENV}
    if is_quiet(args):
        sys.exit(run_quiet([prog, *args], env))
    os.execve(prog, [prog, *args], env)


if __name__ == "__main__":
    main()
