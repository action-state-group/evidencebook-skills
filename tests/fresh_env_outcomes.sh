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
# Then the compiled airline-support-outcomes pack (demo/airline-support-outcomes,
# from packs/airline-support-outcomes/pack-source.yaml) runs on a second book,
# end to end through the paths the tau2 contract never takes: out_of_scope
# answers (the pack's out_of_scope_verdict switch), never_out_of_scope clauses
# that are never offered it, a min_confidence threshold (a recompiled variant at
# 0.95, above the mock's 0.9), a recomputed clause, and pin and pack_source_digest
# scoping in the rollup (each pack's rollup counts the other's reports as
# excluded, never combines them).
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
#   AIRLINE_CASES how many of them the airline-support-outcomes phase judges
#                (default: 12)
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
AIRLINE_CASES=${AIRLINE_CASES:-12}
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

step "a venv with the scripts' requirements (jevals for scripts/judges/jev_judge.py, pyyaml for scripts/pack_compile.py, rfc8785 for JSON-DIGESTs)"
python3 -m venv "$work/venv"
"$work/venv/bin/pip" install --quiet --upgrade pip
"$work/venv/bin/pip" install --quiet -r "$work/skills/requirements.txt"
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

# ---------------------------------------------------------------------------
# The compiled airline-support-outcomes pack, on a second book.
# ---------------------------------------------------------------------------
AIRLINE_MODEL="jev-1.13.0 (mock backend, no model read the conversation)"
AIRLINE_SPEC=demo/airline-support-outcomes/compiled.json
VARIANT_SPEC=demo/airline-support-outcomes-variant/compiled.json
NEVER_OOS='["grounded_communication.no_invented_policy","task_resolution.done_in_full"]'
[[ $(jq -c '[.clauses[] | select(.never_out_of_scope) | .id] | sort' "$AIRLINE_SPEC") == "$NEVER_OOS" ]] \
  || fail "$AIRLINE_SPEC's never_out_of_scope clauses are not $NEVER_OOS"
[[ $(jq -r '.switches.out_of_scope_verdict' "$AIRLINE_SPEC") == true ]] || fail "$AIRLINE_SPEC has out_of_scope off"
a_reports=$((AIRLINE_CASES * CRITERIA))

step "an airline-support-outcomes book: $AIRLINE_CASES of the same sealed cases on $day"
"$ctl" profile create --name airline --type jsonl --jsonl-path "$work/airline-store" \
  --namespace tau2 --log-id tau2-airline --operator tau2-demo \
  --signing-key-file "$work/producer.seed" --trusted-key "$(jq -r .public_key "$work/producer.json")" \
  --checkpoint-signing-key-file "$work/checkpoint.seed" --checkpoint-trusted-key "$(jq -r .public_key "$work/checkpoint.json")"
"$ctl" store init --profile airline
"$work/bin/bookfixture" seed --store "$work/airline-store" --log-id tau2-airline --operator tau2-demo --namespace tau2 \
  --signing-key-file "$work/producer.seed" --checkpoint-key-file "$work/checkpoint.seed" --at "${day}T12:00:00Z" \
  $(ls "$work/cases"/task-*.json | sort | head -n "$AIRLINE_CASES")

step "daily-judge-and-close, airline pack: out_of_scope on, two clauses never_out_of_scope"
JEV_JUDGE_BACKEND=mock python3 scripts/run_daily.py --profile airline --spec "$AIRLINE_SPEC" --capsulectl "$ctl" \
  --judge-cmd "python3 scripts/judges/jev_judge.py" --judge-model-id "$AIRLINE_MODEL" \
  --date "$day" --out "$work/airline/base" | tee "$work/airline-daily.json"
[[ $(jq '.reports | length' "$work/airline-daily.json") -eq "$a_reports" ]] || fail "airline: not $a_reports reports"
a_oos=$(jq '.verdicts.out_of_scope // 0' "$work/airline-daily.json")
[[ "$a_oos" -gt 0 ]] || fail "airline: no out_of_scope verdict, so the out_of_scope path never ran"

step "the airline rollup: out_of_scope excluded, never_out_of_scope never out_of_scope"
JEV_JUDGE_BACKEND=mock python3 scripts/rollup_day.py --profile airline --spec "$AIRLINE_SPEC" --capsulectl "$ctl" \
  --judge-cmd "python3 scripts/judges/jev_judge.py" --judge-model-id "$AIRLINE_MODEL" \
  --generated-at "${day}T23:59:59Z" --out "$work/airline/rollup-base" >"$work/airline-rollup-base.json"
