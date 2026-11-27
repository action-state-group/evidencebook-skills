#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# capsulectl-release.sh VERSION PLATFORM DEST NAME...: each released binary NAME at VERSION for PLATFORM, checked
# against its release's SHA256SUMS line, installed as DEST/NAME. capsulectl comes from capsule-cli's release VERSION,
# a plugin (capsulectl-deal, capsulectl-book) from evidencebook's release capsulectl/VERSION. Needs gh and GH_TOKEN.
set -euo pipefail
v=$1 plat=$2 dest=$3
shift 3
dl=$(mktemp -d)
trap 'rm -rf "$dl"' EXIT
for name in "$@"; do
  if [[ "$name" == capsulectl ]]; then repo=capsule-cli tag=$v; else repo=evidencebook tag=capsulectl/$v; fi
  file="$name-$v-$plat"
  mkdir -p "$dl/$name"
  gh release download "$tag" -R "action-state-group/$repo" -D "$dl/$name" -p SHA256SUMS -p "$file"
  line=$(awk -v f="$file" '$2 == f && length($1) == 64' "$dl/$name/SHA256SUMS")
  [[ -n "$line" ]] || { echo "capsulectl-release.sh: $file is not in $repo $tag's SHA256SUMS" >&2; exit 1; }
  (cd "$dl/$name" && sha256sum -c - <<<"$line")
  install -m 755 "$dl/$name/$file" "$dest/$name"
done
