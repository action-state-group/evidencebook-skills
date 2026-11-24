# SPDX-License-Identifier: Apache-2.0
"""The optional Hugging Face search: a recorded response (tests/hf_search_recorded.json, a live answer of
2026-11-23) served by a local server, so no test touches the network."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import hf_search

RECORDED = Path(__file__).with_name("hf_search_recorded.json").read_bytes()


def serve(status: int, payload: bytes, seen: list):
    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            self.send_response(status)
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}/search"


def test_off_unless_env_is_1(monkeypatch):
    monkeypatch.delenv("ARD_HF_SEARCH", raising=False)
    assert not hf_search.enabled()
    monkeypatch.setenv("ARD_HF_SEARCH", "1")
    assert hf_search.enabled()


def test_sends_the_stand_in_body_and_prints_raw_results():
    seen: list = []
    srv, url = serve(200, RECORDED, seen)
    try:
        lines = hf_search.report("conference badges print", url)
    finally:
        srv.shutdown()
    assert seen == [("/search", {"query": {"text": "conference badges print"}, "pageSize": 3})]
    text = "\n".join(lines)
    assert "Paper2Poster" in text and "score 33" in text
    assert "No Alder or Kestrel entry is there" in text


def test_unreachable_registry_fails_soft():
    lines = hf_search.report("x", "http://127.0.0.1:9/search")
    assert any("not reachable" in line and "unaffected" in line for line in lines)


def test_bad_answer_fails_soft():
    srv, url = serve(200, b"not json", [])
    try:
        lines = hf_search.report("x", url)
    finally:
        srv.shutdown()
    assert any("not reachable" in line for line in lines)
