#!/usr/bin/env python3
"""The inference-deals pack's evaluator: a Mesh node's come-through terms over
its own paid exchanges, decided from its sealed records with no model.

packs/inference-deals/pack-source.yaml names this module as its `evaluator`
(scripts/pack_compile.py EVALUATORS); scripts/report.sh runs it in place of a
judge. Steven's rulings, 2026-10-29: fully deterministic, no LLM call (ops
c18ddbd8); terms 1-3, all must_have, over 12 months in whole closed periods
tied to AAC #315 `period_policy` (ops f4f269eb).

    inference_deals.py --profile NAME --spec packs/inference-deals/compiled/compiled.json \\
        --date YYYY-MM-DD --generated-at TS --out DIR [--period-policy FILE] [--now TIME] \\
        [--capsulectl PATH] [--receipts FILE]

Subject bundles (capsule-viewer#353; agent-action-capsule Evidence Result
§4.5, agent-action-capsule#674). With --receipts FILE, the list
scripts/report.sh forwards to the page builder ({"exchange_capsule_id",
"receipt": <bundle JSON text>} or {"exchange_capsule_id", "held": true}), every
claim of a deal whose own exchange record's capsule id has a receipt carries
`subject_bundle`: that receipt's bundle digest (SHA-256 of the RFC 8785 JCS
form of the bundle with `countersignatures` left out), computed here, before
the Result is sealed. The page then refuses to show a receipt filed under the
deal that is not that one. A held entry carries no bundle to hash and names
none; a deal whose exchange records have two different receipts names none
(the evaluator never picks one). The member is display-only: no verdict, grade
or count reads it. Without --receipts no claim carries it.

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
    settlement-records-00): terms, payer_observed, payee_observed, delivered;
  - an adjudication record: `...["adjudication_received"]` (or
    `adjudication_issued`, or a referee's verdict record's `adjudication`
    block), naming the judged halves by capsule id.

Pack digest (capsules-plugin#271). The Mesh plugin's exchange records cite the
agreement's `inference_deals_digest` (the pack's `pack_source_digest`). A deal
whose records cite another digest than the compiled pack this evaluator runs
is not judged: every row is not_evaluable with the claim member `x-reason`
`inference_deals_digest_mismatch` (not a token AAC registers, so it stays an `x-` member), naming both digests, counted in
`x-window.digest_mismatch_deals`. The sealed Result carries that reason, so it
is signed by whoever seals it. Records citing none are judged as before.

Window. The anchor is the last period boundary (epoch + k * length_s) at or
before the end of --date. The window is every whole period that ends at or
before the anchor and starts no earlier than `months` calendar months before
it, so it moves only when a period closes. A record belongs to a period by its
own `timestamp`: the node seals a record when its stream commits it, and the
capsule's time is the one a republished book still carries, unlike the book's
own append time. A record after the anchor is not read at all, and a deal
belongs to the window by its earliest record. An anchor later than now
(`--now`, default the wall clock) is refused: that period has not closed.
Only the policy's `epoch` and `length_s` are used. Its floor and suppression
protect period counts a node serves to others (AAC inference-service history
§6.2); this Result lists each deal as its own claim, so a floor on its tallies
would hide nothing, and none is applied.

Deals. A deal is one exchange_id that a lifecycle observation names in this
book. An exchange no observation names ran free or with payments off
(`settlement: null`): it is not a deal, never judged and never counted. A deal
whose `counterparty_class` records all say `shop_preauth` is not counted; a
deal with no such member is counted and tallied as lacking it, and one whose
records disagree (AAC Standard History §7) is counted, tallied as lacking it
and as conflicting. Every count the Result carries is in its
`x-window`; amounts, node and peer ids, counterparties and payment hashes
never are.

Terms (rows), each met / not_met / not_evaluable, or out_of_scope when the deal
did not carry it (the node bought: term 1; it provided: terms 2 and 3):
  1. paid_as_agreed, from the payer's observations, in the order the plugin's
     own settlement state uses (evidence_panes/settlement.rs), except that a
     settlement matching no invoice (`unmatched_settlement`) is counted in
     `x-window` and set aside, never graded against the deal: no invoice is
     `terms_only`; every invoice settled by the wallet is met when each
     settlement's amount equals its invoice's and not_met otherwise (a missing
     amount is `amount_missing`); no `final_accounted` is
     `outcome_not_reported`; else `no_settlement_seen`. Every state but a
     settled one is not_evaluable.
  2. served_as_agreed: the provider's served exchange record, and its
     invoices settled by its wallet, by the same rules (an unpaid invoice is
     `outcome_not_reported`).
  3. served_named_model: the accepted terms carry the model only inside
     `terms_digest`, so no Mesh record lets a verifier recompute it. The row
     reads "provider states" (`x-reading: provider_states`): met when every
     served record of the deal names the same requested and resolved model.
     A deal a referee already adjudicated is not judged again (Steven, ops
     c18ddbd8): the row cites the sealed adjudication record and carries its
     verdict (`x-reading: adjudicated`), read for this node as the plugin's
     own `ruling_about` reads it: corroborated, or contradicted naming the
     other half, is met; contradicted naming this node is not_met; anything
     else is not_evaluable. It is counted in `x-window.adjudicated_deals`.

One node is never both sides of one exchange: a deal whose observations or
exchange records name both sides is `conflicting_roles`, every row
not_evaluable.

Grades: `countersigned` when, for every settled payment of the row, the book
also holds the counterparty's leg of it (a `settlement` leg under a key that
is not this node's, joined by payment hash and terms_ref to this node's own
leg under its own key) and that leg's own signature verifies under the
reader's trusted keys, else `self-attested`. The key is read from the record
(`key_id`). Legs are checked in read_book (below).

Signatures (evidencebook-skills#187). Every book record that holds a Mesh
capsule is authenticated with `capsulectl verify` under the READER's trusted
keys before a term reads it (read_book): the record's signature must verify
under its `key_id`, and that key must be one the reader trusts. This says the
record was sealed into this book by a key the reader trusts; it does not check
the Mesh capsule inside it, which is the counterparty's signature on a leg; that
is checked separately (Leg signatures, below). A deal with a record that does not verify is not judged: every row is
not_evaluable, with the claim member `reason` `capsule_signature_did_not_verify` (the signature
or identity was refused) or `capsule_signer_not_trusted` (the signer is not among
the reader's trusted keys, which is not a finding of tampering); the first wins
when both occur. Only a record the window reads counts: one whose own time is
after the window end is not read, as `collect` does not read it. Such a record never gives a deal its window time, a side's key
or a counterparty class, and never creates a deal. A record that cannot be
attributed to a counted deal (a leg, or a record of a deal the verified records
do not establish) only adds to `x-window.unverified_capsules`, and a leg held by
a record that does not verify never makes a payment countersigned. The counts
are in `x-window` (`signature_unverified_deals`, `signer_untrusted_deals`,
`unverified_capsules`, absent when zero) and in `states`, so a run with
unavailable deals never reads as clean. One record that fails to verify never
stops the run; a capsulectl that cannot run at all still does (exit 2).

Leg signatures (evidencebook-skills#207). A settlement leg is a bare Mesh capsule
with its own inline signature and `key_id`: the signature of the side that
sealed it. read_book checks each leg with `capsulectl verify --capsule` on the
leg itself, under the READER's trusted keys, after the book record holding it
verified. A leg whose own signature does not verify (altered, or no signature)
or whose signer the reader does not trust never makes a payment countersigned.
It does not make the deal unavailable: the node's own records still decide the
verdict. The row's grade is `self-attested` and its claim carries `reason`
`counterparty_leg_signature_did_not_verify` or `counterparty_leg_signer_not_trusted`
(the first when both occur), and `x-window` counts the rows
(`leg_signature_unverified_rows`, `leg_signer_untrusted_rows`, absent when zero).
Only the COUNTERPARTY's leg is held to this: a leg under this node's own key sits
in a record the reader already verified. A row with no leg of the other side in
the book carries no `reason`: nothing failed. A deal one of whose records
failed its own check shows that reason alone.
"""
import argparse
import calendar
import datetime
import hashlib
import json
import pathlib
import sys
import tempfile

