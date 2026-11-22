#!/usr/bin/env python3
"""Check an aac.wording-pack/v0 file and its pinned digest before report.sh hands it to capsulectl.

    wording_pack.py check --pack FILE --digest SHA256

`capsulectl book report build --wording` refuses a digest that does not match the
pack's bytes, but report.sh writes the Result, a checkpoint and a bundle into the
book before it builds the page, so a bad pack is refused here first, with nothing
written. It checks only what makes a pack unusable (agent-action-capsule's
spec/presentation-contract-v0.md section 7.4): the digest is the lowercase hex
SHA-256 of the exact bytes; the pack is a JSON object with
wording_pack_version "aac.wording-pack/v0", an id, a locale (a language tag such as "en"
or "en-US") and an `entries` object of non-empty strings under lowercase keys. The page's own rules (placeholders, distinct verdict words)
are the viewer's, and a pack failing them is dropped there and shows default
words, so the committed pack's own test checks them (tests/test_report_wording.py).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys
import unicodedata

VERSION = "aac.wording-pack/v0"
# capsule-viewer ts/src/contract-report-wording.ts readWordingPack: the same shape, key and
# reserved-prefix rules, so a pack the viewer would refuse at load is refused here first.
KEY = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
LOCALE = re.compile(r"^[A-Za-z]{2,8}(-[A-Za-z0-9]{1,8})*$")
MEMBERS = {"wording_pack_version", "id", "locale", "entries"}


class PackError(Exception):
    pass


# The viewer's INVISIBLE is [\p{Cf}\p{Default_Ignorable_Code_Point}]. Python has no property for the
# second, so its code points outside Cf are listed (Unicode DerivedCoreProperties).
_DEFAULT_IGNORABLE = (
    (0x034F, 0x034F), (0x115F, 0x1160), (0x17B4, 0x17B5), (0x180B, 0x180F), (0x2065, 0x2065), (0x3164, 0x3164),
    (0xFE00, 0xFE0F), (0xFFA0, 0xFFA0), (0xFFF0, 0xFFF8), (0xE0000, 0xE0FFF),
)


def invisible(text):
    """Bidi and other format controls, and default-ignorable code points: refused, as the viewer does."""
    return any(unicodedata.category(c) == "Cf" or any(lo <= ord(c) <= hi for lo, hi in _DEFAULT_IGNORABLE)
               for c in text)


def sha256_of(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def check(path, digest):
    """Return the parsed pack, or raise PackError saying what is wrong."""
    path = pathlib.Path(path)
    try:
        raw = path.read_bytes()
    except OSError as e:
        raise PackError(f"cannot read the wording pack: {e}")
    if digest != digest.lower() or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise PackError("--wording-digest must be 64 lowercase hex characters (the SHA-256 of the pack's bytes)")
    actual = hashlib.sha256(raw).hexdigest()
    if actual != digest:
        raise PackError(f"{path} hashes to {actual}, not the pinned {digest}")
    try:
        pack = json.loads(raw)
    except json.JSONDecodeError as e:
        raise PackError(f"{path} is not JSON: {e}")
    if not isinstance(pack, dict) or pack.get("wording_pack_version") != VERSION or set(pack) - MEMBERS:
        raise PackError(f"{path} is not an {VERSION} pack (members: {sorted(MEMBERS)} and nothing else)")
    if not isinstance(pack.get("id"), str) or not pack["id"] or invisible(pack["id"]) \
            or not isinstance(pack.get("locale"), str) or not LOCALE.match(pack["locale"]):
        raise PackError(f"{path} needs an id (no invisible format characters) and a locale such as \"en\"")
    entries = pack.get("entries")
    if not isinstance(entries, dict) or not entries \
            or not all(isinstance(v, str) and v for v in entries.values()) \
            or not all(KEY.match(k) for k in entries):
        raise PackError(f"{path} needs an `entries` object of non-empty strings under lowercase keys")
    hidden = sorted(k for k, v in entries.items() if invisible(v))
    if hidden:
        raise PackError(f"{path}: {hidden[0]!r} carries a bidi or other invisible format character; the page refuses such a pack")
    reserved = sorted(k for k in entries if k.startswith("core."))
    if reserved:
        raise PackError(f"{path} carries the reserved key {reserved[0]!r}: `core.` is the core's own text")
    return pack


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["check"])
    ap.add_argument("--pack", required=True)
    ap.add_argument("--digest", required=True)
    args = ap.parse_args(argv)
    try:
        pack = check(args.pack, args.digest)
    except PackError as e:
        print(f"wording_pack.py: {e}", file=sys.stderr)
        return 1
    print(json.dumps({"id": pack["id"], "entries": len(pack["entries"]), "sha256": args.digest}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
