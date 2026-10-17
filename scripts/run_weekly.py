#!/usr/bin/env python3
"""Exercise script for skills/weekly-blind-expert: run one week, end to end.

It performs the skill's steps in order and calls only the verbs the skill lists:
cll list, get, verify, publish, calibration summarize, close. It pauses for the
human: without --ratings it seals the sample manifest, writes the blind packets,
and stops (exit 3). With --ratings it seals one human-rating per rated case, the
calibration summary (agreement as k of n, nothing else) and the week's Close. It
never fills in a rating and reports any shortfall against the drawn sample.

    run_weekly.py --profile tau2 --spec demo/tau2/compiled.json --date 2026-09-16 --out RUN_DIR
    run_weekly.py ... --ratings RATINGS.json
"""

import argparse
import datetime
import hashlib
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from capsulectl_calls import (EvidenceUnavailable, list_capsules, payload, publish,  # noqa: E402
                              run, seal_request, verify)
from run_daily import DEFAULT_REFERENCE_FILES, judge_reference_files  # noqa: E402
from skill_record import emit_skill_action, json_digest, skill_action_record  # noqa: E402

SAMPLING_RULE = ("per stratum, order by hex(SHA-256(u32be(len(seed)) || seed || report_capsule_id)), "
                 "ties by capsule id, take the first n (docs/calibration-sampling-spec.md)")


# The only fields a blind packet may carry. Anything not listed here -- the
# verdict, rationale, axis judgments, stratum, report id -- never reaches the
# reviewer.
PACKET_FIELDS = ("case_id", "clause", "agent_interaction", "policy", "booking_db")


def blind_packet(report, case, reference_files=None):
    """The packet a reviewer sees for one sampled report: the case and the
    evidence the judge had, built field by field from PACKET_FIELDS.
    `reference_files` is the contract's own repo-relative {"policy",
    "booking_db"} (compiled judge.reference_files), default tau2 airline's --
    the same files scripts/run_daily.py sent the judge."""
    files = reference_files or DEFAULT_REFERENCE_FILES
    packet = {"case_id": report["case_id"], "clause": report["clause_id"],
              "agent_interaction": case["agent_interaction"],
              "policy": files["policy"], "booking_db": files["booking_db"]}
    assert tuple(packet) == PACKET_FIELDS
    return packet


def checked_ratings(ratings, sampled_case_ids):
    """The human's ratings, refused unless each names a sampled case exactly
    once: a rating outside the sample, or a second rating for one case, would
    make rated exceed drawn and the shortfall go negative."""
    seen = set()
    for r in ratings:
        case_id = r.get("case_id")
        if case_id not in sampled_case_ids:
            raise ValueError(f"rating for a case outside the sample: {case_id!r}")
        if case_id in seen:
            raise ValueError(f"more than one rating for case {case_id!r}")
        if r.get("rating") not in {"met", "not_met", "not_evaluable"}:
            raise ValueError(f"rating for {case_id!r} is not met, not_met or not_evaluable")
        seen.add(case_id)
    return ratings


