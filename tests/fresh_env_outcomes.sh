#!/usr/bin/env bash
# Fresh-environment test for the outcomes adjudicator: rubric v3.2's nine jev-judged
# clauses (demo/tau2-outcomes/compiled.json), scripts/judges/jev_judge.py as the
# --judge-cmd, and scripts/rollup_day.py's all-required rollup -- run end to end,
# from a clean machine state, over all 50 trial-0 claude-3-7-sonnet airline
# scenarios (not a 12-case sample).
#
# This is tests/fresh_env.sh's sibling, not a replacement: fresh_env.sh still
# covers the original single-clause contract (demo/tau2/compiled.json) and the
# weekly-blind-expert skill; this one covers the daily skill judging all nine
# criteria at the full 50-case scale, with every record verifying and every
# bundle passing.
#
#   tests/fresh_env_outcomes.sh [LOG_FILE]
#
# Environment (all optional):
#   SKILLS_REPO  this repository to clone (default: its GitHub URL); a local path works
#   SKILLS_REF   branch or commit of it to test (default: main)
#   CLI_REPO     capsule-cli to clone (default: its GitHub URL)
#   CLI_REF      capsule-cli commit to build capsulectl from
#   CASES        how many tau2 airline tasks to put in the book (default: 50, the
#                full trial-0 set of the claude-3-7-sonnet results file)
#
# No model runs anywhere: JEV_JUDGE_BACKEND=mock makes scripts/judges/jev_judge.py a
# deterministic hash-of-request stand-in (see its own docstring) -- no
# TYPESAFE_API_KEY, no network call to Jev, no judging performed. The tau2 cases are
# the recorded runs in airline-data/, sealed by demo/backfill (no model either).
set -euo pipefail

