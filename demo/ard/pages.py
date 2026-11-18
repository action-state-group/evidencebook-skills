# SPDX-License-Identifier: Apache-2.0
"""Each party's History card as a page on screen (design note ``docs/design/ard-buyer-seller-skills.md``
§3.6 item 11).

The page is capsule-viewer's History view (``history-view/v0``, capsule-viewer
``docs/design/history-view.md``), drawn by the released script itself: ``vendor/capsule-viewer-0.18.0/
history-view.iife.js`` is ``dist/history-view.iife.js`` of the npm package
``@action-state-group/capsule-viewer@0.18.0``, copied unchanged with the package's own ``.sha256`` and
licences, and :data:`VIEWER_SHA256` pins it. The view draws and never verifies: the party builds the
view model from its own ``standard_history/1`` card (``Node.standard_history()``) and the checks its own
node ran, and the page inlines the script and the model, so it opens offline and fetches nothing
(its Content-Security-Policy is ``default-src 'none'``).

The demo labels the chat text carries (:mod:`screens`) are on the page, around the view: the DEMO
banner, the label on a "did not hold" counted from the party's own note, and, when this run's Kestrel
answers buyers with a sample card, the sample card label. A row that did not hold says it rests on this
party's own note, not verified.

The receipt is not drawn here: capsule-viewer's receipt modules read the copy's sealed ``deal_report``
named by the bundle's ``x-deal-v0`` extension, and the Goose reference's bundles carry none."""
from __future__ import annotations

import hashlib
import html
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import screens

HERE = Path(__file__).resolve().parent
VIEWER = "capsule-viewer-0.18.0"
VIEWER_DIR = HERE / "vendor" / VIEWER
VIEWER_SCRIPT = VIEWER_DIR / "history-view.iife.js"
#: The package's own digest of the script (``dist/history-view.iife.js.sha256``).
VIEWER_SHA256 = "63c0bdaedbc29ddd9e1377ccf63ac662fbcee291f0cd39382b68d6b39cb32148"
DEFAULT_HOME = "~/.config/ard-commerce-demo"

SAMPLE_LABEL = "sample card, written for this demo; not recomputed from records"
OWN_NOTE = "this party's own note, not verified"


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


def _money(amount: dict) -> str:
    value, code, scale = amount.get("value", ""), amount.get("assetCode", ""), amount.get("assetScale")
    if code == "BTC" and scale == 11:
        return f"{int(value):,} msat"
    return f"{value} {code} (minor units, scale {scale})"


def _outcome(outcome: str, seller: bool) -> str:
    if outcome == "did_not_hold":
        whose = "the seller's" if seller else "this party's"
        return (f"did not hold (counted from {whose} own note, not confirmed by the "
                f"{'buyer' if seller else 'other party'} or a ruling; {OWN_NOTE})")
    return outcome.replace("_", " ")


def history_input(sh: dict, *, name: str, seller: bool, last_at: dict[str, str],
                  seconds: dict[str, tuple[str, str]], built_at: str) -> dict:
    """The ``history-view/v0`` model of a party's own card. ``sh`` is ``Node.standard_history()``;
    ``last_at`` maps a deal id to its last step's time and ``seconds`` maps a deal id to the other party
    whose half this node verified and when (the card's ``stamped_by_both``). Deal rows, newest first."""
    rows = []
    for d in sorted(sh["deals"], key=lambda d: d["agreed_at"], reverse=True):
        deal_id = d["deal"]
        verb = {"provided": "Sold", "bought": "Bought"}.get(d.get("role", ""), d.get("role", "Deal"))
        if d.get("happened") == "stamped_by_both" and deal_id in seconds:
            by, at = seconds[deal_id]
            second = {"state": "passed", "by": by, "at": at}
        else:
            second = {"state": "none"}
        rows.append({"kind": "deal", "asked": f"{verb} at the agreed price", "outcome": _outcome(d["outcome"], seller),
                     "money": _money(d["amount"]), "opened_at": d["agreed_at"],
                     "last_at": last_at.get(deal_id, d["agreed_at"]), "record": deal_id,
                     # The demo runs no witness (CAPSULE_WITNESS=off): no record is time-stamped.
                     "witness": {"state": "none"}, "second_signature": second})
    stamped = bool(rows) and all(r["second_signature"]["state"] == "passed" for r in rows)
    return {
        "view": "history-view/v0", "kind": "deal", "surface": "neutral", "reader": "owner",
        "holder": {"name": name}, "audience": {"kind": "private"}, "built_at": built_at,
        "checked": {"where": "builder", "by": "this party's own node, from its sealed records"},
        "rows": rows,
        "checks": [{"id": "second_signature", "status": "pass" if stamped else "not_run"},
                   {"id": "witness", "status": "not_run"}],
    }


