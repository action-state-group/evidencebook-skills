#!/usr/bin/env python3
"""The Terms Packs this repository holds, and the honest refusal when none fits.

The evidencebook-report skill makes an EvidenceBook report (grade 2) only over a
pack whose contract covers the question. This reads the packs from the tree
instead of a list typed into the skill, so a pack added or removed changes the
answer without editing the skill.

    packs.py list                 every pack: its directory name, pack_id, title,
                                  the compiled spec report.sh takes, and its card
    packs.py require NAME         that pack's entry (exit 0), or the refusal
                                  (exit 3)
    packs.py refuse               the refusal (exit 3), for a question the agent
                                  finds no pack covers

NAME is a pack's directory name under packs/ or its pack_id. The refusal is
JSON with the sentence the skill says to the person, naming the packs that
exist by title; it carries no count and no judgment, because without a pack
there is no Result to read one from.
"""
import argparse
import json
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from wire_presentation import prepare_block  # noqa: E402

# report.sh's own default when a compiled pack has no presentation.json.
DEFAULT_CARD = "outcome"

REFUSED = 3

# history_card/1 is what a book serves today: checkpoints and receipts, no
# counts. The standard card with counts is not registered yet.
OFFER = ("I can narrate it from your records, without totals, or show your History card "
         "(your checkpoints and receipts; it has no totals yet).")


def compiled_spec(root, name):
    """The compiled contract scripts/pack_compile.py wrote for packs/NAME: beside
    the source (packs/NAME/compiled/) or under demo/NAME/. None if neither."""
    for candidate in (root / "packs" / name / "compiled" / "compiled.json",
                      root / "demo" / name / "compiled.json"):
        if candidate.is_file():
            return candidate
    return None


def pack_entry(root, source):
    name = source.parent.name
    pack_id = (yaml.safe_load(source.read_text()) or {}).get("pack_id")
    spec = compiled_spec(root, name)
    card = DEFAULT_CARD
    if spec is not None:
        presentation = spec.with_name("presentation.json")
        if presentation.is_file():
            _, _, card = prepare_block(json.loads(presentation.read_text()))
    compiled = json.loads(spec.read_text()) if spec else {}
    return {
        "name": name,
        "pack_id": pack_id,
        "title": compiled.get("title") or name,
        "contract_ref": compiled.get("contract_ref"),
        "spec": str(spec.relative_to(root)) if spec else None,
        "card": card,
    }


def list_packs(root=ROOT):
    return [pack_entry(root, s) for s in sorted((root / "packs").glob("*/pack-source.yaml"))]


def require(name, root=ROOT):
    """(exit code, JSON-able answer) for `packs.py require NAME`."""
    packs = list_packs(root)
    for p in packs:
        if name in (p["name"], p["pack_id"]):
            if p["spec"] is None:
                return REFUSED, refusal(packs, name, f"the {p['name']} pack is not compiled yet",
                                        f"The {p['title']} pack exists but isn't ready to report from yet.")
            return 0, p
    return REFUSED, refusal(packs, name, f"no Terms Pack named {name!r}")


def refusal(packs, asked=None, reason="no Terms Pack covers the question", lead=None):
    ready = [p for p in packs if p["spec"] is not None]
    titles = ", ".join(p["title"] for p in ready) if ready else "none"
    lead = lead or ("No Terms Pack covers this, so I can't make an EvidenceBook report of it. "
                    f"The packs that exist: {titles}.")
    return {
        "refused": "no_pack",
        "asked": asked,
        "reason": reason,
        "packs": [p["name"] for p in ready],
        "titles": [p["title"] for p in ready],
        "say": f"{lead} {OFFER}",
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    req = sub.add_parser("require")
    req.add_argument("name")
    sub.add_parser("refuse")
    args = ap.parse_args(argv)
    if args.cmd == "list":
        print(json.dumps(list_packs(), indent=2))
        return 0
    if args.cmd == "refuse":
        code, answer = REFUSED, refusal(list_packs())
    else:
        code, answer = require(args.name)
    print(json.dumps(answer, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
