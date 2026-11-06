#!/usr/bin/env python3
"""terms -- the Terms Pack Studio verbs for a seller's deal terms pack.

    terms init    (--deals FILE | --exports DIR | --store HOME) [--pack-id ID] [--workspace DIR]
    terms readiness SRC
    terms lint    SRC   (any kind: admission, deal, conduct, live, report)
    terms test    SRC [--engine PATH | --live-engine PATH] [--engine-commit SHA]
    terms run     SRC [--deals FILE | --exports DIR | --store HOME] [--dry-run] [--workspace DIR]   (no sales flag: the dataset the pack's workspace remembers)
    terms verify  PAGE
    terms compare A B [--workspace DIR]      (A, B: a run, or a pack digest from `history`)
    terms history SRC [--workspace DIR]      (dataset, last run, readiness, one line per pack digest)
    terms checkout SRC DIGEST [--force] [--workspace DIR]   (undo: restore that digest's source; then run and compare)
    terms keep-transcript SRC FILE [--workspace DIR]   (opt-in, private; no verb keeps a transcript otherwise)
    terms publish SRC [--workspace DIR]

SRC is a pack-source.yaml with `scope.kind: deal` (scripts/deal_pack.py). Every
verb prints one JSON object on stdout and exits 0, or 1 with the reason in it. `test` also exits
3 (UNRUN) when no case failed but some did not run (`passed: null`), so a script that checks
only for 0 cannot read unrun cases as passed.
The entry point is scripts/studio/terms (a bare `test` would be the shell's).

`init` reads the sales, writes the field census and a proposed pack under
<workspace>/packs/<pack_id>/, and `readiness` prints (and refreshes) each term's status. `lint`, `test` and
`run` rewrite readiness.json (and `run` census.json) beside a pack `init` made, so it is
current after each edit, label (labels.json) or run; that is the one write `lint` and `test`
make, and `run` makes it only inside the workspace it is given.

The workspace (default ~/studio, or $TERMS_WORKSPACE) is the only place a verb
writes: `run` writes runs/<pack_id>/<n>/{result.json,report.html} and `publish`
writes published/<pack_id>/<digest>/; both also keep packs/<pack_id>/{workspace.json,
history.jsonl,history/} (the dataset, the last run, one line per pack digest; see
scripts/studio/workspace.py), `checkout` overwrites SRC (inside the workspace) and
`keep-transcript` writes packs/<pack_id>/private/. --deals and the Results `compare`
reads are only read. With no --workspace or $TERMS_WORKSPACE, a SRC inside a pack folder
`init` made names its own workspace.

A Result is Evidence Result v0 (scripts/result_v0.py), one claim per sale per
row, plus two document members: `x-pack` (the pack's id, version, definition
digest and each row's digest) and, on a rehearsal, `x-rehearsal: true`. The page
carries result.json's exact bytes in a <script type="application/json">, and
states their SHA-256 beside them; `terms verify` checks the page against itself
offline.
"""
import argparse
import datetime
import hashlib
import html
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "evaluators"))
sys.path.insert(0, str(ROOT / "scripts" / "studio"))

import rfc8785  # noqa: E402
import yaml  # noqa: E402

import admission_pack  # noqa: E402
import case_eval  # noqa: E402
import deal_pack  # noqa: E402
import deal_store  # noqa: E402
import pack_compile  # noqa: E402
import pack_schema  # noqa: E402
import readiness  # noqa: E402
import result_v0  # noqa: E402
import transaction  # noqa: E402
import two_case  # noqa: E402
import workspace as wsm  # noqa: E402

DEFAULT_WORKSPACE = "~/studio"


class TermsError(Exception):
    """A refusal, said in words."""


def out(obj, code=0):
    print(json.dumps(obj, indent=2, sort_keys=False))
    return code


def load_pack(src):
    path = pathlib.Path(src)
    try:
        source = pack_compile.load_source(path.read_text())
    except (OSError, yaml.YAMLError) as e:
        raise TermsError(f"cannot read {src}: {e}")
    if not deal_pack.is_deal(source):
        raise TermsError(f"{src} is not a deal terms pack (scope.kind: deal)")
    issues = lint_issues(source)
    if issues:
        raise TermsError("; ".join(issues))
    return source


def lint_issues(source):
    return pack_compile.validate_source(source)


