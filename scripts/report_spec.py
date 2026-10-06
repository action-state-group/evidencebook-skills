#!/usr/bin/env python3
"""Report from records, with no judge: a declarative "report spec" YAML names
which sealed records count, how to group them (by day, by peer, ...), which
sums/counts to compute, and which thresholds or per-record invariants make a
claim met/unmet -- computed deterministically, with no rubric and no Jev.
Every claim this module produces carries tier "recomputed" and cites the
capsule ids of the records it was computed from, so the report and the
verifier can both recompute it from the same book.

This is scripts/rollup_day.py's sibling, not its replacement: where
rollup_day.py turns a day's JUDGED evaluation-report/v1 capsules (one Jev
verdict per clause per case) into a Result v0 document, this module turns the
SEALED RECORDS THEMSELVES -- no judge in the loop at all -- into the same
Result v0 shape, by calling the exact same scripts/result_v0.py functions
(build_result_v0_for_day) rollup_day.py calls. A "case" (one conversation) is
the group-less building block in both modules; what differs is only how a
criterion's verdict gets decided -- a judge's answer there, a declarative
spec's deterministic computation here.

    python3 scripts/report_spec.py --profile tau2 --spec scripts/specs/tau2-airline-no-judge.yaml \\
        --capsulectl capsulectl --generated-at 2026-09-23T23:59:59Z --out RUN_DIR/rollup

Writes one result-v0-<group>.json per group (day, or whatever --spec's
group_by names) plus a summary.json -- the same file-naming convention
rollup_day.py uses, so scripts/report.sh's tail (result build -> checkpoint
-> disclose -> report build) runs identically over either module's output.

Report spec v1 shape (see scripts/specs/tau2-airline-no-judge.yaml for a worked
example, scripts/specs/mesh-llm-settlement-draft.yaml for a second use case's DRAFT):

    spec_version: report-spec/v1
    id: <becomes the contract id>
    version: <int, becomes the contract_ref "<id>@<version>">
    title: <free text, the report's headline>
    group_by: day              # or the name of any field a source's own
                                # `fields:` mapping projects (e.g. peer_id, or
                                # a `join` composite of two fields for a
                                # "per peer per day" grouping -- see
                                # apply_field_projections's own docstring)
    sources:
      - name: <referenced by other sources/metrics/claims>
        kind: case | record | tool_result | flatten
        # kind: case        -- one row per sealed conversation record (a book
        #   entry whose payload is {"case": {...}, "agent_interaction": {...}}).
        #   Built-in fields: case_id, day, tool_call_count, plus whatever
        #   `fields:` (dotted paths into the payload) names.
        # kind: record      -- `case`'s sibling for a use case whose sealed
        #   records aren't tau2's conversation shape: `match:` (dotted path ->
        #   required value, e.g. {record_type: mesh-settlement-exchange/v1})
        #   selects which book records count; `fields:` projects whatever the
        #   use case's own record carries (e.g. peer_id, served, earned, paid).
        # kind: tool_result -- `from:` a case source, `tool_name:` the tool
        #   whose JSON-parsed result becomes the row (one row per call),
        #   carrying the parent's case_id/day plus the result's own fields
        #   verbatim (e.g. tau2's cancel_reservation result: reservation_id,
        #   cabin, insurance, payment_history, ...).
        # kind: flatten     -- `from:` a tool_result (or case) source, `path:`
        #   a field on it holding a list; one row per list entry, carrying the
        #   parent's scalar fields plus the entry's own. `match_offsets_field:`
        #   (optional) computes __has_offset_match per row: true when some
        #   OTHER entry in the SAME parent list carries the negated amount --
        #   a generic ledger-reconciliation primitive (a charge offset by a
        #   refund, a debit offset by a credit), not specific to one domain.
        #   `where:` (optional, evaluated after __has_offset_match so it can
        #   read it) keeps only matching entries.
    metrics:
      - name: <referenced by threshold claims and the report title>
        source: <a source name>
        op: count | sum
        field: <dotted into the row, required for sum>
        where: <optional safe_expr string, filters rows before aggregating>
        abs: <optional bool, sum only -- abs() of the total, for signed ledgers>
    claims:
      - id: <becomes requirement_ref; "<group>::<id>" becomes the claim id>
        description: <free text>
        kind: threshold
        metric: <a metric name, evaluated for this group>
        op: "<=" | ">=" | "<" | ">" | "==" | "!="
        value: <number, or a safe_expr string over this group's own metrics>
      - id: <...>
        kind: forall
        source: <a source name>
        assert: <safe_expr string over one row of that source; must hold for
                 EVERY row in this group for the claim to be met -- vacuously
                 met when the group has no rows for that source>
    presentation:
      card: <one of capsule-cli's reportCards, e.g. "outcome", "settlement">
      title_template: <a str.format() template over {title}, {period}, and
                       every metric name, rendered once per group and passed
                       to `capsulectl report build --presentation` -- the
                       Result v0 View block's own schema is closed over
                       spec_version/producer_name/logo_data_url/title (no room
                       for a custom metrics block), so the computed sums/counts
                       surface in the report's title line, not as a new field>

Every claim this module computes is met or not_met, never not_evaluable: a
deterministic computation over records that exist has no missing-judge
uncertainty to express. A group with zero rows for a forall claim's source
reads as met (vacuously -- nothing in it violates the assertion), not
not_evaluable, same convention a universally-quantified "every X satisfies P"
statement uses when there are no Xs.
"""
import argparse
import datetime
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from capsulectl_calls import case_id_of, list_capsules, parse_rfc3339, payload  # noqa: E402
from result_v0 import build_result_v0_for_day  # noqa: E402
from rollup import RollupError  # noqa: E402
from safe_expr import ExprError, eval_expr  # noqa: E402

