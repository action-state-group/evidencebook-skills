#!/usr/bin/env python3
"""Exercise script for skills/weekly-blind-expert: run one week, end to end.

It performs the skill's steps in order and calls only the verbs the skill lists:
cll list, get, verify, publish, calibration summarize, book close. It pauses for the
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
from calibration_summary import calibration_summaries, disagreement_with_verb  # noqa: E402
from human_rating import counted_cases, human_rating_record  # noqa: E402
from capsulectl_calls import (EvidenceUnavailable, list_capsules, payload, publish,  # noqa: E402
                              run, seal_request, sha256_file, verify)
from clause_report import is_clause_report  # noqa: E402
from rollup_day import safe_filename  # noqa: E402
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


def is_judged(report):
    """Whether a clause-report was judged, so it names the judge pin it can
    be calibrated against. A recomputed report has no judge_pin_digest and is
    not a judge's output: it is never in the calibration frame."""
    return bool(report.get("judge_pin_digest"))


def week_frame(entries, load, check, week_days):
    """The calibration frame: the week's judged clause-reports, each
    authenticated with `check` before it counts, and how many of the week's
    reports were skipped because no judge wrote them (is_judged). Skipped
    reports are not verified."""
    reports, unjudged = [], 0
    for entry in entries:
        body = load(entry["capsule_id"])
        if not is_clause_report(body):
            continue
        if body.get("period", "").removeprefix("day:") not in week_days:
            continue
        if not is_judged(body):
            unjudged += 1
            continue
        reports.append((entry["capsule_id"], body))
    # Re-running a day seals a second capsule when the record's content changed (the clause-report/v1
    # rename did), so one slot can hold the same verdict twice: keep the lexicographically first
    # capsule id, as rollup_day._group does. Different verdicts for one slot both stay.
    first = {}
    for capsule_id, body in reports:
        slot = (body.get("case_id"), body.get("clause_id"), body.get("period"),
                body.get("judge_pin_digest"), body.get("verdict"))
        if slot not in first or capsule_id < first[slot]:
            first[slot] = capsule_id
    reports = [(c, b) for c, b in reports
               if first[(b.get("case_id"), b.get("clause_id"), b.get("period"),
                         b.get("judge_pin_digest"), b.get("verdict"))] == c]
    for capsule_id, _body in reports:
        check(capsule_id)
    return reports, unjudged


def checked_ratings(ratings, sampled_case_ids, allow_out_of_scope=False, never_out_of_scope_cases=frozenset(), rater_ref=None):
    """The human's ratings, refused unless each names a sampled case exactly
    once: a rating outside the sample, or a second rating for one case, would
    make rated exceed drawn and the shortfall go negative. `out_of_scope` is a
    rating only when the contract lets the judge answer it: the switch
    out_of_scope_verdict is on AND the sampled report's clause is not
    never_out_of_scope (`never_out_of_scope_cases` names the sampled cases
    whose clause is). The sample then holds out_of_scope reports, and the
    reviewer must be able to agree with them; on a clause that can never be
    out of scope, such a rating would be sealed and count against the judge."""
    base = {"met", "not_met", "not_evaluable"}
    seen = set()
    for r in ratings:
        case_id = r.get("case_id")
        if case_id not in sampled_case_ids:
            raise ValueError(f"rating for a case outside the sample: {case_id!r}")
        if case_id in seen:
            raise ValueError(f"more than one rating for case {case_id!r}")
        allowed = base | ({"out_of_scope"} if allow_out_of_scope and case_id not in never_out_of_scope_cases
                          else set())
        if r.get("rating") not in allowed:
            raise ValueError(f"rating for {case_id!r} is not one of {', '.join(sorted(allowed))}")
        own = r.get("rater_ref", rater_ref)
        if not isinstance(own, str) or not own or own != own.strip():
            raise ValueError(f"rating for {case_id!r} has no usable rater_ref (a non-empty opaque string, no surrounding "
                             f"spaces): give each rating one, or pass --rater-ref")
        seen.add(case_id)
    return [{**r, "rater_ref": r.get("rater_ref", rater_ref)} for r in ratings]


