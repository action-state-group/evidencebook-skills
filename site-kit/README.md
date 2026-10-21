# site kit: Terms Packs report pages

Everything needed to put four Terms Packs report pages on a website, and to
rebuild them yourself. Nothing here depends on the people who made it.

## what's here

| path | what it is |
|---|---|
| `pages/eu_2025-09-15_day.html` | EU AI Act obligations report, one day: 2025-09-15 |
| `pages/eu_2025-09_week5.html` | EU AI Act obligations report, week 5 of September 2025 (09-29 to 09-30) |
| `pages/outcomes_2025-09-15_day.html` | Customer support outcomes report (tau2-bench airline), one day: 2025-09-15 |
| `pages/outcomes_2025-09_week5.html` | Customer support outcomes report, week 5 of September 2025 (09-29 to 09-30) |
| `bundles/<same name>.bundle.json` | the sealed Evidence Bundle each page was built from |
| `tools/render-page.mjs` | a 20-line script that draws a page from a bundle with a capsule-viewer build (used for the new layout, below) |
| `homepage/terms-pack.md` | the homepage explainer text, as one paragraph |
| `MANIFEST.txt` | sha256 and size of every file, the verify result for each page and bundle, and the versions used |

The records are tau2-bench airline runs (four agent models), replayed into
September 2025 and sealed into an evidence book. Sizes and hashes are in
`MANIFEST.txt`.

## put them on a site (2 minutes)

1. Copy `pages/` to any path your site serves, for example `/reports/`.
   No build step, no server code, no config.
2. Link to them. The section below is ready to paste.
3. Optional: also copy `bundles/` next to them if you want people to be able
   to download the raw bundle and check it with `capsulectl verify`.

Each page is one self-contained `.html` file: the bundle, the page code and
the styles are all inside it. Check made on these four files (see
`MANIFEST.txt` for the exact output):

- no `<script src>`, no `<link>`, no `<iframe>`, no `src=` or `href=` to any
  `http(s)://` or `//` address, no CSS `url(http...)` or `@import`, no
  `fetch(`, `XMLHttpRequest`, `WebSocket`, `EventSource`, `sendBeacon` or
  `import(`. No `http://` or `https://` address appears anywhere in the four
  files.
- opened in headless Chrome with no network at all (its own network
  namespace, `unshare -rn`), each page verifies its embedded bundle and shows
  `verified` (`data-verify="verified"`).
- the bundle embedded in each page is identical to the matching file in
  `bundles/`.

## homepage text

Also in `homepage/terms-pack.md`:

> A Terms Pack is a set of rules or obligations, kept as one versioned file. Where a row's answer can be computed from the records, it's a deterministic check: same records, same answer. Where judgment is required, it's a judged question for a pinned judge, named on every verdict it gives. Deterministic wherever it can be, a pinned and measured model only where judgment is required. Run a pack over your agent's sealed records and you get a report that states only what those records show, one file you can verify offline. Two packs to start: EU AI Act obligations, and outcomes on the tau2-bench airline runs.

## homepage section, ready to paste

Plain HTML, no classes, no framework. Change `/reports/` to wherever you put
the pages.

```html
<section id="terms-packs">
  <h2>Terms Packs</h2>
  <p>A Terms Pack is a set of rules or obligations, kept as one versioned file. Where a row's answer can be computed from the records, it's a deterministic check: same records, same answer. Where judgment is required, it's a judged question for a pinned judge, named on every verdict it gives. Deterministic wherever it can be, a pinned and measured model only where judgment is required. Run a pack over your agent's sealed records and you get a report that states only what those records show, one file you can verify offline. Two packs to start: EU AI Act obligations, and outcomes on the tau2-bench airline runs.</p>
  <h3>Example reports</h3>
  <ul>
    <li>EU AI Act obligations: <a href="/reports/eu_2025-09-15_day.html">one day (2025-09-15)</a>, <a href="/reports/eu_2025-09_week5.html">one week (2025-09-29 to 09-30)</a></li>
    <li>Customer support outcomes, tau2-bench airline: <a href="/reports/outcomes_2025-09-15_day.html">one day (2025-09-15)</a>, <a href="/reports/outcomes_2025-09_week5.html">one week (2025-09-29 to 09-30)</a></li>
  </ul>
  <p>Each report is one file. Open it with no network and it still checks itself.</p>
  <p><a href="https://github.com/action-state-group/evidencebook-skills/blob/main/docs/quickstart.md">Quick start: turn your own agent logs into a report</a></p>
</section>
```

The quick start link points at `docs/quickstart.md` on `main` of
action-state-group/evidencebook-skills. That file is on PR #30's branch
(`desk/quickstart`) today; the link works once #30 merges.

## rebuild the pages with stock capsulectl rc18

Released capsulectl v0.1.0-rc18 rebuilds a page from a bundle. It needs no
profile, no keys and no network after the download. Needs `curl`, `jq` and
`sha256sum` (macOS: `shasum -a 256`). Run from the `site-kit/` directory:

