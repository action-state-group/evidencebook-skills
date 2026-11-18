#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Open the three Goose Desktop windows of the ARD demo: Maya (buyer), Alder and Kestrel (sellers).

    python goose/open-windows.py [--rail fake|lightning] [--print]

Each window is a recipe with its own embedded extension (``desktop_server.py`` with ``ARD_ROLE``), so each
party's Goose has its own keys and data directory. It opens ``goose://recipe?config=...`` links, which
Goose Desktop answers with one window each (it asks once per recipe: Trust and Execute). Open the sellers
first and Maya last, then tiles them (:func:`tile`): Maya on the left half, the sellers on the right quarters.
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
    "maya": {
        "title": "Maya buys conference badges (buyer)", "skill": "buy-with-evidence",
        "facts": "You are Maya's buying agent. Maya needs 200 conference badges by Friday, under 3,000 msat. "
                 "Your admission pack is packs/ard-demo-buyer.",
        # The first message searches nothing: the presenter types the ask, so all three windows can start together and
        # Maya never searches before the sellers have published their entries (Ethan, 2026-11-18).
        "prompt": "Reply in English only. I am Maya. In one short sentence, say you are my buying agent and ready. Do not "
                  "search or call any tool until I ask.",
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
    """The stand-in registry's search URL, the one parties.REGISTRY_URL serves (the same ARD_STAGE_PORT)."""
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


def link(role: str, rail: str) -> str:
    env = [f"ARD_ROLE={role}", f"ARD_RAIL={rail}", "CAPSULE_WITNESS=off",
           f"CAPSULE_ENGINE={os.environ['CAPSULE_ENGINE']}", f"ARD_EVIDENCEBOOK={os.environ['ARD_EVIDENCEBOOK']}"]
    for var in ("ARD_HOME", "ARD_STAGE_PORT", "CAPSULECTL_DEAL"):  # CAPSULECTL_DEAL: the receipt pages' verifier
        if os.environ.get(var):
            env.append(f"{var}={os.environ[var]}")
    if rail == "local" and role == "maya":  # only the buyer's window pays
        for var in ("ARD_WALLET_BUYER", "ARD_WALLET_SELLER", "ARD_PAY_LOCAL"):
            if os.environ.get(var):
                env.append(f"{var}={os.environ[var]}")
    p = PARTIES[role]
    recipe = {"version": "1.0.0", "title": p["title"], "description": f"The ARD two-seller deal: {role}, following the {p['skill']} skill.",
              "instructions": instructions(role, rail), "prompt": p["prompt"],
              "extensions": [{"type": "stdio", "name": f"ard_{role}", "description": f"The {role} side of the ARD two-seller deal",
                              "cmd": "/usr/bin/env", "args": [*env, sys.executable, str(SERVER)], "timeout": 300}]}
    # No base64 padding: Goose Desktop 1.59.2 opens a blank window for a recipe link whose config ends in "="
    # (percent-encoding it does not help), so a recipe whose JSON length is not a multiple of 3 never loaded.
    return "goose://recipe?config=" + base64.urlsafe_b64encode(json.dumps(recipe).encode()).decode().rstrip("=")


#: Goose Desktop 1.59.2 ignores a window position or size set from outside, and every window is titled "Goose", so the
#: windows are tiled the way a person does it: the Window, Move & Resize, Left & Quarters menu item, which puts the
#: front window (Maya's, opened last) on the left half and the others on the right quarters.
#: Both lines go to System Events, so macOS asks for one permission only (no second "control Goose" prompt).
TILE = ["osascript", "-e", 'tell application "System Events" to set frontmost of process "Goose" to true', "-e",
        'tell application "System Events" to tell process "Goose" to click menu item "Left & Quarters" of menu '
        '"Move & Resize" of menu item "Move & Resize" of menu "Window" of menu bar 1']

#: What osascript says when the terminal may not script System Events or use Accessibility yet.
_NOT_ALLOWED = ("-1719", "-1743", "-25211", "not allowed", "assistive access")
GRANT = ("Turn on your terminal app in System Settings, Privacy & Security, "
         "Accessibility, and allow it to control System Events when macOS asks. ")
MANUAL = ("Then click Maya's window and run the line below to tile again (no new windows), or tile by hand: "
          "Window, Move & Resize, Left & Quarters.")


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
    """Tile the three windows with Maya in front, trying again every :data:`RETRY_S` seconds :data:`RETRIES` times
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="open-windows.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=envhelp.help_text({"windows": "open-windows.py"}))
    ap.add_argument("--rail", choices=["fake", "lightning", "local"], default="fake")
    ap.add_argument("--print", action="store_true", dest="show")
    ap.add_argument("--only", choices=["alder", "kestrel", "maya"], help="open one window only")
    args = ap.parse_args(argv)
    if gap := envhelp.message("open-windows.py", args.rail, as_command="windows"):
        print(gap + "\n(open-windows.py --help lists every variable.)", file=sys.stderr)
        return 2
    if not args.show:  # before any window can be trusted: reset then clears only the trust given since
        reset.snapshot_trust(Path(os.environ.get("ARD_HOME", reset.DEFAULT_HOME)).expanduser())
    for role in ([args.only] if args.only else ["alder", "kestrel", "maya"]):  # Maya last: hers is the front window
        if args.show:
            print(link(role, args.rail))
        else:
            subprocess.run(["open", link(role, args.rail)], check=True)
            time.sleep(3)
    if not args.show and not args.only and (failed := tile()):
        print(failed, file=sys.stderr)  # the windows are open either way: tiling is a convenience
    return 0


if __name__ == "__main__":
    sys.exit(main())
