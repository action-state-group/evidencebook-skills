#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Open the four Goose Desktop windows of the ARD demo: Maya (buyer), Alder and Kestrel (sellers), and the demo's
adjudicator.

    python goose/open-windows.py [--rail fake|lightning] [--print]

Each window is a recipe with its own embedded extension (``desktop_server.py`` with ``ARD_ROLE``), so each
party's Goose has its own keys and data directory. It opens ``goose://recipe?config=...`` links, which
Goose Desktop answers with one window each (it asks once per recipe: Trust and Execute). Open the sellers and the
adjudicator first and Maya last, then tiles them in quarters (:func:`tile`), Maya's in front.
It starts Goose itself on the demo's own root (:data:`GOOSE_ROOT_DEFAULT`, or ``ARD_GOOSE_ROOT``), so the demo's
provider and extension settings never touch your own Goose; ``--goose-only`` starts that Goose and opens no window.
``--print`` prints the links instead of opening them. The environment it needs is listed at the end of
--help."""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import shlex
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVER = HERE.parent / "desktop_server.py"
sys.path.insert(0, str(HERE.parent))
import envhelp  # noqa: E402
import reset  # noqa: E402

#: Each window's recipe is a thin wrapper: the party's own facts, then the skill it follows, read from the
#: this repository at the commit the run sheet pins (#169).
PARTIES = {
    "alder": {
        "title": "Alder Print Co. (seller)", "skill": "sell-with-evidence",
        "facts": "You are the selling agent of Alder Print Co., which sells 200 conference badges at 2,000 msat.",
        "prompt": "Reply in English only. Call your ard_seller_activity tool now and tell me in two short sentences what it shows.",
    },
    "kestrel": {
        "title": "Kestrel Print (seller)", "skill": "sell-with-evidence",
        "facts": "You are the selling agent of Kestrel Print, which sells 200 conference badges at 1,000 msat.",
        "prompt": "Reply in English only. Call your ard_seller_activity tool now and tell me in two short sentences what it shows.",
    },
    "adjudicator": {
        "title": "The adjudicator (run by the operator)", "skill": "adjudicate-deal",
        "facts": "You are the adjudicator's assistant. The operator runs this adjudicator and every party here, so it "
                 "is not independent of them. You gather and show a case; only the presenter decides a "
                 "ruling, in the dialog your ard_rule tool opens.",
        "prompt": "Reply in English only. In one short sentence, say you are the adjudicator's assistant and ready. Do "
                  "not call any tool until I ask.",
    },
    "maya": {
        "title": "Maya buys conference badges (buyer)", "skill": "buy-with-evidence",
        # no amount here: what she will pay comes in her own words, and her spending limit from her yes to it (#361)
        "facts": "You are Maya's buying agent. Maya needs 200 conference badges by Friday. "
                 "Your admission pack is demo/ard/pack.",
        # The first message searches nothing: the presenter types the ask, so all four windows can start together and
        # Maya never searches before the sellers have published their entries (Ethan, 2026-11-18).
        # the first turn shows her own card and the limit she set (#331, carrying #335); it searches nothing, so all four
        # windows can still start together
        "prompt": "Reply in English only. I am Maya. Call ard_show_card to show me my own History card and my spending "
                  "limit, then say in one short sentence that you are my buying agent and ready. Do not search until I ask.",
    },
}


def skill_text(name: str) -> str:
    """The skill's ``SKILL.md`` from this repository, without its front matter, and the commit it is at."""
    root = HERE.parents[2]
    text = (root / "skills" / name / "SKILL.md").read_text()
    if text.startswith("---\n"):
        text = text.split("\n---\n", 1)[1]
    run = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                         stdin=subprocess.DEVNULL)
    return text.strip(), (run.stdout.strip() if run.returncode == 0 else "")


def registry_url() -> str:
    """The stand-in registry's search URL, the one stage.REGISTRY_URL serves (the same ARD_STAGE_PORT)."""
    return f"http://127.0.0.1:{os.environ.get('ARD_STAGE_PORT', '47481')}/search"


