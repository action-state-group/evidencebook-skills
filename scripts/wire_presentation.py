#!/usr/bin/env python3
"""Wire a compiled pack's presentation.json into a disclosed Evidence Bundle.

    wire_presentation.py seal --presentation presentation.json --result result-v0.json --out result-v0-sealed.json
    wire_presentation.py --bundle bundle.json --presentation presentation.json \
        [--sealed-result result-v0-sealed.json] --out wired.json
    wire_presentation.py label --bundle wired.json

scripts/pack_compile.py writes a presentation.json beside every compiled.json:
exactly one template block, keyed by the pack's report template (REPORT_TEMPLATES
there), plus, for the packs in CONTRACT_REPORT_PACKS, the empty
"contract-report/v1": {} opt-in beside it (agent-action-capsule
spec/contract-report-v1.md section 1), copied onto `extensions` as-is.
The report renderer (capsulectl book report build, agent-action-capsule's
built-in manifests) picks its view by that same key on the bundle's `extensions`:

  outcome-report/v1        -> the outcome card      (--card outcome)
  eu-ai-act-compliance/v1  -> the obligation card   (--card obligation)

This copies the block onto `bundle.extensions` and prints the card it selects.
The block is the producer's own mapping (check questions, criterion labels and
wording; on the EU card, article, title, plain-language summary, applicability
and method). It is added after `capsulectl disclose` has written the bundle, so
the block itself rides OUTSIDE the signed records. Without `seal` (below) no
record's digest covers it and nothing on the page should read as if one did;
with it, the signed Result pins the block's digest, and the words are still
presentation, never evidence.

So the page says so, through a channel the renderer already labels:

  - outcome-report/v1: the renderer draws only the block's display settings
    (`percentages`) and its `producer_note`, under its own fixed label
    ("Producer's note · presentation text, not evidence ... outside the signed
    records"). The card's checks, criteria and wording come from the sealed
    claims and reports, never from the block's `terms`. This module adds a
    `producer_note` (PRODUCER_NOTE_LINES) stating that the block was added by
    the report's producer after disclosure, that no signed record covers it,
    and that the pack's own wording it carries is not what the page shows.
    Sealed (below), the note uses SEALED_NOTE_LINES and SEALED_TERMS_LINE
    instead: the Result's digest covers the whole block, the pack's wording
    included, which is still not evidence and still not drawn on the page. A
    note the block already carries is kept, with these lines appended.
  - eu-ai-act-compliance/v1: the renderer reads no note from this block, and
    it does show the producer's titles and summaries. It labels them itself:
    its header says the article, applicability, method and finding
    recommendations are the producer's mapping outside the signed records, and
    each obligation's detail says "Article, summary and method: the producer's
    mapping, not a sealed record." The block is copied verbatim. (The header
    sentence does not yet name the obligation titles, test names, not-evaluable
    notes or the quality protocol; that wording is the renderer's, not ours.)

Sealing the block's digest (issue #29). Before `capsulectl book result build`,
`seal` computes the block exactly as it will be wired (note included) and pins
its SHA-256 over the block's JCS form in the Result v0 document, as the
document-level extension member

    "x-presentation-digest": {"template": "<key>", "digest_alg": "SHA-256", "digest": "<hex>"}

Result v0 is a closed document: a bare `presentation_digest` would fail
`result build`'s schema check, and spec section 8a admits only `x-` members
(verifiers ignore them, so no verdict or count can depend on it). The sealed
Result is signed by the producer, so the digest ties these exact words to the
producer's signature without adding a record. After `disclose`, wiring with
`--sealed-result` rebuilds the same block and refuses to wire one whose digest
differs from the sealed one. `label` (presentation_label) is the check a page
makes: the block's digest equals the sealed one -> "producer-signed"; it
differs or no digest was sealed -> "unsigned producer text"; no block -> no
label. Verdicts and counts never depend on it: they come from the signed claims.
What the page lets the block control is unchanged (presentation contract
section 6): sealing changes the label, not the wording rule.

Fails closed, never guesses:
  - a presentation.json carrying no block this module knows, or a key it
    doesn't know, is refused (a renamed template would otherwise render as a
    silent fallback page);
  - more than one template block is refused (the compliance view forbids the
    outcome-report extension; one pack compiles to one template). The
    contract-report/v1 opt-in may sit beside the one template block, and must
    be exactly {};
  - a bundle that already carries the extension is refused rather than
    overwritten;
  - an outcome-report/v1 block whose own producer_note would, with the lines
    added here, break the renderer's limits is refused (the renderer drops a
    note over its limits whole, which would leave the page unlabelled).
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import pathlib
import sys

# template key -> the capsulectl book report build --card that renders it
CARD_FOR_TEMPLATE = {
    "outcome-report/v1": "outcome",
    "eu-ai-act-compliance/v1": "obligation",
}

# agent-action-capsule spec/contract-report-v1.md section 1: a producer's opt-in
# to the contract-report view, a closed empty object (scripts/pack_compile.py's
# CONTRACT_REPORT_PACKS). It carries no words, so nothing here digests it: like
# every extension it is covered by the bundle digest (section 1). It sits
# beside the pack's report-template block, which stays because capsule-viewer's
# contract-report module reads its grouping data from that block
# (contractReportInput), until the section 5 migration writes the opt-in in
# its place. No renderer in this repo reads it.
CONTRACT_REPORT_KEY = "contract-report/v1"

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
# Used instead of PRODUCER_TERMS_LINE when the block's digest is sealed: the digest
# covers the whole block, `terms` included, so the line must not say no signed
# record covers them.
SEALED_TERMS_LINE = (
    "The same block carries the pack's own check questions and criterion wording. The sealed "
    "digest covers them too, but they are not evidence, and this page does not draw on them: its "
    "checks, criteria and wording are read from the sealed claims and reports, or marked as not stated."
)

# Used instead of PRODUCER_NOTE_LINES when the block's digest is sealed in the Result.
SEALED_NOTE_LINES = (
    "This report's producer added this note and the page's display settings to the bundle "
    "after it was disclosed. The signed Result pins their SHA-256 digest "
    "(x-presentation-digest), so a reader can check they are the words the producer signed. "
    "They are still not evidence: no verdict or count on this page is computed from them.",
)

# The Result v0 extension member (spec section 8a) that pins the block's digest.
DIGEST_MEMBER = "x-presentation-digest"
DIGEST_ALG = "SHA-256"

# What a page says about the block, by presentation_label's state.
LABEL_SIGNED = "producer-signed"
LABEL_UNSIGNED = "unsigned producer text"

# The renderer's limits on a producer_note (outcome-report-presentation.ts): a note
# outside them is dropped whole, so a wired note must stay inside them.
MAX_NOTE_LINES = 12
MAX_NOTE_LINE = 600
MAX_NOTE_TITLE = 120


class WireError(ValueError):
    pass


def prepare_block(presentation, sealed=False):
    """Pure: (template key, the block exactly as it is wired, the card that
    renders it). An outcome-report/v1 block gets the producer_note that labels
    it (see producer_note; `sealed` picks the lines that name the sealed
    digest); any other block is copied verbatim. A presentation.json may also
    carry CONTRACT_REPORT_KEY beside the one template block (checked here, but
    not returned: its own {} content is never noted, just copied by `wire`
    as-is). The argument is not modified."""
    if not isinstance(presentation, dict) or not presentation:
        raise WireError("presentation.json is empty or not a JSON object")
    known = set(CARD_FOR_TEMPLATE) | {CONTRACT_REPORT_KEY}
    unknown = sorted(set(presentation) - known)
    if unknown:
        raise WireError(f"presentation.json carries block(s) this report does not know: {unknown!r} "
                        f"(known: {sorted(known)!r})")
    if CONTRACT_REPORT_KEY in presentation and presentation[CONTRACT_REPORT_KEY] != {}:
        raise WireError(f"{CONTRACT_REPORT_KEY} must be exactly {{}} (a closed, empty opt-in: no words, "
                        "data or flags)")
    template_items = {k: v for k, v in presentation.items() if k in CARD_FOR_TEMPLATE}
    if len(template_items) != 1:
        raise WireError(f"presentation.json carries {len(template_items)} report-template block(s) "
                        f"{sorted(template_items)!r}; one pack compiles to exactly one")
    (template, block), = template_items.items()
    if not isinstance(block, dict):
        raise WireError(f"{template} block is not a JSON object")
    if block.get("enabled") is not True:
        raise WireError(f"{template} block is not enabled (\"enabled\": true is required)")
    block = copy.deepcopy(block)
    if template in NOTE_TEMPLATES:
        block["producer_note"] = producer_note(block, sealed=sealed)
    return template, block, CARD_FOR_TEMPLATE[template]


def wire(bundle, presentation, sealed_digest=None):
    """Pure: (a new bundle with the block on its extensions, the template key,
    the card that renders it). With `sealed_digest` (the Result's
    x-presentation-digest member), the block is built with the sealed note and
    must hash to that digest, or it is refused. When presentation.json also
    carries CONTRACT_REPORT_KEY, that closed empty object is wired beside the
    template block as-is; it carries nothing to sign, and the bundle digest
    covers it like every extension (section 1). A bundle that already carries
    the opt-in is refused, never overwritten. Neither argument is modified."""
    if not isinstance(bundle, dict):
        raise WireError("bundle is not a JSON object")
    template, block, card = prepare_block(presentation, sealed=sealed_digest is not None)
    extensions = bundle.get("extensions")
    if extensions is not None and not isinstance(extensions, dict):
        raise WireError("bundle.extensions is not a JSON object")
    if extensions and template in extensions:
        raise WireError(f"bundle already carries a {template} extension; refusing to overwrite it")
    if extensions and CONTRACT_REPORT_KEY in extensions:
        raise WireError(f"bundle already carries a {CONTRACT_REPORT_KEY} extension; refusing to overwrite it")
    if sealed_digest is not None and sealed_digest != digest_member(template, block):
        raise WireError(f"the {template} block to wire does not match the digest sealed in the Result "
                        f"({DIGEST_MEMBER}); refusing to wire words the producer did not sign")
    wired = copy.deepcopy(bundle)
    wired.setdefault("extensions", {})[template] = block
    if CONTRACT_REPORT_KEY in presentation:
        wired["extensions"][CONTRACT_REPORT_KEY] = {}
    return wired, template, card


def jcs(value):
    """RFC 8785 JCS bytes for the JSON values a presentation block holds:
    objects, arrays, strings, integers, booleans and null. Keys sort by their
    UTF-16 code units, as RFC 8785 says. A non-integral number is refused
    rather than risk a serialisation that differs from another implementation's."""
    if value is None or isinstance(value, bool):
        return json.dumps(value).encode()
    if isinstance(value, int):
        if abs(value) > 2 ** 53 - 1:
            raise WireError(f"integer {value} is outside the range JCS serialises exactly")
        return str(value).encode()
    if isinstance(value, float):
        if value.is_integer() and abs(value) <= 2 ** 53 - 1:
            return str(int(value)).encode()
        raise WireError(f"non-integral number {value!r} in the presentation block; refusing to digest it")
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False).encode("utf-8")
    if isinstance(value, list):
        return b"[" + b",".join(jcs(v) for v in value) + b"]"
    if isinstance(value, dict):
        if not all(isinstance(k, str) for k in value):
            raise WireError("a presentation block key is not a string")
        keys = sorted(value, key=lambda k: k.encode("utf-16-be"))
        return b"{" + b",".join(jcs(k) + b":" + jcs(value[k]) for k in keys) + b"}"
    raise WireError(f"{type(value).__name__} is not a JSON value")


