#!/usr/bin/env python3
"""A local stand-in for a witness, for the quick start: it records every request
it is sent (method, path, body size) to a JSONL file and countersigns nothing.
Point CAPSULE_WITNESS_URL at it so a walk-through never posts to a public witness.

    catcher.py --port 8765 --log caught.jsonl
"""
import argparse
import json
import http.server


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--log", required=True)
    a = ap.parse_args()

    class Catch(http.server.BaseHTTPRequestHandler):
        def _record(self) -> None:
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n) if n else b""
            with open(a.log, "a") as f:
                f.write(json.dumps({"method": self.command, "path": self.path, "bytes": len(body)}) + "\n")
            # a stand-in, not a witness: no countersignature, so the producer records no countersignature
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"local catcher: recorded, not countersigned"}')

        do_POST = do_PUT = do_GET = _record

        def log_message(self, *args) -> None:
            pass

    http.server.ThreadingHTTPServer(("127.0.0.1", a.port), Catch).serve_forever()


if __name__ == "__main__":
    main()
