# SPDX-License-Identifier: Apache-2.0
"""The presenter's dialogs (Set limit, the payment's, Received, Dispute, the ruling's), each a form in the party's own
Goose window (MCP elicitation, evidencebook-skills#418): only the yes answer approves; everything else refuses. The
window is a real MCP client over memory streams here, so no Goose and no engine is needed."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import types

import anyio
import pytest
from mcp import types as mt
from mcp.client.client import Client

import desktop_server as ds

HERE = Path(__file__).resolve().parents[1]


def pay_dialog(summary: str) -> bool:
    return ds.ask_person("Approve this payment", summary, "Pay")


# -- the mapping from the window's answer, with the window stubbed ----------------------------------------------------

def window(monkeypatch, *answers, took=60.0):
    """The window answers each ask in turn: an ElicitResult, or an exception to raise. ``took`` seconds pass per ask."""
    asked, clock = [], [0.0]
    monkeypatch.setattr(ds.time, "monotonic", lambda: clock[0])
    queue = list(answers)

    def ask(ctx, message, schema, wait_s):
        asked.append((message, schema, wait_s))
        clock[0] += min(took, wait_s)
        a = queue.pop(0)
        if isinstance(a, BaseException):
            raise a
        return a
    monkeypatch.setattr(ds, "_ask_window", ask)
    monkeypatch.setattr(ds._call, "ctx", object(), raising=False)
    return asked


def said(answer: str) -> mt.ElicitResult:
    return mt.ElicitResult(action="accept", content={ds.ANSWER_FIELD: answer})


def test_only_the_pay_answer_approves(monkeypatch):
    window(monkeypatch, said("Pay"))
    assert pay_dialog("Pay Alder 289 msat") is True


@pytest.mark.parametrize("answer,took,expected", [
    (said("Pay"), 60, "yes"),
    (said("Cancel"), 60, ds.NO),                                     # the preset safe answer, submitted
    (mt.ElicitResult(action="accept", content={}), 60, ds.NO_ANSWER),  # submitted with nothing chosen
    (said("pay"), 60, ds.NO_ANSWER),                                 # never a near match
    (RuntimeError("Elicitation not supported"), 0.1, ds.NOT_SHOWN),  # a window that cannot show a form
    # the Claude Code adapter auto-declines a form its client cannot draw: never the presenter's no
    (mt.ElicitResult(action="decline"), 0.1, ds.NOT_SHOWN),
])
def test_the_dialog_says_how_it_ended_so_a_timeout_is_never_called_a_decline(monkeypatch, answer, took, expected):
    # #239 finding 11: a dialog that timed out was reported as "declined"
    window(monkeypatch, answer, took=took)
    assert ds.dialog_answer("Approve this payment", "Pay X", "Pay") == expected
    assert expected == "yes" or "declined" not in ds.NOT_YES[expected] or expected == ds.NO


def test_no_window_means_not_shown(monkeypatch):
    monkeypatch.setattr(ds._call, "ctx", None, raising=False)
    assert ds.dialog_answer("Approve this payment", "Pay X", "Pay") == ds.NOT_SHOWN


def test_goose_ending_its_form_asks_again_until_ten_minutes_then_no_answer(monkeypatch):
    # Goose Desktop 1.59.2 ends a form after 300 s; the dialog keeps the 10 minutes by asking again with the same words
    asked = window(monkeypatch, mt.ElicitResult(action="cancel"), mt.ElicitResult(action="cancel"), took=300)
    assert ds.dialog_answer("Approve this payment", "Pay X", "Pay") == ds.NO_ANSWER
    assert len(asked) == 2 and asked[0][:2] == asked[1][:2]
    assert [a[2] for a in asked] == [600, 300] and ds.DIALOG_GIVE_UP_S == 600


def test_goose_s_own_expiry_error_also_asks_again(monkeypatch):
    # on Goose's own MCP path its 300 s expiry comes back as an error (mcp_client.rs create_elicitation), not a cancel
    asked = window(monkeypatch, RuntimeError("Elicitation request timed out or failed"), said("Pay"), took=300)
    assert ds.dialog_answer("Approve this payment", "Pay X", "Pay") == "yes" and len(asked) == 2


def test_an_answer_to_the_second_form_counts(monkeypatch):
    window(monkeypatch, mt.ElicitResult(action="cancel"), said("Pay"), took=300)
    assert ds.dialog_answer("Approve this payment", "Pay X", "Pay") == "yes"


def test_the_ten_minutes_ending_is_no_answer(monkeypatch):
    window(monkeypatch, TimeoutError())
    assert ds.dialog_answer("Approve this payment", "Pay X", "Pay") == ds.NO_ANSWER


def test_a_form_ended_at_once_was_not_shown_and_is_not_asked_again(monkeypatch):
    # a window that cannot draw the form cancels it at once: no loop of asks for ten minutes
    asked = window(monkeypatch, mt.ElicitResult(action="cancel"), took=0.1)
    assert ds.dialog_answer("Approve this payment", "Pay X", "Pay") == ds.NOT_SHOWN
    assert len(asked) == 1


def test_a_window_gone_after_the_form_was_shown_is_no_answer(monkeypatch):
    window(monkeypatch, mt.ElicitResult(action="cancel"), RuntimeError("closed"), took=300)
    assert ds.dialog_answer("Approve this payment", "Pay X", "Pay") == ds.NO_ANSWER


@pytest.mark.parametrize("title,yes,no", [
    ("Set your spending limit", "Set limit", "Cancel"),
    ("Approve this payment", "Pay", "Cancel"),
    ("This order needs your OK", "Buy anyway", "Don't buy"),
    ("Confirm what you received", "Received", "Cancel"),
    ("Dispute this delivery", "Dispute", "Cancel"),
    ("Rule on this case", "Rule", "Cancel"),
])
def test_every_dialog_presets_the_safe_answer(monkeypatch, title, yes, no):
    asked = window(monkeypatch, said(no))
    assert ds.dialog_answer(title, "the words", yes, no) == ds.NO
    message, schema, _ = asked[0]
    field = schema["properties"][ds.ANSWER_FIELD]
    assert field["enum"] == [no, yes] and field["default"] == no and schema["required"] == [ds.ANSWER_FIELD]
    assert message.startswith(title) and message.endswith("the words.")


def test_quotes_in_the_words_are_shown_as_they_are_sealed(monkeypatch):
    asked = window(monkeypatch, said("Cancel"))
    pay_dialog('x" & (do shell script "id") & "')
    assert asked[0][0] == "Approve this payment. " + ds.dialog_text('x" & (do shell script "id") & "') + "."


def test_the_dialog_names_no_demo(monkeypatch):
    asked = window(monkeypatch, said("Cancel"))
    pay_dialog("Pay Alder Print Co. 289 msat over Lightning: this moves real money.")
    assert asked[0][0].startswith("Approve this payment.") and "demo" not in asked[0][0].lower()


def test_no_osascript_in_the_dialogs():
    src = Path(ds.__file__).read_text()
    assert "osascript" not in src and "display dialog" not in src and "display notification" not in src


def test_summary_wording_names_the_rail():
    # the text the presenter reads: real money on the real rails, none on the simulated one, and no word of a demo
    src = open(ds.__file__).read()
    assert 'over Lightning: this moves real money, to a wallet {shared} share"' in src and '"on the simulated rail: no money moves"' in src
    assert '"over Lightning, which moves real money"' in src and "REAL Lightning rail" not in src
    assert "settles to the demo" not in src and "ARD demo: approve" not in src


def test_the_assess_tool_description_names_no_demo():
    # the agent may repeat its tool description on screen
    assert "demo" not in (ds.ard_assess.__doc__ or "").lower()


def test_approval_none_is_refused_on_a_real_rail(monkeypatch):
    monkeypatch.setenv("ARD_APPROVAL", "none")
    monkeypatch.setenv("ARD_RAIL", "local")
    with pytest.raises(RuntimeError, match="refused on the local rail"):
        ds.gate_off()


# -- through a real MCP client: the form goes to the window, and only the window's answer comes back ------------------

@ds._tool(ds.ROLE)
def ard_test_dialog(words: str) -> None:
    """A tool that asks one dialog, for these tests only."""
    print(ds.dialog_answer("Approve this payment", words, "Pay"))


def call(answer, timeout_s: float = 30, meta: dict | None = None):
    """Call ard_test_dialog through an MCP client whose window answers with ``answer(params)``; its text and the
    forms the window was asked."""
    forms = []

    async def elicit(context, params):
        forms.append(params)
        return answer(params)

    async def run():
        async with Client(ds.server, mode="legacy", elicitation_callback=elicit) as client:
            with anyio.fail_after(timeout_s):
                result = await client.call_tool("ard_test_dialog", {"words": "Pay Alder 289 msat"}, meta=meta)
        return result.content[0].text, forms
    return anyio.run(run)


def test_the_form_reaches_the_window_and_its_answer_comes_back():
    text, forms = call(lambda p: said("Pay"))
    assert text == "yes" and len(forms) == 1
    assert forms[0].message == "Approve this payment. Pay Alder 289 msat."
    assert forms[0].requested_schema["properties"][ds.ANSWER_FIELD]["default"] == "Cancel"


def test_the_safe_answer_from_the_window_refuses():
    assert call(lambda p: said("Cancel"))[0] == ds.NO


def test_a_window_without_forms_is_not_shown():
    assert call(lambda p: mt.ErrorData(code=mt.INVALID_REQUEST, message="Elicitation not supported"))[0] == ds.NOT_SHOWN


def test_the_form_carries_back_the_tool_call_goose_named():
    # Goose puts a form in the chat and tool call whose ids it reads back from the form's _meta (ds.ECHOED_META)
    meta = {"agent-session-id": "s-1", "agent-tool-call-request-id": "call-7", "other": "x"}
    _, forms = call(lambda p: said("Pay"), meta=meta)
    got = forms[0].meta if isinstance(forms[0].meta, dict) else forms[0].meta.model_dump(by_alias=True)
    assert {k: got.get(k) for k in ds.ECHOED_META} == {"agent-session-id": "s-1", "agent-tool-call-request-id": "call-7"}
    assert "other" not in got


def test_two_calls_at_once_each_get_their_own_answer():
    # two dialogs open at the same time in one window: each answer reaches only the call that asked it
    async def elicit(context, params):
        await anyio.sleep(0.2 if "first" in params.message else 0)  # the second is answered first
        return said("Pay" if "first" in params.message else "Cancel")

    async def run():
        out = {}
        async with Client(ds.server, mode="legacy", elicitation_callback=elicit) as client:
            async def one(words):
                out[words] = (await client.call_tool("ard_test_dialog", {"words": words})).content[0].text
            with anyio.fail_after(30):
                async with anyio.create_task_group() as tg:
                    tg.start_soon(one, "first")
                    tg.start_soon(one, "second")
        return out
    assert anyio.run(run) == {"first": "yes", "second": ds.NO}


def test_the_request_context_is_no_input_of_any_tool():
    async def run():
        async with Client(ds.server, mode="legacy") as client:
            return (await client.list_tools()).tools
    for tool in anyio.run(run):
        assert "ard_request" not in tool.input_schema.get("properties", {}), tool.name


# -- the party's own agent cannot answer its own dialog ----------------------------------------------------------------

#: Every tool each window's agent has, and its inputs. A dialog's answer comes only from the window's form, or from the
#: person's own typed message in Goose's record of the chat (the tests above and below); none of these tools takes an
#: answer (ard_confirm takes no input and only collects what the record says), so the agent has no button to press.
#: A new tool fails this test until it is added here, after checking that it answers no dialog.
TOOLS = {
    "maya": {"ard_find_sellers": ["ask"], "ard_set_limit": ["limit_msat"], "ard_show_listing": ["seller"],
             "ard_show_history": [], "ard_assess": [], "ard_pick": ["seller"], "ard_pay": ["seller"],
             "ard_confirm_received": ["seller", "deal"], "ard_countersign": ["seller", "deal"],
             "ard_dispute": ["seller", "deal"], "ard_show_card": [], "ard_open_card_page": [],
             "ard_show_receipt": [], "ard_open_receipt_page": [], "ard_confirm": []},
    "alder": {"ard_seller_activity": [], "ard_show_card": [], "ard_open_card_page": [], "ard_show_receipt": [],
              "ard_open_receipt_page": []},
    "adjudicator": {"ard_case": [], "ard_rule": ["seller"], "ard_case_activity": []},
}
TOOLS["kestrel"] = TOOLS["alder"]

LIST = """
import anyio, json, sys
from mcp.client.client import Client
import desktop_server as ds
async def run():
    async with Client(ds.server, mode="legacy") as c:
        return {t.name: sorted(t.input_schema.get("properties", {})) for t in (await c.list_tools()).tools}