import rfc8785

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from capsulectl_calls import (CapsuleDoesNotVerify, EvidenceUnavailable, UntrustedSigner,  # noqa: E402
                              list_capsules, payload, verify, verify_file)
from result_v0 import build_result_v0_for_day, report_title  # noqa: E402
from rollup import RollupError  # noqa: E402

OBSERVATION = "x-mesh-settlement-v1"
EXCHANGE = "x-mesh-poc-v1"
# An exchange record's `role`, as the side of the deal it puts this node on.
EXCHANGE_ROLES = {"served": "provider", "requested": "payer"}

# The member an exchange record cites its agreement's pack digest in, and the
# reason a deal that cites another pack is not judged.
PACK_DIGEST_MEMBER = "inference_deals_digest"
MISMATCH = "inference_deals_digest_mismatch"

# Why a capsule or a deal is evidence unavailable before any term is read: the
# capsule's signature did not verify (possible tampering), or its signer is not
# among the reader's trusted keys (trust not established, no claim of tampering).
UNVERIFIED = "capsule_signature_did_not_verify"
UNTRUSTED = "capsule_signer_not_trusted"

# Why a row is `self-attested` though the book holds the other side's leg of
# every payment: that leg's own signature did not verify, or its signer is not
# among the reader's trusted keys. Carried in the claim member `reason` (AAC ER 4.4).
LEG_UNVERIFIED = "counterparty_leg_signature_did_not_verify"
LEG_UNTRUSTED = "counterparty_leg_signer_not_trusted"
LEG_REASONS = {UNVERIFIED: LEG_UNVERIFIED, UNTRUSTED: LEG_UNTRUSTED}

