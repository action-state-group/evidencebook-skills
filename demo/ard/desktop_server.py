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


def ask_person(title: str, text: str, yes: str, no: str = "Cancel") -> bool:
    """A native dialog on the presenter's screen that the agent neither reads nor answers through the chat. True only
    for ``yes``; ``no``, a timeout (3 minutes), no screen or any error is a no."""
    script = (f'display dialog "{dialog_text(text)}" with title "{dialog_text(title)}" buttons {{"{no}", "{yes}"}} '
              f'default button "{no}" cancel button "{no}" with icon caution giving up after 180')
    try:
        run = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=200)
    except (OSError, subprocess.SubprocessError):
        return False
    return run.returncode == 0 and f"button returned:{yes}" in run.stdout and "gave up:true" not in run.stdout


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
        self.declined: set[str] = set()
        self.pay_lock = threading.Lock()
        self.log: list[str] = []
        threading.Thread(target=self._rulings, daemon=True).start()

    def say(self, line: str) -> None:
        if not self.log or self.log[-1] != line:  # a retry that fails the same way every round says so once
            self.log.append(line)

    def _rulings(self) -> None:
        """Maya's agent enters a ruling on her deals as soon as the adjudicator publishes it, as a seller's does."""
        while True:
            try:
                adj.answer_requests(self.home, self.maya, BUYER, "buyer", self.say)
                flow.enter_rulings(self.home, self.maya, "buyer", buyer.seller_of(self.maya), self.say)
                buyer.seller_statements(self.home, self.maya)
                with self.pay_lock:  # not while ard_pay itself waits for the same delivery
                    buyer.pick_up_deliveries(self.home, self.maya, self.say)
            except Exception as exc:  # shown in the next tool's output
                self.say(f"could not read the adjudicator yet: {exc}")
            time.sleep(3)

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
                return (buf.getvalue() + f"\nREFUSED: {exc}").strip()
            return buf.getvalue().strip()
        run.__signature__ = inspect.signature(fn).replace(return_annotation=str)
        run.__annotations__ = {**fn.__annotations__, "return": str}
        del run.__wrapped__
        if ROLE in roles:
            return server.tool(description=description)(run)
        return run
    return deco


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
            print(f"  {screens.signed_line(e['name'], ev.read is not None and ev.read.witness_status == 'pass')}")


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
    print(f"({screens.CLAIMS_NOTE}; {screens.ASSESSMENT_NOTE})")
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
        "blocks, for up to 3 minutes, until the presenter clicks Pay or Cancel: do not retry or call it again while it "
        "waits. Only after Pay does it open the deal with the seller (the agreement names the deal's adjudicator and "
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
            s.declined.discard(key)
            raise RuntimeError(
                f"the presenter did not approve the last payment to {name}, so this call opens no dialog and pays nothing. "
                f'The question is: "Pay {name} {screens.msat(a.price_msat)} '
                + ("over Lightning, which moves real money?" if _real() else "on the simulated rail, where no money moves?")
                + '" If Maya said yes to it after the dialog was declined, call ard_pay again now; otherwise ask her, end '
                "your turn, and call ard_pay again only after she says yes.")
        made = buyer.open_and_pay(
            s.home, s.maya, key, s.keys[key], a, s.adjudicator.named(), s.rail, summary,
            lambda text: gate_off() or ask_person("Approve this payment", text, "Pay"), print, simulated=not _real())
        if made is None:
            s.declined.add(key)
            raise RuntimeError("the presenter did not approve this payment (the dialog was cancelled, timed out or could "
                               "not be shown): nothing was sent to the seller and nothing was paid. Do not retry on your "
                               "own; if Maya asks again, confirm with her first.")
        deal, payment = made
        s.deals.append(deal)
        who = ("the simulated rail paid it (no money moved)" if not _real() else "the buyer's wallet paid it")
        print(f"invoice {screens.msat(payment.invoice_msat)}; {who}: {payment.status}{screens.fee_note(payment.fee_msat, _real())}")
    print(f"waiting for {name}'s delivery")
    try:
        with s.pay_lock:
            observed = buyer.await_delivery(s.home, s.maya, deal)
    except pt.Refused as exc:
        print(f"{exc}.")
        return
    shipped = buyer.shipped(observed)
    print(screens.delivered_line(name, shipped))
    if shipped.startswith("200 of 200"):
        buyer.close_received(s.home, s.maya, deal)
        print("Maya's statement sent: she received what she paid for.")
    else:
        print(f"Maya ordered 200 badges. If fewer arrived, she can dispute the delivery (ard_dispute {key}).")


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


