#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The ARD two-seller demo as a Goose extension (an MCP server over stdio), so a party's Goose in
Goose Desktop runs its steps itself. It drives the same :class:`demo.Run` the script demo runs; each
tool returns the text that run prints, so the screen says what the script demo says (:mod:`screens`).

``ARD_ROLE`` picks who this server is:

``maya``     the buyer's window (needs the sellers' windows running):
    ard_find_sellers   ->  Maya's ask and ARD discovery
    ard_show_history   ->  each seller's signed answers, checked, and the History cards
    ard_assess         ->  the assessment (the on-stage edit is its ``max_adverse_permille``)
    ard_pick           ->  the pick (a seller outside its limit ends here: no deal opens, nothing is paid)
    ard_pay            ->  the deal and the payment; the one tool that moves money (the presenter approves in a dialog)
``alder`` / ``kestrel``     a seller's window, its own node and keys:
    ard_seller_activity  ->  what its agent did: requests answered, the deal, the sale, its card
    ard_show_card / ard_show_receipt  ->  its own History card and its own receipt (every window has these two)
    ard_open_card_page  ->  its own History card as a page in the browser (every window; pages.py)
    ard_open_receipt_page  ->  its own receipt for its closed deal as a page in the browser (every window; receipt.py)
``all`` (default)     the whole story in one process, Maya's tools (one window).

Environment: ``CAPSULE_ENGINE``, ``ARD_EVIDENCEBOOK`` and ``ARD_HOME`` as for ``demo.py``; ``ARD_RAIL``
(``fake`` or ``lightning``, default ``fake``) and ``ARD_KESTREL_CARD`` (``sentinel`` or ``sample``, the
same in every window); ``CAPSULECTL_DEAL``, the capsulectl-deal binary the receipt page is verified with. Seed the home first with ``demo.py seed``. See README.md ("In Goose Desktop")."""
from __future__ import annotations

import contextlib
import fcntl
import functools
import inspect
import io
import os
import sys
import threading
import time
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

try:  # mcp >= 2 renamed FastMCP to MCPServer
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:  # mcp < 2
    from mcp.server.fastmcp import FastMCP

import demo  # noqa: E402  (puts ../goose on the path and sets CAPSULE_WITNESS)
import buyer  # noqa: E402
import pack as packs  # noqa: E402
import parties  # noqa: E402
import pay  # noqa: E402
import rules  # noqa: E402
import screens  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from world import SELLERS  # noqa: E402

ROLE = os.environ.get("ARD_ROLE", "all")
if ROLE not in ("all", "maya", *SELLERS):
    raise SystemExit(f"ARD_ROLE must be all, maya, alder or kestrel, not {ROLE!r}")

server = FastMCP("ard_demo" if ROLE == "all" else f"ard_{ROLE}")
DEFAULT_PERMILLE = demo.DEFAULT_PERMILLE


def _home() -> Path:
    return Path(os.environ.get("ARD_HOME", demo.DEFAULT_HOME)).expanduser()


def _lock(role: str) -> object:
    """One server per party and demo home: a second Goose chat's server would wait on the first's shelf locks."""
    home = _home()
    home.mkdir(parents=True, exist_ok=True)
    handle = open(home / f".desktop-{role}.lock", "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise RuntimeError(f"another Goose chat already runs the {role} side on this home: "
                           "use that chat, or close it first") from None
    return handle


class Session:
    """The buyer's run (``all`` and ``maya``)."""

    def __init__(self) -> None:
        packs.engine(), packs.skills_checkout()
        self._lock = _lock(ROLE)
        self.start: packs.Pack | None = None
        self.assessed: dict | None = None
        self.pack: packs.Pack | None = None
        self.picked: dict[str, str] = {}
        self.paid: set[str] = set()       # payments the rail reported succeeded
        self.deal_ids: list[str] = []     # this run's deals, oldest first (the receipt shows the latest)
        self.attempted: set[str] = set()  # payments started: a failure mid-way is not a retry
        self.declined: set[str] = set()   # the presenter's last dialog for this seller was not approved
        self.pay_lock = threading.Lock()  # one check, approval and payment at a time
        rail: pay.Rail = pay.from_env(os.environ.get("ARD_RAIL", "fake"))
        kestrel_card = os.environ.get("ARD_KESTREL_CARD", "sentinel")
        if ROLE == "maya":
            self.world = parties.ProcessWorld(_home(), ("maya",)).open()
            self.world.sample_card = {"kestrel": True} if kestrel_card == "sample" else {}
            parties.ensure_stage(_home())
            self.bworld = parties.BuyerWorld(self.world, {})
            self.server = parties.NoServer(parties.REGISTRY_URL)
            self.server.origins, self.server.query = parties.ORIGINS, parties.QUERY
            self.run = demo.Run(self.bworld, self.server, rail, True, False)
            return
        args = types.SimpleNamespace(home=str(_home()), port=0, kestrel_card=kestrel_card)
        self.world, self.server = demo.prepare(args)
        try:
            if any(sum(1 for b in self.world.nodes[n].shelf.books() if b.startswith("deal/") and b.count("/") == 1) < demo.DEALS_EACH
                   for n in SELLERS):
                raise RuntimeError("no sample history yet: run `python demo.py seed` first")
            self.run = demo.Run(self.world, self.server, rail, True, False)
        except BaseException:
            self.server.close()
            self.world.close()
            raise