def block_digest(block):
    """Lowercase hex SHA-256 over the block's JCS form."""
    return hashlib.sha256(jcs(block)).hexdigest()


def digest_member(template, block):
    """The x-presentation-digest member value for this wired block."""
    return {"template": template, "digest_alg": DIGEST_ALG, "digest": block_digest(block)}


def seal(result, presentation):
    """Pure: (a new Result v0 document carrying x-presentation-digest for the
    block exactly as it will be wired, the template key, the card). Run before
    `capsulectl book result build`, so the producer's signature over the
    Result covers the digest. A Result already carrying the member is refused
    rather than overwritten. Neither argument is modified."""
    if not isinstance(result, dict) or result.get("result_version") != "evidence-result-v0":
        raise WireError("the Result is not an evidence-result-v0 document")
    if DIGEST_MEMBER in result:
        raise WireError(f"the Result already carries {DIGEST_MEMBER}; refusing to overwrite it")
    template, block, card = prepare_block(presentation, sealed=True)
    sealed = copy.deepcopy(result)
    sealed[DIGEST_MEMBER] = digest_member(template, block)
    return sealed, template, card


def sealed_result_of(bundle):
    """The Result v0 document at the bundle's root, read the way the report
    viewer reads it (agent-action-capsule ts/docs/result-root.md): the root's
    disclosed agent_output, then agent_input; the document itself (payload
    form) or an evidence_result header's `statement` (book form). None when
    the root discloses no Result."""
    if not isinstance(bundle, dict):
        return None
    disclosed = (bundle.get("disclosures") or {}).get(bundle.get("root"))
    if not isinstance(disclosed, dict):
        return None
    for member in ("agent_output", "agent_input"):
        value = disclosed.get(member)
        if not isinstance(value, dict):
            continue
        if value.get("result_version") == "evidence-result-v0":
            return value
        statement = value.get("statement")
        if value.get("record_type") == "evidence_result" and isinstance(statement, dict) \
                and statement.get("result_version") == "evidence-result-v0":
            return statement
    return None


