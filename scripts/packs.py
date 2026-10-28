#!/usr/bin/env python3
"""The Terms Packs this repository holds, and the honest refusal when none fits.

The evidencebook-report skill makes an EvidenceBook report (grade 2) only over a
pack whose contract covers the question. This reads the packs from the tree
instead of a list typed into the skill, so a pack added or removed changes the
answer without editing the skill.

    packs.py list                 every pack: its directory name, pack_id, the
                                  compiled spec report.sh takes, and its card
    packs.py require NAME         that pack's entry (exit 0), or the refusal
                                  (exit 3) naming the packs that exist

NAME is a pack's directory name under packs/ or its pack_id. The refusal is
JSON with the sentence the skill says to the person; it carries no count and no
judgment, because without a pack there is no Result to read one from.
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

OFFER = ("I can narrate it from your records, without totals, or show your "
         "standard History card.")


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
    return {
        "name": name,
        "pack_id": pack_id,
        "contract_ref": json.loads(spec.read_text()).get("contract_ref") if spec else None,
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
                return REFUSED, refusal(name, packs, f"the {p['name']} pack is not compiled yet")
            return 0, p
    return REFUSED, refusal(name, packs, f"no Terms Pack named {name!r}")


def refusal(name, packs, reason):
    names = [p["name"] for p in packs if p["spec"] is not None]
    listed = ", ".join(names) if names else "none"
    return {
        "refused": "no_pack",
        "asked": name,
        "reason": reason,
        "packs": names,
        "say": (f"No Terms Pack covers this, so I can't make an EvidenceBook report of it. "
                f"The packs that exist: {listed}. {OFFER}"),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    req = sub.add_parser("require")
    req.add_argument("name")
    args = ap.parse_args(argv)
    if args.cmd == "list":
        print(json.dumps(list_packs(), indent=2))
        return 0
    code, answer = require(args.name)
    print(json.dumps(answer, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