def dialog_text(text: str) -> str:
    """The words a native dialog shows for ``text``: AppleScript's string quoting takes no backslash or double quote,
    so they are replaced. The approval record commits to these words, the ones the person saw."""
    return text.replace("\\", " ").replace('"', "'")


def approve_payment(summary: str) -> bool:
    """The presenter's approval, out of band: a native dialog on the presenter's screen that the agent neither reads
    nor answers through the chat (a code returned in the tool's output would reach the agent, which could reuse it in
    the same turn). True only for the Pay button; Cancel, a timeout, no screen or any error is a refusal.
    ``ARD_APPROVAL=none`` turns the gate off (tests only; the tool says so in its output)."""
    import subprocess

    text = dialog_text(summary)
    script = (f'display dialog "{text}" with title "Approve this payment" buttons {{"Cancel", "Pay"}} '
              'default button "Cancel" cancel button "Cancel" with icon caution giving up after 180')
    try:
        run = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=200)
    except (OSError, subprocess.SubprocessError):
        return False
    return run.returncode == 0 and "button returned:Pay" in run.stdout and "gave up:true" not in run.stdout


def approve_hold(title: str, text: str) -> bool:
    """The person's answer to an order the Everyday Rules held (under their spending limit): a native dialog, as
    :func:`approve_payment`, with :func:`screens.hold_question`'s title and text and Steven's buttons (#270); True only
    for Buy anyway. Don't buy, a timeout, no screen or any error is a decline."""
    import subprocess

    script = (f'display dialog "{dialog_text(text)}" with title "{dialog_text(title)}" '
              "buttons {\"Don't buy\", \"Buy anyway\"} default button \"Don't buy\" cancel button \"Don't buy\" "
              "with icon caution giving up after 180")
    try:
        run = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=200)
    except (OSError, subprocess.SubprocessError):
        return False
    return run.returncode == 0 and "button returned:Buy anyway" in run.stdout and "gave up:true" not in run.stdout


def _ask_order(summary: str, real: bool, rail_name: str, seller: str = "", rail: str = ""):
    """The one question that releases an order under the person's spending limit, put after the deal check so a hold
    reason is part of it: an order the Everyday Rules hold is one dialog (:func:`screens.hold_question`: over a limit
    alone its figures, else every reason; Don't buy or Buy anyway); an order they do not hold is the payment dialog as
    before (``approval_gate``). ``seller`` and ``rail`` name the payee and the rail clause on the question's item line.
    For a yes it returns the person's :class:`rules.Answer` (the words the dialog showed and the button), which the
    approval record commits to."""
    def ask(outcome: "rules.Outcome") -> "rules.Answer | bool | None":
        if outcome.held:
            title, text = screens.hold_question(outcome.item, outcome.amount_msat, outcome.limits, outcome.reasons,
                                                outcome.over_limit, seller=seller, rail=rail)
            if not approve_hold(title, text):
                return None
            print(screens.rules_approved(outcome.reasons, outcome.over_limit))
            return rules.Answer(dialog_text(f"{title}\n{text}"), "Buy anyway")
        try:
            clicked = approval_gate(real, rail_name, summary)
        except NotApproved:
            return None
        return clicked or True  # True: the gate is off on a simulated rail (ARD_APPROVAL=none), no one clicked
    return ask


_session: Session | None = None
_seller: parties.Seller | None = None
_seller_lock: object | None = None