def workspace_of(args, create=True):
    """The workspace; a verb that only reads it (create=False) never makes the folder."""
    named = args.workspace or os.environ.get("TERMS_WORKSPACE")
    src = getattr(args, "src", None)
    if not named and src:
        # a pack folder `init` made names its workspace: <ws>/packs/<id>/pack-source.yaml
        folder = pathlib.Path(src).resolve().parent
        if folder.parent.name == "packs" and (folder / "workspace.json").is_file():
            named = str(folder.parent.parent)
    ws = pathlib.Path(named or DEFAULT_WORKSPACE).expanduser()
    if create:
        ws.mkdir(parents=True, exist_ok=True)
    return ws.resolve()


def inside(ws, path):
    """path, which must resolve inside the workspace (a link out is refused)."""
    resolved = path.resolve()
    if ws != resolved and ws not in resolved.parents:
        raise TermsError(f"{path} is outside the workspace {ws}")
    return resolved


def load_deals(path):
    try:
        data = json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError) as e:
        raise TermsError(f"cannot read the sales file {path}: {e}")
    if isinstance(data, dict):
        data = data.get("trades") or data.get("deals")
    if not isinstance(data, list) or not data:
        raise TermsError(f"{path} holds no sales: expected a list, or {{\"trades\": [...]}}")
    deals = []
    for i, d in enumerate(data):
        did = d.get("deal_id", d.get("id")) if isinstance(d, dict) else None
        if not isinstance(did, str) or not did or "::" in did:
            raise TermsError(f"sale {i} has no deal_id (or id) the Result can name")
        deals.append(dict(d, deal_id=did))
    if len({d["deal_id"] for d in deals}) != len(deals):
        raise TermsError("two sales share a deal_id")
    return deals


def stored_dataset(args, ws, pack_id):
    """With no source flag, `run` reads the dataset the pack's workspace remembers (init or the last run)."""
    if args.deals or args.exports or args.store:
        return
    ref = wsm.state(inside(ws, ws / "packs" / pack_id)).get("dataset")
    if not isinstance(ref, dict) or ref.get("kind") not in ("deals", "exports", "store") or not ref.get("path"):
        return
    setattr(args, ref["kind"], str(ws / ref["path"]))  # an absolute path stays itself


def load_sales(args):
    try:
        if args.exports:
            return deal_store.sales_from_exports(args.exports)
        if args.store:
            return deal_store.sales_from_store(args.store)
    except (deal_store.StoreError, OSError, subprocess.SubprocessError) as e:
        raise TermsError(str(e))
    if not args.deals:
        raise TermsError("name the sales: --deals FILE, --exports DIR of `deal export` files, or --store HOME")
    return load_deals(args.deals)


def result_bytes(result):
    """The Result's bytes as written to result.json and embedded in the page:
    compact, sorted, ASCII, and `</` escaped so the page's <script> cannot be
    closed from inside (still the same JSON)."""
    return json.dumps(result, sort_keys=True, ensure_ascii=True, separators=(",", ":")).replace("</", "<\\/").encode()


def build_result(source, deals, generated_at, rehearsal):
    compiled = deal_pack.compiled(source)
    rows = compiled["rows"]
    ids = tuple(r["id"] for r in rows)
    verdicts = transaction.evaluate(source["rows"], deals)
    docs = []
    for deal in deals:
        evidence = hashlib.sha256(rfc8785.dumps(deal)).hexdigest()
        doc, _ = result_v0.build_result_v0(
            deal["deal_id"], verdicts[deal["deal_id"]], {}, generated_at, ids, compiled["contract_ref"],
            {rid: "recomputed" for rid in ids}, source_capsule_ids={rid: evidence for rid in ids},
            case_scoped_ids=True)
        docs.append(doc)
    merged = result_v0.merge_result_v0_documents(docs, f"{source['title']} -- {len(deals)} sales", generated_at)
    merged["x-pack"] = {
        "pack_id": source["pack_id"], "pack_version": source["pack_version"],
        "definition_digest": compiled["definition_digest"],
        "rows": [{"id": r["id"], "statement": r["statement"], "row_digest": r["row_digest"]} for r in rows],
        "sales": {d["deal_id"]: hashlib.sha256(rfc8785.dumps(d)).hexdigest() for d in deals},
    }
    if rehearsal:
        merged["x-rehearsal"] = True
    return merged


def came_through(result):
    head = result_v0.headline_from_result(result)
    return head["resolved"], head["cases"]


def undecided_or_missed(result, verdict):
    """{deal_id: [row ids]} of the sales with a row at this verdict. A sale the terms
    could not decide is neither came-through nor missed."""
    found = {}
    for deal, rows in by_deal(result).items():
        hit = sorted(r for r, v in rows.items() if v == verdict)
        if hit:
            found[deal] = hit
    return found


