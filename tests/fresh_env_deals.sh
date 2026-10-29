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
# window's last closed period holds them. No model runs.
set -euo pipefail

CTL=${CAPSULECTL:?set CAPSULECTL to a capsulectl that loads the capsulectl-book plugin}
REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
DATE=2026-11-01

work=$(mktemp -d)
log=${1:-$work/fresh-env-deals.log}
exec > >(tee "$log") 2>&1
step() { printf '\n== %s ==\n' "$*"; }
fail() { printf 'FRESH-ENV-DEALS: FAIL -- %s\n' "$*"; exit 1; }

export HOME=$work/home XDG_CONFIG_HOME=$work/home/.config
mkdir -p "$XDG_CONFIG_HOME"
"$CTL" book report check --help >/dev/null 2>&1 || fail "$CTL has no \`book report check\` (capsulectl-book plugin missing or too old)"

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
    --date "$DATE" --out "$work/$node.html" --capsulectl "$CTL" --work "$work/$node-run" --seal \
    || fail "$node: report.sh --seal did not hand over a checked page"
  "$CTL" book report check --profile "$node" --page "$work/$node.html" >"$work/$node-check.json" \
    || fail "$node: report check refuses the handed-over page: $(cat "$work/$node-check.json")"
  [[ $(jq -r '"\(.page) \(.verification)"' "$work/$node-check.json") == "match VALID" ]] \
    || fail "$node: report check does not say match VALID: $(cat "$work/$node-check.json")"
  printf '%s report check: %s\n' "$node" "$(jq -c . "$work/$node-check.json")"
  result=$(ls "$work/$node-run"/run.*/rollup/result-v0-*.json)
  printf '%s window: %s\n' "$node" "$(jq -c '."x-window"' "$result")"
  printf '%s claims: %s\n' "$node" "$(jq -c '[.claims[] | [.id, .verdict, .grade]]' "$result")"
done

printf '\nFRESH-ENV-DEALS: PASS (log: %s)\n' "$log"