PAID = "come_through.paid_as_agreed"
SERVED = "come_through.served_as_agreed"
MODEL = "come_through.served_named_model"
FOLDS = {
    "inference_deals.paid_as_agreed": PAID,
    "inference_deals.served_as_agreed": SERVED,
    "inference_deals.served_named_model": MODEL,
}

# A sealed adjudication: this node's record of a verdict delivered to it or
# issued by it, or a referee's verdict record (capsules-plugin producer/capsule.rs).
ADJUDICATION_BLOCKS = ("adjudication_received", "adjudication_issued", "adjudication")

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
    for block in ADJUDICATION_BLOCKS:
        if isinstance(ca.get(block), dict):
            return "adjudication", ca[block]
    return None, None


def _adjudicated_halves(member):
    """The judged halves' capsule ids an adjudication record names."""
    halves = [h for h in (member.get("halves") or []) if isinstance(h, str)]
    halves += [member[k] for k in ("held_half_capsule_id", "half_a_capsule_id", "half_b_capsule_id")
               if isinstance(member.get(k), str)]
    return set(halves)


class Deal:
    def __init__(self, exchange_id):
        self.exchange_id = exchange_id
        self.observations = []   # (book capsule id, member)
        self.exchanges = []      # (book capsule id, body, member) of this node's exchange records
        self.adjudications = []  # (book capsule id, member)
        self.first = None
        self.records = []        # every capsule of this deal, as (book capsule id, body)
        self.unverified = {}     # book capsule id -> reason, for this deal's records that did not verify

    def add(self, cid, body, when):
        self.records.append((cid, body))
        self.first = when if self.first is None else min(self.first, when)

    @property
    def roles(self):
        roles = {m.get("observed_by") for _, m in self.observations}
        roles |= {EXCHANGE_ROLES.get(m.get("role"), m.get("role")) for _, _, m in self.exchanges}
        return roles


def collect(records, start, to):
    """records: [(book capsule id, payload)] in book order -> (deals by
    exchange id, legs, own key ids). Only records sealed before `to` are read;
    a deal is kept when its earliest record is in [start, to)."""
    deals, legs, own_keys = {}, [], set()
    exchanges, adjudications = {}, []
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
        if kind == "adjudication":
            adjudications.append((cid, member))
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
            deal.exchanges.append((cid, body, member))
    for deal in deals.values():
        halves = {body.get("capsule_id") for _, body, _ in deal.exchanges}
        deal.adjudications = [(cid, m) for cid, m in adjudications if _adjudicated_halves(m) & halves]
    kept = {x: d for x, d in deals.items() if start <= d.first < to}
    return kept, legs, own_keys


def _after_window(body, to):
    """Whether an untrusted record's own time says it is after the window, so
    `collect` would not have read it either. A time that does not read is not."""
    try:
        return _time(body.get("timestamp")) >= to
    except (AttributeError, ValueError):
        return False


def _attribute_unverified(deals, unverified_records):
    """Mark the deals that records which did not verify belong to. `unverified_records`:
    [(book capsule id, payload, reason)]. The payload is untrusted: read it only
    with type checks that never raise, and use it only to withhold a judgement,
    never to add a deal or give one evidence. A record that names no counted
    deal marks none."""
    for cid, body, reason in unverified_records:
        try:
            kind, member = _kind(body)
            if kind in ("observation", "exchange"):
                source = member if kind == "observation" else member.get("serving_provenance")
                xid = source.get("exchange_id") if isinstance(source, dict) else None
                targets = [deals[xid]] if isinstance(xid, str) and xid in deals else []
            elif kind == "adjudication":
                halves = _adjudicated_halves(member)
                targets = [d for d in deals.values()
                           if halves & {b.get("capsule_id") for _, b, _ in d.exchanges}]
            else:
                continue  # a leg names no deal; it only drops out of the book (build_result)
        except (AttributeError, TypeError):
            continue  # not shaped as any Mesh record, so it names no deal
        for deal in targets:
            # The signature failure is the stronger reading when one deal has both.
            if deal.unverified.get(cid) != UNVERIFIED:
                deal.unverified[cid] = reason


def _join(invoice, settlement):
    if invoice.get("payment_hash") and settlement.get("payment_hash"):
        return invoice["payment_hash"] == settlement["payment_hash"]
    return invoice.get("segment") == settlement.get("segment")


