# SPDX-License-Identifier: Apache-2.0
"""The environment the demo's commands need, for ``demo.py`` and ``goose/open-windows.py``: the help text's
"Environment" section and, before a command starts, one message naming every missing variable with the export line
that sets it, instead of a traceback from deep inside the demo. It imports nothing of the demo's own."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import _paths


@dataclass(frozen=True)
class Var:
    name: str
    what: str
    example: str
    needed_by: tuple[str, ...]  # "seed", "run", "windows"; with "local" only on the local rail; () when optional
    check: str = ""  # "checkout", "program" or "dir": what a set value must be


VARS = (
    Var("ARD_EVIDENCEBOOK", "the evidencebook checkout at the pinned commit (the Goose reference, the x-deal-v0 checker)",
        "/path/to/evidencebook", ("seed", "run", "windows"), "checkout"),
    Var("CAPSULE_ENGINE", "the capsule-engine binary (go build ./cmd/capsule-engine in capsule-engine/go)",
        "/path/to/capsule-engine", ("run", "windows"), "program"),
    Var("CAPSULECTL_DEAL", "the capsulectl-deal binary: it verifies each receipt page's copy",
        "/path/to/capsulectl-deal", ("windows",), "program"),
    Var("ARD_WALLET_BUYER", "the buyer's wallet directory (ln-pay-local init --wallet <dir>; fund it)",
        "/path/to/buyer-wallet", ("local",), "dir"),
    Var("ARD_WALLET_SELLER", "the sellers' wallet directory (ln-pay-local init --wallet <dir>)",
        "/path/to/seller-wallet", ("local",), "dir"),
    Var("ARD_PAY_LOCAL", "the ln-pay-local binary, if it is not on the PATH", "/path/to/ln-pay-local", (), "program"),
    Var("ARD_HOME", "the demo home (default ~/.config/ard-commerce-demo)", "~/.config/ard-commerce-demo", ()),
)


#: What the help of a script that does not run a command calls that command.
ELSEWHERE = {"seed": "demo.py seed", "run": "demo.py run", "windows": "goose/open-windows.py (the Goose windows)"}


def _needs(var: Var, command: str, rail: str) -> bool:
    if "local" in var.needed_by:
        return rail == "local" and command in ("run", "windows")
    return command in var.needed_by


def _bad(var: Var, value: str) -> str | None:
    """Why a set value cannot work, or None. The value is read as the demo reads it, with no ``~`` expansion (a quoted
    ``~`` reaches the demo as it is)."""
    path = Path(value)
    if var.check == "checkout" and not _paths.is_checkout(path):
        return f"{var.name}={value} is not an evidencebook checkout (no python/examples/goose/goose_node.py)"
    if var.check == "program" and not (path.is_file() and os.access(path, os.X_OK)):
        return f"{var.name}={value} is not an executable file"
    if var.check == "dir" and not path.is_dir():
        return f"{var.name}={value} is not a directory"
    return None


def problems(command: str | None, rail: str = "fake") -> tuple[list[Var], list[str]]:
    """``(missing, wrong)`` for ``command`` (``seed``, ``run``, ``reset`` or ``windows``) on ``rail``."""
    missing, wrong = [], []
    for var in VARS:
        value = os.environ.get(var.name)
        if command is None:
            continue
        if var.name == "ARD_PAY_LOCAL":  # optional, but a set one must be a program on the local rail
            if rail == "local" and command in ("run", "windows") and value and (why := _bad(var, value)):
                wrong.append(why)
            continue
        if not _needs(var, command, rail):
            continue
        if not value:
            missing.append(var)
        elif why := _bad(var, value):
            wrong.append(why)
    if rail == "local" and command in ("run", "windows") and not os.environ.get("ARD_PAY_LOCAL") \
            and not shutil.which("ln-pay-local"):
        wrong.append("ln-pay-local is not on the PATH: cargo install --locked --git "
                     "https://github.com/action-state-group/ln-pay-local, or set ARD_PAY_LOCAL to the binary")
    return missing, wrong


def message(command: str, rail: str = "fake", as_command: str | None = None) -> str | None:
    """One message for what ``command`` lacks (checked as ``as_command`` when given), with the export line to copy;
    None when nothing is missing."""
    missing, wrong = problems(as_command or command, rail)
    if not missing and not wrong:
        return None
    lines = []
    if missing:
        lines.append(f"{command} needs these environment variables, which are not set: "
                     + ", ".join(v.name for v in missing) + ".")
        lines += [f"  {v.name}: {v.what}" for v in missing]
        lines.append("Set them (put your own paths in), then run again:")
        lines.append("  export " + " ".join(f"{v.name}={v.example}" for v in missing))
    lines += wrong
    return "\n".join(lines)


def help_text(commands: dict[str, str]) -> str:
    """The "Environment" section of a help message; ``commands`` maps a command to what it is called in the text."""
    out = ["Environment:"]
    for var in VARS:
        if var.needed_by == ():
            need = "optional"
        elif "local" in var.needed_by:
            need = "needed by " + " and ".join(commands[c] for c in ("run", "windows") if c in commands) + " with --rail local"
        elif here := [commands[c] for c in var.needed_by if c in commands]:
            need = "needed by " + ", ".join(here)
        else:
            need = "not needed here; needed by " + ", ".join(ELSEWHERE[c] for c in var.needed_by)
        out.append(f"  {var.name:<17} {var.what}; {need}")
    core = [v for v in VARS if v.needed_by and "local" not in v.needed_by and any(c in commands for c in v.needed_by)]
    local = [v for v in VARS if "local" in v.needed_by]
    out.append("")
    out.append("Set them (put your own paths in):")
    out.append("  export " + " ".join(f"{v.name}={v.example}" for v in core))
    out.append("  export " + " ".join(f"{v.name}={v.example}" for v in local) + "   # --rail local only")
    if "reset" in commands:
        out.append(f"{commands['reset']} needs none of them.")
    return "\n".join(out)
