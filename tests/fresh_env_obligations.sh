#!/usr/bin/env bash
# The eu-ai-act-obligations report path (eu-ai-act-obligations-report/v2), end to
# end: tau2 cases seeded into a book in a week that has ended (tests/bookfixture
# writes the book log the pinned capsulectl-book reads), then scripts/report.sh on
# the judged path over the pack's compiled contract, closing the period, with the
# mock judge. The page's finding rows are checked: each finding has its id and
# observed text, and at least one obligation is read not met.
#
#   tests/fresh_env_obligations.sh [LOG_FILE]
#
# Environment:
#   CAPSULECTL     a capsulectl binary that loads the capsulectl-book plugin
#                  (required; CAPSULECTL_PLUGIN_ROOTS names the plugin's folder
#                  when it is not on a default root)
#   CASES          how many recorded tau2 airline runs to seal (default: 4)
#
# The judge is the mock backend (scripts/judges/jev_judge.py), so no model reads a
# conversation and no key or network call is used.
set -euo pipefail

CTL=${CAPSULECTL:?set CAPSULECTL to a capsulectl that loads the capsulectl-book plugin}
CASES=${CASES:-4}
REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SPEC=$REPO/demo/eu-ai-act-obligations/compiled.json

work=$(mktemp -d)
log=${1:-$work/fresh-env-obligations.log}
exec > >(tee "$log") 2>&1
step() { printf '\n== %s ==\n' "$*"; }
fail() { printf 'FRESH-ENV-OBLIGATIONS: FAIL -- %s\n' "$*"; exit 1; }

export HOME=$work/home XDG_CONFIG_HOME=$work/home/.config
mkdir -p "$XDG_CONFIG_HOME"
"$CTL" book report check --help >/dev/null 2>&1 || fail "$CTL has no \`book report check\` (capsulectl-book plugin missing or too old)"
"$CTL" --version

step "build the book fixture"
mkdir -p "$work/bin"
(cd "$REPO/tests/bookfixture" && go build -o "$work/bin/bookfixture" .)

step "a book: keys, profile, store"
"$CTL" key generate --output "$work/producer.seed" >"$work/producer.json"
"$CTL" key generate --output "$work/checkpoint.seed" >"$work/checkpoint.json"
"$CTL" profile create --name eu --type jsonl --jsonl-path "$work/store" \
  --namespace tau2 --log-id tau2-airline --log book --operator tau2-demo \
  --signing-key-file "$work/producer.seed" --trusted-key "$(jq -r .public_key "$work/producer.json")" \
  --checkpoint-signing-key-file "$work/checkpoint.seed" --checkpoint-trusted-key "$(jq -r .public_key "$work/checkpoint.json")" >/dev/null

# The cases go into the previous ISO week's Wednesday: a day that has ended, so the
# judged path can close its period.
day=$(python3 -c 'import datetime as d; t=d.date.today(); m=t-d.timedelta(days=t.weekday()+7); print(m+d.timedelta(days=2))')
step "seal $CASES recorded tau2 airline runs and seed them into the book on $day"
python3 "$REPO/demo/backfill/backfill.py" \
  --results "$REPO/airline-data/claude-3-7-sonnet-20250219_airline_default_gpt-4.1-2025-04-14_4trials.json" \
  --out "$work/requests" >/dev/null
mkdir -p "$work/cases"
for request in $(ls "$work/requests"/task-*.json | sort | head -n "$CASES"); do
  "$CTL" seal --profile eu --request "$request" --output "$work/cases/$(basename "$request")" >/dev/null