def _amount(m):
    v = m.get("amount_msat")
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def payment_state(observations, side):
    """(verdict, state, unmatched settlement count, settled payment hashes) over
    one side's observations of one deal (evidence_panes/settlement.rs order,
    with an unmatched settlement set aside rather than grading the deal)."""
    invoices = [m for _, m in observations if m.get("phase") in INVOICE_PHASES]
    settlements = [m for _, m in observations if m.get("phase") in SETTLEMENT_PHASES
                   and m.get("source") == "wallet_reported"]
    unmatched = [s for s in settlements if not any(_join(i, s) for i in invoices)]
    if not invoices:
        return "not_evaluable", "terms_only", len(unmatched), set()
    paired = [(i, [s for s in settlements if _join(i, s)]) for i in invoices]
    if all(found for _, found in paired):
        if any(_amount(m) is None for i, found in paired for m in [i, *found]):
            return "not_evaluable", "amount_missing", len(unmatched), set()
        ok = all(_amount(s) == _amount(i) for i, found in paired for s in found)
        settled = [s for _, found in paired for s in found]
        hashes = {s.get("payment_hash") for s in settled if s.get("payment_hash")}
        if any(not s.get("payment_hash") for s in settled):
            # A settlement joined to its invoice by segment, with no hash, has
            # no counterparty leg to name it: None marks the row as one that
            # cannot be countersigned (_countersigned).
            hashes = hashes | {None}
        return ("met" if ok else "not_met"), "settled", len(unmatched), hashes
    if side == "provider" or not any(m.get("phase") == "final_accounted" for _, m in observations):
        return "not_evaluable", "outcome_not_reported", len(unmatched), set()
    return "not_evaluable", "no_settlement_seen", len(unmatched), set()


def _well_formed_leg(body, m):
    """Whether a leg's members the join reads have the types it expects. A leg
    that did not verify is untrusted input: one that does not read this way can
    match no payment, so it is left out rather than allowed to stop the run."""
    ref = m.get("payment_ref")
    return (isinstance(body, dict) and isinstance(m, dict)
            and all(isinstance(x, str) for x in (body.get("capsule_id"), m.get("terms_ref"), m.get("leg"),
                                                 m.get("sealer_role")) if x is not None)
            and (ref is None or (isinstance(ref, dict) and isinstance(ref.get("value"), (str, type(None)))))
            and isinstance(body.get("key_id", ""), (str, type(None))))


def _countersigned(side, hashes, legs, own_keys, bad_legs=()):
    """(countersigned, reason, cited ids): whether, for EVERY one of these
    payments, the book holds the counterparty's leg beside this node's own: on
    a payer node, the payee's payee_observed leg naming one of the payer's own
    terms legs; on a provider node, the payer's terms leg its own payee_observed
    leg names. A leg is this node's only under one of its own keys, and the
    counterparty's only under a key that is present and not one of them.

    `bad_legs` are legs whose own signature did not verify, as (book capsule
    id, body, member, reason). They are never joined as evidence. A payment
    with no verified pair but a pair that a bad COUNTERPARTY leg would complete
    is the reason's (a bad leg with no key_id at all counts as the
    counterparty's, since nothing says it is this node's); the reason is
    UNVERIFIED's when both kinds occur, and the cited ids are those legs. A
    node's own leg is held by a book record this reader already verified, so
    its own signature is not asked for again."""
    if not hashes or None in hashes:
        return False, None, []
    def own(body):
        return body.get("key_id") in own_keys
    def foreign(body, reason):
        key = body.get("key_id")
        return (bool(key) and key not in own_keys) or (reason is not None and not key)
    def pairs(candidates):
        """{payment hash: [(reason, cited leg id)] for each pair found}"""
        by_id = {}
        for cid, body, m, reason in candidates:
            by_id.setdefault(body.get("capsule_id"), []).append((cid, body, m, reason))
        found = {}
        for cid, body, m, reason in candidates:
            h = (m.get("payment_ref") or {}).get("value")
            if m.get("leg") != "payee_observed" or m.get("sealer_role") != "payee" or h not in hashes:
                continue
            for tcid, tbody, tm, treason in by_id.get(m.get("terms_ref"), []):
                if tm.get("leg") != "terms" or tm.get("sealer_role") != "payer":
                    continue
                if side == "payer" and foreign(body, reason) and own(tbody):
                    found.setdefault(h, []).append((reason, cid))  # the counterparty's leg is the payee_observed one
                if side == "provider" and foreign(tbody, treason) and own(body):
                    found.setdefault(h, []).append((treason, tcid))  # the counterparty's leg is the terms one
        return found
    bad_legs = [x for x in bad_legs if _well_formed_leg(x[1], x[2])]  # before any member is read
    # A bad leg under one of this node's own keys is joined like any other.
    good = [(cid, b, m, None) for cid, b, m in legs] + [(c, b, m, None) for c, b, m, _ in bad_legs if own(b)]
    bad = [x for x in bad_legs if not own(x[1])]
    verified = pairs(good)
    candidates = pairs(good + bad)
    reasons, cited = set(), set()
    for h in hashes:
        if h in verified:
            continue
        if h not in candidates:
            return False, None, []  # no pair at all: the other side's leg is missing
        failed = [(r, cid) for r, cid in candidates[h] if r]
        reasons |= {r for r, _ in failed}
        cited |= {cid for _, cid in failed}
    if reasons:
        return False, UNVERIFIED if UNVERIFIED in reasons else UNTRUSTED, sorted(cited)
    return True, None, []