def checked_bindings(path, rater_refs):
    """The Controller Binding records the human supplies, {rater_ref: binding file}, read
    for the raters who rated this week: the digest of each file's octets as given (AAC
    ts/docs/controller-binding-carriage.md, not the CB section 4 binding digest). A rater
    with no entry is cited for nothing: the page then says its book and controller are
    not in this bundle. A name in the file that rated nothing is refused, so a typo
    never reads as a binding for someone."""
    if path is None:
        return {}
    given = json.loads(path.read_text())
    if not isinstance(given, dict):
        raise ValueError("controller bindings file must be a JSON object {rater_ref: binding record file}")
    stray = sorted(set(given) - set(rater_refs))
    if stray:
        raise ValueError(f"controller binding for a rater who rated nothing this week: {', '.join(stray)}")
    cited = {}
    for ref in sorted(given):
        if not isinstance(given[ref], str):
            raise ValueError(f"controller binding for {ref!r} must be a file path")
        record = pathlib.Path(given[ref])
        if not record.is_absolute():
            record = path.parent / record
        if not record.is_file():
            raise ValueError(f"controller binding file for {ref!r} not found: {record}")
        cited[ref] = sha256_file(record)
    return cited


def raters_of_pin(rated_by_case, by_case, pin):
    """The rater_refs who rated a case whose judged report names `pin`: a pin's summary
    cites the bindings of its own raters only."""
    return {ref for case_id, ref in rated_by_case.items() if by_case[case_id][1]["judge_pin_digest"] == pin}


def citations(manifest_id, binding_digests):
    """The `references[]` the week's calibration summaries carry: the sample manifest
    (which holds the period and the sampling policy) and each rater's Controller Binding
    record, by digest. Nothing is added to calibration-summary/v1 itself. The keys are the
    seal request's capsule keys (capsule-cli decodes them strictly, as `Type`, `DigestAlg`,
    `Digest`, `CitationPurpose`), not the snake_case of a record body."""
    cited = [{"Type": "agent-action-capsule", "DigestAlg": "SHA-256", "Digest": manifest_id,
              "CitationPurpose": "acted_on"}]
    cited += [{"Type": "controller-binding", "DigestAlg": "SHA-256", "Digest": d, "CitationPurpose": "acted_on"}
              for d in sorted(set(binding_digests.values()))]
    return cited


