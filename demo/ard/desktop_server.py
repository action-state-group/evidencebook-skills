#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The ARD demo as a Goose extension (an MCP server over stdio), one per party's window, so each party's Goose in
Goose Desktop runs its own steps. Every tool returns the text a person reads (:mod:`screens`); a refusal is a line
starting ``REFUSED:`` and changes nothing.

``ARD_ROLE`` picks whose window this is:

``maya``   the buyer:
    ard_find_sellers  ->  her ask and ARD discovery
    ard_set_limit     ->  her spending limit, set only from her yes to the amount her agent proposed
    ard_show_listing  ->  a seller's ARD listing, as the search fetched and checked it
    ard_show_history  ->  each seller's History card, fetched and checked
    ard_assess        ->  the assessment of each seller under her pack
    ard_pick          ->  the pick (a seller outside its limit ends here: no deal opens, nothing is paid)
    ard_pay           ->  the deal and the payment; the one tool that moves money (the presenter approves in a dialog)
    ard_dispute       ->  her dispute of a deal's delivery, sent to the seller and to the deal's adjudicator
    ard_confirm_received -> her statement that she received what she paid for, only after her yes in a dialog
``alder`` / ``kestrel``   a seller, its own profile and keys; its agent answers on its own:
    ard_seller_activity  ->  what its agent did: the deal, the delivery, a dispute, a ruling, its card now
