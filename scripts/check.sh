#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# The local check before a push (asg-agent-team-ethan#409): every job of the
# two CI workflows, with the commands and flags CI runs, on this machine.
#
#   scripts/check.sh          the pull request set (fast.yml) and the suites
#                             that run only nightly and on main (tests.yml),
#                             ard-demo only when the change can affect it
#   scripts/check.sh --full   every job, ard-demo included whatever changed
#   scripts/check.sh --plan   print which jobs a run would take, and why, and
#                             run none (with --full: the full set)
#
# ard-demo (its end-to-end test runs both deals on a witness it starts) runs
# only when a file it reads changed since the merge base with origin/main:
# committed, staged, unstaged or untracked, a rename counted at both its old
# and new path (ARD_INPUTS below; evidencebook-skills#374). Without a merge
# base it runs. Every other job always runs; the exit status is non-zero when
# any failed. CI's tests.yml still runs ard-demo in full on main and nightly.
#
# The pins (commits, tags, release versions) are read from the workflow files, so they
# stay the one source; the one exception is ard-demo's end-to-end test, which
# here stamps on a witness started on this machine where CI uses the hosted
# one (LOCAL_WITNESS_REF below, evidencebook-skills#371). Pinned checkouts,
# built binaries, released binaries and Python environments are kept in
# ~/.cache/evidencebook-skills-check (CHECK_DEPS) and reused. A short path: pip and uv write a console script's
# shebang only when its interpreter path is short, and the live-engine test
# reads that shebang.
#
# Needs: git, gh (signed in: the pinned checkouts and releases are
# action-state-group's), Go, uv (it provides Python 3.12), python3 and Google
# Chrome (the report pages' check), openssl, and network: ard-demo's end-to-end
# test stamps on a capsule-anchor witness it starts on this machine (never the
# hosted one, evidencebook-skills#371) and viewer-drift reads capsule-viewer's
# release tags. No secret: nothing here calls a model.
# Released binaries are taken for this machine's platform (darwin-arm64 or
# linux-amd64), where CI takes linux-amd64.
set -euo pipefail
if ((BASH_VERSINFO[0] * 100 + BASH_VERSINFO[1] < 404)); then
  echo "check.sh: needs bash 4.4 or later (macOS: brew install bash)" >&2
  exit 2
fi
# A failure inside $(...) fails the job too.
shopt -s inherit_errexit

full=0 plan=0
for arg in "$@"; do
  case "$arg" in
    --full) full=1 ;;
    --plan) plan=1 ;;
    *) echo "usage: scripts/check.sh [--full] [--plan]" >&2; exit 2 ;;
  esac
done

root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"

jobs=(unit viewer-drift admission-engine live-engine report-grades obligations-report ard-demo tau2-live)

# What ard-demo reads in this repository, besides the pinned checkouts and binaries: the demo itself; the
# skills (demo/ard/goose/open-windows.py and its tests read skills/*/SKILL.md); the pack compiler that
# demo/ard/pack.py runs (scripts/pack_compile.py and the modules it imports) and this script; the pack, schema,
# vocabulary, wording and contract data those modules may read; and tests.yml, which holds the job's pins. A
# directory ends in "/".
ARD_INPUTS=(demo/ard/ skills/ scripts/ packs/ schemas/ vocab/ wording/ contracts/ .github/workflows/tests.yml)

# select_ard: sets ard_runs (1 or 0) and ard_why, the one line that says why.
select_ard() {
  local base f p list
  local -a changed
  ard_runs=1
  if ((full)); then
    ard_why="ard-demo: runs (--full)"
    return
  fi
  if ! base=$(git merge-base HEAD origin/main 2>/dev/null); then
    ard_why="ard-demo: runs (no merge base with origin/main, so the change is not known)"
    return
  fi
  # --no-renames: a rename is a deletion and an addition, so a file moved out of the inputs still counts.
  # Through a file, not a process substitution, so a failing git is seen (and NULs survive, which $(...) drops).
  list=$(mktemp)
  if ! { git diff --no-renames --name-only -z "$base" -- >"$list" && git ls-files --others --exclude-standard -z >>"$list"; }; then
    rm -f "$list"
    ard_why="ard-demo: runs (git could not list the files changed since the merge base with origin/main)"
    return
  fi
  mapfile -d '' changed <"$list"
  rm -f "$list"
  for f in "${changed[@]}"; do
    for p in "${ARD_INPUTS[@]}"; do
      if [[ "$f" == "$p" || ( "$p" == */ && "$f" == "$p"* ) ]]; then
        ard_why="ard-demo: runs ($f changed since the merge base with origin/main, ${base:0:12})"
        return
      fi
    done
  done
  ard_runs=0
  ard_why="ard-demo: skipped (no change since the merge base with origin/main, ${base:0:12}, touches its inputs: ${ARD_INPUTS[*]}; scripts/check.sh --full runs it)"
}