_SCALAR_TYPES = (str, int, float, bool, type(None))


class ReportSpecError(ValueError):
    """A report spec named a source/metric/claim shape this engine refuses to
    guess about -- a config bug fails the run closed, same discipline as
    rollup.RollupError for the judged path."""


def get_path(obj, dotted_path):
    """Dict-only dotted-path lookup (e.g. "case.domain") -- never indexes a
    list; a report spec that needs a list's entries uses a `flatten` source
    instead, where the engine's own code decides how parent/child fields
    combine, not a path string. None if any hop is missing or isn't a dict."""
    cur = obj
    for part in dotted_path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _scalars_only(row):
    return {k: v for k, v in row.items() if isinstance(v, _SCALAR_TYPES)}


def apply_field_projections(row, body, fields):
    """Fill in `row`'s `fields` entries in declaration order -- YAML mapping
    order is preserved by PyYAML's safe_load, and that order is load-bearing
    here: each entry is either a bare dotted path into `body` (the plain
    case), or {"join": [names...], "sep": "/"} (default "/"), which reads
    those NAMES BACK OUT OF `row` ITSELF (already-built-in fields like "day",
    or an earlier entry in this same `fields` mapping) and joins them into one
    composite grouping key -- e.g. a mesh-llm settlement spec's "per peer per
    day" grouping, where neither "peer_id" nor "day" alone is the group, but
    group_by has only ever needed one field name. A `join` naming a field
    declared later in the same mapping reads it back as the string "None"
    (get()'s own default), not a crash -- a spec ordering bug is visible in
    the output, never silently resolved by guessing the author's intent."""
    for name, projection in fields.items():
        if isinstance(projection, str):
            row[name] = get_path(body, projection)
        elif isinstance(projection, dict) and "join" in projection:
            sep = projection.get("sep", "/")
            row[name] = sep.join(str(row.get(part)) for part in projection["join"])
        else:
            raise ReportSpecError(f"unsupported field projection for {name!r}: {projection!r}")
    return row


def _tool_call_count(messages):
    return sum(len(m.get("tool_calls") or []) for m in messages or [])