jq -e ".cases_complete == $AIRLINE_CASES and (.cases_incomplete | length) == 0 and (.cases_conflicting | length) == 0
       and .reports_excluded == {\"judge_pin_mismatch\": 0, \"pack_source_mismatch\": 0}" \
  "$work/airline-rollup-base.json" >/dev/null || fail "airline rollup is not $AIRLINE_CASES complete cases with nothing excluded"
excluded_na=$(jq -s 'map(.aggregate.coverage.excluded_not_applicable) | add' "$work/airline/rollup-base"/result-v0-*.json)
[[ "$excluded_na" -eq "$a_oos" ]] || fail "airline day documents exclude $excluded_na not-applicable criteria, not the $a_oos out_of_scope verdicts"
never_oos_hits=$(jq -s --argjson ids "$NEVER_OOS" \
  '[.[] | select(.criterion_verdicts) | .criterion_verdicts | to_entries[] | select((.key | IN($ids[])) and .value == "out_of_scope")] | length' \
  "$work/airline/rollup-base"/tau2_*.json)
[[ "$never_oos_hits" -eq 0 ]] || fail "a never_out_of_scope clause was answered out_of_scope $never_oos_hits time(s)"
printf 'airline: %s reports, %s out_of_scope (all excluded from claims), never_out_of_scope clauses never out_of_scope\n' "$a_reports" "$a_oos"

step "a variant of the pack: within_fare_rules recomputed, judge.min_confidence 0.95 (the mock answers at 0.9)"
python3 - "$work/airline-variant.yaml" <<'EOF'
import sys, yaml
source = yaml.safe_load(open("packs/airline-support-outcomes/pack-source.yaml"))
source["switches"]["within_fare_rules_recomputed"] = True
source["judge"]["min_confidence"] = 0.95
open(sys.argv[1], "w").write(yaml.safe_dump(source, sort_keys=False))
EOF
python3 scripts/pack_compile.py compile "$work/airline-variant.yaml" --out demo/airline-support-outcomes-variant >/dev/null
[[ $(jq -r .pack_source_digest "$VARIANT_SPEC") != $(jq -r .pack_source_digest "$AIRLINE_SPEC") ]] || fail "the variant kept the pack_source_digest"
JEV_JUDGE_BACKEND=mock python3 scripts/run_daily.py --profile airline --spec "$VARIANT_SPEC" --capsulectl "$ctl" \
  --judge-cmd "python3 scripts/judges/jev_judge.py" --judge-model-id "$AIRLINE_MODEL" \
  --date "$day" --out "$work/airline/variant" | tee "$work/airline-variant-daily.json"
[[ $(jq '.reports | length' "$work/airline-variant-daily.json") -eq "$a_reports" ]] || fail "variant: not $a_reports reports"
JEV_JUDGE_BACKEND=mock python3 scripts/rollup_day.py --profile airline --spec "$VARIANT_SPEC" --capsulectl "$ctl" \
  --judge-cmd "python3 scripts/judges/jev_judge.py" --judge-model-id "$AIRLINE_MODEL" \
  --generated-at "${day}T23:59:59Z" --out "$work/airline/rollup-variant" >"$work/airline-rollup-variant.json"
jq -e ".cases_complete == $AIRLINE_CASES and .reports_excluded == {\"judge_pin_mismatch\": $a_reports, \"pack_source_mismatch\": 0}" \
  "$work/airline-rollup-variant.json" >/dev/null || fail "variant rollup did not count the base pack's $a_reports judged reports as excluded"
below=$(jq -s '[.[] | select(.criterion_verdicts) | .criterion_verdicts | to_entries[]
                | select(.key != "policy_compliance.within_fare_rules" and .value != "not_evaluable")] | length' \
  "$work/airline/rollup-variant"/tau2_*.json)
[[ "$below" -eq 0 ]] || fail "min_confidence 0.95: $below judged verdict(s) taken despite the mock's 0.9 confidence"
printf 'variant: every judged clause not_evaluable below min_confidence; base reports excluded by pin\n'

step "the base pack's rollup again: the variant's reports are excluded by pin and by pack_source_digest"
JEV_JUDGE_BACKEND=mock python3 scripts/rollup_day.py --profile airline --spec "$AIRLINE_SPEC" --capsulectl "$ctl" \
  --judge-cmd "python3 scripts/judges/jev_judge.py" --judge-model-id "$AIRLINE_MODEL" \
  --generated-at "${day}T23:59:59Z" --out "$work/airline/rollup-base-again" >"$work/airline-rollup-base-again.json"
jq -e ".reports_excluded == {\"judge_pin_mismatch\": $((AIRLINE_CASES * (CRITERIA - 1))), \"pack_source_mismatch\": $AIRLINE_CASES}" \
  "$work/airline-rollup-base-again.json" >/dev/null || fail "base rollup did not count the variant's judged and recomputed reports as excluded"
diff <(jq -c '[.cases_complete, .cases_resolved, [.day_results[].headline]]' "$work/airline-rollup-base.json") \
     <(jq -c '[.cases_complete, .cases_resolved, [.day_results[].headline]]' "$work/airline-rollup-base-again.json") >/dev/null \
  || fail "the variant's reports changed the base pack's rollup"
printf 'base rollup unchanged; %s judged + %s recomputed variant reports excluded\n' "$((AIRLINE_CASES * (CRITERIA - 1)))" "$AIRLINE_CASES"

step "summary"
jq -c '{day, cases, reports: (.reports | length), verdicts, close}' "$work/daily.json"
cat "$work/rollup-summary.json"
jq -c '{airline: {reports: (.reports | length), verdicts}}' "$work/airline-daily.json"
jq -c '{airline_variant: {reports: (.reports | length), verdicts}}' "$work/airline-variant-daily.json"
printf 'elapsed: %ss\nFRESH-ENV-OUTCOMES: PASS\n' "$(($(date +%s) - start))"
