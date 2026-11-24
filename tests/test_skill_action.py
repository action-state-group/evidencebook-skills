"""Tests for skill-action/v1 (scripts/skill_record.py) and scripts/skill_action.py.

The pure record/request builders and the wrapper run against a stand-in
capsulectl. When CAPSULECTL names a real capsulectl binary, one more test seals
an action through it, re-runs it, and verifies the record.

    python3 -m unittest discover -s tests -p 'test_*.py'
"""
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from capsulectl_calls import EvidenceUnavailable  # noqa: E402
from skill_record import SKILL_ACTION, json_digest, skill_action_record, skill_action_request  # noqa: E402

D1, D2, D3 = "a1" * 32, "b2" * 32, "c3" * 32

FAKE_CAPSULECTL = textwrap.dedent("""\
    #!/usr/bin/env python3
    # A stand-in capsulectl: `profile show` and `publish` only. Each publish keeps
    # its request in $FAKE_LOG and returns the request's digest as capsule_id.
    import hashlib, json, os, pathlib, sys
    args = sys.argv[1:]
    if args[:2] == ["profile", "show"]:
        print(json.dumps({"Operator": "example-operator"}))
    elif args[0] == "publish":
        if os.environ.get("FAKE_PUBLISH_FAILS"):
            print("store unavailable", file=sys.stderr); sys.exit(1)
        raw = pathlib.Path(args[args.index("--request") + 1]).read_bytes()
        cid = hashlib.sha256(raw).hexdigest()
        (pathlib.Path(os.environ["FAKE_LOG"]) / (cid + ".json")).write_bytes(raw)
        print(json.dumps({"capsule_id": cid, "state": "appended"}))
    else:
        sys.exit(2)
""")


class SkillActionRecord(unittest.TestCase):
    def test_shape_is_digests_only(self):
        record = skill_action_record("evidence-contract-compile", "contract-validate",
                                     inputs=[("schema", D2), ("contract", D1)], output_digest=D3,
                                     argv_digest=D1)
        self.assertEqual(record, {"record_type": SKILL_ACTION, "skill": "evidence-contract-compile",
                                  "action": "contract-validate",
                                  "inputs": [{"role": "contract", "digest": D1}, {"role": "schema", "digest": D2}],
                                  "outcome": "ok", "exit_code": 0, "output_digest": D3, "argv_digest": D1})

    def test_secret_role_and_action_names_are_refused(self):
        for role in ("signing_key", "api-token", "db_password", "producer.seed", "dsn"):
            with self.assertRaises(EvidenceUnavailable, msg=role):
                skill_action_record("s", "a", inputs=[(role, D1)])
        with self.assertRaises(EvidenceUnavailable):
            skill_action_record("s", "key-generate")

    def test_secret_words_match_whole_name_parts_only(self):
        for benign in ("keyword-index", "monkey", "turnkey", "tokenizer-check"):
            self.assertEqual(skill_action_record("s", benign)["action"], benign)

    def test_non_digest_values_are_refused(self):
        for bad in ("not-a-digest", "A1" * 32, D1[:-1], {"x": 1}):
            with self.assertRaises(EvidenceUnavailable, msg=repr(bad)):
                skill_action_record("s", "a", inputs=[("contract", bad)])
        with self.assertRaises(EvidenceUnavailable):
            skill_action_record("s", "a", output_digest="cat CONTRACT.yaml")

    def test_paths_and_free_text_never_reach_a_name(self):
        for bad in ("/home/user/contract.yaml", "contract validate", ""):
            with self.assertRaises(EvidenceUnavailable, msg=bad):
                skill_action_record("s", bad)