def by_deal(result):
    """{deal_id: {row_id: verdict}} from a Result's claims."""
    table = {}
    for claim in result["claims"]:
        deal_id, _, row_id = claim["id"].rpartition("::")
        table.setdefault(deal_id, {})[row_id] = claim["verdict"]
    return table


def page_html(result, raw):
    pack = result["x-pack"]
    met, total = came_through(result)
    table = by_deal(result)
    rehearsal = bool(result.get("x-rehearsal"))
    rows = pack["rows"]
    esc = html.escape
    counts = []
    for r in rows:
        v = [table[d][r["id"]] for d in table]
        counts.append((r, v.count("met"), v.count("not_met"), v.count("not_evaluable")))
    misses = [(d, r) for d in table for r in rows if table[d][r["id"]] == "not_met"]
    cells = "".join(
        f"<tr><td>{esc(r['statement'])}</td><td>{m}</td><td>{n}</td><td>{u}</td></tr>" for r, m, n, u in counts)
    missed = "".join(f"<li>{esc(d)}: {esc(r['statement'])}</li>" for d, r in misses) or "<li>none</li>"
    banner = ('<p id="stamp" class="stamp">REHEARSAL: nothing was switched on; these terms were tried over past sales.</p>'
              if rehearsal else "")
    digest = hashlib.sha256(raw).hexdigest()
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(result['view']['title'])}</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;margin:0 auto;max-width:44rem;padding:1rem 16px}}
.stamp{{background:#fde68a;color:#1f1300;padding:.5rem .75rem;font-weight:600}}
table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #8884;padding:.35rem .5rem;text-align:left}}
code{{overflow-wrap:anywhere}}</style></head><body>
{banner}
<h1>{esc(pack['pack_id'])} {esc(pack['pack_version'])}</h1>
<p id="headline" data-came-through="{met}" data-total="{total}"><strong>{met} of {total}</strong> sales came through.</p>
<table><tr><th>Term</th><th>Met</th><th>Missed</th><th>Could not decide</th></tr>{cells}</table>
<h2>Missed</h2><ul>{missed}</ul>
<p>Pack digest <code id="pack-digest">{pack['definition_digest']}</code><br>
The record below is the same bytes as <code>result.json</code>; its SHA-256 is <code id="result-digest">{digest}</code>.</p>
<script type="application/json" id="terms-result" data-sha256="{digest}" data-rehearsal="{str(rehearsal).lower()}" data-pack-digest="{pack['definition_digest']}">{raw.decode()}</script>
</body></html>
"""


def lint_source(path):
    """(kind, issues) of a pack source of any kind: the schema first, naming each
    field that breaks it, then the kind's own cross-field rules on a source the
    schema accepts (so no rule is reported twice)."""
    text = path.read_text()
    try:
        source = pack_compile.load_source(text)
    except yaml.YAMLError as e:
        return None, [f"cannot read {path}: {e}"]
    kind = pack_schema.kind_of(source)
    issues = pack_schema.schema_issues(source)
    if not issues:
        issues = pack_compile.validate_source(source, path.parent)
        if admission_pack.is_admission(source):
            issues = admission_pack.text_issues(text) + issues
    return kind, issues


def cmd_lint(args):
    path = pathlib.Path(args.src)
    try:
        kind, issues = lint_source(path)
    except OSError as e:
        return out({"valid": False, "issues": [f"cannot read {args.src}: {e}"]}, 1)
    return out({"valid": not issues, "kind": kind, "issues": issues}, 0 if not issues else 1)


UNRUN = 3  # `terms test`: nothing failed, but some case did not run
MIN_COMMIT_PREFIX = 7


def cmd_test(args):
    """Lint, then run the two cases (met, not met) of every row, on any kind."""
    path = pathlib.Path(args.src)
    try:
        kind, issues = lint_source(path)
    except OSError as e:
        return out({"passed": False, "issues": [f"cannot read {args.src}: {e}"]}, 1)
    if issues:
        return out({"passed": False, "kind": kind, "issues": issues}, 1)
    if kind == "deal":
        return test_deal(load_pack(args.src))
    source = pack_compile.load_source(path.read_text())
    cases, issues = two_case.read_cases(path, source)
    if issues:
        return out({"passed": False, "kind": kind, "issues": issues}, 1)
    if args.engine_commit is not None and len(args.engine_commit) < MIN_COMMIT_PREFIX:
        return out({"passed": False, "kind": kind, "issues": [
            f"--engine-commit needs at least {MIN_COMMIT_PREFIX} characters of the commit; {args.engine_commit!r} could match any engine"]}, 1)
    rows = case_eval.run(kind, source, cases, args.engine, args.engine_commit, live_engine=args.live_engine, src=path)
    failed = any(r["evaluated"] and not r["passed"] for r in rows)
    unrun = sum(r["evaluated"] is False for r in rows)
    # `passed` is true only when every row ran and passed; a row that was not run is not a pass, so
    # `null` says "not known", and the exit code is UNRUN (3), never 0, which a script reads as a pass.
    passed = False if failed else (None if unrun else True)
    ran = [r for r in rows if r["evaluated"]]
    return out({"passed": passed, "fixtures_valid": True, "kind": kind, "cases": len(cases),
                "evaluated": 2 * len(ran), "not_evaluated": len(cases) - 2 * len(ran), "rows": rows},
               1 if failed else UNRUN if unrun else 0)


def test_deal(source):
    results, failed = [], False
    for row in source["rows"]:
        name, arg = transaction.parse_check(row["check"])
        met_case, miss_case = transaction.CASES[name](arg)
        fold, _ = transaction.row_check(row)
        got = (fold(met_case, arg), fold(miss_case, arg))
        ok = got == ("met", "not_met")
        failed |= not ok
        results.append({"row": row["id"], "check": row["check"], "passed": ok,
                        "met_case": got[0], "miss_case": got[1], "evaluated": True})
    return out({"passed": not failed, "kind": "deal", "rows": results}, 1 if failed else 0)


PACK_FILES = ("pack-source.yaml", "census.json", "candidates.json", "readiness.json", "workspace.json", "history.jsonl")


def refresh_readiness(src, sales=None, ws=None):
    """Rewrite readiness.json beside a pack `terms init` made (the folder holds census.json). `sales`,
    when a verb has just read them, replace the census. A folder without census.json is not a workspace
    pack and is not touched; with `ws`, neither is a folder outside it. A pack that does not lint has no
    table (lint says why), and the last table stays."""
    path = pathlib.Path(src).resolve()
    folder = path.parent
    if not (folder / "census.json").is_file():
        return None
    if ws is not None:
        inside(ws, folder)
    for name in ("census.json", "readiness.json"):
        if (folder / name).is_symlink():
            raise TermsError(f"{folder / name} is a link; refusing to write through it")
    source = rated_source(path)
    if sales is not None:
        (folder / "census.json").write_text(json.dumps(readiness.census(sales), indent=2) + "\n")
    table = readiness_table(folder, source)
    (folder / "readiness.json").write_text(json.dumps(table, indent=2) + "\n")
    return table


def rated_source(path):
    """The pack source at `path`, which must lint: the table never rates a row the checker would refuse."""
    try:
        kind, issues = lint_source(path)
        source = pack_compile.load_source(path.read_text())
    except (OSError, yaml.YAMLError) as e:
        raise TermsError(f"cannot read {path}: {e}")
    if issues or kind != "deal":
        raise TermsError(f"{path} does not lint as a deal pack, so it has no readiness: " + ("; ".join(issues) or f"kind {kind}"))
    return source


def refresh_or_say(src, sales=None, ws=None):
    """refresh_readiness after a verb has printed its answer: a failure goes to stderr, never into the
    verb's JSON or its exit code."""
    try:
        refresh_readiness(src, sales, ws)
    except (TermsError, OSError, ValueError) as e:
        print(f"terms: readiness.json not refreshed: {e}", file=sys.stderr)


def readiness_table(folder, source):
    try:
        census_doc = readiness.read_json(folder / "census.json", {"records": 0, "fields": []})
        candidates = readiness.read_json(folder / "candidates.json", [])
        labels = readiness.read_json(folder / "labels.json", {})
    except ValueError as e:
        raise TermsError(f"a file beside the pack is not JSON: {e}")
    if not (isinstance(census_doc, dict) and isinstance(census_doc.get("fields"), list)):
        raise TermsError(f"{folder / 'census.json'} is not a field census")
    if not isinstance(candidates, list) or not all(isinstance(c, dict) and {"id", "statement", "tier", "reads", "side"} <= set(c) for c in candidates):
        raise TermsError(f"{folder / 'candidates.json'} is not a list of candidate terms (id, statement, tier, reads, side)")
    if not isinstance(labels, dict):
        raise TermsError(f"{folder / 'labels.json'} is not a map of term id to labelled sales")
    try:
        return readiness.readiness(source, census_doc, candidates, labels)
    except (KeyError, TypeError, AttributeError, ValueError) as e:
        # valid JSON of the wrong shape, anywhere inside: one refusal, never a traceback
        raise TermsError(f"a file beside the pack (census.json, candidates.json or labels.json) has the wrong shape: {type(e).__name__} {e}")


def cmd_readiness(args):
    path = pathlib.Path(args.src).resolve()
    if not (path.parent / "census.json").is_file():
        raise TermsError(f"no field census beside {args.src}: start the pack with `terms init`")
    try:
        return out(refresh_readiness(path))
    except OSError as e:
        raise TermsError(str(e))


def cmd_init(args):
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", args.pack_id):
        raise TermsError("--pack-id must be lowercase letters, digits, - and _")
    sales = load_sales(args)
    ws = workspace_of(args)
    folder = inside(ws, ws / "packs" / args.pack_id)
    taken = [n for n in PACK_FILES if (folder / n).exists() or (folder / n).is_symlink()]
    if taken:
        raise TermsError(f"{folder} already holds {', '.join(taken)}: edit it, then `terms readiness` (init never overwrites)")
    folder.mkdir(parents=True, exist_ok=True)
    source = {"scope": {"kind": "deal"}, "pack_id": args.pack_id, "pack_version": "0.1.0",
              "title": args.title or f"{args.pack_id} terms",
              "statement": "A sale came through when it met every row of these terms.",
              "evaluator": "transaction", "rows": [dict(r, proves=list(r["proves"])) for r in readiness.PROPOSED_ROWS]}
    issues = lint_issues(source)
    if issues:
        raise TermsError("the proposed pack does not lint: " + "; ".join(issues))
    census_doc = readiness.census(sales)
    ref = wsm.dataset_ref(args, sales, ws)  # may refuse (data JCS cannot digest): before anything is written
    (folder / "pack-source.yaml").write_text(yaml.safe_dump(source, sort_keys=False, width=100), encoding="utf-8")
    (folder / "census.json").write_text(json.dumps(census_doc, indent=2) + "\n")
    (folder / "candidates.json").write_text(json.dumps(readiness.propose_candidates(), indent=2) + "\n")
    table = readiness_table(folder, source)
    (folder / "readiness.json").write_text(json.dumps(table, indent=2) + "\n")
    wsm.save_state(folder, {"pack_id": args.pack_id, "dataset": ref, "last_run": None})
    return out({"pack": str(folder / "pack-source.yaml"), "census": str(folder / "census.json"),
                "readiness": str(folder / "readiness.json"), "records": census_doc["records"],
                "fields": len(census_doc["fields"]), "counts": table["counts"], "terms": table["terms"]})


def next_run_dir(ws, pack_id):
    base = inside(ws, ws / "runs" / pack_id)
    base.mkdir(parents=True, exist_ok=True)
    n = 1 + max([int(p.name) for p in base.iterdir() if p.name.isdigit()] or [0])
    run = base / f"{n:03d}"
    run.mkdir()
    return run


def cmd_run(args):
    source = load_pack(args.src)
    ws = workspace_of(args)
    stored_dataset(args, ws, source["pack_id"])
    deals = load_sales(args)
    generated_at = args.generated_at or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = build_result(source, deals, generated_at, args.dry_run)
    raw = result_bytes(result)
    run = next_run_dir(ws, source["pack_id"])
    (run / "result.json").write_bytes(raw)
    (run / "report.html").write_text(page_html(result, raw), encoding="utf-8")
    met, total = came_through(result)
    folder = inside(ws, ws / "packs" / source["pack_id"])
    folder.mkdir(parents=True, exist_ok=True)
    rel = run.relative_to(ws).as_posix()  # relative, so the folder can move or be mounted elsewhere
    wsm.record(folder, args.src, result["x-pack"]["definition_digest"], source["pack_version"], generated_at,
               run=rel, rehearsal=args.dry_run)
    st = wsm.state(folder)
    ref = wsm.dataset_ref(args, deals, ws) or st.get("dataset")
    changed = bool(st.get("dataset")) and st["dataset"].get("sales_digest") != ref.get("sales_digest")
    st.update(pack_id=source["pack_id"], dataset=ref,
              last_run={"run": rel, "digest": result["x-pack"]["definition_digest"], "at": generated_at})
    wsm.save_state(folder, st)
    refresh_or_say(args.src, deals, ws)
    return out({"dataset_changed": changed, "run": str(run), "result": str(run / "result.json"), "page": str(run / "report.html"),
                "rehearsal": bool(args.dry_run), "came_through": met, "sales": total,
                "missed": undecided_or_missed(result, "not_met"),
                "could_not_decide": undecided_or_missed(result, "not_evaluable"),
                "pack_digest": result["x-pack"]["definition_digest"],
                "result_sha256": hashlib.sha256(raw).hexdigest()})


_SCRIPT = re.compile(r'<script type="application/json" id="terms-result" data-sha256="([0-9a-f]{64})" '
                     r'data-rehearsal="(true|false)" data-pack-digest="([0-9a-f]{64})">(.*?)</script>', re.S)


def cmd_verify(args):
    page = pathlib.Path(args.page)
    try:
        text = page.read_text(encoding="utf-8")
    except OSError as e:
        return out({"verified": False, "issues": [f"cannot read {args.page}: {e}"]}, 1)
    m = _SCRIPT.search(text)
    if not m:
        return out({"verified": False, "issues": ["the page carries no terms-result record"]}, 1)
    declared, rehearsal, pack_digest, body = m.groups()
    raw = body.encode()
    issues = []
    if hashlib.sha256(raw).hexdigest() != declared:
        issues.append("the embedded record does not match the digest the page states")
    try:
        result = json.loads(raw)
        met, total = came_through(result)
    except (ValueError, KeyError, TypeError, AttributeError, result_v0.RollupError) as e:
        return out({"verified": False, "issues": issues + [f"the embedded record is not a Result: {e}"]}, 1)
    try:
        edited = not issues and page_html(result, raw) != text
    except (KeyError, TypeError, AttributeError):
        return out({"verified": False, "issues": issues + ["the embedded record is not a terms Result"]}, 1)
    if edited:
        issues.append("the page is not what the embedded record draws: it was edited")
    sibling = page.with_name("result.json")
    if sibling.exists() and sibling.read_bytes() != raw:
        issues.append("result.json beside the page is not the same bytes")
    return out({"verified": not issues, "issues": issues, "came_through": met, "sales": total,
                "rehearsal": bool(result.get("x-rehearsal")), "pack_digest": pack_digest,
                "result_sha256": declared}, 1 if issues else 0)


def read_result(arg, ws=None):
    path = pathlib.Path(arg)
    if ws is not None and not path.is_absolute() and (ws / path).exists():
        path = ws / path  # a run as `history` prints it, relative to the workspace
    elif ws is not None and not path.exists():
        path = wsm.run_of_digest(ws, arg)
    if path.is_dir():
        path = path / "result.json"
    try:
        result = json.loads(path.read_text())
        result["x-pack"]["rows"]
    except (OSError, ValueError, KeyError) as e:
        raise TermsError(f"{arg} is not a terms Result: {e}")
    return result


def cmd_compare(args):
    ws = workspace_of(args, create=False)
    a, b = read_result(args.a, ws), read_result(args.b, ws)
    ta, tb = by_deal(a), by_deal(b)
    if set(ta) != set(tb):
        raise TermsError("the two runs are over different sales; compare runs over the same sales")
    sales_a, sales_b = a["x-pack"].get("sales"), b["x-pack"].get("sales")
    if not isinstance(sales_a, dict) or not isinstance(sales_b, dict) or set(sales_a) != set(ta):
        raise TermsError("a run does not record its sales' digests; run both again, then compare")
    if sales_a != sales_b:
        raise TermsError("the two runs read different records for the same sales; compare runs over the same records")
    rows_a = {r["id"]: r for r in a["x-pack"]["rows"]}
    rows_b = {r["id"]: r for r in b["x-pack"]["rows"]}
    common = [r for r in rows_a if r in rows_b]
    rows, lines = [], []
    for rid in common:
        improved = sum(1 for d in ta if tb[d][rid] == "met" and ta[d][rid] != "met")
        regressed = sum(1 for d in ta if ta[d][rid] == "met" and tb[d][rid] != "met")
        ties = len(ta) - improved - regressed
        kind = ("Tradeoff" if improved and regressed else "Improvement" if improved else
                "Regression" if regressed else "Tie")
        changed = rows_a[rid]["row_digest"] != rows_b[rid]["row_digest"]
        rows.append({"row": rid, "result": kind, "improved": improved, "regressed": regressed, "tied": ties,
                     "row_changed": changed})
        lines.append(f"{rid}: {kind} ({improved} improved, {regressed} regressed, {ties} ties)"
                     + (", row reworded or changed" if changed else ""))
    added, removed = sorted(set(rows_b) - set(rows_a)), sorted(set(rows_a) - set(rows_b))
    same_rows = not added and not removed
    (ma, na), (mb, nb) = came_through(a), came_through(b)
    lines.append(f"sales that came through: {ma} of {na} before, {mb} of {nb} after")
    return out({
        "same_rows": same_rows, "rows_added": added, "rows_removed": removed, "rows": rows,
        "before": {"pack_digest": a["x-pack"]["definition_digest"], "came_through": ma, "sales": na,
                   "rehearsal": bool(a.get("x-rehearsal"))},
        "after": {"pack_digest": b["x-pack"]["definition_digest"], "came_through": mb, "sales": nb,
                  "rehearsal": bool(b.get("x-rehearsal"))},
        "summary": lines})


def rules_checker_pin(source, compiled_path, digest):
    """The pin file `capsulectl profile update --rules-checker` reads. `kind` is the
    pack's own scope.kind, never assumed: capsulectl shares a pin with the
    counterparty only when it states "deal"."""
    return {"command": [str(pathlib.Path(__file__).resolve().parent / "terms-checker"), str(compiled_path.resolve())],
            "timeout": "10s", "definition_digest": digest, "kind": source["scope"]["kind"]}


def cmd_publish(args):
    source = load_pack(args.src)
    ws = workspace_of(args)
    compiled = deal_pack.compiled(source)
    dest = inside(ws, ws / "published" / source["pack_id"] / compiled["definition_digest"][:12])
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("compiled.json", "pack-source.yaml", "rules-checker.json"):
        if (dest / name).is_symlink():
            raise TermsError(f"{dest / name} is a link; refusing to write through it")
    (dest / "compiled.json").write_text(json.dumps(compiled, indent=2) + "\n", encoding="utf-8")
    shutil.copyfile(args.src, dest / "pack-source.yaml")
    # The pin file `capsulectl profile update --rules-checker` reads (the executable must
    # also sit under a trusted plugin root): the checker, the compiled pack it reads, the digest.
    pin = rules_checker_pin(source, dest / "compiled.json", compiled["definition_digest"])
    (dest / "rules-checker.json").write_text(json.dumps(pin, indent=2) + "\n")
    folder = inside(ws, ws / "packs" / source["pack_id"])
    folder.mkdir(parents=True, exist_ok=True)
    wsm.record(folder, args.src, compiled["definition_digest"], source["pack_version"],
               wsm.now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"), published=dest.relative_to(ws).as_posix())
    return out({"pack_id": source["pack_id"], "pack_version": source["pack_version"],
                "definition_digest": compiled["definition_digest"], "published": str(dest),
                "compiled": str(dest / "compiled.json"), "rules_checker_pin": str(dest / "rules-checker.json"),
                "in_force": False,
                "install": shlex.join(["capsulectl", "profile", "update", "--profile", "deal", "--rules-checker",
                                       str(dest / "rules-checker.json")])})


def pack_folder(args):
    """(workspace, SRC, the pack's folder): history lives at packs/<pack_id> wherever SRC sits, as `run` writes it."""
    ws = workspace_of(args, create=False)
    path = pathlib.Path(args.src).resolve()
    try:
        pack_id = pack_compile.load_source(path.read_text())["pack_id"]
    except (OSError, yaml.YAMLError, KeyError, TypeError) as e:
        # a source broken by an edit can still be restored when it sits in its own pack folder
        if path.parent.parent == ws / "packs":
            pack_id = path.parent.name
        else:
            raise TermsError(f"cannot read a pack_id from {args.src}: {e}")
    if not isinstance(pack_id, str) or not re.fullmatch(r"[a-z][a-z0-9_-]*", pack_id):
        raise TermsError(f"{args.src} has no usable pack_id")
    return ws, path, inside(ws, ws / "packs" / pack_id)


def cmd_history(args):
    ws, path, folder = pack_folder(args)
    st = wsm.state(folder)
    table = readiness.read_json(folder / "readiness.json", None)
    return out({"pack": str(path), "workspace": str(ws), "dataset": st.get("dataset"), "last_run": st.get("last_run"),
                "readiness": table["counts"] if isinstance(table, dict) and "counts" in table else None,
                "history": wsm.history(folder)})


def cmd_checkout(args):
    if pathlib.Path(args.src).is_symlink():
        raise TermsError(f"{args.src} is a link; refusing to write through it")
    ws, path, folder = pack_folder(args)
    inside(ws, path)  # the one file checkout overwrites
    try:
        current = deal_pack.compiled(load_pack(args.src))["definition_digest"]
    except TermsError:
        if not args.force:
            raise TermsError(f"{args.src} does not lint, so its changes cannot be told from a recorded digest; pass --force to discard them")
        current = None
    entry = wsm.checkout(folder, path, args.digest, current, args.force)
    refresh_or_say(args.src, None, ws)
    out_ = {"restored": entry["digest"], "version": entry["version"], "pack": str(path), "replaced": current}
    ran = current and any(e["digest"] == current and e.get("run") for e in wsm.history(folder))
    where = f" --workspace {shlex.quote(str(ws))}"
    out_["next"] = f"terms run {shlex.quote(args.src)}{where}" + (
        f", then terms compare {current[:12]} {entry['digest'][:12]}{where}" if ran else "")
    return out(out_)


def cmd_keep_transcript(args):
    ws, path, folder = pack_folder(args)
    folder.mkdir(parents=True, exist_ok=True)
    return out({"kept": str(wsm.keep_transcript(folder, args.file, wsm.now_utc())), "private": True})


def main(argv):
    ap = argparse.ArgumentParser(prog="terms", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("lint", "test", "publish"):
        p = sub.add_parser(name)
        p.add_argument("src")
        if name == "publish":
            p.add_argument("--workspace")
        if name == "test":
            p.add_argument("--engine", help="a capsule-engine binary, to decide admission cases (default: $CAPSULE_ENGINE)")
            p.add_argument("--live-engine", help="the Python capsule-engine CLI, to decide live cases (default: $CAPSULE_LIVE_ENGINE)")
            p.add_argument("--engine-commit", help=f"refuse an engine not built from this commit (at least {MIN_COMMIT_PREFIX} characters of it)")
    p = sub.add_parser("run")
    p.add_argument("src")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--deals", help="JSON file of sales: a list, or {\"trades\": [...]}; omit all three to reuse the dataset the workspace remembers")
    g.add_argument("--exports", help="directory of `capsulectl deal export` files, one per deal, named <deal id>.json")
    g.add_argument("--store", help="a seller's store home (XDG_HOME): reads its closed deals through capsulectl")
    p.add_argument("--dry-run", action="store_true", help="rehearsal: stamp the page, switch nothing on")
    p.add_argument("--workspace")
    p.add_argument("--generated-at")
    p = sub.add_parser("init")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--deals", help="JSON file of sales: a list, or {\"trades\": [...]}")
    g.add_argument("--exports", help="directory of `capsulectl deal export` files, one per deal")
    g.add_argument("--store", help="a seller's store home (XDG_HOME): reads its closed deals through capsulectl")
    p.add_argument("--pack-id", default="sale-terms")
    p.add_argument("--title")
    p.add_argument("--workspace")
    p = sub.add_parser("readiness")
    p.add_argument("src")
    p = sub.add_parser("verify")
    p.add_argument("page")
    p = sub.add_parser("compare")
    p.add_argument("a", help="the earlier run's result.json or run directory, or a pack digest (6+ characters) from `terms history`")
    p.add_argument("b", help="the later run's result.json or run directory, or a pack digest")
    p.add_argument("--workspace")
    p = sub.add_parser("history")
    p.add_argument("src")
    p.add_argument("--workspace")
    p = sub.add_parser("checkout")
    p.add_argument("src")
    p.add_argument("digest", help="a pack digest (6+ characters) from `terms history`")
    p.add_argument("--force", action="store_true", help="discard changes no run or publish has recorded")
    p.add_argument("--workspace")
    p = sub.add_parser("keep-transcript")
    p.add_argument("src")
    p.add_argument("file", help="an authoring transcript to keep, privately, beside the pack (nothing keeps one otherwise)")
    p.add_argument("--workspace")
    args = ap.parse_args(argv)
    try:
        code = {"lint": cmd_lint, "test": cmd_test, "run": cmd_run, "verify": cmd_verify, "init": cmd_init,
                "readiness": cmd_readiness, "compare": cmd_compare, "publish": cmd_publish, "history": cmd_history,
                "checkout": cmd_checkout, "keep-transcript": cmd_keep_transcript}[args.cmd](args)
        if args.cmd in ("lint", "test"):
            refresh_or_say(args.src)
        return code
    except (TermsError, result_v0.RollupError, ValueError) as e:  # WorkspaceError is a ValueError
        return out({"error": str(e)}, 1)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