def _cited(deal, legs, hashes):
    """The book capsule ids a row cites: the deal's own records and the legs
    of its payments."""
    ids = [cid for cid, _ in deal.records]
    hashes = hashes - {None}
    leg_ids = {body.get("capsule_id") for _, body, m in legs
               if (m.get("payment_ref") or {}).get("value") in hashes}
    terms = {m.get("terms_ref") for _, body, m in legs if body.get("capsule_id") in leg_ids}
    ids += [cid for cid, body, _ in legs if body.get("capsule_id") in leg_ids | terms]
    return sorted(set(ids))


def ruling_about(verdict, half_node_ids, node_id):
    """The bucket a sealed verdict puts `node_id` in, when it is one of the two
    judged halves' nodes, else None: the plugin's own reading
    (capsules-plugin verdict_counts.rs `ruling_about`). A contradiction naming
    the OTHER half means the referee's answer matched this one, so it is
    corroborated for this node."""
    if len(half_node_ids) != 2 or not node_id or node_id not in half_node_ids:
        return None  # the plugin's halves are exactly two ([&str; 2])
    if isinstance(verdict, str) and verdict.startswith("contradicted:"):
        named = verdict[len("contradicted:"):]
        if named == node_id:
            return "contradicted"
        return "corroborated" if named in half_node_ids else None
    return verdict if verdict in ("corroborated", "inconclusive", "not_comparable") else None


def _adjudication(deal, own_node):
    """(verdict, x-adjudication, cited ids) from the deal's sealed adjudication
    records, read for this node as ruling_about reads them, or None when it has
    none. A record that puts this node in no bucket, or records that disagree,
    decide nothing."""
    if not deal.adjudications:
        return None
    readings = set()
    for _, m in deal.adjudications:
        halves = [h for h in (m.get("half_node_ids") or []) if isinstance(h, str)]
        readings.add(ruling_about(m.get("verdict"), halves, own_node) or "no_ruling")
    cited = sorted({cid for cid, _ in deal.adjudications} | {cid for cid, _, _ in deal.exchanges})
    if len(readings) != 1:
        return "not_evaluable", "conflicting", cited
    reading = readings.pop()
    verdict = {"corroborated": "met", "contradicted": "not_met"}.get(reading, "not_evaluable")
    return verdict, reading, cited


def cited_pack_digests(deal):
    """The inference-deals digests the deal's exchange records cite (the
    Mesh plugin's `x-mesh-poc-v1.inference_deals_digest`, beside `acceptance`,
    capsules-plugin#271), sorted. A record that cites none adds none."""
    return sorted({m[PACK_DIGEST_MEMBER] if isinstance(m[PACK_DIGEST_MEMBER], str) else repr(m[PACK_DIGEST_MEMBER])
                   for _, _, m in deal.exchanges if PACK_DIGEST_MEMBER in m})


