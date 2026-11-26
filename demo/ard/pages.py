# SPDX-License-Identifier: Apache-2.0
"""Each party's History card as a page on screen (design note ``docs/design/ard-buyer-seller-skills.md``
§3.6 item 11).

The page is capsule-viewer's History view (``history-view/v0``, capsule-viewer
``docs/design/history-view.md``), drawn by the released script itself: ``vendor/capsule-viewer-0.27.2/
history-view.iife.js`` is ``dist/history-view.iife.js`` of the npm package
``@action-state-group/capsule-viewer@0.27.2``, copied unchanged with the package's own ``.sha256`` and
licences, and :data:`VIEWER_SHA256` pins it. The view draws and never verifies: the party builds the
view model from its own ``standard_history/3`` card (``capsulectl deal standard-history card``, its own copy, which
lists the deal entries the card counts), and the page inlines the script and the model, so it opens offline and
fetches nothing (its Content-Security-Policy is ``default-src 'none'``).

Each deal row says each of its rows' status as capsulectl computed it (``agreed``, ``ruled`` and the rest): the
demo derives no outcome of its own. The view has no member for disputes (capsule-viewer 0.27.2 and main), so the
card's dispute tally is one plain line above the view, in the words the chat uses. The page carries no demo banner
(Ethan, 2026-11-17)."""
from __future__ import annotations

import hashlib
import html
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import party as pt
import screens

HERE = Path(__file__).resolve().parent
VIEWER = "capsule-viewer-0.27.2"
VIEWER_DIR = HERE / "vendor" / VIEWER
VIEWER_SCRIPT = VIEWER_DIR / "history-view.iife.js"
#: The package's own digest of the script (``dist/history-view.iife.js.sha256``).
VIEWER_SHA256 = "b7dab1cfae794f42104d0cede6e9debda88f6af94ca8da5bffc31580b8d72d17"
DEFAULT_HOME = "~/.config/ard-commerce-demo"


class PageError(RuntimeError):
    pass


def home() -> Path:
    return Path(os.environ.get("ARD_HOME", DEFAULT_HOME)).expanduser()


def viewer_script() -> str:
    data = VIEWER_SCRIPT.read_bytes()
    got = hashlib.sha256(data).hexdigest()
    if got != VIEWER_SHA256:
        raise PageError(f"{VIEWER_SCRIPT} is not the pinned capsule-viewer script (sha256 {got})")
    return data.decode()


STATUS = {"agreed": "met", "agreed_so_far": "met so far", "uncontested": "met, not contested", "ruled": "ruled",
          "in_dispute": "in dispute", "in_disagreement": "disputed", "waiting": "waiting", "not_due": "not due yet",
          "no_statement": "no statement", "not_reached": "never set"}


def _rows_text(rows: list[dict]) -> str:
    """A deal's rows as capsulectl computed them, holder's row first: "delivery (this party's): ruled, not met"."""
    out = []
    for r in sorted(rows, key=lambda r: r.get("owed_by") != "holder"):
        whose = "this party's" if r.get("owed_by") == "holder" else "the other party's"
        value = {"met": "met", "not_met": "not met"}.get(r.get("value") or "", "")
        out.append(f"{whose} row: {STATUS.get(r.get('status', ''), r.get('status', ''))}" + (f", {value}" if value and r.get("status") == "ruled" else ""))
    return "; ".join(out)


def _money(amount: dict) -> str:
    """A /3 entry's amount is its band's floor (evidencebook ``bandAmount``): say it as a band."""
    value, code, scale = amount.get("value", ""), amount.get("assetCode", ""), amount.get("assetScale")
    if code == "BTC" and scale == 8:
        return f"from {int(value):,} sat (its value band)"
    return f"from {value} {code} (its value band, scale {scale})"


def history_input(deals: list[dict], *, name: str, built_at: str, witnessed: dict | None) -> dict:
    """The ``history-view/v0`` model of a party's own card: one row per deal the card counts, newest first.
    ``witnessed`` is ``{"by", "at"}`` of the witnessed checkpoint the card is anchored on, or ``None``."""
    rows = []
    for d in sorted(deals, key=lambda d: d["agreed_at"], reverse=True):
        verb = {"provided": "Sold", "bought": "Bought"}.get(d.get("role", ""), "Deal")
        second = ({"state": "passed", "by": "the other party", "at": d["agreed_at"]}
                  if d.get("happened") == "stamped_by_both" else {"state": "none"})
        rows.append({"kind": "deal", "asked": verb, "outcome": _rows_text(d.get("rows", [])),
                     "money": _money(d["amount"]), "opened_at": d["agreed_at"], "last_at": d["agreed_at"],
                     "record": d["deal"][:16], "witness": ({"state": "passed", **witnessed} if witnessed else {"state": "none"}),
                     "second_signature": second})
    stamped = bool(rows) and all(r["second_signature"]["state"] == "passed" for r in rows)
    return {
        "view": "history-view/v0", "kind": "deal", "surface": "neutral", "reader": "owner",
        "holder": {"name": name}, "audience": {"kind": "private"}, "built_at": built_at,
        "checked": {"where": "builder", "by": "this party's own profile, from its sealed records (capsulectl)"},
        "rows": rows,
        "checks": [{"id": "second_signature", "status": "pass" if stamped else "not_run"},
                   {"id": "witness", "status": "pass" if witnessed and rows else "not_run"}],
    }