def instructions(role: str, rail: str) -> str:
    """The recipe's instructions: the party's facts, this run's rail, and the skill it follows."""
    p = PARTIES[role]
    body, commit = skill_text(p["skill"])
    facts = p["facts"]
    if p["skill"] == "buy-with-evidence":  # the skill's required input: it has no default registry
        facts += f" The ARD registry to search is {registry_url()} (a local stand-in registry, run by the operator); referrals stay off."
    pays = ("This run pays over real Lightning: real money moves." if rail in ("lightning", "local")
            else "This run's payment rail is simulated: no money moves.")
    at = f" at evidencebook-skills {commit}" if commit else ""
    return f"{facts}\nWrite in English only. {pays}\nFollow the {p['skill']} skill below{at}.\n\n{body}\n"


#: What ``--print`` writes for a wallet variable that is not set: it only prints, so it needs no wallet.
PLACEHOLDER = {"ARD_WALLET_BUYER": "<buyer wallet dir>", "ARD_WALLET_SELLER": "<seller wallet dir>"}

#: Goose's timeout for one tool call. ard_pay is the longest call: the payment dialog (desktop_server.DIALOG_GIVE_UP_S
#: plus 20 s), the seller's agree (flow.WAIT_S), on the real rail the invoice (pay.INVOICE_WAIT_S) and the payment
#: (pay.PAY_WAIT_S), and the delivery (flow.WAIT_S): 1,310 s at most. A call cut off sooner would report an error after
#: the money had moved (#305 review).
TOOL_TIMEOUT_S = 1380


def recipe(role: str, rail: str, placeholders: bool = False) -> dict:
    env = [f"ARD_ROLE={role}", f"ARD_RAIL={rail}", f"CAPSULE_ENGINE={os.environ['CAPSULE_ENGINE']}",
           f"ARD_EVIDENCEBOOK={os.environ['ARD_EVIDENCEBOOK']}", f"CAPSULECTL_DEAL={os.environ['CAPSULECTL_DEAL']}"]
    # the testbed's own witness (ARD_WITNESS=local): its address, its key, and the certificate capsulectl trusts it by
    for var in ("ARD_HOME", "ARD_STAGE_PORT", "ARD_WITNESS", "ARD_WITNESS_URL", "ARD_WITNESS_KEY", "SSL_CERT_FILE"):
        if os.environ.get(var):
            env.append(f"{var}={os.environ[var]}")
    if role == "maya":  # a dialog answered by typed reply is read from this Goose's own record of the chat (#418)
        env.append(f"ARD_GOOSE_DB={goose_root() / 'data' / 'sessions' / 'sessions.db'}")
    if role == "maya":  # the countersign upgrade (ard_countersign): capsule-cli's own capsulectl and the countersigner's folder
        core = os.environ.get("CAPSULECTL") or shutil.which("capsulectl")
        if core:
            env.append(f"CAPSULECTL={core}")
        if os.environ.get("ARD_COUNTERSIGN_DIR"):
            env.append(f"ARD_COUNTERSIGN_DIR={os.environ['ARD_COUNTERSIGN_DIR']}")
    if rail == "local" and role == "maya":  # only the buyer's window pays
        for var in ("ARD_WALLET_BUYER", "ARD_WALLET_SELLER", "ARD_PAY_LOCAL"):
            if os.environ.get(var):
                env.append(f"{var}={os.environ[var]}")
            elif placeholders and var in PLACEHOLDER:
                env.append(f"{var}={PLACEHOLDER[var]}")
    p = PARTIES[role]
    return {"version": "1.0.0", "title": p["title"], "description": f"The ARD two-seller deal: {role}, following the {p['skill']} skill.",
              "instructions": instructions(role, rail), "prompt": p["prompt"],
              "extensions": [{"type": "stdio", "name": f"ard_{role}", "description": f"The {role} side of the ARD two-seller deal",
                              "cmd": "/usr/bin/env", "args": [*env, sys.executable, str(SERVER)], "timeout": TOOL_TIMEOUT_S}]}


def to_link(recipe: dict) -> str:
    # No base64 padding: Goose Desktop 1.59.2 opens a blank window for a recipe link whose config ends in "="
    # (percent-encoding it does not help), so a recipe whose JSON length is not a multiple of 3 never loaded.
    return "goose://recipe?config=" + base64.urlsafe_b64encode(json.dumps(recipe).encode()).decode().rstrip("=")


