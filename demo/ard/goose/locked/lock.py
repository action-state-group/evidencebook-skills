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


def locked_args(argv: list[str]) -> list[str]:
    """The adapter's arguments with every ``--mcp-config`` reduced to the window's ard server, every ``--tools`` the
    adapter passed removed (so the CLI never has to choose between two), and the lock appended. Only the adapter's own
    ``auth status`` and ``auth logout`` (which start no session) pass through unchanged."""
    if _subcommand(argv):
        return list(argv)
    out, i = [], 0
    while i < len(argv):
        a = argv[i]
        if a == "--mcp-config" and i + 1 < len(argv):
            out += [a, ard_only(argv[i + 1])]
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
