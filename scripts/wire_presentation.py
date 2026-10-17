#!/usr/bin/env python3
"""Wire a compiled pack's presentation.json into a disclosed Evidence Bundle.

    wire_presentation.py --bundle bundle.json --presentation presentation.json --out wired.json

scripts/pack_compile.py writes a presentation.json beside every compiled.json:
exactly one block, keyed by the pack's report template (REPORT_TEMPLATES there).
The report renderer (capsulectl report build, agent-action-capsule's built-in
manifests) picks its view by that same key on the bundle's `extensions`:

  outcome-report/v1        -> the outcome card      (--card outcome)
  eu-ai-act-compliance/v1  -> the obligation card   (--card obligation)

This copies the block, verbatim, onto `bundle.extensions` and prints the card
it selects. The block is the producer's own mapping (article, applicability,
method, wording); it rides on the bundle OUTSIDE the signed records, which is
how the renderer itself labels it on the page. It is added after `capsulectl
disclose` has written the bundle, so the disclosure record's own digest does
not cover it.

Fails closed, never guesses:
  - a presentation.json carrying no block this module knows, or a key it
    doesn't know, is refused (a renamed template would otherwise render as a
    silent fallback page);
  - more than one known block is refused (the compliance view forbids the
    outcome-report extension; one pack compiles to one template);
  - a bundle that already carries the extension is refused rather than
    overwritten.
"""
from __future__ import annotations

import argparse
import copy
import json
import pathlib
import sys

# template key -> the capsulectl report build --card that renders it
CARD_FOR_TEMPLATE = {
    "outcome-report/v1": "outcome",
    "eu-ai-act-compliance/v1": "obligation",
}


class WireError(ValueError):
    pass


def wire(bundle, presentation):
    """Pure: (a new bundle with the block on its extensions, the template key,
    the card that renders it). Neither argument is modified."""
    if not isinstance(bundle, dict):
        raise WireError("bundle is not a JSON object")
    if not isinstance(presentation, dict) or not presentation:
        raise WireError("presentation.json is empty or not a JSON object")
    unknown = sorted(set(presentation) - set(CARD_FOR_TEMPLATE))
    if unknown:
        raise WireError(f"presentation.json carries block(s) this report does not know: {unknown!r} "
                        f"(known: {sorted(CARD_FOR_TEMPLATE)!r})")
    if len(presentation) != 1:
        raise WireError(f"presentation.json carries {len(presentation)} blocks {sorted(presentation)!r}; "
                        "one pack compiles to exactly one")
    (template, block), = presentation.items()
    if not isinstance(block, dict):
        raise WireError(f"{template} block is not a JSON object")
    if block.get("enabled") is not True:
        raise WireError(f"{template} block is not enabled (\"enabled\": true is required)")
    extensions = bundle.get("extensions")
    if extensions is not None and not isinstance(extensions, dict):
        raise WireError("bundle.extensions is not a JSON object")
    if extensions and template in extensions:
        raise WireError(f"bundle already carries a {template} extension; refusing to overwrite it")
    wired = copy.deepcopy(bundle)
    wired.setdefault("extensions", {})[template] = copy.deepcopy(block)
    return wired, template, CARD_FOR_TEMPLATE[template]


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bundle", required=True, type=pathlib.Path, help="the disclosed Evidence Bundle")
    ap.add_argument("--presentation", required=True, type=pathlib.Path,
                    help="the pack's compiled presentation.json")
    ap.add_argument("--out", required=True, type=pathlib.Path, help="where to write the wired bundle")
    args = ap.parse_args(argv)
    try:
        wired, template, card = wire(json.loads(args.bundle.read_text()),
                                     json.loads(args.presentation.read_text()))
    except (OSError, json.JSONDecodeError, WireError) as e:
        print(f"wire_presentation.py: {e}", file=sys.stderr)
        return 1
    args.out.write_text(json.dumps(wired))
    print(json.dumps({"template": template, "card": card}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
