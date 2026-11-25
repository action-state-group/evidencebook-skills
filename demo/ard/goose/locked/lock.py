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
import sys

LOCKED = ["--setting-sources", "", "--strict-mcp-config", "--tools", "ToolSearch"]
ENV = {"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1", "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1", "ENABLE_CLAUDEAI_MCP_SERVERS": "false"}


def ard_only(config: str) -> str:
    """The ``--mcp-config`` JSON with only the ``ard_*`` servers; anything else in it is dropped."""
    servers = json.loads(config).get("mcpServers") or {}
    return json.dumps({"mcpServers": {name: s for name, s in servers.items() if name.startswith("ard_")}})


def locked_args(argv: list[str]) -> list[str]:
    """The adapter's arguments with every ``--mcp-config`` reduced to the ard servers and the lock appended. A
    subcommand the adapter runs on its own (``auth status --json``) starts no session and passes through unchanged."""
    if argv and not argv[0].startswith("-"):
        return list(argv)
    out, i = [], 0
    while i < len(argv):
        a = argv[i]
        if a == "--mcp-config" and i + 1 < len(argv):
            out += [a, ard_only(argv[i + 1])]
            i += 2
            continue
        if a.startswith("--mcp-config="):
            out.append("--mcp-config=" + ard_only(a.split("=", 1)[1]))
        else:
            out.append(a)
        i += 1
    return out + LOCKED


def cli(prefix: str) -> str:
    """The Claude CLI the pinned adapter ships (@anthropic-ai/claude-agent-sdk-<platform>), under ``prefix``."""
    found = sorted(glob.glob(os.path.join(prefix, "node_modules", "@anthropic-ai", "claude-agent-sdk-*", "claude")))
    if not found:
        sys.exit(f"claude-locked: no Claude CLI under {prefix}/node_modules/@anthropic-ai: reinstall the demo's adapter")
    return found[0]


def main() -> None:
    prog = cli(os.environ["ARD_ACP_PREFIX"])
    os.execve(prog, [prog, *locked_args(sys.argv[1:])], {**os.environ, **ENV})


if __name__ == "__main__":
    main()
