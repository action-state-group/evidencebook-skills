#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# The local check before a push (asg-agent-team-ethan#409): every job of the
# two CI workflows, with the commands and flags CI runs, on this machine.
#
#   scripts/check.sh          the pull request set (fast.yml) and the suites
#                             that run only nightly and on main (tests.yml)
#   scripts/check.sh --full   the same set: main and nightly run no suite the
#                             pull request path did not run before #409, so
#                             there is nothing more to add here
#
# Every job runs; the exit status is non-zero when any failed. The pins
# (commits, tags, release versions) are read from the workflow files, so they
# stay the one source. Pinned checkouts, built binaries, released binaries and
# Python environments are kept in ~/.cache/evidencebook-skills-check
# (CHECK_DEPS) and reused. A short path: pip and uv write a console script's
# shebang only when its interpreter path is short, and the live-engine test
# reads that shebang.
#
# Needs: git, gh (signed in: the pinned checkouts and releases are
# action-state-group's), Go, uv (it provides Python 3.12), python3 and Google
# Chrome (the report pages' check). No secret: nothing here calls a model.
# Released binaries are taken for this machine's platform (darwin-arm64 or
# linux-amd64), where CI takes linux-amd64.
set -euo pipefail
if ((BASH_VERSINFO[0] * 100 + BASH_VERSINFO[1] < 404)); then
  echo "check.sh: needs bash 4.4 or later (macOS: brew install bash)" >&2
  exit 2
fi
# A failure inside $(...) fails the job too.
shopt -s inherit_errexit

case "${1:-}" in
  "" | --full) ;;
  *) echo "usage: scripts/check.sh [--full]" >&2; exit 2 ;;
esac

root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"
deps=${CHECK_DEPS:-${XDG_CACHE_HOME:-$HOME/.cache}/evidencebook-skills-check}
mkdir -p "$deps"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) plat=darwin-arm64 ;;
  Linux-x86_64) plat=linux-amd64 ;;
  *) echo "check.sh: no released binaries for $(uname -s)-$(uname -m)" >&2; exit 2 ;;
esac
for tool in git gh go uv python3; do
  command -v "$tool" >/dev/null || { echo "check.sh: $tool is not on PATH" >&2; exit 2; }
done