def judge_deal(deal, legs, own_keys, pack_digest=None, bad_legs=()):
    """{criterion: verdict}, {criterion: extras}, {criterion: cited ids}, the
    deal's state, and its unmatched settlement count. A deal whose records
    cite an inference-deals digest other than `pack_digest` (the pack this
    evaluator runs) is not judged: every row is not_evaluable with the reason
    `inference_deals_digest_mismatch`, which the sealed Result then carries."""
    verdicts = {PAID: "out_of_scope", SERVED: "out_of_scope", MODEL: "out_of_scope"}
    extras, cited = {}, {}
    if deal.unverified:
        # A record this reader cannot authenticate decides nothing, not even
        # which pack digest the deal cites.
        reason = UNVERIFIED if UNVERIFIED in deal.unverified.values() else UNTRUSTED
        for c in verdicts:
            verdicts[c] = "not_evaluable"
            extras[c] = {"x-state": reason, "reason": reason,
                         "x-unverified-capsules": sorted(deal.unverified)}
            cited[c] = [cid for cid, _ in deal.records] + sorted(deal.unverified)
        return verdicts, extras, cited, reason, 0
    cites = cited_pack_digests(deal)
    if pack_digest is not None and any(d != pack_digest for d in cites):
        for c in verdicts:
            verdicts[c] = "not_evaluable"
            extras[c] = {"x-state": MISMATCH, "x-reason": MISMATCH,
                         "x-cited-inference-deals-digests": cites, "x-pack-digest": pack_digest}
            cited[c] = [cid for cid, _ in deal.records]
        return verdicts, extras, cited, MISMATCH, 0
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
    signed, why, legs_cited = False, None, []
    if verdict in ("met", "not_met"):
        signed, why, legs_cited = _countersigned(side, hashes, legs, own_keys, bad_legs)
    grade = "countersigned" if signed else "self-attested"
    grade_extras = {"grade": grade, "x-state": state}
    if why:
        # The other side's leg is in the book but its own signature does not
        # check out: say why the row is not countersigned, and cite the leg.
        grade_extras["reason"] = LEG_REASONS[why]
    if side == "payer":
        verdicts[PAID] = verdict
        extras[PAID] = dict(grade_extras)
        cited[PAID] = sorted(set(_cited(deal, legs, hashes) + legs_cited))
        return verdicts, extras, cited, state, unmatched
    served = [(cid, body, m) for cid, body, m in deal.exchanges if m.get("role") == "served"]
    if not served:
        verdicts[SERVED] = verdicts[MODEL] = "not_evaluable"
        extras[SERVED] = {"x-state": "no_served_record"}
        extras[MODEL] = {"x-state": "no_served_record"}
        cited[SERVED] = cited[MODEL] = _cited(deal, legs, hashes)
        return verdicts, extras, cited, state, unmatched
    verdicts[SERVED] = verdict
    extras[SERVED] = dict(grade_extras)
    cited[SERVED] = sorted(set(_cited(deal, legs, hashes) + legs_cited))
    own_nodes = {(m.get("serving_provenance") or {}).get("served_by_node_id") for _, _, m in served}
    adjudicated = _adjudication(deal, own_nodes.pop() if len(own_nodes) == 1 else None)
    if adjudicated is not None:
        verdicts[MODEL], reading, cited[MODEL] = adjudicated
        extras[MODEL] = {"x-reading": "adjudicated", "x-adjudication": reading}
        return verdicts, extras, cited, state, unmatched
    answers = set()
    for _, body, _ in served:
        invocation = _attestation(body).get("invocation") or {}
        requested, resolved = invocation.get("requested_model_id"), invocation.get("resolved_model_id")
        if isinstance(requested, str) and requested and isinstance(resolved, str) and resolved:
            answers.add("met" if requested == resolved else "not_met")
        else:
            answers.add("not_evaluable")
    # Served records that disagree decide nothing.
    verdicts[MODEL] = answers.pop() if len(answers) == 1 else "not_evaluable"
    extras[MODEL] = {"x-reading": "provider_states"}
    cited[MODEL] = sorted(cid for cid, _, _ in served)
    return verdicts, extras, cited, state, unmatched


def counterparty_class(deal):
    """(class, conflicting): the value every record of the deal that carries
    `counterparty_class` agrees on, or None when none carries it or they
    disagree (AAC Standard History §7), with conflicting True for the latter."""
    values = {body["counterparty_class"] for _, body in deal.records if "counterparty_class" in body}
    if len(values) == 1:
        return values.pop(), False
    return None, len(values) > 1


def bundle_digest(bundle):
    """The Evidence Bundle draft's bundle digest, as Evidence Result §4.5's
    `subject_bundle` names it: SHA-256 of the JCS form of the bundle with
    `countersignatures` left out, 64 lowercase hex characters (agent-action-
    capsule python/agent_action_capsule/bundle.py `bundle_digest`)."""
    body = {k: v for k, v in bundle.items() if k != "countersignatures"}
    return hashlib.sha256(rfc8785.dumps(body)).hexdigest()


def receipt_digests(entries):
    """{exchange record capsule id: bundle digest} from report.sh's receipts
    list. A held entry carries no bundle and is skipped. An entry this cannot
    read is a DealsError: the Result would otherwise name no bundle for a deal
    whose receipt the page then carries."""
    if not isinstance(entries, list):
        raise DealsError("--receipts: not a JSON list")
    out = {}
    for i, entry in enumerate(entries):
        xid = entry.get("exchange_capsule_id") if isinstance(entry, dict) else None
        if not isinstance(xid, str) or not xid:
            raise DealsError(f"--receipts: entry {i} has no exchange_capsule_id")
        if entry.get("held") is True and "receipt" not in entry:
            continue
        text = entry.get("receipt")
        try:
            bundle = json.loads(text) if isinstance(text, str) else None
        except ValueError:
            bundle = None
        if not isinstance(bundle, dict):
            raise DealsError(f"--receipts: entry {i} ({xid}) has no receipt bundle JSON object")
        digest = bundle_digest(bundle)
        if out.get(xid, digest) != digest:
            raise DealsError(f"--receipts: two different receipts for exchange record {xid}")
        out[xid] = digest
    return out


