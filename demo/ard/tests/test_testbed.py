# SPDX-License-Identifier: Apache-2.0
"""The multi-role testbed (evidencebook-skills#382): its config, the order ``testbed.py up`` runs in and what it stops
on a failure, the witness it names, and the witness's and the rail's screens."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
import feeds  # noqa: E402
import testbed  # noqa: E402


def _cfg(tmp_path, text):
    f = tmp_path / "testbed.yaml"
    f.write_text(text)
    return f


def test_the_shipped_config_names_every_role_and_the_hosted_witness():
    c = testbed.config()
    assert set(c["roles"]) == set(testbed.AGENTS + testbed.SCREENS)
    assert (c["witness"], c["rail"]) == ("public", "fake")  # the hosted witness is the default


@pytest.mark.parametrize("text, says", [
    ("roles: [alder, kestrel, adjudicator, maya, notary]\nwitness: public\nrail: fake\n", "notary"),
    ("roles: [alder, kestrel, maya]\nwitness: public\nrail: fake\n", "adjudicator is missing"),
    ("roles: [alder, kestrel, adjudicator, maya]\nwitness: hosted\nrail: fake\n", "witness is one of"),
    ("roles: [alder, kestrel, adjudicator, maya]\nwitness: public\nrail: lightning\n", "rail is fake"),
    ("roles: [alder, kestrel, adjudicator, maya, maya]\nwitness: public\nrail: fake\n", "each once"),
    ("roles: [alder, kestrel, adjudicator, maya]\nwitness: public\nrail: fake\nextra: 1\n", "only"),
])
def test_a_config_it_cannot_run_is_refused(tmp_path, text, says):
    with pytest.raises(testbed.Stop, match=says):
        testbed.config(_cfg(tmp_path, text))


# -- the order of `up`, and what a failure leaves --------------------------------------------------------------------

@pytest.fixture
def world(tmp_path, monkeypatch):
    """``up`` with every outside step recorded in ``steps`` instead of run; ``fail`` names a step that fails."""
    steps, fail = [], set()
    monkeypatch.setenv("ARD_TESTBED", str(tmp_path / "tb"))
    import reset
    monkeypatch.setattr(reset, "goose_running", lambda: "goose" in fail)
    monkeypatch.setattr(reset, "goose_quitting", lambda wait_s=None: False)

    def run(argv, **kw):
        name = Path(argv[1]).name if len(argv) > 1 else argv[0]
        step = {"demo.py": argv[2] if len(argv) > 2 else "", "open-windows.py": "windows"}.get(name, name)
        steps.append(step)
        if step == "seed" and "seed^C" in fail:
            raise KeyboardInterrupt
        if step == "osascript":
            return subprocess.CompletedProcess(argv, 0, "", "")
        return subprocess.CompletedProcess(argv, 1 if step in fail else 0, "", "")
    monkeypatch.setattr(testbed.subprocess, "run", run)
    monkeypatch.setattr(testbed, "start_witness", lambda say=print: steps.append("witness up") or {
        "ARD_WITNESS": "local", "ARD_WITNESS_URL": "https://localhost:1", "ARD_WITNESS_KEY": "ab" * 32})
    monkeypatch.setattr(testbed, "stop_witness", lambda say=print: steps.append("witness down"))
    monkeypatch.setattr(testbed, "open_screen", lambda role, env: steps.append(f"screen {role}"))
    monkeypatch.setattr(testbed, "stop_screens", lambda h: steps.append("screens down"))
    return steps, fail


def _up(witness="local", ask=lambda q: "n"):
    c = testbed.config()
    c["witness"] = witness
    return testbed.up(c, say=lambda *_: None, ask=ask)


def test_up_resets_then_starts_the_witness_seeds_and_opens_every_screen(world):
    steps, _ = world
    assert _up() == 0
    assert steps == ["reset", "witness down", "witness up", "seed", "screen witness", "screen rail", "screen catalog",
                     "windows"]


def test_a_failed_seed_stops_the_witness_this_run_started(world):
    steps, fail = world
    fail.add("seed")
    with pytest.raises(testbed.Stop, match="seed failed"):
        _up()
    assert steps[-2:] == ["screens down", "witness down"] and "windows" not in steps


def test_ctrl_c_stops_the_witness_this_run_started(world):
    steps, fail = world
    fail.add("seed^C")
    assert _up() == 130
    assert steps[-2:] == ["screens down", "witness down"] and "windows" not in steps


def test_a_refused_reset_starts_nothing_and_stops_nothing(world):
    # the earlier run's records stay, so the witness they name stays too
    steps, fail = world
    fail.add("reset")
    with pytest.raises(testbed.Stop, match="reset refused"):
        _up()
    assert steps == ["reset"]


def test_down_leaves_the_witness_when_reset_refuses(world):
    steps, fail = world
    fail.add("reset")
    with pytest.raises(testbed.Stop, match="witness was left running"):
        testbed.down(say=lambda *_: None, ask=lambda q: "n")
    assert "witness down" not in steps


def test_a_witness_that_fails_to_start_is_stopped(world, monkeypatch):
    # start.sh starts the witness before its health check, so a failed start can leave it running
    steps, _ = world

    def failing(say=print):
        steps.append("witness up")
        raise testbed.Stop("the local witness did not start")
    monkeypatch.setattr(testbed, "start_witness", failing)
    with pytest.raises(testbed.Stop):
        _up()
    assert steps[-3:] == ["witness up", "screens down", "witness down"] and "seed" not in steps


def test_windows_that_do_not_open_stop_the_witness_this_run_started(world):
    steps, fail = world
    fail.add("windows")
    assert _up() == 1
    assert steps[-3:] == ["windows", "screens down", "witness down"]  # the screens it opened, too


def test_a_local_witness_without_python_311_is_refused_before_anything_changes(world, monkeypatch):
    steps, _ = world
    monkeypatch.setattr(testbed.sys, "version_info", (3, 10, 0))
    monkeypatch.setattr(testbed.shutil, "which", lambda name: None)
    with pytest.raises(testbed.Stop, match="Python 3.11"):
        _up()
    assert steps == []


def test_with_goose_running_it_asks_first_and_a_no_changes_nothing(world):
    steps, fail = world
    fail.add("goose")
    with pytest.raises(testbed.Stop, match="Nothing was changed"):
        _up(ask=lambda q: "n")
    assert steps == []


def test_the_hosted_witness_starts_no_local_one(world):
    steps, _ = world
    assert _up(witness="public") == 0
    assert "witness up" not in steps


def test_the_run_names_only_the_witness_it_chose(monkeypatch):
    # a variable an earlier run left in this shell cannot name a witness that is gone
    monkeypatch.setenv("ARD_WITNESS", "local")
    monkeypatch.setenv("ARD_WITNESS_URL", "https://localhost:9")
    monkeypatch.setenv("ARD_WITNESS_KEY", "cd" * 32)
    env = testbed.run_env({})
    assert env["ARD_WITNESS"] == "public" and "ARD_WITNESS_URL" not in env and "ARD_WITNESS_KEY" not in env
    local = {"ARD_WITNESS": "local", "ARD_WITNESS_URL": "https://localhost:1", "ARD_WITNESS_KEY": "ab" * 32}
    assert {k: testbed.run_env(local)[k] for k in local} == local


def test_reopen_refuses_once_the_local_witness_is_gone(tmp_path, monkeypatch):
    monkeypatch.setenv("ARD_TESTBED", str(tmp_path))
    testbed.write_env(testbed.witness_env_file(), {"ARD_WITNESS": "local", "ARD_WITNESS_URL": "https://localhost:1",
                                                   "ARD_WITNESS_KEY": "ab" * 32})
    with pytest.raises(testbed.Stop, match="no longer running"):
        testbed.reopen(testbed.config())


def test_the_witness_env_file_round_trips(tmp_path):
    f = tmp_path / "w.env"
    env = {"ARD_WITNESS": "local", "SSL_CERT_FILE": str(tmp_path / "a b" / "ca.pem")}
    testbed.write_env(f, env)
    assert testbed.read_env(f) == env


def test_stop_witness_leaves_a_process_that_is_not_ours(tmp_path, monkeypatch):
    monkeypatch.setenv("ARD_TESTBED", str(tmp_path))
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        testbed._pid_file().parent.mkdir(parents=True)
        testbed._pid_file().write_text(str(p.pid))
        testbed.stop_witness(say=lambda *_: None)
        assert p.poll() is None  # still running: its pid file did not make it ours
        assert not testbed._pid_file().exists()
    finally:
        p.kill()
        p.wait()


def test_the_one_command_passes_shellcheck():
    if not shutil.which("shellcheck"):
        pytest.skip("shellcheck is not installed")
    subprocess.run(["shellcheck", str(HERE / "testbed.sh")], check=True)


# -- the witness the run names ---------------------------------------------------------------------------------------

def _party_with(env: dict) -> subprocess.CompletedProcess:
    code = "import party as pt; print(pt.WITNESS_URL, pt.WITNESS_KEY, pt.WITNESS_NAME, sep='|')"
    full = {k: v for k, v in os.environ.items() if not k.startswith("ARD_WITNESS")}
    return subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, {str(HERE)!r}); import _paths; "
                           f"_paths.setup(); {code}"], env={**full, **env}, capture_output=True, text=True)


def test_a_local_witness_is_named_with_its_url_and_key():
    run = _party_with({"ARD_WITNESS": "local", "ARD_WITNESS_URL": "https://localhost:5", "ARD_WITNESS_KEY": "ab" * 32})
    assert run.returncode == 0, run.stderr
    assert run.stdout.strip() == f"https://localhost:5|{'ab' * 32}|the local test witness"


@pytest.mark.parametrize("env", [{"ARD_WITNESS": "local"}, {"ARD_WITNESS": "local", "ARD_WITNESS_URL": "https://x"},
                                 {"ARD_WITNESS": "local", "ARD_WITNESS_KEY": "ab" * 32}])
def test_a_local_witness_without_both_its_url_and_key_is_refused(env):
    run = _party_with(env)
    assert run.returncode != 0 and "needs both ARD_WITNESS_URL and ARD_WITNESS_KEY" in run.stderr


def test_the_hosted_witness_is_the_default():
    run = _party_with({})
    assert run.returncode == 0, run.stderr
    assert run.stdout.split("|")[0] == "https://witness.agentactioncapsule.org"


def test_a_profile_names_a_local_witness_after_init(tmp_path, monkeypatch):
    # deal init can name only the hosted witness: with another one, init runs without one and the profile then names it
    import party as pt
    monkeypatch.setenv("ARD_WITNESS", "local")
    monkeypatch.setattr(pt, "WITNESS_URL", "https://localhost:5")
    monkeypatch.setattr(pt, "WITNESS_KEY", "ab" * 32)
    calls = []

    def run(self, *args):
        calls.append(args)
        if args[0] == "init":
            prof = self.dir / ".config" / "capsule" / "profiles" / f"{self.profile}.yaml"
            prof.parent.mkdir(parents=True, exist_ok=True)
            prof.write_text("store: x\ncheckpoint:\n    interval: 1m\n")
            (self.dir / "deal").mkdir(parents=True, exist_ok=True)
        return {}
    monkeypatch.setattr(pt.Party, "run", run)
    p = pt.Party(tmp_path, "maya")
    p.create("person")
    assert "--no-witness" in calls[0]
    text = (p.dir / ".config" / "capsule" / "profiles" / "ard-maya.yaml").read_text()
    assert "endpoint: https://localhost:5" in text and f"public_key: {'ab' * 32}" in text
    q = pt.Party(tmp_path, "sample-buyer-alder")  # a profile made without a witness on purpose stays without
    calls.clear()
    q.create("person", witness=False)
    assert "endpoint:" not in (q.dir / ".config" / "capsule" / "profiles" / "ard-sample-buyer-alder.yaml").read_text()


def test_the_pack_trusts_the_runs_witness(monkeypatch):
    import pack as packs
    import party as pt
    monkeypatch.setattr(pt, "WITNESS_KEY", "ab" * 32)
    got = {}
    monkeypatch.setattr(packs, "compile_source", lambda text, version, work=None: got.setdefault("text", text))
    packs.starting()
    assert "ab" * 32 in got["text"] and pt.HOSTED_WITNESS_KEY not in got["text"]


def test_every_window_is_handed_the_local_witness(monkeypatch):
    spec = importlib.util.spec_from_file_location("open_windows_tb", HERE / "goose" / "open-windows.py")
    ow = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ow)
    for k, v in {"CAPSULE_ENGINE": "/e", "ARD_EVIDENCEBOOK": "/b", "CAPSULECTL_DEAL": "/d", "ARD_WITNESS": "local",
                 "ARD_WITNESS_URL": "https://localhost:5", "ARD_WITNESS_KEY": "ab" * 32, "SSL_CERT_FILE": "/ca.pem"}.items():
        monkeypatch.setenv(k, v)
    for role in testbed.AGENTS:
        args = ow.recipe(role, "fake")["extensions"][0]["args"]
        assert {"ARD_WITNESS=local", "ARD_WITNESS_URL=https://localhost:5", f"ARD_WITNESS_KEY={'ab' * 32}",
                "SSL_CERT_FILE=/ca.pem"} <= set(args)


# -- the two screens ---------------------------------------------------------------------------------------------------

def test_the_witness_screen_says_what_it_received_and_never_a_record(tmp_path):
    feeds.stamp(tmp_path, "kestrel", "Action State's witness",
                {"state": "ticked", "tick": 4, "checkpoint": 27, "delivered": [3, 4], "pending": [], "witness_sees": "x"})
    feeds.stamp(tmp_path, "kestrel", "Action State's witness", {"state": "not_due", "delivered": [], "pending": []})
    feeds.stamp(tmp_path, "kestrel", "Action State's witness", {"state": "ticked", "witness": "not_configured"})
    feeds.stamp(tmp_path, "kestrel", "Action State's witness", {"error": "refused"})
    lines = feeds.path(tmp_path, "witness").read_text().splitlines()
    assert len(lines) == 1  # nothing due, no witness, and an error are no event the witness saw
    event = json.loads(lines[0])
    assert set(event) == {"at", "party", "witness", "stamp", "covers", "taken", "waiting"}
    from cast import label
    said = feeds.words("witness", event, label)
    assert "Kestrel Print's book sent its hash no. 4;" in said and "entries" not in said  # an MMR size is no count of entries; the clock may read 27
    assert "Action State's witness took 2 of Kestrel Print's stamps" in said


def test_the_rail_screen_says_who_paid_whom_in_plain_words(tmp_path):
    from cast import label
    feeds.payment(tmp_path, "invoice", "maya", "kestrel", 1000, "f" * 64, "simulated")
    feeds.payment(tmp_path, "paid", "maya", "kestrel", 1000, "e" * 64, "simulated")
    feeds.payment(tmp_path, "not_paid", "maya", "alder", 2000, "d" * 64, "lightning")
    events = [json.loads(x) for x in feeds.path(tmp_path, "rail").read_text().splitlines()]
    assert all(len(e["reference"]) == 12 for e in events)  # never a whole hash
    said = [feeds.words("rail", e, label) for e in events]
    assert "Kestrel Print made an invoice for 1,000 msat to Maya (simulated: no money moves)" in said[0]
    assert "Maya paid Kestrel Print 1,000 msat (simulated: no money moves)" in said[1]
    assert "Maya's payment of 2,000 msat to Alder Print Co. did not go through; no money moved" in said[2]
    assert "simulated" not in said[2]


def test_a_feed_that_cannot_be_written_never_fails_the_step(tmp_path):
    blocked = tmp_path / "home"
    blocked.write_text("a file where the home's folder would be")
    feeds.payment(blocked, "paid", "maya", "alder", 2000, "c" * 64, "simulated")  # no exception


def test_follow_waits_for_a_line_to_be_written_whole(tmp_path):
    f = feeds.path(tmp_path, "rail")
    f.parent.mkdir(parents=True)
    f.write_text(json.dumps({"n": 1}) + "\n" + '{"n": 2')
    it = feeds.follow(tmp_path, "rail", poll_s=0)
    assert next(it) == {"n": 1}
    with open(f, "a") as fh:
        fh.write("}\n")
    assert next(it) == {"n": 2}


def test_watch_once_prints_what_the_role_saw(tmp_path):
    feeds.payment(tmp_path, "paid", "maya", "alder", 2000, "c" * 64, "simulated")
    run = subprocess.run([sys.executable, str(HERE / "watch.py"), "rail", "--once", "--home", str(tmp_path)],
                         capture_output=True, text=True, env={k: v for k, v in os.environ.items() if k != "ARD_HOME"})
    assert run.returncode == 0, run.stderr
    assert "The payment rail" in run.stdout and "Maya paid Alder Print Co. 2,000 msat" in run.stdout


def test_reset_counts_an_open_screen_among_the_demos_own(tmp_path):
    import reset
    (tmp_path / ".watch-rail.lock").write_text("")
    assert tmp_path / ".watch-rail.lock" in reset._locks(tmp_path)
    assert "watch.py" in reset.SCRIPTS


def test_a_successful_up_leaves_its_screens_and_witness_running(world):
    steps, _ = world
    assert _up() == 0
    assert "screens down" not in steps and steps[-1] == "windows"


def test_stop_screens_signals_only_our_own_watch_process(tmp_path, monkeypatch):
    import reset
    (tmp_path / ".watch-rail.lock").write_text("")
    killed = []
    monkeypatch.setattr(reset, "_lsof", lambda *a: [(111, "3w", a[0]), (222, "4w", a[0])])
    monkeypatch.setattr(reset, "_runs_our_script", lambda pid: pid == 111)
    monkeypatch.setattr(testbed.os, "kill", lambda pid, sig: killed.append(pid))
    testbed.stop_screens(tmp_path)
    assert killed == [111]


C = "http://127.0.0.1:9"  # the catalog stand-in's origin, as the buyer knows it


def _check(monkeypatch, offer, served):
    import ard
    monkeypatch.setattr(ard, "_fetch", lambda url, body=None: json.dumps(served).encode())
    item = {"id": "kestrel", "checks": []}
    return ard._catalog_check(item, offer, C), item


OFFER = {"item": "200 badges", "price_msat": 1000, "product": "badges-200",
         "catalog": f"{C}/catalog/kestrel/badges-200.json"}
SERVED = {"seller": "kestrel", "product": "badges-200", "title": "200 badges", "price_msat": 1000}


def test_a_listing_is_checked_against_this_sellers_entry_in_the_catalog(monkeypatch):
    import ard
    ok, item = _check(monkeypatch, OFFER, SERVED)
    assert ok and "problem" not in item and "catalog (a stand-in)" in item["checks"][0]
    ok, item = _check(monkeypatch, OFFER, {**SERVED, "price_msat": 500})  # the catalog says 500 msat: refused
    assert not ok and item["problem"] == ard.CATALOG_DIFFERS


@pytest.mark.parametrize("link", [
    f"{C}/catalog/alder/badges-200.json",  # another seller's entry, copying its price
    "http://127.0.0.1:8/catalog/kestrel/badges-200.json",  # a catalog on another host the listing names
    None,  # no catalog at all: refused, never passed in silence
])
def test_a_listing_that_links_no_entry_of_this_seller_in_the_catalog_is_refused(monkeypatch, link):
    import ard
    offer = {k: v for k, v in OFFER.items() if k != "catalog"} | ({"catalog": link} if link else {})
    ok, item = _check(monkeypatch, offer, SERVED)
    assert not ok and item["problem"] == ard.CATALOG_UNLINKED


def test_an_entry_the_catalog_serves_for_another_seller_is_refused(monkeypatch):
    import ard
    ok, item = _check(monkeypatch, OFFER, {**SERVED, "seller": "alder"})
    assert not ok and item["problem"] == ard.CATALOG_DIFFERS


def test_the_stage_serves_each_sellers_product_and_shows_each_read(tmp_path, monkeypatch):
    import stage
    st = stage.Stage.__new__(stage.Stage)
    st.home = tmp_path
    got = json.loads(st.page("/catalog/kestrel/badges-200.json"))
    assert (got["title"], got["price_msat"], got["stand_in"]) == ("200 conference badges, delivered by Friday", 1000, True)
    assert st.page("/catalog/kestrel/mugs.json") is None and st.page("/catalog/../x.json") is None
    from cast import label
    (event,) = [json.loads(x) for x in feeds.path(tmp_path, "catalog").read_text().splitlines()]
    assert "A buyer's agent read Kestrel Print's product badges-200" in feeds.words("catalog", event, label)


def test_the_catalog_screen_lists_what_the_catalog_holds(tmp_path):
    run = subprocess.run([sys.executable, str(HERE / "watch.py"), "catalog", "--once", "--home", str(tmp_path)],
                         capture_output=True, text=True, env={k: v for k, v in os.environ.items() if k != "ARD_HOME"})
    assert run.returncode == 0, run.stderr
    assert "not a real store" in run.stdout
    assert "Kestrel Print: product badges-200, 200 conference badges, delivered by Friday, 1,000 msat" in run.stdout
