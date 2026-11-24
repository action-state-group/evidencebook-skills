# SPDX-License-Identifier: Apache-2.0
"""An optional, read-only ARD search against Hugging Face's public registry (hf-discover).

It sends the same ``POST /search`` body the demo sends its local stand-in registry and only prints the
raw results. It is off unless ``ARD_HF_SEARCH=1``, never feeds ``ard.lookup`` or the deal, and fails soft:
an unreachable registry yields one explanatory line. Run alone: ``python3 hf_search.py "conference badges print"``."""
from __future__ import annotations

import json
import os
import sys
import urllib.request

URL = "https://huggingface-hf-discover.hf.space/search"
ENV = "ARD_HF_SEARCH"
TIMEOUT = 8


def enabled() -> bool:
    return os.environ.get(ENV) == "1"


def search(text: str, url: str = URL, page_size: int = 3) -> list[dict]:
    """The registry's ``results`` (identifier, type, url, score, ...). Raises on any network or format error."""
    body = json.dumps({"query": {"text": text}, "pageSize": page_size}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        results = json.loads(r.read())["results"]
    if not isinstance(results, list):
        raise ValueError("results is not a list")
    return results


def report(text: str, url: str = URL) -> list[str]:
    """Lines to print: the raw results, or one line saying the registry could not be reached. Never raises."""
    head = f"  searched Hugging Face's public ARD registry, read-only: POST {url} {{query: {text!r}}}"
    try:
        results = search(text, url)
    except Exception as exc:
        return [head, f"  Hugging Face registry not reachable ({type(exc).__name__}: {exc}); the deal uses the local stand-in and is unaffected"]
    lines = [head]
    for r in results:
        lines.append(f"  found (live): {r.get('displayName', '?')}  {r.get('identifier')}  type {r.get('type')}  score {r.get('score')}")
        lines.append(f"         {r.get('url')}")
    if not results:
        lines.append("  no results")
    lines.append("  No Alder or Kestrel entry is there: they are local stand-ins. These results are shown only; the deal does not use them.")
    return lines


if __name__ == "__main__":
    print("\n".join(report(" ".join(sys.argv[1:]) or "conference badges print")))
