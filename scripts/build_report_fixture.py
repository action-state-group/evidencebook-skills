#!/usr/bin/env python3
"""Turn a real rollup_day.py day-level Result v0 document (scripts/result_v0.py's
build_result_v0_for_day, run against a tests/fresh_env_outcomes.sh book) into the
unsealed evidence-bundle source shape an outcome-report renderer's test fixture is
sealed from. It writes no invented data: every claim, verdict, rationale, case id
and judge_pin_digest in the output is read back from the evaluation-report/v1
capsules the run sealed, by capsule_id, via capsulectl_calls.payload().

    python3 scripts/build_report_fixture.py --profile tau2 --capsulectl CTL \\
        --result-v0 RUN_DIR/rollup/result-v0-2026-09-23.json --out OUT.json

The bundle's outcome-report/v1 extension carries presentation settings only
(percentages); it carries no price, amount or currency. Not part of any skill: a
bridge from this repo's output to a renderer's fixture format, run by hand.
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from capsulectl_calls import payload  # noqa: E402


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--capsulectl", default="capsulectl")
    ap.add_argument("--result-v0", required=True, type=pathlib.Path)
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("--percentages", action="store_true")
    args = ap.parse_args(argv)

    result_doc = json.loads(args.result_v0.read_text())
    claims = result_doc["claims"]

    digests = sorted({c["evidence"][0]["digest"] for c in claims if c["evidence"]})
    print(f"fetching {len(digests)} real evaluation-report/v1 bodies via capsulectl...", file=sys.stderr)
    disclosures = {"result": {"agent_input": result_doc}}
    records = [{"capsule_id": "result",
                "references": [{"type": "agent-action-capsule", "citation_purpose": "acted_on", "digest": d}
                                for d in digests]}]
    for i, digest in enumerate(digests):
        body = payload(args.capsulectl, args.profile, digest)
        disclosures[digest] = {"agent_input": body}
        records.append({"capsule_id": digest})
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(digests)}", file=sys.stderr)

    bundle = {
        "root": "result",
        "extensions": {
            "outcome-report/v1": {
                "enabled": True,
                "percentages": args.percentages,
            },
        },
        "records": records,
        "disclosures": disclosures,
    }
    args.out.write_text(json.dumps(bundle, indent=2) + "\n")
    met = len(result_doc["aggregate"]["buckets"]["met"])
    not_met = len(result_doc["aggregate"]["buckets"]["not_met"])
    not_evaluable = len(result_doc["aggregate"]["buckets"]["not_evaluable"])
    print(f"wrote {args.out}: {len(claims)} claims over {len(digests)} real reports "
          f"(met {met}, not_met {not_met}, not_evaluable {not_evaluable})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