def _tool_results(messages, tool_name):
    """(call, parsed_result_or_None) for every call to `tool_name`, in
    conversation order -- a small, generic correlator (tool_calls[] carry the
    call id; the matching tool-role message carries the result under the same
    id), independent of scripts/recompute.py's own tau2-specific helper of the
    same shape: that one lives with the tau2 policy checkers it serves, this
    one is this engine's own, reusable for any tool-calling conversation
    format, not just tau2's."""
    results_by_id = {m.get("tool_call_id"): m for m in (messages or []) if m.get("role") == "tool"}
    out = []
    for m in messages or []:
        for call in m.get("tool_calls") or []:
            if call.get("name") != tool_name:
                continue
            res_msg = results_by_id.get(call.get("id"))
            parsed = None
            if res_msg is not None and res_msg.get("content"):
                try:
                    parsed = json.loads(res_msg["content"])
                except (json.JSONDecodeError, TypeError):
                    parsed = None
            out.append((call, parsed))
    return out


def select_case_rows(capsulectl, profile, date_from=None, date_to=None, fields=None):
    """One row per sealed conversation in [date_from, date_to] (inclusive,
    either end optional) -- built-in fields case_id/day/tool_call_count, plus
    `fields` (name -> dotted path into the payload)."""
    fields = fields or {}
    rows = []
    for entry in list_capsules(capsulectl, profile):
        day = parse_rfc3339(entry["appended_at"]).date()
        if date_from is not None and day < date_from:
            continue
        if date_to is not None and day > date_to:
            continue
        body = payload(capsulectl, profile, entry["capsule_id"])
        if not isinstance(body, dict) or not isinstance(body.get("case"), dict):
            continue
        messages = (body.get("agent_interaction") or {}).get("messages")
        row = {
            "case_id": case_id_of(body["case"]),
            "day": day.isoformat(),
            "tool_call_count": _tool_call_count(messages),
            "__capsule_id": entry["capsule_id"],
            "__messages": messages,
        }
        apply_field_projections(row, body, fields)
        rows.append(row)
    return rows


def select_record_rows(capsulectl, profile, match=None, fields=None, date_from=None, date_to=None):
    """One row per sealed book record matching `match` (a dict of dotted-path
    -> required value, e.g. {"record_type": "mesh-settlement-exchange/v1"}) --
    the `kind: case` source's sibling for a use case whose sealed records
    aren't tau2's own {"case": ..., "agent_interaction": ...} shape (e.g. a
    mesh-llm settlement exchange record). Built-in fields: day, __capsule_id,
    plus `fields` (name -> dotted path into the payload) -- no tool_call_count
    or __messages here, since those are specific to a conversation's own
    shape, not every record's."""
    match, fields = match or {}, fields or {}
    rows = []
    for entry in list_capsules(capsulectl, profile):
        day = parse_rfc3339(entry["appended_at"]).date()
        if date_from is not None and day < date_from:
            continue
        if date_to is not None and day > date_to:
            continue
        body = payload(capsulectl, profile, entry["capsule_id"])
        if not isinstance(body, dict):
            continue
        if any(get_path(body, path) != value for path, value in match.items()):
            continue
        row = {"day": day.isoformat(), "__capsule_id": entry["capsule_id"]}
        apply_field_projections(row, body, fields)
        rows.append(row)
    return rows


def extract_tool_result_rows(parent_rows, tool_name, fields=None):
    """One row per matching tool call in each parent (case) row: the parsed
    result's own fields, plus the parent's carried scalars (case_id, day,
    __capsule_id) and `__messages` (needed only so a further `flatten` source
    can still see this row's own raw list fields; stripped by `_scalars_only`
    before anything reaches a safe_expr claim)."""
    fields = fields or {}
    out = []
    for i, prow in enumerate(parent_rows):
        carried = _scalars_only(prow)
        for j, (call, result) in enumerate(_tool_results(prow.get("__messages"), tool_name)):
            if not isinstance(result, dict):
                continue
            row = dict(result)
            row.update(carried)
            row["__row_id"] = f"{prow['case_id']}::{tool_name}::{j}"
            apply_field_projections(row, result, fields)
            out.append(row)
    return out


