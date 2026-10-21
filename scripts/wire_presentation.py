#!/usr/bin/env python3
"""Wire a compiled pack's presentation.json into a disclosed Evidence Bundle.

    wire_presentation.py --bundle bundle.json --presentation presentation.json --out wired.json

scripts/pack_compile.py writes a presentation.json beside every compiled.json:
exactly one block, keyed by the pack's report template (REPORT_TEMPLATES there).
The report renderer (capsulectl book report build, agent-action-capsule's
built-in manifests) picks its view by that same key on the bundle's `extensions`:

  outcome-report/v1        -> the outcome card      (--card outcome)
  eu-ai-act-compliance/v1  -> the obligation card   (--card obligation)

This copies the block onto `bundle.extensions` and prints the card it selects.
The block is the producer's own mapping (check questions, criterion labels and
wording; on the EU card, article, title, plain-language summary, applicability
and method). It is added after `capsulectl disclose` has written the bundle, so
it rides OUTSIDE the signed records: no record's digest covers it and nothing
on the page should read as if one did.

So the page says so, through a channel the renderer already labels:

  - outcome-report/v1: the renderer draws only the block's display settings
    (`percentages`) and its `producer_note`, under its own fixed label
    ("Producer's note · presentation text, not evidence ... outside the signed
    records"). The card's checks, criteria and wording come from the sealed
    claims and reports, never from the block's `terms`. This module adds a
    `producer_note` (PRODUCER_NOTE_LINES) stating that the block was added by
    the report's producer after disclosure, that no signed record covers it,
    and that the pack's own wording it carries is not what the page shows. A
    note the block already carries is kept, with these lines appended.
  - eu-ai-act-compliance/v1: the renderer reads no note from this block, and
    it does show the producer's titles and summaries. It labels them itself:
    its header says the article, applicability, method and finding
    recommendations are the producer's mapping outside the signed records, and
    each obligation's detail says "Article, summary and method: the producer's
    mapping, not a sealed record." The block is copied verbatim. (The header
    sentence does not yet name the obligation titles, test names, not-evaluable
    notes or the quality protocol; that wording is the renderer's, not ours.)

Fails closed, never guesses:
  - a presentation.json carrying no block this module knows, or a key it
    doesn't know, is refused (a renamed template would otherwise render as a
    silent fallback page);
  - more than one known block is refused (the compliance view forbids the
    outcome-report extension; one pack compiles to one template);
  - a bundle that already carries the extension is refused rather than
    overwritten;
  - an outcome-report/v1 block whose own producer_note would, with the lines
    added here, break the renderer's limits is refused (the renderer drops a
    note over its limits whole, which would leave the page unlabelled).
"""
from __future__ import annotations

import argparse
import copy
import json
import pathlib
import sys

# template key -> the capsulectl book report build --card that renders it
CARD_FOR_TEMPLATE = {
    "outcome-report/v1": "outcome",
    "eu-ai-act-compliance/v1": "obligation",
}

# The templates whose renderer draws a `producer_note` from the block (under its
# own fixed "Producer's note ... not evidence" label). Only outcome-report/v1's
# reader (agent-action-capsule ts/src/outcome-report-presentation.ts) has one.
NOTE_TEMPLATES = ("outcome-report/v1",)

PRODUCER_NOTE_TITLE = "Added by this report's producer"
PRODUCER_NOTE_LINES = (
    "This report's producer added this note and the page's display settings to the bundle "
    "after it was disclosed. No signed record covers them, and they are not evidence.",
)
# Added only when the block carries the pack's own wording (pack_compile.py's `terms`).
PRODUCER_TERMS_LINE = (
    "The same block carries the pack's own check questions and criterion wording, which no "
    "signed record covers either. This page does not show them: its checks, criteria and "
    "wording are read from the sealed claims and reports, or marked as not stated."
)

# The renderer's limits on a producer_note (outcome-report-presentation.ts): a note
# outside them is dropped whole, so a wired note must stay inside them.
MAX_NOTE_LINES = 12
MAX_NOTE_LINE = 600
MAX_NOTE_TITLE = 120


class WireError(ValueError):
    pass


def wire(bundle, presentation):
    """Pure: (a new bundle with the block on its extensions, the template key,
    the card that renders it). An outcome-report/v1 block gets the producer_note
    that labels it (see producer_note); any other block is copied verbatim.
    Neither argument is modified."""
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
    block = copy.deepcopy(block)
    if template in NOTE_TEMPLATES:
        block["producer_note"] = producer_note(block)
    wired = copy.deepcopy(bundle)
    wired.setdefault("extensions", {})[template] = block
    return wired, template, CARD_FOR_TEMPLATE[template]


def _note_text(value, limit):
    return isinstance(value, str) and value.strip() != "" and len(value) <= limit


def producer_note(block):
    """The producer_note to wire onto an outcome-report/v1 block: the block's
    own note (if any) with this module's lines appended, or a new one. Refuses
    a note the renderer would drop whole, rather than leave the page unlabelled."""
    lines = list(PRODUCER_NOTE_LINES)
    if "terms" in block or "reason_codes" in block:
        lines.append(PRODUCER_TERMS_LINE)
    existing = block.get("producer_note")
    if existing is None:
        return {"title": PRODUCER_NOTE_TITLE, "lines": lines}
    if not isinstance(existing, dict) or not isinstance(existing.get("lines"), list):
        raise WireError("the block's producer_note is not an object with a lines list")
    title = existing.get("title", PRODUCER_NOTE_TITLE)
    merged = list(existing["lines"]) + lines
    if not _note_text(title, MAX_NOTE_TITLE) or len(merged) > MAX_NOTE_LINES \
            or not all(_note_text(line, MAX_NOTE_LINE) for line in merged):
        raise WireError(f"the block's producer_note, with the {len(lines)} line(s) this adds, is outside the "
                        f"renderer's limits ({MAX_NOTE_LINES} lines of 1-{MAX_NOTE_LINE} characters, a title "
                        f"of 1-{MAX_NOTE_TITLE}); the renderer would drop it and leave the page unlabelled")
    return {"title": title, "lines": merged}


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
