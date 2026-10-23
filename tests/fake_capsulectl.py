#!/usr/bin/env python3
"""A stand-in for the three read verbs scripts/rollup_day.py calls -- `judge pin`,
`cll list` and `get` -- over a book held in one JSON file (FAKE_CAPSULECTL_BOOK:
a list of {"capsule_id", "appended_at", "payload"}). Lets a test run
rollup_day.main() end to end without building capsulectl. It seals nothing and
verifies nothing; `judge pin` is SHA-256 over the pin input's sorted-key JSON,
not capsulectl's own JSON-DIGEST, so a digest from here is only comparable with
another digest from here.
"""
import hashlib
import json
import os
import sys


def main(argv):
    with open(os.environ["FAKE_CAPSULECTL_BOOK"]) as f:
        book = json.load(f)
    verb = argv[:2]
    opts = dict(zip(argv[2::2], argv[3::2]))
    if verb == ["judge", "pin"]:
        with open(argv[2]) as f:
            pin = json.load(f)
        print(json.dumps({"judge_pin_digest": hashlib.sha256(json.dumps(pin, sort_keys=True).encode()).hexdigest()}))
        return 0
    if verb == ["cll", "list"]:
        after, limit = int(opts.get("--after", 0)), int(opts.get("--limit", 1000))
        page = book[after:after + limit]
        entries = [{"capsule_id": e["capsule_id"], "appended_at": e["appended_at"]} for e in page]
        print(json.dumps({"entries": entries, "next_after": after + len(page)}))
        return 0
    if argv[:1] == ["get"]:
        args = dict(zip(argv[1::2], argv[2::2]))
        for e in book:
            if e["capsule_id"] == args.get("--capsule-id"):
                print(json.dumps({"artifacts": [{"name": "payload", "content": e["payload"]}]}))
                return 0
        print(f"no capsule {args.get('--capsule-id')!r}", file=sys.stderr)
        return 1
    print(f"fake capsulectl: unsupported verb {argv!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