def link(role: str, rail: str, placeholders: bool = False) -> str:
    return to_link(recipe(role, rail, placeholders))


#: Goose Desktop 1.59.2 ignores a window position or size set from outside, and every window is titled "Goose", so the
#: windows are tiled the way a person does it: the Window, Move & Resize, Quarters menu item, which puts the four front
#: windows in the screen's four quarters, the front window (Maya's, opened last) among them. Two items of that menu are
#: named Quarters: a disabled heading above Top Left and the item under Arrange; only the enabled one tiles, and a click on
#: the heading does nothing and raises no error (evidencebook-skills#322).
#: Both lines go to System Events, so macOS asks for one permission only (no second "control Goose" prompt).
TILE = ["osascript", "-e", 'tell application "System Events" to set frontmost of process "Goose" to true', "-e",
        'tell application "System Events" to tell process "Goose" to click (first menu item of menu "Move & Resize" of '
        'menu item "Move & Resize" of menu "Window" of menu bar 1 whose name is "Quarters" and enabled is true)']
#: Every Goose window's frame, front to back, one ``x y width height`` line each: what the tile is judged on, since a menu
#: click that exits 0 says nothing about where the windows are (#322).
LAYOUT = ["osascript", "-e", 'tell application "System Events" to tell process "Goose"', "-e", 'set out to ""', "-e",
          "repeat with w in windows", "-e", "set {x, y} to position of w", "-e", "set {ww, hh} to size of w", "-e",
          'set out to out & x & " " & y & " " & ww & " " & hh & linefeed', "-e", "end repeat", "-e", "return out",
          "-e", "end tell"]

#: What osascript says when the terminal may not script System Events or use Accessibility yet.
_NOT_ALLOWED = ("-1719", "-1743", "-25211", "not allowed", "assistive access")
GRANT = ("Turn on your terminal app in System Settings, Privacy & Security, "
         "Accessibility, and allow it to control System Events when macOS asks. ")
MANUAL = ("Then click Maya's window and run the line below to tile again (no new windows), or tile by hand: "
          "Window, Move & Resize, then Quarters under Arrange (the Quarters above Top Left is only a heading).")


#: After a failed tile (the first run, while macOS asks for the permission), try again this often, this many times.
RETRY_S, RETRIES = 10, 2
#: After the click, the frames are read this often, this many times, until they show the tile (the windows move with an
#: animation).
SETTLE_S, SETTLE_READS = 0.5, 6
#: Frames that share at most this many points along an edge still count as side by side (rounding at the screen's middle).
EDGE_PT = 2
#: A quarter is at least this share of the width and height the four windows cover (less than half: macOS can leave
#: margins between tiled windows).
QUARTER_MIN = 0.4


def _osascript(cmd: list[str]) -> tuple[str | None, str, bool]:
    """``(stdout, why, grant)``: stdout when osascript exits 0, else None and the cause on one line, and whether it is a
    permission (or a timeout, which a pending permission prompt causes). Never raises."""
    try:
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as e:
        return None, " ".join(str(e).split()), True
    except (OSError, subprocess.SubprocessError) as e:
        return None, " ".join((str(e) or type(e).__name__).split()), False
    if run.returncode == 0:
        return run.stdout, "", False
    why = " ".join((run.stderr.strip() or f"osascript exit {run.returncode}").split())  # one line, whatever it printed
    return None, why, any(mark in why for mark in _NOT_ALLOWED)


def frames(text: str) -> list[tuple[int, int, int, int]]:
    """The ``(x, y, width, height)`` of each window in :data:`LAYOUT`'s output, front to back."""
    out = []
    for line in text.splitlines():
        if line.strip():
            x, y, w, h = (int(float(v)) for v in line.replace(",", " ").split())
            out.append((x, y, w, h))
    return out


def _shown(frame: tuple[int, int, int, int]) -> str:
    x, y, w, h = frame
    return f"{x},{y} {w}x{h}"


