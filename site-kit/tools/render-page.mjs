// SPDX-License-Identifier: Apache-2.0
// Draw one report page from a bundle with a capsule-viewer build, default words.
// The same buildPresentation call capsule-viewer's own scripts/render-report.mjs
// makes (that script arrives with capsule-viewer #48). The bundle is not changed.
//   node render-page.mjs CAPSULE_VIEWER_TS_DIR BUNDLE.json OUT.html
import { readFileSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
const [ts, bundlePath, out] = process.argv.slice(2);
if (!ts || !bundlePath || !out) {
  console.error("usage: node render-page.mjs CAPSULE_VIEWER_TS_DIR BUNDLE.json OUT.html");
  process.exit(2);
}
const { buildPresentation } = await import(join(resolve(ts), "dist", "index.js"));
const bundle = JSON.parse(readFileSync(bundlePath, "utf8"));
const built = await buildPresentation(bundle, {
  presentation: "auto", audience: "*", format: "html",
  runtime: { code: readFileSync(join(ts, "dist", "evidence-graph.iife.js"), "utf8") },
});
writeFileSync(out, built.html);
console.log(`${out}: module ${built.module ?? "none"} (${built.resolution}), default words`);
