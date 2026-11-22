#!/usr/bin/env bash
# The inference-deals pack end to end (evidencebook-skills#71, acceptance 4):
# a node's records sealed into a fresh book, `report.sh --seal` over
# packs/inference-deals, and `book report check` saying match with the embedded
# evidence VALID, once for the payer node's book and once for the provider's.
#
#   tests/fresh_env_deals.sh [LOG_FILE]
#
# Environment:
#   CAPSULECTL     a capsulectl that loads the capsulectl-book plugin (required;
#                  with CAPSULECTL_PLUGIN_ROOTS pointing at the plugin when it is
#                  not on a default root). `book report build --seal` and `book
#                  report check` are on evidencebook main, not yet in a
#                  capsulectl-book release.
#
# The records are tests/fixtures/inference-deals/{payer,provider}.jsonl, each one
# Mesh capsule the plugin's producer sealed (see that directory's README). Each
# goes into the book as one record whose payload is the capsule, stamped with the
# capsule's own time. The report's --date is the end of the fixtures' week, so the
# window's last closed period holds them; --now says that week has closed, as it
# has for anyone replaying these recorded fixtures after 2026-11-02. No model runs.
set -euo pipefail

CTL=${CAPSULECTL:?set CAPSULECTL to a capsulectl that loads the capsulectl-book plugin}
REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
DATE=2026-11-01

work=$(mktemp -d)
log=${1:-$work/fresh-env-deals.log}
exec > >(tee "$log") 2>&1
step() { printf '\n== %s ==\n' "$*"; }
fail() { printf 'FRESH-ENV-DEALS: FAIL -- %s\n' "$*"; exit 1; }

# The page as a person sees it: the settled page opened in a headless Chrome (CHROME, or the
# usual places), its visible text, must carry the pack's row labels and verdict words and no raw
# clause id, and must not say the viewer refused the pack. The viewer drops a pack it refuses and
# the page still seals and checks match VALID, so only this look at the text catches that. No
# Chrome: say NOT RUN and fail the run, never pass.
CHROME=${CHROME:-}
for c in "$CHROME" "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" google-chrome chromium chrome; do
  if [[ -n "$c" ]] && command -v "$c" >/dev/null 2>&1; then CHROME=$c; break; else CHROME=; fi
done
PAGE_CHECK=NOT-RUN
page_check() {
  local node=$1 page=$2
  if [[ -z "$CHROME" ]]; then printf '%s page text: NOT RUN (no Chrome; set CHROME)\n' "$node"; return 0; fi  # the run then fails at the end: no pass without it
  "$CHROME" --headless=new --use-mock-keychain --password-store=basic --user-data-dir="$work/chrome-profile" --disable-gpu --window-size=1280,2400 --virtual-time-budget=60000 --enable-logging=stderr --v=0 --dump-dom "file://$page" >"$work/$node.dom" 2>"$work/$node.chrome.log" || true
  # The window size is set because, on the CI runner's Chrome 157 (Linux), the default window made
  # the viewer refuse the contract report ("The presentation for this bundle failed") after the
  # page settled, and of four flag variants only the larger window drew it (checked on CI, #102).
  # Chrome headless can exit non-zero from its own teardown after it has written the DOM, so the gate is the DOM and the checks on it, not its status.
  [[ -s "$work/$node.dom" ]] || fail "$node: Chrome wrote no DOM for the page"
  python3 - "$work/$node.dom" "$PACK" "$node" <<'EOF' || fail "$node: the page does not show the wording pack"
import html, json, re, sys
dom, pack, node = sys.argv[1:4]
text = open(dom).read()
text = re.sub(r"<script.*?</script>|<style.*?</style>", "", text, flags=re.S)
text = html.unescape(re.sub(r"<[^>]+>", "\n", text))
entries = json.load(open(pack))["entries"]
rows = {"provider": ["served_as_agreed", "served_named_model"], "payer": ["paid_as_agreed"]}[node]
problems = []
if "wording pack supplied with this page was refused" in text:
    problems.append("the viewer refused the pack")
for row in rows:
    label = entries[f"row.come_through.{row}.label"]
    if label not in text:
        problems.append(f"row label not shown: {label!r}")
    if f"come_through.{row}" in text:
        problems.append(f"raw clause id shown: come_through.{row}")
if entries["group.come_through.title"] not in text:
    problems.append("group title not shown")
def shown(word):
    return re.search(r"(?<![A-Za-z])" + re.escape(word) + r"(?![A-Za-z])", text) is not None
if not shown(entries["verdict.met"]):
    problems.append("verdict word 'met' not shown")
if entries["report.title"] not in text:
    problems.append("report title not shown")
if node == "provider":  # its fixtures hold an undecided and a not-met deal
    for verdict in ("verdict.not_met", "verdict.not_evaluable"):
        if not shown(entries[verdict]):
            problems.append(f"{verdict} word not shown")
if problems:
    print("; ".join(problems), file=sys.stderr)
    print("--- the page's visible text, first 3000 characters ---", file=sys.stderr)
    print(re.sub(r"\n\s*\n+", "\n", text)[:3000], file=sys.stderr)
    log = open(dom[:-4] + ".chrome.log").read().splitlines()
    print("--- Chrome's console lines ---", file=sys.stderr)
    print("\n".join(l[:400] for l in log if "CONSOLE" in l or "Uncaught" in l)[:3000], file=sys.stderr)
    sys.exit(1)
EOF
  PAGE_CHECK=PASS
  printf '%s page text: the pack'"'"'s row labels, group title and verdict words are shown\n' "$node"
}

