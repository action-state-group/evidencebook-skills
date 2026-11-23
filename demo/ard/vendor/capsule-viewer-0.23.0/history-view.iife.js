"use strict";
var HistoryView = (() => {
  var __defProp = Object.defineProperty;
  var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
  var __getOwnPropNames = Object.getOwnPropertyNames;
  var __hasOwnProp = Object.prototype.hasOwnProperty;
  var __export = (target, all) => {
    for (var name in all)
      __defProp(target, name, { get: all[name], enumerable: true });
  };
  var __copyProps = (to, from, except, desc) => {
    if (from && typeof from === "object" || typeof from === "function") {
      for (let key of __getOwnPropNames(from))
        if (!__hasOwnProp.call(to, key) && key !== except)
          __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
    }
    return to;
  };
  var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

  // src/history-view.ts
  var history_view_exports = {};
  __export(history_view_exports, {
    HISTORY_CHECK_IDS: () => HISTORY_CHECK_IDS,
    HISTORY_VIEW: () => HISTORY_VIEW,
    HISTORY_VIEW_WORDING: () => HISTORY_VIEW_WORDING,
    HistoryViewRefused: () => HistoryViewRefused,
    buildHistoryView: () => buildHistoryView,
    historyElementToDom: () => historyElementToDom,
    historyViewDocument: () => historyViewDocument,
    historyViewHtml: () => historyViewHtml,
    historyViewStyles: () => historyViewStyles,
    renderHistoryView: () => renderHistoryView,
    serializeHistoryElement: () => serializeHistoryElement
  });

  // src/wording/history-view.en.json
  var history_view_en_default = {
    wording_pack_version: "0",
    id: "capsuleviewer.history-view.wording/v0",
    locale: "en",
    provenance: {
      _comment: "Entries copied from actionstate-muse's packs name their source key; the snapshot test (test/history-view.test.ts) holds them to test/fixtures/history-view/muse-source.json. Once actionstate-muse deletes its history.page.* words, this pack is the source.",
      muse_commit: "79cc01cfbae59536e690fd6c8e68192b6cf7a12a",
      sources: {
        "header.title.owner": "plugin.json history.page.title",
        "badge.private": "plugin.json history.page.private",
        "hero.none.deals": "plugin.json history.page.none",
        "hero.deals.one": "plugin.json history.page.count.one",
        "hero.deals.other": "plugin.json history.page.count.other",
        "row.opened": "plugin.json history.page.row.opened",
        "row.last": "plugin.json history.page.row.last",
        "stamp.recorded": "plugin.json history.page.stamp.recorded",
        "stamp.timestamped": "plugin.json history.page.stamp.timestamped",
        "slot.timestamped.none": "plugin.json history.page.stamp.timestamped.not",
        "slot.part": "plugin.json history.page.stamp.timestamped.part",
        "slot.unchecked": "plugin.json history.page.stamp.timestamped.unchecked",
        "slot.failed": "plugin.json history.page.stamp.timestamped.failed",
        "seal.deals": "receipt.json seal.text.unpostmarked",
        "seal.directory": "plugin.json history.page.checked.directory"
      }
    },
    entries: {
      "header.title.node": "History \xB7 node {node}",
      "header.title.stream": "History \xB7 node {node} \xB7 {stream} log",
      "header.title.owner": "Your History",
      "header.title.shared": "History \xB7 shared by {name}",
      "header.title.person": "History \xB7 {name}",
      "badge.private": "PRIVATE \xB7 for you only. Never send this page.",
      "badge.shared": "SHARED COPY \xB7 for {who}",
      "badge.anyone": "What this node gives anyone who asks",
      "scope.period": "{from} to {to}",
      "built.owner": "As of {at}. It is a snapshot, not a page that updates itself.",
      "built.recipient": "As of {at}. It is a snapshot, not a page that updates itself.",
      "hero.checkpoints.one": "1 checkpoint \xB7 {entries} \xB7 last cut {at} \xB7 {verdict}",
      "hero.checkpoints.other": "{n} checkpoints \xB7 {entries} \xB7 last cut {at} \xB7 {verdict}",
      "hero.entries.one": "1 entry",
      "hero.entries.other": "{n} entries",
      "verdict.pass": "every checkpoint signature checks",
      "verdict.pass.all": "every signature checks, including the answer's own, by the node's published key",
      "verdict.unchecked": "signatures not checked here",
      "hero.failed": "This history didn't verify, so this page shows none of it.",
      "hero.none.checkpoints": "No checkpoints yet.",
      "hero.refused": "The node declined to answer.",
      "hero.refused.reason": "Its reason, in its own words: \u201C{reason}\u201D",
      "hero.unreadable": "This page could not read the answer, so it shows none of it.",
      "hero.deals.one": "{n} deal, newest first",
      "hero.deals.other": "{n} deals, newest first",
      "hero.deals.picked.one": "1 deal {name} picked \xB7 steps recorded, not outcomes",
      "hero.deals.picked.other": "{n} deals {name} picked \xB7 steps recorded, not outcomes",
      "hero.none.deals": "There are no deals in this store yet.",
      "chip.signatures.pass": "Checkpoint signatures check",
      "chip.signatures.pass.all": "Every signature checks",
      "chip.signatures.unchecked": "Signatures not checked here",
      "chip.timestamped.all": "Time-stamped: all {n}",
      "chip.timestamped.some": "Time-stamped: {k} of {n}",
      "chip.timestamped.none": "Time-stamped: none yet",
      "chip.timestamped.unchecked": "Time stamps not checked here",
      "chip.timestamped.failed": "Time stamps didn't verify",
      "chip.started": "Started {date}",
      "chip.recorded": "Each step recorded as it happened",
      "rows.heading.checkpoints": "Checkpoints",
      "rows.heading.deals": "Deals",
      "row.cut": "Cut {at}",
      "row.entries.one": "1 entry in the log",
      "row.entries.other": "{n} entries in the log",
      "row.opened": "Opened {at}",
      "row.last": "Last step {at}",
      "proof.checkpoint": "\u{1F50F} checkpoint {id}\u2026",
      "proof.node": "\u{1F50F} node key {id}\u2026",
      "proof.record": "\u{1F50F} record {id}\u2026",
      "stamp.recorded": "RECORDED",
      "stamp.timestamped": "TIME-STAMPED",
      "stamp.second": "SECOND SIGNATURE",
      "stamp.signature.unchecked": "Signature not checked here",
      "slot.timestamped.at": "{at}",
      "slot.timestamped.by": "{at} \xB7 by {by}",
      "slot.part": "through step {k} of {n}",
      "slot.timestamped.none": "Not time-stamped yet",
      "slot.second.by": "{by} signed this record too \xB7 {at}, by their clock",
      "slot.second.none": "None yet",
      "slot.unchecked": "Not checked here",
      "slot.failed": "Didn't verify",
      "periods.heading": "Service History: exchanges served in each closed week",
      "periods.row": "{from} to {to}",
      "periods.cell": "{what}: {value}",
      "periods.cell.withheld": "{what}: fewer than 5",
      "callout.heading": "What this does not show",
      "callout.checkpoints": "These checkpoints show when this node's log was cut and how much it holds. They don't show what any exchange said or how it went, and this is not a judgment of the node.",
      "callout.checkpoints.time": "The exact time of each exchange. Checkpoint times are rounded to the minute, and each side of an exchange gets its own checkpoint, so two can share a time.",
      "callout.deals": "\u201CSteps recorded\u201D is this side's record of each deal, not a confirmed outcome.",
      "callout.deals.picked": "{name} picked these; it isn't every deal. \u201CSteps recorded\u201D is {name}'s side's record, not a confirmed outcome.",
      "shares.heading": "What this node shares",
      "shares.summary": "With anyone who asks: a summary of its checkpoints, meaning how much it has recorded and when, and nothing about any exchange.",
      "shares.standard.on": "With anyone: the Service History.",
      "shares.standard.off": "The Service History: only the other side of an exchange gets it (off for anyone else on this node).",
      "shares.segments.counterparties": "Only with the other side of an exchange, when they ask: that exchange's record.",
      "shares.segments.peers": "With any node that signs its request: an exchange's record.",
      "shares.segments.off": "The other side of an exchange can't ask for its record (off on this node).",
      "shares.segments.off.sealed": "They still get the sealed record when it completes.",
      "shares.corroboration.on": "With any node that asks by an exchange's id: whether this node holds its half (ids and digests only).",
      "shares.completion.on": "Sent on its own: the sealed record when an exchange completes.",
      "shares.completion.off": "The sealed record isn't sent when an exchange completes (off on this node).",
      "shares.adjudications.on": "If this node judges an exchange, its verdict goes to the node judged.",
      "shares.adjudications.off": "Verdicts this node reaches aren't sent to the nodes judged (off on this node).",
      "shares.dealhalf.counterparty": "Only with the other side of an exchange: that exchange's half of the record.",
      "shares.stranger": "With anyone who asks, even a stranger: {items}.",
      "shares.stranger.none": "Nothing else goes to a stranger.",
      "shares.stranger.token.history_card/1": "the History Card",
      "shares.twins.on": "When two copies of a model answer differently, this node sends the question and both answers to a referee.",
      "shares.unstated": "This node's settings don't say: {items}.",
      "shares.unstated.one": "This node's settings don't say {item}.",
      "shares.unstated.standard": "whether its Service History goes to anyone",
      "shares.unstated.segments": "whether the other side of an exchange can ask for that exchange's record",
      "shares.unstated.corroboration": "whether it tells a node that asks by exchange id if it holds that exchange's half",
      "shares.unstated.completion": "whether it sends the sealed record when an exchange completes",
      "shares.unstated.adjudications": "whether its verdicts go to the nodes judged",
      "shares.unstated.twins": "whether it sends differing answers to a referee",
      "shares.unstated.witnesses": "which witnesses get its checkpoints",
      "shares.unstated.never": "whether a record goes to someone who doesn't prove who they are",
      "shares.witnesses": "Signed checkpoints go to the witnesses named here: {witnesses}",
      "shares.witnesses.none": "No witnesses named in this node's settings now. A row's time-stamp may come from an earlier setting.",
      "shares.never": "Never: a record to anyone who doesn't prove who they are.",
      "shares.as_of": "Set by this node as of {at}.",
      "seal.title": "Locked as it happened.",
      "seal.checkpoints": "Each checkpoint is signed and extends the one before, so a change to what it covers shows.",
      "seal.deals": "Each step was saved as it happened. Any change to a saved step shows.",
      "seal.second.label": "Second signature",
      "seal.second.rows": "See each row",
      "seal.second.some_failed": "{k} of {n} didn't verify; see each row",
      "seal.directory": "Signers are looked up at {directory} on every read, so that site can see each time you look.",
      "checked.heading": "How this was checked",
      "checked.where.page": "These checks ran in this browser when the page opened ({by}).",
      "checked.where.builder": "These checks cover the records as of {at} ({by}).",
      "check.line": "{status}: {name}",
      "status.pass": "Checked",
      "status.fail": "Didn't verify",
      "status.not_run": "Not checked here",
      "check.readable": "The answer can be read",
      "check.refusal": "The refusal is signed by the key that answered",
      "check.artifact_digest": "The answer's file is the bytes its digest names",
      "check.card_digest": "The history card (history_card/1) matches its digest",
      "check.checkpoint_signatures": "Every checkpoint is signed by the key that answered",
      "check.checkpoint_chain": "Each checkpoint names the one before",
      "check.consistency": "The log only grew between checkpoints: nothing removed or changed",
      "check.anchor": "The last checkpoint is the one the answer names",
      "check.period_counts": "The Service History's counts (service_history/1) match its checkpoints",
      "check.envelope_signature": "The answer itself is signed by the key that answered",
      "check.key_is_node": "The signing key is the node's published key",
      "check.reply_bound": "The answer is bound to the request it answers",
      "check.witness": "A witness time-stamped these records",
      "check.second_signature": "A second party signed this record",
      "check.deal_report": "Each deal was read with its own report, which writes nothing",
      refused: "This page can't show this history: {reasons}"
    }
  };

  // src/history-view.ts
  var HISTORY_VIEW = "history-view/v0";
  var HISTORY_CHECK_IDS = [
    "readable",
    "refusal",
    "artifact_digest",
    "card_digest",
    "checkpoint_signatures",
    "checkpoint_chain",
    "consistency",
    "anchor",
    "period_counts",
    "envelope_signature",
    "key_is_node",
    "reply_bound",
    "witness",
    "second_signature",
    "deal_report"
  ];
  var SLOT_CHECKS = /* @__PURE__ */ new Set([
    "witness",
    "second_signature"
  ]);
  var BASE = history_view_en_default.entries;
  var HISTORY_VIEW_WORDING = history_view_en_default;
  var HistoryViewRefused = class extends Error {
    reasons;
    constructor(reasons) {
      super(`history-view refused: ${reasons.join("; ")}`);
      this.name = "HistoryViewRefused";
      this.reasons = reasons;
    }
  };
  var TOKEN = /^[a-z0-9 _.-]*$/u;
  function el(tag, attrs, ...children) {
    const pairs = Object.entries(attrs ?? {});
    for (const [name, value] of pairs)
      if (!TOKEN.test(name) || !TOKEN.test(value))
        throw new Error(
          `history-view: attribute ${name}=${value} is not a view token`
        );
    return {
      tag,
      attrs: pairs,
      children: children.filter(
        (c) => c !== null && c !== false
      )
    };
  }
  function escapeText(text) {
    return text.replace(
      /[&<> ]/gu,
      (c) => c === "&" ? "&amp;" : c === "<" ? "&lt;" : c === ">" ? "&gt;" : "&nbsp;"
    );
  }
  function serializeHistoryElement(node) {
    if (typeof node === "string") return escapeText(node);
    const attrs = node.attrs.map(([n, v]) => ` ${n}="${v}"`).join("");
    return `<${node.tag}${attrs}>${node.children.map(serializeHistoryElement).join("")}</${node.tag}>`;
  }
  function historyElementToDom(node, doc) {
    if (typeof node === "string") return doc.createTextNode(node);
    const out = doc.createElement(node.tag);
    for (const [n, v] of node.attrs) out.setAttribute(n, v);
    for (const child of node.children)
      out.appendChild(historyElementToDom(child, doc));
    return out;
  }
  var Reader = class {
    reasons = [];
    refuse(path, why) {
      this.reasons.push(`${path}: ${why}`);
    }
    object(v, path, allowed, required) {
      if (typeof v !== "object" || v === null || Array.isArray(v)) {
        this.refuse(path, "is not an object");
        return null;
      }
      const o = v;
      for (const k of Object.keys(o))
        if (!allowed.includes(k))
          this.refuse(`${path}.${k}`, "is not a member of history-view/v0");
      for (const k of required)
        if (!(k in o)) this.refuse(`${path}.${k}`, "is missing");
      return o;
    }
    string(v, path, max = 2e3) {
      if (typeof v !== "string" || v.length === 0 || v.length > max) {
        this.refuse(path, `is not a string of 1 to ${max} characters`);
        return void 0;
      }
      return v;
    }
    oneOf(v, path, values) {
      if (typeof v !== "string" || !values.includes(v)) {
        this.refuse(path, `is not one of ${values.join(", ")}`);
        return void 0;
      }
      return v;
    }
    bool(v, path) {
      if (typeof v !== "boolean") {
        this.refuse(path, "is not true or false");
        return void 0;
      }
      return v;
    }
    count(v, path) {
      if (typeof v !== "number" || !Number.isSafeInteger(v) || v < 0) {
        this.refuse(path, "is not a whole number of 0 or more");
        return void 0;
      }
      return v;
    }
    time(v, path) {
      const s = this.string(v, path, 64);
      if (s === void 0) return void 0;
      const t = parseInstant(s);
      if (t === void 0) this.refuse(path, "is not an RFC 3339 time");
      return t;
    }
    date(v, path) {
      const s = this.string(v, path, 64);
      if (s === void 0) return void 0;
      const t = /^\d{4}-\d{2}-\d{2}$/u.test(s) ? parseInstant(`${s}T00:00:00Z`) : parseInstant(s);
      if (t === void 0)
        this.refuse(path, "is not a date (YYYY-MM-DD) or an RFC 3339 time");
      return t;
    }
  };
  function parseInstant(s) {
    const m = /^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?([Zz]|[+-]\d{2}:\d{2})$/u.exec(
      s
    );
    if (!m) return void 0;
    const [, y, mo, d, h, mi, se, , zone = "Z"] = m;
    const month = Number(mo);
    const day = Number(d);
    if (month < 1 || month > 12 || day < 1 || day > 31 || Number(h) > 23 || Number(mi) > 59 || Number(se) > 59)
      return void 0;
    let ms = Date.UTC(
      Number(y),
      month - 1,
      day,
      Number(h),
      Number(mi),
      Number(se)
    );
    if (new Date(ms).getUTCDate() !== day) return void 0;
    if (zone !== "Z" && zone !== "z") {
      const sign = zone.startsWith("-") ? -1 : 1;
      ms -= sign * (Number(zone.slice(1, 3)) * 60 + Number(zone.slice(4, 6))) * 6e4;
    }
    return { ms };
  }
  var MONTHS = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec"
  ];
  var two = (n) => String(n).padStart(2, "0");
  function dateOf(t) {
    const d = new Date(t.ms);
    return `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}, ${d.getUTCFullYear()}`;
  }
  function minuteOf(t) {
    const d = new Date(t.ms);
    return `${dateOf(t)}, ${two(d.getUTCHours())}:${two(d.getUTCMinutes())} UTC`;
  }
  function shortMinuteOf(t) {
    const d = new Date(t.ms);
    return `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}, ${two(d.getUTCHours())}:${two(d.getUTCMinutes())} UTC`;
  }
  var PLACEHOLDER = /\{([a-z_]+)\}/gu;
  function placeholders(text) {
    return [...text.matchAll(PLACEHOLDER)].map((m) => m[1] ?? "").sort();
  }
  function readOverlay(r, v) {
    const o = r.object(v, "overlay", ["id", "entries"], ["id", "entries"]);
    if (!o) return {};
    r.string(o["id"], "overlay.id", 200);
    const e = r.object(o["entries"], "overlay.entries", Object.keys(BASE), []);
    const out = {};
    if (!e) return out;
    for (const [k, text] of Object.entries(e)) {
      const base = Object.hasOwn(BASE, k) ? BASE[k] : void 0;
      const s = r.string(text, `overlay.entries.${k}`);
      if (base === void 0 || s === void 0) continue;
      if (placeholders(base).join(",") !== placeholders(s).join(","))
        r.refuse(
          `overlay.entries.${k}`,
          `must use the placeholders ${JSON.stringify(placeholders(base))}`
        );
      else out[k] = s;
    }
    return out;
  }
  function readSlot(r, v, path, needBy) {
    const o = r.object(v, path, ["state", "by", "at", "through"], ["state"]);
    const state = o ? r.oneOf(o["state"], `${path}.state`, [
      "passed",
      "failed",
      "none",
      "not_checked"
    ]) ?? "not_checked" : "not_checked";
    const by = o && "by" in o ? r.string(o["by"], `${path}.by`, 200) : void 0;
    const at = o && "at" in o ? r.time(o["at"], `${path}.at`) : void 0;
    let through;
    if (o && "through" in o) {
      const t = r.object(o["through"], `${path}.through`, ["k", "n"], ["k", "n"]);
      const k = t ? r.count(t["k"], `${path}.through.k`) : void 0;
      const n = t ? r.count(t["n"], `${path}.through.n`) : void 0;
      if (k !== void 0 && n !== void 0) {
        if (k > n || n === 0)
          r.refuse(`${path}.through`, "k must be at most n, and n more than 0");
        else through = { k, n };
      }
    }
    if (state === "passed") {
      if (!o || !("at" in o)) r.refuse(path, "a passed slot needs at");
      if (needBy && !(o && "by" in o))
        r.refuse(path, "a passed second-signature slot needs by");
    }
    return { state, by, at, through };
  }
  var EPOCH = { ms: 0 };
  function readRow(r, v, path, kind) {
    if (kind === "checkpoint") {
      const o2 = r.object(
        v,
        path,
        [
          "kind",
          "cut_at",
          "log_size",
          "anchor",
          "signature",
          "witness",
          "second_signature"
        ],
        [
          "kind",
          "cut_at",
          "log_size",
          "anchor",
          "signature",
          "witness",
          "second_signature"
        ]
      );
      if (!o2) return void 0;
      if (o2["kind"] !== "checkpoint")
        r.refuse(`${path}.kind`, "must be the page's kind, checkpoint");
      return {
        kind,
        cut: r.time(o2["cut_at"], `${path}.cut_at`) ?? EPOCH,
        logSize: r.count(o2["log_size"], `${path}.log_size`) ?? 0,
        anchor: r.string(o2["anchor"], `${path}.anchor`, 200) ?? "",
        signature: r.oneOf(o2["signature"], `${path}.signature`, [
          "pass",
          "fail",
          "not_run"
        ]) ?? "not_run",
        witness: readSlot(r, o2["witness"], `${path}.witness`, false),
        second: readSlot(
          r,
          o2["second_signature"],
          `${path}.second_signature`,
          true
        )
      };
    }
    const o = r.object(
      v,
      path,
      [
        "kind",
        "asked",
        "outcome",
        "money",
        "opened_at",
        "last_at",
        "record",
        "witness",
        "second_signature"
      ],
      [
        "kind",
        "asked",
        "outcome",
        "opened_at",
        "last_at",
        "record",
        "witness",
        "second_signature"
      ]
    );
    if (!o) return void 0;
    if (o["kind"] !== "deal")
      r.refuse(`${path}.kind`, "must be the page's kind, deal");
    return {
      kind,
      asked: r.string(o["asked"], `${path}.asked`) ?? "",
      outcome: r.string(o["outcome"], `${path}.outcome`, 200) ?? "",
      money: "money" in o ? r.string(o["money"], `${path}.money`, 200) : void 0,
      opened: r.time(o["opened_at"], `${path}.opened_at`) ?? EPOCH,
      last: r.time(o["last_at"], `${path}.last_at`) ?? EPOCH,
      record: r.string(o["record"], `${path}.record`, 200) ?? "",
      witness: readSlot(r, o["witness"], `${path}.witness`, false),
      second: readSlot(
        r,
        o["second_signature"],
        `${path}.second_signature`,
        true
      )
    };
  }
  var TOP = [
    "view",
    "kind",
    "surface",
    "reader",
    "holder",
    "audience",
    "built_at",
    "checked",
    "outcome",
    "picked",
    "rows",
    "checks",
    "periods",
    "sharing",
    "signer_directory",
    "period"
  ];
  function buildHistoryView(input, overlay) {
    const r = new Reader();
    const o = r.object(input, "input", TOP, [
      "view",
      "kind",
      "surface",
      "reader",
      "holder",
      "audience",
      "built_at",
      "checked",
      "rows",
      "checks"
    ]);
    if (!o) return { ok: false, reasons: r.reasons };
    if (o["view"] !== HISTORY_VIEW)
      r.refuse("input.view", `is not ${HISTORY_VIEW}`);
    const kind = r.oneOf(o["kind"], "input.kind", ["checkpoint", "deal"]) ?? "checkpoint";
    const surface = r.oneOf(o["surface"], "input.surface", ["neutral", "product"]) ?? "neutral";
    const reader = r.oneOf(o["reader"], "input.reader", ["owner", "recipient"]) ?? "recipient";
    let words = {};
    if (overlay !== void 0) {
      if (surface !== "product")
        r.refuse("overlay", "a neutral page takes no overlay");
      else words = readOverlay(r, overlay);
    }
    const ho = r.object(
      o["holder"],
      "input.holder",
      ["node", "name", "stream"],
      []
    );
    const node = ho && "node" in ho ? r.string(ho["node"], "input.holder.node", 200) : void 0;
    const name = ho && "name" in ho ? r.string(ho["name"], "input.holder.name", 200) : void 0;
    const stream = ho && "stream" in ho ? r.string(ho["stream"], "input.holder.stream", 200) : void 0;
    if (kind === "checkpoint" && node === void 0 && ho)
      r.refuse(
        "input.holder.node",
        "is missing (a checkpoint page names its node)"
      );
    const au = r.object(
      o["audience"],
      "input.audience",
      ["kind", "for"],
      ["kind"]
    );
    const audienceKind = au ? r.oneOf(au["kind"], "input.audience.kind", [
      "private",
      "shared",
      "anyone"
    ]) ?? "anyone" : "anyone";
    const audienceFor = audienceKind === "shared" && au ? r.string(au["for"], "input.audience.for", 200) : void 0;
    if (audienceKind !== "shared" && au && "for" in au)
      r.refuse("input.audience.for", "is only for a shared audience");
    const built = r.time(o["built_at"], "input.built_at") ?? EPOCH;
    const ck = r.object(
      o["checked"],
      "input.checked",
      ["where", "by"],
      ["where", "by"]
    );
    const where = ck ? r.oneOf(ck["where"], "input.checked.where", [
      "page",
      "builder"
    ]) ?? "builder" : "builder";
    const checkedBy = ck ? r.string(ck["by"], "input.checked.by", 200) ?? "" : "";
    let outcome = "answered";
    let refusedReason;
    if ("outcome" in o) {
      if (kind !== "checkpoint")
        r.refuse("input.outcome", "is only for a checkpoint page");
      const oc = r.object(
        o["outcome"],
        "input.outcome",
        ["kind", "reason"],
        ["kind"]
      );
      if (oc) {
        outcome = r.oneOf(oc["kind"], "input.outcome.kind", [
          "answered",
          "refused",
          "unreadable"
        ]) ?? "answered";
        if (outcome === "refused")
          refusedReason = r.string(oc["reason"], "input.outcome.reason", 200);
        else if ("reason" in oc)
          r.refuse("input.outcome.reason", "is only for a refused answer");
      }
    }
    const picked = "picked" in o ? r.bool(o["picked"], "input.picked") === true : false;
    if (picked && kind !== "deal")
      r.refuse("input.picked", "is only for a deal page");
    if (kind === "deal" && reader === "recipient" && name === void 0)
      r.refuse(
        "input.holder.name",
        "is missing (a deal page shown to someone else names whose it is)"
      );
    else if (picked && name === void 0)
      r.refuse(
        "input.holder.name",
        "is missing (a picked selection names who picked it)"
      );
    const rows = [];
    if (Array.isArray(o["rows"])) {
      if (o["rows"].length > 1e4)
        r.refuse("input.rows", "has more than 10000 rows");
      o["rows"].forEach((row, i) => {
        const read = readRow(r, row, `input.rows[${i}]`, kind);
        if (read) rows.push(read);
      });
      if (outcome !== "answered" && o["rows"].length > 0)
        r.refuse("input.rows", "must be empty unless the node answered");
    } else r.refuse("input.rows", "is not a list");
    const checks = [];
    if (Array.isArray(o["checks"])) {
      o["checks"].forEach((c, i) => {
        const path = `input.checks[${i}]`;
        const co = r.object(
          c,
          path,
          ["id", "status", "values"],
          ["id", "status"]
        );
        if (!co) return;
        const id = r.oneOf(co["id"], `${path}.id`, HISTORY_CHECK_IDS);
        const status = r.oneOf(co["status"], `${path}.status`, [
          "pass",
          "fail",
          "not_run"
        ]);
        if ("values" in co) {
          const vo = r.object(co["values"], `${path}.values`, [], []);
          if (vo && Object.keys(vo).length > 0)
            r.refuse(
              `${path}.values`,
              "names a placeholder the check's words do not have"
            );
        }
        if (id && checks.some((x) => x.id === id))
          r.refuse(`${path}.id`, "is listed twice");
        if (id && status) checks.push({ id, status });
      });
    } else r.refuse("input.checks", "is not a list");
    const periods = [];
    if ("periods" in o) {
      if (kind !== "checkpoint")
        r.refuse("input.periods", "is only for a checkpoint page");
      if (Array.isArray(o["periods"]))
        o["periods"].forEach((p, i) => {
          const path = `input.periods[${i}]`;
          const po = r.object(
            p,
            path,
            ["from", "to", "cells"],
            ["from", "to", "cells"]
          );
          if (!po) return;
          const from = r.date(po["from"], `${path}.from`);
          const to = r.date(po["to"], `${path}.to`);
          const cells = [];
          if (Array.isArray(po["cells"]))
            po["cells"].forEach((c, j) => {
              const co = r.object(
                c,
                `${path}.cells[${j}]`,
                ["what", "value", "withheld"],
                ["what"]
              );
              const what = co ? r.string(co["what"], `${path}.cells[${j}].what`, 200) : void 0;
              const withheld = co !== null && "withheld" in co;
              if (withheld && co["withheld"] !== true)
                r.refuse(`${path}.cells[${j}].withheld`, "is not true");
              if (co && withheld === "value" in co)
                r.refuse(
                  `${path}.cells[${j}]`,
                  "carries either a value or withheld: true"
                );
              const value = co && "value" in co ? r.string(co["value"], `${path}.cells[${j}].value`, 40) : void 0;
              if (what !== void 0) cells.push({ what, value });
            });
          else r.refuse(`${path}.cells`, "is not a list");
          if (from && to) periods.push({ from, to, cells });
        });
      else r.refuse("input.periods", "is not a list");
    }
    let sharing;
    if (kind === "checkpoint" && !("sharing" in o))
      r.refuse(
        "input.sharing",
        "is missing (a checkpoint page says what its node shares)"
      );
    if ("sharing" in o) {
      if (kind !== "checkpoint")
        r.refuse("input.sharing", "is only for a checkpoint page");
      const keys = [
        "standard_history",
        "history_segments",
        "record_at_completion",
        "adjudications",
        "exchange_corroboration",
        "adjudicate_differing_twins",
        "witnesses",
        "share_deal_half",
        "stranger_safe"
      ];
      const so = r.object(o["sharing"], "input.sharing", keys, []);
      if (so) {
        let witnesses;
        if ("witnesses" in so) {
          witnesses = [];
          if (Array.isArray(so["witnesses"]))
            for (const [i, w] of so["witnesses"].entries()) {
              const s = r.string(w, `input.sharing.witnesses[${i}]`, 300);
              if (s !== void 0) witnesses.push(s);
            }
          else r.refuse("input.sharing.witnesses", "is not a list");
        }
        let strangerSafe;
        if ("stranger_safe" in so) {
          strangerSafe = [];
          if (Array.isArray(so["stranger_safe"]))
            for (const [i, w] of so["stranger_safe"].entries()) {
              const t = r.string(w, `input.sharing.stranger_safe[${i}]`, 80);
              if (t !== void 0) strangerSafe.push(t);
            }
          else r.refuse("input.sharing.stranger_safe", "is not a list");
        }
        const stated = {};
        let wrong = false;
        const take = (k, parse) => {
          if (!(k in so)) return;
          const v = parse();
          if (v === void 0) wrong = true;
          else stated[k] = v;
        };
        const on = (k) => take(k, () => r.bool(so[k], `input.sharing.${k}`));
        const one = (k, values) => take(k, () => r.oneOf(so[k], `input.sharing.${k}`, values));
        on("standard_history");
        one("history_segments", ["off", "counterparties", "peers"]);
        one("record_at_completion", ["counterparty", "off"]);
        one("adjudications", ["deliver_to_subjects", "off"]);
        on("exchange_corroboration");
        on("adjudicate_differing_twins");
        one("share_deal_half", ["counterparty"]);
        if (!wrong)
          sharing = {
            ...stated,
            ...witnesses !== void 0 ? { witnesses } : {},
            ...strangerSafe !== void 0 ? { stranger_safe: strangerSafe } : {}
          };
      }
    }
    let directory;
    if ("signer_directory" in o) {
      if (kind !== "deal")
        r.refuse("input.signer_directory", "is only for a deal page");
      directory = r.string(o["signer_directory"], "input.signer_directory", 300);
      if (directory !== void 0 && !directory.startsWith("https://"))
        r.refuse("input.signer_directory", "is not an https:// address");
    }
    let period;
    if ("period" in o) {
      const po = r.object(
        o["period"],
        "input.period",
        ["from", "to"],
        ["from", "to"]
      );
      const from = po ? r.date(po["from"], "input.period.from") : void 0;
      const to = po ? r.date(po["to"], "input.period.to") : void 0;
      if (from && to) period = { from, to };
    }
    if (r.reasons.length > 0) return { ok: false, reasons: r.reasons };
    const say = (key, values = {}) => {
      const text = words[key] ?? BASE[key];
      if (text === void 0)
        throw new Error(`history-view: no words for ${key}`);
      return text.replace(PLACEHOLDER, (_, p) => {
        const v = values[p];
        if (v === void 0) throw new Error(`history-view: ${key} needs {${p}}`);
        return v;
      });
    };
    const plural = (key, n, values = {}) => say(`${key}.${n === 1 ? "one" : "other"}`, { n: String(n), ...values });
    const short = (id) => id.length > 12 ? id.slice(0, 12) : id;
    const failedCheck = checks.some(
      (c) => c.status === "fail" && !SLOT_CHECKS.has(c.id)
    );
    const failedRow = rows.some(
      (x) => x.kind === "checkpoint" && x.signature === "fail"
    );
    const failed = failedCheck || failedRow;
    const allPass = rows.length > 0 && rows.every((x) => x.kind !== "checkpoint" || x.signature === "pass") && checks.filter((c) => !SLOT_CHECKS.has(c.id) && c.status !== "not_run").every((c) => c.status === "pass") && (kind === "deal" || checks.some(
      (c) => c.id === "checkpoint_signatures" && c.status === "pass"
    ));
    const passed = (id) => checks.some((c) => c.id === id && c.status === "pass");
    const everySignature = allPass && passed("envelope_signature") && passed("key_is_node");
    const verdictKey = everySignature ? "verdict.pass.all" : "verdict.pass";
    const chipKey = everySignature ? "chip.signatures.pass.all" : "chip.signatures.pass";
    const statusOf = (id) => checks.find((c) => c.id === id)?.status;
    const dealRecorded = statusOf("deal_report") === "pass";
    const witnessFailed = statusOf("witness") === "fail";
    const secondFailed = statusOf("second_signature") === "fail";
    const lockChecked = kind === "checkpoint" ? statusOf("checkpoint_signatures") === "pass" && statusOf("checkpoint_chain") === "pass" && statusOf("consistency") === "pass" : dealRecorded;
    let title;
    if (kind === "checkpoint")
      title = stream !== void 0 ? say("header.title.stream", { node: short(node ?? ""), stream }) : say("header.title.node", { node: short(node ?? "") });
    else if (reader === "owner") title = say("header.title.owner");
    else
      title = audienceKind === "shared" ? say("header.title.shared", { name: name ?? "" }) : say("header.title.person", { name: name ?? "" });
    const badge = audienceKind === "private" ? say("badge.private") : audienceKind === "shared" ? say("badge.shared", { who: audienceFor ?? "" }) : say("badge.anyone");
    const header = el(
      "header",
      { class: "cvh-header", "data-history": "header" },
      el("h1", { class: "cvh-title" }, title),
      node !== void 0 ? el(
        "details",
        { class: "cvh-proof" },
        el("summary", null, say("proof.node", { id: short(node) })),
        el("code", null, node)
      ) : null,
      period ? el(
        "p",
        { class: "cvh-scope" },
        say("scope.period", {
          from: dateOf(period.from),
          to: dateOf(period.to)
        })
      ) : null,
      el("p", { class: "cvh-badge", "data-audience": audienceKind }, badge),
      el(
        "p",
        { class: "cvh-built" },
        say(reader === "owner" ? "built.owner" : "built.recipient", {
          at: minuteOf(built)
        })
      )
    );
    const heroLines = [];
    let drawRows = false;
    if (outcome === "refused") {
      heroLines.push(say("hero.refused"));
      if (refusedReason !== void 0)
        heroLines.push(say("hero.refused.reason", { reason: refusedReason }));
    } else if (outcome === "unreadable") heroLines.push(say("hero.unreadable"));
    else if (failed) heroLines.push(say("hero.failed"));
    else if (rows.length === 0)
      heroLines.push(
        say(kind === "checkpoint" ? "hero.none.checkpoints" : "hero.none.deals")
      );
    else {
      drawRows = true;
      if (kind === "checkpoint") {
        const cps = rows;
        const last = cps.reduce((a, b) => b.cut.ms > a.cut.ms ? b : a);
        const entries = Math.max(...cps.map((c) => c.logSize));
        heroLines.push(
          plural("hero.checkpoints", cps.length, {
            entries: plural("hero.entries", entries),
            at: shortMinuteOf(last.cut),
            verdict: say(allPass ? verdictKey : "verdict.unchecked")
          })
        );
      } else
        heroLines.push(
          picked ? plural("hero.deals.picked", rows.length, { name: name ?? "" }) : plural("hero.deals", rows.length)
        );
    }
    const hero = el(
      "section",
      { class: "cvh-hero", "data-history": "hero" },
      ...heroLines.map(
        (line, i) => el("p", { class: i === 0 ? "cvh-hero-line" : "cvh-hero-note" }, line)
      )
    );
    let chips = null;
    if (drawRows) {
      const stamped = rows.filter((x) => x.witness.state === "passed").length;
      const stampChip = witnessFailed ? say("chip.timestamped.failed") : stamped === 0 && rows.some((x) => x.witness.state === "not_checked") ? say("chip.timestamped.unchecked") : stamped === 0 ? say("chip.timestamped.none") : stamped === rows.length ? say("chip.timestamped.all", { n: String(rows.length) }) : say("chip.timestamped.some", {
        k: String(stamped),
        n: String(rows.length)
      });
      const items = [];
      if (kind === "checkpoint") {
        items.push(
          say(allPass ? chipKey : "chip.signatures.unchecked"),
          stampChip
        );
        const first = rows.reduce(
          (a, b) => b.cut.ms < a.cut.ms ? b : a
        );
        items.push(say("chip.started", { date: dateOf(first.cut) }));
      } else {
        if (dealRecorded) items.push(say("chip.recorded"));
        items.push(stampChip);
      }
      chips = el(
        "ul",
        { class: "cvh-chips", "data-history": "chips" },
        ...items.map((t) => el("li", { class: "cvh-chip" }, t))
      );
    }
    const slotLine = (s, second) => {
      if (s.state === "passed") {
        const at = s.at ? minuteOf(s.at) : "";
        let line = second ? say("slot.second.by", { by: s.by ?? "", at }) : s.by !== void 0 ? say("slot.timestamped.by", { at, by: s.by }) : say("slot.timestamped.at", { at });
        if (s.through && s.through.k < s.through.n)
          line += ` \xB7 ${say("slot.part", { k: String(s.through.k), n: String(s.through.n) })}`;
        return line;
      }
      if (s.state === "failed") return say("slot.failed");
      if (s.state === "none")
        return say(second ? "slot.second.none" : "slot.timestamped.none");
      return say("slot.unchecked");
    };
    const stamp = (nameKey, filled, state, line) => el(
      "li",
      {
        class: "cvh-stamp",
        "data-filled": filled ? "yes" : "no",
        "data-state": state
      },
      el("span", { class: "cvh-stamp-name" }, say(nameKey)),
      line !== null ? el("span", { class: "cvh-stamp-line" }, line) : null
    );
    const slotStamps = (row) => [
      stamp(
        "stamp.timestamped",
        row.witness.state === "passed",
        row.witness.state,
        slotLine(row.witness, false)
      ),
      stamp(
        "stamp.second",
        row.second.state === "passed",
        row.second.state,
        slotLine(row.second, true)
      )
    ];
    const proof = (key, id) => el(
      "details",
      { class: "cvh-proof" },
      el("summary", null, say(key, { id: short(id) })),
      el("code", null, id)
    );
    let rowList = null;
    if (drawRows) {
      const items = rows.map((x) => {
        if (x.kind === "checkpoint") {
          return el(
            "li",
            { class: "cvh-row", "data-history": "row" },
            el(
              "p",
              { class: "cvh-row-title" },
              say("row.cut", { at: minuteOf(x.cut) })
            ),
            el(
              "p",
              { class: "cvh-row-detail" },
              plural("row.entries", x.logSize)
            ),
            proof("proof.checkpoint", x.anchor),
            el(
              "ul",
              { class: "cvh-stamps" },
              stamp(
                "stamp.recorded",
                x.signature === "pass",
                x.signature,
                x.signature === "pass" ? null : say("stamp.signature.unchecked")
              ),
              ...slotStamps(x)
            )
          );
        }
        const detail = [
          x.outcome,
          ...x.money !== void 0 ? [x.money] : [],
          say("row.opened", { at: minuteOf(x.opened) }),
          say("row.last", { at: minuteOf(x.last) })
        ].join(" \xB7 ");
        return el(
          "li",
          { class: "cvh-row", "data-history": "row" },
          el("p", { class: "cvh-row-title" }, x.asked),
          el("p", { class: "cvh-row-detail" }, detail),
          proof("proof.record", x.record),
          el(
            "ul",
            { class: "cvh-stamps" },
            dealRecorded ? stamp("stamp.recorded", true, "passed", null) : stamp(
              "stamp.recorded",
              false,
              "not_checked",
              say("slot.unchecked")
            ),
            ...slotStamps(x)
          )
        );
      });
      rowList = el(
        "section",
        { class: "cvh-rows-block" },
        el(
          "h2",
          null,
          say(
            kind === "checkpoint" ? "rows.heading.checkpoints" : "rows.heading.deals"
          )
        ),
        el("ol", { class: "cvh-rows", "data-history": "rows" }, ...items)
      );
    }
    const periodBlock = drawRows && periods.length > 0 ? el(
      "section",
      { class: "cvh-periods", "data-history": "periods" },
      el("h2", null, say("periods.heading")),
      el(
        "ul",
        null,
        ...periods.map(
          (p) => el(
            "li",
            null,
            el(
              "p",
              null,
              say("periods.row", {
                from: dateOf(p.from),
                to: dateOf(p.to)
              })
            ),
            el(
              "ul",
              null,
              ...p.cells.map(
                (c) => el(
                  "li",
                  null,
                  c.value === void 0 ? say("periods.cell.withheld", { what: c.what }) : say("periods.cell", { what: c.what, value: c.value })
                )
              )
            )
          )
        )
      )
    ) : null;
    const callout = outcome === "answered" && !failed ? el(
      "aside",
      { class: "cvh-callout", "data-history": "does-not-show" },
      el("h2", null, say("callout.heading")),
      el(
        "p",
        null,
        kind === "checkpoint" ? say("callout.checkpoints") : picked ? say("callout.deals.picked", { name: name ?? "" }) : say("callout.deals")
      ),
      kind === "checkpoint" && rows.length > 0 ? el("p", null, say("callout.checkpoints.time")) : null
    ) : null;
    let shares = null;
    if (sharing) {
      const lines = [say("shares.summary")];
      if (sharing.share_deal_half === "counterparty")
        lines.push(say("shares.dealhalf.counterparty"));
      if (sharing.stranger_safe !== void 0)
        lines.push(
          sharing.stranger_safe.length > 0 ? say("shares.stranger", {
            items: sharing.stranger_safe.map(
              (t) => (words[`shares.stranger.token.${t}`] ?? BASE[`shares.stranger.token.${t}`]) !== void 0 ? say(`shares.stranger.token.${t}`) : t
            ).join(", ")
          }) : say("shares.stranger.none")
        );
      const unstated = [];
      if (sharing.standard_history === void 0) unstated.push("standard");
      else
        lines.push(
          say(
            sharing.standard_history ? "shares.standard.on" : "shares.standard.off"
          )
        );
      if (sharing.history_segments === "counterparties")
        lines.push(say("shares.segments.counterparties"));
      else if (sharing.history_segments === "peers")
        lines.push(say("shares.segments.peers"));
      else if (sharing.history_segments === "off")
        lines.push(
          sharing.record_at_completion === "counterparty" ? `${say("shares.segments.off")} ${say("shares.segments.off.sealed")}` : say("shares.segments.off")
        );
      else unstated.push("segments");
      if (sharing.exchange_corroboration === void 0)
        unstated.push("corroboration");
      else if (sharing.exchange_corroboration)
        lines.push(say("shares.corroboration.on"));
      if (sharing.record_at_completion === void 0) unstated.push("completion");
      else
        lines.push(
          say(
            sharing.record_at_completion === "counterparty" ? "shares.completion.on" : "shares.completion.off"
          )
        );
      if (sharing.adjudications === void 0) unstated.push("adjudications");
      else
        lines.push(
          say(
            sharing.adjudications === "deliver_to_subjects" ? "shares.adjudications.on" : "shares.adjudications.off"
          )
        );
      if (sharing.adjudicate_differing_twins === void 0)
        unstated.push("twins");
      else if (sharing.adjudicate_differing_twins)
        lines.push(say("shares.twins.on"));
      if (sharing.witnesses === void 0) unstated.push("witnesses");
      else
        lines.push(
          sharing.witnesses.length > 0 ? say("shares.witnesses", { witnesses: sharing.witnesses.join(", ") }) : say("shares.witnesses.none")
        );
      if (sharing.history_segments !== void 0) lines.push(say("shares.never"));
      else if (sharing.stranger_safe === void 0) unstated.push("never");
      if (unstated.length > 0)
        lines.push(
          unstated.length === 1 ? say("shares.unstated.one", {
            item: say(`shares.unstated.${unstated[0]}`)
          }) : say("shares.unstated", {
            items: unstated.map((k) => say(`shares.unstated.${k}`)).join("; ")
          })
        );
      shares = el(
        "section",
        { class: "cvh-shares", "data-history": "shares" },
        el("h2", null, say("shares.heading")),
        el("ul", null, ...lines.map((l) => el("li", null, l))),
        el(
          "p",
          { class: "cvh-note" },
          say("shares.as_of", { at: minuteOf(built) })
        )
      );
    }
    let seal = null;
    {
      const states = drawRows ? rows.map((x) => x.second.state) : [];
      const sealState = secondFailed || states.some((s) => s === "failed") ? "failed" : states.length === 0 || states.some((s) => s === "not_checked") ? "not_checked" : states.every((s) => s === "none") ? "none" : "mixed";
      const failedRows = states.filter((s) => s === "failed").length;
      const signedRows = states.filter(
        (s) => s === "failed" || s === "passed"
      ).length;
      const sealLine = sealState === "failed" ? failedRows > 0 && failedRows < signedRows ? say("seal.second.some_failed", {
        k: String(failedRows),
        n: String(signedRows)
      }) : say("slot.failed") : sealState === "none" ? say("slot.second.none") : sealState === "not_checked" ? say("slot.unchecked") : say("seal.second.rows");
      seal = el(
        "section",
        { class: "cvh-seal", "data-history": "seal" },
        drawRows && lockChecked ? el("p", { class: "cvh-seal-title" }, say("seal.title")) : null,
        drawRows && lockChecked ? el(
          "p",
          null,
          say(kind === "checkpoint" ? "seal.checkpoints" : "seal.deals")
        ) : null,
        el(
          "p",
          {
            class: "cvh-seal-slot",
            "data-filled": "no",
            "data-state": sealState
          },
          el("span", { class: "cvh-stamp-name" }, say("seal.second.label")),
          el("span", { class: "cvh-stamp-line" }, sealLine)
        ),
        directory !== void 0 ? el(
          "p",
          { class: "cvh-note", "data-history": "directory" },
          say("seal.directory", { directory })
        ) : null
      );
    }
    const checkedAttrs = {
      class: "cvh-checked",
      "data-history": "checked"
    };
    if (failed || outcome !== "answered") checkedAttrs["open"] = "";
    const panel = el(
      "details",
      checkedAttrs,
      el("summary", null, say("checked.heading")),
      el(
        "ul",
        null,
        ...checks.map(
          (c) => el(
            "li",
            { class: "cvh-check", "data-status": c.status },
            say("check.line", {
              status: say(`status.${c.status}`),
              name: say(`check.${c.id}`)
            })
          )
        )
      ),
      // The "ran" sentence only when a check passed or failed; all not-run says nothing it does not already.
      checks.some((c) => c.status === "pass" || c.status === "fail") ? el(
        "p",
        { class: "cvh-note" },
        where === "page" ? say("checked.where.page", { by: checkedBy }) : say("checked.where.builder", {
          at: minuteOf(built),
          by: checkedBy
        })
      ) : null
    );
    const tree = el(
      "section",
      {
        class: "cv-history",
        "data-history": "view",
        "data-kind": kind,
        "data-surface": surface,
        "data-verdict": failed ? "failed" : allPass ? "pass" : "unchecked"
      },
      header,
      el("div", { class: "cvh-main" }, hero, chips, rowList, periodBlock),
      el("div", { class: "cvh-side" }, callout, shares, seal, panel)
    );
    return { ok: true, tree };
  }
  function historyViewHtml(input, overlay) {
    const built = buildHistoryView(input, overlay);
    if (!built.ok) throw new HistoryViewRefused(built.reasons);
    return serializeHistoryElement(built.tree);
  }
  function renderHistoryView(input, container, overlay) {
    const doc = container.ownerDocument;
    const built = buildHistoryView(input, overlay);
    const node = built.ok ? historyElementToDom(built.tree, doc) : historyElementToDom(
      el(
        "p",
        { class: "cvh-refused", "data-history": "refused" },
        (BASE["refused"] ?? "").replace(
          "{reasons}",
          () => built.reasons.join("; ")
        )
      ),
      doc
    );
    container.replaceChildren(node);
    return built.ok;
  }
  var historyViewStyles = `.cv-history{--cvh-ink:#1f2733;--cvh-slate:#6b7482;--cvh-line:#e3ded3;--cvh-cream:#f6f2ea;--cvh-navy:#232f42;--cvh-ok:#2e7d5b;--cvh-bad:#b5462f;font:16px/1.45 system-ui,sans-serif;color:var(--cvh-ink);max-width:1120px;margin:0 auto;padding:16px;display:grid;gap:16px}
.cv-history h1{font-size:22px;margin:0}.cv-history h2{font-size:15px;margin:0 0 8px;color:var(--cvh-navy)}
.cvh-header p{margin:4px 0}.cvh-badge{display:inline-block;border:1px solid var(--cvh-line);border-radius:6px;padding:2px 8px;font-size:12px;font-weight:700;letter-spacing:.02em}
.cvh-badge[data-audience=private]{background:#fbefd9;border-color:#e8a33d}.cvh-built,.cvh-note{color:var(--cvh-slate);font-size:13px}
.cvh-hero-line{font-size:20px;font-weight:700;margin:0}.cvh-hero-note{margin:6px 0 0;color:var(--cvh-slate)}
.cvh-chips{list-style:none;padding:0;margin:0;display:flex;flex-wrap:wrap;gap:8px}.cvh-chip{background:var(--cvh-cream);border-radius:999px;padding:3px 10px;font-size:13px}
.cvh-rows{list-style:none;padding:0;margin:0}.cvh-row{border:1px solid var(--cvh-line);border-radius:10px;padding:10px 12px;margin:0 0 10px}
.cvh-row p{margin:0 0 4px}.cvh-row-title{font-weight:700}.cvh-row-detail{color:var(--cvh-slate);font-size:14px}
.cvh-proof summary{cursor:pointer;font-size:13px;color:var(--cvh-slate)}.cvh-proof code{font-size:12px;word-break:break-all}
.cvh-stamps{list-style:none;padding:0;margin:8px 0 0;display:flex;flex-wrap:wrap;gap:8px}
.cvh-stamp,.cvh-seal-slot{border:2px solid var(--cvh-navy);border-radius:999px;padding:2px 10px;font-size:12px;color:var(--cvh-navy)}
.cvh-stamp[data-filled=no],.cvh-seal-slot[data-filled=no]{border-style:dotted;border-color:#9aa1ab;color:var(--cvh-slate)}
.cvh-stamp[data-state=failed]{border-color:var(--cvh-bad);color:var(--cvh-bad)}
.cvh-stamp-name{font-weight:800}.cvh-stamp-line{margin-left:6px}
.cvh-callout,.cvh-shares,.cvh-seal,.cvh-periods{border:1px solid var(--cvh-line);border-radius:10px;padding:12px}
.cvh-callout{background:var(--cvh-cream)}.cvh-callout p,.cvh-seal p{margin:0 0 6px}.cvh-shares ul,.cvh-periods ul{margin:0;padding-left:18px}
.cvh-seal-title{font-weight:700}.cvh-checked summary{cursor:pointer;font-weight:700;color:var(--cvh-navy)}
.cvh-check[data-status=fail]{color:var(--cvh-bad)}.cvh-check[data-status=pass]{color:var(--cvh-ok)}
.cvh-main,.cvh-side{display:grid;gap:16px;align-content:start}.cvh-refused{border:1px solid var(--cvh-bad);color:var(--cvh-bad);padding:8px 12px;border-radius:8px}
@media screen and (prefers-color-scheme:dark){.cv-history{--cvh-ink:#e8eaee;--cvh-slate:#a3a9b3;--cvh-line:#33373e;--cvh-cream:#22262d;--cvh-navy:#c3d0e8;--cvh-ok:#5fcf90;--cvh-bad:#ff8f84;background:#16181c;color-scheme:dark}.cvh-badge[data-audience=private]{background:#3a2f1a;border-color:#e6b85c}}
@media (min-width:900px){.cv-history{grid-template-columns:minmax(0,3fr) minmax(0,2fr)}.cvh-header{grid-column:1/-1}}
@media print{.cv-history{max-width:none;grid-template-columns:1fr}.cvh-proof code{display:block}}
`;
  function historyViewDocument(input, overlay, title = "History") {
    const body = historyViewHtml(input, overlay);
    return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escapeText(title)}</title><style>${historyViewStyles}</style></head><body>${body}</body></html>
`;
  }
  return __toCommonJS(history_view_exports);
})();