def sample_key(seed, capsule_id):
    s = seed.encode()
    return hashlib.sha256(len(s).to_bytes(4, "big") + s + capsule_id.encode()).hexdigest(), capsule_id


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--spec", required=True, type=pathlib.Path)
    ap.add_argument("--date", required=True, help="any day in the week, YYYY-MM-DD (UTC; weeks start Monday)")
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("--ratings", type=pathlib.Path, help="the human's blind ratings: [{case_id, rating, rater_ref?}]")
    ap.add_argument("--rater-ref", help="an opaque principal reference for the rater (never a name), for each rating "
                    "that carries no rater_ref of its own; the run refuses a rating with neither")
    ap.add_argument("--controller-bindings", type=pathlib.Path, help="JSON {rater_ref: Controller Binding record file}: "
                    "the week's summaries cite each file by the SHA-256 of its octets, so a page can read the rater's "
                    "controller from the binding; a rater with no entry is cited for nothing")
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
        reports, unjudged = week_frame(
            list_capsules(ctl, profile), lambda cid: payload(ctl, profile, cid),
            lambda cid: verify(ctl, profile, cid, work), week_days)
        log["frame"] = len(reports)
        log["frame_unjudged_skipped"] = unjudged
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
            # A case id is book-sourced data (it can carry an agent model,
            # demo/backfill/backfill.py --case-model): escaped the same way
            # every other per-case file name is, never interpolated raw.
            name = safe_filename(body["case_id"])
            (packets / f"{name}.json").write_text(json.dumps(packet, indent=2))
            by_case[body["case_id"]] = (rid, body)
            written[name] = packet
        # What the reviewer is shown, as a digest: the disclosure itself is a skill action.
        action("blind-packets", inputs=[("sample_manifest", manifest_id)], output_digest=json_digest(written))

        if args.ratings is None:
            log["status"] = f"awaiting the human's blind ratings for {len(selected)} case(s) in {packets}"
            print(json.dumps(log, indent=2))
            return 3

        # 4. The human's ratings, one record each, citing the report audited.
        try:
            never_oos_clauses = {c["id"] for c in spec.get("clauses", []) if c.get("never_out_of_scope")}
            never_oos_cases = {cid for cid, (_, b) in by_case.items() if b.get("clause_id") in never_oos_clauses}
            ratings = checked_ratings(json.loads(args.ratings.read_text()), set(by_case),
                                      bool((spec.get("switches") or {}).get("out_of_scope_verdict")),
                                      never_oos_cases, args.rater_ref)
            bindings = checked_bindings(args.controller_bindings, {r["rater_ref"] for r in ratings})
            rater_of = {r["case_id"]: r["rater_ref"] for r in ratings}
        except ValueError as e:
            raise EvidenceUnavailable(f"ratings refused: {e}") from e
        rated = []
        for r in ratings:
            rid, body = by_case[r["case_id"]]
            record = human_rating_record(r["case_id"], week_key, rid, r["rating"], r["rater_ref"], stamp)
            publish(ctl, profile, seal_request(
                record["record_id"], operator,
                "evidencebook-skills/weekly-blind-expert", stamp, record), work, f"rating-{rid[:16]}")
            rated.append({"case_id": r["case_id"], "rating": r["rating"]})
        log["rated"] = len(rated)
        log["shortfall"] = len(selected) - len(rated)

        # 5. Agreement as k of n over the drawn sample; nothing else.
        # A case counts only when the rating and the judge's verdict are both met
        # or not_met (human_rating.counted_cases); the verb reads the same pairs,
        # so its totals and ours are one reading.
        counts = counted_cases(selected, rated)
        (work / "sampled-reports.json").write_text(json.dumps(
            [{"case_id": b["case_id"], "judge_pin_digest": b["judge_pin_digest"], "verdict": b["verdict"]}
             for _, b in selected if b["case_id"] in counts]))
        (work / "ratings.json").write_text(json.dumps([r for r in rated if r["case_id"] in counts]))
        # With no countable case there is nothing to summarize: the records read 0 of 0.
        summary = (run(ctl, "calibration", "summarize", str(work / "sampled-reports.json"), str(work / "ratings.json"))
                   if counts else {"pins": []})
        records = calibration_summaries(selected, rated, spec["contract"], week_key, stamp)
        # The per-clause tallies must add up to the verb's per-pin totals: one
        # reading of agreement, not two.
        disagreement = disagreement_with_verb(records, summary["pins"])
        if disagreement:
            raise EvidenceUnavailable(disagreement)
        log["calibration_summaries"] = []
        for record in records:
            request = seal_request(record["record_id"], operator, "evidencebook-skills/weekly-blind-expert",
                                   stamp, record)
            own = raters_of_pin(rater_of, by_case, record["judge_pin"]["digest"])
            request["capsule"]["References"] = citations(
                manifest_id, {ref: d for ref, d in bindings.items() if ref in own})
            log["calibration_summaries"].append(publish(
                ctl, profile, request, work, f"calibration-summary-{record['judge_pin']['digest'][:16]}"))
        # This action ties the summaries to the sample they summarize (the manifest),
        # as the blind-packets action does.
        action("calibration-summary", inputs=[("sample_manifest", manifest_id)], output_digest=json_digest(log["calibration_summaries"]))
        log["agreement"] = [{"judge_pin_digest": p["judge_pin_digest"], "k": p["agreement_count"], "n": p["rated_count"]}
                            for p in summary["pins"]]

        # 6. The week's Close; unilateral, no peer bundle is held.
        close_args = ["book", "close", "--profile", profile, "--period", "week", "--date", str(day),
                      "--counterparty", spec["counterparty"]]
        capsule_out, bundle_out = out / "close.json", out / "close-bundle.json"
        if not capsule_out.exists():
            close_args += ["--capsule-out", str(capsule_out), "--bundle-out", str(bundle_out)]
        closed = run(ctl, *close_args)
        log["close"] = {"record_id": closed["record_id"], "already_closed": closed["already_closed"],
                        "unilateral": not closed.get("peer_bundle"),
                        # capsulectl rc52 returns the reconciliation only on the call that closes the period.
                        "window": ([closed["reconciliation"]["from_seq"], closed["reconciliation"]["to_seq"]]
                                   if closed.get("reconciliation") else None),
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
