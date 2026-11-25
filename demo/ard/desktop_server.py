#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The ARD demo as a Goose extension (an MCP server over stdio), one per party's window, so each party's Goose in
Goose Desktop runs its own steps. Every tool returns the text a person reads (:mod:`screens`); a refusal is a line
starting ``REFUSED:`` and changes nothing.

``ARD_ROLE`` picks whose window this is:

``maya``   the buyer:
    ard_find_sellers  ->  her ask and ARD discovery
    ard_show_history  ->  each seller's History card, fetched and checked
    ard_assess        ->  the assessment of each seller under her pack
    ard_pick          ->  the pick (a seller outside its limit ends here: no deal opens, nothing is paid)
    ard_pay           ->  the deal and the payment; the one tool that moves money (the presenter approves in a dialog)
    ard_dispute       ->  her dispute of a deal's delivery, sent to the seller and to the deal's adjudicator
    ard_confirm_received -> her statement that she received what she paid for, only after her yes in a dialog
``alder`` / ``kestrel``   a seller, its own profile and keys; its agent answers on its own:
    ard_seller_activity  ->  what its agent did: the deal, the delivery, a dispute, a ruling, its card now
``adjudicator``   the demo's adjudicator (its own capsulectl-deal profile, run by the demo operator):
    ard_case          ->  the cases sent to it: it asks each side for its books and shows what they show
    ard_rule          ->  the presenter's ruling on a case (a dialog), recorded and time-stamped
    ard_case_activity ->  whether each party entered the ruling in its own book
Every party's window also has ard_show_card, ard_open_card_page, ard_show_receipt and ard_open_receipt_page: its own
History card and its own receipt (the adjudicator holds no deal of its own, so not those).

Environment (``demo.py --help`` lists it): ``CAPSULECTL_DEAL``, ``CAPSULE_ENGINE``, ``ARD_EVIDENCEBOOK``,
``ARD_HOME``, ``ARD_RAIL`` (``fake``, ``lightning`` or ``local``; default ``fake``). Seed the
home first with ``demo.py seed``. See RUNBOOK.md."""
from __future__ import annotations

import contextlib
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
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:  # mcp < 2
    from mcp.server.fastmcp import FastMCP

import adjudicator as adj  # noqa: E402
import ard  # noqa: E402
import buyer  # noqa: E402
import flow  # noqa: E402
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
    """The words a native dialog shows for ``text``: AppleScript's string quoting takes no backslash or double quote,
    so they are replaced. A record of the person's answer commits to these words, the ones the person saw."""
    return text.replace("\\", " ").replace('"', "'")


#: How a dialog ended other than yes (#239 finding 11: a dialog nobody answered is never called a decline).
NO, NO_ANSWER, NOT_SHOWN = "no", "no_answer", "not_shown"
#: What the person is told when the dialog did not end in yes (Sherlock2's words for no answer, #239 finding 11).
NOT_YES = {NO: "the presenter declined it",
           NO_ANSWER: "no answer in time",
           NOT_SHOWN: "the dialog could not be shown"}


#: How long a dialog waits for the presenter before it gives up (run finding F6a, 2026-11-25: 3 minutes was too short
#: when a person first has to find the dialog). The window's MCP tool timeout (open-windows.py TOOL_TIMEOUT_S) covers
#: it and the rest of the longest call, ard_pay.
DIALOG_GIVE_UP_S = 600