print(json.dumps(anyio.run(run)))
"""


@pytest.mark.parametrize("role", sorted(TOOLS))
def test_no_tool_of_the_agent_answers_a_dialog(role):
    env = {**os.environ, "ARD_ROLE": role, "PYTHONPATH": os.pathsep.join([str(HERE), *sys.path])}
    run = subprocess.run([sys.executable, "-c", LIST], env=env, capture_output=True, text=True, cwd=HERE,
                         stdin=subprocess.DEVNULL, timeout=60)
    assert run.returncode == 0, run.stderr
    import json
    assert json.loads(run.stdout) == {k: sorted(v) for k, v in TOOLS[role].items()}
    src = Path(ds.__file__).read_text()
    # the only place a dialog's answer is read: the window's own response to the form it was sent
    assert src.count("_ask_window(") == 2 and src.count("result.content") == 1


# -- the typed reply, when the window cannot show a form (Claude Code ACP) --------------------------------------------

import json as _json
import sqlite3 as _sqlite3


class Record:
    """Goose's record of its chats (sessions.db), as Goose 1.59.2 writes it: the tables and columns the dialog reads."""

    def __init__(self, path):
        self.path = path
        con = _sqlite3.connect(path)
        con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, message_id TEXT, session_id TEXT NOT "
                    "NULL, role TEXT NOT NULL, content_json TEXT NOT NULL, created_timestamp INTEGER NOT NULL)")
        con.commit()
        con.close()

    def add(self, session, role, content, at=None):
        con = _sqlite3.connect(self.path)
        con.execute("INSERT INTO messages (session_id, role, content_json, created_timestamp) VALUES (?, ?, ?, ?)",
                    (session, role, _json.dumps(content), int(at if at is not None else __import__("time").time())))
        con.commit()
        con.close()

    def typed(self, session, text, at=None):
        self.add(session, "user", [{"type": "text", "text": text}], at)


