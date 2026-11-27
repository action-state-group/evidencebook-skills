# SPDX-License-Identifier: Apache-2.0
"""The airline's sample report on one case, at two disclosure levels, each verified.

    uv run python report.py CASE_DIR

1. Cuts the deal store's next checkpoint tick (a report rests on one), waiting for it
   when it is not yet due: up to the store's cadence interval and jitter.
2. Seals the airline's own report (``deal report --out``).
3. Writes two Evidence Bundles of it: ``keep`` (the airline's own view, nothing
   withheld) and ``adjudicator`` (the copy for the judge: rows withheld, the
   share put on record before the file is written).
4. Runs ``capsulectl deal verify --bundle`` on each (core's checks plus the x-deal-v1
   report rule) and keeps the result, with core ``capsulectl verify --bundle``'s beside it.
5. Writes ``report.html``, one page showing both levels side by side with the
   evaluator's signed verdict and the OTel join, from those same files.

x-deal-v1 has no report page of its own yet (``deal report --html`` refuses a v1
deal), so the page is the demo's. It shows what the files say and checks nothing
itself: ``capsulectl deal verify`` is the check.
"""
from __future__ import annotations

import argparse
import html
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import records

HERE = Path(__file__).resolve().parent


def wait_for_checkpoint(store: records.Store, book: str) -> dict:
    """Cut the store's next checkpoint tick, waiting for it when it is not yet due.

    A tick checkpoints everything sealed before it, so the first one cut now or later covers the
    case. ``deal tick`` cuts one at once when it is due; otherwise it says when it will be
    (``due``), and ``deal tick --wait-up-to`` just past that time takes that one tick and returns:
    the next is at least half a cadence interval later, outside the window. A tick another poll cuts in
    the meantime covers the case as well; ``deal report`` refuses a book its checkpoint does not
    cover."""
    tick = store.run("deal", "tick", profile=book)
    if tick.get("state") != "ticked":
        due = datetime.fromisoformat(tick["due"].replace("Z", "+00:00"))
        wait = max(0, math.ceil((due - datetime.now(timezone.utc)).total_seconds())) + 2
        tick = store.run("deal", "tick", "--wait-up-to", f"{wait}s", profile=book)
    return tick


def verify(store: records.Store, bundle: Path, deal: bool = True) -> dict:
    """``capsulectl deal verify --bundle``: core's checks plus the x-deal-v1 report rule
    (xdealv1.VerifyReportBundle). Core ``capsulectl verify --bundle`` alone does not run
    that rule and says so (on rc53 it answers VALID with a "Not checked here" note naming x-deal-v1)."""
    cmd = [store.capsulectl] + (["deal", "verify"] if deal else ["verify"]) + ["--bundle", str(bundle)]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=store.env(), stdin=subprocess.DEVNULL)
    lines = proc.stdout.strip().splitlines()
    result = json.loads(lines[-1]) if lines else {}
    result["exit_code"] = proc.returncode
    result["command"] = " ".join(cmd[1:3] if deal else cmd[1:2]) + " --bundle"
    return result


def build(store: records.Store, case_dir: Path, judge_label: str = "tau2 evaluator") -> dict:
    case = records.load_case(store, case_dir)
    out = case_dir / "report"
    out.mkdir(exist_ok=True)
    tick = wait_for_checkpoint(store, case.book)
    sealed_path = out / "report-sealed.json"
    if sealed_path.exists():
        sealed_path.unlink()  # a re-run seals a new report as of its own checkpoint
    sealed = store.run("deal", "report", "--deal", case.deal_id, "--out", str(sealed_path), profile=case.book)
    bundles = {}
    for level, extra in (("keep", []), ("adjudicator", ["--share", "adjudicator", "--to", judge_label])):
        path = out / f"bundle-{level}.json"
        if path.exists():
            path.unlink()  # a bundle is a snapshot; a re-run writes a fresh one
        result = store.run("deal", "report", "--deal", case.deal_id, *extra, "--bundle", str(path), profile=case.book)
        bundles[level] = {"file": path.name, "report": result.get("report"), "verify": verify(store, path),
                          "core_verify": verify(store, path, deal=False)}
        (out / f"verify-{level}.json").write_text(json.dumps(bundles[level]["verify"], indent=1))
        (out / f"core-verify-{level}.json").write_text(json.dumps(bundles[level]["core_verify"], indent=1))
    summary = {"book": case.book, "window": case.window, "deal_id": case.deal_id, "tick": tick, "sealed": sealed_path.name, "bundles": bundles}
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    (out / "report.html").write_text(page(case_dir, summary))
    return summary