def extract_flatten_rows(parent_rows, path, match_offsets_field=None, where=None):
    """One row per entry of the list at `path` on each parent row, carrying
    the parent's scalar fields plus the entry's own. `match_offsets_field`,
    when given, computes __has_offset_match: true when some OTHER entry in
    THE SAME parent list carries the negated value of this entry's own
    `match_offsets_field` -- a generic ledger-reconciliation primitive, not
    specific to any one domain's field names. `where` (a safe_expr string,
    evaluated per candidate row, AFTER __has_offset_match is set so it can
    read it) keeps only matching entries."""
    out = []
    for prow in parent_rows:
        items = prow.get(path)
        if not isinstance(items, list):
            continue
        carried = _scalars_only(prow)
        amounts = [it.get(match_offsets_field) if isinstance(it, dict) else None for it in items] \
            if match_offsets_field else None
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            row = dict(carried)
            row.update(_scalars_only(item))
            if match_offsets_field is not None:
                value = item.get(match_offsets_field)
                row["__has_offset_match"] = (
                    value is not None and any(j != i and amounts[j] == -value for j in range(len(amounts)))
                )
            try:
                keep = where is None or eval_expr(where, row)
            except ExprError as e:
                raise ReportSpecError(f"flatten source {path!r}: where {where!r}: {e}") from e
            if keep:
                out.append(row)
    return out


def build_rows(spec, capsulectl, profile, date_from=None, date_to=None):
    """name -> list of rows, for every source the spec declares, in order
    (a source may name an earlier source as its own `from`)."""
    rows_by_name, kind_by_name = {}, {}
    for source in spec["sources"]:
        kind = source["kind"]
        if kind == "case":
            rows_by_name[source["name"]] = select_case_rows(
                capsulectl, profile, date_from, date_to, source.get("fields"))
        elif kind == "record":
            rows_by_name[source["name"]] = select_record_rows(
                capsulectl, profile, source.get("match"), source.get("fields"), date_from, date_to)
        elif kind == "tool_result":
            parent = rows_by_name.get(source["from"])
            if parent is None:
                raise ReportSpecError(f"source {source['name']!r}: unknown `from` source {source['from']!r}")
            if kind_by_name.get(source["from"]) != "case":
                # tool_result reads __messages, a field only a `kind: case` row carries
                # (select_case_rows' own built-in) -- any other parent kind silently
                # yields zero rows forever (desk-review finding, this job), never an
                # error, which looks exactly like "no matching tool calls" instead of
                # "this spec is wrong."
                raise ReportSpecError(
                    f"source {source['name']!r}: `from: {source['from']!r}` must be a `kind: case` "
                    f"source (it is {kind_by_name.get(source['from'])!r})")
            rows_by_name[source["name"]] = extract_tool_result_rows(parent, source["tool_name"], source.get("fields"))
        elif kind == "flatten":
            parent = rows_by_name.get(source["from"])
            if parent is None:
                raise ReportSpecError(f"source {source['name']!r}: unknown `from` source {source['from']!r}")
            rows_by_name[source["name"]] = extract_flatten_rows(
                parent, source["path"], source.get("match_offsets_field"), source.get("where"))
        else:
            raise ReportSpecError(f"source {source['name']!r}: unknown kind {kind!r}")
        kind_by_name[source["name"]] = kind
    return rows_by_name


def metric_rows(metric, rows):
    """The rows a metric actually aggregates over -- its own `where` applied,
    nothing else. The single place both compute_metric() and a threshold
    claim's own evidence (evaluate_group()) go through, so a claim citing
    "the records it was computed from" (this module's own docstring promise)
    can never cite a row the metric's where clause filtered out."""
    return [r for r in rows if metric.get("where") is None or eval_expr(metric["where"], r)]


def compute_metric(metric, rows):
    rows = metric_rows(metric, rows)
    if metric["op"] == "count":
        return len(rows)
    if metric["op"] == "sum":
        field = metric["field"]
        total = sum((r.get(field) or 0) for r in rows)
        return abs(total) if metric.get("abs") else total
    raise ReportSpecError(f"metric {metric['name']!r}: unknown op {metric['op']!r}")