``adjudicator``   the demo's adjudicator (its own capsulectl-deal profile, run by the demo operator):
    ard_case          ->  the cases sent to it: what the adjudicator ruled and why, and what each side's books show
                          (it rules on its own, with no person: evidencebook-skills#416)
    ard_ruling        ->  what the adjudicator ruled and why, under the line that it is not independent (#446)
    ard_case_activity ->  whether each party entered the ruling in its own book
Every party's window also has ard_show_card, ard_open_card_page, ard_show_receipt and ard_open_receipt_page: its own
History card and its own receipt (the adjudicator holds no deal of its own, so not those).

Environment (``demo.py --help`` lists it): ``CAPSULECTL_DEAL``, ``CAPSULE_ENGINE``, ``ARD_EVIDENCEBOOK``,
``ARD_HOME``, ``ARD_RAIL`` (``fake``, ``lightning`` or ``local``; default ``fake``). Seed the
home first with ``demo.py seed``. See RUNBOOK.md."""
from __future__ import annotations

import fcntl
import functools
import inspect
import io
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

try:  # mcp >= 2 renamed FastMCP to MCPServer
    from mcp.server.mcpserver import Context, MCPServer as FastMCP
except ImportError:  # mcp < 2
    from mcp.server.fastmcp import Context, FastMCP

import adjudicator as adj  # noqa: E402
import ard  # noqa: E402
import buyer  # noqa: E402
import flow  # noqa: E402
import limits  # noqa: E402
import pack as packs  # noqa: E402
import party as pt  # noqa: E402
import pay  # noqa: E402
import screens  # noqa: E402
import stage  # noqa: E402
from cast import ADJUDICATOR, BUYER, SELLERS  # noqa: E402

ROLE = os.environ.get("ARD_ROLE", "maya")
if ROLE not in (BUYER, ADJUDICATOR, *SELLERS):
    raise SystemExit(f"ARD_ROLE must be maya, alder, kestrel or adjudicator, not {ROLE!r}")

server = FastMCP(f"ard_{ROLE}")
DEFAULT_HOME = "~/.config/ard-commerce-demo"


def _home() -> Path:
    return Path(os.environ.get("ARD_HOME", DEFAULT_HOME)).expanduser()


def _rail_name() -> str:
    return os.environ.get("ARD_RAIL", "fake")


def _real() -> bool:
    return _rail_name() in ("lightning", "local")


def _lock(role: str) -> object:
    """One server per party and demo home: a second Goose chat's server would wait on the first's store."""
    home = _home()
    home.mkdir(parents=True, exist_ok=True)
    handle = open(home / f".desktop-{role}.lock", "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise RuntimeError(f"another Goose chat already runs the {role} side on this home: "
                           "use that chat, or close it first") from None
    return handle


def _seeded() -> None:
    if not pt.Party(_home(), BUYER).exists:
        raise RuntimeError("no sample history yet: run `python demo.py seed` first")


# -- dialogs ------------------------------------------------------------------------------------------

def dialog_text(text: str) -> str:
    """The words a dialog shows for ``text``, with no backslash or double quote (they are replaced, as when the dialogs
    were drawn by AppleScript, so the words sealed with an answer stay the same). A record of the person's answer
    commits to these words, the ones the person saw."""
    return text.replace("\\", " ").replace('"', "'")


#: How a dialog ended other than yes (#239 finding 11: a dialog nobody answered is never called a decline).
NO, NO_ANSWER, NOT_SHOWN = "no", "no_answer", "not_shown"
#: What the person is told when the dialog did not end in yes (Sherlock2's words for no answer, #239 finding 11).
NOT_YES = {NO: "the presenter declined it",
           NO_ANSWER: "no answer in time",
           NOT_SHOWN: "the dialog could not be shown"}


#: How long a dialog waits for the presenter before it gives up (run finding F6a, 2026-11-25: 3 minutes was too short
#: when a person first has to find the dialog): a typed reply waits this long; a form waits until the window ends it,
#: at most this long, which with Goose 1.59.2 is 5 minutes (FORM_LIMIT_S). The window's MCP tool timeout
#: (open-windows.py TOOL_TIMEOUT_S) covers it and the rest of the longest call, ard_pay.
DIALOG_GIVE_UP_S = 600
#: The one field of a dialog's form in the window. Its key is the words a person reads: Goose Desktop 1.59.2 labels the
#: field with its key, not its ``title`` (#418's hand run on 2026-11-27 showed "answer *"), so key and title are the same.
ANSWER_FIELD = ANSWER_LABEL = "Your answer"
#: The key of the form in a 2026-07-28 input round (``input_requests`` and the client's ``input_responses``).
ROUND_KEY = "dialog"
#: A form the window ends sooner than this after it was asked was not shown to anyone: Goose Desktop 1.59.2 ends a form
#: it cannot draw at once, and one it drew only after 300 s (FORM_LIMIT_S).
SHOWN_AT_LEAST_S = 30

#: The MCP request of the tool call running on this thread (set by :func:`_tool`): a dialog is asked in that call's
#: own window. Each tool call runs on its own worker thread (mcp's ``anyio.to_thread``), so a thread-local is that call's.
_call = threading.local()


def answer_schema(yes: str, no: str) -> dict:
    """The form a dialog is in the party's window: one required choice between its two answers, the safe one (``no``)
    first and preset, so Submit without a change sends it."""
    return {"type": "object", "required": [ANSWER_FIELD],
            "properties": {ANSWER_FIELD: {"type": "string", "title": ANSWER_LABEL, "enum": [no, yes], "default": no}}}


def dialog_message(title: str, text: str) -> str:
    """The words of a dialog in the window: its title, then its text. Goose 1.59.2 shows a form's message as one paragraph
    (ElicitationRequest.tsx draws it in a span), so a line with no closing punctuation, such as each reason a held order
    lists, ends with a full stop here and does not run into the next. The words are those sealed with the answer."""
    lines = [line.strip() for line in dialog_text(f"{title}\n{text}").splitlines() if line.strip()]
    return " ".join(line if line.endswith((".", "?", "!", ":")) else line + "." for line in lines)


#: The tool call's ``_meta`` keys Goose Desktop reads back from a form it is sent, to put the form in the chat and tool
#: call that asked it (goose v1.59.2 crates/goose/src/session_context.rs; without them Goose refuses a form while two
#: of the window's tool calls run, mcp_client.rs resolve_tool_call_request_id).
ECHOED_META = ("agent-session-id", "agent-tool-call-request-id")


def echoed_meta(ctx) -> dict | None:
    """The keys of the call's ``_meta`` Goose reads back from a form it is sent (:data:`ECHOED_META`)."""
    if ctx is None:
        return None
    meta = ctx.request_context.meta or {}  # a dict in mcp 2.3.0, a model in older mcp
    asked_by = meta if isinstance(meta, dict) else meta.model_dump(by_alias=True)
    return {k: asked_by[k] for k in ECHOED_META if k in asked_by} or None


def _ask_window(ctx, message: str, schema: dict, wait_s: float):
    """One elicitation in the window of the tool call ``ctx`` belongs to, ended after ``wait_s``; raises TimeoutError
    then. Runs on the tool's worker thread, so the request itself goes through the server's event loop."""
    import anyio
    import anyio.from_thread
    from mcp import types as mt
    from mcp.shared.message import ServerMessageMetadata

    rc = ctx.request_context
    echo = echoed_meta(ctx)
    request = mt.ElicitRequest(params=mt.ElicitRequestFormParams(message=message, requested_schema=schema, _meta=echo))

    async def ask():
        with anyio.fail_after(wait_s):
            return await rc.session.send_request(request, mt.ElicitResult,
                                                 metadata=ServerMessageMetadata(related_request_id=ctx.request_id))
    return anyio.from_thread.run(ask, token=getattr(_call, "loop", None))


def dialog_answer(title: str, text: str, yes: str, no: str = "Cancel") -> str:
    """A dialog in this party's own Goose window, as a form with a choice between ``no`` (preset) and ``yes`` and
    Goose's Submit button, and how it ended: ``"yes"`` (``yes`` submitted), :data:`NO` (``no`` submitted),
    :data:`NO_ANSWER` (nothing submitted before the window ended the form) or :data:`NOT_SHOWN` (no window, or any error
    before it was shown). The form goes from the server to the window (MCP elicitation) and its answer straight back:
    the window's agent neither sees the answer before the tool returns nor has any tool that gives one. It is asked
    once: Goose ends a form after 5 minutes (:data:`FORM_LIMIT_S`) and fails the call, so it cannot be shown again.
    Where the window cannot show a form, Maya's dialog is asked by typed reply instead (:func:`_typed_answer`)."""
    how = _form_answer(title, text, yes, no)
    if how == NOT_SHOWN and ROLE == BUYER and getattr(_call, "job", None) is not None:  # ard_confirm is Maya's
        return _typed_answer(title, text, yes, no)
    return how


def _ended(title: str, asked: float, what) -> str:
    """How a form that ended without a submitted answer ended: at once, the window could not draw it (:data:`NOT_SHOWN`);
    later, it was on screen and nobody answered (:data:`NO_ANSWER`). Goose 1.59.2 offers a person no decline (only
    Submit), and a client that cannot draw the form declines or cancels it at once (the Claude Code adapter without
    form support auto-declines), so none of these is ever the presenter's no."""
    if time.monotonic() - asked < SHOWN_AT_LEAST_S:
        _log(f"dialog {title!r} not shown: {what!r}")
        return NOT_SHOWN
    _log(f"dialog {title!r}: nobody answered before the window ended it ({what!r})")
    return NO_ANSWER


def _form_answer(title: str, text: str, yes: str, no: str) -> str:
    """The dialog as a form in the window (:func:`dialog_answer`), asked once. It waits until the window ends it, at
    most :data:`DIALOG_GIVE_UP_S` (with Goose, :data:`FORM_LIMIT_S`); it is never asked again."""
    _call.typed = None
    ctx = getattr(_call, "ctx", None)
    if ctx is None:
        return NOT_SHOWN
    message, schema = dialog_message(title, text), answer_schema(yes, no)
    asked = time.monotonic()
    try:
        result = _ask_window(ctx, message, schema, DIALOG_GIVE_UP_S)
    except TimeoutError:
        return NO_ANSWER
    except Exception as exc:  # noqa: BLE001: no window, a closed chat, a client without forms, Goose's limit
        if type(exc).__name__ == "NoBackChannelError" and getattr(_call, "job", None) is not None:
            return _form_round(title, yes, no, message, schema)
        return _ended(title, asked, exc)
    if result.action == "accept":
        got = (result.content or {}).get(ANSWER_FIELD)
        return "yes" if got == yes else NO if got == no else NO_ANSWER
    return _ended(title, asked, result.action)


#: How long Goose 1.59.2 keeps a form it showed: it answers the form request after at most 300 s, with an error when
#: nobody submitted (crates/goose/src/agents/mcp_client.rs:418-435), and on the 2026-07-28 protocol rmcp 3.4.1 then
#: fails the whole call, with no retry (src/service/client.rs fulfill_input_request). So with Goose a form waits 5
#: minutes and is never shown again; evidencebook-skills#438.
FORM_LIMIT_S = 300
#: How long a form round waits for the client's retry: past Goose's limit the call has failed and no retry comes.
ROUND_WAIT_S = FORM_LIMIT_S + 30


def _reply_parts(reply) -> tuple[str | None, dict]:
    if reply is None:
        return None, {}
    if isinstance(reply, dict):
        return reply.get("action"), reply.get("content") or {}
    return getattr(reply, "action", None), getattr(reply, "content", None) or {}


def _form_round(title: str, yes: str, no: str, message: str, schema: dict) -> str:
    """The form on a 2026-07-28 connection, which has no back-channel: the call returns it as its input_required result,
    the client (Goose's MCP client) shows it in the window and retries the call with the answer, and this thread reads
    the answer from that retry (:func:`_tool`). As :func:`_form_answer`, asked once. The form cannot carry the call's ids
    (ECHOED_META) here: the 2026-07-28 surface of mcp 2.3.0 drops ``_meta`` from an embedded request, and rmcp reads them
    only from there; so Goose can place the form only while the window runs one call, as the skill has its agent do
    (one tool per message). Otherwise Goose fails the call, and nothing is done."""
    job = _call.job
    asked = time.monotonic()
    job.pause_form(message, schema)
    if not job.replied.wait(ROUND_WAIT_S):  # Goose failed the call at its limit: nobody answered
        _log(f"dialog {title!r}: no answer came back from the window")
        return NO_ANSWER
    action, content = _reply_parts(job.reply)
    if action == "accept":
        got = content.get(ANSWER_FIELD)
        return "yes" if got == yes else NO if got == no else NO_ANSWER
    return _ended(title, asked, action)


# -- the typed reply: when the window cannot show a form ----------------------------------------------------------------
#
# With the Claude Code (ACP) provider the window cannot show a form (Claude Code talks MCP 2026-07-28 to this server,
# which then has no back-channel, and the Claude Code adapter forwards no form to Goose 1.59.2). The dialog is then asked
# in the chat (Ethan, 2026-11-26: "弹不出表单就用文字让用户确认"): the tool returns its words and the exact reply to
# type, and its work waits on its own thread. The answer is read from Goose's own record of the chat, the person's next
# typed message after the question (Goose writes it only from what is typed in the window), never from the agent: the
# agent cannot type the person's reply. Only the exact reply is yes; anything else, or no reply within
# DIALOG_GIVE_UP_S, is the safe answer.

#: How often the record is read for the person's reply.
REPLY_POLL_S = 2.0
#: The words a seal adds after the dialog's words when the answer was a typed reply (proposed; awaiting Sherlock2's
#: wording review).
TYPED_NOTE = "Answered by a typed reply in the chat"


def goose_db() -> Path:
    """Goose's record of its chats (crates/goose/src/session/session_manager.rs SESSIONS_FOLDER, DB_NAME at v1.59.2):
    ``ARD_GOOSE_DB``, which open-windows.py sets, else the one under ``GOOSE_PATH_ROOT``, else the demo's Goose root."""
    if os.environ.get("ARD_GOOSE_DB"):
        return Path(os.environ["ARD_GOOSE_DB"]).expanduser()
    if os.environ.get("GOOSE_PATH_ROOT"):
        return Path(os.environ["GOOSE_PATH_ROOT"]).expanduser() / "data" / "sessions" / "sessions.db"
    import reset
    return reset.goose_root() / "data" / "sessions" / "sessions.db"


def _read_db(query: str, args: tuple) -> list[tuple]:
    import sqlite3
    db = goose_db()
    if not db.is_file():
        return []
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
    try:
        return con.execute(query, args).fetchall()
    finally:
        con.close()


def chat_of(meta: dict) -> str | None:
    """The Goose chat (session id) a tool call came from: Goose's own ``agent-session-id`` (a provider Goose runs), or the
    chat whose recorded tool request has the id Claude Code gives the call (``claudecode/toolUseId``, Claude Code ACP)."""
    if meta.get("agent-session-id"):
        return str(meta["agent-session-id"])
    use = meta.get("claudecode/toolUseId")
    if not use:
        return None
    import json
    for sid, content in _read_db("SELECT session_id, content_json FROM messages WHERE role = 'assistant' AND "
                                 "content_json LIKE ? ORDER BY id DESC", (f'%{use}%',)):
        try:
            if any(c.get("type") == "toolRequest" and c.get("id") == use for c in json.loads(content)):
                return sid
        except (ValueError, AttributeError):
            continue
    return None


def last_record_id() -> int:
    """The id of the newest message in Goose's record (its ids only grow): a reply counts only if recorded after it."""
    rows = _read_db("SELECT COALESCE(MAX(id), 0) FROM messages", ())
    return int(rows[0][0]) if rows else 0


def typed_reply(chat: str, after_id: int) -> tuple[int, str] | None:
    """The person's first message typed in ``chat`` after the record's message ``after_id``, with its id, or None yet.
    A tool's result and the turn context Goose adds are recorded as the user's too, so only a plain typed text counts."""
    import json
    for mid, content in _read_db("SELECT id, content_json FROM messages WHERE session_id = ? AND role = 'user' AND "
                                 "id > ? ORDER BY id", (chat, after_id)):
        try:
            parts = json.loads(content)
        except ValueError:
            continue
        texts = [c.get("text", "") for c in parts if isinstance(c, dict) and c.get("type") == "text"]
        if not texts or len(texts) != len(parts) or texts[0].lstrip().startswith("<turn-context>"):
            continue
        return int(mid), "\n".join(texts)
    return None


def reply_matches(reply: str, yes: str) -> bool:
    """Whether the typed reply is exactly ``yes``: case, surrounding spaces and a closing full stop aside."""
    return reply.strip().rstrip(".").strip().casefold() == yes.casefold()


#: One question waits for a typed reply at a time, so one reply never answers two questions.
_typed_one = threading.Lock()
#: Set to end every wait for a typed reply at once (tests; a window closing).
_shutdown = threading.Event()


def _typed_answer(title: str, text: str, yes: str, no: str) -> str:
    """The dialog asked by typed reply (above): this call's tool returns the question, and this thread waits for the
    person's reply in Goose's record. While one question waits, another is not asked: it is not shown."""
    job, ctx = _call.job, _call.ctx
    raw = (ctx.request_context.meta or {}) if ctx is not None else {}
    meta = raw if isinstance(raw, dict) else raw.model_dump(by_alias=True)
    if not (meta.get("agent-session-id") or meta.get("claudecode/toolUseId")):
        _log(f"dialog {title!r}: this call names no chat, so it cannot be answered by a typed reply")
        return NOT_SHOWN
    if not _typed_one.acquire(blocking=False):
        _log(f"dialog {title!r}: another question already waits for a typed reply")
        return NOT_SHOWN
    try:
        after = last_record_id()  # before the question goes out: an earlier message never answers it
        job.pause(title, text, yes, no)
        chat = None  # Goose records the call's own request only once the call has returned the question
        end = time.monotonic() + DIALOG_GIVE_UP_S
        while time.monotonic() < end and not _shutdown.is_set():
            chat = chat or chat_of(meta)
            got = typed_reply(chat, after) if chat else None
            if got is not None:
                _call.typed = got[1]
                return "yes" if reply_matches(got[1], yes) else NO
            _shutdown.wait(REPLY_POLL_S)
        if chat is None:
            _log(f"dialog {title!r}: its chat was not found in Goose's record ({goose_db()})")
        return NO_ANSWER
    finally:
        _typed_one.release()
        job.answered.set()


#: How a typed reply other than the exact one is told (proposed; awaiting Sherlock2's wording review): never "chose
#: Cancel" or "declined".
TYPED_NOT_YES = "Maya's typed reply was not the exact answer"


def not_yes(how: str, table: dict) -> str:
    """Why a dialog did not end in yes, in ``table``'s words; a typed reply that was not the exact one says so."""
    return TYPED_NOT_YES if how == NO and getattr(_call, "typed", None) is not None else table[how]


def typed_note() -> str:
    """The line a seal adds when this thread's last dialog was answered by a typed reply, else ""."""
    reply = getattr(_call, "typed", None)
    return f"\n{TYPED_NOTE}: {dialog_text(reply)}" if reply is not None else ""


def ask_person(title: str, text: str, yes: str, no: str = "Cancel") -> bool:
    """True only for ``yes`` (:func:`dialog_answer`)."""
    return dialog_answer(title, text, yes, no) == "yes"


def gate_off() -> bool:
    """``ARD_APPROVAL=none`` answers every dialog yes, on the simulated rail only (tests; the tool says so)."""
    if os.environ.get("ARD_APPROVAL") != "none":
        return False
    if _real():
        raise RuntimeError(f"ARD_APPROVAL=none is refused on the {_rail_name()} rail, which moves real money: unset it")
    print("(approval dialog off: ARD_APPROVAL=none, simulated rail, tests only)")
    return True


# -- the buyer's session ------------------------------------------------------------------------------

class Session:
    """Maya's run: her profile, the sellers found, the evidence, the assessments, the pick and the deals."""

    def __init__(self) -> None:
        packs.engine(), packs.skills_checkout()
        _seeded()
        self._lock = _lock(BUYER)
        stage.ensure_stage(_home())
        self.home = _home()
        self.maya = pt.Party(self.home, BUYER)
        self.adjudicator = adj.Adjudicator(self.home)
        self.rail: pay.Rail = pay.from_env(_rail_name())
        self.entries: list[dict] = []
        self.evidence: dict[str, buyer.Evidence] = {}
        self.assessed: dict[str, buyer.Assessment] = {}
        self.pack: packs.Pack | None = None
        self.ask = ""  # what she asked for, in her own words (ard_find_sellers): each deal's intent seals it
        #: the sellers picked under the last search, each with Maya's own words naming it ("" when the agent picked)
        self.picked: dict[str, str] = {}
        self.deals: list[buyer.Deal] = buyer.deals_from_notes(self.maya)  # a reopened window keeps its deals
        #: the sellers whose last payment dialog was declined, each with that dialog's title (a held order's question)
        self.declined: dict[str, str] = {}
        self.pay_lock = threading.Lock()
        self.log: list[str] = []
        self.failing: set[str] = set()  # the trying-again lines said since the last other line
        threading.Thread(target=self._rulings, daemon=True).start()

    def say(self, line: str) -> None:
        if not screens.once_per_failure(self.failing, line):  # a step that keeps failing says so once
            return
        if not self.log or self.log[-1] != line:
            self.log.append(line)

    def _rulings(self) -> None:
        """Maya's agent enters a ruling on her deals as soon as the adjudicator publishes it, as a seller's does."""
        while True:
            for what, step in (
                    ("answering the adjudicator's request for this buyer's books",
                     lambda: adj.answer_requests(self.home, self.maya, BUYER, "buyer", self.say)),
                    ("entering the adjudicator's ruling",
                     lambda: flow.enter_rulings(self.home, self.maya, "buyer", buyer.seller_of(self.maya), self.say)),
                    ("keeping the seller's statements", lambda: buyer.seller_statements(self.home, self.maya)),
                    ("taking the seller's delivery", self._deliveries)):
                try:
                    step()
                except Exception as exc:  # one plain line in the next tool's output; the error itself in Maya's log
                    self.maya.log(f"{what}: {exc!r}")
                    self.say(screens.trying_again(what, exc))
            time.sleep(3)

    def _deliveries(self) -> None:
        with self.pay_lock:  # not while ard_pay itself pays or waits for the same delivery
            buyer.pick_up_deliveries(self.home, self.maya, self.say)

    @property
    def keys(self) -> dict[str, str]:
        return {e["id"]: e["commitment"]["key_id"] for e in self.entries if "commitment" in e}

    def latest(self, seller: str | None = None) -> buyer.Deal | None:
        ds = [d for d in self.deals if seller is None or d.seller == seller]
        return ds[-1] if ds else None


_session: Session | None = None
_seller: flow.SellerAgent | None = None
_seller_lock: object | None = None


def session() -> Session:
    global _session
    if _session is None:
        _session = Session()
    return _session


def seller() -> flow.SellerAgent:
    global _seller, _seller_lock
    if _seller is None:
        packs.engine()
        _seeded()
        _seller_lock = _lock(ROLE)
        stage.ensure_stage(_home())
        _seller = flow.SellerAgent(_home(), ROLE)
    return _seller


def _log(line: str) -> None:
    """A line in this window's party log (``<home>/<role>/agent.log``); never raises."""
    try:
        d = _home() / ROLE
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "agent.log", "a") as fh:
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}  {line}\n")
    except OSError:
        pass