def page(case_dir: Path, summary: dict) -> str:
    """One self-contained page: the two levels side by side, from the files on disk."""
    e = lambda v: html.escape(str(v))  # noqa: E731
    task = json.loads((case_dir / "task.json").read_text())
    evaluation = json.loads((case_dir / "evaluation.json").read_text()) if (case_dir / "evaluation.json").exists() else None
    calls = [json.loads(line) for line in (case_dir / "tool_calls.jsonl").read_text().splitlines()] \
        if (case_dir / "tool_calls.jsonl").exists() else []
    acts = [c for c in calls if c.get("perform")]

    def column(level: str) -> str:
        b = summary["bundles"][level]
        rep = b.get("report") or {}
        rows = rep.get("rows") or []
        v = b["verify"]
        rows_html = "".join(f"<tr><td>{e(r.get('row') or r.get('id'))}</td><td>{e(r.get('status') or r.get('value') or json.dumps(r)[:80])}</td></tr>"
                            for r in rows) or f"<tr><td colspan=2><em>rows {e(rep.get('rows_state', 'none'))}</em></td></tr>"
        return f"""<section class="level"><h2>{'The airline’s own view (keep)' if level == 'keep' else 'The judge’s copy (adjudicator)'}</h2>
<p class="verdict {'ok' if v.get('verdict') == 'VALID' else 'bad'}">capsulectl deal verify: <b>{e(v.get('verdict', 'no verdict'))}</b> (exit {e(v.get('exit_code'))})</p>
<p>audience <code>{e(rep.get('audience'))}</code>, as of <code>{e(rep.get('as_of'))}</code></p>
<table><tr><th>row</th><th>status</th></tr>{rows_html}</table>
<p class="file">bundle: <code>{e(b['file'])}</code>, digest <code>{e(v.get('bundle_digest', ''))[:16]}…</code></p></section>"""

    acts_html = "".join(f"<li><code>{e(a['tool'])}</code> perform <code>{e(a['perform'][:12])}</code> on span <code>{e(a.get('span_id'))}</code> (trace <code>{e(str(a.get('trace_id'))[:12])}…</code>), confirmed by message <code>{e(a['confirmation'][:12])}</code></li>" for a in acts) or "<li>no database change in this case</li>"
    eval_html = "<p>not evaluated yet</p>" if evaluation is None else (
        f"<p>signed by the evaluator's own key, record <code>{e(evaluation['evaluation_capsule_id'])}</code>; judge <code>{e(evaluation['judge_model_id'])}</code></p>"
        + "<table><tr><th>check</th><th>verdict</th></tr>" + "".join(f"<tr><td>{e(k)}</td><td>{e(v)}</td></tr>" for k, v in evaluation["checks"].items()) + "</table>")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Support case report: tau2 airline task {e(task['id'])}</title>
<style>body{{font:15px/1.5 system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#1d2433}}
.levels{{display:grid;grid-template-columns:1fr 1fr;gap:1.5rem}}.level{{border:1px solid #d6dbe4;border-radius:8px;padding:1rem}}
table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #e6e9ef;text-align:left;padding:.3rem}}
.ok{{color:#11663a}}.bad{{color:#a11}}code{{font-size:.85em}}.note{{color:#556;font-size:.9em}}</style></head><body>
<h1>Support case report: a fictional airline, tau2 airline task {e(task['id'])}</h1>
<p>Deal store <code>{e(summary['book'])}</code>, window <code>{e(summary.get('window'))}</code>, deal <code>{e(summary['deal_id'])}</code>. A live role-play between two agents, sealed as it happened: not a replay of a benchmark transcript.</p>
<div class="levels">{column('keep')}{column('adjudicator')}</div>
<h2>The evaluator's verdict (side by side, not merged)</h2>{eval_html}
<h2>Acts and their OTel spans</h2><ul>{acts_html}</ul>
<p class="note">Each act's span carries only the record's capsule id (<code>aac.capsule_id</code>); the record stays in the book.
Every act shows <code>person_signature: missing</code>: no person's own signature format exists yet (agent-action-capsule#627).
The deal store is split into windows; this case is in window <code>{e(summary.get('window'))}</code>. A report over a range of windows, with its coverage check, is not in this demo.
The customer keeps no signed records of its own, so there is no counterparty copy here.</p>
<p class="note"><b>What VALID covers.</b> Each bundle carries the sealed report and the deal-book records it cites (the agreement and the acts).
The conversation, the customer's "yes", the policy check and the evaluator's verdict sit in the books, outside these bundles.
VALID does not say the airline handled the case well; that is the evaluator's verdict, which is cited, not applied to the rows.
The rows read <code>not_due</code> because each falls due a week after the case opens.
No witness co-signs the checkpoint: it and the report's <code>as_of</code> are the airline's own word.
The demo operator runs the evaluator and both agents, so the verdict is not independent.</p>
</body></html>
"""


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("case_dir", type=Path)
    p.add_argument("--state", type=Path, default=HERE / "state")
    p.add_argument("--allow-incomplete", action="store_true", help="report on a case whose role-play did not complete")
    a = p.parse_args()
    records.require_complete(a.case_dir.resolve(), a.allow_incomplete)
    summary = build(records.Store(state=a.state.resolve()), a.case_dir.resolve())
    for level, b in summary["bundles"].items():
        print(f"{level}: {b['file']} verify {b['verify'].get('verdict')} (exit {b['verify']['exit_code']})")
    print(f"page: {a.case_dir.resolve() / 'report' / 'report.html'}")


if __name__ == "__main__":
    main()