def _subject_bundle(deal, receipts):
    """The digest of the one receipt of the deal's own exchange records, or None."""
    digests = {receipts[cid] for cid in (body.get("capsule_id") for _, body, _ in deal.exchanges)
               if isinstance(cid, str) and cid in receipts}
    return digests.pop() if len(digests) == 1 else None


def build_result(records, compiled, date, generated_at, policy=None, unverified=None, leg_unverified=None,
                 receipts=None):
    """Pure: the book's records -> (Result v0 document, summary). No I/O.
    `unverified` maps the book capsule ids that did not verify to UNVERIFIED or
    UNTRUSTED; those records are never read as evidence (see the module docstring).
    `leg_unverified` maps the book capsule ids of settlement legs whose OWN
    signature did not verify (the book record holding them did) to the same two
    reasons; such a leg never makes a payment countersigned.
    `receipts` maps an exchange record's capsule id to its receipt's bundle
    digest (receipt_digests); each claim of a deal with one is given
    `subject_bundle` (see Subject bundles in the module docstring)."""
    unverified = unverified or {}
    leg_unverified = leg_unverified or {}
    bad = [(cid, body, unverified[cid]) for cid, body in records if cid in unverified]
    records = [(cid, body) for cid, body in records if cid not in unverified]
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
    bad_legs = [(cid, body, m, leg_unverified[cid]) for cid, body, m in legs if cid in leg_unverified]
    legs = [leg for leg in legs if leg[0] not in leg_unverified]
    bad = [b for b in bad if not _after_window(b[1], to)]  # collect would not have read it
    _attribute_unverified(deals, bad)

    ordered = sorted(deals.values(), key=lambda d: (d.first, d.exchange_id))
    rollups, sources, extras_by_case, subjects = [], {}, {}, {}
    counts = {"deals_counted": 0, "not_counted_shop_preauth": 0, "class_missing": 0,
              "class_conflicting": 0, "unmatched_settlements": 0, "adjudicated_deals": 0, "states": {},
              "leg_rows": {}}
    n = 0
    for deal in ordered:
        cls, conflicting = counterparty_class(deal)
        if cls == "shop_preauth":
            counts["not_counted_shop_preauth"] += 1
            continue
        if cls is None:
            counts["class_missing"] += 1
            counts["class_conflicting"] += int(conflicting)
        verdicts, extras, cited, state, unmatched = judge_deal(deal, legs, own_keys, compiled.get("pack_source_digest"), bad_legs)
        counts["unmatched_settlements"] += unmatched
        counts["adjudicated_deals"] += int((extras.get(MODEL) or {}).get("x-reading") == "adjudicated")
        counts["states"][state] = counts["states"].get(state, 0) + 1
        for e in extras.values():
            if e.get("reason") in LEG_REASONS.values():
                counts["leg_rows"][e["reason"]] = counts["leg_rows"].get(e["reason"], 0) + 1
        n += 1
        case_id = f"d{n}"
        tiers = {c: "recomputed" for c in verdicts}
        rollups.append((case_id, verdicts, {c: cited.get(c) for c in verdicts}, tiers))
        extras_by_case[case_id] = extras
        if receipts:
            subject = _subject_bundle(deal, receipts)
            if subject is not None:
                subjects[case_id] = subject
        sources[case_id] = {}
    counts["deals_counted"] = n
    if not rollups:
        if unverified:
            raise DealsError(f"no deal could be checked in the window {_iso(start)} to {_iso(to)}: "
                             f"{len(unverified)} book record(s) did not verify under the trusted keys and "
                             "create no deal (this does not mean the node made no deals); with no trusted "
                             "keys, add the node's keys to the profile's trusted_keys")
        raise DealsError(f"no counted deal in the window {_iso(start)} to {_iso(to)}: nothing to report")

    all_criteria = tuple(c["id"] for c in compiled["clauses"])
    label = f"{start.date().isoformat()} to {(to - datetime.timedelta(seconds=1)).date().isoformat()}"
    try:
        doc = build_result_v0_for_day(label, rollups, generated_at, all_criteria, compiled["contract_ref"],
                                      allow_out_of_scope=True, claim_extras=extras_by_case)
    except RollupError as e:
        raise DealsError(str(e)) from e
    doc["view"]["title"] = report_title(compiled, label)
    # §4.5's `subject_bundle` is a defined claim member, not an `x-` one, so it
    # is set here rather than through claim_extras; every claim of a deal gets
    # the same value.
    for claim in doc["claims"]:
        subject = subjects.get(claim["id"].split("::", 1)[0])
        if subject is not None:
            claim["subject_bundle"] = {"digest_alg": "SHA-256", "digest": subject}
    doc["x-window"] = {
        "from": _iso(start), "to": _iso(to), "periods": periods, "months": window["months"],
        "period_policy_digest": policy_digest(policy),
        "deals_counted": counts["deals_counted"],
        "not_counted_shop_preauth": counts["not_counted_shop_preauth"],
        "class_missing": counts["class_missing"],
        "class_conflicting": counts["class_conflicting"],
        "unmatched_settlements": counts["unmatched_settlements"],
        "adjudicated_deals": counts["adjudicated_deals"],
        "peer_book": "not_available",
    }
    if counts["states"].get(MISMATCH):  # absent otherwise, so an unaffected Result is byte-identical
        doc["x-window"]["digest_mismatch_deals"] = counts["states"][MISMATCH]
    if bad:
        doc["x-window"]["unverified_capsules"] = len(bad)
    for state, key in ((UNVERIFIED, "signature_unverified_deals"), (UNTRUSTED, "signer_untrusted_deals")):
        if counts["states"].get(state):
            doc["x-window"][key] = counts["states"][state]
    for reason, key in ((LEG_UNVERIFIED, "leg_signature_unverified_rows"), (LEG_UNTRUSTED, "leg_signer_untrusted_rows")):
        if counts["leg_rows"].get(reason):  # absent when zero, so an unaffected Result is byte-identical
            doc["x-window"][key] = counts["leg_rows"][reason]
    summary = {"contract_ref": compiled["contract_ref"], "window": doc["x-window"], "states": counts["states"]}
    return doc, summary


