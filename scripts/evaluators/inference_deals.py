#!/usr/bin/env python3
"""The inference-deals pack's evaluator: a Mesh node's come-through terms over
its own paid exchanges, decided from its sealed records with no model.

packs/inference-deals/pack-source.yaml names this module as its `evaluator`
(scripts/pack_compile.py EVALUATORS); scripts/report.sh runs it in place of a
judge. Steven's rulings, 2026-10-29: fully deterministic, no LLM call (ops
c18ddbd8); terms 1-3, all must_have, over 12 months in whole closed periods
tied to AAC #315 `period_policy` (ops f4f269eb).

    inference_deals.py --profile NAME --spec packs/inference-deals/compiled/compiled.json \\
        --date YYYY-MM-DD --generated-at TS --out DIR [--period-policy FILE] [--capsulectl PATH]

writes DIR/result-v0-<from>_<to>.json (one Result v0 for the window) and
DIR/summary.json, the file names scripts/report.sh's tail reads.

The records it reads, as a Mesh node seals them (Mesh-LLM/capsules-plugin
a0297e0; each book record's payload is one Mesh capsule):
  - a payment lifecycle observation: `model_attestation.compute_attestation
    ["x-mesh-settlement-v1"]` {observed_by, exchange_id, phase, source,
    segment, payment_hash, amount_msat, ...} (producer/capsule.rs);
  - an exchange record: `...["x-mesh-poc-v1"]` with `role` (served |
    requested) and `serving_provenance.exchange_id`, and the provider's own
    `invocation.requested_model_id` / `resolved_model_id`;
  - a settlement leg: a top-level `settlement` member (draft-mih-agent-
    settlement-records-00): terms, payer_observed, payee_observed, delivered.

Window. The anchor is the last period boundary (epoch + k * length_s) at or
before the end of --date. The window is every whole period that ends at or
before the anchor and starts no earlier than `months` calendar months before
it, so it moves only when a period closes. A record belongs to a period by its
own `timestamp` (the node seals at commit); a record after the anchor is not
read at all, and a deal belongs to the window by its earliest record.

Deals. A deal is one exchange_id that a lifecycle observation names in this
book. An exchange no observation names ran free or with payments off
(`settlement: null`): it is not a deal, never judged and never counted. A deal
whose one `counterparty_class` record says `shop_preauth` is not counted; a
deal with no such member (or with it on two records, AAC Standard History §7)
is counted and tallied as lacking it. Every count the Result carries is in its
`x-window`; amounts, node and peer ids, counterparties and payment hashes
never are.

Terms (rows), each met / not_met / not_evaluable, or out_of_scope when the deal
did not carry it (the node bought: term 1; it provided: terms 2 and 3):
  1. paid_as_agreed, from the payer's observations, in the order the plugin's
     own settlement state uses (evidence_panes/settlement.rs): a settlement
     matching no invoice makes the deal `unmatched_settlement`, counted and
     never graded; no invoice is `terms_only`; every invoice settled by the
     wallet is met when each settlement equals its invoice's amount and
     not_met otherwise; no `final_accounted` is `outcome_not_reported`; else
     `no_settlement_seen`. The last three and unmatched are not_evaluable.
  2. served_as_agreed: the provider's served exchange record, and its
     invoices settled by its wallet, by the same rules (an unpaid invoice is
     `outcome_not_reported`).
  3. served_named_model: the accepted terms carry the model only inside
     `terms_digest`, so no Mesh record lets a verifier recompute it. The row
     reads "provider states" (`x-reading: provider_states`): met when the
     node's own record names the same requested and resolved model.

Grades: `countersigned` when the book also holds the counterparty's signed
leg of the same payment (a `settlement` leg under another key, joined by
payment hash and terms_ref), else `self-attested`. The key is read from the
record (`key_id`); the counterparty's signature is not verified here.
"""
import argparse
import calendar
import datetime
import hashlib
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from capsulectl_calls import EvidenceUnavailable, list_capsules, payload  # noqa: E402
from result_v0 import build_result_v0_for_day, report_title  # noqa: E402
from rollup import RollupError  # noqa: E402