def layout_problem(seen: list[tuple[int, int, int, int]]) -> str | None:
    """None when Goose shows exactly the four windows, side by side in a two by two grid (no two overlap by more than
    :data:`EDGE_PT`, each in its own quarter of the area the four cover and at least :data:`QUARTER_MIN` of that area's
    width and height); else what was read, on one line. Goose started on the first window's link, so it has no window of
    its own: any other count means a window is missing or one is not the demo's."""
    if len(seen) != 4:
        return f"Goose shows {len(seen)} window{'s' if len(seen) != 1 else ''}, not four"
    if any(w <= 0 or h <= 0 for _, _, w, h in seen):
        return "a window has no size, at " + "; ".join(_shown(f) for f in seen)
    left, top = min(f[0] for f in seen), min(f[1] for f in seen)
    width, height = max(f[0] + f[2] for f in seen) - left, max(f[1] + f[3] for f in seen) - top
    quarters = {(f[0] + f[2] / 2 >= left + width / 2, f[1] + f[3] / 2 >= top + height / 2) for f in seen}
    overlap = any(min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]) > EDGE_PT
                  and min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]) > EDGE_PT
                  for i, a in enumerate(seen) for b in seen[i + 1:])
    small = any(w < QUARTER_MIN * width or h < QUARTER_MIN * height for _, _, w, h in seen)
    if overlap or small or len(quarters) != 4:
        return "the four windows are not in quarters, at " + "; ".join(_shown(f) for f in seen)
    return None


def _tile_once() -> tuple[bool, str, bool]:
    """``(tiled, why, grant)``: tiled only once the frames read back after the click show the four windows in quarters,
    read again every :data:`SETTLE_S` seconds :data:`SETTLE_READS` times while the windows move; else the cause on one
    line (what the last read showed), and whether it is a permission (or a timeout). Never raises."""
    out, why, grant = _osascript(TILE)
    if out is None:
        return False, why, grant
    for _ in range(SETTLE_READS):
        time.sleep(SETTLE_S)
        out, why, grant = _osascript(LAYOUT)
        if out is None:
            return False, f"could not read the windows back: {why}", grant
        try:
            why = layout_problem(frames(out))
        except ValueError:
            why = "could not read the windows back: " + " ".join(out.split())[:200]
        if not why:
            return True, "", False
    return False, why, False


def tile(say=lambda line: print(line, file=sys.stderr)) -> str | None:
    """Tile the four windows with Maya in front, trying again every :data:`RETRY_S` seconds :data:`RETRIES` times
    (time to allow the permission macOS asks for, or for the last window to open); None once the windows read back side
    by side, else the message to print, which ends with the command after a blank line. Never raises."""
    for attempt in range(RETRIES + 1):
        tiled, why, grant = _tile_once()
        if tiled:
            return None
        if attempt < RETRIES:
            say(f"could not tile the windows yet ({why}); trying again in {RETRY_S} s"
                + (": allow the access macOS asks for." if grant else "."))
            time.sleep(RETRY_S)
    return f"could not tile the windows ({why}). " + (GRANT if grant else "") + MANUAL + "\n\n" + shlex.join(TILE)


#: The demo's own Goose root (reset.GOOSE_ROOT_DEFAULT, which says why), or ARD_GOOSE_ROOT.
GOOSE_ROOT_DEFAULT = reset.GOOSE_ROOT_DEFAULT


#: The Claude Code ACP adapter the demo's Goose uses, installed under the demo's own prefix and never globally: a
#: global install replaces the version other ACP clients on the Mac rely on (one broke above 0.94.0). 0.108.0 is the
#: version Goose 1.59.2 ran with on the Mac the demo was built on.
ACP_PIN = "0.108.0"
#: The demo's adapter wrapper (evidencebook-skills#276): the folder Goose searches first for claude-agent-acp.
LOCKED_DIR = HERE / "locked"
ACP_PREFIX_DEFAULT = "~/ard-demo/acp"


def acp_prefix() -> Path:
    return Path(os.environ.get("ARD_ACP_PREFIX", ACP_PREFIX_DEFAULT)).expanduser()


def acp_install() -> str:
    return f"npm install --prefix {acp_prefix()} @agentclientprotocol/claude-agent-acp@{ACP_PIN}"


def goose_root() -> Path:
    return reset.goose_root()


