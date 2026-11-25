#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The ARD two-seller demo: Maya buys 200 conference badges twice from sellers found through ARD.

    python demo.py seed            # once: the sample history (24 + 24 deals), about eight minutes
    python demo.py run [--rail lightning]
    python demo.py reset           # stop the demo's processes, forget the home, clear Goose's recipe trust

Deal 1: Maya picks Kestrel Print, the cheaper seller; Kestrel's own delivery record says 150 of 200 badges; Maya
disputes; the demo's adjudicator rules against Kestrel. Deal 2: Kestrel's card counts the lost dispute, Maya's own
records hold the ruling, and Maya buys from Alder Print Co. The Goose windows run the same story (RUNBOOK.md); this
script runs it in one terminal, each dialog asked at the prompt. The environment each command needs is listed at the
end of --help."""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _paths  # noqa: E402
import envhelp  # noqa: E402

DEFAULT_HOME = "~/.config/ard-commerce-demo"


def parser() -> argparse.ArgumentParser:
    """The command line; its help ends with the environment each command needs. It needs none of the demo's modules."""
    ap = argparse.ArgumentParser(prog="demo.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=envhelp.help_text({"seed": "seed", "run": "run", "reset": "reset"}))
    ap.add_argument("command", nargs="?", choices=["seed", "run", "reset"])
    ap.add_argument("--home", default=DEFAULT_HOME)
    ap.add_argument("--rail", choices=["fake", "lightning", "local"], default="fake")
    ap.add_argument("--auto", action="store_true", help="no pauses; every question answered yes (simulated rail only)")
    return ap


if __name__ == "__main__":
    # Before the setup below, which needs ARD_EVIDENCEBOOK: no command prints the help, a missing variable one
    # message with the export line (no traceback), and reset, which needs none of them, runs here.
    _args = parser().parse_args()
    if _args.command is None:
        parser().print_help()
        sys.exit(2)
    if _gap := envhelp.message(_args.command, _args.rail):
        sys.exit(_gap + "\n(demo.py --help lists every variable.)")
    if _args.command == "reset":
        import reset  # noqa: E402

        sys.exit(reset.main(["--home", _args.home]))

_paths.setup()

import adjudicator as adj  # noqa: E402
import ard  # noqa: E402
import buyer  # noqa: E402
import flow  # noqa: E402
import hf_search  # noqa: E402
import pack as packs  # noqa: E402
import party as pt  # noqa: E402
import pay  # noqa: E402
import screens  # noqa: E402
import seed as seeding  # noqa: E402
import stage  # noqa: E402
from cast import ASK, BUYER, SELLERS  # noqa: E402


def rule(title: str) -> None:
    print(f"\n── {title} " + "─" * max(4, 70 - len(title)))


class Script:
    """The whole story in one process: the stage, both sellers' agents, Maya's steps and the adjudicator's."""

    def __init__(self, home: Path, rail: pay.Rail, auto: bool, real: bool):
        self.home, self.rail, self.auto, self.real = home, rail, auto, real
        self.stage = stage.Stage(home)
        self.agents = {n: flow.SellerAgent(home, n) for n in SELLERS}
        self.maya = pt.Party(home, BUYER)
        self.adjudicator = adj.Adjudicator(home)
        self.pack = packs.starting()
        self.entries: list[dict] = []
        self.keys: dict[str, str] = {}

    def close(self) -> None:
        for a in self.agents.values():
            a.stop()
        self.stage.close()

    def ask(self, question: str) -> bool:
        print(f"\n{question}")
        if self.auto:
            print("[--auto: yes]")
            return True
        return input("[y/N] ").strip().lower() in ("y", "yes")

    def pause(self, prompt: str) -> None:
        if not self.auto:
            input(f"\n[{prompt}] ")

    def discover(self) -> None:
        rule("Maya asks her agent")
        print(f"Maya: {ASK}")
        rule("ARD discovery")
        self.entries = ard.lookup(stage.REGISTRY_URL, stage.ORIGINS, stage.QUERY)
        self.keys = {e["id"]: e["commitment"]["key_id"] for e in self.entries if "commitment" in e}
        for e in self.entries:
            price = screens.msat(e["offer"]["price_msat"]) if "offer" in e else "?"
            print(f"  found: {e['name']:18} {price:>10}   commitment {'verified' if 'commitment' in e else 'REFUSED: ' + e['problem']}")
        if hf_search.enabled():
            print("\n".join(hf_search.report(stage.QUERY)))

    def assess(self, heading: str) -> dict[str, buyer.Assessment]:
        rule(heading)
        made = {}
        for e in self.entries:
            ev = buyer.gather(self.home, self.maya, e)
            print(f"\n{e['name']}")
            print("\n".join("  " + line for line in screens.check_lines(ev)))
            if ev.card is None:
                continue
            print(f"  History card: {screens.card_line(ev.card)}")
            print(f"  {screens.signed_line(e['name'], ev.read is not None and ev.read.witness_status == 'pass')}")
            a = buyer.assess(self.maya, ev, self.keys[e["id"]], e["offer"]["price_msat"], self.pack)
            made[e["id"]] = a
            ceiling = self.pack.ceiling_msat(a.tier) if a.tier else None
            print(f"  assessment: {screens.decision_line(a, ev, ceiling)}")
        return made

    def buy(self, made: dict[str, buyer.Assessment], key: str) -> buyer.Deal | None:
        a, name = made[key], SELLERS[key]["label"]
        buyer.seal_pick(self.maya, self.keys[key], a, [m for k, m in made.items() if k != key])
        rule(f"Maya picks {name}")
        print(f"pick sealed before any payment: {name} at {screens.msat(a.price_msat)}")
        if a.verdict != "GO":
            print(screens.limit_outcome(a))
            return None
        deal = buyer.open_deal(self.home, self.maya, key, self.keys[key], a, self.adjudicator.named(), print,
                               rail=self.rail.SEALED)
        inv = self.rail.invoice(a.price_msat)
        check = buyer.check_payment(self.maya, deal, inv.payment_hash)
        words = "over Lightning, which moves real money" if self.real else "on the simulated rail: no money moves"
        summary = f"Pay {name} {screens.msat(a.price_msat)} {words}."
        if not check.get("proceed"):
            if not self.ask(summary):
                print("not approved: nothing was paid")
                return None
            self.maya.approve(deal.deal_id, check, "proceed", f"{summary}\nAnswer: Pay")
        payment = self.rail.pay_invoice(inv)
        print(f"invoice {screens.msat(payment.invoice_msat)}: {payment.status}{screens.fee_note(payment.fee_msat, self.real)}")
        buyer.pay(self.home, self.maya, deal, check, payment.reference, simulated=not self.real)
        observed = buyer.await_delivery(self.home, self.maya, deal)
        print(screens.delivered_line(name, buyer.shipped(observed)))
        return deal

    def dispute(self, deal: buyer.Deal) -> None:
        rule("Maya disputes the delivery")
        buyer.dispute(self.home, self.maya, deal, print)
        print(screens.DISPUTE_RAISED.format(seller=SELLERS[deal.seller]["label"]))
        rule("The adjudicator")
        print(screens.ADJUDICATOR_INDEPENDENCE)
        names = {self.maya.key_id: "Maya", **{v: SELLERS[k]["label"] for k, v in self.keys.items()}}
        print("waiting for both sides' books (each needs its next checkpoint, up to a minute)")
        stop = time.time() + 300
        while time.time() < stop:
            cases = [c for c in self.adjudicator.cases() if c["deal_id"] == deal.deal_id]
            if cases and len(cases[0]["copies"]) >= 2:
                break
            time.sleep(3)
        c = flow.case_view(cases[0], names)
        for b in c.books:
            print(f"  books read: {'Maya' if b['side'] == 'buyer' else SELLERS[deal.seller]['label']}'s own book (sent {b['received_at']})")
        for line in c.deciding:
            print(f"  {line}")
        if not self.ask(screens.rule_question(c.deal_id, c.row, SELLERS[deal.seller]["label"])):
            print("no ruling recorded")
            return
        self.adjudicator.rule(c.case, c.dispute, c.copies, c.row, "not_met", "seller")
        if pt.witnessed():
            self.adjudicator.witness()
        print(f"Ruling recorded: not met, against {SELLERS[deal.seller]['label']}. Both parties fetch it and enter it.")
        agent = self.agents[deal.seller]
        stop = time.time() + 300
        while time.time() < stop and not (self.maya.notes(flow.RULING_ENTERED) and agent.party.notes(flow.RULING_ENTERED)):
            flow.enter_rulings(self.home, self.maya, deal.seller, print)
            time.sleep(3)
        print("waiting for the seller's next checkpoint, so its card counts the ruling (up to a minute)")
        stop = time.time() + 180
        while time.time() < stop:
            agent.republish()
            card, _, _ = flow.read_card(self.home / "stage" / "cards" / f"{deal.seller}.json")
            if card["disputes"]["received"]["by_outcome"]["against"]:
                break
            time.sleep(5)


def cmd_seed(args) -> int:
    seeding.seed(Path(os.environ.get("ARD_HOME", args.home)).expanduser())
    return 0


def cmd_run(args) -> int:
    packs.engine(), packs.skills_checkout()
    home = Path(os.environ.get("ARD_HOME", args.home)).expanduser()
    if not pt.Party(home, BUYER).exists:
        print("no sample history yet: run `python demo.py seed` first")
        return 2
    real = args.rail in ("lightning", "local")
    if args.auto and real:
        print("--auto answers every question yes, so it is refused on a rail that moves real money")
        return 2
    s = Script(home, pay.from_env(args.rail), args.auto, real)
    try:
        s.discover()
        s.pause("Enter: read each seller's History card and assess both")
        made = s.assess("Deal 1: History cards and assessment")
        s.pause("Enter: Maya picks the cheaper seller")
        cheaper = min(made, key=lambda k: made[k].price_msat)
        deal = s.buy(made, cheaper)
        if deal is not None:
            s.pause("Enter: Maya disputes the short delivery")
            s.dispute(deal)
        s.pause("Enter: deal 2, Maya orders again")
        made = s.assess("Deal 2: History cards and assessment again")
        go = [k for k, a in made.items() if a.verdict == "GO"]
        if go:
            d2 = s.buy(made, go[0])
            if d2 is not None:
                buyer.close_received(home, s.maya, d2)
                print("Maya's statement sent: she received what she paid for.")
        return 0
    except KeyboardInterrupt:
        print("\ninterrupted: the deals so far are kept; run `demo.py reset` and `demo.py seed` to start over")
        return 130
    finally:
        s.close()


def main(argv: list[str] | None = None) -> int:
    ap = parser()
    sys.stdout.reconfigure(line_buffering=True)
    args = ap.parse_args(argv)
    if args.command is None:
        ap.print_help()
        return 2
    return {"seed": cmd_seed, "run": cmd_run}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