def dialog_answer(title: str, text: str, yes: str, no: str = "Cancel") -> str:
    """A native dialog on the presenter's screen that the agent neither reads nor answers through the chat, and how it
    ended: ``"yes"`` (the ``yes`` button), :data:`NO` (the other button), :data:`NO_ANSWER` (it gave up after :data:`DIALOG_GIVE_UP_S`,
    nobody clicked) or :data:`NOT_SHOWN` (no screen, or any error)."""
    script = (f'display dialog "{dialog_text(text)}" with title "{dialog_text(title)}" buttons {{"{no}", "{yes}"}} '
              f'default button "{no}" cancel button "{no}" with icon caution giving up after {DIALOG_GIVE_UP_S}')
    try:
        run = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                             timeout=DIALOG_GIVE_UP_S + 20)
    except subprocess.TimeoutExpired:  # past its own give-up: most likely on screen, unanswered
        return NO_ANSWER
    except (OSError, subprocess.SubprocessError):
        return NOT_SHOWN
    if run.returncode == 0 and "gave up:true" in run.stdout:
        return NO_ANSWER
    if run.returncode == 0 and f"button returned:{yes}" in run.stdout:
        return "yes"
    if "(-128)" in (getattr(run, "stderr", "") or "") or (run.returncode == 0 and "button returned:" in run.stdout):
        return NO  # the cancel button (osascript: "User canceled. (-128)")
    return NOT_SHOWN


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
        self.picked: set[str] = set()
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
                    ("answering the adjudicator's request for Maya's books",
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


def _tool(*roles: str, description: str | None = None):
    """Register a tool for these roles. A tool returns the text it printed; a refusal is a line starting
    ``REFUSED:`` and changes nothing."""
    def deco(fn):
        @functools.wraps(fn)
        def run(*args, **kwargs) -> str:
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    if _session is not None and _session.log:  # what Maya's agent did since her last request
                        print("Since your last request:")
                        _flush(_session)
                        print()
                    fn(*args, **kwargs)
            except (SystemExit, Exception) as exc:
                return (buf.getvalue() + f"\nREFUSED: {_refusal(exc)}").strip()
            return buf.getvalue().strip()
        run.__signature__ = inspect.signature(fn).replace(return_annotation=str)
        run.__annotations__ = {**fn.__annotations__, "return": str}
        del run.__wrapped__
        if ROLE in roles:
            return server.tool(description=description)(run)
        return run
    return deco


def _refusal(exc: BaseException) -> str:
    """A tool's refusal without raw output (evidencebook-skills#327). The demo's refusals and capsulectl's error words
    are written for a person and stay; a refusal that carries a verb's raw output (JSON, or a long dump) goes to this
    window's log and reads as one plain line."""
    text = str(exc)
    if isinstance(exc, pt.Refused) and ("{" in text or len(text) > 400):
        try:
            d = _home() / ROLE
            d.mkdir(parents=True, exist_ok=True)
            with open(d / "agent.log", "a") as fh:
                fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}  a tool refused: {exc!r}\n")
        except OSError:
            pass
        return "capsulectl refused this step (the reason is in this party's log, agent.log); nothing was changed"
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
def ard_find_sellers() -> None:
    """Step 1-2: Maya's ask and ARD discovery. Lists the sellers found, each with its price and whether its signed
    commitment verified. Call this first."""
    s = session()
    s.entries = ard.lookup(stage.REGISTRY_URL, stage.ORIGINS, stage.QUERY)
    print(f"searched a local stand-in registry, run by the operator: POST {stage.REGISTRY_URL} {{query: {stage.QUERY!r}}}")
    for e in s.entries:
        price = screens.msat(e["offer"]["price_msat"]) if "offer" in e else "?"
        print(f"found: {e['name']:18} {price:>10}   commitment {'verified' if 'commitment' in e else 'REFUSED: ' + e['problem']}")
        for line in e.get("checks", []):
            print(f"       {line}")
    if len(s.entries) < len(SELLERS):
        print("only " + ", ".join(e["name"] for e in s.entries) + " answered: the other seller's window is not running")


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


@_tool("maya")
def ard_assess() -> None:
    """Step 4: assess each seller under Maya's admission pack (its thresholds are placeholders), from the card she
    checked and her own records of deals with that seller. Call after ard_show_history."""
    s = session()
    if not s.evidence:
        raise RuntimeError("call ard_show_history first")
    s.pack = s.pack or packs.starting()
    p = s.pack
    print(f"pack {p.version} · digest {p.digest[:12]}… · {screens.PACK_NOTE}")
    print(f"({screens.ASSESSMENT_NOTE})")
    print(f"({screens.OPERATOR_NOTE})\n")
    for e in s.entries:
        ev = s.evidence.get(e["id"])
        if ev is None or ev.card is None:
            print(f"  {e['name']:18} not assessed: no checked History card")
            continue
        a = buyer.assess(s.maya, ev, e["commitment"]["key_id"], e["offer"]["price_msat"], p)
        s.assessed[e["id"]] = a
        ceiling = p.ceiling_msat(a.tier) if a.tier else None
        print(f"  {e['name']:18} {screens.decision_line(a, ev, ceiling)}")


@_tool("maya")
def ard_pick(seller: str) -> None:
    """Step 5: seal Maya's pick of ``seller`` ("alder" or "kestrel"), citing every assessment. A seller that is not GO
    ends here: no deal opens and nothing is paid. For a GO seller, ard_pay opens the deal and pays it next."""
    s = session()
    key = _seller_key(seller)
    if key not in s.assessed:
        raise RuntimeError("call ard_assess first")
    a = s.assessed[key]
    buyer.seal_pick(s.maya, s.keys[key], a, [m for k, m in s.assessed.items() if k != key])
    print(f"pick sealed before any payment: {SELLERS[key]['label']} at {screens.msat(a.price_msat)}, citing every assessment")
    if a.verdict != "GO":
        print(screens.limit_outcome(a))
        return
    s.picked.add(key)
    print(f"{SELLERS[key]['label']} is within its limit. Call ard_pay to open the deal and pay it.")


