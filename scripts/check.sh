#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# The local check before a push (asg-agent-team-ethan#409): every job of the
# two CI workflows, with the commands and flags CI runs, on this machine.
#
#   scripts/check.sh          every job but the two end-to-end ones: the pull
#                             request set (fast.yml), the checks of
#                             contracts.yml and neutrality.yml, and the unit
#                             tests tests.yml's ard-demo and tau2-live jobs run
#                             (ard-demo-unit, tau2-live-unit)
#   scripts/check.sh --full   every job, ard-demo and tau2-live (tests.yml)
#                             included
#   scripts/check.sh --plan   print which jobs a run would take and run none
#                             (with --full: the full set)
#
# ard-demo and tau2-live, the end-to-end runs of tests.yml's two jobs, run
# only with --full: ard-demo takes about 8 minutes on its own (tau2-live under
# a minute since #431), and the check before every push stays well under 10
# (evidencebook-skills#425). CI's tests.yml runs both nightly and on every push
# to main that changes their inputs. The exit status is non-zero when any job
# that ran failed.
#
# The jobs see none of this shell's ARD_* variables, and each runs with fresh,
# empty demo folders of its own (ARD_HOME and the rest, demo_homes below),
# removed when the run ends: a laptop's seeded ~/.config/ard-commerce-demo is
# never read or written, so the check tests what CI's clean runner tests
# (evidencebook-skills#357).
#
# The pins (commits, tags, release versions) are read from the workflow files, so they
# stay the one source. ard-demo's end-to-end test stamps on a witness started on
# this machine, as CI's local leg does (local_witness below, evidencebook-skills#371,
# #378); CI's hosted leg, nightly only, is not run here. Pinned checkouts,
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

# The demo's settings come from the jobs alone, as on CI's clean runner (evidencebook-skills#357): a variable this
# shell exported (ARD_HOME, ARD_RAIL, ARD_WITNESS ...) is dropped, and each job gets fresh, empty demo folders of its own
# (demo_homes below).
while read -r var; do unset "$var"; done < <(compgen -e | grep '^ARD_' || true)

jobs=(unit viewer-drift admission-engine live-engine report-grades obligations-report contracts neutrality ard-demo-unit
  tau2-live-unit ard-demo tau2-live)

# The end-to-end jobs, run only with --full.
e2e=(ard-demo tau2-live)

# runs JOB: whether this run takes JOB.
runs() {
  ((full)) || [[ " ${e2e[*]} " != *" $1 "* ]]
}

if ((plan)); then
  for job in "${jobs[@]}"; do
    if runs "$job"; then printf '%s: runs\n' "$job"; else printf '%s: skipped (scripts/check.sh --full runs it)\n' "$job"; fi
  done
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
  gobuild "$(checkout capsule-engine "$1")/go" capsule-engine "$1" ./cmd/capsule-engine
}