class _Job:
    """One tool call's work, on its own thread, so a dialog asked by typed reply can return the question while the work
    waits for the answer (:func:`_typed_answer`)."""

    def __init__(self) -> None:
        import uuid
        self.id = uuid.uuid4().hex
        self.buf = io.StringIO()
        self.shown = 0  # how much of buf a tool result already returned
        self.done, self.paused, self.answered = threading.Event(), threading.Event(), threading.Event()
        self.question: tuple[str, str, str, str] | None = None
        self.kind = "typed"  # what the pause asks: "typed" (the question in the chat) or "form" (a form round)
        self.form: tuple[str, dict] | None = None
        self.replied = threading.Event()
        self.reply = None  # the form round's answer, from the client's retry of the call

    def pause(self, title: str, text: str, yes: str, no: str) -> None:
        self.question, self.kind = (title, text, yes, no), "typed"
        self.answered.clear()
        self.paused.set()

    def pause_form(self, message: str, schema: dict) -> None:
        self.form, self.kind, self.reply = (message, schema), "form", None
        self.replied.clear()
        self.paused.set()

    def take(self) -> str:
        out = self.buf.getvalue()
        part, self.shown = out[self.shown:], len(out)
        return part


#: The tool call of this window whose dialog waits for a typed reply, if any (ard_confirm collects it).
_waiting: list[_Job] = []
#: The tool calls whose form went out as an input_required result, by the request state the client's retry echoes.
_rounds: dict[str, _Job] = {}


class _ThreadOut(io.TextIOBase):
    """sys.stdout that writes to the running tool call's own buffer, on the thread that runs it, and elsewhere to the
    real stdout: tool calls run at the same time each keep their own output."""

    def __init__(self, real) -> None:
        self.real = real

    def write(self, s: str) -> int:
        out = getattr(_call, "out", None)
        return (out or self.real).write(s)

    def flush(self) -> None:
        (getattr(_call, "out", None) or self.real).flush()

    def __getattr__(self, name):
        return getattr(self.real, name)


