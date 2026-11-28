# SPDX-License-Identifier: Apache-2.0
"""evidencebook-skills#453: the end-to-end test names Action State's hosted witness only when told to."""
from __future__ import annotations

import pytest

import _e2ewitness as w

LOCAL = {"ARD_E2E_WITNESS_URL": "https://localhost:1", "ARD_E2E_WITNESS_KEY": "ab" * 32}


def test_a_local_witness_is_used_when_named():
    assert w.choose(LOCAL) == (LOCAL["ARD_E2E_WITNESS_URL"], LOCAL["ARD_E2E_WITNESS_KEY"])


def test_the_hosted_witness_only_when_asked_for():
    assert w.choose({"ARD_E2E_WITNESS": "hosted"}) is None


def test_no_witness_named_is_refused_not_hosted():
    with pytest.raises(w.Refused, match="names no witness: run it through scripts/check.sh --full"):
        w.choose({})


@pytest.mark.parametrize("env, says", [
    ({"ARD_E2E_WITNESS_URL": "https://localhost:1"}, "set both"),
    ({"ARD_E2E_WITNESS_KEY": "ab"}, "set both"),
    ({**LOCAL, "ARD_E2E_WITNESS": "hosted"}, "two witnesses"),
    ({"ARD_E2E_WITNESS": "public"}, "hosted or unset"),
])
def test_an_unclear_choice_is_refused(env, says):
    with pytest.raises(w.Refused, match=says):
        w.choose(env)
