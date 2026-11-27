# SPDX-License-Identifier: Apache-2.0
"""How long the witness takes to take one stamp, through the demo's own path (evidencebook-skills#378).

    python demo/ard/tests/witness_probe.py [--stamps N] [--parallel K] [--wait S]

K fresh profiles, each made as :meth:`party.Party.create` makes one (naming Action State's hosted witness, or the one
``ARD_E2E_WITNESS_URL`` and ``ARD_E2E_WITNESS_KEY`` name), each take N stamps one after another, all K at once. Each
stamp is :meth:`party.Party.wait_checkpoint` with a wait of S seconds, by default ``receipt.PAGE_WAIT_S``, the wait the
receipt page gives the witness before it is drawn without the witness time. It prints one line per stamp and a summary
naming the witness, and exits 1 when a stamp was not taken within S seconds, 2 (:data:`CANNOT_MEASURE`) when a profile
could not be made or the demo's checkout is missing, so CI's
hosted leg says whether the witness was slow apart from the end-to-end test. Needs ``CAPSULECTL_DEAL`` and
``ARD_EVIDENCEBOOK`` (and the network for the hosted witness)."""
from __future__ import annotations

import argparse
import os
import shutil
import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _paths  # noqa: E402

#: The exit status when the witness could not be measured (no evidencebook checkout, a profile that could not be made):
#: apart from 1, a stamp not taken in time, so a caller does not blame the witness's speed for it (#382).
CANNOT_MEASURE = 2


def main(argv: list[str] | None = None) -> int:
    try:
        _paths.setup()
    except _paths.SetupError as exc:
        print(f"could not measure the witness: {exc}", flush=True)
        return CANNOT_MEASURE
    import party as pt
    import receipt

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--stamps", type=int, default=3)
    ap.add_argument("--parallel", type=int, default=1)
    ap.add_argument("--wait", type=float, default=receipt.PAGE_WAIT_S)
    args = ap.parse_args(argv)
    os.environ["ARD_WITNESS"] = "public"
    url, key = os.environ.get("ARD_E2E_WITNESS_URL", ""), os.environ.get("ARD_E2E_WITNESS_KEY", "")
    if url:  # as test_e2e's _local_witness names it; Party.create then names it in each profile (#382)
        pt.WITNESS_URL, pt.WITNESS_KEY = url, key
    witness = pt.WITNESS_URL
    home = Path(tempfile.mkdtemp(prefix="witness-probe-"))
    times: list[float] = []
    failed: list[str] = []  # each stamp not taken in time, and each profile that could not be made or stamped
    broken: list[str] = []  # each profile that could not be made or stamped: the witness was not measured there
    lock = threading.Lock()

    def probe(i: int) -> None:
        try:
            p = pt.Party(home, f"probe-{i}").create("node")
            for n in range(args.stamps):
                t0 = time.monotonic()
                try:
                    p.wait_checkpoint(args.wait)
                    took, why = time.monotonic() - t0, ""
                except pt.Refused as exc:
                    took, why = time.monotonic() - t0, str(exc)
                with lock:
                    print(f"probe-{i} stamp {n + 1}: {'not taken: ' + why if why else 'taken'} in {took:.1f} s",
                          flush=True)
                    if why:
                        failed.append(f"probe-{i} stamp {n + 1} ({why})")
                    else:
                        times.append(took)
        except Exception as exc:  # noqa: BLE001 (a thread's exception would not reach the exit status otherwise)
            with lock:
                print(f"probe-{i}: {exc!r}", flush=True)
                failed.append(f"probe-{i} ({exc!r})")
                broken.append(f"probe-{i}")

    threads = [threading.Thread(target=probe, args=(i,)) for i in range(args.parallel)]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        shutil.rmtree(home, ignore_errors=True)  # the throwaway profiles
    asked = args.parallel * args.stamps
    if times:
        print(f"{witness}: {len(times)} of {asked} stamps taken within {args.wait:.0f} s; min {min(times):.1f} s, "
              f"median {statistics.median(times):.1f} s, max {max(times):.1f} s ({args.parallel} profile(s) at once)")
    if failed or len(times) != asked:
        print(f"{witness}: {asked - len(times)} of {asked} stamps not taken within {args.wait:.0f} s: "
              f"{'; '.join(failed)}")
        return CANNOT_MEASURE if broken else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