def _own_stdout() -> None:
    if not isinstance(sys.stdout, _ThreadOut):
        sys.stdout = _ThreadOut(sys.stdout)


def _question_text(job: _Job) -> str:
    title, text, yes, no = job.question
    fence, shown = "-" * 40, dialog_text(f"{title}\n{text}")
    return ("This step waits for the person's answer, which they give by typing in this chat. Show them the words "
            f"between the two lines of dashes exactly, without the dashes, then end your turn:\n{fence}\n"
            f"{shown}\n\nTo answer {yes}, type exactly: {yes}\n"
            f"Anything else typed, or no reply within {DIALOG_GIVE_UP_S // 60} minutes, means {no}.\n{fence}\n"
            "When they have replied, call ard_confirm. Never type or give the answer yourself: only their own typed reply "
            "counts.")


def _run_job(job: _Job, fn, args, kwargs, ctx, token) -> None:
    _call.ctx, _call.job, _call.out, _call.loop = ctx, job, job.buf, token
    try:
        if _session is not None and _session.log:  # what Maya's agent did since her last request
            print("Since your last request:")
            _flush(_session)
            print()
        fn(*args, **kwargs)
    except (SystemExit, Exception) as exc:
        print(f"\nREFUSED: {_refusal(exc)}")
    finally:
        _call.ctx = _call.job = _call.out = _call.loop = None
        _rounds.pop(job.id, None)  # a form round the client never retried
        job.answered.set()
        job.done.set()


def _until_paused_or_done(job: _Job) -> str:
    """The job's output once it ends, or once it pauses on a dialog asked by typed reply (then its question)."""
    while not job.done.wait(0.1):
        if job.paused.is_set() and job.kind == "form":
            job.paused.clear()
            _rounds[job.id] = job
            from mcp import types as mt
            message, schema = job.form
            return mt.InputRequiredResult(request_state=job.id, input_requests={ROUND_KEY: mt.ElicitRequest(
                params=mt.ElicitRequestFormParams(message=message, requested_schema=schema))})
        if job.paused.is_set():
            job.paused.clear()
            _waiting[:] = [j for j in _waiting if not j.done.is_set() or j.shown < len(j.buf.getvalue())]
            if job not in _waiting:
                _waiting.append(job)
            return (job.take() + "\n\n" + _question_text(job)).strip()
    if job in _waiting:
        _waiting.remove(job)
    _rounds.pop(job.id, None)
    return job.take().strip()


def _tool(*roles: str, description: str | None = None, plain: bool = False):
    """Register a tool for these roles. A tool returns the text it printed; a refusal is a line starting
    ``REFUSED:`` and changes nothing. ``plain``: the result is the printed text alone, with no structured copy
    (``{"result": ...}``), so Goose shows the tool's own lines as printed rather than as one line of JSON
    (evidencebook-skills#446)."""
    def deco(fn):
        @functools.wraps(fn)
        def run(*args, ard_request: Context | None = None, **kwargs) -> str:
            _own_stdout()
            state = getattr(ard_request, "request_state", None) if ard_request is not None else None
            if state is not None and state in _rounds:  # the client's retry with the form's answer
                job = _rounds.pop(state)
                responses = ard_request.input_responses or {}
                job.reply = responses.get(ROUND_KEY)
                job.replied.set()
                return _until_paused_or_done(job)
            job = _Job()
            token = None
            if ard_request is not None:  # mcp runs this on its worker thread: the event loop a form is sent through
                import anyio.from_thread
                import anyio.lowlevel
                token = anyio.from_thread.run_sync(anyio.lowlevel.current_token)
            threading.Thread(target=_run_job, args=(job, fn, args, kwargs, ard_request, token), daemon=True).start()
            return _until_paused_or_done(job)
        sig = inspect.signature(fn)
        # mcp passes the request's Context to the parameter annotated with it and leaves it out of the tool's inputs
        request = inspect.Parameter("ard_request", inspect.Parameter.KEYWORD_ONLY, default=None, annotation=Context)
        run.__signature__ = sig.replace(parameters=[*sig.parameters.values(), request], return_annotation=str)
        run.__annotations__ = {**fn.__annotations__, "ard_request": Context, "return": str}
        del run.__wrapped__
        if ROLE in roles:
            return server.tool(description=description, structured_output=False if plain else None)(run)
        return run
    return deco


class Said(RuntimeError):
    """A refusal the demo writes for the person in full, such as every reason a held order lists: :func:`_refusal`
    never shortens it, however long it is (evidencebook-skills#412)."""


def _refusal(exc: BaseException) -> str:
    """A tool's refusal without raw output (evidencebook-skills#327). The demo's refusals and capsulectl's error words
    are written for a person and stay; a refusal that carries a verb's raw output (JSON, or a long dump), whatever
    exception carries it, goes to this window's log and reads as one plain line. It claims nothing about what the step
    did before it was refused. A :class:`Said` refusal is the demo's own and stays whole."""
    text = str(exc)
    if isinstance(exc, Said):
        return text
    if "{" in text or len(text) > 400:  # whatever wrapped it (a tool that wraps capsulectl's refusal in a RuntimeError)
        _log(f"a tool refused: {exc!r}")
        return "this step was refused (the reason is in your log, agent.log)"
    return text


def _seller_key(name: str) -> str:
    key = name.strip().lower().split()[0] if name.strip() else ""
    if key not in SELLERS:
        raise ValueError(f"unknown seller {name!r}; the sellers are " + ", ".join(SELLERS[k]["label"] for k in SELLERS))
    return key


def _flush(s: Session) -> None:
    while s.log:
        print(s.log.pop(0))


# -- Maya ---------------------------------------------------------------------------------------------

@_tool("maya")
def ard_find_sellers(ask: str) -> None:
    """Step 1-2: Maya's ask and ARD discovery. Lists the sellers found, each with its price and whether its listing
    checks out. Call this first. ``ask`` is what the person asked for, in their own words, word for word: each deal's
    intent seals it."""
    if not ask.strip():
        raise RuntimeError("pass the person's ask, in their own words")
    s = session()
    found = ard.lookup(stage.REGISTRY_URL, stage.ORIGINS, stage.QUERY, stage.CATALOG_ORIGIN)
    try:  # the checks, kept in her own records before the search's results are used (#345)
        buyer.record_search(s.maya, stage.REGISTRY_URL, stage.QUERY, found)
    except Exception as exc:  # noqa: BLE001
        _log(f"keeping the search's checks: {exc!r}")
        raise RuntimeError("The search could not be saved to your records, so its results are not used. The reason "
                           "is in agent.log.") from None
    # her ask and the sellers found replace the last search's only once this one is kept; a pick belongs to the search
    # it came from, so a new search clears it (Codex on #361: a pick never pays under another search's ask)
    s.entries, s.ask, s.picked = found, ask, {}
    print(f"searched a local stand-in registry, run by the operator: POST {stage.REGISTRY_URL} {{query: {stage.QUERY!r}}}")
    for e in s.entries:
        price = screens.msat(e["offer"]["price_msat"]) if "offer" in e else "?"
        print(f"found: {e['name']:18} {price:>10}   {'listing checks out' if 'commitment' in e else 'listing refused: ' + e['problem']}")
        # the search's own checks are not shown in her chat (#332, Sherlock2)
    if len(s.entries) < len(SELLERS):
        print("only " + ", ".join(e["name"] for e in s.entries) + " answered: the other seller's window is not running")
    if limits.sealed(s.maya) is None:  # Steven's hand runs of 2026-11-26: the question never came (#413)
        print(f"\n{LIMIT_FIRST}")


#: What Maya's agent does after a search while she has no spending limit (evidencebook-skills#413).
LIMIT_FIRST = ("No spending limit is set yet. Before anything else, ask Maya in one short question whether the most she "
               "said she will pay should be her spending limit, and end your turn: show no History card and assess "
               "nothing until she answers. Until she sets it, it is not her limit: never call it her limit.")
#: For Maya's agent beside the assessment: the 7-day total is the payment check's to say (evidencebook-skills#415's
#: hand run: "Your 7-day total only allows one of these", of 1,000 and 2,000 msat under a 3,000 msat limit).
NO_SUMS = ("Never add up prices or payments against the limit yourself: say only what these lines and the payment check "
           "say.")
#: Beside the History cards: they say nothing of her limit; the assessment says whether a price fits it (#457 F13: "Both
#: prices are within your 3,000 msat limit", said at this step from no tool line).
CARDS_NO_LIMIT = ("These cards say nothing about your spending limit: the assessment says whether each price fits it. "
                  + NO_SUMS)
#: After the limit dialog: one yes sets the limit and nothing more (#413).
LIMIT_SET_THEN = "Tell Maya what the limit is now, and end your turn: wait for her next request."


