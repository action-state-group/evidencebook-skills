# SPDX-License-Identifier: Apache-2.0
"""evidencebook-skills#340: the demo's Goose opens the windows with Claude Code ACP (through the demo's locked adapter)
or with a provider Goose runs itself (every Goose extension off), never with a provider that runs its own agent."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load():
    spec = importlib.util.spec_from_file_location("open_windows", Path(__file__).resolve().parents[1] / "goose" /
                                                  "open-windows.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_OW = _load()


def _root(tmp_path, text):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.yaml").write_text(text)
    return tmp_path


OFF = "extensions:\n  developer:\n    enabled: false\n  scheduler:\n    enabled: true\n"


@pytest.fixture(autouse=True)
def _no_system_layers(monkeypatch, tmp_path):
    """No /etc/goose/config.yaml and nothing in launchd's environment, unless a test sets them."""
    monkeypatch.setattr(_OW, "SYSTEM_CONFIG", tmp_path / "no-system.yaml")
    monkeypatch.setattr(_OW, "launchd_env", lambda name: "")


def _ow():
    return _OW


def test_no_provider_yet_is_refused_for_the_windows_but_opens_for_set_up(tmp_path, monkeypatch, capsys):
    ow = _ow()
    assert "no provider yet" in ow.provider_problem(tmp_path)
    monkeypatch.setattr(ow.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("no open in tests")))
    assert "could not start Goose Desktop" in ow.launch_goose(tmp_path, setup=True)  # it got past the check
    assert "note: the demo's Goose has no provider yet" in capsys.readouterr().out


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
    msg = _ow().provider_problem(_root(tmp_path, f"active_provider: {provider}\n" + OFF))
    assert msg and "runs its own agent" in msg and provider not in msg  # plain words, no provider id (ops c0813d7e)
    assert "Gemini or ChatGPT sign-in, an API key, or Claude Code (ACP)" in msg and "Settings, Models" in msg


@pytest.mark.parametrize("provider", ["gemini_oauth", "openai", "anthropic", "chatgpt_codex"])
def test_a_provider_goose_runs_itself_opens_with_every_extension_off(tmp_path, provider):
    ow = _ow()
    assert ow.provider_problem(_root(tmp_path, f"active_provider: {provider}\n" + OFF)) is None


def test_an_extension_left_on_stops_the_windows(tmp_path):
    ow = _ow()
    msg = ow.provider_problem(_root(tmp_path, "GOOSE_PROVIDER: openai\nextensions:\n  computercontroller:\n"
                                              "    enabled: true\n  scheduler:\n    enabled: true\n"))
    assert msg and "still on: computercontroller" in msg and "scheduler" not in msg


def test_the_message_uses_the_name_the_extensions_page_shows(tmp_path):
    msg = _ow().provider_problem(_root(tmp_path, "active_provider: openai\nextensions:\n  tom:\n    enabled: true\n"
                                                 "    display_name: Top Of Mind\n"))
    assert msg.endswith("still on: Top Of Mind")


def test_the_system_layer_counts_and_the_root_overrides_it(tmp_path, monkeypatch):
    ow = _ow()
    system = tmp_path / "etc.yaml"
    system.write_text("active_provider: gemini-cli\nextensions:\n  developer:\n    enabled: true\n")
    monkeypatch.setattr(ow, "SYSTEM_CONFIG", system)
    root = tmp_path / "r"
    root.mkdir()
    assert "runs its own agent" in ow.provider_problem(root)  # inherited from the system file
    (root / "config").mkdir()
    (root / "config" / "config.yaml").write_text("active_provider: openai\n")
    assert "still on: developer" in ow.provider_problem(root)  # the system file's extension still counts


def test_launchd_layers_are_refused_or_read(tmp_path, monkeypatch):
    ow = _ow()
    monkeypatch.setattr(ow, "launchd_env", lambda name: "/x.yaml" if name == "GOOSE_ADDITIONAL_CONFIG_FILES" else "")
    assert "more config files" in ow.provider_problem(_root(tmp_path, "active_provider: openai\n"))
    monkeypatch.setattr(ow, "launchd_env", lambda name: "cursor-agent" if name == "GOOSE_PROVIDER" else "")
    assert "runs its own agent" in ow.provider_problem(tmp_path)


def test_a_config_that_is_not_yaml_is_named_not_a_traceback(tmp_path):
    msg = _ow().provider_problem(_root(tmp_path, "- a list\n- not a mapping\n"))
    assert "is not a Goose config" in msg


def test_goose_gets_exactly_the_provider_that_was_checked(tmp_path, monkeypatch):
    """Codex's and Claude's round 2: launchd's provider wins in the check, so it is the one Goose gets."""
    ow = _ow()
    root = _root(tmp_path, "active_provider: cursor-agent\n" + OFF)
    monkeypatch.setattr(ow, "launchd_env", lambda name: "openai" if name == "GOOSE_PROVIDER" else "")
    ran = []
    monkeypatch.setattr(ow.subprocess, "run", lambda args, **k: ran.append(args) or (_ for _ in ()).throw(OSError("x")))
    ow.launch_goose(root)
    assert "GOOSE_PROVIDER=openai" in ran[0] and not any("cursor-agent" in a for a in ran[0])


def test_set_up_pins_no_provider(tmp_path, monkeypatch):
    ow = _ow()
    root = _root(tmp_path, "active_provider: openai\n" + OFF)
    ran = []
    monkeypatch.setattr(ow.subprocess, "run", lambda args, **k: ran.append(args) or (_ for _ in ()).throw(OSError("x")))
    ow.launch_goose(root, setup=True)
    assert not any(a.startswith("GOOSE_PROVIDER=") for a in ran[0])  # a provider switched in Settings takes effect


@pytest.mark.parametrize("own,refused", [("  developer:\n    display_name: Developer\n", True),
                                         ("  developer:\n    enabled: false\n", False)])
def test_extensions_merge_field_by_field_as_goose_does(tmp_path, monkeypatch, own, refused):
    ow = _ow()
    system = tmp_path / "etc.yaml"
    system.write_text("extensions:\n  developer:\n    enabled: true\n")
    monkeypatch.setattr(ow, "SYSTEM_CONFIG", system)
    root = tmp_path / "r"
    (root / "config").mkdir(parents=True)
    (root / "config" / "config.yaml").write_text("active_provider: openai\nextensions:\n" + own)
    assert bool(ow.provider_problem(root)) is refused


def test_an_extension_that_is_not_a_mapping_is_named_not_a_traceback(tmp_path):
    msg = _ow().provider_problem(_root(tmp_path, "active_provider: openai\nextensions:\n  developer: on\n"))
    assert "extensions entry that is not a mapping" in msg