def sample_key(seed, capsule_id):
    s = seed.encode()
    return hashlib.sha256(len(s).to_bytes(4, "big") + s + capsule_id.encode()).hexdigest(), capsule_id


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--spec", required=True, type=pathlib.Path)
    ap.add_argument("--date", required=True, help="any day in the week, YYYY-MM-DD (UTC; weeks start Monday)")
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("--ratings", type=pathlib.Path, help="the human's blind ratings: [{case_id, rating}]")
    ap.add_argument("--capsulectl", default="capsulectl")
    args = ap.parse_args(argv)

    spec = json.loads(args.spec.read_text())
    reference_files = (spec.get("judge") or {}).get("reference_files")
    if reference_files is not None:
        try:  # the same containment rules run_daily.py applied before judging
            judge_reference_files(spec, args.spec.resolve().parents[2])
        except EvidenceUnavailable as e:
            print(json.dumps({"skill": "weekly-blind-expert", "evidence_unavailable": str(e)}, indent=2))
            return 2
    day = datetime.date.fromisoformat(args.date)
    monday = day - datetime.timedelta(days=day.weekday())
    week_days = {str(monday + datetime.timedelta(days=i)) for i in range(7)}
    year, week, _ = monday.isocalendar()
    week_key = f"week:{year:04d}-W{week:02d}"
    out = args.out / week_key.replace(":", "-")
    # The packets directory is a sibling of the run directory, never inside it:
    # the run directory holds the raw report capsules, verdicts included. A
    # reviewer is given the packets directory and nothing else.
    work, packets = out / "work", args.out / (week_key.replace(":", "-") + "-blind-packets")
    work.mkdir(parents=True, exist_ok=True)
    packets.mkdir(exist_ok=True)
    ctl, profile = args.capsulectl, args.profile
    operator = run(ctl, "profile", "show", profile)["Operator"]
    stamp = f"{monday + datetime.timedelta(days=6)}T23:59:59Z"
    log = {"skill": "weekly-blind-expert", "week": week_key, "profile": profile}
    actions = log["actions"] = []

    def action(name, **fields):
        """Seal one skill action of this run (scripts/skill_record.py, skill-action/v1)."""
        actions.append(emit_skill_action(ctl, profile, work, operator, stamp,
                                         skill_action_record("weekly-blind-expert", name, **fields)))

    try:
        # 1. The week's evaluation reports, authenticated before sampling.
        reports = []
        for entry in list_capsules(ctl, profile):
            body = payload(ctl, profile, entry["capsule_id"])
            if not (isinstance(body, dict) and body.get("record_type") == "evaluation-report/v1"):
                continue
            if body.get("period", "").removeprefix("day:") not in week_days:
                continue
            verify(ctl, profile, entry["capsule_id"], work)
            reports.append((entry["capsule_id"], body))
        log["frame"] = len(reports)
        action("read-frame", output_digest=json_digest(sorted(rid for rid, _ in reports)))

        # 2. Draw the sample and seal the manifest before anyone sees a case.
        policy = spec["sample_policy"]
        strata = {}
        for rid, body in reports:
            strata.setdefault(body[policy["stratify_by"]], []).append((rid, body))
        selected = []
        for name in sorted(strata):
            ranked = sorted(strata[name], key=lambda rb: sample_key(policy["seed"], rb[0]))
            selected.extend(ranked[:policy["per_stratum"]])
        manifest = {"record_type": "sample-manifest/v1", "epistemic_type": "derived_metric",
                    "contract": spec["contract"], "period": week_key, "frame_size": len(reports),
                    "strata": {k: len(v) for k, v in sorted(strata.items())}, "seed": policy["seed"],
                    "rule": SAMPLING_RULE, "selected": [rid for rid, _ in selected]}
        manifest_id = publish(ctl, profile, seal_request(
            f"urn:evidencebook-skills:sample-manifest:{spec['contract']}:{week_key}", operator,
            "evidencebook-skills/weekly-blind-expert", stamp, manifest), work, "sample-manifest")
        log["sample_manifest"] = manifest_id
        log["drawn"] = len(selected)

        # 3. Blind packets: the case and the evidence the judge had; never the
        #    verdict, rationale, axis judgments, stratum or report id.
        by_case, written = {}, {}
        for rid, body in selected:
            case = payload(ctl, profile, body["source_capsule_id"])
            packet = blind_packet(body, case, reference_files)
            name = body["case_id"].replace(":", "_")
            (packets / f"{name}.json").write_text(json.dumps(packet, indent=2))
            by_case[body["case_id"]] = (rid, body)
            written[name] = packet
        # What the reviewer is shown, as a digest: the disclosure itself is a skill action.
        action("blind-packets", inputs=[("sample_manifest", manifest_id)], output_digest=json_digest(written))

        if args.ratings is None:
            log["status"] = f"awaiting the human's blind ratings for {len(selected)} case(s) in {packets}"
            print(json.dumps(log, indent=2))
            return 3

        # 4. The human's ratings, one record each, chained to the report audited.
        try:
            ratings = checked_ratings(json.loads(args.ratings.read_text()), set(by_case))
        except ValueError as e:
            raise EvidenceUnavailable(f"ratings refused: {e}") from e
        rated = []
        for r in ratings:
            rid, body = by_case[r["case_id"]]
            record = {"record_type": "human-rating/v1", "epistemic_type": "human_report", "blind": True,
                      "case_id": r["case_id"], "rating": r["rating"], "audits": rid,
                      "sample_manifest": manifest_id, "period": week_key}
            publish(ctl, profile, seal_request(
                f"urn:evidencebook-skills:human-rating:{r['case_id']}:{week_key}", operator,
                "evidencebook-skills/weekly-blind-expert", stamp, record), work, f"rating-{rid[:16]}")
            rated.append({"case_id": r["case_id"], "rating": r["rating"]})
        log["rated"] = len(rated)
        log["shortfall"] = len(selected) - len(rated)

        # 5. Agreement as k of n over the drawn sample; nothing else.
        (work / "sampled-reports.json").write_text(json.dumps(
            [{"case_id": b["case_id"], "judge_pin_digest": b["judge_pin_digest"], "verdict": b["verdict"]} for _, b in selected]))
        (work / "ratings.json").write_text(json.dumps(rated))
        summary = run(ctl, "calibration", "summarize", str(work / "sampled-reports.json"), str(work / "ratings.json"))
        calibration = {"record_type": "calibration-summary/v1", "epistemic_type": "derived_metric",
                       "contract": spec["contract"], "period": week_key, "sample_manifest": manifest_id,
                       "drawn": len(selected), "rated": len(rated), "shortfall": len(selected) - len(rated),
                       "pins": summary["pins"]}
        log["calibration_summary"] = publish(ctl, profile, seal_request(
            f"urn:evidencebook-skills:calibration-summary:{spec['contract']}:{week_key}", operator,
            "evidencebook-skills/weekly-blind-expert", stamp, calibration), work, "calibration-summary")
        log["agreement"] = [{"judge_pin_digest": p["judge_pin_digest"], "k": p["agreement_count"], "n": p["rated_count"]}
                            for p in summary["pins"]]

        # 6. The week's Close; unilateral, no peer bundle is held.
        close_args = ["close", "--profile", profile, "--period", "week", "--date", str(day),
                      "--counterparty", spec["counterparty"]]
        capsule_out, bundle_out = out / "close.json", out / "close-bundle.json"
        if not capsule_out.exists():
            close_args += ["--capsule-out", str(capsule_out), "--bundle-out", str(bundle_out)]
        closed = run(ctl, *close_args)
        log["close"] = {"record_id": closed["record_id"], "already_closed": closed["already_closed"],
                        "unilateral": not closed.get("peer_bundle"),
                        "window": [closed["reconciliation"]["from_seq"], closed["reconciliation"]["to_seq"]],
                        "capsule": str(capsule_out), "bundle": str(bundle_out)}
    except EvidenceUnavailable as e:
        log["evidence_unavailable"] = str(e)
        print(json.dumps(log, indent=2))
        return 2
    (out / "run.json").write_text(json.dumps(log, indent=2))
    print(json.dumps(log, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
