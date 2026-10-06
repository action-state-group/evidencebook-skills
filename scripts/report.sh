#!/usr/bin/env bash
# report.sh -- ONE COMMAND: report.html from a book, --spec picks the path.
#
# A --spec that is a report-spec/v1 YAML (scripts/report_spec.py,
# scripts/specs/*.yaml) goes the NO-JUDGE path: every claim is computed
# deterministically from the sealed records themselves, no rubric, no Jev.
# A --spec that is a compiled pack contract (scripts/pack_compile.py's own
# compiled.json, e.g. demo/airline-support-outcomes/compiled.json) goes the
# JUDGED path: scripts/run_daily.py (one Jev call per clause per case, mock
# backend by default) then scripts/rollup_day.py's all-required rollup.
# Both paths converge on the SAME tail: capsulectl result build -> a fresh
# checkpoint -> disclose -> (judged path only) wire the pack's own
# outcome-invoice/v1 presentation settings -> report build.
#
#   report.sh --spec SPEC --profile NAME --date YYYY-MM-DD [--to YYYY-MM-DD] \
#       --out report.html [--work DIR] [--capsulectl PATH] [--card CARD] \
#       [--judge-cmd CMD] [--judge-model-id ID] [--judge-backend mock|live]
#
# --profile names an ALREADY SET UP book (this command builds the report
# from one; it does not seal data into it -- see scripts/outcomes_setup.sh
# for that step, or your own producer's own sealing). Every capsulectl call
# below runs in the CALLER's own environment (HOME/XDG_CONFIG_HOME
# unchanged) unless --work is given, in which case intermediate files (never
# the final --out) live under it.
#
# --card defaults to the spec's own `presentation.card` (report-spec path)
# or "outcome" (judged path, the pack's own card); --judge-backend defaults
# to mock (scripts/judges/jev_judge.py's mock backend, no key, no network
# call) -- pass --judge-backend live with TYPESAFE_API_KEY set in the
# environment for a real Jev run. --judge-cmd/--judge-model-id are read from
# the compiled pack by default (its own judge.model_id) and almost never
# need to be given explicitly.
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
usage: report.sh --spec SPEC --profile NAME --date YYYY-MM-DD [--to YYYY-MM-DD] --out report.html
                  [--work DIR] [--capsulectl PATH] [--card CARD]
                  [--judge-cmd CMD] [--judge-model-id ID] [--judge-backend mock|live]
EOF
  exit 2
}

SPEC= PROFILE= DATE= TO= OUT= WORK= CAPSULECTL=capsulectl CARD= JUDGE_CMD= JUDGE_MODEL_ID= JUDGE_BACKEND=mock
while [[ $# -gt 0 ]]; do
  case "$1" in
    --spec) SPEC=$2; shift 2 ;;
    --profile) PROFILE=$2; shift 2 ;;
    --date) DATE=$2; shift 2 ;;
    --to) TO=$2; shift 2 ;;
    --out) OUT=$2; shift 2 ;;
    --work) WORK=$2; shift 2 ;;
    --capsulectl) CAPSULECTL=$2; shift 2 ;;
    --card) CARD=$2; shift 2 ;;
    --judge-cmd) JUDGE_CMD=$2; shift 2 ;;
    --judge-model-id) JUDGE_MODEL_ID=$2; shift 2 ;;
    --judge-backend) JUDGE_BACKEND=$2; shift 2 ;;
    *) usage ;;
  esac
done
[[ -n "$SPEC" && -n "$PROFILE" && -n "$DATE" && -n "$OUT" ]] || usage
[[ -f "$SPEC" ]] || { echo "report.sh: no such spec file: $SPEC" >&2; exit 2; }
[[ "$JUDGE_BACKEND" == "mock" || "$JUDGE_BACKEND" == "live" ]] || usage
if [[ "$JUDGE_BACKEND" == "live" ]]; then
  [[ -n "${TYPESAFE_API_KEY:-}" ]] || { echo "report.sh: --judge-backend live needs TYPESAFE_API_KEY set" >&2; exit 2; }
fi

REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
WORK=${WORK:-$(mktemp -d)}
mkdir -p "$WORK"
step() { printf '\n== %s ==\n' "$*"; }
fail() { printf 'report.sh: FAIL -- %s\n' "$*" >&2; exit 1; }

# the day range this report covers. A plain command-substitution assignment
# (not `mapfile < <(...)`, whose own exit status -- not the process
# substitution's -- is what `set -e` would see, silently losing a failure
# from the Python below) so a bad --date/--to actually stops the script here.
DATES_RAW=$(python3 -c "
import datetime as d, sys
a = d.date.fromisoformat(sys.argv[1])
b = d.date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] else a
if b < a:
    sys.exit('report.sh: --to is before --date')