def read_book(capsulectl, profile):
    """(records, unverified, leg_unverified): every book record as (capsule id,
    payload); the ids of the Mesh capsules among them that did not verify, each
    with its reason; and the ids of the settlement legs among the verified ones
    whose OWN signature did not verify (a leg is a bare Mesh capsule with its
    inline signature and key_id: the counterparty's signature, which the book
    record's does not cover), each with its reason. Only a capsule `_kind`
    reads is verified (a sealed Result or another pack's case in the same book
    is not this pack's evidence); a capsulectl that cannot get a capsule at all
    still raises EvidenceUnavailable."""
    records, unverified, leg_unverified = [], {}, {}
    with tempfile.TemporaryDirectory() as work:
        for e in list_capsules(capsulectl, profile):
            cid = e["capsule_id"]
            body = payload(capsulectl, profile, cid)
            records.append((cid, body))
            try:
                try:
                    mesh = _kind(body)[0] is not None
                except (AttributeError, TypeError):
                    mesh = True  # unreadable as a Mesh record: verify it, so a bad one is set aside
                if mesh:
                    verify(capsulectl, profile, cid, work)
            except UntrustedSigner:
                unverified[cid] = UNTRUSTED
            except CapsuleDoesNotVerify:
                unverified[cid] = UNVERIFIED
            else:
                if mesh and _kind(body)[0] == "leg":
                    leg_file = pathlib.Path(work) / f"leg-{cid}.json"
                    leg_file.write_text(json.dumps(body, ensure_ascii=False))
                    try:
                        verify_file(capsulectl, profile, leg_file, f"leg {cid}")
                    except UntrustedSigner:
                        leg_unverified[cid] = UNTRUSTED
                    except CapsuleDoesNotVerify:
                        leg_unverified[cid] = UNVERIFIED
    return records, unverified, leg_unverified


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
    ap.add_argument("--now", help="RFC 3339 UTC time the anchor may not pass (default: the wall clock); "
                                  "a test replaying recorded fixtures sets a later one")
    ap.add_argument("--receipts", type=pathlib.Path,
                    help="report.sh's receipts list: each claim of a deal with a receipt names it "
                         "as subject_bundle (see Subject bundles above)")
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
        date = datetime.date.fromisoformat(args.date)
        now = _time(args.now) if args.now else datetime.datetime.now(datetime.timezone.utc)
        _, anchor, _ = window_bounds(date, compiled["window"]["months"], policy or compiled["window"]["period_policy"])
        if anchor > now:
            raise DealsError(f"the window would end at {_iso(anchor)}, after now ({_iso(now)}): "
                             "that period has not closed")
        receipts = receipt_digests(json.loads(args.receipts.read_text())) if args.receipts else None
        records, unverified, leg_unverified = read_book(args.capsulectl, args.profile)
        doc, summary = build_result(records, compiled, date, args.generated_at, policy, unverified, leg_unverified,
                                    receipts)
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