@_tool("maya")
def ard_show_listing(seller: str) -> None:
    """Show a seller's ARD listing, as the last search fetched and checked it from the seller's own
    /.well-known/ard.json: whether it checks out, the seller's site, its stated offer (unsigned) and which checks it
    passed. It fetches nothing new. ``seller`` is a name or identifier from the search. Call after ard_find_sellers, when the
    person asks to see a seller's listing."""
    s = session()
    if not s.entries:
        raise RuntimeError("search first (ard_find_sellers): a listing is shown as the search fetched it")
    want = seller.strip().lower()
    found = [e for e in s.entries if want and want in (e.get("identifier", "").lower(), e.get("id", "").lower(),
                                                       e.get("name", "").lower())]
    if not found:
        found = [e for e in s.entries if want and e.get("name", "").lower().startswith(want)]
    if len(found) != 1:
        names = ", ".join(e.get("name", e.get("identifier", "?")) for e in s.entries)
        raise RuntimeError(f"{'no seller' if not found else 'more than one seller'} from the search matches {seller!r}; "
                           f"the search found: {names}")
    print("\n".join(screens.listing_lines(found[0])))


@_tool("maya")
def ard_show_history() -> None:
    """Step 3: fetch each seller's History card and check it (its signature, the key its commitment names, its witness
    receipt), and show it. Call after ard_find_sellers, and again before a second order: a card changes."""
    s = session()
    if not s.entries:
        raise RuntimeError("call ard_find_sellers first")
    for e in s.entries:
        ev = buyer.gather(s.home, s.maya, e)
        s.evidence[e["id"]] = ev
        print(f"\n{e['name']}")
        print("\n".join("  " + line for line in screens.check_lines(ev)))
        if ev.card:
            print(f"  History card: {screens.card_line(ev.card)}")
            print(f"  {screens.signed_line(e['name'], e['id'], ev.read is not None and ev.read.witness_status == 'pass')}")
    if limits.sealed(s.maya) is not None:  # her agent said both prices fit her limit at this step (#457 F13)
        print(f"\n{CARDS_NO_LIMIT}")


@_tool("maya")
def ard_assess() -> None:
    """Step 4: assess each seller under Maya's admission pack (its thresholds are placeholders), from the card she
    checked and her own records of deals with that seller. Call after ard_show_history."""
    s = session()
    if not s.evidence:
        raise RuntimeError("call ard_show_history first")
    s.pack = s.pack or packs.starting()
    p = s.pack
    limit = limits.sealed(s.maya)  # the limit she confirmed (ard_set_limit), or none
    print(f"The assessment rules: {screens.PACK_NOTE}")  # its version and digest are in the buyer's assessment records
    print(screens.limit_line(limit, _ceilings(p)))
    print(f"({screens.ASSESSMENT_NOTE})")
    if limit is not None:  # the hand run of #415: Maya added up the two prices herself, and got the 7-day limit wrong
        print(NO_SUMS)
    cards = [ev for ev in s.evidence.values() if ev.read is not None]
    print(f"({screens.operator_note(sum(ev.read.witness_status == 'pass' for ev in cards), len(cards))})\n")
    for e in s.entries:
        ev = s.evidence.get(e["id"])
        if ev is None or ev.card is None:
            print(f"  {e['name']:18} not assessed: no checked History card")
            continue
        a = buyer.assess(s.maya, ev, e["commitment"]["key_id"], e["offer"]["price_msat"], p)
        s.assessed[e["id"]] = a
        ceiling = p.ceiling_msat(a.tier) if a.tier else None
        # the limit words only for a seller that can be paid: a pick that is not GO pays nothing (ard_pick)
        fits = screens.within_limit(a.price_msat, limit) if a.verdict == "GO" else ""
        print(f"  {e['name']:18} {screens.decision_line(a, ev, ceiling)}{'.' if fits else ''}{fits}")
        caution = screens.open_disputes_line(e["name"], ev.card) if a.verdict == "GO" else ""
        if caution:
            print(f"  {'':18} {caution}")


@_tool("maya")
def ard_set_limit(limit_msat: int) -> None:
    """Set the person's spending limit. When the person names the most they will pay in their ask, propose it to them
    as their spending limit in one short question ("<the amount> msat as your spending limit?") and end your turn;
    never set it on your own reading of their words. Only after they say yes, call this with the amount in msat: it
    asks them in a dialog in this window, and only their answer there sets it. You cannot answer the dialog. If the
    step hands you a question to show, show it word for word, end your turn, and call ard_confirm after the person
    replies. Once set, it is sealed in their records, and their card, the assessment and every payment check use it.
    Never propose a new or higher limit yourself, after a held order included: change it only when the person asks for
    that in their own words."""
    limit = limits.check_amount(limit_msat)
    s = session()
    title, text = screens.limit_question(limit)
    with s.pay_lock:  # never while a payment is checked or waits for her answer under the limit it read (Codex on #361)
        how = "yes" if gate_off() else dialog_answer(title, text, screens.LIMIT_YES)
        if how != "yes":
            raise RuntimeError(f"{not_yes(how, RECEIVED_NOT_YES)}, so no spending limit was set. Do not retry on your own; ask "
                               "Maya.")
        limits.seal(s.maya, limit, dialog_text(f"{title}\n{text}") + typed_note() + f"\nAnswer: {screens.LIMIT_YES}")
    print(screens.limit_line(limits.sealed(s.maya), _ceilings(s.pack or packs.starting())))
    print(LIMIT_SET_THEN)



def _ceilings(p: packs.Pack) -> list[int]:
    """The pack's limit for each history tier (pack.Pack.ceiling_msat), as many as the pack has."""
    return [p.ceiling_msat(t["id"]) for t in p.tiers()]


@_tool("maya")
def ard_pick(seller: str, said: str = "") -> None:
    """Step 5: seal the pick of ``seller`` ("alder" or "kestrel"), citing every assessment. When Maya named the seller
    herself, pass her words that named it as ``said``, word for word ("Pick Kestrel Print, the cheaper one."): the pick
    is sealed as hers. Leave ``said`` out only when she left the choice to you: the pick is then sealed as yours, and
    her payment question says you picked. A seller that is not GO ends here: no deal opens and nothing is paid. For a GO
    seller, ard_pay opens the deal and pays it next."""
    s = session()
    key = _seller_key(seller)
    if key not in s.assessed:
        raise RuntimeError("call ard_assess first")
    said = said.strip()
    if said and not buyer.names_only(said, key):
        raise RuntimeError(f"Maya's words do not name {SELLERS[key]['label']} alone, so they are not her pick of it. Pass "
                           "her words only when she named this seller; if she left the choice to you, call ard_pick "
                           "without them.")
    a = s.assessed[key]
    buyer.seal_pick(s.maya, s.keys[key], a, [m for k, m in s.assessed.items() if k != key], said)
    print(f"pick sealed before any payment: {SELLERS[key]['label']} at {screens.msat(a.price_msat)}, citing every assessment")
    if a.verdict != "GO":
        print(screens.limit_outcome(a))
        return
    s.picked[key] = said
    # no tool name: the agent repeated "Call ard_pay" to the person (evidencebook-skills#362; Sherlock2's words)
    print(f"{SELLERS[key]['label']} is within its limit. Ask Maya whether to pay it; nothing is paid until she says yes.")


#: How a held order's question ended other than Buy anyway, in Maya's terms (evidencebook-skills#412).
HELD_NOT_YES = {NO: "Maya chose Don't buy", NO_ANSWER: "Maya did not answer in time",
                NOT_SHOWN: "the question could not be shown"}


def _rail_clause() -> str:
    """Whether real money moves, as a payment question says it."""
    return "over Lightning, which moves real money" if _real() else "on the simulated rail, where no money moves"


def held_declined(name: str, price_msat: int) -> str:
    """After Don't buy, what Maya's agent offers next: one question to order again, naming the seller, the amount and
    the rail, so her yes to it is the fresh yes a declined order needs; another seller if she wants one; never a higher
    limit (Steven's hand run of 2026-11-26, evidencebook-skills#414). This question takes the place of the declined
    guard's, so her yes opens the dialog again on the next call (the hand run of #415 at 502bbc4: with the guard as well,
    the agent asked her a second question)."""
    return (f'Do not retry on your own. Ask Maya, in one question: "Want me to order again from {name} for '
            f'{screens.msat(price_msat)}, {_rail_clause()}?", and say she can choose another seller instead. On her yes '
            "to it, call ard_pay again: the dialog asks her once more. Never offer to change her spending limit: change "
            "it only when she asks for that in her own words.")


