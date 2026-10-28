#!/usr/bin/env python3
"""Check a grade-1 narration (evidencebook-report skill) before the person sees it.

A narration is the agent's own prose over records it has verified. This checks
the rules that make it safe, against the very records it cites:

  - it is labelled "narrated by your agent, from your records" on its first or
    last line;
  - it cites at least one record, as [RECORD_ID], and every id it cites is one
    of the --record files it was given (records the agent fetched and verified);
  - every number it states is read, not computed: the number appears in a
    record cited in the same sentence;
  - it shows no percentage;
  - when it states a number, it ends by offering the sealed version, once.

    narration_check.py --narration ANSWER.txt \\
        --record RESULT_ID=result.json --record DEAL_ID=deal.json

Exit 0 and {"ok": true} when every rule holds; exit 1 and the findings
otherwise. It seals nothing: a narration is not a consequential action.
"""
import argparse
import json
import pathlib
import re
import sys

LABEL = "narrated by your agent, from your records"
OFFER = ("Tell me if you'd like an EvidenceBook version of this: sealed, checked, "
         "and the same page anyone can verify.")

CITATION = re.compile(r"\[([A-Za-z0-9][A-Za-z0-9:._-]*)\]")
NUMBER = re.compile(r"\d+(?:\.\d+)?")
# A sentence ends at . ! or ? followed by space, or at a line end, so "3.5" and
# a dotted record id stay whole.
SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n")
PERCENT = re.compile(r"%|\bper ?cent\b", re.IGNORECASE)
# Inside a record's strings, only a number standing on its own counts (a date,
# a period, a count written out), and a digest, key or signature counts for
# nothing: their digit runs would otherwise "hold" almost any small number.
STANDALONE_NUMBER = re.compile(r"(?<![A-Za-z0-9])\d+(?:\.\d+)?(?![A-Za-z0-9])")
OPAQUE = re.compile(r"[A-Za-z0-9+/=_:-]{24,}")


def numbers_in(value, out):
    """Every number a record holds: numeric values, and the standalone numbers
    in its strings (a date or a period reads as the numbers it is written with)."""
    if isinstance(value, bool):
        return out
    if isinstance(value, (int, float)):
        out.add(canonical(repr(value)))
    elif isinstance(value, str):
        if not OPAQUE.fullmatch(value):
            out.update(canonical(n) for n in STANDALONE_NUMBER.findall(value))
    elif isinstance(value, dict):
        for k, v in value.items():
            numbers_in(k, out)
            numbers_in(v, out)
    elif isinstance(value, list):
        for v in value:
            numbers_in(v, out)
    return out


def canonical(token):
    """'03' and '3' and '3.0' are the same number."""
    n = float(token)
    return str(int(n)) if n.is_integer() else repr(n)


def check(text, records):
    """Findings (strings) for a narration `text` over `records` {id: parsed JSON}."""
    findings = []
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    if not lines or not any(LABEL in l.lower() for l in (lines[0], lines[-1])):
        findings.append(f'not labelled: the first or last line must say "{LABEL}"')

    cited = CITATION.findall(text)
    if not cited:
        findings.append("cites no record: every statement names the record ids it rests on")
    for rid in sorted(set(cited) - set(records)):
        findings.append(f"cites [{rid}], a record it was not given as verified")

    if PERCENT.search(text):
        findings.append("shows a percentage")

    held = {rid: numbers_in(doc, set()) for rid, doc in records.items()}
    stated = False
    offer_at = text.find(OFFER)
    for sentence in SENTENCE_END.split(text):
        if OFFER in sentence or LABEL in sentence.lower():
            continue
        ids = [rid for rid in CITATION.findall(sentence) if rid in held]
        prose = CITATION.sub(" ", sentence)
        for token in NUMBER.findall(prose):
            stated = True
            if not any(canonical(token) in held[rid] for rid in ids):
                where = ", ".join(ids) if ids else "no record cited in that sentence"
                findings.append(f"states {token} without reading it from a cited record ({where}): "
                                f"{sentence.strip()!r}")
    if stated and offer_at < 0:
        findings.append(f'states a number but does not offer the sealed version: "{OFFER}"')
    if text.count(OFFER) > 1:
        findings.append("offers the sealed version more than once")
    return findings


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--narration", required=True, type=pathlib.Path)
    ap.add_argument("--record", action="append", default=[], metavar="ID=FILE")
    args = ap.parse_args(argv)
    records = {}
    for spec in args.record:
        rid, sep, path = spec.partition("=")
        if not sep or not rid or not path:
            ap.error(f"--record wants ID=FILE, not {spec!r}")
        records[rid] = json.loads(pathlib.Path(path).read_text())
    findings = check(args.narration.read_text(), records)
    print(json.dumps({"ok": not findings, "findings": findings}, indent=2))
    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())
