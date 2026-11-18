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


def lookup(registry_url: str, origins: dict[str, str], text: str) -> list[dict]:
    """Search the registry, then check each result against the seller's own entry and commitment. Each
    item says what was checked (``checks``); an item that fails a check has ``problem`` set and no
    ``commitment``. ``origins`` maps a publisher domain to the address it is served at."""
    found = []
    for result in search(registry_url, text).get("results", []):
        ident = result.get("identifier", "")
        domain = _publisher_of(ident)
        item: dict[str, Any] = {"identifier": ident, "id": ident.rsplit(":", 1)[-1], "name": result.get("displayName", ident),
                                "publisher": domain,
                                "checks": [f"registry result: {ident} (score {result.get('score')}, a pointer only)"]}
        found.append(item)
        origin = origins.get(domain)
        if not origin:
            item["problem"] = f"publisher {domain or '?'} is not one the buyer can reach"
            continue
        try:
            own = next(e for e in json.loads(_fetch(origin + WELL_KNOWN))["entries"] if e["identifier"] == ident)
        except StopIteration:
            item["problem"] = "the seller's own ard.json has no entry with this identifier"
            continue
        except Exception as exc:
            item["problem"] = f"the seller's own ard.json: {exc}"
            continue
        item["checks"].append(f"seller's own entry fetched from {domain} ({origin}{WELL_KNOWN})")
        if own.get("url") != result.get("url") or own.get("displayName") != result.get("displayName"):
            item["problem"] = "the registry's copy and the seller's own entry differ"
            continue
        item["checks"].append("registry copy matches the seller's own entry")
        tm = own.get("trustManifest", {})
        if tm.get("identity") != domain:
            item["problem"] = f"the entry's identity {tm.get('identity')!r} does not name its publisher {domain}"
            continue
        item["checks"].append(f"identity names the publisher {domain} (a local stand-in: nothing proves domain control)")
        item["offer"] = own["x-demo-offer"]
        att = next(a for a in tm.get("attestations", []) if a.get("type") == PROFILE)
        item["uri"] = att["uri"]
        octets = _fetch(att["uri"])
        item["digest_matches"] = att["digest"] == "sha256:" + hashlib.sha256(octets).hexdigest()
        try:
            doc_c = json.loads(octets)
            cm.verify(doc_c)
            item["identity"] = doc_c["key_id"]
            item["commitment"] = doc_c
            item["checks"].append(f"commitment signature verifies under {doc_c['key_id'][:8]}…")
        except Exception as exc:
            item["problem"] = f"commitment: {exc}"
    return found