# pin WORKFLOW JOB KEY: the value of KEY in JOB's env block of WORKFLOW.
pin() {
  local v
  v=$(awk -v job="  $2:" -v key="$3:" '$0 == job { f = 1; next } f && /^  [A-Za-z0-9_-]+:/ { f = 0 }
    f && $1 == key { print $2; exit }' ".github/workflows/$1")
  [[ -n "$v" ]] || { echo "check.sh: no $3 in job $2 of $1" >&2; return 1; }
  printf '%s\n' "$v"
}

# checkout REPO REF: a checkout of action-state-group/REPO at REF under .deps; prints its path.
checkout() {
  local dir="$deps/src/$1@${2//\//_}"
  if [[ "$(cat "$dir/.pinned" 2>/dev/null)" != "$2" ]]; then
    rm -rf "$dir"
    git init -q "$dir"
    git -C "$dir" fetch -q --depth 1 "https://github.com/action-state-group/$1.git" "$2"
    git -C "$dir" checkout -q --detach FETCH_HEAD
    printf '%s\n' "$2" >"$dir/.pinned"
  fi
  printf '%s\n' "$dir"
}

# venv NAME PIP-ARGS...: a Python 3.12 environment with PIP-ARGS installed; prints its path.
venv() {
  local dir="$deps/venv/$1" want
  shift
  want="pip: $*"
  if [[ "$(cat "$dir/.installed" 2>/dev/null)" != "$want" ]]; then
    rm -rf "$dir"
    uv venv -q --python 3.12 "$dir" >&2
    (($# == 0)) || uv pip install -q --python "$dir/bin/python" "$@" >&2
    printf '%s\n' "$want" >"$dir/.installed"
  fi
  printf '%s\n' "$dir"
}

# req_venv: the name of the requirements.txt environment, keyed by the file's content so an edit rebuilds it.
req_venv() {
  local h
  h=$(shasum -a 256 requirements.txt | cut -c1-12)
  printf 'requirements-%s\n' "$h"
}

# engine REF: capsule-engine (Go) built from REF; prints the binary's path.
engine() {
  local out="$deps/bin/capsule-engine@${1//\//_}" src
  if [[ ! -x "$out" ]]; then
    src=$(checkout capsule-engine "$1")
    mkdir -p "$deps/bin"
    (cd "$src/go" && go build -o "$out" ./cmd/capsule-engine)
  fi
  printf '%s\n' "$out"
}

# release REPO TAG NAME: the released binary NAME (checked against the release's SHA256SUMS); prints its path.
release() {
  local d="$deps/release/$1/${2//\//_}"
  if [[ ! -x "$d/$3" ]]; then
    mkdir -p "$d"
    gh release download "$2" -R "action-state-group/$1" -D "$d" --clobber -p SHA256SUMS -p "$3" >&2
    (cd "$d" && grep " $3\$" SHA256SUMS | shasum -a 256 -c - >&2)
    chmod 755 "$d/$3"
  fi
  printf '%s\n' "$d/$3"
}

# plugins NAME=PATH...: a plugin root holding a copy of each PATH as NAME, as CI installs them; prints its path.
plugins() {
  local d
  d=$(mktemp -d "$tmp/plugins.XXXX")
  chmod 755 "$d"
  for p in "$@"; do install -m 755 "${p#*=}" "$d/${p%%=*}"; done
  printf '%s\n' "$d"
}

job_unit() {
  local ref aac py req
  req=$(req_venv)
  ref=$(pin fast.yml unit AAC_REF)
  aac=$(checkout agent-action-capsule "$ref")
  py=$(venv "$req" -r requirements.txt)
  AAC_CHECKOUT=$aac PATH="$py/bin:$PATH" python -m unittest discover -s tests -p 'test_*.py'
}

job_ard_demo() {
  local w=tests.yml eb_ref ce_tag tag viewer eb ce deal py
  eb_ref=$(pin $w ard-demo EVIDENCEBOOK_REF)
  ce_tag=$(pin $w ard-demo CAPSULE_ENGINE_TAG)
  tag=$(pin $w ard-demo CAPSULECTL_DEAL_TAG)
  viewer=$(pin $w ard-demo CAPSULE_VIEWER_REF)
  eb=$(checkout evidencebook "$eb_ref")
  ce=$(engine "$ce_tag")
  deal=$(release evidencebook "$tag" "capsulectl-deal-${tag#capsulectl/}-$plat")
  py=$(venv "ard-${eb_ref:0:12}-${viewer:0:12}" "$eb/python" pyyaml rfc8785 websockets "mcp==2.3.0" pytest pytest-xdist \
    "capsule-viewer @ git+https://github.com/action-state-group/capsule-viewer@$viewer")
  ARD_EVIDENCEBOOK="$eb" CAPSULE_ENGINE="$ce" CAPSULECTL_DEAL="$deal" PATH="$py/bin:$PATH" \
    python -m pytest -q --durations=40 -n 4 --dist loadfile demo/ard/tests
}

job_admission_engine() {
  local ref ce py req
  ref=$(pin fast.yml admission-engine CAPSULE_ENGINE_REF)
  ce=$(engine "$ref")
  req=$(req_venv)
  py=$(venv "$req" -r requirements.txt)
  CAPSULE_ENGINE="$ce" CAPSULE_ENGINE_REF="$ref" PATH="$py/bin:$PATH" python -m unittest tests.test_pack_schema.RealAdmissionEngine -v
}

job_live_engine() {
  local ref eng py req
  ref=$(pin fast.yml live-engine CAPSULE_ENGINE_PY_REF)
  eng=$(venv "engine-py-${ref:0:12}" "git+https://github.com/action-state-group/capsule-engine@${ref}#subdirectory=python")
  req=$(req_venv)
  py=$(venv "$req" -r requirements.txt)
  CAPSULE_LIVE_ENGINE="$eng/bin/capsule-engine" CAPSULE_ENGINE_PY_REF="$ref" PATH="$py/bin:$PATH" python -m unittest tests.test_pack_schema.RealLiveEngine -v
}

job_report_grades() {
  local eb_ref cli_ref eb cli bin="$tmp/report-grades" roots py
  eb_ref=$(pin fast.yml report-grades EVIDENCEBOOK_REF)
  cli_ref=$(pin fast.yml report-grades CAPSULE_CLI_REF)
  eb=$(checkout evidencebook "$eb_ref")
  cli=$(checkout capsule-cli "$cli_ref")
  mkdir -p "$bin"
  (cd "$cli" && go build -o "$bin/capsulectl" ./cmd/capsulectl)
  (cd "$eb/capsulectl" && go build -o "$bin/capsulectl-book" ./cmd/capsulectl-book)
  roots=$(plugins "capsulectl-book=$bin/capsulectl-book")
  py=$(venv report pyyaml rfc8785)
  CAPSULECTL="$bin/capsulectl" CAPSULECTL_PLUGIN_ROOTS="$roots" PATH="$py/bin:$PATH" bash tests/fresh_env_report.sh
  CAPSULECTL="$bin/capsulectl" CAPSULECTL_PLUGIN_ROOTS="$roots" PATH="$py/bin:$PATH" bash tests/fresh_env_deals.sh
}

job_obligations_report() {
  local v ctl book roots py
  v=$(pin fast.yml obligations-report CAPSULECTL_VERSION)
  ctl=$(release capsule-cli "$v" "capsulectl-$v-$plat")
  book=$(release evidencebook "capsulectl/$v" "capsulectl-book-$v-$plat")
  roots=$(plugins "capsulectl-book=$book")
  py=$(venv bare)
  CAPSULECTL="$ctl" CAPSULECTL_PLUGIN_ROOTS="$roots" PATH="$py/bin:$PATH" bash tests/fresh_env_obligations.sh
}

job_tau2_live() {
  # The tests' directory as a variable: tests/test_scripts.py takes a literal
  # path under tests/ in scripts/ for a citation of this repository's tests/.
  local v ref ce ctl deal book roots bin="$tmp/tau2-bin" t=demo/tau2-live/tests
  v=$(pin tests.yml tau2-live CAPSULECTL_VERSION)
  ref=$(pin tests.yml tau2-live CAPSULE_ENGINE_REF)
  ce=$(engine "$ref")
  ctl=$(release capsule-cli "$v" "capsulectl-$v-$plat")
  deal=$(release evidencebook "capsulectl/$v" "capsulectl-deal-$v-$plat")
  book=$(release evidencebook "capsulectl/$v" "capsulectl-book-$v-$plat")
  roots=$(plugins "capsulectl-deal=$deal" "capsulectl-book=$book")
  mkdir -p "$bin"
  ln -sf "$ctl" "$bin/capsulectl"
  ln -sf "$ce" "$bin/capsule-engine"
  (
    cd demo/tau2-live
    export PATH="$bin:$PATH"
    uv run --group dev pytest -q tests
    CAPSULECTL_PLUGIN_ROOTS="$roots" uv run python "$root/$t/e2e_scripted.py" "$tmp/tau2-live"
    CAPSULECTL_PLUGIN_ROOTS="$roots" python3 "$root/$t/e2e_range.py" "$tmp/tau2-range"
  )
}

failed=()
summary=()
for job in unit admission-engine live-engine report-grades obligations-report ard-demo tau2-live; do
  printf '\n=== %s\n' "$job"
  start=$SECONDS
  # Not in an `if`: errexit would be off inside the job.
  set +e
  (set -e; "job_${job//-/_}")
  rc=$?
  set -e
  if ((rc == 0)); then status=pass; else status=FAIL; failed+=("$job"); fi
  summary+=("$(printf '%-20s %s  %ds' "$job" "$status" $((SECONDS - start)))")
done
printf '\n'
printf '%s\n' "${summary[@]}"
if ((${#failed[@]})); then
  printf 'check.sh: FAILED: %s\n' "${failed[*]}" >&2
  exit 1
fi
echo "check.sh: all jobs passed"
