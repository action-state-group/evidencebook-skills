"""The per-conversation facts Outcomes frame 5 ("Same customer in this report") draws,
as a pack-namespaced document-level `x-` member of a day's Result v0
(evidencebook-skills#89; Sherlock2's what answer, Buzz 3958de61).

    "x-airline-support-outcomes": {
      "subject_history": {
        "handle_scope": {"pack": ..., "tier": "operator", "salting": "per-pack"},   # operator tier only
        "conversations": {
          "<case_id>": {"request_label": ..., "usd_band": "e+1",
                        "halves": {"present": 4, "of": 4},
                        "customer_handle": "<hex>", "follow_up_of": "<case_id>"}}}}

Not AAC vocabulary: Result v0 section 8a admits `x-` members on the document and a verifier
ignores them; the name carries the pack id so no other pack reads it as its own.

Tiers (Sherlock2): `operator` carries all five fields. `shared` carries label, band and
halves only: a customer handle and `follow_up_of` each join conversations into one customer, so
both wait for per-share salting. The handle is HMAC-SHA256 under a producer-held salt over
(scope, customer id); the customer id and the salt are never written. A field the inputs do not
show is omitted, never guessed: no single customer id in the conversation means no handle.

`request_label` is one of REQUEST_LABELS, chosen from the tool calls the agent made, never
transcript text. `usd_band` is "e+N", the order of magnitude of the largest USD amount the
agent's own write actions moved. `follow_up_of` (a `references[]` cite of the case record) and
`halves` (from the bilateral records) are supplied by the caller and validated here.
"""
import hmac
import json
import math

from rollup import RollupError

TIERS = ("operator", "shared")
MIN_SALT_BYTES = 16

# Closed list, first match wins; "information request" is the fallback.
REQUEST_LABELS = (
    ("cancel_reservation", "cancellation"),
    ("update_reservation_flights", "flight change"),
    ("book_reservation", "new booking"),
    ("update_reservation_baggages", "baggage change"),
    ("update_reservation_passengers", "passenger change"),
    ("send_certificate", "compensation"),
    ("transfer_to_human_agents", "transfer to a person"),
)
FALLBACK_LABEL = "information request"
LABEL_VALUES = tuple(label for _, label in REQUEST_LABELS) + (FALLBACK_LABEL,)
_WRITE_TOOLS = ("cancel_reservation", "update_reservation_flights", "book_reservation",
                "update_reservation_baggages", "update_reservation_passengers")


def _calls(messages):
    for m in messages or []:
        for c in m.get("tool_calls") or []:
            yield c


def _payload(message):
    try:
        out = json.loads(message.get("content") or "null")
    except (json.JSONDecodeError, TypeError):
        return None
    return out if isinstance(out, dict) else None


def request_label(messages):
    names = {c.get("name") for c in _calls(messages)}
    for tool, label in REQUEST_LABELS:
        if tool in names:
            return label
    return FALLBACK_LABEL


def customer_id(messages):
    """The one user id the conversation looked up (get_user_details), or None when it
    shows none or several: a handle for an ambiguous customer would be a guess."""
    ids = {(c.get("arguments") or {}).get("user_id") for c in _calls(messages)
           if c.get("name") == "get_user_details"}
    ids.discard(None)
    return ids.pop() if len(ids) == 1 and next(iter(ids)) else None


def usd_band(messages):
    """"e+N" for the largest USD amount an agent write action moved (a certificate's
    amount, or a payment in a write result's payment_history), None when none shows
    an amount of at least 1."""
    calls = {c.get("id"): c for c in _calls(messages)}
    amounts = []
    for m in messages or []:
        call = calls.get(m.get("tool_call_id")) if m.get("role") == "tool" else None
        if not call:
            continue
        if call.get("name") == "send_certificate":
            amounts.append((call.get("arguments") or {}).get("amount"))
        elif call.get("name") in _WRITE_TOOLS:
            body = _payload(m) or {}
            amounts.extend(p.get("amount") for p in body.get("payment_history") or [] if isinstance(p, dict))
    usable = [abs(a) for a in amounts if isinstance(a, (int, float)) and not isinstance(a, bool) and abs(a) >= 1]
    return f"e+{int(math.floor(math.log10(max(usable))))}" if usable else None