select_ard
if ((plan)); then
  for job in "${jobs[@]}"; do
    [[ "$job" == ard-demo ]] || printf '%s: runs\n' "$job"
  done
  printf '%s\n' "$ard_why"
  exit 0
fi
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

# deps_lock / deps_unlock: hold the cache's lock while filling an entry, so two runs at the same time (two lanes'
# checks under asg-gate's --heavy class, say) never build or delete the same entry at once. Each entry is keyed by
# what it holds and marked complete last, so a complete entry is never rebuilt and is read without the lock. The
# lock is an flock held by a python3 child that exits when its stdin closes: when this shell ends, crashed or not,
# the lock goes with it. Nested calls (engine's checkout) take it once.
deps_lock_depth=0
deps_lock() {
  if ((deps_lock_depth++ == 0)); then
    coproc DEPS_LOCK { python3 -c 'import fcntl, sys
f = open(sys.argv[1], "a")
fcntl.flock(f, fcntl.LOCK_EX)
print("locked", flush=True)
sys.stdin.read()' "$deps/.lock"; }
    local ack
    read -r ack <&"${DEPS_LOCK[0]}"
    [[ "$ack" == locked ]] || { echo "check.sh: could not lock $deps" >&2; return 1; }
  fi
}
deps_unlock() {
  if ((--deps_lock_depth == 0)); then
    local pid=$DEPS_LOCK_PID
    exec {DEPS_LOCK[1]}>&-
    wait "$pid"
  fi
}

# checkout REPO REF: a checkout of action-state-group/REPO at REF under .deps; prints its path.
checkout() {
  local dir="$deps/src/$1@${2//\//_}"
  if [[ "$(cat "$dir/.pinned" 2>/dev/null)" != "$2" ]]; then
    deps_lock
    if [[ "$(cat "$dir/.pinned" 2>/dev/null)" != "$2" ]]; then
      rm -rf "$dir"
      git init -q "$dir"
      git -C "$dir" fetch -q --depth 1 "https://github.com/action-state-group/$1.git" "$2"
      git -C "$dir" checkout -q --detach FETCH_HEAD
      printf '%s\n' "$2" >"$dir/.pinned"
    fi
    deps_unlock
  fi
  printf '%s\n' "$dir"
}

# venv NAME PIP-ARGS...: a Python 3.12 environment with PIP-ARGS installed; prints its path. Its directory is keyed
# by PIP-ARGS too, so a branch that changes them builds its own and never replaces one another run is using.
venv() {
  local name=$1 dir want
  shift
  want="pip: $*"
  dir="$deps/venv/$name-$(printf '%s' "$want" | shasum -a 256 | cut -c1-8)"
  if [[ "$(cat "$dir/.installed" 2>/dev/null)" != "$want" ]]; then
    deps_lock
    if [[ "$(cat "$dir/.installed" 2>/dev/null)" != "$want" ]]; then
      rm -rf "$dir"
      uv venv -q --python 3.12 "$dir" >&2
      (($# == 0)) || uv pip install -q --python "$dir/bin/python" "$@" >&2
      printf '%s\n' "$want" >"$dir/.installed"
    fi
    deps_unlock
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
    deps_lock
    if [[ ! -x "$out" ]]; then
      src=$(checkout capsule-engine "$1")
      mkdir -p "$deps/bin"
      (cd "$src/go" && go build -o "$out.partial" ./cmd/capsule-engine)
      mv "$out.partial" "$out"
    fi
    deps_unlock
  fi
  printf '%s\n' "$out"
}

# release REPO TAG NAME: the released binary NAME (checked against the release's SHA256SUMS); prints its path.
release() {
  local d="$deps/release/$1/${2//\//_}"
  if [[ ! -x "$d/$3" ]]; then
    deps_lock
    if [[ ! -x "$d/$3" ]]; then
      mkdir -p "$d"
      gh release download "$2" -R "action-state-group/$1" -D "$d" --clobber -p SHA256SUMS -p "$3" >&2
      (cd "$d" && grep " $3\$" SHA256SUMS | shasum -a 256 -c - >&2)
      chmod 755 "$d/$3"
    fi
    deps_unlock
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

# stage_port: a free ARD_STAGE_PORT for the demo's end-to-end test. It serves the registry on that port and the
# two sellers on port+10 and port+11; its default (47681) is shared by every checkout on this machine, so a second
# run at the same time (another clone's check, a lane's own run) would fail with "Address already in use".
stage_port() {
  python3 - <<'PY'
import random, socket
for _ in range(200):
    base = random.randrange(20000, 60000)
    socks = []
    try:
        for port in (base, base + 10, base + 11):
            s = socket.socket()
            socks.append(s)
            s.bind(("127.0.0.1", port))
    except OSError:
        continue
    finally:
        for s in socks:
            s.close()
    print(base)
    break
else:
    raise SystemExit("no free ARD_STAGE_PORT")
PY
}

# The witness the local check's ard-demo end-to-end test stamps on (evidencebook-skills#371): capsule-anchor at the
# release Action State's hosted witness runs, v0.1.4 (Cloud Run capsule-witness, revision capsule-witness-00014-b6h,
# label git-sha=78a69853bc83, read on 2026-11-26), started by capsule-anchor's own ci/local-witness/start.sh (#118) on
# https://localhost:<free port> with a throwaway key, an in-memory store and a self-signed certificate that
# capsulectl trusts through SSL_CERT_FILE. Local only: tests.yml keeps CI's run on main and nightly on the hosted
# witness, so that path stays covered.
LOCAL_WITNESS_REF=78a69853bc83c9c65b9fe79a8270b83727c55304 # capsule-anchor v0.1.4: move it with the hosted witness
LOCAL_WITNESS_START_REF=42f5fab488d2edc1fe7338f7da09a31de1b0d5b7 # capsule-anchor main: ci/local-witness (#118)

# local_witness DIR: start that witness with its files under DIR; prints the url=, public-key=, ca-bundle= and log=
# lines start.sh writes, and leaves its process id in DIR/local-witness/pid.
local_witness() {
  local src tools out="$1/outputs"
  src=$(checkout capsule-anchor "$LOCAL_WITNESS_REF")
  tools=$(checkout capsule-anchor "$LOCAL_WITNESS_START_REF")
  # start.sh pip-installs SRC, and setuptools writes build/ into the source it builds: a copy of this run's own, so two
  # runs never write into the shared cached checkout at once (evidencebook-skills#372).
  cp -R "$src" "$1/capsule-anchor"
  src=$1/capsule-anchor
  : >"$out"
  # BLOCK=false: blocking the hosted witness's names in /etc/hosts needs sudo; the end-to-end step routes every
  # other host to a closed port instead (job_ard_demo).
  # start.sh checks the witness on localhost with curl and urllib: an inherited proxy must not take those calls, while
  # it may still be what pip needs to install capsule-anchor.
  NO_PROXY="localhost,127.0.0.1${NO_PROXY:+,$NO_PROXY}" no_proxy="localhost,127.0.0.1${no_proxy:+,$no_proxy}" \
    RUNNER_TEMP="$1" SRC="$src" BLOCK=false GITHUB_OUTPUT="$out" PYTHON="$(uv python find 3.12)" \
    bash "$tools/ci/local-witness/start.sh" >&2
  cat "$out"
}

job_ard_demo() {
  # The tests' directory as a variable, for the same reason as in job_tau2_live.
  local w=tests.yml eb_ref ce_tag cli_ref anchor_ref eb ce deal core cpy py port t=demo/ard/tests wdir outs url key ca log
  eb_ref=$(pin $w ard-demo EVIDENCEBOOK_REF)
  cli_ref=$(pin $w ard-demo CAPSULE_CLI_REF)
  ce_tag=$(pin $w ard-demo CAPSULE_ENGINE_TAG)
  eb=$(checkout evidencebook "$eb_ref")
  ce=$(engine "$ce_tag")
  # capsulectl-deal is built from the pinned evidencebook checkout, as CI builds it.
  deal="$deps/bin/capsulectl-deal@$eb_ref"
  if [[ ! -x "$deal" ]]; then
    deps_lock
    if [[ ! -x "$deal" ]]; then
      mkdir -p "$deps/bin"
      (cd "$eb/capsulectl" && go build -o "$deal.partial" ./cmd/capsulectl-deal)
      mv "$deal.partial" "$deal"
    fi
    deps_unlock
  fi
  # capsulectl itself, for the countersign upgrade's `countersign request` (#383).
  core="$deps/bin/capsulectl@$cli_ref"
  if [[ ! -x "$core" ]]; then
    deps_lock
    if [[ ! -x "$core" ]]; then
      mkdir -p "$deps/bin"
      (cd "$(checkout capsule-cli "$cli_ref")" && go build -o "$core.partial" ./cmd/capsulectl)
      mv "$core.partial" "$core"
    fi
    deps_unlock
  fi
  # The demo's countersigner (demo/ard/countersigner.py) at its own pin, installed here: the end-to-end step below
  # reaches no host but this machine, so it cannot install capsule-anchor itself.
  anchor_ref=$(sed -n 's/^ANCHOR_REF = "\([0-9a-f]*\)"$/\1/p' demo/ard/countersigner.py)
  cpy=$(venv "countersigner-${anchor_ref:0:12}" "capsule-anchor @ git+https://github.com/action-state-group/capsule-anchor@$anchor_ref")
  py=$(venv ard cryptography pyyaml rfc8785 "mcp==2.3.0" pytest pytest-xdist)
  ARD_EVIDENCEBOOK="$eb" CAPSULE_ENGINE="$ce" CAPSULECTL_DEAL="$deal" PATH="$py/bin:$PATH" \
    python -m pytest -q --durations=20 -n 4 --dist loadfile "$t" --ignore "$t/test_e2e.py"
  # Both deals end to end, on a witness this run starts (local_witness), where CI uses the hosted one. Every
  # host but this machine goes through a proxy on a closed port, so a call that still reaches for the hosted
  # witness fails the run instead of loading it.
  wdir=$(mktemp -d "$tmp/witness.XXXX")
  # The job runs in its own subshell, so this trap fires when the job ends, after its locals are gone: the path is
  # written into it now.
  trap "kill \"\$(cat '$wdir/local-witness/pid' 2>/dev/null)\" 2>/dev/null || true" EXIT
  outs=$(local_witness "$wdir")
  url=$(sed -n 's/^url=//p' <<<"$outs")
  key=$(sed -n 's/^public-key=//p' <<<"$outs")
  ca=$(sed -n 's/^ca-bundle=//p' <<<"$outs")
  log=$(sed -n 's/^log=//p' <<<"$outs")
  port=$(stage_port)
  ARD_E2E=1 ARD_STAGE_PORT="$port" ARD_EVIDENCEBOOK="$eb" CAPSULE_ENGINE="$ce" CAPSULECTL_DEAL="$deal" PATH="$py/bin:$PATH" \
    CAPSULECTL="$core" ARD_COUNTERSIGN_PYTHON="$cpy/bin/python" \
    ARD_E2E_WITNESS_URL="$url" ARD_E2E_WITNESS_KEY="$key" SSL_CERT_FILE="$ca" \
    HTTPS_PROXY=http://127.0.0.1:9 HTTP_PROXY=http://127.0.0.1:9 https_proxy=http://127.0.0.1:9 http_proxy=http://127.0.0.1:9 \
    NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1 \
    python -m pytest -v "$t/test_e2e.py"
  # The run stamped on this witness, not on none (capsule-anchor's ci/local-witness/check does the same in CI).
  grep -qE '"POST /checkpoints HTTP/[0-9.]+" 2[0-9][0-9]' "$log" || { cat "$log" >&2; echo "ard-demo: the local witness took no stamp" >&2; return 1; }
}

job_viewer_drift() {
  local py
  py=$(venv bare)
  PATH="$py/bin:$PATH" python demo/ard/viewer_drift.py
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
printf '%s\n' "$ard_why"
for job in "${jobs[@]}"; do
  if [[ "$job" == ard-demo ]] && ((!ard_runs)); then
    summary+=("$(printf '%-20s %s' "$job" skipped)")
    continue
  fi
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
