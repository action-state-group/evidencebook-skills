"""The calendar, timeline and co-failure views a pack declares for its report
page, and the wording that goes with them (evidencebook-skills#94).

    chart_views.build_block(pack_id) -> the "chart-views/v1" block, or None

Format: capsule-viewer docs/design/report-views.md, "Calendar cells, timeline and
co-failure", over the closed Vega-Lite subset of docs/design/chart-spec.md. The
viewer reads the block's `charts` as its `charts` builder setting and `wording`
as entries of the wording pack, so nothing here is a second schema.

These are DECLARATIONS. A chart spec's `usermeta.capsule` statement (population,
window, runs, values) and its window `range` filter are computed from the sealed
dataset, which the compiler never sees: evidencebook's report builder adds them
before the viewer checks the chart. A spec emitted here is otherwise complete.

The views live here, keyed by pack_id, and not in pack-source.yaml for the reason
pack_compile.CONTRACT_REPORT_PACKS is kept out of it: the judge pin carries
pack_source_digest, so a presentation-only field in a pack source would move the
pin of work already judged. Adding a pack's views changes presentation.json only.

The record field paths below are the dataset rows' (statement.* is a record's
statement, record_type its type). They are the viewer's fixture shape; the
builder half of #94 confirms them against the records the daily run seals.
"""
from __future__ import annotations

import re

BLOCK_KEY = "chart-views/v1"
VEGA_LITE = "https://vega.github.io/schema/vega-lite/v5.json"
WINDOW_FIELD = "event_time_claim"

ROLES = ("activity", "judgment", "adjudication")
CLASSES = ("good", "bad", "open")
MARKS = ("tick", "diamond")
ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

# The wording-pack keys a pack may set (report-views.md "Words"): the calendar's
# nouns and verbs, the legend and the co-failure caption, and a title per
# timeline lane.
WORDING_KEYS = re.compile(
    r"^(calendar\.activity|calendar\.class\.(good|bad|open)|calendar\.adj\.[a-z_]+"
    r"|calendar\.legend\.[a-z_]+|cofail\.failing|lane\.[a-z][a-z0-9_]{0,31}\.title)$")


def _filter(where):
    preds = [{"field": f, "equal": v} for f, v in where]
    return {"filter": preds[0] if len(preds) == 1 else {"and": preds}}


def _x():
    return {"field": WINDOW_FIELD, "type": "temporal", "timeUnit": "utcyearmonthdate"}


def lane_chart(lane):
    """The chart spec for one lane: a bar of counts per UTC day, or, on a keyed
    lane, a rect of day by key value."""
    spec = {"$schema": VEGA_LITE, "data": {"name": "dataset"},
            "transform": [_filter(lane["where"])]}
    if lane.get("key"):
        spec["mark"] = "rect"
        spec["encoding"] = {"x": _x(), "y": {"field": lane["key"], "type": "nominal"},
                            "color": {"aggregate": "count", "type": "quantitative"}}
    else:
        spec["mark"] = "bar"
        spec["encoding"] = {"x": _x(), "y": {"aggregate": "count", "type": "quantitative"}}
    return spec


def cofail_chart(count):
    """The by-period count chart of a co-failure: the failing rows, one key channel
    (the requirement)."""
    return {"$schema": VEGA_LITE, "data": {"name": "dataset"},
            "transform": [_filter(count["where"])], "mark": "bar",
            "encoding": {"x": _x(), "y": {"aggregate": "count", "type": "quantitative"},
                         "color": {"field": count["key"], "type": "nominal"}}}


def _lane_entry(lane):
    entry = {"id": lane["id"], "chart": lane_chart(lane)}
    for member in ("role", "mark", "classes"):
        if lane.get(member):
            entry[member] = dict(lane[member]) if member == "classes" else lane[member]
    return entry


def build_charts(decl):
    charts = []
    if decl.get("calendar"):
        charts.append({"view": "calendar", "lanes": [_lane_entry(l) for l in decl["calendar"]]})
    if decl.get("timeline"):
        charts.append({"view": "timeline", "lanes": [_lane_entry(l) for l in decl["timeline"]]})
    if decl.get("cofail"):
        c = decl["cofail"]
        charts.append({"view": "co-failure",
                       "count": {"id": c["id"], "chart": cofail_chart(c)},
                       "subject": c["subject"]})
    return charts