class JsonDigest(unittest.TestCase):
    """json_digest is a JSON-DIGEST: SHA-256 over RFC 8785 (JCS) bytes."""

    def test_jcs_number_form_and_key_order(self):
        # JCS writes 1e21 as 1e+21 and 0.1 as 0.1, and sorts keys by UTF-16 code units,
        # which puts U+1F600 (surrogates D83D..) before U+FB01.
        value = {"\ufb01": 1, "\U0001f600": 2, "n": [1e21, 0.1, 1.0]}
        jcs = '{"n":[1e+21,0.1,1],"\U0001f600":2,"\ufb01":1}'.encode()
        self.assertEqual(json_digest(value), hashlib.sha256(jcs).hexdigest())

    def test_a_value_jcs_cannot_represent_has_no_digest(self):
        for bad in (float("nan"), 2 ** 60):
            with self.assertRaises(EvidenceUnavailable, msg=repr(bad)):
                json_digest([bad])


class SkillActionRequest(unittest.TestCase):
    RECORD = skill_action_record("daily-judge-and-close", "read-range", output_digest=D1)

    def test_same_action_same_inputs_is_the_same_request(self):
        a = skill_action_request(self.RECORD, "op", "2026-09-23T23:59:59Z")
        b = skill_action_request(dict(self.RECORD), "op", "2026-09-23T23:59:59Z")
        self.assertEqual(a, b)
        self.assertEqual(a["capsule"]["Developer"], "evidencebook-skills/daily-judge-and-close")
        self.assertTrue(a["capsule"]["ActionID"].startswith(
            "urn:evidencebook-skills:skill-action:daily-judge-and-close:read-range:"))
        self.assertNotIn("References", a["capsule"])

    def test_a_different_outcome_is_a_different_action_id(self):
        failed = skill_action_record("daily-judge-and-close", "read-range", output_digest=D1,
                                     outcome="failed", exit_code=1)
        self.assertNotEqual(skill_action_request(self.RECORD, "op", "t")["capsule"]["ActionID"],
                            skill_action_request(failed, "op", "t")["capsule"]["ActionID"])

