#!/usr/bin/env python3
"""The transaction evaluator: three recomputed folds over a seller's
transactions (a deal between a buyer and a seller, whatever is sold), decided
from each transaction's own record with no model and no key.

A deal pack (`scope.kind: deal`; packs/sticker-sale and
packs/coffee-beans-sale are the example packs) names this module as its
`evaluator: transaction`; scripts/studio/terms.py runs it (`terms run`, `terms test`).
Terms Pack Studio first demo, evidencebook-skills#117.

A transaction is one normalized dict, the fields the deal store's records carry once
read (the field names are the replay fixture's, evidencebook-deal#136):

    deal_id          the transaction's id
    offered_price    the asking price the goods were offered at (minor units)
    accepted_price   the price the buyer accepted and the seller committed to
    paid_at          when the payment was received (RFC 3339 UTC)
    delivered_at     when the seller reports the goods were delivered (RFC 3339 UTC)

The folds, each met / not_met / not_evaluable. A fold that lacks a field it
needs is not_evaluable, never not_met: a transaction that is not delivered yet has not
missed a delivery term.

    paid_before_delivered      paid_at is not after delivered_at
    delivered_within_days(N)   delivered_at - paid_at is at most N whole days
                               (N is written in the row's `check`, so the
                               number a seller edits lives inside the row)
    price_as_offered           accepted_price equals offered_price

`CHECKS` is the closed list of check names a row may use; `CASES` builds the two
transactions per check (one met, one not) that `terms test` runs.
"""
import datetime
import re

CHECK_RE = re.compile(r"\A([a-z_]+)(?:\((\d+)\))?\Z")


def parse_check(check):
    """('name', arg_or_None) from a row's check string, or None when it is not
    one name with at most one whole-number argument."""
    m = CHECK_RE.match(check) if isinstance(check, str) else None
    if not m:
        return None
    return m.group(1), (int(m.group(2)) if m.group(2) is not None else None)


def _time(value):
    if not isinstance(value, str):
        return None
    try:
        t = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo is not None else None  # RFC 3339 carries an offset; a bare time is no time


def _minor(value):
    """A price in minor units: a whole number, never a bool, string or object."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def paid_before_delivered(deal, arg):
    paid, delivered = _time(deal.get("paid_at")), _time(deal.get("delivered_at"))
    if paid is None or delivered is None:
        return "not_evaluable"
    return "met" if paid <= delivered else "not_met"


def delivered_within_days(deal, arg):
    paid, delivered = _time(deal.get("paid_at")), _time(deal.get("delivered_at"))
    if paid is None or delivered is None:
        return "not_evaluable"
    return "met" if delivered - paid <= datetime.timedelta(days=arg) else "not_met"


def price_as_offered(deal, arg):
    offered, accepted = _minor(deal.get("offered_price")), _minor(deal.get("accepted_price"))
    if offered is None or accepted is None:
        return "not_evaluable"
    return "met" if offered == accepted else "not_met"


# name -> (fold, takes a whole-number argument)
CHECKS = {
    "paid_before_delivered": (paid_before_delivered, False),
    "delivered_within_days": (delivered_within_days, True),
    "price_as_offered": (price_as_offered, False),
}

# name -> the transaction fields the fold reads: what a row's `proves` must list
READS = {
    "paid_before_delivered": ("paid_at", "delivered_at"),
    "delivered_within_days": ("paid_at", "delivered_at"),
    "price_as_offered": ("offered_price", "accepted_price"),
}

_PAID = datetime.datetime(2026, 11, 1, 10, 0, 0, tzinfo=datetime.timezone.utc)


def _stamp(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _delivered_after(delta):
    return {"paid_at": _stamp(_PAID), "delivered_at": _stamp(_PAID + delta)}


# name -> fn(arg) -> (a transaction that meets the row, one that misses it)
CASES = {
    "paid_before_delivered": lambda arg: (_delivered_after(datetime.timedelta(hours=2)),
                                          _delivered_after(datetime.timedelta(hours=-1))),
    "delivered_within_days": lambda arg: (_delivered_after(datetime.timedelta(days=arg)),
                                          _delivered_after(datetime.timedelta(days=arg, seconds=1))),
    "price_as_offered": lambda arg: ({"offered_price": 500, "accepted_price": 500},
                                     {"offered_price": 500, "accepted_price": 450}),
}


def row_check(row):
    """(fold, arg) for a row, or raises ValueError naming why it has none."""
    parsed = parse_check(row.get("check"))
    if parsed is None or parsed[0] not in CHECKS:
        raise ValueError(f"row {row.get('id')!r}: check {row.get('check')!r} must be one of {sorted(CHECKS)}")
    name, arg = parsed
    fold, takes_arg = CHECKS[name]
    if takes_arg and (arg is None or arg < 1):
        raise ValueError(f"row {row.get('id')!r}: {name} needs a whole number of days, as {name}(2)")
    if not takes_arg and arg is not None:
        raise ValueError(f"row {row.get('id')!r}: {name} takes no argument")
    return fold, arg


def evaluate(rows, deals):
    """{deal_id: {row_id: verdict}} for every transaction and every row."""
    folds = [(row["id"], *row_check(row)) for row in rows]
    return {deal["deal_id"]: {rid: fold(deal, arg) for rid, fold, arg in folds} for deal in deals}
