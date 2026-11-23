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
REASONS_CHECK=NOT-RUN
page_check() {
  local node=$1 page=$2
  if [[ -z "$CHROME" ]]; then printf '%s page text: NOT RUN (no Chrome; set CHROME)\n' "$node"; return 0; fi  # the run then fails at the end: no pass without it
  "$CHROME" --headless=new --use-mock-keychain --password-store=basic --user-data-dir="$work/chrome-profile" --disable-gpu --window-size=1280,2400 --virtual-time-budget=60000 --enable-logging=stderr --v=0 --dump-dom "file://$page" >"$work/$node.dom" 2>"$work/$node.chrome.log" || true
  # The window size is set because, on the CI runner's Chrome 157 (Linux), the default window made
  # the viewer refuse the contract report ("The presentation for this bundle failed") after the
  # page settled, and of four flag variants only the larger window drew it (checked on CI, #102).
  # Chrome headless can exit non-zero from its own teardown after it has written the DOM, so the gate is the DOM and the checks on it, not its status.
  [[ -s "$work/$node.dom" ]] || fail "$node: Chrome wrote no DOM for the page"
  python3 - "$work/$node.dom" "$PACK" "${node%-legs}" <<'EOF' || fail "$node: the page does not show the wording pack"
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

# Every `reason` a claim carries must be the registered leg token on a self-attested row, and the
# page's text must carry the pack's sentence for it (capsule-viewer draws it beside the row, labelled
# as the producer's statement; a viewer older than go v0.20.0 draws none).
reasons_check() {
  local node=$1 result=$2 page=$3 dom=$work/$node-open.dom
  if [[ -z "$CHROME" ]]; then printf '%s claim reasons: NOT RUN (no Chrome; set CHROME)\n' "$node"; return 0; fi  # the run then fails at the end
  # The runtime builds a row's claims when the row opens; depth L2 in the page's render options opens
  # them all, so the dump holds the reason lines (evidencebook capsulectl/internal/book/report_reason_test.go
  # does the same). The copy is read for its text only: its content-security meta is removed so the
  # edited options run, and it is never checked or handed over.
  python3 - "$page" "$work/$node-open.html" <<'EOF' || fail "$node: could not open the page's rows"
import pathlib, re, sys
page = pathlib.Path(sys.argv[1]).read_text()
opened = page.replace('{"audience":"*"', '{"audience":"*","depth":"L2"', 1)
if opened == page:
    sys.exit("the page has no render options to open")
opened = re.sub(r'<meta http-equiv="Content-Security-Policy"[^>]*>', "", opened)
pathlib.Path(sys.argv[2]).write_text(opened)
EOF
  "$CHROME" --headless=new --use-mock-keychain --password-store=basic --user-data-dir="$work/chrome-profile" --disable-gpu --window-size=1280,2400 --virtual-time-budget=60000 --dump-dom "file://$work/$node-open.html" >"$dom" 2>/dev/null || true
  [[ -s "$dom" ]] || fail "$node: Chrome wrote no DOM for the opened page"
  REASONS_CHECK=PASS
  python3 - "$result" "$dom" "$PACK" <<'EOF' || fail "$node: the claim reason is not on the page in the pack's words"
import html, json, re, sys
result, dom, pack = sys.argv[1:4]
claims = json.load(open(result))["claims"]
entries = json.load(open(pack))["entries"]
text = open(dom).read()
text = re.sub(r"<script.*?</script>|<style.*?</style>", "", text, flags=re.S)
text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text)))
withreason = [c for c in claims if "reason" in c]
problems = []
if not withreason:
    problems.append("no claim carries a reason")
for c in withreason:
    key = f"row.{c['requirement_ref']}.reason.{c['reason']}"
    if c["reason"] != "counterparty_leg_signer_not_trusted" or c["grade"] != "self-attested":
        problems.append(f"unexpected reason {c['reason']!r} on a {c['grade']} claim {c['id']}")
    sentence = re.sub(r"\s+", " ", entries.get(key, ""))
    if not sentence:
        problems.append(f"the pack has no sentence {key}")
    elif sentence not in text:
        problems.append(f"the page does not show {key}: {sentence!r}")