#: Goose 1.59.2 providers that run their own agent, with its own tools (a shell among them), outside Goose's extensions:
#: set-up step 9's switches do not reach them, so a window's agent could operate the payment dialog (#276). Ids from
#: goose v1.59.2 crates/goose/src/providers/*.rs. Claude Code ACP runs through the demo's locked adapter instead.
AGENT_PROVIDERS = frozenset({"claude-code", "codex", "cursor-agent", "gemini-cli", "codex-acp", "amp-acp", "copilot-acp",
                             "pi-acp"})
LOCKED_PROVIDER = "claude-acp"
#: Goose's scheduler stays on (set-up step 9, the hand run of 2026-11-24): it schedules recipes, it gives no agent a tool
#: that acts on the screen or a shell.
KEPT_ON = frozenset({"scheduler"})


#: Goose 1.59.2 reads its config from these layers, later ones overriding (crates/goose/src/config/base.rs Config::default:
#: the system file, then GOOSE_ADDITIONAL_CONFIG_FILES, then the root's own file). ``open -a`` starts Goose with
#: launchd's environment, not the terminal's, so additional files can come only from there: provider_problem refuses
#: when launchd names any (launchd_env).
SYSTEM_CONFIG = Path("/etc/goose/config.yaml")


class ConfigError(Exception):
    pass


def _yaml(f: Path) -> dict:
    import yaml
    try:
        doc = yaml.safe_load(f.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"{f} cannot be read as Goose's config ({' '.join(str(exc).split())[:200]})") from None
    if doc is None:
        return {}
    if not isinstance(doc, dict):
        raise ConfigError(f"{f} is not a Goose config (not a mapping)")
    return doc


def goose_config(root: Path) -> dict:
    """The config the demo's Goose runs on: the system file under the root's own (``<root>/config/config.yaml``),
    extensions merged by name; {} before set-up."""
    system, own = _yaml(SYSTEM_CONFIG), _yaml(root / "config" / "config.yaml")
    cfg = {**system, **own}
    # field by field, as Goose merges its layers (config/base.rs): an own entry that sets only display_name keeps the
    # system file's enabled
    sys_ext, own_ext = system.get("extensions") or {}, own.get("extensions") or {}
    for f, ext in ((SYSTEM_CONFIG, sys_ext), (root / "config" / "config.yaml", own_ext)):
        if not isinstance(ext, dict) or any(v and not isinstance(v, dict) for v in ext.values()):
            raise ConfigError(f"{f} has an extensions entry that is not a mapping")
    cfg["extensions"] = {k: {**(sys_ext.get(k) or {}), **(own_ext.get(k) or {})}
                         for k in {*sys_ext, *own_ext}}
    return cfg