def session() -> Session:
    global _session
    if _session is None:
        _session = Session()
    return _session


def seller() -> parties.Seller:
    global _seller
    if _seller is None:
        packs.engine()
        global _seller_lock
        _seller_lock = _lock(ROLE)  # kept for the process's life: a dropped handle closes and frees the lock
        world = parties.ProcessWorld(_home(), (ROLE,)).open()
        n = world.nodes[ROLE]
        if sum(1 for b in n.shelf.books() if b.startswith("deal/") and b.count("/") == 1) < demo.DEALS_EACH:
            world.close()
            raise RuntimeError("no sample history yet: run `python demo.py seed` first")
        parties.ensure_stage(_home())
        _seller = parties.Seller(world, ROLE, os.environ.get("ARD_KESTREL_CARD", "sentinel"))
    return _seller


def _tool(*roles: str, description: str | None = None):
    """Register a tool for these roles (and for ``all``, which is the buyer's five). A tool returns the text the
    run printed; a refusal is a line starting ``REFUSED:`` and changes nothing."""
    def deco(fn):
        @functools.wraps(fn)
        def run(*args, **kwargs) -> str:
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    fn(*args, **kwargs)
            except (SystemExit, Exception) as exc:  # the demo's own refusals raise SystemExit with a message
                return (buf.getvalue() + f"\nREFUSED: {exc}").strip()
            return buf.getvalue().strip()
        run.__signature__ = inspect.signature(fn).replace(return_annotation=str)  # the result is the text, not what fn returns
        run.__annotations__ = {**fn.__annotations__, "return": str}
        del run.__wrapped__
        if ROLE in roles or (ROLE == "all" and "maya" in roles):
            return server.tool(description=description)(run)
        return run
    return deco


def _seller_key(name: str) -> str:
    key = name.strip().lower().split()[0] if name.strip() else ""
    if key not in SELLERS:
        raise ValueError(f"unknown seller {name!r}; the sellers found are " + ", ".join(SELLERS[k]["label"] for k in SELLERS))
    return key


@_tool("maya")
def ard_find_sellers() -> None:
    """Step 1-2: Maya's ask and ARD discovery. Lists the sellers found, each with its offer and whether its signed
    commitment verified. Call this first."""
    s = session()
    s.run.discover()
    if ROLE == "maya":
        s.bworld.nodes.update(parties.peers_from(_home()))
        if len(s.run.entries) < len(SELLERS):
            print("only " + ", ".join(e["name"] for e in s.run.entries) + " answered: the other seller's window is not running")


@_tool("maya")
def ard_show_history() -> None:
    """Step 3: ask each seller found for its evidence (history card and selection, over its mailbox), check each
    signed answer, and show the History cards. Call after ard_find_sellers."""
    s = session()
    if not s.run.entries:
        raise RuntimeError("call ard_find_sellers first")
    s.run.collect()
    print("\nHistory cards")
    for e in s.run.verified:
        ev = s.run.evidence[e["id"]]
        print(f"  {e['name']:18} {screens.card_line(ev, ev.sample_card)}")


@_tool("maya")
def ard_assess(max_adverse_permille: int = DEFAULT_PERMILLE) -> None:
    """Step 4: assess each seller under the admission pack, first as written, then with the rule tightened to at most
    ``max_adverse_permille`` deals in every 1,000 not holding (the pack's thresholds are placeholders).
    Call after ard_show_history."""
    s = session()
    if not s.run.evidence:
        raise RuntimeError("call ard_show_history first")
    s.start = s.start or packs.starting()
    s.run.assessments(s.start, "4  Assessment under the starting pack")
    s.pack = s.run.edit(s.start, max_adverse_permille)
    s.assessed = s.run.assessments(s.pack, "4b  Assessment again under the edited pack")


@_tool("maya")
def ard_pick(seller: str) -> None:
    """Step 5-6: seal Maya's pick of ``seller`` ("alder" or "kestrel"), citing both assessments. A seller over its
    limit ends here: no deal opens and nothing is paid. For a seller within its limit, ard_pay pays it next.
    Call after ard_assess."""
    s = session()
    if s.assessed is None:
        raise RuntimeError("call ard_assess first")
    key = _seller_key(seller)
    pick = s.run.seal(s.assessed, key)
    if pick is not None:
        s.picked[key] = pick
        print(f"{SELLERS[key]['label']} is within its limit. Call ard_pay to open the deal and pay it.")