if "x-countersign" in json.dumps(claims):
    problems.append("a claim still carries x-countersign")
if problems:
    print("; ".join(problems), file=sys.stderr)
    sys.exit(1)
print(f"claim reasons shown on the page in the pack's words: {len(withreason)} claim(s)")
EOF
}

export HOME=$work/home XDG_CONFIG_HOME=$work/home/.config
mkdir -p "$XDG_CONFIG_HOME"
"$CTL" book report check --help >/dev/null 2>&1 || fail "$CTL has no \`book report check\` (capsulectl-book plugin missing or too old)"
"$CTL" book report build --help 2>&1 | grep -q -- '--wording-digest' || fail "$CTL has no \`book report build --wording\` (capsulectl-book too old)"
PACK=$REPO/wording/inference-deals-settlement-en.json
PACK_DIGEST=$(tr -d '[:space:]' < "$REPO/wording/inference-deals-settlement-en.sha256")

# provider-legs: the provider's book also holds the payer's terms legs its payee legs name. Those legs
# are signed by the payer's own key, which this reader does not trust, so every settled row stays
# self-attested and its claim carries the registered `reason` counterparty_leg_signer_not_trusted
# (AAC evidence-result-v0 section 4.4); the page must show the pack's sentence for it (#209).
python3 - "$REPO/tests/fixtures/inference-deals" "$work/provider-legs.jsonl" <<'EOF'
import json, pathlib, sys
src, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
provider = [json.loads(l) for l in (src / "provider.jsonl").read_text().splitlines()]
payer = [json.loads(l) for l in (src / "payer.jsonl").read_text().splitlines()]
named = {c["settlement"]["terms_ref"] for c in provider if "settlement" in c}
lines = [json.dumps(c) for c in provider + [c for c in payer if c["capsule_id"] in named]]
out.write_text("\n".join(lines) + "\n")
EOF

for node in payer provider provider-legs; do
  base=${node%-legs}
  if [[ $node == provider-legs ]]; then records=$work/provider-legs.jsonl; else records=$REPO/tests/fixtures/inference-deals/$node.jsonl; fi
  step "$node: a book with the $base node's records"
  "$CTL" key generate --output "$work/$node.seed" >"$work/$node.json"
  "$CTL" key generate --output "$work/$node-cp.seed" >"$work/$node-cp.json"
  "$CTL" profile create --name "$node" --type jsonl --jsonl-path "$work/$node-store" \
    --namespace "$node" --log-id "$node-log" --log book --operator "$node-node" \
    --signing-key-file "$work/$node.seed" --trusted-key "$(jq -r .public_key "$work/$node.json")" \
    --checkpoint-signing-key-file "$work/$node-cp.seed" \
    --checkpoint-trusted-key "$(jq -r .public_key "$work/$node-cp.json")" >/dev/null
  "$CTL" store init --profile "$node" >/dev/null
  mkdir -p "$work/$node-requests"
  python3 - "$records" "$work/$node-requests" "$node-node" <<'EOF'
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
  printf '%s claims: %s\n' "$node" "$(jq -c '[.claims[] | [.id, .verdict, .grade, .reason]]' "$result")"
  if [[ $node == provider-legs ]]; then
    reasons_check "$node" "$result" "$work/$node.html"
  fi
done

[[ "$PAGE_CHECK" == PASS ]] || fail "the page text check did not run (no Chrome; set CHROME): the wording is not shown to be on the page, so this is not a pass"
[[ "$REASONS_CHECK" == PASS ]] || fail "the claim reasons were not checked on the page (no Chrome; set CHROME), so this is not a pass"
printf '\nFRESH-ENV-DEALS: PASS (log: %s; page text check: %s; claim reasons on the page: %s)\n' "$log" "$PAGE_CHECK" "$REASONS_CHECK"