done
"$work/bin/bookfixture" seed --store "$work/store" --log-id tau2-airline --operator tau2-demo --namespace tau2 \
  --signing-key-file "$work/producer.seed" --checkpoint-key-file "$work/checkpoint.seed" --at "${day}T12:00:00Z" "$work/cases"/*.json
"$CTL" store init --profile eu >/dev/null
listed=$("$CTL" cll list --profile eu --limit 1000 | jq '[.entries[] | select(.record_type=="published_capsule")] | length')
[[ "$listed" -eq "$CASES" ]] || fail "capsulectl lists $listed cases, not $CASES: the seeded book is not the one this capsulectl reads"
printf '%s cases in the book, as capsulectl lists them\n' "$listed"

step "report.sh over the closed day $day: the eu-ai-act-obligations pack, mock judge"
python3 -m venv "$work/venv" >/dev/null
"$work/venv/bin/pip" install --quiet -r "$REPO/requirements.txt"
PATH="$work/venv/bin:$PATH" bash "$REPO/scripts/report.sh" --spec "$SPEC" --profile eu --date "$day" \
  --out "$work/report.html" --capsulectl "$CTL" --work "$work/run" --judge-backend mock \
  || fail "report.sh did not build the report"
[[ -s "$work/report.html" ]] || fail "no page handed over"
closes=$("$CTL" cll list --profile eu --all --limit 1000 | jq '[.entries[] | select(.record_type=="close")] | length')
[[ "$closes" -eq 1 ]] || fail "the book holds $closes Close records for the ended day, not 1"
printf 'the day %s is closed: %s Close record in the book\n' "$day" "$closes"

# The page as a person sees it: the settled page in a headless Chrome (CHROME, or the usual
# places). The viewer draws the findings in the browser, so only a look at the page's text shows
# that the v2 finding rows (id, observed, owner and due) are there. No Chrome: NOT RUN, and the
# run fails, never passes.
CHROME=${CHROME:-}
for c in "$CHROME" "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" google-chrome chromium chrome; do
  if [[ -n "$c" ]] && command -v "$c" >/dev/null 2>&1; then CHROME=$c; break; else CHROME=; fi
done
step "the page's finding rows, as Chrome draws them"
[[ -n "$CHROME" ]] || fail "page text: NOT RUN (no Chrome; set CHROME), so this is not a pass"
# Throwaway profile and the mock keychain flags, so the run raises no Keychain prompt.
"$CHROME" --headless=new --use-mock-keychain --password-store=basic --user-data-dir="$work/chrome-profile" \
  --disable-gpu --window-size=1280,2400 --virtual-time-budget=60000 --dump-dom "file://$work/report.html" \
  >"$work/report.dom" 2>"$work/chrome.log" || true
[[ -s "$work/report.dom" ]] || fail "Chrome wrote no DOM for the page"
result=$(ls "$work/run"/run.*/rollup/result-v0-"$day".json 2>/dev/null) || fail "no sealed Result for $day under $work/run"
python3 - "$result" "$work/report.dom" "$REPO/demo/eu-ai-act-obligations/presentation.json" <<'PYEOF' || fail "the page's finding rows are not what the sealed Result calls for"
import html, json, re, sys
result = json.load(open(sys.argv[1]))
text = open(sys.argv[2]).read()
text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S)
text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text)))
block = json.load(open(sys.argv[3]))["eu-ai-act-obligations-report/v2"]
not_met = {c["requirement_ref"] for c in result["claims"] if c["verdict"] == "not_met"}
if not not_met:
    sys.exit("no obligation is read not met in the sealed Result: the finding rows have nothing to show")
if "The presentation for this bundle failed" in text:
    sys.exit("the viewer refused the presentation")
problems, shown = [], []
rows = {row["criterion_id"] for obligation in block["obligations"] for row in obligation["rows"]}
for ref in sorted(not_met - rows):
    problems.append(f"{ref} is read not met but the v2 block has no row for it")
for obligation in block["obligations"]:
    for row in obligation["rows"]:
        finding = row.get("finding")
        if not finding:
            continue
        drawn = re.search(r"Finding %s (\d+) sessions?" % re.escape(finding["id"]), text) is not None
        if row["criterion_id"] in not_met:
            shown.append(finding["id"])
            if not drawn:
                problems.append(f"{finding['id']} ({row['criterion_id']}) is read not met but its finding row is not on the page")
            for key in ("observed", "owner_due"):
                if finding[key] not in text:
                    problems.append(f"{finding['id']}: the page does not carry its {key} text")
        elif drawn:
            problems.append(f"{finding['id']} ({row['criterion_id']}) has no not-met claim but its finding row is on the page")
if not shown:
    problems.append("no not-met requirement has a finding row, so no finding row was checked")
if problems:
    sys.exit("\n".join(problems))
print("finding rows on the page for the %d not-met requirement(s): %s" % (len(shown), ", ".join(sorted(shown))))
PYEOF
printf '\nFRESH-ENV-OBLIGATIONS: PASS (log: %s; capsulectl %s)\n' "$log" "$("$CTL" --version)"