cur = a
while cur <= b:
    print(cur.isoformat())
    cur += d.timedelta(days=1)
" "$DATE" "${TO:-}")
mapfile -t DATES <<< "$DATES_RAW"
[[ ${#DATES[@]} -ge 1 ]] || fail "empty date range"
GENERATED_AT="${DATES[-1]}T23:59:59Z"

# --spec's own kind: report-spec/v1 (no judge) or a compiled pack contract (judged).
MODE=$(python3 -c "
import json, sys
import yaml
spec = yaml.safe_load(open(sys.argv[1]))
if isinstance(spec, dict) and spec.get('spec_version') == 'report-spec/v1':
    print('no-judge')
elif isinstance(spec, dict) and 'clauses' in spec and 'judge' in spec:
    print('judged')
else:
    sys.exit('report.sh: ' + sys.argv[1] + ' is neither a report-spec/v1 YAML nor a compiled pack contract (no clauses+judge)')
" "$SPEC")
step "spec kind: $MODE ($SPEC)"

mkdir -p "$WORK/rollup"
if [[ "$MODE" == "no-judge" ]]; then
  step "report_spec.py: deterministic claims from the sealed records, no judge"
  python3 "$REPO/scripts/report_spec.py" --profile "$PROFILE" --spec "$SPEC" --capsulectl "$CAPSULECTL" \
    --generated-at "$GENERATED_AT" --out "$WORK/rollup" --date-from "${DATES[0]}" --date-to "${DATES[-1]}"
  DEFAULT_CARD=$(python3 -c "import yaml,sys; print((yaml.safe_load(open(sys.argv[1])).get('presentation') or {}).get('card', 'outcome'))" "$SPEC")
else
  JUDGE_MODEL_ID=${JUDGE_MODEL_ID:-$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['judge']['model_id'])" "$SPEC")}
  JUDGE_CMD=${JUDGE_CMD:-"python3 $REPO/scripts/judges/jev_judge.py"}
  if [[ "$JUDGE_BACKEND" == "mock" ]]; then
    EFFECTIVE_MODEL_ID="$JUDGE_MODEL_ID (mock backend, no model read the conversation)"
  else
    EFFECTIVE_MODEL_ID="$JUDGE_MODEL_ID"
  fi
  for day in "${DATES[@]}"; do
    step "daily-judge-and-close: $day"
    if [[ "$JUDGE_BACKEND" == "mock" ]]; then
      JEV_JUDGE_BACKEND=mock python3 "$REPO/scripts/run_daily.py" --profile "$PROFILE" --spec "$SPEC" \
        --capsulectl "$CAPSULECTL" --judge-cmd "$JUDGE_CMD" --judge-model-id "$EFFECTIVE_MODEL_ID" \
        --date "$day" --out "$WORK/runs"
    else
      python3 "$REPO/scripts/run_daily.py" --profile "$PROFILE" --spec "$SPEC" --capsulectl "$CAPSULECTL" \
        --judge-cmd "$JUDGE_CMD" --judge-model-id "$EFFECTIVE_MODEL_ID" --date "$day" --out "$WORK/runs"
    fi
  done
  step "rollup_day.py: the all-required rollup, pin-scoped to the current compiled pack"
  python3 "$REPO/scripts/rollup_day.py" --profile "$PROFILE" --spec "$SPEC" --capsulectl "$CAPSULECTL" \
    --generated-at "$GENERATED_AT" --judge-model-id "$EFFECTIVE_MODEL_ID" --out "$WORK/rollup"
  DEFAULT_CARD=outcome
fi
CARD=${CARD:-$DEFAULT_CARD}

# one result-v0-<day>.json per day either path just wrote; merge if more than one.
shopt -s nullglob
DAY_RESULTS=("$WORK"/rollup/result-v0-*.json)
shopt -u nullglob
[[ ${#DAY_RESULTS[@]} -ge 1 ]] || fail "no result-v0-*.json written for ${DATES[0]}..${DATES[-1]} -- nothing to report on"
if [[ ${#DAY_RESULTS[@]} -eq 1 ]]; then
  RESULT_V0="${DAY_RESULTS[0]}"
else
  step "merge_results.py: combine ${#DAY_RESULTS[@]} days into one Result v0"
  # $MODE (already known, not re-sniffed) picks the field: a report-spec/v1
  # YAML's own `title`, or a compiled pack contract's `contract` id -- yaml.safe_load
  # parses well-formed JSON without error (JSON is a YAML subset), so trying the
  # YAML read first and falling back to JSON on a parse failure never reaches the
  # JSON branch for a compiled pack (its title key is simply absent, not a parse
  # error), which silently fell back to the literal $SPEC path. Branching on $MODE
  # reads the field that actually exists for each kind instead of guessing from
  # which parse happened not to throw.
  if [[ "$MODE" == "no-judge" ]]; then
    # same fallback scripts/report_spec.py's own render_title() uses: title, else id.
    TITLE=$(python3 -c "import yaml,sys; s=yaml.safe_load(open(sys.argv[1])); print(s.get('title', s['id']))" "$SPEC")
  else
    TITLE=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['contract'])" "$SPEC")
  fi
  RESULT_V0="$WORK/rollup/result-v0-merged.json"
  python3 "$REPO/scripts/merge_results.py" --title "$TITLE -- ${DATES[0]} to ${DATES[-1]}" \
    --generated-at "$GENERATED_AT" --out "$RESULT_V0" "${DAY_RESULTS[@]}"
fi

step "capsulectl result build: seal the Result v0 into the book"
"$CAPSULECTL" result build --profile "$PROFILE" --result "$RESULT_V0" --out "$WORK/result-sealed.json" \
  | tee "$WORK/result-build.json"
RESULT_CAPSULE=$(jq -r '.record_id' "$WORK/result-build.json")
[[ -n "$RESULT_CAPSULE" && "$RESULT_CAPSULE" != "null" ]] || fail "result build printed no .record_id"

step "cll checkpoint create: a fresh checkpoint covering the just-sealed Result v0"
"$CAPSULECTL" cll checkpoint create --profile "$PROFILE" | tee "$WORK/checkpoint-create.json"

step "capsulectl disclose: assemble the Evidence Bundle rooted at the sealed Result v0"
"$CAPSULECTL" disclose --profile "$PROFILE" --root "$RESULT_CAPSULE" --closure-depth 2 --out "$WORK/bundle.json"
uncheckpointed=$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(len(d['records']) - len(d.get('completeness_certificate',{}).get('memberships',{})))" "$WORK/bundle.json")
[[ "$uncheckpointed" -eq 0 ]] || fail "$uncheckpointed records in the disclosed bundle have no membership entry"
BUNDLE="$WORK/bundle.json"

if [[ "$MODE" == "judged" ]]; then
  # The pack-compiler convention (scripts/pack_compile.py): a compiled.json
  # always has a presentation.json beside it. `${SPEC/compiled.json/presentation.json}`
  # is a no-op (equals $SPEC itself) for any --spec not literally named
  # "compiled.json" -- guarded explicitly rather than relying on an unlikely
  # coincidence, so a differently-named contract skips this step cleanly
  # instead of trying to read its own compiled.json as a presentation file.
  PRESENTATION_JSON="${SPEC/compiled.json/presentation.json}"
  if [[ "$PRESENTATION_JSON" != "$SPEC" && -f "$PRESENTATION_JSON" ]]; then
    step "wire the pack's own outcome-invoice/v1 presentation extension into the bundle"
    BUNDLE="$WORK/bundle-with-invoice.json"
    python3 -c "
import json, sys
bundle_path, pres_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
bundle = json.load(open(bundle_path))
presentation = (json.load(open(pres_path)) or {}).get('outcome-invoice/v1')
if presentation is None:
    print(f'report.sh: {pres_path} carries no outcome-invoice/v1 block -- skipping', file=sys.stderr)
else:
    bundle.setdefault('extensions', {})['outcome-invoice/v1'] = {
        'enabled': True, 'percentages': presentation['percentages'],
        'price_per_resolved': presentation['price_per_resolved'],
    }
json.dump(bundle, open(out_path, 'w'))
" "$WORK/bundle.json" "$PRESENTATION_JSON" "$BUNDLE"
  fi
fi

PRESENTATION_FILE="$WORK/presentation.json"
python3 -c "
import json, sys
result_v0_path, out_path = sys.argv[1], sys.argv[2]
title = json.load(open(result_v0_path))['view']['title']
json.dump({'title': title}, open(out_path, 'w'))
" "$RESULT_V0" "$PRESENTATION_FILE"

step "capsulectl report build: render $OUT (--card $CARD)"
mkdir -p "$(dirname "$OUT")"
"$CAPSULECTL" report build --profile "$PROFILE" --bundle "$BUNDLE" --card "$CARD" \
  --presentation "$PRESENTATION_FILE" --out "$OUT" | tee "$WORK/report-build.json"
[[ -f "$OUT" ]] || fail "report.html was not written"

printf '\nreport complete -- %s (%s bytes)\n' "$OUT" "$(stat -c%s "$OUT" 2>/dev/null || stat -f%z "$OUT")"
