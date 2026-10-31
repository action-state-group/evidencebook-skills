#!/usr/bin/env bash
# Fresh-environment test: run both cron skills end to end on the tau2 airline book
# from a clean machine state -- a new temporary HOME (no profiles, no Go caches), a
# fresh clone of this repository and of capsule-cli, and capsulectl built from source.
#
#   tests/fresh_env.sh [LOG_FILE]
#
# Environment (all optional):
#   SKILLS_REPO  this repository to clone (default: its GitHub URL); a local path works
#   SKILLS_REF   branch or commit of it to test (default: main)
#   CLI_REPO     capsule-cli to clone (default: its GitHub URL)
#   CLI_REF      capsule-cli commit to build capsulectl from
#   CASES        how many tau2 airline tasks to put in the book (default: 12)
#
# No model runs anywhere: the judge is tests/stub_judge.py and the human expert is
# tests/stub_rater.py, both deterministic stand-ins that say so. The tau2 cases are
# the recorded runs in airline-data/, sealed by demo/backfill (no model either).
set -euo pipefail

SKILLS_REPO=${SKILLS_REPO:-https://github.com/action-state-group/evidencebook-skills.git}
SKILLS_REF=${SKILLS_REF:-main}
CLI_REPO=${CLI_REPO:-https://github.com/action-state-group/capsule-cli.git}
CLI_REF=${CLI_REF:-6dadefd}
CASES=${CASES:-12}

work=$(mktemp -d)
log=${1:-$work/fresh-env.log}
exec > >(tee "$log") 2>&1
start=$(date +%s)
step() { printf '\n== %s ==\n' "$*"; }
fail() { printf 'FRESH-ENV: FAIL -- %s\n' "$*"; exit 1; }

export HOME=$work/home XDG_CONFIG_HOME=$work/home/.config
export GOPATH=$work/home/go GOCACHE=$work/home/.cache/go-build GOMODCACHE=$work/home/go/pkg/mod GOWORK=off
mkdir -p "$XDG_CONFIG_HOME" "$work/bin"
printf 'work dir: %s\nclean HOME: %s\nstarted: %s\n' "$work" "$HOME" "$(date -u +%FT%TZ)"

step "fresh clones"
git clone --quiet "$SKILLS_REPO" "$work/skills"
git -C "$work/skills" checkout --quiet "$SKILLS_REF"
git clone --quiet "$CLI_REPO" "$work/capsule-cli"
git -C "$work/capsule-cli" checkout --quiet "$CLI_REF"
printf 'skills  %s @ %s\ncapsule-cli %s @ %s\n' "$SKILLS_REPO" "$(git -C "$work/skills" rev-parse HEAD)" "$CLI_REPO" "$(git -C "$work/capsule-cli" rev-parse HEAD)"

step "build capsulectl and the test fixture from source"
(cd "$work/capsule-cli" && go build -o "$work/bin/capsulectl" ./cmd/capsulectl)
(cd "$work/skills/tests/bookfixture" && go build -o "$work/bin/bookfixture" .)
ctl=$work/bin/capsulectl
"$ctl" --version

step "a venv with the scripts' requirements (rfc8785 for JSON-DIGESTs)"
# --system-site-packages: whatever else the host python3 already provides stays visible.
python3 -m venv --system-site-packages "$work/venv"
"$work/venv/bin/pip" install --quiet --upgrade pip
"$work/venv/bin/pip" install --quiet -r "$work/skills/requirements.txt"
export PATH="$work/venv/bin:$PATH"

step "unit tests of the scripts' pure logic"
cd "$work/skills"
CAPSULECTL="$ctl" python3 -m unittest discover -s tests -p 'test_*.py'

step "the EU AI Act pack's Evidence Contract is published as it compiles, and capsulectl accepts it"
python3 scripts/evidence_contract.py publish packs/eu-ai-act-obligations/pack-source.yaml >"$work/contract.json" \
  || fail "the EU AI Act pack does not compile to its published contract: $(cat "$work/contract.json")"
[[ $(jq -r .written "$work/contract.json") == false ]] || fail "the EU AI Act pack's current version is not published"
contract=$(jq -r .path "$work/contract.json")
"$ctl" contract validate "$contract" --schema tests/fixtures/capsule-engine/evidence-contract-v0.json --json \
  | jq -e .valid >/dev/null || fail "capsulectl contract validate refuses $contract"
printf '%s: valid Evidence Contract v0\n' "$contract"

step "a tau2 book: profile, keys, store"
"$ctl" key generate --output "$work/producer.seed" >"$work/producer.json"
"$ctl" key generate --output "$work/checkpoint.seed" >"$work/checkpoint.json"
"$ctl" profile create --name tau2 --type jsonl --jsonl-path "$work/store" \
  --namespace tau2 --log-id tau2-airline --operator tau2-demo \
  --signing-key-file "$work/producer.seed" --trusted-key "$(jq -r .public_key "$work/producer.json")" \
  --checkpoint-signing-key-file "$work/checkpoint.seed" --checkpoint-trusted-key "$(jq -r .public_key "$work/checkpoint.json")"
"$ctl" store init --profile tau2

# The cases go into the previous ISO week's Wednesday: a day and a week that have ended.
day=$(python3 -c 'import datetime as d; t=d.date.today(); m=t-d.timedelta(days=t.weekday()+7); print(m+d.timedelta(days=2))')
printf 'cases committed on %s (week ended)\n' "$day"

step "seal $CASES recorded tau2 airline runs and put them in the book on $day"
python3 demo/backfill/backfill.py --results airline-data/claude-3-7-sonnet-20250219_airline_default_gpt-4.1-2025-04-14_4trials.json --out "$work/requests" >/dev/null
mkdir -p "$work/cases"
for request in $(ls "$work/requests"/task-*.json | sort | head -n "$CASES"); do
  "$ctl" seal --profile tau2 --request "$request" --output "$work/cases/$(basename "$request")" >/dev/null
done
"$work/bin/bookfixture" seed --store "$work/store" --log-id tau2-airline --operator tau2-demo --namespace tau2 \
  --signing-key-file "$work/producer.seed" --checkpoint-key-file "$work/checkpoint.seed" --at "${day}T12:00:00Z" "$work/cases"/*.json
listed=$("$ctl" cll list --profile tau2 --limit 1000 | jq '[.entries[] | select(.record_type=="published_capsule")] | length')
[[ "$listed" -eq "$CASES" ]] || fail "capsulectl lists $listed cases, not $CASES: the seeded records do not match what capsulectl writes"
printf '%s cases in the book, as capsulectl lists them\n' "$listed"

step "daily-judge-and-close for $day"
python3 scripts/run_daily.py --profile tau2 --spec demo/tau2/compiled.json --capsulectl "$ctl" \
  --judge-cmd "python3 tests/stub_judge.py" --judge-model-id "stub-judge/0 (deterministic, no model)" \
  --date "$day" --out "$work/runs" | tee "$work/daily.json"
[[ $(jq '.reports | length' "$work/daily.json") -eq "$CASES" ]] || fail "not one report per case"
[[ $(jq -r '.close.already_closed' "$work/daily.json") == false ]] || fail "the day was already closed"

step "daily-judge-and-close again for $day: nothing new is sealed"
before=$("$ctl" cll list --profile tau2 --all --limit 1000 | jq '.entries | length')
python3 scripts/run_daily.py --profile tau2 --spec demo/tau2/compiled.json --capsulectl "$ctl" \
  --judge-cmd "python3 tests/stub_judge.py" --judge-model-id "stub-judge/0 (deterministic, no model)" \
  --date "$day" --out "$work/runs" >"$work/daily-again.json"
after=$("$ctl" cll list --profile tau2 --all --limit 1000 | jq '.entries | length')
[[ $(jq -r '.close.already_closed' "$work/daily-again.json") == true ]] || fail "a second run sealed a second Close"
diff <(jq -c .reports "$work/daily.json") <(jq -c .reports "$work/daily-again.json") >/dev/null || fail "a second run sealed different reports"
[[ "$before" -eq "$after" ]] || fail "a second run grew the log from $before to $after records"
printf 're-run: same %s reports, same Close, log still %s records\n' "$CASES" "$after"

step "weekly-blind-expert: sample, then pause for the human"
set +e
python3 scripts/run_weekly.py --profile tau2 --spec demo/tau2/compiled.json --capsulectl "$ctl" \
  --date "$day" --out "$work/runs" | tee "$work/weekly-paused.json"
paused=${PIPESTATUS[0]}
set -e
[[ "$paused" -eq 3 ]] || fail "the weekly skill did not pause for ratings (exit $paused)"
packets=$(jq -r '.status' "$work/weekly-paused.json" | sed 's/.* in //')
if grep -l '"verdict"\|"rationale"\|"stratum"' "$packets"/*.json >/dev/null; then fail "a blind packet shows the judge's verdict"; fi
run_dir="$(cd "$work/runs" && pwd)/$(jq -r .week "$work/weekly-paused.json" | tr ':' '-')/"
case "$(cd "$packets" && pwd)/" in "$run_dir"*) fail "the blind packets sit inside the run directory, beside the verdicts" ;; esac
printf 'blind packets: %s in %s, outside the run directory (no verdict, rationale or stratum in any)\n' "$(ls "$packets" | wc -l | tr -d ' ')" "$packets"

step "duplicate ratings for one case are refused before any rating is sealed"
before=$("$ctl" cll list --profile tau2 --all --limit 1000 | jq '.entries | length')
python3 tests/stub_rater.py "$packets" | jq '. + [.[0]]' >"$work/ratings-duplicated.json"
set +e
python3 scripts/run_weekly.py --profile tau2 --spec demo/tau2/compiled.json --capsulectl "$ctl" \
  --date "$day" --out "$work/runs" --ratings "$work/ratings-duplicated.json" >"$work/weekly-duplicated.json"
refused=$?
set -e
[[ "$refused" -eq 2 ]] && jq -e '.evidence_unavailable | contains("more than one rating")' "$work/weekly-duplicated.json" >/dev/null || fail "a duplicated rating was not refused (exit $refused)"
after=$("$ctl" cll list --profile tau2 --all --limit 1000 | jq '.entries | length')
[[ "$before" -eq "$after" ]] || fail "a refused rating set still sealed records ($before -> $after)"
printf 'refused: %s\n' "$(jq -r .evidence_unavailable "$work/weekly-duplicated.json")"

step "the human's ratings (stand-in), then resume"
python3 tests/stub_rater.py "$packets" >"$work/ratings.json"
python3 scripts/run_weekly.py --profile tau2 --spec demo/tau2/compiled.json --capsulectl "$ctl" \
  --date "$day" --out "$work/runs" --ratings "$work/ratings.json" --rater-ref "rater:stub-expert" | tee "$work/weekly.json"
jq -e '.shortfall == 0 and (.agreement | length) == 1 and (.calibration_summaries | length) == 1' "$work/weekly.json" >/dev/null || fail "calibration summary is not one pin's k of n"

step "every capsule in the book verifies offline"
verified=0
for id in $("$ctl" cll list --profile tau2 --limit 1000 | jq -r '.entries[].capsule_id'); do
  "$ctl" get --profile tau2 --capsule-id "$id" --raw --output "$work/verify-$id.json" >/dev/null
  "$ctl" verify --profile tau2 --capsule "$work/verify-$id.json" >/dev/null || fail "capsule $id does not verify"
  verified=$((verified + 1))
done
for close in $(jq -r .close.capsule "$work/daily.json") $(jq -r .close.capsule "$work/weekly.json"); do
  "$ctl" verify --profile tau2 --capsule "$close" >/dev/null || fail "Close $close does not verify"
  verified=$((verified + 1))
done
printf '%s records verified with capsulectl verify (cases, reports, skill actions, manifest, ratings, summary, two Closes)\n' "$verified"

step "bundles verify with the neutral AAC bundle verifier"
"$ctl" bundle --profile tau2 --root "$(jq -r ".calibration_summaries[0]" "$work/weekly.json")" --out "$work/calibration-bundle.json"
for bundle in "$(jq -r .close.bundle "$work/daily.json")" "$(jq -r .close.bundle "$work/weekly.json")" "$work/calibration-bundle.json"; do
  printf '%s: ' "$(basename "$(dirname "$bundle")")/$(basename "$bundle")"
  "$work/bin/bookfixture" aac-verify "$bundle" || fail "$bundle does not verify"
done

step "summary"
jq -c '{day, cases, verdicts, close}' "$work/daily.json"
jq -c '{week, frame, drawn, rated, shortfall, agreement, close}' "$work/weekly.json"
printf 'elapsed: %ss\nFRESH-ENV: PASS\n' "$(($(date +%s) - start))"
