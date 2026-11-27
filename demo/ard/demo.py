#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The ARD two-seller demo: Maya buys 200 conference badges twice from sellers found through ARD.

    python demo.py seed            # once, before anyone watches: the sample history (15 + 10 deals), under a minute
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

    def close(self, wait: bool = True) -> None:
        """Stop the run. With ``wait``, first wait for a ruling stamp still being asked for in the background
        (adjudicator.LATER, #307), so the ruling with its stamp reaches both parties and Maya enters it; an
        interrupted run (Ctrl-C) does not wait, and a second Ctrl-C during the wait stops it too."""
        try:
            pending = [t for t in adj.LATER if t.is_alive()] if wait else []
            if pending:
                print(f"waiting up to {adj.LATER_S // 60} minutes for {pt.WITNESS_NAME} to stamp the ruling before "
                      "closing (Ctrl-C stops without it)")
                stop = time.monotonic() + adj.LATER_S
                for t in pending:
                    t.join(max(stop - time.monotonic(), 0))
            if wait:  # a ruling sent again with its stamp, now or earlier in the run: each side takes it before stopping
                for deal in buyer.deals_from_notes(self.maya):
                    flow.enter_rulings(self.home, self.maya, "buyer", deal.seller, print)
        except KeyboardInterrupt:
            wait = False
            print("\nstopped without the ruling's stamp")
        finally:
            for a in self.agents.values():  # each seller takes a stamped ruling after its loop stops, not alongside it
                a.stop(take_rulings=wait)
            self.stage.close()

    def ask(self, question: str) -> bool:
        print(f"\n{question}")
        if self.auto:
            print("[--auto: yes]")
            return True
        return input("[y/N] ").strip().lower() in ("y", "yes")

    def answer(self, q: buyer.Question) -> str:
        """The payment question at the terminal, as the dialog shows it: its title, its text (with capsulectl's card
        when the check paused) and its two choices; ``yes`` or ``no`` as typed (Enter is the safe one)."""
        print(f"\n{q.title}\n{q.text}")
        if self.auto:
            print(f"[--auto: {q.yes}]")
            return "yes"
        typed = input(f"[{q.yes}: y / {q.no}: N] ").strip().lower()
        return "yes" if typed in ("y", "yes") else "no"

    def countersign(self, deal: buyer.Deal) -> None:
        """The countersign upgrade after deal 2, as Maya's ``ard_countersign`` does it in Goose (RUNBOOK step 16): the
        demo's countersigner (``countersigner.py up``) countersigns Maya's own records of the deal, and the line is her
        receipt's, from capsulectl's report. A refusal says why and changes nothing, as the tool's does."""
        import countersigner as cs
        import receipt

        name = SELLERS[deal.seller]["label"]
        try:
            service = cs.env(Path(os.environ.get("ARD_COUNTERSIGN_DIR") or cs.default_dir(self.home)))
            stamp = self.maya.countersign(deal.deal_id, service)
        except (cs.CountersignerError, pt.Refused) as exc:
            print(f"REFUSED: {exc}")
            return
        print(f"Maya's deal {deal.deal_id[5:13]} with {name}: " + receipt.countersign_line(stamp, "Maya", name))

    def pause(self, prompt: str) -> None:
        if not self.auto:
            input(f"\n[{prompt}] ")

    def discover(self) -> None:
        rule("Maya asks her agent")
        print(f"Maya: {ASK}")
        rule("ARD discovery")
        self.entries = ard.lookup(stage.REGISTRY_URL, stage.ORIGINS, stage.QUERY, stage.CATALOG_ORIGIN)
        buyer.record_search(self.maya, stage.REGISTRY_URL, stage.QUERY, self.entries)
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
            print(f"  {screens.signed_line(e['name'], e['id'], ev.read is not None and ev.read.witness_status == 'pass')}")
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
        words = "over Lightning, which moves real money" if self.real else "on the simulated rail: no money moves"
        made = buyer.open_and_pay(self.home, self.maya, key, self.keys[key], a, self.adjudicator.named(), self.rail,
                                  f"Pay {name} {screens.msat(a.price_msat)} {words}.", self.answer, print,
                                  simulated=not self.real, rail_words=words)
        if made is None:
            print("not approved: nothing was sent to the seller and nothing was paid")
            return None
        deal, payment = made
        print(f"invoice {screens.msat(payment.invoice_msat)}: {payment.status}{screens.fee_note(payment.fee_msat, self.real)}")
        observed = buyer.await_delivery(self.home, self.maya, deal)
        print(screens.delivered_line(name, buyer.shipped(observed)))
        return deal

    def dispute(self, deal: buyer.Deal) -> None:
        rule("Maya disputes the delivery")
        buyer.dispute(self.home, self.maya, deal, print)
        print(screens.DISPUTE_RAISED.format(seller=SELLERS[deal.seller]["label"]))
        rule("The adjudicator")
        print(screens.ADJUDICATOR_INDEPENDENCE)
        print("the adjudicator asks each side for its books; each side's agent answers on its own")
        # Each side answers once the witness takes its stamp, or after ANSWER_WAIT_S without one: wait past that.
        stop = time.time() + adj.ANSWER_WAIT_S + 30
        while True:
            raw = next(c for c in self.adjudicator.gather(5) if c["deal_id"] == deal.deal_id)
            adj.answer_requests(self.home, self.maya, BUYER, "buyer", print)
            if len(raw["answers"]) == 2 or time.time() > stop:
                break
        raw = next(c for c in self.adjudicator.cases() if c["deal_id"] == deal.deal_id)  # with an answer sent just now
        if len(raw["answers"]) < 2:
            print(f"only {len(raw['answers'])} of the 2 sides answered in time; the case shows what came")
        # the adjudicator rules on its own, with no question to anyone (evidencebook-skills#416): at once on both answers,
        # or, with one, once RULE_AFTER_S has passed since it asked, on the answers in by then (a late one still counts)
        if len(raw["answers"]) < 2:
            print(f"the adjudicator rules {adj.RULE_AFTER_S // 60} minutes after asking, on the answers in by then")
        stop = adj.epoch(raw["asked_at"]) + adj.RULE_AFTER_S + 30
        while True:
            adj.answer_requests(self.home, self.maya, BUYER, "buyer", print)
            self.adjudicator.rule_decided()
            self.adjudicator.resume()
            raw = next(c for c in self.adjudicator.cases() if c["deal_id"] == deal.deal_id)
            if raw["ruling"] or adj.needs_person(raw["decision"], raw["answers"]) or time.time() > stop:
                break
            time.sleep(1)
        names = flow.case_names(raw)
        print("\n".join(flow.case_lines(flow.case_view(raw, names), names)))
        if not raw["ruling"]:
            return
        if pt.witnessed() and not adj.stamped(self.home, deal.deal_id):
            print(f"Not yet time-stamped: {pt.WITNESS_NAME} did not answer within 12 seconds. Both parties have the "
                  f"ruling without a stamp. This run keeps asking for {adj.LATER_S // 60} minutes and, once stamped, "
                  "sends the ruling to both parties again with its stamp.")
        print("Sent to both parties; each enters it.")
        agent = self.agents[deal.seller]
        stop = time.time() + 60
        while time.time() < stop and not (self.maya.notes(flow.RULING_ENTERED) and agent.party.notes(flow.RULING_ENTERED)):
            flow.enter_rulings(self.home, self.maya, "buyer", deal.seller, print)
            time.sleep(1)
        stop = time.time() + 30  # the seller stamps now, so its card counts the ruling (a second stamp, if the deal's
        while time.time() < stop:  # outcome follows the dispute's count by one)
            agent.republish(now=True)
            card, _, _ = flow.read_card(self.home / "stage" / "cards" / f"{deal.seller}.json")
            if card["disputes"]["received"]["by_outcome"]["against"] and card["outcomes"]["did_not_hold"]:
                break
            time.sleep(2)


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
    interrupted = False
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
                print(buyer.after_delivery(d2.seller, "200 of 200 badges"))
                buyer.confirm_by_question(home, s.maya, d2, SELLERS[d2.seller]["label"], s.ask, print)
                s.pause("Enter: Maya asks for deal 2 to be countersigned")
                s.countersign(d2)
        return 0
    except KeyboardInterrupt:
        interrupted = True
        print("\ninterrupted: the deals so far are kept; run `demo.py reset` and `demo.py seed` to start over")
        return 130
    finally:
        s.close(wait=not interrupted)


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