if os.environ.get("ARD_RAIL") in ("lightning", "local"):
    _PAY = ("Step 6-7: open the deal for the picked seller and pay it over the real Lightning rail (2,000 msat for Alder). "
            "THIS MOVES REAL MONEY. A dialog appears on the presenter's screen and this call blocks, for up to 3 minutes, until "
            "the presenter clicks Pay or Cancel: do not retry or call it again while it waits, and tell the presenter to answer the "
            "dialog. Refused unless ard_pick sealed this seller.")
else:
    _PAY = ("Step 6-7: open the deal for the picked seller and pay it on the SIMULATED rail: no money moves. "
            "A dialog appears on the presenter's screen and this call blocks, for up to 3 minutes, until the presenter clicks Pay "
            "or Cancel: do not retry or call it again while it waits. Refused unless ard_pick sealed this seller.")


class NotApproved(RuntimeError):
    """The presenter's dialog did not approve the payment."""


def approval_gate(real: bool, rail_name: str, summary: str) -> rules.Answer | None:
    """Return only when this payment may go ahead: the presenter clicked Pay (their answer: the dialog's words and Pay,
    which the deal's approval record names), or the gate is off on a simulated rail (``None``: no one clicked)."""
    if os.environ.get("ARD_APPROVAL") == "none":
        if real:  # the gate goes off only where no money moves: a leftover test setting never pays for real
            raise RuntimeError(f"ARD_APPROVAL=none is refused on the {rail_name} rail, which moves real money: "
                               "unset it so the presenter approves the payment. Nothing was paid.")
        print("(approval gate off: ARD_APPROVAL=none, simulated rail, tests only)")
        return None
    if not approve_payment(summary):
        raise NotApproved("the presenter did not approve this payment (the approval dialog was cancelled, timed out or "
                           "could not be shown): nothing was paid. Do not retry on your own; if Maya asks again, confirm with her first.")
    return rules.Answer(dialog_text(summary), "Pay")


@_tool("maya", description=_PAY)
def ard_pay(seller: str) -> None:
    """Step 6-7: open the deal for the picked seller and pay it. Refused unless ard_pick sealed this seller."""
    s = session()
    key = _seller_key(seller)
    if key not in s.picked:
        raise RuntimeError(f"no sealed pick of {SELLERS[key]['label']} within its limit: call ard_pick first")
    limit = rules.limit_msat()
    with s.pay_lock:  # a second call waits here, then sees the seller attempted or paid
        was_paid = limit is not None and key in s.paid
        if was_paid:
            # With a spending limit set, a second order is the point of the show: it goes to the deal check as a new
            # deal, and the Everyday Rules decide. Without one, a seller is paid once per run, as before.
            s.paid.discard(key)
            s.attempted.discard(key)
            print(f"a second order to {SELLERS[key]['label']}: the deal check will run the Everyday Rules under your limit")
        try:  # nothing is paid until the lines below pass: a refusal here restores a paid seller the second order lifted
            if key in s.paid:
                raise RuntimeError(f"{SELLERS[key]['label']} was already paid in this run")
            if key in s.attempted:
                raise RuntimeError(f"a payment to {SELLERS[key]['label']} was already attempted in this run and is not confirmed: "
                                   "check the wallet before trying again")
            rail_name = os.environ.get("ARD_RAIL", "fake")
            real = rail_name in ("lightning", "local")
            label, amount = SELLERS[key]["label"], screens.msat(s.assessed[key].price_msat)
            shared = f"{SELLERS['alder']['label']} and {SELLERS['kestrel']['label']}"  # one seller wallet takes both sellers' payments
            rail = (f"over Lightning: this moves real money, to a wallet {shared} share" if real
                    else "on the simulated rail: no money moves")
            summary = f"Pay {label} {amount} {rail}."
            if key in s.declined:
                # This server never sees the chat, so it cannot check that Maya said yes. What it can do: the first call
                # after a refusal opens no dialog and hands the agent the question, so a bare "yes, pay" never goes straight
                # back to the dialog. An agent that already asked it calls again at once (no second ask of Maya); the next
                # call opens the dialog again, and the presenter's click stays the gate.
                s.declined.discard(key)
                raise RuntimeError(
                    f"the presenter did not approve the last payment to {label} (the dialog was cancelled or declined, timed out or could not be shown), "
                    f'so this call opens no dialog and pays nothing. The question is: "Pay {label} {amount} '
                    + ("over Lightning, which moves real money?" if real else "on the simulated rail, where no money moves?")
                    + '" If you asked Maya exactly that since the refusal and she said yes, call ard_pay again now. '
                    "Otherwise ask her it in your reply, end your turn, and call ard_pay again only after she says yes.")
            ask, clicked = None, None
            if limit is None:
                try:
                    clicked = approval_gate(real, rail_name, summary)
                except NotApproved:
                    s.declined.add(key)
                    raise
            else:  # under a spending limit the one dialog comes after the deal check, so it can carry the hold reasons
                ask = _ask_order(summary, real, rail_name, label, rail)
        except BaseException:
            if was_paid:
                s.paid.add(key)
            raise
        s.attempted.add(key)  # before the payment: a failure mid-way must not be retried blindly (check the wallet)
    try:
        _pay(s, key, limit, ask, clicked)
    except (rules.RuleHeld, rules.RulesError) as stopped:
        # The deal check ran before any payment: nothing was paid, so the session is as it was before this order
        # (an earlier paid order stays paid, and the order may be tried again).
        s.attempted.discard(key)
        if was_paid:
            s.paid.add(key)
        if isinstance(stopped, rules.RuleHeld):
            s.declined.add(key)  # the next call hands the agent the question again instead of reopening the dialog
        if isinstance(stopped, rules.RuleHeld) and not stopped.reasons:  # the payment dialog was cancelled, nothing held
            raise NotApproved("the presenter did not approve this payment (the approval dialog was cancelled, timed out or "
                              "could not be shown): nothing was paid. Do not retry on your own; if Maya asks again, confirm with her first.") from None
        if isinstance(stopped, rules.RuleHeld):
            raise RuntimeError(f"{screens.rules_held(stopped.reasons)} The person declined it. Tell Maya which rule held the "
                               "order and why, and that nothing was paid; do not try to pay around it.") from None
        if isinstance(stopped, rules.RulesRefused):
            raise RuntimeError(f"{stopped}. Nothing was paid. Tell Maya the Everyday Rules did not allow this order; do not "
                               "pay around it.") from None
        raise RuntimeError(f"{stopped}. Nothing was paid. Tell Maya the deal check could not run; do not pay around it.") from None