def labels(card: dict, rail: str, seller: bool, sample_card: bool, party: str) -> list[str]:
    """The demo labels this party's page carries, the banner first, then whose page it is."""
    out = [screens.banner(rail), f"{party}: its own History card, drawn from its own sealed records"]
    if card["outcomes"]["did_not_hold"]:
        out.append(f"{card['outcomes']['did_not_hold']} of {card['outcomes']['of']} deals did not hold: did not hold counted from "
                   + ("the seller's own note, not confirmed by the buyer or a ruling" if seller
                      else "this party's own note, not confirmed by the other party or a ruling")
                   + f" ({OWN_NOTE})")
    if sample_card:
        out.append(f"In this run, buyers who ask this seller get a {SAMPLE_LABEL}. This page draws this seller's own records.")
    return out


def _script_json(value: dict) -> str:
    """JSON safe inside a <script> element: no "</" or "<!--" can end or bend it."""
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


_HOST_CSS = (".ard-demo{font:15px/1.4 system-ui,sans-serif;margin:0;padding:12px 16px;background:#5a1d1d;color:#fff}"
             ".ard-demo p{margin:0 0 4px}.ard-demo .banner{font-weight:700}")


def history_page(view_input: dict, page_labels: list[str], title: str) -> str:
    """A self-contained page: the labels, then capsule-viewer's History view drawn by its own script."""
    notes = "".join(f'<p class="{"banner" if i == 0 else "label"}">{html.escape(t)}</p>' for i, t in enumerate(page_labels))
    return (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>{html.escape(title)}</title><style>{_HOST_CSS}</style></head><body>"
        f"<div class=\"ard-demo\" role=\"note\">{notes}</div>"
        "<div id=\"history\"></div>"
        "<noscript>This page draws its History with capsule-viewer's script; allow scripts for this file.</noscript>"
        f"<script>{viewer_script()}</script>"
        f"<script type=\"application/json\" id=\"history-input\">{_script_json(view_input)}</script>"
        "<script>(function(){var s=document.createElement('style');s.textContent=HistoryView.historyViewStyles;"
        "document.head.appendChild(s);HistoryView.renderHistoryView(JSON.parse("
        "document.getElementById('history-input').textContent),document.getElementById('history'));})();</script>"
        "</body></html>\n")


def _deal_times(node, deal_ids: list[str]) -> dict[str, str]:
    """Each deal's last step time, from the party's own deal book."""
    out = {}
    for deal_id in deal_ids:
        payloads = [json.loads(p) for p in node.deal_payloads(deal_id)]
        times = [(p.get("x-deal-v0") or {}).get("at") or p.get("at") for p in payloads]
        times = [t for t in times if t]
        if times:
            out[deal_id] = times[-1]
    return out


def _seconds(node, half_received: str) -> dict[str, tuple[str, str]]:
    """Per deal, the newest counterparty half this node verified: whose key, and when it held it."""
    out = {}
    for r, s in node.notes(half_received):
        if s.get("close_half_digest"):
            out[s["deal_id"]] = (f"the other party (key {s['key_id'][:12]})", r.header.committed_at)
    return out


def write(name: str, kind: str, page: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = home() / "pages" / f"{name}-{kind}-{stamp}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")
    return path


def card_page(node, name: str, label: str, *, rail: str, seller: bool, sample_card: bool,
              half_received: str = "goose_half_received") -> Path:
    """Write the party's History card page from its own records, as of its newest checkpoint (taken now when one
    is due, as :func:`parties.card_view` does), and return its path."""
    node.tick(datetime.now(timezone.utc))
    sh = node.standard_history()
    card = json.loads(sh["card"])
    view = history_input(sh, name=label, seller=seller, last_at=_deal_times(node, [d["deal"] for d in sh["deals"]]),
                         seconds=_seconds(node, half_received),
                         built_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    return write(name, "history", history_page(view, labels(card, rail, seller, sample_card, label), f"History · {label} (DEMO)"))


def open_page(path: Path) -> bool:
    """Open the page in the default browser (macOS ``open``); ``ARD_OPEN_PAGES=0`` skips it. True when opened."""
    if os.environ.get("ARD_OPEN_PAGES", "1") == "0":
        return False
    try:
        return subprocess.run(["open", str(path)], stdin=subprocess.DEVNULL, capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