export HOME=$work/home XDG_CONFIG_HOME=$work/home/.config
mkdir -p "$XDG_CONFIG_HOME"
"$CTL" book report check --help >/dev/null 2>&1 || fail "$CTL has no \`book report check\` (capsulectl-book plugin missing or too old)"
"$CTL" book report build --help 2>&1 | grep -q -- '--wording-digest' || fail "$CTL has no \`book report build --wording\` (capsulectl-book too old)"
PACK=$REPO/wording/inference-deals-settlement-en.json
PACK_DIGEST=$(tr -d '[:space:]' < "$REPO/wording/inference-deals-settlement-en.sha256")

for node in payer provider; do
  step "$node: a book with the $node node's records"
  "$CTL" key generate --output "$work/$node.seed" >"$work/$node.json"
  "$CTL" key generate --output "$work/$node-cp.seed" >"$work/$node-cp.json"
  "$CTL" profile create --name "$node" --type jsonl --jsonl-path "$work/$node-store" \
    --namespace "$node" --log-id "$node-log" --log book --operator "$node-node" \
    --signing-key-file "$work/$node.seed" --trusted-key "$(jq -r .public_key "$work/$node.json")" \
    --checkpoint-signing-key-file "$work/$node-cp.seed" \
    --checkpoint-trusted-key "$(jq -r .public_key "$work/$node-cp.json")" >/dev/null
  "$CTL" store init --profile "$node" >/dev/null
  mkdir -p "$work/$node-requests"
  python3 - "$REPO/tests/fixtures/inference-deals/$node.jsonl" "$work/$node-requests" "$node-node" <<'EOF'
import json, pathlib, sys
src, out, operator = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), sys.argv[3]
for i, line in enumerate(src.read_text().splitlines()):
    capsule = json.loads(line)
    request = {"spec_version": "capsule-seal-request/v1",
               "capsule": {"ActionID": f"urn:mesh-record:{capsule['capsule_id']}", "ActionType": "fyi",
                           "Operator": operator, "Developer": "evidencebook-skills/fresh_env_deals",
                           "Timestamp": capsule["timestamp"]},
               "payload": capsule}
    (out / f"{i:04d}.json").write_text(json.dumps(request, sort_keys=True))
EOF
  for request in "$work/$node-requests"/*.json; do
    "$CTL" publish --profile "$node" --request "$request" >/dev/null
  done

  step "$node: report.sh --seal over packs/inference-deals, then report check"
  bash "$REPO/scripts/report.sh" --spec "$REPO/packs/inference-deals/compiled/compiled.json" --profile "$node" \
    --date "$DATE" --now 2026-11-02T00:00:00Z --out "$work/$node.html" --capsulectl "$CTL" \
    --work "$work/$node-run" --seal --wording "$PACK" --wording-digest "$PACK_DIGEST" \
    || fail "$node: report.sh --seal did not hand over a checked page"
  "$CTL" book report check --profile "$node" --page "$work/$node.html" >"$work/$node-check.json" \
    || fail "$node: report check refuses the handed-over page: $(cat "$work/$node-check.json")"
  [[ $(jq -r '"\(.page) \(.verification)"' "$work/$node-check.json") == "match VALID" ]] \
    || fail "$node: report check does not say match VALID: $(cat "$work/$node-check.json")"
  printf '%s report check: %s\n' "$node" "$(jq -c . "$work/$node-check.json")"
  page_check "$node" "$work/$node.html"
  result=$(ls "$work/$node-run"/run.*/rollup/result-v0-*.json)
  printf '%s window: %s\n' "$node" "$(jq -c '."x-window"' "$result")"
  printf '%s claims: %s\n' "$node" "$(jq -c '[.claims[] | [.id, .verdict, .grade]]' "$result")"
done

[[ "$PAGE_CHECK" == PASS ]] || fail "the page text check did not run (no Chrome; set CHROME): the wording is not shown to be on the page, so this is not a pass"
printf '\nFRESH-ENV-DEALS: PASS (log: %s; page text check: %s)\n' "$log" "$PAGE_CHECK"