_RAIL_WORDS = ("over Lightning: this moves real money, to a wallet {shared} share", "on the simulated rail: no money moves")
_PAY = ("Step 6: pay the picked seller on the {rail}. A dialog appears in this window first and this call "
        "blocks, for up to 5 minutes, until the presenter answers it (Pay or Cancel; Buy anyway or Don't buy when the "
        "Everyday Rules hold the order; with Claude Code ACP it returns the question to show instead): do not retry or "
        "call it again while it waits. You cannot answer the dialog. If the step hands you a question to show, show it "
        "word for word, end your turn, and call ard_confirm after the person replies. Only after that yes does it send "
        "the order to the seller (the agreement names the deal's adjudicator and "
        "Action State's witness) and pay it. Refused "
        "unless ard_pick sealed this seller. It then waits for the seller's delivery and says what the seller's delivery "
        "record says it shipped. If this call instead ends in an error that the dialog timed out, nothing was paid and "
        "nothing was sent: say \"The approval timed out, so nothing was paid.\" and ask Maya, in one question, \"Want "
        "me to order again from <the seller> for <its price>, {again}?\"; on her yes, call ard_pay again.")


@_tool("maya", description=_PAY.format(rail="real Lightning rail: THIS MOVES REAL MONEY" if _real() else "SIMULATED rail: no money moves",
                                      again=_rail_clause()))
def ard_pay(seller: str) -> None:
    s = session()
    key = _seller_key(seller)
    if key not in s.picked:
        raise RuntimeError(f"no sealed pick of {SELLERS[key]['label']} within its limit: call ard_pick first")
    a, name = s.assessed[key], SELLERS[key]["label"]
    shared = f"{SELLERS['alder']['label']} and {SELLERS['kestrel']['label']}"
    words = _RAIL_WORDS[0].format(shared=shared) if _real() else _RAIL_WORDS[1]
    summary = f"Pay {name} {screens.msat(a.price_msat)} {words}."
    with s.pay_lock:
        if key in s.declined:
            held = s.declined.pop(key)
            raise Said(  # whole: past 400 characters for a held order's title, it read as the bare refusal (#412)
                f"the presenter did not approve the last payment to {name}, so this call opens no dialog and pays nothing. "
                f'The question is: "Pay {name} {screens.msat(a.price_msat)} {_rail_clause()}'
                + (f", although {held[:1].lower() + held[1:]}?" if held and held != "Approve this payment" else "?")
                + '" If Maya said yes to it after the dialog was declined, call ard_pay again now; otherwise ask her, end '
                "your turn, and call ard_pay again only after she says yes.")
        answer: dict = {}

        def ask(q: buyer.Question) -> str:
            answer["q"] = q
            if gate_off():
                answer["how"] = "yes"
            else:
                answer["how"] = dialog_answer(q.title, q.text, q.yes, q.no)
            return answer["how"]
        made = buyer.open_and_pay(s.home, s.maya, key, s.keys[key], a, s.adjudicator.named(), s.rail, summary, ask,
                                  print, simulated=not _real(), said=lambda w: dialog_text(w) + typed_note(), rail_words=words,
                                  request=s.ask, picked=s.picked[key])
        held = getattr(answer.get("q"), "held", None)
        if made is None:
            how = answer.get("how", NOT_SHOWN)
            if how == NO and held is None:  # a held order's answer asks the order-again question instead (held_declined)
                s.declined[key] = getattr(answer.get("q"), "title", "")
            if held is not None:  # the hold's own sentence first, whole, for Maya to read (#412)
                raise Said(screens.rules_held(held.reasons) + f" {not_yes(how, HELD_NOT_YES)}, so nothing was sent to {screens.stop(name)} "
                           + (held_declined(name, a.price_msat) if how == NO else "Do not retry on your own; if Maya "
                              "asks again, confirm with her first. Never say she declined it."))
            raise RuntimeError(f"{not_yes(how, NOT_YES)}, so the order was not placed: nothing was sent to the seller and nothing "
                               "was paid. Do not retry on your own; if Maya asks again, confirm with her first."
                               + ("" if how == NO else " Never say she declined it."))
        if held is not None:
            print(screens.rules_approved(held.reasons, held.over_limit))
        deal, payment = made
        s.deals.append(deal)
        who = ("the simulated rail paid it (no money moved)" if not _real() else "the buyer's wallet paid it")
        print(f"invoice {screens.msat(payment.invoice_msat)}; {who}: {payment.status}{screens.fee_note(payment.fee_msat, _real())}")
        print(f"waiting for {name}'s delivery")
        try:  # still under the lock: Maya's agent does not take this delivery while the payment tool waits for it
            observed = buyer.await_delivery(s.home, s.maya, deal)
        except pt.Refused as exc:
            print(f"{exc}.")
            return
    shipped = buyer.shipped(observed)
    print(screens.delivered_line(name, shipped))
    print(buyer.after_delivery(key, shipped))


#: How the receipt dialog ended other than Received, in Maya's terms (Sherlock2 on #304: "presenter" is our word).
RECEIVED_NOT_YES = {NO: "Maya chose Cancel", NO_ANSWER: "Maya did not answer in time",
                    NOT_SHOWN: "the dialog could not be shown"}


@_tool("maya")
def ard_confirm_received(seller: str, deal: str = "") -> None:
    """Ask Maya, in a dialog in this window, whether she received what she paid for in her deal with
    ``seller``; only her yes seals her statement that she did and sends it to the seller. Call only when Maya says she
    received the delivery, never on your own after a payment or a delivery. You cannot answer the dialog. If the step hands you a question to show, show it word for word, end your turn, and call ard_confirm after the person replies. With
    more than one deal with that seller still to confirm, pass ``deal`` (the deal id, or its first characters)."""
    s = session()
    key = _seller_key(seller)
    name = SELLERS[key]["label"]
    mine = [d for d in s.deals if d.seller == key]
    if not mine:
        raise RuntimeError(f"Maya has no deal with {name} in this run")
    if deal:  # the deal she named, among all her deals with this seller
        found = [d for d in mine if d.deal_id.removeprefix("deal-").startswith(deal.removeprefix("deal-"))]
        if len(found) != 1:
            raise RuntimeError(f"{'no' if not found else 'more than one'} deal with {name} matches {deal!r}: her deals "
                               "with it are " + ", ".join(d.deal_id[5:13] for d in mine))
        target = found[0]
    else:  # the one still to confirm; with none, her latest
        open_ = buyer.to_confirm(s.maya, mine)
        if len(open_) > 1:
            raise RuntimeError(f"Maya has {len(open_)} deals with {name} still to confirm (" +
                               ", ".join(d.deal_id[5:13] for d in open_) + "): ask her which, then pass it as deal")
        target = open_[0] if open_ else mine[-1]
    if buyer.received_said(s.maya, target):
        print(f"Maya already said she received it: {name} has her statement for deal {target.deal_id[5:13]}.")
        _deal_state(s.maya, target.deal_id)
        return
    if buyer.disputed(s.maya, target):
        raise RuntimeError(f"Maya disputed her delivery from {name} (deal {target.deal_id[5:13]}): her dispute stands, "
                           "and nothing was sent")
    with s.pay_lock:  # not while the payment tool or Maya's agent takes the same delivery
        observed = buyer.take_delivery(s.home, s.maya, target)
    if observed is None:
        raise RuntimeError(f"{name} has not delivered yet, so there is nothing to confirm")
    text = (f"Did you receive what you paid for from {name}? Its delivery record says {buyer.shipped(observed)} were "
            f"shipped. Choosing Received sends {name} your statement that you received it.")
    how = "yes" if gate_off() else dialog_answer("Confirm what you received", text, "Received")
    if how != "yes":
        raise RuntimeError(f"{not_yes(how, RECEIVED_NOT_YES)}, so nothing was sent in Maya's name. Do not retry on your own; ask "
                           "Maya.")
    with s.pay_lock:
        buyer.close_received(s.home, s.maya, target)
    print(f"Maya's statement sent to {name}: she received what she paid for.")
    _deal_state(s.maya, target.deal_id)


def _deal_state(p: pt.Party, deal_id: str) -> None:
    """The deal's rows as her receipt says them now, so the deal's state is the receipt's, never the agent's own word
    ("complete" for a deal still open to dispute, evidencebook-skills#457). A report rests on a checkpoint and her
    statement was sealed after the last one, so a checkpoint is taken first (as ard_show_card does); a report still not
    ready says so."""
    import receipt

    try:
        p.stamp()
    except pt.Refused as exc:
        p.log(f"stamp for the deal's state after her statement: {exc!r}")
    try:
        rep = p.report(deal_id)
    except pt.Refused as exc:
        p.log(f"report of {deal_id} after her statement: {exc!r}")
        print(f"Her receipt for deal {deal_id[5:13]} is not ready yet, so its state is not shown here; ask for the "
              "receipt in a minute.")
        return
    print(f"Her receipt for deal {deal_id[5:13]} now says: " + "; ".join(receipt.row_lines(rep.get("report", rep))) + ".")