def _pay(s, key: str, limit: int | None, ask=None, clicked: rules.Answer | None = None) -> None:
    if ROLE == "all":
        s.run.pay_deal(s.assessed, key, s.picked[key], limit=limit, approve=ask, ask_always=True, clicked=clicked)
        s.paid.add(key)
        return
    a, peer, run = s.assessed[key], s.bworld.nodes[key], s.run
    chain = buyer.open_deal(run.maya, peer, s.picked[key], a, demo.ASK, run.rail.SEALED)
    print(f"deal opened with {SELLERS[key]['label']}: waiting for its agent's half")
    s.deal_ids.append(chain.deal_id)
    try:
        payment = parties.buyer_deal(run.maya, peer, chain, run.rail, a.price_msat, limit=limit, approve=ask, ask_always=True,
                                     clicked=clicked,
                                     on_paid=lambda p: s.paid.add(key) if p.status == "succeeded" else None)
    except (rules.RuleHeld, rules.RulesError):
        s.deal_ids.remove(chain.deal_id)  # the receipt tools read the latest deal: a declined order is not one
        raise
    who = ("the buyer's test node paid it" if run.banner == screens.BANNER else "the buyer's wallet paid it") if run.banner != screens.BANNER_FAKE else "the simulated rail paid it (no money moved)"
    print(f"invoice {screens.msat(payment.invoice_msat)}; {who}: {payment.status}"
          + screens.fee_note(payment.fee_msat, run.banner != screens.BANNER_FAKE))
    if payment.status == "succeeded":
        s.paid.add(key)
    print(f"deal closed with {SELLERS[key]['label']}: both parties' records of the deal compared.")
    # Maya's checkpoint over her own records, taken now so her card shows this deal right away. The profile allows one a
    # minute at the soonest, so this waits for it if the last one is that recent (it is due in the demo's story).
    waited = 0
    while waited < 60:
        if run.maya.tick(datetime.now(timezone.utc)).ticked:
            print("Maya's checkpoint taken over her records: her History card now counts this deal.")
            break
        if waited == 0:
            print("Maya's last checkpoint was under a minute ago: waiting for the next one (at most a minute).")
        time.sleep(5)
        waited += 5
    else:
        print("Maya's checkpoint is not due yet: her card shows this deal after it.")
    print(f"{SELLERS[key]['label']}'s agent takes its own checkpoint after the close; its card follows.")


