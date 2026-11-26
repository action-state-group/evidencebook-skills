# SPDX-License-Identifier: Apache-2.0
"""The demo's ARD entries and the buyer's lookup through a registry (ARD v0.91).

Each seller's own ``/.well-known/ard.json`` holds one entry (§4.2: ``identifier``, ``displayName``,
``type``, ``url``) whose discovery identifier is ``urn:air:<publisher>:print:<name>`` with a ``.test``
publisher domain, and whose ``trustManifest.identity`` names that domain (§4.5.1). Its
``trustManifest.attestations`` carries the commitment pointer the carrier spec defines
(agent-action-capsule ``spec/bindings/evidence-commitment-carriers-v0.md`` §5.1: the commitment's
profile, URI, media type and digest), and the offer sits in ``x-demo-offer``, a member of this demo
only. The buyer searches a registry (§5.3.2), treats each result only as a pointer, fetches the
seller's own entry from its origin, compares the two, checks that the identity names the publisher,
and fetches and verifies the commitment itself (§4: V0 to V4)."""
from __future__ import annotations

import hashlib
import json
import urllib.request
from typing import Any

import commitment as cm

PROFILE = "evidence-commitment/1"
WELL_KNOWN = "/.well-known/ard.json"
MEDIA = "application/json"
DESCRIPTION = "Answers evidence requests about its own records; verify the commitment, not this entry"


def publisher(name: str) -> str:
    """The seller's publisher domain: a ``.test`` name, reserved for testing (no DNS, no TLS)."""
    return f"{name}.ard-demo.test"


def identifier(name: str) -> str:
    return f"urn:air:{publisher(name)}:print:{name}"


def commitment_octets(doc: dict) -> bytes:
    """The commitment as served: the octets the digest is taken over (§4)."""
    return json.dumps(doc, sort_keys=True, indent=2).encode()


def entry(name: str, seller: dict, doc: dict, origin: str) -> dict:
    uri = f"{origin}/commitments/{name}.json"
    return {"identifier": identifier(name), "displayName": seller["label"], "type": MEDIA, "url": uri,
            "description": f"{seller['label']}: conference badges", "tags": ["evidence-request", "print", "badges"],
            "trustManifest": {"identity": publisher(name), "attestations": [{
                "type": PROFILE, "uri": uri, "mediaType": MEDIA,
                "digest": "sha256:" + hashlib.sha256(commitment_octets(doc)).hexdigest(), "description": DESCRIPTION}]},
            "x-demo-offer": {"item": seller["item"], "price_msat": seller["price_msat"], "currency": "msat"}}


def manifest(name: str, seller: dict, doc: dict, origin: str) -> dict:
    """One seller's own ``/.well-known/ard.json`` (§5.1)."""
    return {"entries": [entry(name, seller, doc, origin)]}


def _fetch(url: str, body: bytes | None = None) -> bytes:
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"} if body else {})
    with urllib.request.urlopen(req, timeout=10) as r:  # demo-local servers
        return r.read()


def search(registry_url: str, text: str) -> dict:
    """``POST /search`` with the item query only: the person's budget and deadline stay with the agent."""
    body = json.dumps({"query": {"text": text}, "federation": "none", "pageSize": 10}).encode()
    return json.loads(_fetch(registry_url, body))


def _publisher_of(ident: str) -> str:
    parts = ident.split(":")
    return parts[2] if len(parts) >= 4 and parts[:2] == ["urn", "air"] else ""


#: Why a seller's listing was refused, one plain sentence each for the person (evidencebook-skills#345, Sherlock2 on
#: #352): no file names, digests or error text. The technical detail goes to the item's ``detail`` and the buyer's own
#: records, never to her chat.
UNREACHABLE = "the seller's site could not be reached"
NOT_LISTED = "the seller's own site does not list the seller the registry points to"
UNREADABLE = "the seller's own listing could not be read"
DIFFERS = "the registry's copy of the listing differs from the seller's own"
WRONG_SITE = "the listing does not name the site it was published on"
NO_COMMITMENT = "the listing does not say how to ask this seller for evidence"
NOT_NAMED = "the seller's signed commitment is not the one its listing names"
NOT_VERIFIED = "the seller's signed commitment does not verify"
COMMITMENT_UNREADABLE = "the seller's listing or its signed commitment could not be read"