@_tool("maya")
def ard_countersign(seller: str, deal: str = "") -> None:
    """Have the demo's countersigner countersign Maya's own records of her latest deal with ``seller`` (the countersign
    upgrade, after a deal is done). Call only when Maya asks for it, never on your own. It sends the countersigner her
    own records as digests with their seal times, and her own payments' amounts, fees, references and status (never a
    payment's secret, never the seller's records), and nothing to the seller. With more than one deal with that
    seller, pass ``deal`` (the deal id, or its first characters)."""
    import countersigner as cs
    import receipt

    s = session()
    key = _seller_key(seller)
    name = SELLERS[key]["label"]
    mine = [d for d in s.deals if d.seller == key]
    if not mine:
        raise RuntimeError(f"Maya has no deal with {name} in this run")
    if deal:
        found = [d for d in mine if d.deal_id.removeprefix("deal-").startswith(deal.removeprefix("deal-"))]
        if len(found) != 1:
            raise RuntimeError(f"{'no' if not found else 'more than one'} deal with {name} matches {deal!r}: her deals "
                               "with it are " + ", ".join(d.deal_id[5:13] for d in mine))
        target = found[0]
    else:
        target = mine[-1]
    try:
        service = cs.env(Path(os.environ.get("ARD_COUNTERSIGN_DIR") or cs.default_dir(s.home)))
    except cs.CountersignerError as exc:
        raise RuntimeError(str(exc)) from None
    with s.pay_lock:  # not while another of Maya's steps writes her book
        stamp = s.maya.countersign(target.deal_id, service)
    print(f"Maya's deal {target.deal_id[5:13]} with {name}: " + receipt.countersign_line(stamp, "Maya", name))


#: One ard_confirm collects a step's outcome at a time.
_collect = threading.Lock()
#: How long ard_confirm waits for the person's reply to reach Goose's record before it says there is none yet.
CONFIRM_WAIT_S = 6


@_tool("maya")
def ard_confirm() -> None:
    """Only after you showed the person a question a step asked them to answer by typing in this chat, word for word,
    and they replied: the outcome of that step. Their reply is read from this chat's own record, never from you, so
    never call this to answer it yourself. It says when no reply has come yet."""
    if not _collect.acquire(timeout=CONFIRM_WAIT_S):
        raise RuntimeError("another ard_confirm is collecting that step's outcome")
    try:
        if not _waiting:
            raise RuntimeError("no step is waiting for a typed reply")
        job = _waiting[0]
        if not job.answered.wait(CONFIRM_WAIT_S):
            print("No reply from the person yet. Show them the question exactly as the step gave it, then end your "
                  "turn.")
            return
        print(_until_paused_or_done(job))
    finally:
        _collect.release()


#: How the dispute dialog ended other than Dispute, in Maya's terms (as RECEIVED_NOT_YES).
DISPUTE_NOT_YES = {NO: "Maya chose Cancel", NO_ANSWER: "Maya did not answer in time",
                   NOT_SHOWN: "the dialog could not be shown"}


@_tool("maya")
def ard_dispute(seller: str, deal: str = "") -> None:
    """Dispute the delivery of Maya's deal with ``seller``, only after her yes in a dialog in this window
    (evidencebook-skills#333): her signed statement that it was not met, and a dispute, sent to the seller and to the
    adjudicator the agreement names, which then asks each side for its books. It moves no money. Call only when Maya
    says the delivery was short or did not come. This call blocks, for up to 5 minutes, until she answers Dispute or
    Cancel (with Claude Code ACP it returns the question to show instead): do not call it again while it waits; you
    cannot answer the dialog. If the step hands you a question to show, show it word for word, end your turn, and call ard_confirm after the person replies. With more than one deal with that
    seller, pass ``deal`` (the deal id, or its first characters)."""
    s = session()
    key = _seller_key(seller)
    name = SELLERS[key]["label"]
    # only deals the seller agreed: an offer withdrawn unanswered (buyer.open_deal) is no deal to dispute. Not "paid":
    # a payment can move money and still fail to reach the seller's records
    mine = [d for d in s.deals if d.seller == key and buyer.agreed(s.home, d)]
    if not mine:
        raise RuntimeError(f"Maya has no deal with {name} that it agreed to in this run, so there is nothing to dispute")
    if deal:
        found = [d for d in mine if d.deal_id.removeprefix("deal-").startswith(deal.removeprefix("deal-"))]
        if len(found) != 1:
            raise RuntimeError(f"{'no' if not found else 'more than one'} deal with {name} matches {deal!r}: her deals "
                               "with it are " + ", ".join(d.deal_id[5:13] for d in mine))
        target = found[0]
    elif len(mine) > 1:  # never a guess between two orders that look the same in the dialog
        raise RuntimeError(f"Maya has {len(mine)} deals with {name} (" + ", ".join(d.deal_id[5:13] for d in mine) +
                           "): ask her which, then pass it as deal")
    else:
        target = mine[0]
    if buyer.disputed(s.maya, target):
        print(f"Maya already disputed this delivery: {name} and the adjudicator have it (deal {target.deal_id[5:13]}).")
        return
    if buyer.received_said(s.maya, target):
        raise RuntimeError(f"Maya already said she received what she paid for from {name} (deal "
                           f"{target.deal_id[5:13]}): nothing was sent")
    with s.pay_lock:  # not while the payment tool or Maya's agent takes the same delivery
        observed = buyer.take_delivery(s.home, s.maya, target)
    record = (f"Its delivery record says {buyer.shipped(observed)} were shipped." if observed is not None
              else f"{name} has sent no delivery record yet.")
    which = f" (deal {target.deal_id[5:13]})" if len([d for d in s.deals if d.seller == key]) > 1 else ""
    text = (f"Dispute your delivery from {name}{which}? {record} Choosing Dispute sends {name} and the adjudicator your signed "
            "statement that the delivery was not met. It moves no money.")
    how = "yes" if gate_off() else dialog_answer("Dispute this delivery", text, "Dispute")
    if how != "yes":
        raise RuntimeError(f"{not_yes(how, DISPUTE_NOT_YES)}, so nothing was sent in Maya's name. Do not retry on your own; ask "
                           "Maya.")
    buyer.dispute(s.home, s.maya, target, print)
    print(screens.DISPUTE_RAISED.format(seller=name))
    with s.pay_lock:  # read again: a delivery record can arrive while the dialog waits (Codex on #464)
        observed = buyer.take_delivery(s.home, s.maya, target)
    print(screens.dispute_stated(name, buyer.shipped(observed) if observed is not None else None))


# -- the sellers --------------------------------------------------------------------------------------

@_tool("alder", "kestrel")
def ard_seller_activity() -> None:
    """What your owner's selling process did on its own, in their words: their commitment, the deal asked of them, the
    payment, their delivery, a dispute and a ruling, then each ruling entered as their records hold it now (the
    outcome, when Action State's witness stamped it, and any refund), and their own History card now."""
    sel = seller()
    print(f"{sel.label}: your own profile, keys and records (this window only)")
    for line in list(sel.log):
        print("  " + line)
    for deal_id, stamped_at in flow.rulings_entered(sel.party).items():  # read now, so a stamp that came late shows
        try:
            rep = sel.party.report(deal_id)
        except pt.Refused as exc:  # one deal's report never hides the others or the card
            sel.party.log(f"report of {deal_id} for the ruling line: {exc!r}")
            print(f"  ruling on deal {deal_id[5:13]}: its report is not ready yet; ask again in a minute.")
            continue
        for line in screens.ruled_for_seller(rep.get("report", rep), stamped_at,
                                             flow.delivery_record(sel.party, deal_id)):
            print(f"  ruling on deal {deal_id[5:13]}: {line}")
    card, _, _ = flow.read_card(sel.party.card_bundle(shared=True))
    print(f"now: {screens.card_line(card)}")
    print("  " + screens.own_sample_note(sel.name, card["outcomes"]["of"], _real()))


# -- the adjudicator ----------------------------------------------------------------------------------

def _adjudicator() -> adj.Adjudicator:
    global _seller_lock
    if _seller_lock is None:
        _seller_lock = _lock(ADJUDICATOR)
        stage.ensure_stage(_home())
        threading.Thread(target=_ask_on_arrival, daemon=True).start()
    return adj.Adjudicator(_home())


#: How often the adjudicator's window looks for a dispute that has arrived and a case it can rule (_ask_on_arrival).
ASK_EVERY_S = 3


def _ask_on_arrival() -> None:
    """The adjudicator's own work, with no person (Ethan, 2026-11-26, evidencebook-skills#416): it asks each side for
    its books as soon as a dispute arrives (evidencebook-skills#326), rules each case the books decide
    (``Adjudicator.rule_decided``), and sends again any ruling not yet sent or stamped (``Adjudicator.resume``). This loop is the only place a ruling is sealed in this window; ``ard_case`` only reads.
    Each step is idempotent; a failure is written to the adjudicator's log and tried again on the next round."""
    a = adj.Adjudicator(_home())
    while True:
        for step in (a.ask, a.rule_decided, a.resume):
            try:
                step()
            except Exception as exc:  # noqa: BLE001: a background step never ends the window's server
                a.party.log(f"{step.__name__}: {exc!r}")
        time.sleep(ASK_EVERY_S)