# -- the adjudicator ----------------------------------------------------------------------------------

def _adjudicator() -> adj.Adjudicator:
    global _seller_lock
    if _seller_lock is None:
        _seller_lock = _lock(ADJUDICATOR)
        stage.ensure_stage(_home())
    return adj.Adjudicator(_home())


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
        if not raw["ruling"] and not (gate_off() or ask_person("Rule on this case", screens.rule_question(
                c.deal_id, c.row, seller_name), "Rule")):
            raise RuntimeError("the presenter did not record a ruling (the dialog was cancelled or timed out): nothing was ruled")
        try:
            r = raw["ruling"] or a.rule(raw, c.row, "not_met", "seller")
        except adj.AdjudicatorError as exc:
            raise RuntimeError(f"capsulectl refused the ruling: {exc}") from None
        print(f"Ruling recorded on deal {c.deal_id[5:13]}, row {c.row}: not met, against {seller_name}.")
        if a.stamp({**raw, "ruling": r}):
            print(f"Its stamp was taken by {pt.WITNESS_NAME}; each party's window shows the time it was stamped.")
        elif pt.witnessed():
            print(f"Not yet time-stamped: {pt.WITNESS_NAME} took no stamp within 90 seconds (no network?). Run this "
                  "again to send it with its stamp.")
        print("Sent to both parties; each enters it in its own records.")
        return
    raise RuntimeError(f"no case about {seller_name}")


@_tool("adjudicator")
def ard_case_activity() -> None:
    """Whether each party entered this adjudicator's ruling in its own records, read from the books they sent back."""
    a = _adjudicator()
    ruled = [c for c in a.cases() if c["ruling"]]
    if not ruled:
        print("no ruling yet")
        return
    for c in ruled:
        names = flow.case_names(c)
        rows = a.entries(c)
        if not rows:
            print(f"deal {c['deal_id'][5:13]}: no party has sent its book back yet")
        for x in rows:
            print(f"deal {c['deal_id'][5:13]}  {names.get(x['party'], x['party'])}: {x['words']}")


# -- every party: its own card and receipt ---------------------------------------------------------------

def _own() -> tuple[pt.Party, str]:
    if ROLE in SELLERS:
        sel = seller()
        return sel.party, sel.label
    return session().maya, "Maya"


@_tool("maya", "alder", "kestrel")
def ard_show_card() -> None:
    """Show THIS window's own History card (its standard_history derivation) as of its newest checkpoint: deals counted, held, did
    not hold, and disputes others raised about it. A deal or a ruling counts after the party's next checkpoint."""
    p, name = _own()
    p.tick()
    card, as_of, _ = flow.read_card(p.card_bundle(shared=True))
    print(f"{name}: its own History card, as of its checkpoint at {as_of['anchor_time']}")
    print("  " + screens.card_line(card))


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
    """Open THIS window's own receipt for its latest deal as a page in the browser, for the audience: capsule-viewer's
    view of its own copy of the deal, checked by capsulectl verify --bundle, with nothing added."""
    import pages
    import receipt

    p, name, deal_id = _own_deal()
    if deal_id is None:
        print(f"{name}: no deal yet, so no receipt page")
        return
    try:
        path = receipt.receipt_page(p, name, deal_id, rail=_rail_name(), seller=ROLE in SELLERS)
    except receipt.ReceiptError as exc:
        print(f"{name}: no receipt page yet: {exc}")
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