@_tool("alder", "kestrel")
def ard_seller_activity() -> None:
    """What this seller's agent has done: the evidence requests it answered, any deal asked of it and how it went,
    the sale and payment, and its own History card now."""
    sel = seller()
    print(f"{sel.label}: its own node, keys and book (this window only)")
    for line in list(sel.log):
        print("  " + line)
    print(f"now: {sel.card_line()}")


def _own_node():
    """This window's own node, and its label."""
    if ROLE in SELLERS:
        sel = seller()
        return sel.node, sel.label
    s = session()
    return s.run.maya, "Maya"


@_tool("maya", "alder", "kestrel")
def ard_show_card() -> None:
    """Show THIS window's own History card (standard_history/1), computed from its own sealed records: its deals
    counted, held, did not hold. Call it before the deal and again after it: a sale counts after the party's next
    checkpoint. Each window shows only its own card."""
    node, label = _own_node()
    print(parties.card_view(node, label))


def _own_deal():
    """This window's node, its label and the latest deal of this run (``None`` before one)."""
    node, label = _own_node()
    stored = sorted(b[len("deal/"):] for b in node.shelf.books() if b.startswith("deal/") and b.count("/") == 1)
    # This run's deals in order. A seller's book also holds its 24 sample deals, so a seller shows only deals made since
    # its window opened (a restarted window shows none); the buyer's book holds only its own deals.
    ids = seller().deal_ids if ROLE in SELLERS else (session().deal_ids or stored)
    return node, label, (ids[-1] if ids else None)


@_tool("maya", "alder", "kestrel")
def ard_show_receipt() -> None:
    """Show THIS window's own receipt for the deal it took part in, read from its own sealed deal book: terms,
    steps, the payment's commitment, how it closed and its check of the other party's half."""
    node, label, deal_id = _own_deal()
    if deal_id is None:
        print(f"{label}: no deal yet, so no receipt")
        return
    print(parties.receipt_view(node, label, deal_id, seller=ROLE in SELLERS,
                               real=os.environ.get("ARD_RAIL", "fake") in ("lightning", "local")))


@_tool("maya", "alder", "kestrel")
def ard_open_receipt_page() -> None:
    """Open THIS window's own receipt for its deal as a page in the browser, for the audience: capsule-viewer's receipt
    view of its own copy of the deal, checked by capsulectl verify --bundle, with nothing added. Call it after the
    deal has closed (after ard_pay on Maya's side, after the close on a seller's)."""
    import pages
    import receipt

    node, label, deal_id = _own_deal()
    if deal_id is None:
        print(f"{label}: no deal yet, so no receipt page")
        return
    name = ROLE if ROLE in SELLERS else "maya"
    try:
        path = receipt.receipt_page(node, name, label, deal_id, rail=os.environ.get("ARD_RAIL", "fake"), seller=name in SELLERS)
    except receipt.ReceiptError as exc:
        print(f"{label}: no receipt page yet: {exc}")
        return
    opened = pages.open_page(path)
    shown = ("opened in the browser on the presenter's screen; nothing else is needed (do not copy or link the file)"
             if opened else "written (not opened)")
    print(f"{label}: its receipt page {shown}: {path}")


@_tool("maya", "alder", "kestrel")
def ard_open_card_page() -> None:
    """Open THIS window's own History card as a page in the browser, for the audience: capsule-viewer's History
    view of its own card (standard_history/1), with only the labels its count needs. Call it before the deal and again after it."""
    import pages

    node, label = _own_node()
    name = ROLE if ROLE in SELLERS else "maya"
    sample = name == "kestrel" and os.environ.get("ARD_KESTREL_CARD", "sentinel") == "sample"
    path = pages.card_page(node, name, label, rail=os.environ.get("ARD_RAIL", "fake"), seller=name in SELLERS,
                           sample_card=sample)
    opened = pages.open_page(path)
    shown = ("opened in the browser on the presenter's screen; nothing else is needed (do not copy or link the file)"
             if opened else "written (not opened)")
    print(f"{label}: its History card page {shown}: {path}")


def main() -> None:
    if ROLE in SELLERS:
        seller()  # a seller's agent runs from the moment its window opens, so the buyer finds it
    server.run()


if __name__ == "__main__":
    main()
