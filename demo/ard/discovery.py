# SPDX-License-Identifier: Apache-2.0
"""The demo's discovery stand-ins (design note ``docs/design/ard-buyer-seller-skills.md`` §3.6 items 4-5).

Each seller's own origin serves its ``/.well-known/ard.json`` (ARD v0.91 §5.1: a manifest with an
``entries`` array) and its signed ``evidence-commitment/1``, on a local port of its own. A
:class:`StandInRegistry` answers ``POST /search`` (ARD v0.91 §5.3.2) from a fixed list of those
origins. There is no crawler (§5.2), and the registry never becomes a service anyone runs: it lives
in this demo only, as a stand-in for registries other people run (spec u545, "no discovery system of
our own"). Each seller's publisher is a ``.test`` domain (``alder.ard-demo.test``); the local port
is only the transport address, mapped from that domain in one fixed table (:data:`ORIGINS`), and
nothing here proves that a seller controls its domain."""
from __future__ import annotations

import json
import re
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

import ard

#: The registry's media type for a referral or itself (ARD §5.3.2's example).
REGISTRY_TYPE = "application/ai-registry+json"


def _handler(get: Callable[[str], bytes | None], post: Callable[[str, bytes], bytes | None] | None = None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_a):
            pass

        def _send(self, body: bytes | None) -> None:
            self.send_response(200 if body is not None else 404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body or b"{}")))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body if body is not None else b"{}")

        def do_GET(self) -> None:  # noqa: N802
            self._send(get(self.path.split("?")[0]))

        def do_POST(self) -> None:  # noqa: N802
            body = self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))
            self._send(post(self.path.split("?")[0], body) if post else None)

    return Handler


def _serve(port: int, handler) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


class SellerOrigin:
    """One seller's own origin: its ``/.well-known/ard.json`` and its commitment."""

    def __init__(self, name: str, seller: dict, commitment: Callable[[], dict | None], port: int = 0):
        self.name, self.seller, self.commitment = name, seller, commitment
        self.httpd = _serve(port, _handler(self.get))
        self.origin = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def get(self, path: str) -> bytes | None:
        doc = self.commitment()
        if doc is None:
            return None
        if path == ard.WELL_KNOWN:
            return json.dumps(ard.manifest(self.name, self.seller, doc, self.origin), sort_keys=True).encode()
        if path == f"/commitments/{self.name}.json":
            return ard.commitment_octets(doc)
        return None

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


class StandInRegistry:
    """A demo stand-in for an ARD registry run by someone else: ``POST /search`` over a fixed list of
    seller origins, read at query time. No crawler, no referrals (it has none to give)."""

    def __init__(self, origins: list[str], port: int = 0):
        self.origins = list(origins)
        self.httpd = _serve(port, _handler(lambda _p: None, self.post))
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/search"

    def post(self, path: str, body: bytes) -> bytes | None:
        if path != "/search":
            return None
        try:
            req = json.loads(body or b"{}")
            text = req["query"]["text"]
        except (ValueError, KeyError, TypeError):
            return json.dumps({"error": "a search names query.text (ARD v0.91 §5.3.2)"}).encode()
        words = {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2}
        results = []
        for origin in self.origins:
            try:
                with urllib.request.urlopen(origin + ard.WELL_KNOWN, timeout=5) as r:  # a demo-local origin
                    entries = json.loads(r.read())["entries"]
            except Exception:
                continue
            for e in entries:
                hay = " ".join([e.get("displayName", ""), e.get("description", ""), " ".join(e.get("tags", []))]).lower()
                hits = sum(1 for w in words if w in hay)
                if hits:
                    results.append({"identifier": e["identifier"], "displayName": e["displayName"], "type": e["type"],
                                    "url": e["url"], "score": min(100, 50 + 10 * hits), "source": self.url})
        results.sort(key=lambda r: -r["score"])
        return json.dumps({"results": results[: int(req.get("pageSize", 10))], "referrals": []}, sort_keys=True).encode()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


class Discovery:
    """The two seller origins and the stand-in registry. ``ports`` is (registry, *sellers) or 0 for
    free ports. :attr:`origins` is the fixed domain-to-origin table the buyer resolves with."""

    def __init__(self, sellers: dict[str, dict], commitment: Callable[[str], dict | None],
                 registry_port: int = 0, seller_ports: dict[str, int] | None = None):
        self.sellers = {n: SellerOrigin(n, s, (lambda n=n: commitment(n)), (seller_ports or {}).get(n, 0))
                        for n, s in sellers.items()}
        self.origins = {ard.publisher(n): o.origin for n, o in self.sellers.items()}
        self.registry = StandInRegistry([o.origin for o in self.sellers.values()], registry_port)

    def close(self) -> None:
        self.registry.close()
        for o in self.sellers.values():
            o.close()