def validate(decl, where="views"):
    """Every issue found in one pack's declaration."""
    issues = []

    def lanes(name, items, timeline):
        ids = set()
        roles = set()
        if not isinstance(items, list) or not items:
            return [f"{where}.{name} must be a non-empty list"]
        for i, lane in enumerate(items):
            at = f"{where}.{name}[{i}]"
            if not isinstance(lane, dict):
                issues.append(f"{at} must be a mapping")
                continue
            if not ID_RE.match(str(lane.get("id", ""))):
                issues.append(f"{at}.id must match {ID_RE.pattern}")
            elif lane["id"] in ids:
                issues.append(f"{at}.id {lane['id']!r} is used twice")
            ids.add(lane.get("id"))
            w = lane.get("where")
            if not (isinstance(w, list) and w and all(isinstance(p, (list, tuple)) and len(p) == 2
                                                      and isinstance(p[0], str) for p in w)):
                issues.append(f"{at}.where must be a non-empty list of (field, value) pairs")
            role = lane.get("role")
            if role is not None:
                if timeline:
                    issues.append(f"{at}.role is a calendar member; a timeline lane has none")
                elif role not in ROLES:
                    issues.append(f"{at}.role {role!r} is not one of {list(ROLES)}")
                elif role in roles:
                    issues.append(f"{at}.role {role!r} is on more than one lane")
                roles.add(role)
            mark = lane.get("mark")
            if timeline and mark not in MARKS:
                issues.append(f"{at}.mark must be one of {list(MARKS)}")
            if not timeline and mark is not None:
                issues.append(f"{at}.mark is a timeline member")
            classes = lane.get("classes")
            if classes is not None:
                if not lane.get("key"):
                    issues.append(f"{at}.classes needs a keyed lane (key: <field>)")
                if not (isinstance(classes, dict) and classes
                        and all(isinstance(k, str) and v in CLASSES for k, v in classes.items())):
                    issues.append(f"{at}.classes must map each verdict value to one of {list(CLASSES)}")
            if role in ("judgment",) and not classes:
                issues.append(f"{at}: a judgment lane needs classes")
        return []

    if not isinstance(decl, dict) or not decl:
        return [f"{where} must be a non-empty mapping"]
    extra = sorted(set(decl) - {"calendar", "timeline", "cofail", "wording"})
    issues += [f"{where}.{k} is not a view member" for k in extra]
    for name in ("calendar", "timeline"):
        if name in decl:
            issues += lanes(name, decl[name], name == "timeline")
    if "cofail" in decl:
        c = decl["cofail"]
        if not (isinstance(c, dict) and ID_RE.match(str(c.get("id", ""))) and c.get("where")
                and c.get("key") and c.get("subject")):
            issues.append(f"{where}.cofail needs id, where, key and subject")
    wording = decl.get("wording", {})
    if not isinstance(wording, dict) or not all(isinstance(v, str) and v.strip() for v in wording.values()):
        issues.append(f"{where}.wording must map keys to non-empty strings")
    else:
        for key in wording:
            if not WORDING_KEYS.match(key):
                issues.append(f"{where}.wording.{key} is not a wording key a view reads")
        timeline_ids = {l.get("id") for l in decl.get("timeline", []) if isinstance(l, dict)}
        for key in wording:
            m = re.match(r"^lane\.(.+)\.title$", key)
            if m and m.group(1) not in timeline_ids:
                issues.append(f"{where}.wording.{key} names no timeline lane")
    return issues


# ---- the packs' declarations -------------------------------------------------

_CASE = [("record_type", "case")]

_TERMS_CALENDAR = [
    {"id": "activity", "role": "activity", "where": _CASE},
    {"id": "judgment", "role": "judgment", "where": _CASE, "key": "statement.verdict",
     "classes": {"met": "good", "not_met": "bad", "not_evaluable": "open"}},
    {"id": "adjudications", "role": "adjudication", "where": [("record_type", "adjudication")],
     "key": "statement.agreement", "classes": {"concur": "good", "differs": "bad"}},
]

_EU_CALENDAR = [
    {"id": "activity", "role": "activity", "where": _CASE},
    {"id": "judgment", "role": "judgment", "where": _CASE, "key": "statement.verdict",
     "classes": {"met_all": "good", "not_met": "bad", "not_evaluable": "open"}},
    {"id": "adjudications", "role": "adjudication", "where": [("record_type", "adjudication")],
     "key": "statement.agreement", "classes": {"concur": "good", "differs": "bad"}},
]

PACK_VIEWS = {
    "airline-support-outcomes": {
        "calendar": _TERMS_CALENDAR,
        "wording": {
            "calendar.activity": "conversations",
            "calendar.class.good": "resolved",
            "calendar.class.bad": "missed",
            "calendar.class.open": "undecided",
            "calendar.legend.good": "at most one judged conversation missed, most resolved",
            "calendar.legend.bad": "more than half of the judged conversations missed",
            "calendar.legend.open": "anything between",
        },
    },
    "eu-ai-act-obligations": {
        "calendar": _EU_CALENDAR,
        "timeline": [
            {"id": "routed", "mark": "tick", "where": [("verdict_class", "hitl_dispatched")]},
            {"id": "effects_unconfirmed", "mark": "tick", "where": [("verdict_class", "effects_not_confirmed")]},
            {"id": "incident_flags", "mark": "diamond", "where": [("verdict_class", "incident_flag")]},
            {"id": "adjudications_close", "mark": "diamond",
             "where": [("record_type", "adjudication"), ("statement.phase", "close")]},
        ],
        "cofail": {"id": "failing", "where": [("record_type", "case"), ("statement.verdict", "not_met")],
                   "key": "statement.requirement", "subject": "statement.session"},
        "wording": {
            "calendar.activity": "sessions",
            "calendar.class.good": "met all",
            "calendar.class.bad": "did not",
            "calendar.class.open": "undecided",
            "calendar.legend.good": "at most one judged session did not meet all, most met all",
            "calendar.legend.bad": "more than half of the judged sessions did not",
            "calendar.legend.open": "anything between",
            "cofail.failing": "sessions failing",
            "lane.routed.title": "Routed to a person",
            "lane.effects_unconfirmed.title": "Effects not confirmed",
            "lane.incident_flags.title": "Incident flags",
            "lane.adjudications_close.title": "Adjudications · close",
        },
    },
}


def build_block(pack_id):
    decl = PACK_VIEWS.get(pack_id)
    if decl is None:
        return None
    return {"charts": build_charts(decl), "wording": dict(decl.get("wording", {}))}


def check_registry():
    """Issues in every registered declaration (the tests call this)."""
    out = []
    for pid, decl in PACK_VIEWS.items():
        out += validate(decl, where=pid)
    return out
