"""The judge pin's input, built in one place for scripts/run_daily.py (which seals
it) and scripts/rollup_day.py (which recomputes it to scope the rollup).

`capsulectl judge pin` hashes model id, prompt digest, axes digest and the flat
sampling_params map. A pin must also move when anything that changes a verdict
moves, so two more digests and the confidence threshold ride in sampling_params
(string and integer values are what `judge pin` accepts there):

  - pack_source_digest: the compiled contract's digest of its whole pack source
    (scripts/pack_compile.py:source_digest). Every criterion edit and every switch
    flip (out_of_scope_verdict, done_in_full_refusal_aware, a claim_when_on
    rewording) changes it.
  - instruction_template_digest: the digest of the instruction template the judge
    command actually sends to its model, as the judge command itself reports it
    (`{"describe": true}` on stdin -> `{"instruction_template_digest": ...}`).
    judge-prompt.md is pinned too, but a judge that builds its instructions in code
    is pinned by what it sends, not by a file it may never read.
  - min_confidence_micros: the compiled judge.min_confidence, scaled to an integer
    (`judge pin` refuses floats), when set.
"""
import json
import shlex
import subprocess

from capsulectl_calls import EvidenceUnavailable, sha256_file

DEFAULT_JUDGE_TIMEOUT = 600


def describe_judge(cmd, timeout=DEFAULT_JUDGE_TIMEOUT):
    """Ask the judge command which instruction template it sends. Refuses (fails
    closed) when the command cannot say: a judge whose instructions cannot be
    pinned is not a pinned judge."""
    try:
        proc = subprocess.run(shlex.split(cmd), input=json.dumps({"describe": True}),
                              capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise EvidenceUnavailable(f"judge did not describe itself within {timeout}s")
    except OSError as e:
        raise EvidenceUnavailable(f"judge command could not run: {e}")
    if proc.returncode != 0:
        raise EvidenceUnavailable(f"judge describe exited {proc.returncode}: {proc.stderr.strip()}")
    try:
        described = json.loads(proc.stdout)
        digest = described["instruction_template_digest"]
    except (json.JSONDecodeError, KeyError, TypeError):
        raise EvidenceUnavailable(f"judge did not report an instruction_template_digest: {proc.stdout[:200]!r}")
    if not isinstance(digest, str) or len(digest) != 64:
        raise EvidenceUnavailable(f"judge reported a malformed instruction_template_digest: {digest!r}")
    return digest


def min_confidence_micros(spec):
    value = (spec.get("judge") or {}).get("min_confidence")
    if value is None:
        return None
    return int(round(value * 1_000_000))


def pin_input(spec, root, judge_model_id, instruction_template_digest):
    """The exact JSON `capsulectl judge pin` is given. Pure apart from hashing the
    prompt and axes files the spec names."""
    sampling = dict(spec["judge"].get("sampling_params") or {})
    reserved = {"pack_source_digest", "instruction_template_digest", "min_confidence_micros"} & set(sampling)
    if reserved:
        raise EvidenceUnavailable(f"judge.sampling_params uses reserved key(s) {sorted(reserved)!r}")
    if spec.get("pack_source_digest"):
        sampling["pack_source_digest"] = spec["pack_source_digest"]
    sampling["instruction_template_digest"] = instruction_template_digest
    micros = min_confidence_micros(spec)
    if micros is not None:
        sampling["min_confidence_micros"] = micros
    return {"model_id": judge_model_id,
            "prompt_digest": sha256_file(root / spec["judge"]["prompt"]),
            "axes_digest": sha256_file(root / spec["judge"]["axes"]),
            "sampling_params": sampling}