class Wrapper(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.ctl = self.tmp / "capsulectl"
        self.ctl.write_text(FAKE_CAPSULECTL)
        self.ctl.chmod(0o755)
        self.log = self.tmp / "log"
        self.log.mkdir()
        self.contract = self.tmp / "contract.yaml"
        self.contract.write_text("contract: example\n")
        self.env = dict(os.environ, FAKE_LOG=str(self.log))

    def wrap(self, *own, command=("echo", '{"valid": true}'), env=None, at="2026-09-23T12:00:00Z"):
        argv = [sys.executable, str(ROOT / "scripts" / "skill_action.py"), "--profile", "p",
                "--capsulectl", str(self.ctl), "--work", str(self.tmp / "work"),
                *(("--at", at) if at else ()), *own, "--", *command]
        return subprocess.run(argv, capture_output=True, text=True, env=env or self.env)

    def sealed(self):
        return [json.loads(p.read_text()) for p in sorted(self.log.iterdir())]

    def test_seals_one_record_and_passes_stdout_through(self):
        proc = self.wrap("--skill", "evidence-contract-compile", "--action", "contract-validate",
                         "--input", f"contract={self.contract}")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, '{"valid": true}\n')
        [request] = self.sealed()
        body = request["payload"]
        self.assertEqual(body["inputs"], [{"role": "contract",
                                           "digest": hashlib.sha256(self.contract.read_bytes()).hexdigest()}])
        self.assertEqual(body["output_digest"], hashlib.sha256(b'{"valid": true}\n').hexdigest())
        self.assertEqual(body["argv_digest"], json_digest(["echo", '{"valid": true}']))
        self.assertEqual(request["capsule"]["Operator"], "example-operator")
        self.assertEqual(request["capsule"]["Timestamp"], "2026-09-23T12:00:00Z")
        # Digests only: no path, no file content anywhere in the request.
        flat = json.dumps(request)
        self.assertNotIn(str(self.tmp), flat)
        self.assertNotIn("contract: example", flat)

    def test_a_rerun_seals_the_same_capsule(self):
        for _ in range(2):
            self.assertEqual(self.wrap("--skill", "s", "--action", "map").returncode, 0)
        self.assertEqual(len(self.sealed()), 1)

    def test_at_is_required(self):
        proc = self.wrap("--skill", "s", "--action", "map", at=None)
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(self.sealed(), [])

    def test_a_failed_command_is_sealed_and_its_exit_status_kept(self):
        proc = self.wrap("--skill", "s", "--action", "discover", command=("sh", "-c", "echo partial; exit 3"))
        self.assertEqual(proc.returncode, 3)
        [request] = self.sealed()
        self.assertEqual((request["payload"]["outcome"], request["payload"]["exit_code"]), ("failed", 3))

    def test_key_material_input_is_refused_before_anything_runs(self):
        seed = self.tmp / "producer.seed"
        seed.write_text("x")
        marker = self.tmp / "ran"
        proc = self.wrap("--skill", "s", "--action", "install", "--input", f"profile={seed}",
                         command=("touch", str(marker)))
        self.assertEqual(proc.returncode, 2)
        self.assertFalse(marker.exists())
        self.assertEqual(self.sealed(), [])

    def test_no_record_is_evidence_unavailable(self):
        proc = self.wrap("--skill", "s", "--action", "install",
                         env=dict(self.env, FAKE_PUBLISH_FAILS="1"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("evidence unavailable", proc.stderr)


@unittest.skipUnless(os.environ.get("CAPSULECTL"), "set CAPSULECTL to a capsulectl binary to run")
class AgainstCapsulectl(unittest.TestCase):
    """A skill action sealed by `capsulectl publish` verifies, and a re-run with the
    same --at appends nothing."""

    def test_publishes_verifies_and_reruns_idempotently(self):
        ctl = os.environ["CAPSULECTL"]
        tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        env = dict(os.environ, HOME=str(tmp / "home"), XDG_CONFIG_HOME=str(tmp / "home" / ".config"))
        (tmp / "home" / ".config").mkdir(parents=True)

        def ctl_run(*args):
            proc = subprocess.run([ctl, *args], capture_output=True, text=True, env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return json.loads(proc.stdout) if proc.stdout.strip() else None

        keys = {n: ctl_run("key", "generate", "--output", str(tmp / f"{n}.seed")) for n in ("p", "c")}
        ctl_run("profile", "create", "--name", "t", "--type", "jsonl", "--jsonl-path", str(tmp / "store"),
                "--namespace", "t", "--log-id", "t", "--log", "cll", "--operator", "example-operator",
                "--signing-key-file", str(tmp / "p.seed"), "--trusted-key", keys["p"]["public_key"],
                "--checkpoint-signing-key-file", str(tmp / "c.seed"),
                "--checkpoint-trusted-key", keys["c"]["public_key"])
        ctl_run("store", "init", "--profile", "t")
        contract = tmp / "contract.yaml"
        contract.write_text("contract: example\n")
        ids = []
        for _ in range(2):
            proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "skill_action.py"), "--profile", "t",
                                   "--capsulectl", ctl, "--work", str(tmp / "work"), "--skill", "s",
                                   "--action", "contract-validate", "--input", f"contract={contract}",
                                   "--at", "2026-09-23T12:00:00Z", "--", "echo", "ok"],
                                  capture_output=True, text=True, env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            ids.append(proc.stderr.strip().rsplit(" ", 1)[-1])
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(len(ctl_run("cll", "list", "--profile", "t")["entries"]), 1)
        ctl_run("get", "--profile", "t", "--capsule-id", ids[0], "--raw", "--output", str(tmp / "r.json"))
        verified = ctl_run("verify", "--profile", "t", "--capsule", str(tmp / "r.json"))
        self.assertEqual(verified["capsule_identity"], "passed")
        self.assertEqual(verified["producer_signature_and_trust"], "passed")


if __name__ == "__main__":
    unittest.main()
