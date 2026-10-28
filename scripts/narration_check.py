#!/usr/bin/env python3
"""Check a grade-1 narration (evidencebook-report skill) before the person sees it.

A narration is the agent's own prose over records it has verified. This checks
the rules that make it safe, against the very records it cites:

  - it is labelled "narrated by your agent, from your records" on its first or
    last line;
  - every statement cites the records it rests on, as [RECORD_ID], and every
    id it cites is one of the --record files it was given (records the agent
    fetched and verified); only the label and the offer stand without one;
  - every number it states is read, not computed: the number appears in a
    record cited in the same sentence. Numbers are written as digits ("1,000"
    reads as one thousand), so a spelled-out number ("three") is a finding;
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
# A grouped number ("1,000") is read whole; anything else is a digit run.
NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
# Written-out numbers the check cannot read. "one" is left out: "no one" and
# "every one" are not counts, and the skill says to write numbers as digits.
NUMBER_WORD = re.compile(r"\b(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|"
                         r"fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|"
                         r"fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|billion|dozen)\b",
                         re.IGNORECASE)
# A sentence ends at . ! or ? followed by space, or at a line end, so "3.5" and
# a dotted record id stay whole.
SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n")
PERCENT = re.compile(r"%|\bper ?cent\b", re.IGNORECASE)
LABEL_TEXT = re.compile(re.escape(LABEL), re.IGNORECASE)
# A digest or a key or signature encoding holds no number: its digit runs would
# otherwise "hold" almost any small number. A date, a time or a claim id (they
# carry "-" and ":") is read for the numbers it is written with.
OPAQUE = re.compile(r"(?:sha256:)?[0-9a-fA-F]{16,}|[A-Za-z0-9+/_=-]{40,}")


def numbers_in(value, out):
    """Every number a record holds: numeric values, and the numbers written in
    its strings, apart from digests and encoded keys or signatures."""
    if isinstance(value, bool):
        return out
    if isinstance(value, (int, float)):
        out.add(canonical(repr(value)))
    elif isinstance(value, str):
        if not OPAQUE.fullmatch(value):
            out.update(canonical(n) for n in NUMBER.findall(value))
    elif isinstance(value, dict):
        for k, v in value.items():
            numbers_in(k, out)
            numbers_in(v, out)
    elif isinstance(value, list):
        for v in value:
            numbers_in(v, out)
    return out


def canonical(token):
    """'03', '3' and '3.0' are the same number, and so are '1,000' and '1000'."""
    n = float(token.replace(",", ""))
    return str(int(n)) if n.is_integer() else repr(n)


def check(text, records):
    """Findings (strings) for a narration `text` over `records` {id: parsed JSON}."""
    findings = []
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    if not lines or not any(LABEL in l.lower() for l in (lines[0], lines[-1])):
        findings.append(f'not labelled: the first or last line must say "{LABEL}"')

    cited = CITATION.findall(text)
    for rid in sorted(set(cited) - set(records)):
        findings.append(f"cites [{rid}], a record it was not given as verified")

    if PERCENT.search(text):
        findings.append("shows a percentage")

    held = {rid: numbers_in(doc, set()) for rid, doc in records.items()}
    stated = False
    for sentence in SENTENCE_END.split(text):
        # The label and the offer are the skill's fixed words; whatever else
        # shares their sentence is checked like any other statement.
        rest = LABEL_TEXT.sub(" ", sentence.replace(OFFER, " "))
        if not re.search(r"[A-Za-z0-9]", CITATION.sub(" ", rest)):
            continue
        quoted = repr(sentence.strip())
        ids = [rid for rid in CITATION.findall(rest) if rid in held]
        if not ids:
            findings.append(f"cites no verified record for this statement: {quoted}")
        prose = CITATION.sub(" ", rest)
        for word in NUMBER_WORD.findall(prose):
            stated = True
            findings.append(f"writes the number {word!r} as a word; write it as digits so it can be checked: {quoted}")
        for token in NUMBER.findall(prose):
            stated = True
            if not any(canonical(token) in held[rid] for rid in ids):
                where = ", ".join(ids) if ids else "no record cited in that sentence"
                findings.append(f"states {token} without reading it from a cited record ({where}): {quoted}")
    if stated and OFFER not in text:
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
