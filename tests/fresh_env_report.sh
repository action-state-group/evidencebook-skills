#!/usr/bin/env bash
# The evidencebook-report skill's done-means, run for real against capsulectl
# and the capsulectl-book plugin: a sealed and checked EvidenceBook report
# (grade 2) whose page `book report check` matches, the same page tampered with
# no longer matching, and a question with no Terms Pack refused honestly.
#
#   tests/fresh_env_report.sh [LOG_FILE]
#
# Environment:
#   CAPSULECTL     a capsulectl binary that loads the capsulectl-book plugin
#                  (required; with CAPSULECTL_PLUGIN_ROOTS pointing at the
#                  plugin when it is not on a default root). `book report
#                  build --seal` and `book report check` are on evidencebook
#                  main, not yet in a capsulectl-book release.
#   CASES          how many recorded tau2 airline runs to seal (default: 4)
#
# The book is new, in a temporary HOME, and the report goes the no-judge path
# (scripts/specs/tau2-airline-no-judge.yaml): every claim is computed from the
# sealed records, so no model and no judge runs. The cases are the recorded
# runs in airline-data/, sealed by demo/backfill.
set -euo pipefail

CTL=${CAPSULECTL:?set CAPSULECTL to a capsulectl that loads the capsulectl-book plugin}
CASES=${CASES:-4}
REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

work=$(mktemp -d)
log=${1:-$work/fresh-env-report.log}
exec > >(tee "$log") 2>&1
step() { printf '\n== %s ==\n' "$*"; }
fail() { printf 'FRESH-ENV-REPORT: FAIL -- %s\n' "$*"; exit 1; }

export HOME=$work/home XDG_CONFIG_HOME=$work/home/.config
mkdir -p "$XDG_CONFIG_HOME"
"$CTL" book report check --help >/dev/null 2>&1 || fail "$CTL has no \`book report check\` (capsulectl-book plugin missing or too old)"

step "a book: keys, profile, store"
"$CTL" key generate --output "$work/producer.seed" >"$work/producer.json"
"$CTL" key generate --output "$work/checkpoint.seed" >"$work/checkpoint.json"
"$CTL" profile create --name report --type jsonl --jsonl-path "$work/store" \
  --namespace report --log-id report-log --log book --operator report-demo \
  --signing-key-file "$work/producer.seed" --trusted-key "$(jq -r .public_key "$work/producer.json")" \
  --checkpoint-signing-key-file "$work/checkpoint.seed" --checkpoint-trusted-key "$(jq -r .public_key "$work/checkpoint.json")" >/dev/null
"$CTL" store init --profile report >/dev/null

step "seal $CASES recorded tau2 airline runs into the book"
python3 "$REPO/demo/backfill/backfill.py" \
  --results "$REPO/airline-data/claude-3-7-sonnet-20250219_airline_default_gpt-4.1-2025-04-14_4trials.json" \
  --out "$work/requests" >/dev/null
for request in $(ls "$work/requests"/task-*.json | sort | head -n "$CASES"); do
  "$CTL" publish --profile report --request "$request" >/dev/null
done
day=$(date -u +%F)

step "grade 2: report.sh --seal, then report check"
bash "$REPO/scripts/report.sh" --spec "$REPO/scripts/specs/tau2-airline-no-judge.yaml" --profile report \
  --date "$day" --out "$work/report.html" --capsulectl "$CTL" --work "$work/run" --seal \
  || fail "report.sh --seal did not hand over a checked page"
[[ -f "$work/report.html" ]] || fail "no page handed over"
"$CTL" book report check --profile report --page "$work/report.html" >"$work/check.json" \
  || fail "report check refuses the handed-over page: $(cat "$work/check.json")"
[[ $(jq -r '"\(.page) \(.verification)"' "$work/check.json") == "match VALID" ]] \
  || fail "report check does not say match VALID: $(cat "$work/check.json")"
printf 'report check: %s\n' "$(jq -c . "$work/check.json")"

step "grade 1: a narration over the verified Result cites it and reads every number from it"
bundle=$(ls "$work"/run/run.*/bundle.json)
"$CTL" verify --profile report --bundle "$bundle" >"$work/verify.json" || true
[[ $(jq -r .verdict "$work/verify.json") == VALID ]] || fail "the Result's bundle does not verify: $(cat "$work/verify.json")"
root=$(jq -r .root "$bundle")
jq --arg r "$root" '.disclosures[$r].agent_input.statement' "$bundle" >"$work/result.json"
evaluated=$(jq -r .aggregate.coverage.evaluated_population "$work/result.json")
cat >"$work/narration.txt" <<EOF
The sealed report for $day [$root] evaluated $evaluated checks.
Tell me if you'd like an EvidenceBook version of this: sealed, checked, and the same page anyone can verify.
Narrated by your agent, from your records.
EOF
python3 "$REPO/scripts/narration_check.py" --narration "$work/narration.txt" --record "$root=$work/result.json" \
  || fail "a narration that reads its numbers from the cited Result fails the check"
# A total the Result does not hold: the agent added it up itself.
computed=$(python3 -c "
import json, sys
sys.path.insert(0, sys.argv[2])
from narration_check import numbers_in
held = numbers_in(json.load(open(sys.argv[1])), set())
print(next(n for n in range(2, 10000) if str(n) not in held))
" "$work/result.json" "$REPO/scripts")
sed "s/evaluated $evaluated checks\./evaluated $evaluated checks, $computed in all./" "$work/narration.txt" >"$work/computed.txt"
set +e
python3 "$REPO/scripts/narration_check.py" --narration "$work/computed.txt" --record "$root=$work/result.json" >"$work/computed.json"
computed_exit=$?
set -e
[[ "$computed_exit" -eq 1 ]] && jq -e --arg n "$computed" '.findings | any(startswith("states " + $n + " "))' "$work/computed.json" >/dev/null \
  || fail "a narration stating a number the Result does not hold passed: $(cat "$work/computed.json")"
printf 'narration: passes; with a computed %s: %s\n' "$computed" "$(jq -r '.findings[0]' "$work/computed.json")"

step "the same page with one byte changed no longer matches"
python3 -c "
import sys
page = open(sys.argv[1], 'rb').read()
at = page.rindex(b'</html>')
open(sys.argv[2], 'wb').write(page[:at] + b'<!-- edited -->' + page[at:])
" "$work/report.html" "$work/edited.html"
set +e
"$CTL" book report check --profile report --page "$work/edited.html" >"$work/edited-check.json" 2>/dev/null
edited=$?
set -e
[[ "$edited" -ne 0 && $(jq -r .page "$work/edited-check.json") != "match" ]] \
  || fail "an edited page still checks: $(cat "$work/edited-check.json")"
printf 'edited page: exit %s, %s\n' "$edited" "$(jq -c . "$work/edited-check.json")"

step "a question with no Terms Pack: an honest refusal, no count"
set +e
python3 "$REPO/scripts/packs.py" require personal-deals >"$work/refusal.json"
refused=$?
set -e
[[ "$refused" -eq 3 ]] || fail "packs.py require personal-deals exited $refused, not 3"
jq -e '.refused == "no_pack" and (.packs | index("everyday-rules")) and (.say | test("[0-9]") | not)' \
  "$work/refusal.json" >/dev/null || fail "the refusal is not the honest one: $(cat "$work/refusal.json")"
printf 'refused: %s\n' "$(jq -r .say "$work/refusal.json")"

printf '\nFRESH-ENV-REPORT: PASS\n'