@_tool("adjudicator", plain=True)
def ard_case() -> None:
    """Show the disputes sent to this adjudicator: what the adjudicator ruled and why, or why it has not; who answered
    its request for their books (each side's agent answers on its own, with its own book and the copy it holds of the
    other side's); and what the books show (the seller's own signed delivery record, each side's statement on the row).
    The adjudicator rules on its own, with no person; this tool decides nothing and records nothing. Its output is the
    whole answer: the person reads it as printed."""
    a = _adjudicator()
    cases = _settle(a, a.gather(30))
    if not cases:
        print("no case yet: a party has sent no dispute to this adjudicator")
        return
    print(screens.ADJUDICATOR_INDEPENDENCE)
    for raw in cases:
        print()
        print("\n".join(flow.case_lines(flow.case_view(raw, flow.case_names(raw)), flow.case_names(raw))))
        _sent_line(raw)


@_tool("adjudicator", plain=True)
def ard_ruling() -> None:
    """Show what this adjudicator ruled on each case and why, or why it has not, in the adjudicator's own lines, under
    the line that it is not independent of the parties. Call it whenever the person asks about the ruling, its reason or
    the adjudicator's independence. It reads only: it asks no one, decides nothing and records nothing. Its output is
    the whole answer: the person reads it as printed."""
    a = _adjudicator()
    cases = _settle(a, a.cases())
    if not cases:
        print("no case yet: a party has sent no dispute to this adjudicator")
        return
    print(screens.ADJUDICATOR_INDEPENDENCE)
    for raw in cases:
        names = flow.case_names(raw)
        c = flow.case_view(raw, names)
        print()
        print(flow.case_header(c, names))
        print("\n".join(f"  {line}" for line in flow.ruling_lines(c, names)))
        _sent_line(raw)


def _settle(a: adj.Adjudicator, cases: list[dict]) -> list[dict]:
    """``cases`` once each case whose answers are both in is ruled or settled: the window's loop checks and rules within
    a round or two, so a view waits up to :data:`CASE_WAIT_S` for it."""
    stop = time.monotonic() + CASE_WAIT_S
    while time.monotonic() < stop and any(len(c["answers"]) == 2 and not c["ruling"] and not _settled(c)
                                          for c in cases):
        time.sleep(1)
        cases = a.cases()
    return cases


def _sent_line(raw: dict) -> None:
    """Whether the ruling went to both parties, or its stamp is still being asked for."""
    r = raw["ruling"]
    if r and pt.witnessed() and not adj.stamped(_home(), raw["deal_id"]):
        print(f"Its stamp is not taken yet: this window keeps asking {pt.WITNESS_NAME} and sends the ruling to "
              "both parties again with its stamp. Keep this window open until then.")
    elif r:
        print("Sent to both parties; each enters it in its own records.")


#: How long ard_case waits for the window's loop to rule a case whose answers are both in.
CASE_WAIT_S = 30


def _settled(case: dict) -> bool:
    """The adjudicator checked this case on the answers it has now and the check did not decide it (a decisive check
    is waited on until its ruling is sealed)."""
    return adj.needs_person(case.get("decision"), case["answers"])


@_tool("adjudicator", plain=True)
def ard_case_activity() -> None:
    """Whether each party entered this adjudicator's ruling in its own records, read from the books they sent back:
    the ruling's own time-stamp, then each party's entry and whether it is time-stamped. A book or a stamp that has not
    come back yet comes on its own: ask again in a minute."""
    a = _adjudicator()
    ruled = [c for c in a.cases() if c["ruling"]]
    if not ruled:
        print("no ruling yet")
        return
    for c in ruled:
        print("\n".join(flow.entry_lines(c["deal_id"], a.entries(c), flow.case_names(c))))


# -- every party: its own card and receipt ---------------------------------------------------------------

def _own() -> tuple[pt.Party, str]:
    if ROLE in SELLERS:
        sel = seller()
        return sel.party, sel.label
    return session().maya, "Maya"


@_tool("maya", "alder", "kestrel")
def ard_show_card() -> None:
    """Show THIS window's own History card as of a checkpoint taken now (or its last one, if the witness does not take a
    new one): deals counted, held, did not hold, and disputes others raised about it; in the buyer's window also the
    spending limit the person confirmed (ard_set_limit), or that none is set. The buyer's first turn calls it."""
    p, name = _own()
    limit = None if ROLE in SELLERS else limits.sealed(p)
    try:
        p.stamp()
    except pt.Refused as exc:  # the card as of its last checkpoint still shows, and the time says which (#331)
        p.log(f"stamp for the card: {exc!r}")
    card, as_of, _ = flow.read_card(p.card_bundle(shared=True))
    its = "your" if ROLE in SELLERS else "its"  # a seller's owner types in its window (Sherlock2 on #456)
    print(f"{name}: {its} own History card, as of {its} checkpoint at {screens.local_time(as_of['anchor_time'], date=True)}")
    print("  " + screens.card_line(card))
    if ROLE in SELLERS:
        print("  " + screens.own_sample_note(ROLE, card["outcomes"]["of"], _real()))
        return
    s = session()
    s.pack = s.pack or packs.starting()
    print("  " + screens.limit_line(limit, _ceilings(s.pack)))
    for d in s.deals:  # a deal ruled for her says what that means, beside the card's "not final yet" count
        try:
            rep = p.report(d.deal_id)
        except pt.Refused as exc:
            p.log(f"report of {d.deal_id} for the card: {exc!r}")
            continue
        for line in screens.ruled_for_buyer(rep.get("report", rep), SELLERS[d.seller]["label"],
                                            flow.delivery_record(p, d.deal_id)):
            print(f"  deal {d.deal_id[5:13]} with {SELLERS[d.seller]['label']}: {line}")


def _own_deal() -> tuple[pt.Party, str, str | None]:
    p, name = _own()
    if ROLE in SELLERS:
        ids = [d["deal_id"] for d in p.deals() if d.get("version") == "x-deal-v1"]
        live = [i for i in ids if (p.dir / "handled" / f"{i}.offer").exists()]
        return p, name, (live[-1] if live else None)
    d = session().latest()
    return p, name, (d.deal_id if d else None)


@_tool("maya", "alder", "kestrel")
def ard_show_receipt() -> None:
    """Show THIS window's own receipt for its latest deal of this run: capsulectl's report of the deal, each row's
    status, read from its own records."""
    import receipt

    p, name, deal_id = _own_deal()
    if deal_id is None:
        print(f"{name}: no deal yet, so no receipt")
        return
    other = "" if ROLE in SELLERS else SELLERS[session().latest().seller]["label"]
    print(receipt.receipt_text(p, name, deal_id, real=_real(), seller=ROLE in SELLERS, counterparty=other))


@_tool("maya", "alder", "kestrel")
def ard_open_receipt_page() -> None:
    """Open THIS window's own receipt for its latest deal as a page in the browser: capsulectl's own
    page of its copy of the deal (deal report --html), with capsulectl's verify report, with nothing added. Its witness
    line is the same as ard_show_receipt's: it says a time only when capsulectl verify reported one."""
    import pages
    import receipt

    p, name, deal_id = _own_deal()
    if deal_id is None:
        print(f"{name}: no deal yet, so no receipt page")
        return
    try:
        path = receipt.receipt_page(p, name, deal_id, rail=_rail_name(), seller=ROLE in SELLERS)
    except receipt.ReceiptError as exc:
        p.log(f"receipt page of {deal_id}: {exc!r}")
        print(f"{name}: no receipt page yet; ask again in a minute.")
        return
    opened = pages.open_page(path)
    its = "your" if ROLE in SELLERS else "its"
    print(f"{name}: {its} receipt page " + ("opened in the browser; nothing else is needed (do not copy or link the "
                                            "file)" if opened else "written (not opened)") + f": {path}")
    if ROLE not in SELLERS:  # what a ruled deal's page shows at its top, said here too (#411's hand run)
        d = session().latest()
        try:
            rep = p.report(deal_id)
        except pt.Refused as exc:
            p.log(f"report of {deal_id} for the receipt page: {exc!r}")
        else:
            for line in screens.ruled_for_buyer(rep.get("report", rep), SELLERS[d.seller]["label"],
                                                flow.delivery_record(p, deal_id)):
                print(f"deal {deal_id[5:13]}: {line}")


@_tool("maya", "alder", "kestrel")
def ard_open_card_page() -> None:
    """Open THIS window's own History card as a page in the browser."""
    import pages

    p, name = _own()
    path = pages.card_page(p, name, rail=_rail_name(), seller=ROLE in SELLERS)
    opened = pages.open_page(path)
    its = "your" if ROLE in SELLERS else "its"
    print(f"{name}: {its} History card page " + ("opened in the browser; nothing else is needed (do not copy or link "
                                                 "the file)" if opened else "written (not opened)") + f": {path}")


def main() -> None:
    if ROLE in SELLERS:
        seller()  # a seller's agent runs from the moment its window opens, so the buyer finds it
    elif ROLE == ADJUDICATOR:
        _adjudicator()
    server.run()


if __name__ == "__main__":
    main()