```bash
V=v0.1.0-rc18; OS=linux-amd64    # or linux-arm64, darwin-arm64
R=https://github.com/action-state-group/capsule-cli/releases/download/$V
mkdir -p rc18 && cd rc18
curl -fsSLO $R/SHA256SUMS
curl -fsSLO $R/capsulectl-$V-$OS
curl -fsSLO $R/capsulectl-$V-plugin-book-$OS
grep -E " capsulectl-$V-($OS|plugin-book-$OS)$" SHA256SUMS | sha256sum -c -   # macOS: shasum -a 256 -c -
chmod +x capsulectl-$V-$OS capsulectl-$V-plugin-book-$OS
cd ..
export HOME=$(mktemp -d)          # a throwaway home: nothing below needs a profile or keys
C=./rc18/capsulectl-$V-$OS
$C --version
$C plugin install ./rc18/capsulectl-$V-plugin-book-$OS
mkdir -p rebuilt-rc18
for n in eu_2025-09-15_day eu_2025-09_week5 outcomes_2025-09-15_day outcomes_2025-09_week5; do
  case $n in eu_*) card=obligation;; *) card=outcome;; esac
  $C verify --bundle bundles/$n.bundle.json | jq -c '{verdict, bundle_digest}'
  $C book report build --bundle bundles/$n.bundle.json --card $card --out rebuilt-rc18/$n.html \
    | jq -c '{verdict, verification, claims, report}'
done
```

Expected: every `verify` line says `"verdict":"VALID"` with the
`bundle_digest` listed in `MANIFEST.txt`, and every `report build` line says
`"verdict":"VALID","verification":"pass"` with 218, 421, 192 and 356 claims.
`book report build` also takes `--presentation FILE.json` (a JSON object with
`title`, `producer_display_name`, `logo_data_url`) if you want your own page
title.

**Layout note.** Stock rc18 draws the older layout. The pages in `pages/`
use the newer two-level layout, which comes from capsule-viewer pull
requests that capsulectl does not ship yet:

- #41 `desk/two-level-reports`: two levels, plain words, on both cards
- #42 `desk/report-provenance-line`: who judged, who witnessed and what verified, on the front
- #48 `desk/contract-report-module`: one view, wording packs (#46)

#41 is merged to capsule-viewer `main`. #42 is open, based on `main`. #48 is
open, targets #42's branch, and is not yet rebased onto #42's current head. The pages here were built from the #42
head, `457a13e35b7f4f2bfbd201057d15deea0aad9896`, which is #41 plus #42.
#48 (wording packs, and capsule-viewer's own `scripts/render-report.mjs`) is
not in these pages. Each page names the build it was drawn with:
`capsule-viewer 0.1.0 at 457a13e35b7f`.

## rebuild with the new layout, before capsulectl ships it

Needs `git` and Node 20 or newer (checked with Node 24.18.1, npm 11.16.0).
Run from the `site-kit/` directory:

```bash
CV=457a13e35b7f4f2bfbd201057d15deea0aad9896   # capsule-viewer #42 head, on main with #41 merged
git clone -q https://github.com/action-state-group/capsule-viewer.git
git -C capsule-viewer fetch -q origin desk/report-provenance-line
git -C capsule-viewer checkout -q $CV
(cd capsule-viewer/ts && npm ci --no-audit --no-fund && npm run build)
mkdir -p rebuilt-new
for n in eu_2025-09-15_day eu_2025-09_week5 outcomes_2025-09-15_day outcomes_2025-09_week5; do
  node --max-old-space-size=4096 tools/render-page.mjs capsule-viewer/ts \
    bundles/$n.bundle.json rebuilt-new/$n.html
done
```

Each line prints the module it drew with (`aac.builtin.result-compliance/v0`
for the EU pages, `aac.builtin.result-outcome-report/v0` for the outcomes
pages) and `default words`. The render does not change the bundle, so no
digest or verdict moves. To check a rebuilt page, open it in a browser: the
page verifies its own bundle and shows the result.

Checked: run exactly as above on a clean Linux box, all four rebuilt pages
are byte-identical to the ones in `pages/` (same sha256 as in
`MANIFEST.txt`). Once #48 is rebased onto #42, capsule-viewer's own
`node scripts/render-report.mjs BUNDLE.json -o PAGE.html` does the same job
and also takes `--wording PACK.json`.

Once capsulectl ships a release with these capsule-viewer changes, the rc18
steps above give the new layout with that version number in place of rc18.

## read this before publishing: conversation text is inside the files

The pages do not show conversation transcripts on screen (checked in the
rendered page: no customer messages, user ids or addresses appear). The files
still carry the conversations, inside the embedded bundle, in two places:

- `disclosures`: the `agent_input` of 26 records (day pages) or 50 records
  (week pages) is disclosed, and it holds the conversation messages in plain
  JSON;
- the `evidencebook/payloads` extension holds the same conversations,
  base64-encoded.

Anyone who opens the page source or the bundle can read them. They are
tau2-bench airline simulations (simulated customers, simulated data), the
public benchmark runs, not real people. If the site must not carry them at
all, the bundles need to be disclosed again without those originals and the
pages rebuilt; that is a change on the producer side, not something this kit
can do.

## where the bundles came from

The four bundles are disclosed from the September 2025 evidence books (one
book per day or week, tau2 airline runs sealed with `capsulectl publish` and
`capsulectl book backfill run`, judged and sealed into a Result v0). Each was
disclosed with released rc18 `capsulectl disclose --closure-depth 2` from the
book's Result record, without `--attach-input-originals`, then the pack's
presentation block was added (the `eu-ai-act-compliance/v1` or
`outcome-report/v1` extension). The root record ids are in `MANIFEST.txt`.