def launchd_env(name: str) -> str:
    """A variable in launchd's environment, which ``open -a`` hands Goose; "" when unset or not readable."""
    try:
        run = subprocess.run(["launchctl", "getenv", name], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                             timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return run.stdout.strip() if run.returncode == 0 else ""


def provider_of(cfg: dict) -> str | None:
    """The active provider as Goose 1.59.2 picks it (config/providers.rs get_active_provider): GOOSE_PROVIDER in Goose's
    own environment first (launch_goose passes the one checked here), then ``active_provider``, then ``GOOSE_PROVIDER``."""
    return cfg.get("active_provider") or cfg.get("GOOSE_PROVIDER")


def provider_problem(root: Path) -> str | None:
    return check_provider(root)[0]


def check_provider(root: Path) -> tuple[str | None, str | None]:
    """Why the demo's Goose must not open the windows with the provider it is set to (or None), and the provider that
    check read, which launch_goose hands Goose as is (#340). Claude Code ACP needs the demo's pinned, locked adapter; a
    provider where Goose runs the tools needs every Goose extension off (set-up step 9), so only each window's own
    extension reaches its agent; a provider that runs its own agent is refused."""
    if extra := launchd_env("GOOSE_ADDITIONAL_CONFIG_FILES"):
        return (f"launchd hands Goose more config files ({extra}), which this check does not read: launchctl unsetenv "
                "GOOSE_ADDITIONAL_CONFIG_FILES, then run this again"), None
    try:
        cfg = goose_config(root)
    except ConfigError as exc:
        return str(exc), None
    provider = launchd_env("GOOSE_PROVIDER") or provider_of(cfg)
    if provider == LOCKED_PROVIDER:
        if not (acp_prefix() / "node_modules" / ".bin" / "claude-agent-acp").exists():
            return (f"the demo's own Claude Code adapter is not installed: {acp_install()} (pinned, under the demo's "
                    "folder; never npm install -g, which changes the adapter other tools use)"), provider
        return None, provider
    if provider in AGENT_PROVIDERS:
        # Sherlock2 on #340 (ops c0813d7e, amended f5adbf20; #356): the allowed choices by the names Goose shows,
        # and where to switch, in plain words, no provider id
        return ("the demo's Goose uses a model provider that runs its own agent with its own tools, which could answer "
                "the Set limit, Pay, Received, Dispute and Rule dialogs instead of you. Choose ChatGPT Codex (a "
                "ChatGPT sign-in), an API key (Google, OpenAI, Anthropic and others), or Claude Code (ACP): start the "
                "demo's Goose with open-windows.py --goose-only and change it in Settings, Models"), provider
    if not provider:
        return "the demo's Goose has no provider yet: choose one in set-up step 8 (open-windows.py --goose-only)", None
    on = sorted(str(v.get("display_name") or k) for k, v in cfg["extensions"].items()
                if isinstance(v, dict) and v.get("enabled") and k not in KEPT_ON)
    if on:
        return ("with this provider, every Goose extension must be off so each window's agent has only its own "
                "demo tools (set-up step 9); still on: " + ", ".join(on)), provider
    return None, provider


def launch_goose(root: Path, wait_s: float = 30.0, setup: bool = False, first: str | None = None) -> str | None:
    """Start Goose Desktop on ``root``, opening the recipe link ``first`` as it starts; None once it runs, else why not.
    Started with a link, Goose 1.59.2 opens that recipe's window and no window of its own (ui/desktop/src/main.ts: the
    open-url handler sets openUrlHandledLaunch), so every Goose window is one the demo opened. The caller has checked
    Goose is not running:
    a running Goose would take the recipe links into its own settings. For the windows the provider must pass
    :func:`check_provider`, and Goose gets exactly the provider it checked; with ``setup`` (the settings only, no
    window, no dialog) Goose opens on whatever it is set to, with no provider pinned, so a person can change it, and the
    problem is printed as a note."""
    problem, checked = check_provider(root)
    if problem and not setup:
        return problem
    if problem:
        print(f"note: {problem}; change it in this Goose's Settings, Models before opening the windows")
    provider = None if setup else checked
    root.mkdir(parents=True, exist_ok=True)
    # Goose resolves claude-agent-acp from GOOSE_SEARCH_PATHS before /opt/homebrew/bin and PATH
    # (crates/goose/src/config/search_path.rs), and reads that config value from the environment first. It finds the
    # demo's locked adapter (goose/locked, #276), which runs the pinned one under ARD_ACP_PREFIX with each agent limited
    # to ToolSearch and its own ard tools; ARD_PYTHON runs the lock's filter.
    try:
        subprocess.run(["open", "-a", "Goose", "--env", f"GOOSE_PATH_ROOT={root}",
                        "--env", f"GOOSE_SEARCH_PATHS={json.dumps([str(LOCKED_DIR)])}",
                        "--env", f"ARD_ACP_PREFIX={acp_prefix()}", "--env", f"ARD_PYTHON={sys.executable}",
                        # the provider the check above read (#340); Goose takes GOOSE_PROVIDER from its environment first
                        *(["--env", f"GOOSE_PROVIDER={provider}"] if provider else []), *([first] if first else [])],
                       check=True,
                       capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        return f"could not start Goose Desktop ({' '.join(str(e).split())}); is Goose.app in Applications?"
    end = time.monotonic() + wait_s
    while not reset.goose_running():
        if time.monotonic() >= end:
            return f"Goose Desktop did not start within {wait_s:.0f} s"
        time.sleep(0.5)
    time.sleep(5)  # its server starts after the app: give it a moment before the first link
    return None


def already_trusted(recipes: list[dict]) -> list[str]:
    """The titles of the recipes Goose already trusts. Goose Desktop 1.59.2 skips the Trust and Execute prompt only for a
    recipe whose trust file exists (ui/desktop/src/sessions.ts ensureRecipeConsent, utils/recipeHash.ts, at v1.59.2
    9da692f), named as reset.trust_hash computes it, so these windows open and run with no prompt (#322)."""
    folder = reset._hashes()
    return [r["title"] for r in recipes if (folder / f"{reset.trust_hash(r)}.hash").is_file()]


#: Reset deletes the demo home too, so the way back is the RUNBOOK's whole "Before each run" (its step 7 says the same).
TRUSTED = ("Goose already trusts these recipes, so their windows open with no Trust and Execute prompt: {titles}. To be "
           "asked again, quit Goose and do the RUNBOOK's \"Before each run\" again from step 1 (reset, seed and its wait, "
           "the balances, the windows).")


RUNNING = ("Goose Desktop is running: quit it first (osascript -e 'quit app \"Goose\"'), then run this again. "
           "open-windows.py starts its own Goose on {root}, so the demo never changes your own Goose settings.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="open-windows.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=envhelp.help_text({"windows": "open-windows.py"}))
    ap.add_argument("--rail", choices=["fake", "lightning", "local"], default="fake")
    ap.add_argument("--print", action="store_true", dest="show")
    ap.add_argument("--only", choices=["alder", "kestrel", "adjudicator", "maya"], help="open one window only")
    ap.add_argument("--goose-only", action="store_true",
                    help="start the demo's own Goose and open no window (for the one-time provider setup)")
    args = ap.parse_args(argv)
    root = goose_root()
    home = Path(os.environ.get("ARD_HOME", reset.DEFAULT_HOME)).expanduser()
    if root.resolve() == home.resolve() or home.resolve() in root.resolve().parents:
        print(f"ARD_GOOSE_ROOT {root} is inside the demo home {home}, which reset deletes: choose a folder outside it",
              file=sys.stderr)
        return 2
    if args.goose_only:  # only starts Goose: it needs none of the demo's variables
        if reset.goose_running():
            print(RUNNING.format(root=root), file=sys.stderr)
            return 2
        failed = launch_goose(root, setup=True)
        print(failed or f"started the demo's own Goose on {root}", file=sys.stderr if failed else sys.stdout)
        return 1 if failed else 0
    # --print opens nothing and pays nothing, so it needs no wallet: it checks the rest and writes placeholders.
    if gap := envhelp.message("open-windows.py", "fake" if args.show else args.rail, as_command="windows"):
        print(gap + "\n(open-windows.py --help lists every variable.)", file=sys.stderr)
        return 2
    if not args.show and reset.goose_running():
        print(RUNNING.format(root=root), file=sys.stderr)
        return 2
    roles = [args.only] if args.only else ["alder", "kestrel", "adjudicator", "maya"]  # Maya last: hers is the front window
    if args.show:
        for role in roles:
            print(link(role, args.rail, placeholders=True))
    else:
        recipes = [recipe(role, args.rail) for role in roles]
        try:  # before any window can be trusted: reset deletes exactly these trust files
            reset.note_trust(recipes, root)
        except ValueError as e:  # a recipe reset could not clear again: open nothing rather than leave trust behind
            print(f"open-windows.py: {e}; nothing was opened (evidencebook-skills#277)", file=sys.stderr)
            return 2
        if trusted := already_trusted(recipes):
            print(TRUSTED.format(titles="; ".join(trusted)), file=sys.stderr)
        # Goose starts on the first window's link, so it opens no window of its own for the tile to count (#322)
        if failed := launch_goose(root, first=to_link(recipes[0])):
            print(failed, file=sys.stderr)
            return 1
        for r in recipes[1:]:
            subprocess.run(["open", to_link(r)], check=True)
            time.sleep(3)
    unset = [v for v in PLACEHOLDER if not os.environ.get(v)]
    if args.show and args.rail == "local" and unset:
        print(f"printed with placeholder paths for {', '.join(unset)}: set them before opening the windows "
              "(open-windows.py without --print checks them)", file=sys.stderr)
    if not args.show and not args.only:
        if failed := tile():
            print(failed, file=sys.stderr)  # the windows are open either way: tiling is a convenience
        else:
            print("tiled the four windows in quarters (read back from the screen)")  # where, not which window is where
    return 0


if __name__ == "__main__":
    sys.exit(main())