#: Said on a card page whose rows read witnessed: the witness is run by Action State, as is every party here.
WITNESS_NOTE = (f"Time-stamped by {pt.WITNESS_NAME}. Action State also runs every party here, so the witness is not "
                "independent of them.")


def labels(card: dict, witnessed: bool, sample: str = "") -> list[str]:
    """The lines above the view: who time-stamped it, the card's counts with its dispute tally (the view has no member
    for disputes), and, on a seller's card (``sample``: the seller), that its first deals are sample history."""
    return ([WITNESS_NOTE] if witnessed else []) + [screens.card_line(card)] + ([screens.sample_note(sample)] if sample else [])


def _script_json(value: dict) -> str:
    """JSON safe inside a <script> element: no "</" or "<!--" can end or bend it."""
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


_HOST_CSS = (".ard-labels{font:13px/1.4 system-ui,sans-serif;margin:0;padding:8px 16px;color:#57606a}"
             ".ard-labels p{margin:0}")


def history_page(view_input: dict, page_labels: list[str], title: str) -> str:
    """A self-contained page: the labels, then capsule-viewer's History view drawn by its own script."""
    notes = "".join(f"<p>{html.escape(t)}</p>" for t in page_labels)
    return (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>{html.escape(title)}</title><style>{_HOST_CSS}</style></head><body>"
        + (f"<div class=\"ard-labels\" role=\"note\">{notes}</div>" if page_labels else "") +
        "<div id=\"history\"></div>"
        "<noscript>This page draws its History with capsule-viewer's script; allow scripts for this file.</noscript>"
        f"<script>{viewer_script()}</script>"
        f"<script type=\"application/json\" id=\"history-input\">{_script_json(view_input)}</script>"
        "<script>(function(){var s=document.createElement('style');s.textContent=HistoryView.historyViewStyles;"
        "document.head.appendChild(s);HistoryView.renderHistoryView(JSON.parse("
        "document.getElementById('history-input').textContent),document.getElementById('history'));})();</script>"
        "</body></html>\n")


def path(name: str, kind: str) -> Path:
    """A new page file under the demo home's pages folder (a verb may refuse to overwrite one)."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out = home() / "pages" / f"{name}-{kind}-{stamp}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


def write(name: str, kind: str, page: str) -> Path:
    out = path(name, kind)
    out.write_text(page, encoding="utf-8")
    return out


def card_page(p: pt.Party, label: str, *, rail: str, seller: bool) -> Path:
    """Write the party's History card page from its own card, as of a checkpoint taken now, and return its path."""
    p.stamp()
    bundle = p.card_bundle(shared=False)
    doc = json.loads(bundle.read_text())
    card = doc["disclosures"][doc["records"][0]["capsule_id"]]["agent_input"]
    ext = doc["extensions"]["x-standard-history/v0"]
    out = p.verify(bundle, report_on_fail=True)
    stamp = pt.anchor_witness(out)
    if stamp == "fail":  # never drawn as "not run": a receipt that does not check makes the card INVALID (#957)
        raise pt.Refused(f"Your History card does not verify: {pt.STAMP_FAILED}.")
    if out.get("verdict") != "VALID":
        raise pt.Refused(pt.not_verified("Your History card", out.get("verdict")))
    witnessed = {"by": pt.WITNESS_NAME, "at": ext["as_of"]["anchor_time"]} if stamp == "pass" else None
    view = history_input(ext.get("deals", []), name=label, witnessed=witnessed,
                         built_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    return write(p.name, "history", history_page(view, labels(card, witnessed is not None, sample=p.name if seller else ""),
                                                     f"History · {label}"))


def open_page(path: Path) -> bool:
    """Open the page in the default browser (macOS ``open``); ``ARD_OPEN_PAGES=0`` skips it. True when opened."""
    if os.environ.get("ARD_OPEN_PAGES", "1") == "0":
        return False
    try:
        return subprocess.run(["open", str(path)], stdin=subprocess.DEVNULL, capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