_OPS = {"<=": lambda a, b: a <= b, ">=": lambda a, b: a >= b, "<": lambda a, b: a < b,
        ">": lambda a, b: a > b, "==": lambda a, b: a == b, "!=": lambda a, b: a != b}


def evaluate_group(spec, group_key, rows_by_name, group_field):
    """One group's (criterion_verdicts, report_digests, metric_values) --
    every claim in the spec, evaluated over only this group's own rows."""
    group_rows = {name: [r for r in rows if r.get(group_field) == group_key] for name, rows in rows_by_name.items()}

    metric_values = {}
    for m in spec.get("metrics", []):
        if m["source"] not in group_rows:
            raise ReportSpecError(f"metric {m['name']!r}: unknown source {m['source']!r}")
        try:
            metric_values[m["name"]] = compute_metric(m, group_rows[m["source"]])
        except ExprError as e:
            raise ReportSpecError(f"metric {m['name']!r}: where {m.get('where')!r}: {e}") from e

    verdicts, digests = {}, {}
    for claim in spec["claims"]:
        cid = claim["id"]
        kind = claim["kind"]
        if kind == "threshold":
            metric_name = claim["metric"]
            if metric_name not in metric_values:
                raise ReportSpecError(f"claim {cid!r}: unknown metric {metric_name!r}")
            left = metric_values[metric_name]
            value = claim["value"]
            try:
                right = value if isinstance(value, (int, float)) else eval_expr(value, metric_values)
            except ExprError as e:
                raise ReportSpecError(f"claim {cid!r}: value {value!r}: {e}") from e
            op = claim["op"]
            if op not in _OPS:
                raise ReportSpecError(f"claim {cid!r}: unknown op {op!r}")
            metric = spec_metric(spec, metric_name)
            source_rows = metric_rows(metric, group_rows[metric["source"]])
            verdicts[cid] = "met" if _OPS[op](left, right) else "not_met"
            digests[cid] = sorted({r["__capsule_id"] for r in source_rows if "__capsule_id" in r})
        elif kind == "forall":
            if claim["source"] not in group_rows:
                raise ReportSpecError(f"claim {cid!r}: unknown source {claim['source']!r}")
            source_rows = group_rows[claim["source"]]
            try:
                ok = all(eval_expr(claim["assert"], r) for r in source_rows)
            except ExprError as e:
                raise ReportSpecError(f"claim {cid!r}: assert {claim['assert']!r}: {e}") from e
            verdicts[cid] = "met" if ok else "not_met"
            digests[cid] = sorted({r["__capsule_id"] for r in source_rows if "__capsule_id" in r})
        else:
            raise ReportSpecError(f"claim {cid!r}: unknown kind {kind!r}")
    return verdicts, digests, metric_values


def spec_metric(spec, metric_name):
    for m in spec.get("metrics", []):
        if m["name"] == metric_name:
            return m
    raise ReportSpecError(f"unknown metric: {metric_name!r}")


def contract_ref(spec):
    return f"{spec['id']}@{spec['version']}"


def render_title(spec, group_key, metric_values):
    template = (spec.get("presentation") or {}).get("title_template")
    if not template:
        return f"{spec.get('title', spec['id'])} -- {group_key}"
    try:
        return template.format(title=spec.get("title", spec["id"]), period=group_key, **metric_values)
    except (KeyError, IndexError) as e:
        raise ReportSpecError(f"presentation.title_template {template!r} names a field this spec "
                               f"doesn't compute: {e}") from e


def safe_filename(value):
    import re
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(value))


