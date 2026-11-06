"""Run the met / not_met cases of a non-deal pack for `terms test`.

Each runner takes the pack's cases (scripts/studio/two_case.py) and returns one
dict per row. A row either ran (`evaluated: True`, with `met_case`, `miss_case`
and `passed`, and who decided it) or did not (`evaluated: False`, with the
reason). A case that cannot run -- no engine, no model key -- is never reported
passed: the caller sets `passed` to null while any row is unrun.

    admission  the capsule-engine binary (`capsule-engine admission evaluate`),
               named by --engine or $CAPSULE_ENGINE, optionally pinned to a
               commit with --engine-commit
    evaluator  the pack's own evaluator in scripts/evaluators, over the sealed
               records the case carries: {"records": [<capsule>, ...], "date": "YYYY-MM-DD"}
    live       capsule-engine has no entry point for a pack and a list of actions
               yet (capsule-engine#286): not evaluated
    judged     the pinned judge needs a model key, and a real judged run waits for
               the owner's go: not evaluated
"""
import datetime
import hashlib
import json
import os
import pathlib
import subprocess
import tempfile

import admission_pack
import two_case

ROW_RESULTS = {"pass": "met", "fail": "not_met"}
GENERATED_AT = "2026-01-01T00:00:00Z"  # a case's Result is read, never kept


def not_run(source, reason):
    return [{"row": r, "met_case": "not_evaluated", "miss_case": "not_evaluated", "evaluated": False,
             "reason": reason} for r in two_case.row_ids(source)]


def by_row(cases):
    out = {}
    for c in cases:
        out.setdefault(c["row"], {})[c["case"]] = c["input"]
    return out


def row_report(row, got, who):
    ok = got == ("met", "not_met")
    return {"row": row, "met_case": got[0], "miss_case": got[1], "evaluated": True, "passed": ok, **who}


def engine_identity(path):
    """(identity, None) of a capsule-engine binary, or (None, why not). The commit is the
    revision the binary was built from (`go version -m`); the digest is of its bytes."""
    p = pathlib.Path(path)
    if not p.is_file() or not os.access(p, os.X_OK):
        return None, f"{path} is not an executable capsule-engine"
    ident = {"name": "capsule-engine", "path": str(p.resolve()), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
    try:
        info = subprocess.run(["go", "version", "-m", str(p)], capture_output=True, text=True, timeout=30,
                              stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.SubprocessError):
        info = ""
    for line in info.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == "build":
            if parts[1].startswith("vcs.revision="):
                ident["commit"] = parts[1].split("=", 1)[1]
            elif parts[1] == "vcs.modified=true":
                ident["modified"] = True
    return ident, None


def run_admission(source, cases, engine, engine_commit):
    if not engine:
        return not_run(source, "no capsule-engine to decide it: pass --engine PATH or set CAPSULE_ENGINE "
                               "(a build of go/cmd/capsule-engine)")
    ident, why = engine_identity(engine)
    if why:
        return not_run(source, why)
    if engine_commit and not (ident.get("commit") or "").startswith(engine_commit):
        return not_run(source, f"the engine is built from {ident.get('commit', 'an unknown revision')}, "
                               f"not the pinned {engine_commit}")
    definition = admission_pack.compiled_bytes(source)
    definition = definition if isinstance(definition, bytes) else definition.encode()
    digest = hashlib.sha256(definition).hexdigest()
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        pack_file = pathlib.Path(tmp) / "pack-definition.json"
        pack_file.write_bytes(definition)
        for row, pair in by_row(cases).items():
            got = []
            for name in two_case.CASES:
                case_file = pathlib.Path(tmp) / "case.json"
                case_file.write_text(json.dumps(pair[name]))
                try:
                    r = subprocess.run([engine, "admission", "evaluate", "--pack", str(pack_file), "--pack-id",
                                        source["pack_id"], "--digest", digest, "--input", str(case_file)],
                                       capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
                    if r.returncode != 0:
                        raise ValueError(f"refused: {(r.stderr or r.stdout).strip()[:300]}")
                    decided = {x["row"]: x["result"] for x in json.loads(r.stdout)["rows"]}
                except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as e:
                    rows.append({"row": row, "met_case": "not_evaluated", "miss_case": "not_evaluated",
                                 "evaluated": False, "reason": f"the engine could not decide the {name} case: "
                                 f"{type(e).__name__}: {e}"})
                    break
                got.append(ROW_RESULTS.get(decided.get(row), decided.get(row, "not_decided")))
            else:
                rows.append(row_report(row, tuple(got), {"decided_by": ident, "pack_digest": digest}))
    return rows


def evaluator_identity(module):
    """The evaluator that ran, by the digest of its source: it has no release of its own."""
    f = pathlib.Path(module.__file__)
    return {"name": f.stem, "path": f"scripts/evaluators/{f.name}", "sha256": hashlib.sha256(f.read_bytes()).hexdigest()}


def run_inference_deals(source, cases):
    import inference_deals
    import pack_compile
    # Compiled from the source under test, never read from a compiled/ file that may be stale.
    compiled = pack_compile.build_deterministic_compiled_json(source)
    rows = []
    for row, pair in by_row(cases).items():
        got = []
        for name in two_case.CASES:
            inp = pair[name]
            try:
                records = [(c["capsule_id"], c) for c in inp["records"]]
                doc, _ = inference_deals.build_result(records, compiled, datetime.date.fromisoformat(inp["date"]),
                                                      GENERATED_AT)
                mine = [c for c in doc["claims"] if c["requirement_ref"] == row]
                if len(mine) != 1:
                    raise ValueError(f"a case must carry exactly one counted deal for the row; it gave {len(mine)}")
            except (KeyError, TypeError, ValueError, inference_deals.DealsError) as e:
                got.append(None)
                why = f"the {name} case could not be built into a Result: {type(e).__name__}: {e}"
                break
            got.append(mine[0]["verdict"])
        if None in got:
            rows.append({"row": row, "met_case": "not_evaluated", "miss_case": "not_evaluated",
                         "evaluated": False, "reason": why})
            continue
        rows.append(row_report(row, tuple(got), {"decided_by": evaluator_identity(inference_deals)}))
    return rows


EVALUATORS = {"inference_deals": run_inference_deals}


def run(kind, source, cases, engine=None, engine_commit=None, environ=None):
    environ = os.environ if environ is None else environ
    if kind == "admission":
        return run_admission(source, cases, engine or environ.get("CAPSULE_ENGINE"), engine_commit)
    if kind == "live":
        return not_run(source, "a live pack's cases are decided by capsule-engine, which has no entry point "
                               "for a pack and a list of actions yet (capsule-engine#286)")
    if source.get("evaluator"):
        runner = EVALUATORS.get(source["evaluator"])
        if runner is None:
            return not_run(source, f"no case runner for the {source['evaluator']} evaluator")
        return runner(source, cases)
    if not environ.get("TYPESAFE_API_KEY"):
        return not_run(source, f"a {kind} pack's cases are judged by its pinned judge, which needs a model key "
                               "(TYPESAFE_API_KEY), and none is set")
    return not_run(source, f"a {kind} pack's cases are judged by its pinned judge; a judged run costs money "
                           "and waits for the owner's go, so terms test does not run it yet")