def _refuse(item: dict, reason: str, detail: str = "") -> None:
    item["problem"] = reason
    if detail:
        item["detail"] = detail


def _check_entry(item: dict, own: dict, result: dict, domain: str) -> None:
    """The checks on one seller's own entry, recorded on ``item``: its copy matches the registry's, its identity names
    its publisher, and the commitment it names is the one served and verifies. A failed check sets ``problem``."""
    if own.get("url") != result.get("url") or own.get("displayName") != result.get("displayName"):
        return _refuse(item, DIFFERS)
    item["checks"].append("the registry's copy matches the seller's own listing")
    tm = own.get("trustManifest") or {}
    if tm.get("identity") != domain:
        return _refuse(item, WRONG_SITE, f"the entry's identity {tm.get('identity')!r} does not name its publisher {domain}")
    item["checks"].append(f"the listing names the site it was published on, {domain} (a local stand-in here: nothing "
                          "proves who controls that site)")
    att = next((a for a in tm.get("attestations") or [] if isinstance(a, dict) and a.get("type") == PROFILE), None)
    if att is None:
        return _refuse(item, NO_COMMITMENT, f"no {PROFILE} attestation in the entry's trustManifest")
    item["offer"] = own["x-demo-offer"]
    item["uri"] = att["uri"]
    octets = _fetch(att["uri"])
    item["digest_matches"] = att["digest"] == "sha256:" + hashlib.sha256(octets).hexdigest()
    if not item["digest_matches"]:  # the entry points at another document than the one served
        return _refuse(item, NOT_NAMED, f"the digest of {att['uri']} differs from the entry's {att['digest']}")
    item["checks"].append("the seller's signed commitment is the one its listing names")
    try:
        doc_c = json.loads(octets)
        cm.verify(doc_c)
    except Exception as exc:  # noqa: BLE001
        return _refuse(item, NOT_VERIFIED, repr(exc))
    item["identity"] = doc_c["key_id"]
    item["commitment"] = doc_c
    item["checks"].append("the seller's signed commitment verifies")


def lookup(registry_url: str, origins: dict[str, str], text: str) -> list[dict]:
    """Search the registry, then check each result against the seller's own entry and commitment. Each
    item says what was checked (``checks``); an item that fails a check has ``problem`` set (a plain reason above),
    ``detail`` when there is more to keep, and no ``commitment``. ``origins`` maps a publisher domain to the address it
    is served at."""
    found = []
    for result in search(registry_url, text).get("results", []):
        ident = result.get("identifier", "")
        domain = _publisher_of(ident)
        item: dict[str, Any] = {"identifier": ident, "id": ident.rsplit(":", 1)[-1], "name": result.get("displayName", ident),
                                "publisher": domain, "score": result.get("score"),
                                "checks": ["the registry found it: a pointer only, so the seller's own listing is checked"]}
        found.append(item)
        origin = origins.get(domain)
        if not origin:
            _refuse(item, UNREACHABLE, f"publisher {domain or '?'} is not one the buyer can reach")
            continue
        item["fetched_from"] = origin + WELL_KNOWN  # the address tried, kept in the buyer's records even on a failure
        try:
            own = next(e for e in json.loads(_fetch(origin + WELL_KNOWN))["entries"] if e["identifier"] == ident)
        except StopIteration:
            _refuse(item, NOT_LISTED, f"{origin}{WELL_KNOWN} has no entry {ident}")
            continue
        except Exception as exc:  # noqa: BLE001
            _refuse(item, UNREADABLE, f"{origin}{WELL_KNOWN}: {exc!r}")
            continue
        item["entry"], item["registry"] = own, result  # for the listing tool
        item["checks"].append(f"the seller's own listing was fetched from its site, {domain}")
        try:  # any malformed field or fetch fails this seller only; the entry fetched stays for the listing
            _check_entry(item, own, result, domain)
        except Exception as exc:  # noqa: BLE001
            for k in ("offer", "commitment", "identity"):
                item.pop(k, None)
            _refuse(item, COMMITMENT_UNREADABLE, repr(exc))
    return found
