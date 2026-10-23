#!/usr/bin/env python3
"""Thin CLI wrapper over scripts/result_v0.merge_result_v0_documents: `capsulectl
book report build` takes exactly one sealed Result as its bundle's root, so a --date/--to
range that produced one result-v0-<day>.json per day (either path --
scripts/rollup_day.py or scripts/report_spec.py) needs them combined into one
document before scripts/report.sh's "book result build" step. A single input file
is accepted too (the common one-day case) -- it passes through in the same
shape merge_result_v0_documents always produces (claims/aggregate recomputed
from the one document's own claims, not copied verbatim), so a caller never
needs to branch on "one day vs many."

    python3 scripts/merge_results.py --title "..." --generated-at RFC3339 \\
        --out result-v0-merged.json INPUT1.json [INPUT2.json ...]

or, instead of --title, `--spec SPEC --period "2026-10-01 to 2026-10-03"`: the
title is then composed here by result_v0.report_title from the spec's own name,
so a caller (scripts/report.sh) passes only ASCII arguments and never has to
carry the title's non-ASCII separator through the shell's locale.
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import yaml  # noqa: E402

from result_v0 import merge_result_v0_documents, report_title  # noqa: E402
from rollup import RollupError  # noqa: E402


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--title")
    ap.add_argument("--spec", type=pathlib.Path, help="compose the title from this spec's name (with --period)")
    ap.add_argument("--period", help="what the merged Result covers, e.g. '2026-10-01 to 2026-10-03'")
    ap.add_argument("--generated-at", required=True)
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("inputs", nargs="+", type=pathlib.Path)
    args = ap.parse_args(argv)
    if (args.title is None) == (args.spec is None) or (args.spec is None) != (args.period is None):
        ap.error("give either --title, or --spec with --period")
    # yaml.safe_load also reads a compiled pack's JSON.
    title = args.title if args.title is not None else report_title(yaml.safe_load(args.spec.read_text()), args.period)

    docs = [json.loads(p.read_text()) for p in args.inputs]
    try:
        merged = merge_result_v0_documents(docs, title, args.generated_at)
    except RollupError as e:
        print(json.dumps({"error": str(e)}, indent=2))
        return 2
    args.out.write_text(json.dumps(merged, indent=2))
    summary = {"out": str(args.out), "claims": len(merged["claims"]), "inputs": len(docs)}
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