SKILLS_REPO=${SKILLS_REPO:-https://github.com/action-state-group/evidencebook-skills.git}
SKILLS_REF=${SKILLS_REF:-main}
CLI_REPO=${CLI_REPO:-https://github.com/action-state-group/capsule-cli.git}
CLI_REF=${CLI_REF:-6dadefd}
CASES=${CASES:-50}
CRITERIA=9

work=$(mktemp -d)
log=${1:-$work/fresh-env-outcomes.log}
exec > >(tee "$log") 2>&1
start=$(date +%s)
step() { printf '\n== %s ==\n' "$*"; }
fail() { printf 'FRESH-ENV-OUTCOMES: FAIL -- %s\n' "$*"; exit 1; }

export HOME=$work/home XDG_CONFIG_HOME=$work/home/.config
export GOPATH=$work/home/go GOCACHE=$work/home/.cache/go-build GOMODCACHE=$work/home/go/pkg/mod GOWORK=off
mkdir -p "$XDG_CONFIG_HOME" "$work/bin"
printf 'work dir: %s\nclean HOME: %s\nstarted: %s\ncases: %s\n' "$work" "$HOME" "$(date -u +%FT%TZ)" "$CASES"

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

step "a venv with jevals (scripts/judges/jev_judge.py's only dependency beyond stdlib)"
python3 -m venv "$work/venv"
"$work/venv/bin/pip" install --quiet --upgrade pip
"$work/venv/bin/pip" install --quiet jevals
export PATH="$work/venv/bin:$PATH"
python3 -c "import jevals; print('jevals', __import__('importlib.metadata', fromlist=['version']).version('jevals'))"

step "unit tests of the scripts' pure logic"
cd "$work/skills"
python3 -m unittest discover -s tests -p 'test_*.py'

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

step "seal all $CASES trial-0 claude-3-7-sonnet airline runs and put them in the book on $day"
python3 demo/backfill/backfill.py --results airline-data/claude-3-7-sonnet-20250219_airline_default_gpt-4.1-2025-04-14_4trials.json --out "$work/requests" >/dev/null
request_count=$(ls "$work/requests"/task-*.json | wc -l | tr -d ' ')
[[ "$request_count" -ge "$CASES" ]] || fail "backfill only produced $request_count seal requests, fewer than CASES=$CASES (the claude file's own trial-0 count is the ceiling)"
mkdir -p "$work/cases"
for request in $(ls "$work/requests"/task-*.json | sort | head -n "$CASES"); do
  "$ctl" seal --profile tau2 --request "$request" --output "$work/cases/$(basename "$request")" >/dev/null
done
"$work/bin/bookfixture" seed --store "$work/store" --log-id tau2-airline --operator tau2-demo --namespace tau2 \
  --signing-key-file "$work/producer.seed" --checkpoint-key-file "$work/checkpoint.seed" --at "${day}T12:00:00Z" "$work/cases"/*.json
listed=$("$ctl" cll list --profile tau2 --limit 1000 | jq '[.entries[] | select(.record_type=="published_capsule")] | length')
[[ "$listed" -eq "$CASES" ]] || fail "capsulectl lists $listed cases, not $CASES: the seeded records do not match what capsulectl writes"
printf '%s cases in the book, as capsulectl lists them\n' "$listed"

step "daily-judge-and-close for $day: all nine rubric v3.2 clauses, jev_judge.py (mock backend)"
JEV_JUDGE_BACKEND=mock python3 scripts/run_daily.py --profile tau2 --spec demo/tau2-outcomes/compiled.json --capsulectl "$ctl" \
  --judge-cmd "python3 scripts/judges/jev_judge.py" --judge-model-id "jev-1.13.0 (mock backend, no model read the conversation)" \
  --date "$day" --out "$work/runs" | tee "$work/daily.json"
expected_reports=$((CASES * CRITERIA))
[[ $(jq '.reports | length' "$work/daily.json") -eq "$expected_reports" ]] || fail "not nine reports per case ($CASES cases x $CRITERIA criteria = $expected_reports expected)"
[[ $(jq -r '.close.already_closed' "$work/daily.json") == false ]] || fail "the day was already closed"
printf '%s cases x %s criteria = %s evaluation-report/v1 capsules sealed\n' "$CASES" "$CRITERIA" "$expected_reports"

step "daily-judge-and-close again for $day: nothing new is sealed"
before=$("$ctl" cll list --profile tau2 --all --limit 1000 | jq '.entries | length')
JEV_JUDGE_BACKEND=mock python3 scripts/run_daily.py --profile tau2 --spec demo/tau2-outcomes/compiled.json --capsulectl "$ctl" \
  --judge-cmd "python3 scripts/judges/jev_judge.py" --judge-model-id "jev-1.13.0 (mock backend, no model read the conversation)" \
  --date "$day" --out "$work/runs" >"$work/daily-again.json"
after=$("$ctl" cll list --profile tau2 --all --limit 1000 | jq '.entries | length')
[[ $(jq -r '.close.already_closed' "$work/daily-again.json") == true ]] || fail "a second run sealed a second Close"
diff <(jq -c .reports "$work/daily.json") <(jq -c .reports "$work/daily-again.json") >/dev/null || fail "a second run sealed different reports"
[[ "$before" -eq "$after" ]] || fail "a second run grew the log from $before to $after records"
printf 're-run: same %s reports, same Close, log still %s records\n' "$expected_reports" "$after"

step "the all-required rollup over every case's nine sealed reports (scripts/rollup_day.py)"
JEV_JUDGE_BACKEND=mock python3 scripts/rollup_day.py --profile tau2 --spec demo/tau2-outcomes/compiled.json --capsulectl "$ctl" \
  --judge-cmd "python3 scripts/judges/jev_judge.py" --judge-model-id "jev-1.13.0 (mock backend, no model read the conversation)" --generated-at "${day}T23:59:59Z" --out "$work/runs/rollup" | tee "$work/rollup-summary.json"
jq -e ".cases_complete == $CASES and (.cases_incomplete | length) == 0" "$work/rollup-summary.json" >/dev/null \
  || fail "rollup did not find all $CASES cases complete with nine reports each"
printf 'rollup: %s cases judged, %s complete (nine of nine), %s resolved (all nine met)\n' \
  "$(jq -r .cases_judged "$work/rollup-summary.json")" "$(jq -r .cases_complete "$work/rollup-summary.json")" "$(jq -r .cases_resolved "$work/rollup-summary.json")"

step "every capsule in the book verifies offline"
verified=0
for id in $("$ctl" cll list --profile tau2 --limit 1000 | jq -r '.entries[].capsule_id'); do
  "$ctl" get --profile tau2 --capsule-id "$id" --raw --output "$work/verify-$id.json" >/dev/null
  "$ctl" verify --profile tau2 --capsule "$work/verify-$id.json" >/dev/null || fail "capsule $id does not verify"
  verified=$((verified + 1))
done
"$ctl" verify --profile tau2 --capsule "$(jq -r .close.capsule "$work/daily.json")" >/dev/null || fail "Close does not verify"
verified=$((verified + 1))
printf '%s records verified with capsulectl verify (cases, reports, Close)\n' "$verified"
expected_verified=$((CASES + expected_reports + 1))
[[ "$verified" -eq "$expected_verified" ]] || fail "verified $verified records, expected $expected_verified ($CASES cases + $expected_reports reports + 1 Close)"

step "the day's bundle verifies with the neutral AAC bundle verifier"
bundle=$(jq -r .close.bundle "$work/daily.json")
printf '%s: ' "$(basename "$(dirname "$bundle")")/$(basename "$bundle")"
"$work/bin/bookfixture" aac-verify "$bundle" || fail "$bundle does not verify"

step "summary"
jq -c '{day, cases, reports: (.reports | length), verdicts, close}' "$work/daily.json"
cat "$work/rollup-summary.json"
printf 'elapsed: %ss\nFRESH-ENV-OUTCOMES: PASS\n' "$(($(date +%s) - start))"
