# SPDX-License-Identifier: Apache-2.0
"""Which witness the end-to-end test stamps on (evidencebook-skills#453).

Automation posts to Action State's hosted witness only from the nightly hosted leg (capsule-anchor#109,
https://github.com/action-state-group/capsule-anchor/issues/109#issuecomment-7230085528). So the test stamps on the
witness ``ARD_E2E_WITNESS_URL`` and ``ARD_E2E_WITNESS_KEY`` name, which scripts/check.sh and CI's local leg start on
their own machine (capsule-anchor's ci/local-witness), and names the hosted one only when ``ARD_E2E_WITNESS=hosted``
says so, as tests.yml's hosted leg does. With neither it refuses, rather than load the hosted witness by default."""
from __future__ import annotations

from collections.abc import Mapping

#: What the refusal says to do instead.
HOW = ("run it through scripts/check.sh --full, which starts a local witness, or set ARD_E2E_WITNESS_URL and "
       "ARD_E2E_WITNESS_KEY to a witness you started (capsule-anchor ci/local-witness/start.sh); only tests.yml's "
       "hosted leg sets ARD_E2E_WITNESS=hosted")


class Refused(Exception):
    """The environment names no witness, or names two."""


def choose(env: Mapping[str, str]) -> tuple[str, str] | None:
    """The local witness's ``(url, key)``, or None for Action State's hosted one when ``ARD_E2E_WITNESS=hosted``."""
    url, key = env.get("ARD_E2E_WITNESS_URL", ""), env.get("ARD_E2E_WITNESS_KEY", "")
    hosted = env.get("ARD_E2E_WITNESS", "")
    if hosted not in ("", "hosted"):
        raise Refused(f"ARD_E2E_WITNESS is hosted or unset, not {hosted!r}")
    if bool(url) != bool(key):
        raise Refused("set both ARD_E2E_WITNESS_URL and ARD_E2E_WITNESS_KEY, or neither")
    if url and hosted:
        raise Refused("ARD_E2E_WITNESS=hosted and ARD_E2E_WITNESS_URL name two witnesses: set one")
    if url:
        return url, key
    if hosted:
        return None
    raise Refused(f"the end-to-end test names no witness: {HOW}")
