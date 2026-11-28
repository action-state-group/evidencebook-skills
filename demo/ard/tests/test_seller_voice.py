# SPDX-License-Identifier: Apache-2.0
"""The seller's owner types in a seller's window, so its agent and its tools speak to them as "you" (Sherlock2's ruling
on evidencebook-skills#456, ops 32b9aa6d): no line a seller's agent reads or shows says "the seller", "this seller",
"the audience" or "the presenter", and a deal made in this run is never "the only real deal". Checked on what reaches
the window: the seller recipes' instructions (skill included), the seller tools' descriptions, the lines the selling
process says in its activity, and the tools' returned text. No binary is run."""
from __future__ import annotations

import ast
import importlib.util
import re
import threading
from pathlib import Path

import pytest

import desktop_server as ds
import flow
import pages
import receipt
import screens

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]
SELLER_ROLES = ("alder", "kestrel")

#: The words the ruling removes from a seller's window.
BANNED = re.compile(r"\b(the|this) seller\b|\bthe audience\b|\bthe presenter\b|\bpresenter's\b|\breal deal\b", re.I)


def clean(text: str) -> list[str]:
    """The banned phrases ``text`` holds, with their context, for an assertion message."""
    return [text[max(0, m.start() - 40):m.end() + 40] for m in BANNED.finditer(text)]


def test_the_banned_words_are_caught():
    for bad in ("The seller delivered only 150", "for the audience", "on the presenter's screen",
                "this seller's books", "the only real deal in this run"):
        assert clean(bad), bad
    assert not clean("your delivery record says so; the buyer says it paid; a seller's card")


