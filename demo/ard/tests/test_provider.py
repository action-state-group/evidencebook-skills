# SPDX-License-Identifier: Apache-2.0
"""evidencebook-skills#340: the demo's Goose opens the windows with Claude Code ACP (through the demo's locked adapter)
or with a provider Goose runs itself (every Goose extension off), never with a provider that runs its own agent."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _ow():
    spec = importlib.util.spec_from_file_location("open_windows", Path(__file__).resolve().parents[1] / "goose" /
                                                  "open-windows.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _root(tmp_path, text):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.yaml").write_text(text)
    return tmp_path


OFF = "extensions:\n  developer:\n    enabled: false\n  scheduler:\n    enabled: true\n"


def test_no_provider_yet_opens_for_set_up(tmp_path):
    assert _ow().provider_problem(tmp_path, setup=True) is None  # step 7: the provider is picked in step 8


def test_claude_code_acp_needs_the_pinned_adapter(tmp_path, monkeypatch):
    ow = _ow()
    root = _root(tmp_path, "active_provider: claude-acp\n" + OFF.replace("false", "true"))
    monkeypatch.setattr(ow, "acp_prefix", lambda: tmp_path / "acp")
    assert "Claude Code adapter is not installed" in ow.provider_problem(root)
    (tmp_path / "acp" / "node_modules" / ".bin").mkdir(parents=True)
    (tmp_path / "acp" / "node_modules" / ".bin" / "claude-agent-acp").write_text("")
    assert ow.provider_problem(root) is None  # the locked adapter limits the tools, extensions or not


@pytest.mark.parametrize("provider", ["claude-code", "codex", "cursor-agent", "gemini-cli", "codex-acp", "amp-acp",
                                      "copilot-acp", "pi-acp"])
def test_a_provider_that_runs_its_own_agent_is_refused(tmp_path, provider):
    msg = _ow().provider_problem(_root(tmp_path, f"active_provider: {provider}\n" + OFF), setup=True)
    assert msg and "runs its own agent" in msg


@pytest.mark.parametrize("provider", ["gemini_oauth", "openai", "anthropic", "chatgpt_codex"])
def test_a_provider_goose_runs_itself_opens_with_every_extension_off(tmp_path, provider):
    ow = _ow()
    assert ow.provider_problem(_root(tmp_path, f"active_provider: {provider}\n" + OFF)) is None


def test_an_extension_left_on_stops_the_windows(tmp_path):
    ow = _ow()
    msg = ow.provider_problem(_root(tmp_path, "GOOSE_PROVIDER: openai\nextensions:\n  computercontroller:\n"
                                              "    enabled: true\n  scheduler:\n    enabled: true\n"))
    assert msg and "still on: computercontroller" in msg and "scheduler" not in msg