def build_documents(spec, rows_by_name, generated_at):
    """Pure: rows_by_name (already built, no I/O) -> {group_key: Result v0
    document}, plus the per-group metric values -- groups them by
    spec['group_by'] (default "day"), evaluates every claim per group
    (evaluate_group), and calls the SAME scripts/result_v0.build_result_v0_for_day
    function scripts/rollup_day.py calls for the judged path, one group at a
    time. Separated from build_report_from_records's file-writing/capsulectl-I/O
    so this half -- the actual contract-building logic -- has a direct unit
    test, the same split tests/test_rollup_day.py's own docstring describes for
    group_reports()/rollup_case() versus collect_reports()."""
    group_field = spec.get("group_by", "day")
    all_claims = tuple(c["id"] for c in spec["claims"])
    tiers = {c: "recomputed" for c in all_claims}
    cref = contract_ref(spec)

    # The FIRST listed source decides which groups exist at all (desk-review
    # finding: undocumented) -- a claim/metric over a later source only ever
    # narrows an already-existing group's rows, it can never add a new group.
    # tau2-airline-no-judge.yaml and mesh-llm-settlement-draft.yaml both list
    # their base conversation/exchange source first for exactly this reason.
    base_source = spec["sources"][0]["name"]
    group_keys = sorted({r.get(group_field) for r in rows_by_name.get(base_source, []) if r.get(group_field) is not None})

    docs, group_results = {}, []
    for group_key in group_keys:
        verdicts, digests, metric_values = evaluate_group(spec, group_key, rows_by_name, group_field)
        try:
            doc = build_result_v0_for_day(
                f"{group_field}:{group_key}", [(str(group_key), verdicts, digests, tiers)],
                generated_at, all_claims, cref)
        except RollupError as e:
            raise ReportSpecError(f"group {group_key!r}: {e}") from e
        doc["view"]["title"] = render_title(spec, group_key, metric_values)
        docs[group_key] = doc
        group_results.append({group_field: str(group_key), "claims": len(doc["claims"]), "metrics": metric_values})
    return docs, group_results


def build_report_from_records(spec, capsulectl, profile, generated_at, out_dir, date_from=None, date_to=None):
    """The engine's own entry point (also scripts/report.sh's no-judge path):
    reads the book (build_rows), computes every group's Result v0 document
    (build_documents), and writes one result-v0-<group>.json plus a
    summary.json -- same file-naming convention scripts/rollup_day.py uses, so
    scripts/report.sh's tail doesn't need to know which path produced its
    input."""
    rows_by_name = build_rows(spec, capsulectl, profile, date_from, date_to)
    docs, group_results = build_documents(spec, rows_by_name, generated_at)

    out_dir.mkdir(parents=True, exist_ok=True)
    for group_key, entry in zip(docs, group_results):
        out_path = out_dir / f"result-v0-{safe_filename(group_key)}.json"
        out_path.write_text(json.dumps(docs[group_key], indent=2))
        entry["out"] = str(out_path)

    summary = {"spec": spec["id"], "contract_ref": contract_ref(spec), "groups": group_results}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return summary


def load_spec(path):
    import yaml
    spec = yaml.safe_load(pathlib.Path(path).read_text())
    if not isinstance(spec, dict):
        raise ReportSpecError(f"{path}: must be a YAML mapping, got {type(spec).__name__}")
    if spec.get("spec_version") != "report-spec/v1":
        raise ReportSpecError(f"{path}: spec_version must be report-spec/v1, got {spec.get('spec_version')!r}")
    for key in ("id", "version", "sources", "claims"):
        if not spec.get(key):
            raise ReportSpecError(f"{path}: missing or empty required key {key!r}")
    return spec


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--spec", required=True, type=pathlib.Path, help="a report-spec/v1 YAML file")
    ap.add_argument("--capsulectl", default="capsulectl")
    ap.add_argument("--generated-at", required=True)
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("--date-from", default=None, help="YYYY-MM-DD, inclusive")
    ap.add_argument("--date-to", default=None, help="YYYY-MM-DD, inclusive")
    args = ap.parse_args(argv)

    spec = load_spec(args.spec)
    date_from = datetime.date.fromisoformat(args.date_from) if args.date_from else None
    date_to = datetime.date.fromisoformat(args.date_to) if args.date_to else None
    try:
        build_report_from_records(spec, args.capsulectl, args.profile, args.generated_at, args.out,
                                   date_from, date_to)
    except (ReportSpecError, RollupError) as e:
        print(json.dumps({"error": str(e)}, indent=2))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