@pytest.fixture
def ow(monkeypatch):
    monkeypatch.setenv("CAPSULE_ENGINE", "/bin/true")
    monkeypatch.setenv("ARD_EVIDENCEBOOK", "/nonexistent/evidencebook")
    monkeypatch.setenv("CAPSULECTL_DEAL", "/opt/capsulectl-deal")
    spec = importlib.util.spec_from_file_location("open_windows", HERE / "goose" / "open-windows.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("role", SELLER_ROLES)
@pytest.mark.parametrize("rail", ("fake", "lightning"))
def test_a_seller_windows_instructions_speak_to_its_owner(ow, role, rail):
    text = ow.instructions(role, rail)
    assert "sell-with-evidence" in text and not clean(text), clean(text)
    assert "owner: say I for yourself and you for them" in text


def test_the_seller_skill_files_say_none_of_the_words():
    for name in ("SKILL.md", "AGENTS.md"):
        text = (ROOT / "skills" / "sell-with-evidence" / name).read_text()
        assert not clean(text), (name, clean(text))
    assert "the only deal made in this run (simulated payment, no money moved)" in " ".join(text.split())


def seller_tools() -> list[str]:
    """Every tool a seller's window registers: ``@_tool(...)`` naming alder or kestrel, read from the source."""
    tree = ast.parse((HERE / "desktop_server.py").read_text())
    out = []
    for fn in tree.body:
        if not isinstance(fn, ast.FunctionDef):
            continue
        for d in fn.decorator_list:
            if isinstance(d, ast.Call) and getattr(d.func, "id", "") == "_tool" and any(
                    isinstance(a, ast.Constant) and a.value in SELLER_ROLES for a in d.args):
                out.append(fn.name)
    return out


def test_every_seller_tools_description_says_none_of_the_words():
    tools = seller_tools()
    assert {"ard_seller_activity", "ard_show_card", "ard_show_receipt", "ard_open_receipt_page",
            "ard_open_card_page"} <= set(tools)
    for name in tools:
        doc = getattr(ds, name).__doc__ or ""
        assert not clean(doc), (name, clean(doc))


def _said_text(node: ast.AST) -> str:
    """The literal text of an argument: a string, or an f-string's literal parts."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value for v in node.values if isinstance(v, ast.Constant))
    if isinstance(node, ast.BinOp):
        return _said_text(node.left) + _said_text(node.right)
    if isinstance(node, ast.IfExp):
        return _said_text(node.body) + " " + _said_text(node.orelse)
    return ""


def test_every_line_the_selling_process_says_speaks_to_its_owner():
    # what reaches the seller's window from flow.SellerAgent: what it says (say, event), a failed step's name
    # (failed), and a delivery its own check held, said as the refusal's text; its own agent.log (party.log) is not
    # shown and is left as it is
    tree = ast.parse((HERE / "flow.py").read_text())
    agent = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "SellerAgent")
    said = []
    for call in ast.walk(agent):
        if not isinstance(call, ast.Call):
            continue
        f = call.func
        if (isinstance(f, ast.Attribute) and f.attr in ("say", "event", "failed")
                and getattr(f.value, "id", "") == "self") or (isinstance(f, ast.Attribute) and f.attr == "Refused"):
            said += [_said_text(a) for a in call.args]
    # the loop's step names, said through self.failed(what, ...), and a reopened window's lines rebuilt from its records
    # (_replay's (mark, line) pairs)
    for t in ast.walk(agent):
        if isinstance(t, ast.Tuple) and len(t.elts) == 2 and isinstance(t.elts[0], ast.Constant):
            said += [_said_text(t.elts[0]), _said_text(t.elts[1])]
    # the event lines it says through flow's helpers, which a reopened window rebuilds with too
    for fn in tree.body:
        if isinstance(fn, ast.FunctionDef) and fn.name in ("paid_line", "delivered_line", "dispute_line"):
            said += [_said_text(n.value) for n in ast.walk(fn) if isinstance(n, ast.Return)]
            said += [_said_text(n.value) for n in ast.walk(fn) if isinstance(n, ast.Assign)]
    text = "\n".join(s for s in said if s)
    assert "your delivery record says so" in text and "your History card" in text and "held by your own check" in text
    assert "your own wallet is not checked here" in text and "asks for your" in text
    assert not clean(text), clean(text)


def test_every_line_a_party_says_about_its_books_speaks_to_it():
    # the shared steps a seller's window shows in its activity (Maya's too, where "your" is also hers): answering the
    # adjudicator, entering a ruling, sending the book and its stamp, and a retried step's line
    said = []
    for file, names in (("adjudicator.py", ("answer_requests", "books_sent_line", "send_book", "send_proof_once_witnessed")),
                        ("flow.py", ("enter_rulings",)), ("screens.py", ("trying_again",)), ("party.py", ("wait_checkpoint",))):
        tree = ast.parse((HERE / file).read_text())
        for fn in ast.walk(tree):
            if not (isinstance(fn, ast.FunctionDef) and fn.name in names):
                continue
            for node in ast.walk(fn):
                if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "say":
                    said += [_said_text(a) for a in node.args]
                if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "what" for t in node.targets):
                    said.append(_said_text(node.value))
                if isinstance(node, ast.Return) and fn.name in ("trying_again", "books_sent_line"):
                    said.append(_said_text(node.value))
    text = "\n".join(s for s in said if s)
    assert "the adjudicator asked for your books" in text and "entered in your records" in text
    assert "the reason is in agent.log" in text and "your checkpoint did not go through" in text
    assert not clean(text) and "this party" not in text, text


@pytest.mark.parametrize("made,real", [(0, False), (1, False), (3, False), (1, True)])
def test_a_sellers_own_lines_say_none_of_the_words(made, real):
    lines = [screens.own_sample_note("kestrel", made, real), screens.seller_credit_note(1000),
             *pages.labels({"outcomes": {"of": 10 + made, "held": 10, "did_not_hold": 0, "undecided": made}}, True,
                           sample="kestrel", made=made, real=real)]
    for line in lines:
        assert not clean(line), clean(line)
    assert "your wallet" in screens.seller_credit_note(1000)


RULED_AGAINST_SELLER = {"as_of": "2026-11-26T05:49:28Z", "rows": [
    {"id": "paid_as_agreed", "status": "agreed", "value": "met", "owed": {"amount_minor": 1000}},
    {"id": "delivered", "status": "ruled", "ruling": {"value": "not_met", "against": "seller"}}]}


class _Party:
    name = "kestrel"

    def report(self, deal_id):
        return {"report": RULED_AGAINST_SELLER}

    def log(self, line):
        pass


@pytest.mark.parametrize("real", [False, True])
def test_a_sellers_receipt_says_you(monkeypatch, real):
    monkeypatch.setattr(receipt, "proof_lines", lambda p, deal_id, name="": [])
    monkeypatch.setattr(receipt, "_countersigned", lambda p, deal_id: None)
    monkeypatch.setattr(flow, "shipped_of", lambda p, deal_id: "150 of 200 badges")
    out = receipt.receipt_text(_Party(), "Kestrel Print", "deal-fedcba9876543210", real=real, seller=True)
    assert out.startswith("Kestrel Print: your receipt for deal fedcba98, from your own records"), out
    assert "(not met, against you)" in out
    assert ("What your wallet was credited" in out) == real
    assert not clean(out), clean(out)
    # the buyer's receipt still names the side ruled against
    maya = receipt.receipt_text(_Party(), "Maya", "deal-fedcba9876543210", real=real, seller=False,
                                counterparty="Kestrel Print")
    assert "(not met, against the seller)" in maya


class _Agent(flow.SellerAgent):
    def __init__(self, tmp_path):  # no binary: its log and its party only
        self.log, self._lock, self.label, self.name, self.home = [], threading.Lock(), "Kestrel Print", "kestrel", tmp_path
        self.party = type("P", (), {"log": lambda self, line: None, "notes": lambda self, kind: [],
                                    "card_bundle": lambda self, shared: "card.json", "dir": tmp_path / "kestrel"})()


@pytest.mark.parametrize("opened", [True, False])
def test_the_seller_tools_return_lines_say_none_of_the_words(tmp_path, monkeypatch, opened):
    agent = _Agent(tmp_path)
    agent.say("delivered to the buyer: 150 of 200 badges (your delivery record says so)")
    (tmp_path / "kestrel").mkdir()
    agent._mark("deal-fedcba9876543210", "agree")  # the buyer's agreement it kept: one deal made in this run
    monkeypatch.setattr(ds, "ROLE", "kestrel")
    monkeypatch.setattr(ds, "seller", lambda: agent)
    monkeypatch.setattr(ds, "_own", lambda: (agent.party, "Kestrel Print"))
    monkeypatch.setattr(ds, "_own_deal", lambda: (agent.party, "Kestrel Print", "deal-fedcba9876543210"))
    # Codex's PR review: a card that has not counted the deal yet (it waits for a stamp) still leaves it made in this run
    monkeypatch.setattr(flow, "read_card", lambda b: ({"outcomes": {"of": 10, "held": 10, "did_not_hold": 0,
                                                                    "undecided": 0}}, None, None))
    monkeypatch.setattr(pages, "card_page", lambda *a, **k: tmp_path / "history.html")
    monkeypatch.setattr(receipt, "receipt_page", lambda *a, **k: tmp_path / "receipt.html")
    monkeypatch.setattr(pages, "open_page", lambda path: opened)
    outs = {"activity": ds.ard_seller_activity(), "card page": ds.ard_open_card_page(),
            "receipt page": ds.ard_open_receipt_page()}
    assert outs["activity"].startswith("Kestrel Print: your own profile, keys and records")
    assert "the only deal made in this run (simulated payment, no money moved)" in outs["activity"]
    assert outs["card page"].startswith("Kestrel Print: your History card page")
    assert outs["receipt page"].startswith("Kestrel Print: your receipt page")
    for what, out in outs.items():
        assert not clean(out), (what, clean(out))
