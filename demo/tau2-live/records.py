# SPDX-License-Identifier: Apache-2.0
"""The airline's x-deal-v1 records for one support case, through capsulectl.

One support case is one x-deal-v1 deal (Sherlock2's what confirmation on #219,
buzz://message?channel=0d760ea3-529d-4dec-b309-24184967f8e0&id=aa77b7d21f027f70cc1555f451b3acf98da6e74b7f37a361479f0063702607ae):

- the airline offers to a customer who keeps no records of its own (``to: null``)
  and agrees alone; the rows are the three checks of the tau2 airline rubric,
  owed by the airline;
- every turn of the conversation is a ``message`` in the airline's journal;
- a database-changing tool call is a ``perform`` resting on a passing ``deal
  check`` whose snapshot quotes the customer's sealed confirmation. The customer's
  "yes" is a received message the check reads, never an ``approval``: an
  approval is the airline's own principal's word.

Every command runs with ``XDG_CONFIG_HOME`` under the demo's state directory, so
the demo's profiles never mix with the user's own capsulectl profiles.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import window

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
RUBRIC = REPO / "demo" / "tau2-outcomes" / "compiled.json"
CHECKS = ("policy_compliance", "task_resolution", "grounded_communication")
ADMISSION_PACK = HERE / "admission" / "pack-definition.json"

INTENT = ("Handle each customer support case under the airline policy: change the booking "
          "database only after the customer explicitly confirms the listed action.")


class RecordError(RuntimeError):
    """A capsulectl command refused or failed; the message is its own."""


def utc(at: datetime) -> str:
    return at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass
class Store:
    """Where the demo keeps its profiles, books and files."""

    state: Path
    holder: str = "airline"
    window: str = "month"
    capsulectl: str = "capsulectl"
    capsule_engine: str = "capsule-engine"

    def env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["XDG_CONFIG_HOME"] = str(self.state / "config")
        return env

    def run(self, *args: str, profile: str | None = None) -> dict:
        cmd = [self.capsulectl] + (["--profile", profile] if profile else []) + list(args)
        proc = subprocess.run(cmd, capture_output=True, text=True, env=self.env(), stdin=subprocess.DEVNULL)
        out = proc.stdout.strip().splitlines()
        last = out[-1] if out else ""
        try:
            result = json.loads(last) if last else {}
        except json.JSONDecodeError:
            result = {}
        if proc.returncode != 0 or "error" in result:
            raise RecordError(result.get("error") or proc.stderr.strip() or f"{cmd[1:4]} exited {proc.returncode}")
        return result

    def book(self, at: datetime) -> str:
        """The window book (deal profile) for a time, created on first use."""
        name = window.book_name(self.holder, at, self.window)
        directory = self.state / "books" / name
        if not (directory / "deal.db").exists():
            self.run("deal", "init", "--dir", str(directory), "--no-witness",
                     "--materiality", "builtin:neutral", profile=name)
            self.run("deal", "set-version", "x-deal-v1", "--migrate", profile=name)
        return name


@dataclass
class Case:
    """One open support case: its deal and the book it is in."""

    store: Store
    book: str
    deal_id: str
    dir: Path

    def write(self, name: str, value: object) -> Path:
        path = self.dir / name
        path.write_text(json.dumps(value, indent=1) + "\n")
        return path

    def message(self, sender: str, text: str, sent_at: datetime | None = None) -> str:
        """Seal one turn as a message in the airline's journal; returns its capsule id.

        ``sender`` is ``agent`` (the airline's agent) or ``counterparty`` (the customer)."""
        body = {"from": sender, "channel": "support_chat", "text": text}
        if sent_at is not None:
            body["sent_at"] = utc(sent_at)
        path = self.write(f"msg-{os.urandom(4).hex()}.json", body)
        return self.store.run("deal", "note", "--deal", self.deal_id, "--kind", "message",
                              "--input", str(path), profile=self.book)["capsule_id"]

    def check(self, tool: str, arguments: dict, confirmation: dict) -> dict:
        """The airline's policy check before a write: what is about to happen, and the
        customer's sealed confirmation it rests on (capsule id and quoted words)."""
        description = (f"{tool} {json.dumps(arguments, sort_keys=True)}; customer confirmed in "
                       f"message {confirmation['capsule_id']}: {confirmation['text']!r}")
        path = self.write(f"check-{os.urandom(4).hex()}.json",
                          {"action": "commit", "description": description,
                           "terms": {"item": "airline support case"}})
        return self.store.run("deal", "check", "--deal", self.deal_id, "--input", str(path), profile=self.book)

    def perform(self, check_id: str, tool: str, observed: str = "tool_result") -> dict:
        """Seal the act in the deal book; returns the result with the record's capsule id."""
        out = self.dir / f"perform-{os.urandom(4).hex()}.json"
        result = self.store.run("deal", "perform", "--deal", self.deal_id, "--check", check_id,
                                "--act", tool, "--observed", observed, "--out", str(out), profile=self.book)
        result["capsule_id"] = json.loads(out.read_text())["record"]["record"]["capsule_id"]
        return result


def offer_input(task_id: str, judge_key: str, now: datetime) -> dict:
    """The airline's offer for one case: the rubric's three checks as rows it owes."""
    rubric = sha256_file(RUBRIC)
    rows = [{"id": check, "owed_by": "seller", "owed": {"check": check},
             "due": {"at": utc(now + timedelta(hours=1))},
             "window_end": {"at": utc(now + timedelta(days=1))}} for check in CHECKS]
    return {
        "role": "seller", "to": None,
        "terms": {"item": "airline support case", "conditions": {"case": f"tau2 airline task {task_id}"}},
        "pack_digest": rubric, "agree_by": utc(now + timedelta(hours=1)),
        "terms_rows": {"rows": rows, "named": {}},
        "adjudicator": {"key_id": judge_key, "rules_digest": rubric,
                        "rules_url": "https://github.com/action-state-group/evidencebook-skills/blob/main/demo/tau2-outcomes/compiled.json"},
        "forums": ["external:tau2-evaluator"], "witnesses": [],
    }


def admission_input(now: datetime) -> dict:
    """The demo admission pack's inputs: a customer on a support chat, not deny-listed."""
    return {"now": utc(now), "amount": "0", "currency": "USD",
            "platform": {"release_attestation": "unknown"}, "card": {},
            "own": {"exchanges": 0, "settled": 0, "held_halves": 0, "conflicting": 0, "verdicts": []},
            "operator": {"deny_listed": False}, "vouches": [], "subject": "", "judged": {},
            "asks": {}, "asks_made": 0}


def open_case(store: Store, task_id: str, judge_key: str, now: datetime | None = None) -> Case:
    """Offer, admit, intend and agree: the case's deal book opens with the agreement."""
    now = now or datetime.now(timezone.utc)
    book = store.book(now)
    case_dir = store.state / "cases" / f"{book}-task-{task_id}-{now.strftime('%H%M%S')}"
    case_dir.mkdir(parents=True, exist_ok=True)
    case = Case(store, book, "", case_dir)
    offer = store.run("deal", "offer", "--input", str(case.write("offer-in.json", offer_input(task_id, judge_key, now))),
                      "--out", str(case_dir / "offer.json"), profile=book)
    case.deal_id = offer["deal_id"]
    proc = subprocess.run([store.capsule_engine, "admission", "evaluate", "--pack", str(ADMISSION_PACK),
                           "--input", str(case.write("admission-in.json", admission_input(now))),
                           "--admit", str(case.write("admit-refs.json", {"asks": [], "answers": [], "card_digest": "0" * 64}))],
                          capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if proc.returncode != 0:
        raise RecordError(f"capsule-engine admission evaluate: {proc.stderr.strip()}")
    (case_dir / "admission-out.json").write_text(proc.stdout)
    store.run("deal", "admit", "--deal", case.deal_id, "--input", str(case_dir / "admission-out.json"), profile=book)
    intent = store.run("deal", "note", "--deal", case.deal_id, "--kind", "intent",
                       "--input", str(case.write("intent.json", {"verbatim": INTENT})),
                       "--opening", str(case.write("opening.json", {"type": "booking", "who": {"name": f"customer (tau2 task {task_id})"},
                                                                    "recourse": {"rail": "none", "refundable": False}})),
                       profile=book)
    store.run("deal", "agree", offer["offer"], "--intent", intent["intent"], "--out", str(case_dir / "agree.json"), profile=book)
    case.write("case.json", {"book": book, "deal_id": case.deal_id, "task_id": task_id, "opened_at": utc(now)})
    return case


def load_case(store: Store, case_dir: Path) -> Case:
    meta = json.loads((case_dir / "case.json").read_text())
    return Case(store, meta["book"], meta["deal_id"], case_dir)