OBSERVATION = "x-mesh-settlement-v1"
EXCHANGE = "x-mesh-poc-v1"

PAID = "come_through.paid_as_agreed"
SERVED = "come_through.served_as_agreed"
MODEL = "come_through.served_named_model"
FOLDS = {
    "inference_deals.paid_as_agreed": PAID,
    "inference_deals.served_as_agreed": SERVED,
    "inference_deals.served_named_model": MODEL,
}

INVOICE_PHASES = ("input_invoice_issued", "output_invoice_issued")
SETTLEMENT_PHASES = ("input_settlement_observed", "output_settlement_observed")


class DealsError(ValueError):
    """The pack, the policy or the book cannot give a Result; nothing is written."""


def _time(value):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"not an RFC 3339 UTC time: {value!r}")
    return datetime.datetime.fromisoformat(value[:-1] + "+00:00")


def _iso(dt):
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _months_before(dt, months):
    """The same instant `months` calendar months earlier, the day clamped to
    the target month's length."""
    y, m = divmod(dt.year * 12 + dt.month - 1 - months, 12)
    m += 1
    return dt.replace(year=y, month=m, day=min(dt.day, calendar.monthrange(y, m)[1]))


def policy_digest(policy):
    """SHA-256 over the RFC 8785 form of a period policy: its members are
    strings and integers only, which JSON with sorted keys and no spaces
    serializes exactly as RFC 8785 does."""
    return hashlib.sha256(json.dumps(policy, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


def window_bounds(date, months, policy):
    """(from, to, periods) for the report's --date: whole closed periods of the
    policy, ending at the last boundary at or before the end of `date`."""
    epoch, length = _time(policy["epoch"]), policy["length_s"]
    end_of_day = datetime.datetime.combine(date + datetime.timedelta(days=1), datetime.time(),
                                           datetime.timezone.utc)
    k = (end_of_day - epoch) // datetime.timedelta(seconds=length)
    to = epoch + datetime.timedelta(seconds=k * length)
    earliest = _months_before(to, months)
    j = -((epoch - earliest) // datetime.timedelta(seconds=length))  # first boundary >= earliest
    start = epoch + datetime.timedelta(seconds=j * length)
    periods = (to - start) // datetime.timedelta(seconds=length)
    if periods < 1:
        raise DealsError(f"no whole closed period of {length}s fits in {months} months before {_iso(to)}")
    return start, to, periods


def _attestation(body):
    return ((body.get("model_attestation") or {}).get("compute_attestation") or {})


def _kind(body):
    """(kind, member) for one Mesh capsule, or (None, None) for anything else."""
    if not isinstance(body, dict):
        return None, None
    ca = _attestation(body)
    if isinstance(ca.get(OBSERVATION), dict):
        return "observation", ca[OBSERVATION]
    if isinstance(body.get("settlement"), dict):
        return "leg", body["settlement"]
    if isinstance(ca.get(EXCHANGE), dict):
        return "exchange", ca[EXCHANGE]
    return None, None


class Deal:
    def __init__(self, exchange_id):
        self.exchange_id = exchange_id
        self.observations = []   # (book capsule id, member)
        self.exchange = None     # (book capsule id, body, member) of this node's exchange record
        self.first = None
        self.records = []        # every capsule of this deal, as (book capsule id, body)

    def add(self, cid, body, when):
        self.records.append((cid, body))
        self.first = when if self.first is None else min(self.first, when)

    @property
    def roles(self):
        return {m.get("observed_by") for _, m in self.observations}


def collect(records, start, to):
    """records: [(book capsule id, payload)] in book order -> (deals by
    exchange id, legs, own key ids). Only records sealed before `to` are read;
    a deal is kept when its earliest record is in [start, to)."""
    deals, legs, own_keys = {}, [], set()
    exchanges = {}
    for cid, body in records:
        kind, member = _kind(body)
        if kind is None:
            continue
        try:
            when = _time(body.get("timestamp"))
        except ValueError:
            raise DealsError(f"record {cid}: no readable timestamp")
        if when >= to:
            continue
        if kind == "leg":
            legs.append((cid, body, member))
            continue
        if body.get("key_id"):
            own_keys.add(body["key_id"])
        if kind == "observation":
            xid = member.get("exchange_id")
            if not isinstance(xid, str) or not xid:
                raise DealsError(f"record {cid}: a lifecycle observation with no exchange_id")
            deal = deals.setdefault(xid, Deal(xid))
            deal.observations.append((cid, member))
            deal.add(cid, body, when)
        else:
            xid = (member.get("serving_provenance") or {}).get("exchange_id")
            if isinstance(xid, str) and xid:
                exchanges.setdefault(xid, []).append((cid, body, member, when))
    for xid, found in exchanges.items():
        deal = deals.get(xid)
        if deal is None:
            continue  # free, or payments off: no observation names it
        for cid, body, member, when in found:
            deal.add(cid, body, when)
            if deal.exchange is None:
                deal.exchange = (cid, body, member)
    kept = {x: d for x, d in deals.items() if start <= d.first < to}
    return kept, legs, own_keys


def _join(invoice, settlement):
    if invoice.get("payment_hash") and settlement.get("payment_hash"):
        return invoice["payment_hash"] == settlement["payment_hash"]
    return invoice.get("segment") == settlement.get("segment")


def payment_state(observations, side):
    """(verdict, state, unmatched settlement count, settled payment hashes) over
    one side's observations of one deal (evidence_panes/settlement.rs order)."""
    invoices = [m for _, m in observations if m.get("phase") in INVOICE_PHASES]
    settlements = [m for _, m in observations if m.get("phase") in SETTLEMENT_PHASES
                   and m.get("source") == "wallet_reported"]
    unmatched = [s for s in settlements if not any(_join(i, s) for i in invoices)]
    if unmatched:
        return "not_evaluable", "unmatched_settlement", len(unmatched), set()
    if not invoices:
        return "not_evaluable", "terms_only", 0, set()
    paired = [(i, [s for s in settlements if _join(i, s)]) for i in invoices]
    if all(found for _, found in paired):
        ok = all(all(s.get("amount_msat") == i.get("amount_msat") for s in found) for i, found in paired)
        hashes = {s.get("payment_hash") for _, found in paired for s in found if s.get("payment_hash")}
        return ("met" if ok else "not_met"), "settled", 0, hashes
    if side == "payer" and not any(m.get("phase") == "final_accounted" for _, m in observations):
        return "not_evaluable", "outcome_not_reported", 0, set()
    if side == "provider":
        return "not_evaluable", "outcome_not_reported", 0, set()
    return "not_evaluable", "no_settlement_seen", 0, set()


def _countersigned(side, hashes, legs, own_keys):
    """Whether the book holds the counterparty's signed leg of one of these
    payments: on a payer node, the payee's payee_observed leg naming one of the
    payer's own terms legs; on a provider node, the payer's terms leg its own
    payee_observed leg names."""
    if not hashes:
        return False
    def foreign(body):
        return bool(body.get("key_id")) and body["key_id"] not in own_keys
    by_id = {body.get("capsule_id"): (body, m) for _, body, m in legs}
    for _, body, m in legs:
        if m.get("leg") != "payee_observed" or (m.get("payment_ref") or {}).get("value") not in hashes:
            continue
        terms = by_id.get(m.get("terms_ref"))
        if terms is None or terms[1].get("leg") != "terms" or terms[1].get("sealer_role") != "payer":
            continue
        payee_foreign, terms_foreign = foreign(body), foreign(terms[0])
        if side == "payer" and payee_foreign and not terms_foreign and m.get("sealer_role") == "payee":
            return True
        if side == "provider" and terms_foreign and not payee_foreign:
            return True
    return False


def _cited(deal, legs, hashes):
    """The book capsule ids a row cites: the deal's own records and the legs
    of its payments."""
    ids = [cid for cid, _ in deal.records]
    leg_ids = {body.get("capsule_id") for _, body, m in legs
               if (m.get("payment_ref") or {}).get("value") in hashes}
    terms = {m.get("terms_ref") for _, body, m in legs if body.get("capsule_id") in leg_ids}
    ids += [cid for cid, body, _ in legs if body.get("capsule_id") in leg_ids | terms]
    return sorted(set(ids))


def judge_deal(deal, legs, own_keys):
    """{criterion: verdict}, {criterion: extras}, {criterion: cited ids}, the
    deal's state, and its unmatched settlement count."""
    verdicts = {PAID: "out_of_scope", SERVED: "out_of_scope", MODEL: "out_of_scope"}
    extras, cited = {}, {}
    roles = deal.roles
    if len(roles) != 1 or roles - {"payer", "provider"}:
        # One node is never both sides of one exchange: the records conflict.
        for c in verdicts:
            verdicts[c] = "not_evaluable"
            extras[c] = {"x-state": "conflicting_roles"}
            cited[c] = [cid for cid, _ in deal.records]
        return verdicts, extras, cited, "conflicting_roles", 0
    side = roles.pop()
    verdict, state, unmatched, hashes = payment_state(deal.observations, side)
    grade = "countersigned" if verdict in ("met", "not_met") and _countersigned(side, hashes, legs, own_keys) \
        else "self-attested"
    if side == "payer":
        verdicts[PAID] = verdict
        extras[PAID] = {"grade": grade, "x-state": state}
        cited[PAID] = _cited(deal, legs, hashes)
        return verdicts, extras, cited, state, unmatched
    served = deal.exchange is not None and deal.exchange[2].get("role") == "served"
    if not served:
        verdicts[SERVED] = verdicts[MODEL] = "not_evaluable"
        extras[SERVED] = {"x-state": "no_served_record"}
        extras[MODEL] = {"x-state": "no_served_record"}
        cited[SERVED] = cited[MODEL] = _cited(deal, legs, hashes)
        return verdicts, extras, cited, state, unmatched
    verdicts[SERVED] = verdict
    extras[SERVED] = {"grade": grade, "x-state": state}
    cited[SERVED] = _cited(deal, legs, hashes)
    invocation = _attestation(deal.exchange[1]).get("invocation") or {}
    requested, resolved = invocation.get("requested_model_id"), invocation.get("resolved_model_id")
    if isinstance(requested, str) and requested and isinstance(resolved, str) and resolved:
        verdicts[MODEL] = "met" if requested == resolved else "not_met"
    else:
        verdicts[MODEL] = "not_evaluable"
    extras[MODEL] = {"x-reading": "provider_states"}
    cited[MODEL] = [deal.exchange[0]]
    return verdicts, extras, cited, state, unmatched


def counterparty_class(deal):
    """The deal's counterparty_class: the one record's value, or None when no
    record or more than one carries it (AAC Standard History §7)."""
    values = [body["counterparty_class"] for _, body in deal.records if "counterparty_class" in body]
    return values[0] if len(values) == 1 else None


def build_result(records, compiled, date, generated_at, policy=None):
    """Pure: the book's records -> (Result v0 document, summary). No I/O."""
    for clause in compiled["clauses"]:
        if FOLDS.get(clause.get("fold_id")) != clause["id"]:
            raise DealsError(f"clause {clause['id']!r} names fold {clause.get('fold_id')!r}, which this "
                             "evaluator does not answer")
    if {c["id"] for c in compiled["clauses"]} != set(FOLDS.values()):
        raise DealsError("the compiled pack's clauses are not this evaluator's three terms")
    window = compiled["window"]
    policy = policy or window["period_policy"]
    start, to, periods = window_bounds(date, window["months"], policy)
    deals, legs, own_keys = collect(records, start, to)

    ordered = sorted(deals.values(), key=lambda d: (d.first, d.exchange_id))
    rollups, sources, extras_by_case = [], {}, {}
    counts = {"deals_counted": 0, "not_counted_shop_preauth": 0, "class_missing": 0,
              "unmatched_settlements": 0, "states": {}}
    n = 0
    for deal in ordered:
        cls = counterparty_class(deal)
        if cls == "shop_preauth":
            counts["not_counted_shop_preauth"] += 1
            continue
        if cls is None:
            counts["class_missing"] += 1
        verdicts, extras, cited, state, unmatched = judge_deal(deal, legs, own_keys)
        counts["unmatched_settlements"] += unmatched
        counts["states"][state] = counts["states"].get(state, 0) + 1
        n += 1
        case_id = f"d{n}"
        tiers = {c: "recomputed" for c in verdicts}
        rollups.append((case_id, verdicts, {c: cited.get(c) for c in verdicts}, tiers))
        extras_by_case[case_id] = extras
        sources[case_id] = {}
    counts["deals_counted"] = n
    if not rollups:
        raise DealsError(f"no counted deal in the window {_iso(start)} to {_iso(to)}: nothing to report")

    all_criteria = tuple(c["id"] for c in compiled["clauses"])
    label = f"{start.date().isoformat()} to {(to - datetime.timedelta(seconds=1)).date().isoformat()}"
    try:
        doc = build_result_v0_for_day(label, rollups, generated_at, all_criteria, compiled["contract_ref"],
                                      allow_out_of_scope=True, claim_extras=extras_by_case)
    except RollupError as e:
        raise DealsError(str(e)) from e
    doc["view"]["title"] = report_title(compiled, label)
    doc["x-window"] = {
        "from": _iso(start), "to": _iso(to), "periods": periods, "months": window["months"],
        "period_policy_digest": policy_digest(policy),
        "deals_counted": counts["deals_counted"],
        "not_counted_shop_preauth": counts["not_counted_shop_preauth"],
        "class_missing": counts["class_missing"],
        "unmatched_settlements": counts["unmatched_settlements"],
        "peer_book": "not_available",
    }
    summary = {"contract_ref": compiled["contract_ref"], "window": doc["x-window"], "states": counts["states"]}
    return doc, summary


def read_book(capsulectl, profile):
    return [(e["capsule_id"], payload(capsulectl, profile, e["capsule_id"]))
            for e in list_capsules(capsulectl, profile)]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--spec", required=True, type=pathlib.Path, help="the pack's compiled.json")
    ap.add_argument("--capsulectl", default="capsulectl")
    ap.add_argument("--date", required=True, help="YYYY-MM-DD: the window ends at the last period boundary "
                                                  "at or before the end of this day (UTC)")
    ap.add_argument("--generated-at", required=True)
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("--period-policy", type=pathlib.Path,
                    help="the node's own period_policy JSON, in place of the pack's default")
    args = ap.parse_args(argv)
    compiled = json.loads(args.spec.read_text())
    try:
        policy = json.loads(args.period_policy.read_text()) if args.period_policy else None
        if policy is not None:
            import pack_compile
            issues = pack_compile._validate_deterministic(
                {"evaluator": "inference_deals", "window": {"months": 1, "period_policy": policy}}, [])
            if issues:
                raise DealsError("--period-policy: " + "; ".join(issues))
        doc, summary = build_result(read_book(args.capsulectl, args.profile), compiled,
                                    datetime.date.fromisoformat(args.date), args.generated_at, policy)
    except (DealsError, EvidenceUnavailable, ValueError) as e:
        print(json.dumps({"error": str(e)}, indent=2))
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    w = doc["x-window"]
    out = args.out / f"result-v0-{w['from'][:10]}_{w['to'][:10]}.json"
    out.write_text(json.dumps(doc, indent=2))
    summary["out"] = str(out)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