# gobuild DIR NAME REF PKG: NAME built from package PKG in DIR, a checkout at REF, kept in the cache by NAME and REF;
# prints the binary's path.
gobuild() {
  local out="$deps/bin/$2@${3//\//_}"
  if [[ ! -x "$out" ]]; then
    deps_lock
    if [[ ! -x "$out" ]]; then
      mkdir -p "$deps/bin"
      (cd "$1" && go build -o "$out.partial" "$4")
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

# The witness ard-demo's end-to-end test stamps on, here as in CI's local leg (evidencebook-skills#371, #378):
# capsule-anchor at tests.yml's LOCAL_WITNESS_REF (the release Action State's hosted witness runs), started by
# capsule-anchor's own ci/local-witness/start.sh (#118, at LOCAL_WITNESS_START_REF) on https://localhost:<free port>
# with a throwaway key, an in-memory store and a self-signed certificate that capsulectl trusts through SSL_CERT_FILE.
# CI's hosted leg (nightly and by hand) keeps the hosted witness's path covered; the local check never loads it.

# local_witness DIR: start that witness with its files under DIR; prints the url=, public-key=, ca-bundle= and log=
# lines start.sh writes, and leaves its process id in DIR/local-witness/pid.
local_witness() {
  local src tools out="$1/outputs"
  src=$(checkout capsule-anchor "$(pin tests.yml ard-demo LOCAL_WITNESS_REF)")
  tools=$(checkout capsule-anchor "$(pin tests.yml ard-demo LOCAL_WITNESS_START_REF)")
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

# ard_setup: the pinned evidencebook checkout and the binaries and Python environments ard-demo's two jobs use, in
# the caller's locals eb, ce, deal, core, cpy and py (each is fetched or built once and kept in the cache).
ard_setup() {
  local w=tests.yml eb_ref ce_tag v anchor_ref
  eb_ref=$(pin $w ard-demo EVIDENCEBOOK_REF)
  v=$(pin $w ard-demo CAPSULECTL_VERSION)
  ce_tag=$(pin $w ard-demo CAPSULE_ENGINE_TAG)
  eb=$(checkout evidencebook "$eb_ref")
  ce=$(engine "$ce_tag")
  # capsulectl-deal and capsulectl itself (the countersign upgrade's `countersign request`, #383): the release the
  # RUNBOOK installs, as CI installs it (#435).
  deal=$(release evidencebook "capsulectl/$v" "capsulectl-deal-$v-$plat")
  core=$(release capsule-cli "$v" "capsulectl-$v-$plat")
  # The demo's countersigner (demo/ard/countersigner.py) at its own pin, installed here: the end-to-end step below
  # reaches no host but this machine, so it cannot install capsule-anchor itself.
  anchor_ref=$(sed -n 's/^ANCHOR_REF = "\([0-9a-f]*\)"$/\1/p' demo/ard/countersigner.py)
  cpy=$(venv "countersigner-${anchor_ref:0:12}" "capsule-anchor @ git+https://github.com/action-state-group/capsule-anchor@$anchor_ref")
  py=$(venv ard cryptography pyyaml rfc8785 "mcp==2.3.0" pytest pytest-xdist)
}

# ard-demo's tests but the end-to-end one, as tests.yml's ard-demo job runs them first.
job_ard_demo_unit() {
  # The tests' directory as a variable, for the same reason as in job_tau2_live.
  local eb ce deal core cpy py t=demo/ard/tests
  ard_setup
  ARD_EVIDENCEBOOK="$eb" CAPSULE_ENGINE="$ce" CAPSULECTL_DEAL="$deal" PATH="$py/bin:$PATH" \
    python -m pytest -q --durations=20 -n 4 --dist loadfile "$t" --ignore "$t/test_e2e.py"
}

job_ard_demo() {
  local eb ce deal core cpy py port t=demo/ard/tests wdir outs url key ca log
  ard_setup
  # Both deals end to end, on a witness this run starts (local_witness), as CI's local leg does. Every
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
  # How many checkpoints the run sent, all to this witness (evidencebook-skills#453): the hosted one gets none.
  echo "ard-demo: the local witness answered $(grep -cE '"POST /checkpoints HTTP/' "$log") POST /checkpoints"
}

# contracts.yml's add-only rule on what a push sends: the commits since the merge base with origin/main (a pull
# request's base), as CI compares its base with the pull request's head. A published contract
# (contracts/<id>/<version>.json) is never modified, deleted or renamed.
job_contracts() {
  local base diff changed
  base=$(git merge-base HEAD origin/main) || { echo "contracts: no merge base with origin/main" >&2; return 1; }
  diff=$(git diff --name-status --no-renames "$base" HEAD -- contracts/)
  changed=$(grep -v '^A' <<<"$diff" || true)
  if [[ -n "$changed" ]]; then
    echo "A published contract is immutable; publish a new version instead:"
    echo "$changed"
    return 1
  fi
  echo "contracts/: additions only"
}

# neutrality.yml: the scan with the scanner origin/main holds (CI runs the base branch's scanner on a pull request's
# files as data, so a branch's own edit to the scanner never judges itself), after that scanner's self-test. The term
# list is the repository secret NEUTRALITY_TERMS, which this public repository does not hold: it is read from the
# file $NEUTRALITY_TERMS_FILE (default ~/.config/evidencebook-skills/neutrality-terms.json, the secret's JSON) and
# given to the scanner process alone. Without that file the scan is reported NOT RUN in the summary, never a pass.
job_neutrality() {
  local py scanner terms=${NEUTRALITY_TERMS_FILE:-$HOME/.config/evidencebook-skills/neutrality-terms.json}
  py=$(venv bare)
  scanner=$tmp/neutrality_scan.py
  git show origin/main:.github/neutrality_scan.py >"$scanner"
  "$py/bin/python" "$scanner" --self-test
  if [[ ! -f "$terms" ]]; then
    # The summary line carries it too (a job's note file), so the run's last lines say the scan did not run.
    echo "the scan NOT RUN: no term list at $terms" | tee "$tmp/neutrality.note"
    return 0
  fi
  NEUTRALITY_TERMS=$(<"$terms") NEUTRALITY_REVEAL=true "$py/bin/python" "$scanner" .
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
  local eb_ref cli_ref eb cli ctl book roots py
  eb_ref=$(pin fast.yml report-grades EVIDENCEBOOK_REF)
  cli_ref=$(pin fast.yml report-grades CAPSULE_CLI_REF)
  eb=$(checkout evidencebook "$eb_ref")
  cli=$(checkout capsule-cli "$cli_ref")
  ctl=$(gobuild "$cli" capsulectl "$cli_ref" ./cmd/capsulectl)
  book=$(gobuild "$eb/capsulectl" capsulectl-book "$eb_ref" ./cmd/capsulectl-book)
  roots=$(plugins "capsulectl-book=$book")
  py=$(venv report pyyaml rfc8785)
  CAPSULECTL="$ctl" CAPSULECTL_PLUGIN_ROOTS="$roots" PATH="$py/bin:$PATH" bash tests/fresh_env_report.sh
  CAPSULECTL="$ctl" CAPSULECTL_PLUGIN_ROOTS="$roots" PATH="$py/bin:$PATH" bash tests/fresh_env_deals.sh
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

# tau2_setup: the binaries tau2-live's two jobs use, at the job's pins, on PATH (capsulectl, capsule-engine), and the
# plugin root in the caller's local roots. capsulectl and its plugins are the job's release (#435).
tau2_setup() {
  local w=tests.yml v ce ctl deal book bin
  v=$(pin $w tau2-live CAPSULECTL_VERSION)
  ce=$(engine "$(pin $w tau2-live CAPSULE_ENGINE_REF)")
  ctl=$(release capsule-cli "$v" "capsulectl-$v-$plat")
  deal=$(release evidencebook "capsulectl/$v" "capsulectl-deal-$v-$plat")
  book=$(release evidencebook "capsulectl/$v" "capsulectl-book-$v-$plat")
  roots=$(plugins "capsulectl-deal=$deal" "capsulectl-book=$book")
  bin=$(mktemp -d "$tmp/tau2-bin.XXXX")
  ln -sf "$ctl" "$bin/capsulectl"
  ln -sf "$ce" "$bin/capsule-engine"
  PATH="$bin:$PATH"
}

# tau2-live's unit tests, as tests.yml's tau2-live job runs them first.
job_tau2_live_unit() {
  local roots
  tau2_setup
  (cd demo/tau2-live && uv run --group dev pytest -q tests)
}

job_tau2_live() {
  # The tests' directory as a variable: tests/test_scripts.py takes a literal
  # path under tests/ in scripts/ for a citation of this repository's tests/.
  local roots t=demo/tau2-live/tests
  tau2_setup
  (
    cd demo/tau2-live
    CAPSULECTL_PLUGIN_ROOTS="$roots" uv run python "$root/$t/e2e_scripted.py" "$tmp/tau2-live"
    CAPSULECTL_PLUGIN_ROOTS="$roots" python3 "$root/$t/e2e_range.py" "$tmp/tau2-range"
  )
}

# demo_homes JOB: export the demo's folders (DEMO_HOMES in the demo tests' conftest), each a fresh, empty one under
# $tmp/homes/JOB, which the EXIT trap removes with the rest of $tmp. The person's own (~/.config/ard-commerce-demo, a
# seeded one on a laptop, never on CI; ~/ard-demo) are never read or written by a job (evidencebook-skills#357).
demo_homes() {
  local var d
  for var in ARD_HOME ARD_GOOSE_ROOT ARD_TESTBED ARD_ACP_PREFIX ARD_CAPSULE_ANCHOR; do
    d=$tmp/homes/$1/$var
    mkdir -p "$d"
    export "$var=$d"
  done
}

# Every job starts at once, so the check takes as long as its slowest job, not the sum of all
# (evidencebook-skills#419). Each runs in its own process group (set -m), writing its own log; a job's log is
# printed whole when it ends, with its pass or FAIL line, so two jobs' output never interleave. Ending the script
# (a failure of its own, Ctrl-C, a kill) stops every job's group, the processes a job started included.
failed=()
declare -A pid_of=() start_of=() result=()
# stop_jobs: TERM to each running job's process group (ard-demo's witness, started with nohup, is in its group too),
# up to 10 seconds for the groups to go, then KILL to what is left; only then is $tmp, which the jobs read, removed.
stop_jobs() {
  local p i alive
  ((${#pid_of[@]})) || return 0
  for p in "${pid_of[@]}"; do kill -TERM -- "-$p" 2>/dev/null || true; done
  for ((i = 0; i < 100; i++)); do
    alive=0
    for p in "${pid_of[@]}"; do kill -0 -- "-$p" 2>/dev/null && alive=1; done
    ((alive)) || return 0
    sleep 0.1
  done
  for p in "${pid_of[@]}"; do kill -KILL -- "-$p" 2>/dev/null || true; done
}
trap 'stop_jobs; rm -rf "$tmp"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
set -m
for job in "${jobs[@]}"; do
  if ! runs "$job"; then
    result[$job]="skipped (scripts/check.sh --full runs it)"
    continue
  fi
  start_of[$job]=$SECONDS
  # errexit inside the job: a job is a function run with `set -e`, as when the jobs ran one by one.
  (set -e; demo_homes "$job"; "job_${job//-/_}") </dev/null >"$tmp/$job.log" 2>&1 &
  pid_of[$job]=$!
done
set +m
printf 'check.sh: running %s at once\n' "${!pid_of[*]}"
while ((${#pid_of[@]})); do
  ended=()
  for job in "${!pid_of[@]}"; do
    kill -0 "${pid_of[$job]}" 2>/dev/null || ended+=("$job")
  done
  if ((${#ended[@]} == 0)); then
    # The next job to end, whichever it is (bash 4.4's wait -n takes no job list; this script starts no others).
    wait -n || true
    continue
  fi
  for job in "${ended[@]}"; do
    set +e
    wait "${pid_of[$job]}"
    rc=$?
    set -e
    unset "pid_of[$job]"
    if ((rc == 0)); then status=pass; else status=FAIL; failed+=("$job"); fi
    result[$job]=$(printf '%s  %ds' "$status" $((SECONDS - start_of[$job])))
    [[ ! -s "$tmp/$job.note" ]] || result[$job]+=" ($(<"$tmp/$job.note"))"
    printf '\n=== %s\n' "$job"
    cat "$tmp/$job.log"
    printf '=== %s: %s\n' "$job" "${result[$job]}"
  done
done
printf '\n'
for job in "${jobs[@]}"; do printf '%-20s %s\n' "$job" "${result[$job]}"; done
if ((${#failed[@]})); then
  printf 'check.sh: FAILED: %s\n' "${failed[*]}" >&2
  exit 1
fi
if [[ -s "$tmp/neutrality.note" ]]; then
  echo "check.sh: all jobs passed; NOT RUN: neutrality's scan ($(<"$tmp/neutrality.note"))"
else
  echo "check.sh: all jobs passed"
fi
