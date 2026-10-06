#!/usr/bin/env python3
"""Thin CLI wrapper over scripts/result_v0.merge_result_v0_documents: `report
build` takes exactly one sealed Result as its bundle's root, so a --date/--to
range that produced one result-v0-<day>.json per day (either path --
scripts/rollup_day.py or scripts/report_spec.py) needs them combined into one
document before scripts/report.sh's "result build" step. A single input file
is accepted too (the common one-day case) -- it passes through in the same
shape merge_result_v0_documents always produces (claims/aggregate recomputed
from the one document's own claims, not copied verbatim), so a caller never
needs to branch on "one day vs many."

    python3 scripts/merge_results.py --title "..." --generated-at RFC3339 \\
        --out result-v0-merged.json INPUT1.json [INPUT2.json ...]
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from result_v0 import merge_result_v0_documents  # noqa: E402
from rollup import RollupError  # noqa: E402


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--title", required=True)
    ap.add_argument("--generated-at", required=True)
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("inputs", nargs="+", type=pathlib.Path)
    args = ap.parse_args(argv)

    docs = [json.loads(p.read_text()) for p in args.inputs]
    try:
        merged = merge_result_v0_documents(docs, args.title, args.generated_at)
    except RollupError as e:
        print(json.dumps({"error": str(e)}, indent=2))
        return 2
    args.out.write_text(json.dumps(merged, indent=2))
    summary = {"out": str(args.out), "claims": len(merged["claims"]), "inputs": len(docs)}
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
