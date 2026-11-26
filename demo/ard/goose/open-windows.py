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
        # no amount here: what she will pay comes in her own words, and her spending limit from ARD_LIMIT_MSAT (#331)
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
    for var in ("ARD_HOME", "ARD_STAGE_PORT", "ARD_WITNESS", "ARD_NOTIFY"):
        if os.environ.get(var):
            env.append(f"{var}={os.environ[var]}")
    if role == "maya" and os.environ.get("ARD_LIMIT_MSAT"):  # the buyer's spending limit (limits.py)
        env.append(f"ARD_LIMIT_MSAT={os.environ['ARD_LIMIT_MSAT']}")
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
#: windows are tiled the way a person does it: the Window, Move & Resize, Quarters menu item, which puts the four
#: windows in the screen's four quarters, the front window (Maya's, opened last) among them.
#: Both lines go to System Events, so macOS asks for one permission only (no second "control Goose" prompt).
TILE = ["osascript", "-e", 'tell application "System Events" to set frontmost of process "Goose" to true', "-e",
        'tell application "System Events" to tell process "Goose" to click menu item "Quarters" of menu '
        '"Move & Resize" of menu item "Move & Resize" of menu "Window" of menu bar 1']

#: What osascript says when the terminal may not script System Events or use Accessibility yet.
_NOT_ALLOWED = ("-1719", "-1743", "-25211", "not allowed", "assistive access")
GRANT = ("Turn on your terminal app in System Settings, Privacy & Security, "
         "Accessibility, and allow it to control System Events when macOS asks. ")
MANUAL = ("Then click Maya's window and run the line below to tile again (no new windows), or tile by hand: "
          "Window, Move & Resize, Quarters.")


#: After a failed tile (the first run, while macOS asks for the permission), try again this often, this many times.
RETRY_S, RETRIES = 10, 2


def _tile_once() -> tuple[bool, str, bool]:
    """``(tiled, why, grant)``: the cause on one line, and whether it is a permission (or a timeout, which a pending
    permission prompt causes). Never raises."""
    try:
        run = subprocess.run(TILE, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as e:
        return False, " ".join(str(e).split()), True
    except (OSError, subprocess.SubprocessError) as e:
        return False, " ".join((str(e) or type(e).__name__).split()), False
    if run.returncode == 0:
        return True, "", False
    why = " ".join((run.stderr.strip() or f"osascript exit {run.returncode}").split())  # one line, whatever it printed
    return False, why, any(mark in why for mark in _NOT_ALLOWED)


def tile(say=lambda line: print(line, file=sys.stderr)) -> str | None:
    """Tile the four windows with Maya in front, trying again every :data:`RETRY_S` seconds :data:`RETRIES` times
    (time to allow the permission macOS asks for); None when it worked, else the message to print, which ends with
    the command after a blank line. Never raises."""
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
    cfg["extensions"] = {**(system.get("extensions") or {}), **(own.get("extensions") or {})}
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
    """Why the demo's Goose must not open the windows with the provider it is set to, or None (#340). Claude Code ACP
    needs the demo's pinned, locked adapter; a provider where Goose runs the tools needs every Goose extension off (set-up
    step 9), so only each window's own extension reaches its agent; a provider that runs its own agent is refused."""
    if extra := launchd_env("GOOSE_ADDITIONAL_CONFIG_FILES"):
        return (f"launchd hands Goose more config files ({extra}), which this check does not read: "
                "launchctl unsetenv GOOSE_ADDITIONAL_CONFIG_FILES, then run this again")
    try:
        cfg = goose_config(root)
    except ConfigError as exc:
        return str(exc)
    provider = launchd_env("GOOSE_PROVIDER") or provider_of(cfg)
    if provider == LOCKED_PROVIDER:
        if not (acp_prefix() / "node_modules" / ".bin" / "claude-agent-acp").exists():
            return (f"the demo's own Claude Code adapter is not installed: {acp_install()} (pinned, under the demo's "
                    "folder; never npm install -g, which changes the adapter other tools use)")
        return None
    if provider in AGENT_PROVIDERS:
        return (f"the demo's Goose is set to {provider}, which runs its own agent with its own tools, so the windows' "
                "agents could act outside the demo's tools: choose Claude Code ACP or a provider Goose runs itself (an API "
                "key, or a sign-in such as Gemini or ChatGPT) in its Settings, Models (open-windows.py --goose-only)")
    if not provider:
        return "the demo's Goose has no provider yet: choose one in set-up step 8 (open-windows.py --goose-only)"
    on = sorted(str(v.get("display_name") or k) for k, v in cfg["extensions"].items()
                if isinstance(v, dict) and v.get("enabled") and k not in KEPT_ON)
    if on:
        return ("with " + str(provider) + ", every Goose extension must be off so each window's agent has only its own "
                "demo tools (set-up step 9); still on: " + ", ".join(on))
    return None


def launch_goose(root: Path, wait_s: float = 30.0, setup: bool = False) -> str | None:
    """Start Goose Desktop on ``root``; None once it runs, else why not. The caller has checked Goose is not running:
    a running Goose would take the recipe links into its own settings. For the windows the provider must pass
    :func:`provider_problem`; with ``setup`` (the settings only, no window, no dialog) Goose opens whatever it is set to,
    so a person can change the provider, and the problem is printed as a note."""
    problem = provider_problem(root)
    if problem and not setup:
        return problem
    if problem:
        print(f"note: {problem}; change it in this Goose's Settings, Models before opening the windows")
    provider = None if problem else provider_of(goose_config(root))
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
                        *(["--env", f"GOOSE_PROVIDER={provider}"] if provider else [])], check=True,
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
    import limits  # the limit's one parser (limits.limit_msat); it needs no evidencebook checkout
    try:  # a bad spending limit stops here, before any window opens (#331), not at the buyer's first turn
        limits.limit_msat()
    except limits.LimitError as exc:
        print(str(exc), file=sys.stderr)
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
        if failed := launch_goose(root):
            print(failed, file=sys.stderr)
            return 1
        for r in recipes:
            subprocess.run(["open", to_link(r)], check=True)
            time.sleep(3)
    unset = [v for v in PLACEHOLDER if not os.environ.get(v)]
    if args.show and args.rail == "local" and unset:
        print(f"printed with placeholder paths for {', '.join(unset)}: set them before opening the windows "
              "(open-windows.py without --print checks them)", file=sys.stderr)
    if not args.show and not args.only and (failed := tile()):
        print(failed, file=sys.stderr)  # the windows are open either way: tiling is a convenience
    return 0


if __name__ == "__main__":
    sys.exit(main())