def customer_handle(salt, scope, cust_id):
    if not isinstance(salt, (bytes, bytearray)) or len(salt) < MIN_SALT_BYTES:
        raise RollupError(f"the handle salt must be at least {MIN_SALT_BYTES} bytes")
    msg = json.dumps(scope, sort_keys=True, separators=(",", ":")).encode() + b"\0" + cust_id.encode()
    return hmac.new(bytes(salt), msg, "sha256").hexdigest()


def _check_halves(case_id, halves):
    ok = (isinstance(halves, dict) and set(halves) == {"present", "of"}
          and all(isinstance(halves[k], int) and not isinstance(halves[k], bool) for k in halves)
          and 0 <= halves["present"] <= halves["of"] and halves["of"] > 0)
    if not ok:
        raise RollupError(f"case {case_id!r}: halves must be {{present, of}} with 0 <= present <= of, of > 0")
    return {"present": halves["present"], "of": halves["of"]}


def build_subject_history(pack_id, tier, conversations, facts=None, salt=None, known_cases=None):
    """The extension member's value for the cases in `conversations` (case_id ->
    agent_interaction messages). `facts`: optional case_id -> {"follow_up_of": case_id,
    "halves": {"present", "of"}}. `salt` (bytes) is required at operator tier."""
    if tier not in TIERS:
        raise RollupError(f"subject tier must be one of {TIERS}, got {tier!r}")
    facts = facts or {}
    known_cases = set(known_cases if known_cases is not None else conversations)
    unknown = sorted(set(facts) - known_cases)
    if unknown:
        raise RollupError(f"subject facts name cases the report does not carry: {unknown!r}")
    scope = {"pack": pack_id, "tier": tier, "salting": "per-pack"}
    if tier == "operator" and salt is None:
        raise RollupError("operator tier needs a handle salt")
    out = {}
    for case_id, messages in sorted(conversations.items()):
        entry = {"request_label": request_label(messages)}
        band = usd_band(messages)
        if band:
            entry["usd_band"] = band
        fact = facts.get(case_id) or {}
        if "halves" in fact:
            entry["halves"] = _check_halves(case_id, fact["halves"])
        if tier == "operator":
            cid = customer_id(messages)
            if cid:
                entry["customer_handle"] = customer_handle(salt, scope, cid)
            earlier = fact.get("follow_up_of")
            if earlier is not None:
                if earlier == case_id or earlier not in known_cases:
                    raise RollupError(f"case {case_id!r}: follow_up_of {earlier!r} is not another case in this report")
                entry["follow_up_of"] = earlier
        out[case_id] = entry
    value = {"conversations": out}
    if tier == "operator":
        value["handle_scope"] = scope
    return {"subject_history": value}


def extension_name(pack_id):
    return f"x-{pack_id}"


def merge_subject_history(members):
    """Combine several days' extension values (one pack) into one; refuses mixed scopes
    and a case carried twice."""
    merged, scope = {}, None
    members = list(members)
    for member in members:
        sub = member["subject_history"]
        if scope is not None and sub.get("handle_scope") != scope.get("handle_scope"):
            raise RollupError("subject history members carry different handle scopes")
        scope = scope or sub
        dupes = sorted(set(merged) & set(sub["conversations"]))
        if dupes:
            raise RollupError(f"subject history carries case(s) twice: {dupes!r}")
        merged.update(sub["conversations"])
    for case_id, entry in merged.items():
        if entry.get("follow_up_of") not in (None, *[c for c in merged if c != case_id]):
            raise RollupError(f"case {case_id!r}: follow_up_of {entry['follow_up_of']!r} is not another case in this report")
    out = {"conversations": dict(sorted(merged.items()))}
    if "handle_scope" in scope:
        out["handle_scope"] = scope["handle_scope"]
    return {"subject_history": out}