def presentation_label(bundle):
    """What a page says about the bundle's presentation block, as
    (state, template): state is LABEL_SIGNED when the block on the bundle's
    extensions hashes to the digest the root Result seals for that template,
    LABEL_UNSIGNED when it differs or no digest was sealed, and None (with
    template None) when the bundle carries no known block -- that page renders
    as today, with no label. The Result's signature is the verifier's check,
    not this one: this only compares the block against what the signed Result
    pins. Nothing here touches a verdict or a count."""
    extensions = bundle.get("extensions") if isinstance(bundle, dict) else None
    if not isinstance(extensions, dict):
        return None, None
    present = [t for t in CARD_FOR_TEMPLATE if t in extensions]
    if not present:
        return None, None
    template = present[0]
    result = sealed_result_of(bundle)
    sealed = result.get(DIGEST_MEMBER) if isinstance(result, dict) else None
    block = extensions[template]
    try:
        matches = (isinstance(sealed, dict) and sealed.get("template") == template
                   and sealed.get("digest_alg") == DIGEST_ALG and isinstance(block, dict)
                   and sealed.get("digest") == block_digest(block))
    except WireError:
        matches = False
    return (LABEL_SIGNED if matches else LABEL_UNSIGNED), template


def _note_text(value, limit):
    return isinstance(value, str) and value.strip() != "" and len(value) <= limit