_RAIL_WORDS = ("over Lightning: this moves real money, to a wallet {shared} share", "on the simulated rail: no money moves")
_PAY = ("Step 6: pay the picked seller on the {rail}. A dialog appears on the presenter's screen first and this call "
        "blocks, for up to 10 minutes, until the presenter answers it (Pay or Cancel; Buy anyway or Don't buy when the "
        "Everyday Rules hold the order): do not retry or call it again while it waits. Only after that yes does it send "
        "the order to the seller (the agreement names the deal's adjudicator and "
        "Action State's witness) and pay it. Refused "
        "unless ard_pick sealed this seller. It then waits for the seller's delivery and says what the seller's delivery "
        "record says it shipped.")


@_tool("maya", description=_PAY.format(rail="real Lightning rail: THIS MOVES REAL MONEY" if _real() else "SIMULATED rail: no money moves"))
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
            raise RuntimeError(
                f"the presenter did not approve the last payment to {name}, so this call opens no dialog and pays nothing. "
                f'The question is: "Pay {name} {screens.msat(a.price_msat)} '
                + ("over Lightning, which moves real money" if _real() else "on the simulated rail, where no money moves")
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
                                  print, simulated=not _real(), said=dialog_text, rail_words=words)
        held = getattr(answer.get("q"), "held", None)
        if made is None:
            how = answer.get("how", NOT_SHOWN)
            if how == NO:
                s.declined[key] = getattr(answer.get("q"), "title", "")
            reasons = (" " + screens.rules_held(held.reasons)) if held is not None else ""
            raise RuntimeError(f"{NOT_YES[how]}, so the order was not placed: nothing was sent to the seller and nothing "
                               "was paid." + reasons + " Do not retry on your own; if Maya asks again, confirm with her first."
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
    """Ask Maya, in a dialog on the presenter's screen, whether she received what she paid for in her deal with
    ``seller``; only her yes seals her statement that she did and sends it to the seller. Call only when Maya says she
    received the delivery, never on your own after a payment or a delivery. You cannot see or answer the dialog. With
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
        raise RuntimeError(f"{RECEIVED_NOT_YES[how]}, so nothing was sent in Maya's name. Do not retry on your own; ask "
                           "Maya.")
    with s.pay_lock:
        buyer.close_received(s.home, s.maya, target)
    print(f"Maya's statement sent to {name}: she received what she paid for.")


@_tool("maya")
def ard_dispute(seller: str) -> None:
    """Dispute the delivery of Maya's latest deal with ``seller``: her statement that it was not met, and a dispute,
    sent to the seller and to the adjudicator the agreement names, which then asks each side for its books. It moves no
    money. Call only when Maya says the delivery was short or did not come."""
    s = session()
    key = _seller_key(seller)
    deal = s.latest(key)
    if deal is None:
        raise RuntimeError(f"Maya has no deal with {SELLERS[key]['label']} in this run")
    buyer.dispute(s.home, s.maya, deal, print)
    print(screens.DISPUTE_RAISED.format(seller=SELLERS[key]["label"]))


# -- the sellers --------------------------------------------------------------------------------------

@_tool("alder", "kestrel")
def ard_seller_activity() -> None:
    """What this seller's agent did on its own: its commitment, the deal asked of it, the payment, its delivery, a
    dispute and a ruling, and its own History card now."""
    sel = seller()
    print(f"{sel.label}: its own profile, keys and records (this window only)")
    for line in list(sel.log):
        print("  " + line)
    card, _, _ = flow.read_card(sel.party.card_bundle(shared=True))
    print(f"now: {screens.card_line(card)}")
    print("  " + screens.sample_note(sel.name))


# -- the adjudicator ----------------------------------------------------------------------------------

def _adjudicator() -> adj.Adjudicator:
    global _seller_lock
    if _seller_lock is None:
        _seller_lock = _lock(ADJUDICATOR)
        stage.ensure_stage(_home())
        threading.Thread(target=_ask_on_arrival, daemon=True).start()
    return adj.Adjudicator(_home())


#: How often the adjudicator's window looks for a dispute that has arrived (_ask_on_arrival).
ASK_EVERY_S = 3


def _ask_on_arrival() -> None:
    """The adjudicator asks each side for its books as soon as a dispute arrives, not when the case is first opened
    (evidencebook-skills#326), so the first ``ard_case`` already finds the answers coming in. Asking is idempotent
    (``Adjudicator.ask`` skips a case it already asked about); a failure is written to the adjudicator's log and tried
    again on the next round."""
    a = adj.Adjudicator(_home())
    while True:
        try:
            a.ask()
        except Exception as exc:  # noqa: BLE001: a background step never ends the window's server
            a.party.log(f"asking for books: {exc!r}")
        time.sleep(ASK_EVERY_S)


@_tool("adjudicator")
def ard_case() -> None:
    """Show the disputes sent to this adjudicator: it asks each side for its books (each side's agent answers on its own,
    with its own book and the copy it holds of the other side's), then shows who answered and what the books show (the
    seller's own signed delivery record, each side's statement on the row) and any ruling recorded. It decides nothing."""
    cases = _adjudicator().gather(30)
    if not cases:
        print("no case yet: a party has sent no dispute to this adjudicator")
        return
    print(screens.ADJUDICATOR_INDEPENDENCE)
    for raw in cases:
        print()
        print("\n".join(flow.case_lines(flow.case_view(raw, flow.case_names(raw)), flow.case_names(raw))))


@_tool("adjudicator")
def ard_rule(seller: str) -> None:
    """Rule on the open case about ``seller``'s delivery: a dialog on the presenter's screen asks for the decision
    (against the seller, the row not met); only the presenter's click records it, with capsulectl's ``deal ruling`` over
    the books the sides sent. The ruling is then time-stamped by Action State's witness and sent to both parties, each of
    which enters it in its own records."""
    key = _seller_key(seller)
    a = _adjudicator()
    seller_name = SELLERS[key]["label"]
    for raw in a.gather(30):
        if raw["parties"]["seller"] != key:
            continue
        if not raw["answers"]:
            raise RuntimeError("neither side has answered the adjudicator's request for its books yet: no ruling from "
                               "this case yet (try again in a minute)")
        c = flow.case_view(raw, flow.case_names(raw))
        if not raw["ruling"] and not gate_off():
            how = dialog_answer("Rule on this case", screens.rule_question(c.deal_id, c.row, seller_name), "Rule")
            if how != "yes":
                raise RuntimeError(f"{NOT_YES[how]}, so no ruling was recorded")
        try:
            r = raw["ruling"] or a.rule(raw, c.row, "not_met", "seller")
        except adj.AdjudicatorError as exc:
            raise RuntimeError(f"capsulectl refused the ruling: {exc}") from None
        print(f"Ruling recorded on deal {c.deal_id[5:13]}, row {c.row}: not met, against {seller_name}.")
        if a.stamp({**raw, "ruling": r}):
            print(f"Its stamp was taken by {pt.WITNESS_NAME}; each party's window shows the time it was stamped.")
        elif pt.witnessed():
            print(f"Not yet time-stamped: {pt.WITNESS_NAME} did not answer within 12 seconds. Both parties have the "
                  f"ruling without a stamp. This window keeps asking for {adj.LATER_S // 60} minutes and, once stamped, "
                  "sends the ruling to both parties again with its stamp. Keep this window open until then. If none "
                  "comes by then, run this again.")
        print("Sent to both parties; each enters it in its own records.")
        return
    raise RuntimeError(f"no case about {seller_name}")


@_tool("adjudicator")
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
    """Show THIS window's own History card (its standard_history derivation) as of a checkpoint taken now: deals counted, held,
    did not hold, and disputes others raised about it."""
    p, name = _own()
    p.stamp()
    card, as_of, _ = flow.read_card(p.card_bundle(shared=True))
    print(f"{name}: its own History card, as of its checkpoint at {screens.local_time(as_of['anchor_time'], date=True)}")
    print("  " + screens.card_line(card))
    if ROLE in SELLERS:
        print("  " + screens.sample_note(ROLE))


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
    print(receipt.receipt_text(p, name, deal_id, real=_real(), seller=ROLE in SELLERS))


@_tool("maya", "alder", "kestrel")
def ard_open_receipt_page() -> None:
    """Open THIS window's own receipt for its latest deal as a page in the browser, for the audience: capsulectl's own
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
    print(f"{name}: its receipt page " + ("opened in the browser on the presenter's screen; nothing else is needed "
                                          "(do not copy or link the file)" if opened else "written (not opened)") + f": {path}")


@_tool("maya", "alder", "kestrel")
def ard_open_card_page() -> None:
    """Open THIS window's own History card as a page in the browser, for the audience."""
    import pages

    p, name = _own()
    path = pages.card_page(p, name, rail=_rail_name(), seller=ROLE in SELLERS)
    opened = pages.open_page(path)
    print(f"{name}: its History card page " + ("opened in the browser on the presenter's screen; nothing else is needed "
                                               "(do not copy or link the file)" if opened else "written (not opened)")
          + f": {path}")


def main() -> None:
    if ROLE in SELLERS:
        seller()  # a seller's agent runs from the moment its window opens, so the buyer finds it
    elif ROLE == ADJUDICATOR:
        _adjudicator()
    server.run()


if __name__ == "__main__":
    main()