@pytest.fixture
def record(tmp_path, monkeypatch):
    monkeypatch.setenv("ARD_GOOSE_DB", str(tmp_path / "sessions.db"))
    monkeypatch.setenv("ARD_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(ds, "REPLY_POLL_S", 0.05)
    monkeypatch.setattr(ds, "CONFIRM_WAIT_S", 2)
    ds._waiting.clear()
    yield Record(tmp_path / "sessions.db")
    # end every worker this test started before its patches go: none may read a later test's record
    ds._shutdown.set()
    for job in list(ds._waiting) + list(ds._rounds.values()):
        job.done.wait(5)
    ds._waiting.clear()
    ds._rounds.clear()
    ds._shutdown.clear()


def no_form(monkeypatch):
    monkeypatch.setattr(ds, "_form_answer", lambda *a: ds.NOT_SHOWN)


@ds._tool(ds.ROLE)
def ard_test_typed() -> None:
    """A tool that asks one dialog, for these tests only."""
    print("before the question")
    how = ds.dialog_answer("Approve this payment", "Pay Kestrel Print 1,000 msat.", "Buy anyway", "Don't buy")
    print(f"answer: {how}{ds.typed_note()!r}")


def call_typed(monkeypatch, meta):
    ctx = types.SimpleNamespace(request_context=types.SimpleNamespace(meta=meta, session=None), request_id="1")
    real = ds._run_job
    monkeypatch.setattr(ds, "_run_job", lambda job, fn, a, k, c, tok: real(job, fn, a, k, ctx, tok))
    return ard_test_typed()


def test_without_a_form_the_tool_returns_the_question_and_the_exact_reply(monkeypatch, record):
    no_form(monkeypatch)
    out = call_typed(monkeypatch, {"agent-session-id": "chat-1"})
    assert out.startswith("before the question")
    assert "Approve this payment. Pay Kestrel Print 1,000 msat." in out
    assert "type exactly: Buy anyway" in out and "means Don't buy" in out and "call ard_confirm" in out


@pytest.mark.parametrize("reply,expected", [
    ("Buy anyway", "yes"), ("buy anyway.", "yes"), ("  Buy anyway  ", "yes"),
    ("yes", ds.NO), ("Buy anyway, please", ds.NO), ("Don't buy", ds.NO),
])
def test_only_the_exact_typed_reply_is_yes(monkeypatch, record, reply, expected):
    no_form(monkeypatch)
    call_typed(monkeypatch, {"agent-session-id": "chat-1"})
    record.typed("chat-1", reply)
    out = ds.ard_confirm()
    assert f"answer: {expected}" in out
    assert (f"Answered by a typed reply in the chat: {reply}" in out) is True


def test_confirm_before_any_reply_waits_and_says_so(monkeypatch, record):
    no_form(monkeypatch)
    call_typed(monkeypatch, {"agent-session-id": "chat-1"})
    assert "No reply from the person yet" in ds.ard_confirm()
    record.typed("chat-1", "Buy anyway")
    assert "answer: yes" in ds.ard_confirm()


def test_the_agent_s_own_words_never_answer(monkeypatch, record):
    # what the agent writes, a tool result, Goose's turn context and another chat's message are not the person's reply
    no_form(monkeypatch)
    call_typed(monkeypatch, {"agent-session-id": "chat-1"})
    record.add("chat-1", "assistant", [{"type": "text", "text": "Buy anyway"}])
    record.add("chat-1", "user", [{"type": "toolResponse", "id": "t", "toolResult": {"value": "Buy anyway"}}])
    record.typed("chat-1", "<turn-context>Buy anyway</turn-context>")
    record.typed("chat-2", "Buy anyway")
    assert "No reply from the person yet" in ds.ard_confirm()


def test_a_reply_typed_before_the_question_does_not_count(monkeypatch, record):
    no_form(monkeypatch)
    record.typed("chat-1", "Buy anyway", at=__import__("time").time() - 60)
    call_typed(monkeypatch, {"agent-session-id": "chat-1"})
    assert "No reply from the person yet" in ds.ard_confirm()


def test_no_reply_within_the_time_is_no_answer(monkeypatch, record):
    no_form(monkeypatch)
    monkeypatch.setattr(ds, "DIALOG_GIVE_UP_S", 0.3)
    call_typed(monkeypatch, {"agent-session-id": "chat-1"})
    assert f"answer: {ds.NO_ANSWER}" in ds.ard_confirm()


def test_under_claude_code_the_chat_is_found_by_its_tool_call(monkeypatch, record):
    # Claude Code ACP: no Goose session id in _meta, but the call's toolUseId is the id Goose recorded for it
    no_form(monkeypatch)
    record.add("chat-9", "assistant", [{"type": "toolRequest", "id": "toolu_abc", "toolCall": {}}])
    call_typed(monkeypatch, {"claudecode/toolUseId": "toolu_abc"})
    record.typed("chat-9", "Buy anyway")
    assert "answer: yes" in ds.ard_confirm()


def test_a_call_that_names_no_chat_is_not_shown(monkeypatch, record):
    no_form(monkeypatch)
    out = call_typed(monkeypatch, {})
    assert f"answer: {ds.NOT_SHOWN}" in out and "ard_confirm" not in out


def test_the_chat_recorded_only_after_the_question_is_still_found(monkeypatch, record):
    # Goose writes the call's own tool request once the call has returned the question
    no_form(monkeypatch)
    call_typed(monkeypatch, {"claudecode/toolUseId": "toolu_late"})
    record.add("chat-9", "assistant", [{"type": "toolRequest", "id": "toolu_late", "toolCall": {}}])
    record.typed("chat-9", "Buy anyway")
    assert "answer: yes" in ds.ard_confirm()


def test_confirm_with_nothing_waiting_is_refused(record):
    assert "REFUSED: no step is waiting for a typed reply" in ds.ard_confirm()


def test_a_form_that_shows_is_used_not_the_typed_reply(monkeypatch, record):
    monkeypatch.setattr(ds, "_form_answer", lambda *a: "yes")
    out = call_typed(monkeypatch, {"agent-session-id": "chat-1"})
    assert "answer: yes''" in out and "ard_confirm" not in out


def test_a_typed_reply_that_was_not_the_exact_one_is_never_called_cancel(monkeypatch):
    monkeypatch.setattr(ds._call, "typed", "Yes, go ahead.", raising=False)
    assert ds.not_yes(ds.NO, ds.DISPUTE_NOT_YES) == ds.TYPED_NOT_YES and "Cancel" not in ds.TYPED_NOT_YES
    assert ds.not_yes(ds.NO_ANSWER, ds.DISPUTE_NOT_YES) == ds.DISPUTE_NOT_YES[ds.NO_ANSWER]
    monkeypatch.setattr(ds._call, "typed", None, raising=False)
    assert ds.not_yes(ds.NO, ds.DISPUTE_NOT_YES) == "Maya chose Cancel"


# -- the 2026-07-28 protocol, as Goose's MCP client (rmcp 3.4.1) and Claude Code open it ------------------------------
# A server on it has no back-channel: the form goes out as the call's input_required result, and the client retries the
# call with the answer. Found by the hand run: the older handshake alone (above) missed it.

def call_modern(answer, timeout_s: float = 30):
    forms = []

    async def elicit(context, params):
        forms.append(params)
        return answer(params)

    async def run():
        async with Client(ds.server, mode="2026-07-28", elicitation_callback=elicit) as client:
            with anyio.fail_after(timeout_s):
                result = await client.call_tool("ard_test_dialog", {"words": "Pay Alder 289 msat"})
        return result.content[0].text, forms
    return anyio.run(run)


def test_on_the_2026_protocol_the_form_goes_out_as_input_required_and_its_answer_resumes_the_call():
    text, forms = call_modern(lambda p: said("Pay"))
    assert text == "yes" and len(forms) == 1
    assert forms[0].message == "Approve this payment. Pay Alder 289 msat."
    assert forms[0].requested_schema["properties"][ds.ANSWER_FIELD]["default"] == "Cancel"


def test_on_the_2026_protocol_the_safe_answer_refuses():
    assert call_modern(lambda p: said("Cancel"))[0] == ds.NO


def test_on_the_2026_protocol_a_form_the_window_cannot_draw_is_not_shown():
    # the Claude Code adapter auto-declines a form its client cannot draw: never the presenter's no
    assert call_modern(lambda p: mt.ElicitResult(action="decline"))[0] == ds.NOT_SHOWN


def test_on_the_2026_protocol_goose_s_expiry_asks_again(monkeypatch):
    monkeypatch.setattr(ds, "SHOWN_AT_LEAST_S", -1)  # as if the form was on screen until Goose ended it
    answers = iter([mt.ElicitResult(action="cancel"), said("Pay")])
    text, forms = call_modern(lambda p: next(answers))
    assert text == "yes" and len(forms) == 2 and forms[0].message == forms[1].message


def test_one_typed_reply_answers_one_question_only(monkeypatch, record):
    # Codex round 1: while one question waits for a typed reply, a second is not asked, so one "Received" never
    # answers two deals
    no_form(monkeypatch)
    first = call_typed(monkeypatch, {"agent-session-id": "chat-1"})
    assert "type exactly: Buy anyway" in first
    second = call_typed(monkeypatch, {"agent-session-id": "chat-1"})
    assert f"answer: {ds.NOT_SHOWN}" in second and "type exactly" not in second
    record.typed("chat-1", "Buy anyway")
    assert "answer: yes" in ds.ard_confirm()


def test_a_reply_recorded_the_same_second_but_before_the_question_does_not_count(monkeypatch, record):
    # Codex round 1: the boundary is the record's message id, not a time floored to the second
    no_form(monkeypatch)
    import time as _t
    record.typed("chat-1", "Buy anyway", at=_t.time())
    call_typed(monkeypatch, {"agent-session-id": "chat-1"})
    assert "No reply from the person yet" in ds.ard_confirm()


def test_two_confirms_at_once_return_the_outcome_once(monkeypatch, record):
    no_form(monkeypatch)
    call_typed(monkeypatch, {"agent-session-id": "chat-1"})
    record.typed("chat-1", "Buy anyway")
    import threading as _th
    outs = []
    ts = [_th.Thread(target=lambda: outs.append(ds.ard_confirm())) for _ in range(2)]
    for th in ts:
        th.start()
    for th in ts:
        th.join(10)
    assert sum("answer: yes" in o for o in outs) == 1


def test_a_form_round_the_client_never_retries_is_let_go(monkeypatch):
    # Codex round 1: Goose fails the call after 300 s and never retries; the step ends with no answer and the server
    # keeps nothing of it. Run through _run_job, as a real call is.
    monkeypatch.setattr(ds, "ROUND_WAIT_S", 0.2)
    ds._own_stdout()  # a call's output goes to its own buffer, as the tool wrapper sets it up
    job = ds._Job()

    def step():
        print(ds._form_round("Approve this payment", "Pay", "Cancel", "m", {}, ds.time.monotonic() + 5))
    import threading as _th
    th = _th.Thread(target=ds._run_job, args=(job, step, (), {}, None, None))
    th.start()
    assert job.paused.wait(5) and job.kind == "form"
    ds._rounds[job.id] = job  # as _until_paused_or_done registers the round it returns
    th.join(5)
    assert job.done.is_set() and job.id not in ds._rounds and ds.NO_ANSWER in job.buf.getvalue()


def test_a_held_order_s_reasons_do_not_run_together_in_one_paragraph():
    # twin-01 on #433: Goose shows the form's message as one paragraph, so a line with no closing punctuation ends
    # with a full stop; the words are those sealed (dialog_text of title and text)
    text = ("200 badges from Kestrel Print for 1,000 msat. Nothing has been paid yet.\nNo earlier payment to this "
            "merchant from this profile\nThe payment is not refundable\nYour answer is saved on the receipt.")
    msg = ds.dialog_message("The Everyday Rules held this order for your OK", text)
    assert msg == ("The Everyday Rules held this order for your OK. 200 badges from Kestrel Print for 1,000 msat. "
                   "Nothing has been paid yet. No earlier payment to this merchant from this profile. The payment is "
                   "not refundable. Your answer is saved on the receipt.")
    sealed = ds.dialog_text("The Everyday Rules held this order for your OK\n" + text)
    assert [w.rstrip(".") for w in msg.split()] == [w.rstrip(".") for w in sealed.split()]