def producer_note(block, sealed=False):
    """The producer_note to wire onto an outcome-report/v1 block: the block's
    own note (if any) with this module's lines appended, or a new one. With
    `sealed`, the first line says the signed Result pins the block's digest,
    and the terms line (when the block carries the pack's wording) says the
    digest covers that wording too, never that no signed record does.
    Refuses a note the renderer would drop whole, rather than leave the page
    unlabelled."""
    lines = list(SEALED_NOTE_LINES if sealed else PRODUCER_NOTE_LINES)
    if "terms" in block or "reason_codes" in block:
        lines.append(SEALED_TERMS_LINE if sealed else PRODUCER_TERMS_LINE)
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


def _read(path):
    return json.loads(pathlib.Path(path).read_text())


def main(argv):
    if argv[:1] == ["seal"]:
        ap = argparse.ArgumentParser(prog="wire_presentation.py seal",
                                     description="pin the block's digest in the Result v0 before result build")
        ap.add_argument("--presentation", required=True, type=pathlib.Path)
        ap.add_argument("--result", required=True, type=pathlib.Path, help="the Result v0 document to seal")
        ap.add_argument("--out", required=True, type=pathlib.Path, help="where to write it, digest added")
        args = ap.parse_args(argv[1:])
        try:
            sealed, template, card = seal(_read(args.result), _read(args.presentation))
        except (OSError, json.JSONDecodeError, WireError) as e:
            print(f"wire_presentation.py seal: {e}", file=sys.stderr)
            return 1
        args.out.write_text(json.dumps(sealed))
        print(json.dumps({"template": template, "card": card, DIGEST_MEMBER: sealed[DIGEST_MEMBER]}))
        return 0
    if argv[:1] == ["label"]:
        ap = argparse.ArgumentParser(prog="wire_presentation.py label",
                                     description="say whether the bundle's block matches the sealed digest")
        ap.add_argument("--bundle", required=True, type=pathlib.Path)
        args = ap.parse_args(argv[1:])
        try:
            state, template = presentation_label(_read(args.bundle))
        except (OSError, json.JSONDecodeError) as e:
            print(f"wire_presentation.py label: {e}", file=sys.stderr)
            return 1
        print(json.dumps({"template": template, "label": state}))
        return 0
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bundle", required=True, type=pathlib.Path, help="the disclosed Evidence Bundle")
    ap.add_argument("--presentation", required=True, type=pathlib.Path,
                    help="the pack's compiled presentation.json")
    ap.add_argument("--sealed-result", type=pathlib.Path,
                    help="the Result v0 `seal` wrote and result build sealed: wire only a block matching its digest")
    ap.add_argument("--out", required=True, type=pathlib.Path, help="where to write the wired bundle")
    args = ap.parse_args(argv)
    try:
        sealed_digest = None
        if args.sealed_result is not None:
            sealed_digest = _read(args.sealed_result).get(DIGEST_MEMBER)
            if sealed_digest is None:
                raise WireError(f"{args.sealed_result} carries no {DIGEST_MEMBER}")
        wired, template, card = wire(_read(args.bundle), _read(args.presentation), sealed_digest=sealed_digest)
    except (OSError, json.JSONDecodeError, AttributeError, WireError) as e:
        print(f"wire_presentation.py: {e}", file=sys.stderr)
        return 1
    args.out.write_text(json.dumps(wired))
    print(json.dumps({"template": template, "card": card}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
