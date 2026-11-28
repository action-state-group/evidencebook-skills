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
    SEAL_SHAPES: () => SEAL_SHAPES,
    amountText: () => amountText,
    buildHistoryView: () => buildHistoryView,
    historyElementToDom: () => historyElementToDom,
    historyViewDocument: () => historyViewDocument,
    historyViewHtml: () => historyViewHtml,
    historyViewStyles: () => historyViewStyles,
    renderHistoryView: () => renderHistoryView,
    serializeHistoryElement: () => serializeHistoryElement,
    sha256Hex: () => sha256Hex
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
      "hero.deals.picked.one": "1 deal {name} picked \xB7 this side's record, not confirmed outcomes",
      "hero.deals.picked.other": "{n} deals {name} picked \xB7 this side's record, not confirmed outcomes",
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
      "callout.deals": "Each deal's outcome here is what this side recorded, not a confirmed outcome.",
      "callout.deals.named": "Each deal's outcome here is what {name} recorded, not a confirmed outcome.",
      "callout.deals.picked": "{name} picked these; it isn't every deal. Each outcome is what {name}'s side recorded, not a confirmed outcome.",
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
      "check.line.unregistered": "{status}: {name}. Checkpoint {n} (cut {at}) is not registered with the witness yet.",
      "check.second_signature": "A second party signed this record",
      "check.deal_report": "Each deal was read with its own report, which writes nothing",
      refused: "This page can't show this history: {reasons}",
      "card.title.owner": "Your History",
      "card.title.recipient": "{name}'s History",
      "card.tag.private": "Private: your copy",
      "card.tag.shared": "Shared copy",
      "card.download": "Download card",
      "card.counts.none": "No deals yet.",
      "card.counts.one": "1 deal",
      "card.counts.other": "{n} deals",
      "card.counts.all.one": ", and it went as agreed.",
      "card.counts.all": ", every one went as agreed.",
      "card.counts.didnt": ", {k} didn't go as agreed",
      "card.counts.open": ", {u} not final yet",
      "card.failed": `This card didn't verify, so its counts are not shown. See "Is this record intact?".`,
      "card.reported.owner": "As your own records show.",
      "card.reported": "As {name} reported.",
      "card.waiting.one": "1 more deal not counted yet: waiting for a time-stamp.",
      "card.waiting.other": "{n} more deals not counted yet: waiting for a time-stamp.",
      "card.sample.one": "1 of these deals is sample history.",
      "card.sample.other": "{n} of these deals are sample history.",
      "card.as_of.before": "Counted as of ",
      "card.as_of.after": ".",
      "card.rows.heading": "Your deals, newest first",
      "card.row.bought": "Bought",
      "card.row.sold": "Sold",
      "card.term.yours": "your side's term",
      "card.term.theirs": "their side's term",
      "card.term.yours.label": "Your side",
      "card.term.theirs.label": "Their side",
      "card.row.ruled": "Ruled: {term} not met",
      "card.row.remedy.made": ", remedy made",
      "card.row.remedy.due": ", remedy due",
      "card.row.remedy.not_honoured": ", remedy not made in time",
      "card.row.in_dispute": "In dispute before the adjudicator",
      "card.row.in_disagreement": "The two sides' statements differ",
      "card.row.went": "Went as agreed: both sides say every term was met",
      "card.row.not_due": "Nothing is due yet",
      "card.row.not_reached": "No term has come due",
      "card.row.open": "Not final yet",
      "card.row.outcome.held": "Went as agreed",
      "card.row.outcome.did_not_hold": "Didn't go as agreed",
      "card.row.outcome.undecided": "Not final yet",
      "card.row.amount.band": "{amount} or more (value band)",
      "card.row.agreed": "Agreed",
      "card.row.both_halves": "Their signed agreement is in your records.",
      "card.row.receipt": "Open this deal's receipt",
      "card.status.not_reached": "never came due",
      "card.status.not_due": "not due yet",
      "card.status.no_statement": "no statement",
      "card.status.waiting": "waiting for the other side",
      "card.status.uncontested": "met, not contested",
      "card.status.agreed_so_far": "both say the same so far",
      "card.status.agreed": "both say the same",
      "card.status.in_disagreement": "statements differ",
      "card.status.in_dispute": "in dispute",
      "card.status.ruled": "ruled",
      "card.status.ruled.met": ", met",
      "card.status.ruled.not_met": ", not met",
      "card.seal.not_as_agreed": "Didn't go as agreed",
      "card.stamp.recorded": "RECORDED",
      "card.stamp.recorded.filled": "Checkpointed",
      "card.stamp.recorded.partial": "Checkpointed through step {k} of {n}",
      "card.stamp.recorded.open": "Not checkpointed yet",
      "card.stamp.recorded.not_checked": "Not checked here",
      "card.stamp.recorded.failed": "Didn't verify",
      "card.stamp.time_stamped": "TIME-STAMPED",
      "card.stamp.time_stamped.open": "Not time-stamped yet",
      "card.stamp.time_stamped.not_checked": "Not checked here",
      "card.stamp.time_stamped.failed": "Didn't verify",
      "card.stamp.countersigned": "COUNTERSIGNED",
      "card.stamp.countersigned.by": "{signer} signed this record too",
      "card.stamp.countersigned.clock": ", by their clock",
      "card.stamp.countersigned.open": "Not countersigned",
      "card.stamp.countersigned.not_checked": "Not checked here",
      "card.stamp.countersigned.failed": "Didn't verify",
      "card.signed.heading": "Who signed this card",
      "card.signed.by": "Signed by key {key}, the key you know as {name}",
      "card.signed.note": "The signature shows who wrote this card and that it is unchanged since. It does not show that the deals happened.",
      "card.proof.heading": "Is this record intact?",
      "card.proof.lede.passed": "Yes. capsulectl verify passed every test when this page was made. The page shows its answer; it did not re-check by itself.",
      "card.proof.lede.partial": "capsulectl verify passed every test it ran when this page was made; a test marked \u2013 was not run on this copy. The page shows its answer; it did not re-check by itself.",
      "card.proof.lede.failed": "No. capsulectl verify reported a test that failed.",
      "card.proof.status.pass": "passed",
      "card.proof.status.fail": "failed",
      "card.proof.status.withheld": "not run on this copy",
      "card.proof.status.absent": "not in this copy",
      "card.proof.producer_signatures": "Signed by the agent's device",
      "card.proof.interval_coverage": "No step missing from first to last",
      "card.proof.graph_closure": "Each step links to the one before",
      "card.proof.per_record_membership": "Every step is in this card's log",
      "card.proof.checkpoint": "The log's summary adds up",
      "card.proof.witness.filled": "Witness time stamp: {witness} at",
      "card.proof.witness.open": "Witness time stamp: not in this copy",
      "card.proof.witness.failed": "Witness time stamp: didn't verify",
      "card.check.title": "Check it yourself",
      "card.check.download": "On the downloaded card:",
      "card.check.expect": "Expect: {verdict}, fingerprint {fingerprint}.",
      "card.not_proven.heading": "What this does not prove",
      "card.not_proven.true.owner": "That what the agents said was true. Only that your records weren't changed after sealing.",
      "card.not_proven.true": "That the deals went as {name} counted them. Only that {name} signed these counts and they weren't changed since.",
      "card.not_proven.who.owner": "Who made the records. The signing key is on your agent's machine.",
      "card.not_proven.who": "Who made the records. The signing key is on the machine of whoever holds that key.",
      "card.not_proven.outside": "Anything outside these deals.",
      "card.technical": "Technical details",
      "card.technical.card": "Card",
      "card.technical.key": "Signing key",
      "card.technical.digest": "Proof fingerprint",
      "card.technical.deals": "Deal ids",
      "card.footer.utc": "Times are in UTC.",
      "card.footer.local": "Times are in your time zone.",
      "card.footer.private": "This page is your private copy, and so is the card it downloads: never send either. To show your History to someone, send them your counts-only card, made with capsulectl deal standard-history card --shared.",
      "card.footer.shared": "This page shows the card {name} sent. Only its counts are here; {name} keeps its deals.",
      "card.footer.built.before": "Page made ",
      "card.footer.built.after": ".",
      "card.row.not_met": "Not met: {term}",
      "card.row.went.final": "Went as agreed: every term ended as met",
      "card.status.uncontested.not_met": "not met, not contested",
      "card.status.agreed.not_met": "both say it was not met",
      "card.status.agreed_so_far.not_met": "both say it was not met, so far",
      "card.stamp.time_stamped.partial": "Time-stamped through step {k} of {n}",
      "card.stamp.countersigned.partial": "Countersigned through step {k} of {n}",
      "card.signed.failed": "capsulectl verify reported that this card's signature didn't verify.",
      "card.signed.unchecked": "capsulectl verify reported no signature check for this card.",
      "card.signed.claimed": "This card names its signer as key {key}, the key you know as {name}",
      "card.download.private": "Download your private card",
      "card.signed.by.owner": "Signed by your key {key}",
      "card.signed.claimed.owner": "This card names its signer as your key {key}",
      "card.term.yours.label.n": "Your side, term {n}",
      "card.term.theirs.label.n": "Their side, term {n}"
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
  var ATTR_NAME = /^[a-zA-Z][a-zA-Z0-9-]*$/u;
  var ATTR_VALUE = /^[^<>"\u00a0]*$/u;
  function el(tag, attrs, ...children) {
    const pairs = Object.entries(attrs ?? {});
    for (const [name, value] of pairs)
      if (!ATTR_NAME.test(name) || !ATTR_VALUE.test(value))
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
    const attrs = node.attrs.map(([n, v]) => ` ${n}="${v.replace(/&/gu, "&amp;")}"`).join("");
    return `<${node.tag}${attrs}>${node.children.map(serializeHistoryElement).join("")}</${node.tag}>`;
  }
  var SVG_TAGS = /* @__PURE__ */ new Set([
    "svg",
    "path",
    "circle",
    "ellipse"
  ]);
  function historyElementToDom(node, doc) {
    if (typeof node === "string") return doc.createTextNode(node);
    const out = SVG_TAGS.has(node.tag) ? doc.createElementNS("http://www.w3.org/2000/svg", node.tag) : doc.createElement(node.tag);
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
  function readUnregistered(r, v, path, kind, rows) {
    if (typeof v === "object" && v !== null && !Array.isArray(v) && Object.keys(v).length === 0)
      return void 0;
    const o = r.object(v, path, ["n", "at"], ["n", "at"]);
    if (!o || !("n" in o) || !("at" in o)) return void 0;
    const n = r.count(o["n"], `${path}.n`);
    const at = r.time(o["at"], `${path}.at`);
    if (kind !== "checkpoint") {
      r.refuse(path, "names a checkpoint, and only a checkpoint page has them");
      return void 0;
    }
    if (n === void 0 || at === void 0) return void 0;
    const row = rows[n - 1];
    if (n < 1 || row === void 0 || row.kind !== "checkpoint") {
      r.refuse(
        `${path}.n`,
        "is not the place of one of this page's rows (1 to the number of rows)"
      );
      return void 0;
    }
    if (row.witness.state === "passed") {
      r.refuse(`${path}.n`, "names a row whose time-stamp passed");
      return void 0;
    }
    if (row.cut.ms !== at.ms) {
      r.refuse(`${path}.at`, "is not the cut time of row n");
      return void 0;
    }
    return { n, at };
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
  function sha256Hex(text) {
    const K = [
      1116352408,
      1899447441,
      3049323471,
      3921009573,
      961987163,
      1508970993,
      2453635748,
      2870763221,
      3624381080,
      310598401,
      607225278,
      1426881987,
      1925078388,
      2162078206,
      2614888103,
      3248222580,
      3835390401,
      4022224774,
      264347078,
      604807628,
      770255983,
      1249150122,
      1555081692,
      1996064986,
      2554220882,
      2821834349,
      2952996808,
      3210313671,
      3336571891,
      3584528711,
      113926993,
      338241895,
      666307205,
      773529912,
      1294757372,
      1396182291,
      1695183700,
      1986661051,
      2177026350,
      2456956037,
      2730485921,
      2820302411,
      3259730800,
      3345764771,
      3516065817,
      3600352804,
      4094571909,
      275423344,
      430227734,
      506948616,
      659060556,
      883997877,
      958139571,
      1322822218,
      1537002063,
      1747873779,
      1955562222,
      2024104815,
      2227730452,
      2361852424,
      2428436474,
      2756734187,
      3204031479,
      3329325298
    ];
    const bytes = new TextEncoder().encode(text);
    const len = bytes.length;
    const padded = new Uint8Array(len + 9 + 63 >> 6 << 6);
    padded.set(bytes);
    padded[len] = 128;
    const view = new DataView(padded.buffer);
    view.setUint32(padded.length - 8, Math.floor(len / 536870912));
    view.setUint32(padded.length - 4, len << 3 >>> 0);
    const h = [
      1779033703,
      3144134277,
      1013904242,
      2773480762,
      1359893119,
      2600822924,
      528734635,
      1541459225
    ];
    const w = new Array(64);
    const rot = (x, n) => x >>> n | x << 32 - n;
    for (let off = 0; off < padded.length; off += 64) {
      for (let i = 0; i < 16; i++) w[i] = view.getUint32(off + i * 4);
      for (let i = 16; i < 64; i++) {
        const a2 = w[i - 15] ?? 0;
        const b2 = w[i - 2] ?? 0;
        const s0 = rot(a2, 7) ^ rot(a2, 18) ^ a2 >>> 3;
        const s1 = rot(b2, 17) ^ rot(b2, 19) ^ b2 >>> 10;
        w[i] = (w[i - 16] ?? 0) + s0 + (w[i - 7] ?? 0) + s1 | 0;
      }
      let [a, b, c, d, e, f, g, k] = h;
      for (let i = 0; i < 64; i++) {
        const t1 = k + (rot(e, 6) ^ rot(e, 11) ^ rot(e, 25)) + (e & f ^ ~e & g) + (K[i] ?? 0) + (w[i] ?? 0) | 0;
        const t2 = (rot(a, 2) ^ rot(a, 13) ^ rot(a, 22)) + (a & b ^ a & c ^ b & c) | 0;
        k = g;
        g = f;
        f = e;
        e = d + t1 | 0;
        d = c;
        c = b;
        b = a;
        a = t1 + t2 | 0;
      }
      const add = [a, b, c, d, e, f, g, k];
      for (let i = 0; i < 8; i++) h[i] = (h[i] ?? 0) + (add[i] ?? 0) | 0;
    }
    return h.map((x) => (x >>> 0).toString(16).padStart(8, "0")).join("");
  }
  var ROW_STATUSES = [
    "not_reached",
    "not_due",
    "no_statement",
    "waiting",
    "uncontested",
    "agreed_so_far",
    "agreed",
    "in_disagreement",
    "in_dispute",
    "ruled"
  ];
  var PROOF_CHECKS = [
    "producer_signatures",
    "interval_coverage",
    "graph_closure",
    "per_record_membership",
    "checkpoint"
  ];
  var FILE_JSON = /^[A-Za-z0-9][A-Za-z0-9._-]{0,150}\.json$/u;
  var FILE_HTML = /^[A-Za-z0-9][A-Za-z0-9._-]{0,150}\.html$/u;
  var HEX64 = /^[0-9a-f]{64}$/u;
  var DIGITS = /^(0|[1-9][0-9]{0,299})$/u;
  var CURRENCY = /^(?:[A-Z]{3}|[-a-z0-9]{3,8}:[-_a-zA-Z0-9]{1,32}\/[-a-z0-9]{3,8}:[-.%a-zA-Z0-9]{1,128})$/u;
  function isObj(v) {
    return typeof v === "object" && v !== null && !Array.isArray(v);
  }
  function count(v) {
    return typeof v === "number" && Number.isSafeInteger(v) && v >= 0 ? v : void 0;
  }
  function readAmount(r, v, path) {
    const o = r.object(
      v,
      path,
      ["value", "assetCode", "assetScale"],
      ["value", "assetCode", "assetScale"]
    );
    if (!o) return void 0;
    const value = typeof o["value"] === "string" ? o["value"] : "";
    const code = typeof o["assetCode"] === "string" ? o["assetCode"] : "";
    const scale = o["assetScale"];
    if (!DIGITS.test(value) || !CURRENCY.test(code) || typeof scale !== "number" || !Number.isSafeInteger(scale) || scale < 0 || scale > 255) {
      r.refuse(
        path,
        "is not an amount (an integer value, an ISO 4217 or CAIP-19 assetCode, assetScale 0 to 255)"
      );
      return void 0;
    }
    return { value, code, scale };
  }
  function grouped(digits) {
    return digits.replace(/\B(?=(\d{3})+(?!\d))/gu, ",");
  }
  function amountText(a) {
    if (a.code === "BTC" && a.scale <= 11) {
      const msat = a.value === "0" ? "0" : a.value + "0".repeat(11 - a.scale);
      if (msat === "0") return "0 sat";
      if (msat.length > 3 && msat.endsWith("000"))
        return `${grouped(msat.slice(0, -3))} sat`;
      return `${grouped(msat)} msat`;
    }
    if (a.scale === 0) return `${grouped(a.value)} ${a.code}`;
    const padded = a.value.padStart(a.scale + 1, "0");
    const whole = padded.slice(0, padded.length - a.scale);
    return `${grouped(whole)}.${padded.slice(padded.length - a.scale)} ${a.code}`;
  }
  function readCardObject(r, text) {
    let doc;
    try {
      doc = JSON.parse(text);
    } catch {
      r.refuse("input.machine.text", "is not JSON");
      return void 0;
    }
    const bad = (why) => {
      r.refuse("input.machine.text", why);
      return void 0;
    };
    if (!isObj(doc)) return bad("is not a bundle");
    const records = doc["records"];
    const root = Array.isArray(records) ? records[0] : void 0;
    if (!isObj(root)) return bad("has no root record");
    const cid = root["capsule_id"];
    const disclosures = doc["disclosures"];
    const disclosed = typeof cid === "string" && isObj(disclosures) ? disclosures[cid] : void 0;
    const card = isObj(disclosed) ? disclosed["agent_input"] : void 0;
    if (!isObj(card)) return bad("discloses no card on its root record");
    const derivation = card["derivation"];
    if (typeof derivation !== "string" || !/^standard_history\/[1-4]$/u.test(derivation))
      return bad("its card is not a standard_history card");
    const oc = card["outcomes"];
    if (isObj(oc) && Object.keys(oc).some(
      (k) => !["of", "held", "did_not_hold", "undecided"].includes(k)
    ))
      return bad("its card's outcomes carry a member SH \xA74 does not have");
    const of = isObj(oc) ? count(oc["of"]) : void 0;
    const held = isObj(oc) ? count(oc["held"]) : void 0;
    const didNotHold = isObj(oc) ? count(oc["did_not_hold"]) : void 0;
    const undecided = isObj(oc) ? count(oc["undecided"]) : void 0;
    if (of === void 0 || held === void 0 || didNotHold === void 0 || undecided === void 0 || held + didNotHold + undecided !== of)
      return bad("its card's outcomes are not a tally");
    const nc = card["not_counted"];
    const waiting = isObj(nc) ? count(nc["no_witness_time"]) ?? 0 : 0;
    const keyId = typeof root["key_id"] === "string" ? root["key_id"] : "";
    const signedAt = typeof root["timestamp"] === "string" ? parseInstant(root["timestamp"]) : void 0;
    const ext = isObj(doc["extensions"]) ? doc["extensions"]["x-standard-history/v0"] : void 0;
    const asOf = isObj(ext) && isObj(ext["as_of"]) && typeof ext["as_of"]["anchor_time"] === "string" ? parseInstant(ext["as_of"]["anchor_time"]) : void 0;
    let deals;
    if (isObj(ext) && "deals" in ext) {
      deals = [];
      const list = ext["deals"];
      if (!Array.isArray(list)) return bad("its deals are not a list");
      for (const [i, d] of list.entries()) {
        const path = `input.machine.text deals[${i}]`;
        if (!isObj(d)) {
          r.refuse(path, "is not a deal entry");
          continue;
        }
        const id = typeof d["deal"] === "string" ? d["deal"] : "";
        const agreed = typeof d["agreed_at"] === "string" ? parseInstant(d["agreed_at"]) : void 0;
        const role = d["role"];
        if (id === "" || id.length > 200 || agreed === void 0 || role !== "provided" && role !== "bought") {
          r.refuse(path, "has no deal id, agreed time or role");
          continue;
        }
        const amount = "amount" in d ? readAmount(r, d["amount"], `${path}.amount`) : void 0;
        const outcome = d["outcome"];
        let terms;
        if (Array.isArray(d["rows"])) {
          terms = [];
          for (const row of d["rows"]) {
            const status = isObj(row) ? row["status"] : void 0;
            const value = isObj(row) ? row["value"] : void 0;
            const remedy = isObj(row) ? row["remedy"] : void 0;
            if (!isObj(row) || row["owed_by"] !== "holder" && row["owed_by"] !== "counterparty" || typeof status !== "string" || !ROW_STATUSES.includes(status) || value !== void 0 && value !== "met" && value !== "not_met" || remedy !== void 0 && typeof remedy !== "string") {
              r.refuse(path, "has a row that is not an SH \xA711.2 row result");
              continue;
            }
            terms.push({
              holder: row["owed_by"] === "holder",
              status,
              value,
              remedy
            });
          }
        }
        deals.push({
          id,
          agreed,
          role,
          amount,
          outcome: outcome === "held" || outcome === "did_not_hold" || outcome === "undecided" ? outcome : void 0,
          terms,
          bothHalves: d["happened"] === "stamped_by_both"
        });
      }
    }
    return {
      derivation,
      keyId,
      signedAt,
      outcomes: { of, held, didNotHold, undecided },
      waiting,
      asOf,
      deals
    };
  }
  var CARD_TOP = [
    "view",
    "kind",
    "surface",
    "reader",
    "holder",
    "audience",
    "built_at",
    "checked",
    "rows",
    "checks",
    "machine",
    "deals",
    "sample"
  ];
  function buildCardPage(r, o, overlay) {
    for (const k of Object.keys(o))
      if (!CARD_TOP.includes(k))
        r.refuse(`input.${k}`, "is not a member of a card page");
    if (o["kind"] !== "deal")
      r.refuse("input.kind", "a card page is a deal page");
    const surface = r.oneOf(o["surface"], "input.surface", ["neutral", "product"]) ?? "neutral";
    const reader = r.oneOf(o["reader"], "input.reader", ["owner", "recipient"]) ?? "recipient";
    let words = {};
    if (overlay !== void 0) {
      if (surface !== "product")
        r.refuse("overlay", "a neutral page takes no overlay");
      else words = readOverlay(r, overlay);
    }
    const ho = r.object(o["holder"], "input.holder", ["name"], ["name"]);
    const name = ho ? r.string(ho["name"], "input.holder.name", 200) : void 0;
    const au = r.object(o["audience"], "input.audience", ["kind"], ["kind"]);
    const audience = au ? r.oneOf(au["kind"], "input.audience.kind", ["private", "shared"]) : void 0;
    if (reader === "owner" && audience !== void 0 && audience !== "private")
      r.refuse("input.audience.kind", "the holder's own page is private");
    if (reader === "recipient" && audience !== void 0 && audience !== "shared")
      r.refuse("input.audience.kind", "a card someone was sent is shared");
    const built = r.time(o["built_at"], "input.built_at") ?? EPOCH;
    const ck = r.object(
      o["checked"],
      "input.checked",
      ["where", "by"],
      ["where", "by"]
    );
    if (ck) {
      r.oneOf(ck["where"], "input.checked.where", ["builder"]);
      r.string(ck["by"], "input.checked.by", 200);
    }
    if (!Array.isArray(o["rows"]) || o["rows"].length > 0)
      r.refuse(
        "input.rows",
        "must be empty: a card page reads its rows from its object"
      );
    if (!Array.isArray(o["checks"]) || o["checks"].length > 0)
      r.refuse(
        "input.checks",
        "must be empty: a card page shows capsulectl verify's checks"
      );
    const sample = "sample" in o ? r.count(o["sample"], "input.sample") : void 0;
    const mo = r.object(
      o["machine"],
      "input.machine",
      ["file", "text", "verify"],
      ["file", "text", "verify"]
    );
    const file = mo ? r.string(mo["file"], "input.machine.file", 160) : void 0;
    if (file !== void 0 && !FILE_JSON.test(file))
      r.refuse("input.machine.file", "is not a plain .json file name");
    const text = mo ? r.string(mo["text"], "input.machine.text", 16e6) : void 0;
    const vo = mo ? r.object(
      mo["verify"],
      "input.machine.verify",
      ["verdict", "bundle_digest", "checks", "witness"],
      ["verdict", "bundle_digest", "checks"]
    ) : null;
    const verdict = vo ? r.oneOf(vo["verdict"], "input.machine.verify.verdict", [
      "VALID",
      "INVALID"
    ]) : void 0;
    const digest = vo ? r.string(vo["bundle_digest"], "input.machine.verify.bundle_digest", 64) : void 0;
    if (digest !== void 0 && !HEX64.test(digest))
      r.refuse("input.machine.verify.bundle_digest", "is not 64 lowercase hex");
    if (text !== void 0 && digest !== void 0 && sha256Hex(text) !== digest)
      r.refuse(
        "input.machine.text",
        "is not the bundle capsulectl verify answered for (its SHA-256 is not the bundle_digest)"
      );
    const proof = {};
    const cko = vo ? r.object(
      vo["checks"],
      "input.machine.verify.checks",
      [...PROOF_CHECKS, "witnesses"],
      []
    ) : null;
    if (cko)
      for (const [k, v] of Object.entries(cko)) {
        const s = r.oneOf(v, `input.machine.verify.checks.${k}`, [
          "pass",
          "fail",
          "withheld"
        ]);
        if (s) proof[k] = s;
      }
    let witnessBy;
    let witnessAt;
    if (vo && "witness" in vo) {
      const wo = r.object(
        vo["witness"],
        "input.machine.verify.witness",
        ["by", "at"],
        ["by", "at"]
      );
      witnessBy = wo ? r.string(wo["by"], "input.machine.verify.witness.by", 200) : void 0;
      witnessAt = wo ? r.time(wo["at"], "input.machine.verify.witness.at") : void 0;
    }
    if (proof["witnesses"] === "pass" && witnessAt === void 0)
      r.refuse(
        "input.machine.verify.witness",
        "is missing (a passed witness check names its witness and time)"
      );
    if (proof["witnesses"] !== "pass" && vo && "witness" in vo)
      r.refuse(
        "input.machine.verify.witness",
        "is only for a passed witness check"
      );
    const obj = text !== void 0 ? readCardObject(r, text) : void 0;
    if (obj && reader === "recipient" && obj.deals !== void 0)
      r.refuse(
        "input.machine.text",
        "carries the holder's deal entries; a card someone was sent never does"
      );
    if (obj && reader === "owner" && obj.deals === void 0)
      r.refuse(
        "input.machine.text",
        "carries no deal entries; the holder's own page is drawn from its own copy"
      );
    const extras = /* @__PURE__ */ new Map();
    if ("deals" in o) {
      if (reader !== "owner")
        r.refuse("input.deals", "is only for the holder's own page");
      const dm = r.object(
        o["deals"],
        "input.deals",
        obj?.deals?.map((d) => d.id) ?? [],
        []
      );
      if (dm)
        for (const [id, v] of Object.entries(dm)) {
          const path = `input.deals.${id}`;
          const e = r.object(
            v,
            path,
            [
              "item",
              "amount",
              "recorded",
              "time_stamped",
              "countersigned",
              "receipt"
            ],
            []
          );
          if (!e) continue;
          const receipt = "receipt" in e ? r.string(e["receipt"], `${path}.receipt`, 160) : void 0;
          if (receipt !== void 0 && !FILE_HTML.test(receipt))
            r.refuse(`${path}.receipt`, "is not a plain .html file name");
          extras.set(id, {
            item: "item" in e ? r.string(e["item"], `${path}.item`, 300) : void 0,
            amount: "amount" in e ? readAmount(r, e["amount"], `${path}.amount`) : void 0,
            recorded: "recorded" in e ? readSlot(r, e["recorded"], `${path}.recorded`, false) : void 0,
            witness: "time_stamped" in e ? readSlot(r, e["time_stamped"], `${path}.time_stamped`, true) : void 0,
            countersigned: "countersigned" in e ? readSlot(r, e["countersigned"], `${path}.countersigned`, true) : void 0,
            receipt
          });
        }
    }
    if (r.reasons.length > 0 || !obj || name === void 0)
      return {
        ok: false,
        reasons: r.reasons.length > 0 ? r.reasons : ["input: no card"]
      };
    const say = (key, values = {}) => {
      const t = words[key] ?? BASE[key];
      if (t === void 0) throw new Error(`history-view: no words for ${key}`);
      return t.replace(PLACEHOLDER, (_, p) => {
        const v = values[p];
        if (v === void 0) throw new Error(`history-view: ${key} needs {${p}}`);
        return v;
      });
    };
    const plural = (key, n, values = {}) => say(`${key}.${n === 1 ? "one" : "other"}`, {
      n: grouped(String(n)),
      ...values
    });
    const short = (id) => id.length > 16 ? `${id.slice(0, 8)}\u2026${id.slice(-4)}` : id;
    const time = (t) => el(
      "time",
      { datetime: new Date(t.ms).toISOString(), "data-time": "minute" },
      minuteOf(t)
    );
    const owner = reader === "owner";
    const failed = verdict !== "VALID";
    const download = el(
      "a",
      {
        class: "cvh-button",
        href: `data:application/json;charset=utf-8,${encodeURIComponent(text ?? "")}`,
        download: file ?? "",
        "data-history": "download"
      },
      say(owner ? "card.download.private" : "card.download")
    );
    const header = el(
      "header",
      { class: "cvh-header", "data-history": "header" },
      el(
        "h1",
        { class: "cvh-title" },
        owner ? say("card.title.owner") : say("card.title.recipient", { name })
      ),
      el(
        "p",
        { class: "cvh-tags" },
        el(
          "span",
          { class: "cvh-tag", "data-audience": owner ? "private" : "shared" },
          say(owner ? "card.tag.private" : "card.tag.shared")
        ),
        download
      )
    );
    const oc = obj.outcomes;
    const counts = oc.of === 0 ? say("card.counts.none") : plural("card.counts", oc.of) + (oc.didNotHold === 0 && oc.undecided === 0 ? say(oc.of === 1 ? "card.counts.all.one" : "card.counts.all") : say("card.counts.didnt", { k: grouped(String(oc.didNotHold)) }) + (oc.undecided > 0 ? say("card.counts.open", { u: grouped(String(oc.undecided)) }) : ""));
    const heroLines = failed ? [
      el(
        "p",
        { class: "cvh-hero-line", "data-history": "top-line" },
        say("card.failed")
      )
    ] : [
      el("p", { class: "cvh-hero-line", "data-history": "top-line" }, counts),
      el(
        "p",
        { class: "cvh-hero-note" },
        owner ? say("card.reported.owner") : say("card.reported", { name })
      ),
      obj.waiting > 0 ? el(
        "p",
        { class: "cvh-hero-note" },
        plural("card.waiting", obj.waiting)
      ) : null,
      sample !== void 0 && sample > 0 ? el(
        "p",
        { class: "cvh-hero-note", "data-history": "sample" },
        plural("card.sample", sample)
      ) : null,
      obj.asOf !== void 0 ? el(
        "p",
        { class: "cvh-hero-note" },
        say("card.as_of.before"),
        time(obj.asOf),
        say("card.as_of.after")
      ) : null
    ];
    const hero = el(
      "section",
      { class: "cvh-hero", "data-history": "hero" },
      ...heroLines
    );
    let rowList = null;
    if (owner && !failed && obj.deals !== void 0 && obj.deals.length > 0) {
      const sorted = [...obj.deals].sort(
        (a, b) => b.agreed.ms - a.agreed.ms || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0)
      );
      const stamp = (nameKey, state, line) => el(
        "li",
        {
          class: "cvh-stamp",
          "data-filled": state === "filled" ? "yes" : "no",
          "data-state": state
        },
        el("span", { class: "cvh-stamp-name" }, say(nameKey)),
        el("span", { class: "cvh-stamp-line" }, ...line)
      );
      const slotState = (s) => s === void 0 || s.state === "not_checked" ? "not_checked" : s.state === "passed" ? s.through !== void 0 && s.through.k < s.through.n ? "partial" : "filled" : s.state === "failed" ? "failed" : "open";
      const items = sorted.map((d) => {
        const x = extras.get(d.id);
        const title = say(
          d.role === "bought" ? "card.row.bought" : "card.row.sold"
        );
        let line;
        let seal = false;
        const t = d.terms;
        if (t !== void 0 && t.length > 0) {
          const ruled = t.find(
            (x2) => x2.status === "ruled" && x2.value === "not_met"
          );
          if (ruled) {
            seal = true;
            line = say("card.row.ruled", {
              term: say(ruled.holder ? "card.term.yours" : "card.term.theirs")
            });
            if (ruled.remedy === "made" || ruled.remedy === "due" || ruled.remedy === "not_honoured")
              line += say(`card.row.remedy.${ruled.remedy}`);
          } else if (t.some((x2) => x2.status === "in_dispute"))
            line = say("card.row.in_dispute");
          else if (t.some((x2) => x2.status === "in_disagreement"))
            line = say("card.row.in_disagreement");
          else if (t.some(
            (x2) => x2.value === "not_met" && (x2.status === "agreed" || x2.status === "agreed_so_far" || x2.status === "uncontested")
          )) {
            const stated = t.find(
              (x2) => x2.value === "not_met" && (x2.status === "agreed" || x2.status === "agreed_so_far" || x2.status === "uncontested")
            );
            line = say("card.row.not_met", {
              term: say(stated?.holder ? "card.term.yours" : "card.term.theirs")
            });
            if (stated?.remedy === "made") line += say("card.row.remedy.made");
          } else if (t.every((x2) => x2.status === "agreed" && x2.value === "met"))
            line = say("card.row.went");
          else if (t.every(
            (x2) => (x2.status === "agreed" || x2.status === "uncontested" || x2.status === "ruled") && x2.value === "met"
          ))
            line = say("card.row.went.final");
          else if (t.every((x2) => x2.status === "not_due"))
            line = say("card.row.not_due");
          else if (t.every((x2) => x2.status === "not_reached"))
            line = say("card.row.not_reached");
          else line = say("card.row.open");
        } else
          line = say(
            d.outcome === "held" ? "card.row.outcome.held" : d.outcome === "did_not_hold" ? "card.row.outcome.did_not_hold" : "card.row.outcome.undecided"
          );
        const amount = x?.amount ?? d.amount;
        const facts = [];
        const exact = x?.amount !== void 0 || d.terms === void 0;
        if (amount !== void 0 && (exact || amount.value !== "0"))
          facts.push(
            exact ? amountText(amount) : say("card.row.amount.band", { amount: amountText(amount) }),
            " \xB7 "
          );
        facts.push(say("card.row.agreed"), " ", time(d.agreed));
        const sides = { yours: 0, theirs: 0 };
        const many = (holder) => (t ?? []).filter((x2) => x2.holder === holder).length > 1;
        const label = (holder) => {
          const side = holder ? "yours" : "theirs";
          sides[side] += 1;
          return many(holder) ? say(`card.term.${side}.label.n`, { n: String(sides[side]) }) : say(`card.term.${side}.label`);
        };
        const termLine = t !== void 0 && t.length > 0 ? [...t].sort((a, b) => a.holder === b.holder ? 0 : a.holder ? -1 : 1).map(
          (x2) => `${label(x2.holder)}: ${say(
            x2.value === "not_met" && x2.status !== "ruled" && BASE[`card.status.${x2.status}.not_met`] !== void 0 ? `card.status.${x2.status}.not_met` : `card.status.${x2.status}`
          )}${x2.status === "ruled" && x2.value !== void 0 ? say(`card.status.ruled.${x2.value}`) : ""}`
        ).join("; ") : null;
        const part = (key, s) => s?.through !== void 0 && s.at !== void 0 ? [
          say(key, { k: String(s.through.k), n: String(s.through.n) }),
          " \xB7 ",
          time(s.at)
        ] : [];
        const rec = x?.recorded;
        const recState = slotState(rec);
        const recLine = recState === "partial" ? part("card.stamp.recorded.partial", rec) : recState === "filled" && rec?.at ? [say("card.stamp.recorded.filled"), " \xB7 ", time(rec.at)] : [say(`card.stamp.recorded.${recState}`)];
        const ts = x?.witness;
        const tsState = slotState(ts);
        const tsLine = tsState === "partial" ? [
          `${ts?.by ?? ""} \xB7 `,
          ...part("card.stamp.time_stamped.partial", ts)
        ] : tsState === "filled" && ts?.at ? [`${ts.by ?? ""} \xB7 `, time(ts.at)] : [say(`card.stamp.time_stamped.${tsState}`)];
        const cs = x?.countersigned;
        const csState = slotState(cs);
        const csLine = csState === "partial" ? [
          say("card.stamp.countersigned.by", { signer: cs?.by ?? "" }),
          " \xB7 ",
          ...part("card.stamp.countersigned.partial", cs)
        ] : csState === "filled" && cs?.at ? [
          say("card.stamp.countersigned.by", { signer: cs.by ?? "" }),
          " \xB7 ",
          time(cs.at),
          say("card.stamp.countersigned.clock")
        ] : [say(`card.stamp.countersigned.${csState}`)];
        return el(
          "li",
          {
            class: "cvh-row",
            "data-history": "row",
            "data-deal-state": seal ? "not_as_agreed" : "plain"
          },
          el(
            "div",
            { class: "cvh-row-head" },
            seal ? sealSvg("not_as_agreed") : null,
            el(
              "div",
              null,
              el("p", { class: "cvh-row-title" }, title),
              x?.item !== void 0 ? el("p", { class: "cvh-row-item" }, x.item) : null,
              el(
                "p",
                { class: "cvh-row-line", "data-history": "row-line" },
                line
              ),
              seal ? el("p", { class: "cvh-sr" }, say("card.seal.not_as_agreed")) : null
            )
          ),
          el("p", { class: "cvh-row-detail" }, ...facts),
          termLine !== null ? el("p", { class: "cvh-row-detail" }, termLine) : null,
          d.bothHalves ? el(
            "p",
            { class: "cvh-row-detail", "data-history": "both-halves" },
            say("card.row.both_halves")
          ) : null,
          el(
            "ul",
            { class: "cvh-stamps" },
            stamp("card.stamp.recorded", recState, recLine),
            stamp("card.stamp.time_stamped", tsState, tsLine),
            stamp("card.stamp.countersigned", csState, csLine)
          ),
          x?.receipt !== void 0 ? el(
            "p",
            null,
            el(
              "a",
              {
                class: "cvh-link",
                href: x.receipt,
                "data-history": "receipt"
              },
              say("card.row.receipt")
            )
          ) : null
        );
      });
      rowList = el(
        "section",
        { class: "cvh-rows-block" },
        el("h2", null, say("card.rows.heading")),
        el("ol", { class: "cvh-rows", "data-history": "rows" }, ...items)
      );
    }
    const signed = el(
      "section",
      { class: "cvh-panel", "data-history": "signed" },
      el("h2", null, say("card.signed.heading")),
      el(
        "p",
        null,
        // "Signed by" only when capsulectl verify reported the signature passed;
        // otherwise the page names the signer the card claims.
        // The signature proves the key, not the name: the name stays a label.
        say(
          (proof["producer_signatures"] === "pass" ? "card.signed.by" : "card.signed.claimed") + (owner ? ".owner" : ""),
          { name, key: short(obj.keyId) }
        ),
        ...obj.signedAt !== void 0 ? [" \xB7 ", time(obj.signedAt)] : []
      ),
      // What the signature shows is said only when capsulectl verify reported
      // the signature check passed.
      el(
        "p",
        {
          class: "cvh-note",
          "data-signature": proof["producer_signatures"] ?? "absent"
        },
        say(
          proof["producer_signatures"] === "pass" ? "card.signed.note" : proof["producer_signatures"] === "fail" ? "card.signed.failed" : "card.signed.unchecked"
        )
      )
    );
    const statuses = PROOF_CHECKS.map((c) => proof[c]);
    const lede = failed ? "card.proof.lede.failed" : statuses.some((s) => s === "fail") || proof["witnesses"] === "fail" ? "card.proof.lede.failed" : statuses.every((s) => s === "pass") ? "card.proof.lede.passed" : "card.proof.lede.partial";
    const proofRow = (code, status, label) => el(
      "li",
      {
        class: "cvh-proof-row",
        "data-check": code,
        "data-check-status": status
      },
      el(
        "span",
        { class: "cvh-mark", "data-status": status },
        status === "pass" ? "\u2713" : status === "fail" ? "\u2717" : "\u2013"
      ),
      el(
        "span",
        null,
        el(
          "span",
          { class: "cvh-sr" },
          `${say(`card.proof.status.${status}`)}: `
        ),
        el("span", null, ...label),
        " ",
        el("code", { class: "cvh-code" }, code.replace(/_/gu, " "))
      )
    );
    const witnessStatus = proof["witnesses"] ?? "absent";
    const proofRows = [
      ...PROOF_CHECKS.map(
        (c) => proofRow(c, proof[c] ?? "absent", [say(`card.proof.${c}`)])
      ),
      proofRow(
        "witnesses",
        witnessStatus,
        witnessStatus === "pass" && witnessAt !== void 0 ? [
          say("card.proof.witness.filled", { witness: witnessBy ?? "" }),
          " ",
          time(witnessAt)
        ] : [
          say(
            witnessStatus === "fail" ? "card.proof.witness.failed" : "card.proof.witness.open"
          )
        ]
      )
    ];
    const command = `capsulectl verify --bundle ${file ?? ""}`;
    const proofPanel = el(
      "section",
      { class: "cvh-panel", "data-history": "proof" },
      el("h2", null, say("card.proof.heading")),
      el(
        "p",
        { class: "cvh-note", "data-proof": lede.split(".").pop() ?? "" },
        say(lede)
      ),
      el("ul", { class: "cvh-proof-list" }, ...proofRows),
      el(
        "div",
        { class: "cvh-check", "data-history": "check" },
        el("p", { class: "cvh-check-title" }, say("card.check.title")),
        el("p", { class: "cvh-note" }, say("card.check.download")),
        el(
          "pre",
          { class: "cvh-command" },
          el("code", { "data-verify-command": "download" }, command)
        ),
        el(
          "p",
          { class: "cvh-note", "data-expect": digest ?? "" },
          say("card.check.expect", {
            verdict: verdict ?? "",
            fingerprint: short(digest ?? "")
          })
        )
      )
    );
    const notProven = el(
      "section",
      { class: "cvh-panel cvh-callout", "data-history": "does-not-show" },
      el("h2", null, say("card.not_proven.heading")),
      el(
        "ul",
        null,
        el(
          "li",
          null,
          owner ? say("card.not_proven.true.owner") : say("card.not_proven.true", { name })
        ),
        el(
          "li",
          null,
          owner ? say("card.not_proven.who.owner") : say("card.not_proven.who", { name })
        ),
        el("li", null, say("card.not_proven.outside"))
      )
    );
    const technical = el(
      "details",
      { class: "cvh-technical", "data-history": "technical" },
      el("summary", null, say("card.technical")),
      el(
        "dl",
        null,
        el("dt", null, say("card.technical.card")),
        el("dd", null, el("code", null, obj.derivation)),
        el("dt", null, say("card.technical.key")),
        el("dd", null, el("code", null, obj.keyId)),
        el("dt", null, say("card.technical.digest")),
        el("dd", null, el("code", null, digest ?? "")),
        ...owner && obj.deals !== void 0 ? [
          el("dt", null, say("card.technical.deals")),
          el(
            "dd",
            null,
            ...obj.deals.map((d) => el("code", { class: "cvh-id" }, d.id))
          )
        ] : []
      )
    );
    const footer = el(
      "footer",
      { class: "cvh-footer", "data-history": "footer" },
      el("p", { "data-history": "times" }, say("card.footer.utc")),
      el(
        "p",
        null,
        owner ? say("card.footer.private") : say("card.footer.shared", { name })
      ),
      el(
        "p",
        null,
        say("card.footer.built.before"),
        time(built),
        say("card.footer.built.after")
      )
    );
    const tree = el(
      "section",
      {
        class: "cv-history cvh-card",
        "data-history": "view",
        "data-kind": "deal",
        "data-surface": surface,
        "data-perspective": owner ? "yours" : "theirs",
        "data-verdict": failed ? "failed" : "pass"
      },
      header,
      el("div", { class: "cvh-main" }, hero, rowList, owner ? null : signed),
      el(
        "div",
        { class: "cvh-side" },
        proofPanel,
        notProven,
        owner ? signed : null
      ),
      el("div", { class: "cvh-wide" }, technical, footer)
    );
    return { ok: true, tree };
  }
  var SEAL_SHAPES = {
    body: [
      [
        "path",
        {
          d: "M22 106 C18 70 34 44 60 42 C86 44 102 70 98 106 Z",
          fill: "#7F96A8"
        }
      ],
      ["ellipse", { cx: "60", cy: "88", rx: "24", ry: "19", fill: "#C9D5DE" }],
      ["circle", { cx: "60", cy: "40", r: "26", fill: "#8FA5B6" }]
    ],
    moods: {
      not_as_agreed: [
        [
          "path",
          {
            d: "M45 31 L54 34 M75 31 L66 34",
            stroke: "#13202B",
            "stroke-width": "1.8",
            "stroke-linecap": "round"
          }
        ],
        ["circle", { cx: "50", cy: "39", r: "3.4", fill: "#13202B" }],
        ["circle", { cx: "70", cy: "39", r: "3.4", fill: "#13202B" }],
        ["ellipse", { cx: "60", cy: "49", rx: "9", ry: "6", fill: "#C9D5DE" }],
        [
          "ellipse",
          { cx: "60", cy: "46.5", rx: "3.2", ry: "2.2", fill: "#13202B" }
        ],
        [
          "path",
          {
            d: "M56.5 53 Q60 50.5 63.5 53",
            stroke: "#13202B",
            "stroke-width": "1.6",
            fill: "none",
            "stroke-linecap": "round"
          }
        ],
        ["path", { d: "M76 76 Q92 70 95 82 Q88 86 79 82 Z", fill: "#6E8597" }],
        ["circle", { cx: "96", cy: "78", r: "14", fill: "#D97A1E" }],
        [
          "path",
          {
            d: "M96 71 L96 79",
            stroke: "#FFFFFF",
            "stroke-width": "2.8",
            "stroke-linecap": "round"
          }
        ],
        ["circle", { cx: "96", cy: "84.5", r: "1.7", fill: "#FFFFFF" }]
      ]
    }
  };
  function sealSvg(mood) {
    const shapes = [...SEAL_SHAPES.body, ...SEAL_SHAPES.moods[mood] ?? []];
    return el(
      "svg",
      {
        viewBox: "0 0 120 120",
        width: "48",
        height: "48",
        "aria-hidden": "true",
        focusable: "false",
        class: "cvh-seal-art",
        "data-seal": mood
      },
      ...shapes.map(([tag, attrs]) => el(tag, attrs))
    );
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
    if (isObj(input) && "machine" in input) {
      if (input["view"] !== HISTORY_VIEW)
        r.refuse("input.view", `is not ${HISTORY_VIEW}`);
      return buildCardPage(r, input, overlay);
    }
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
        let unregistered;
        if ("values" in co) {
          if (id === "witness" && status === "not_run")
            unregistered = readUnregistered(
              r,
              co["values"],
              `${path}.values`,
              kind,
              rows
            );
          else {
            const vo = r.object(co["values"], `${path}.values`, [], []);
            if (vo && Object.keys(vo).length > 0)
              r.refuse(
                `${path}.values`,
                "names a placeholder the check's words do not have"
              );
          }
        }
        if (id && checks.some((x) => x.id === id))
          r.refuse(`${path}.id`, "is listed twice");
        if (id && status) checks.push({ id, status, unregistered });
      });
      if (kind === "deal" && !checks.some((x) => x.id === "deal_report"))
        checks.push({ id: "deal_report", status: "not_run" });
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
    const personTitle = kind !== "checkpoint" && reader !== "owner" && audienceKind !== "shared";
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
        kind === "checkpoint" ? say("callout.checkpoints") : picked ? say("callout.deals.picked", { name: name ?? "" }) : personTitle ? say("callout.deals.named", { name: name ?? "" }) : say("callout.deals")
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
            c.unregistered ? say("check.line.unregistered", {
              status: say(`status.${c.status}`),
              name: say(`check.${c.id}`),
              n: String(c.unregistered.n),
              at: minuteOf(c.unregistered.at)
            }) : say("check.line", {
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
  function renderHistoryView(input, container, overlay, options = {}) {
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
    if (built.ok && options.localTime !== false) localTimes(container, overlay);
    return built.ok;
  }
  function localTimes(container, overlay) {
    const times = container.querySelectorAll("time[data-time]");
    if (times.length === 0) return;
    const view = container.ownerDocument.defaultView;
    const I = view?.Intl ?? Intl;
    const fmt = new I.DateTimeFormat(void 0, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
      timeZoneName: "short"
    });
    for (const t of times) {
      const at = Date.parse(t.getAttribute("datetime") ?? "");
      if (!Number.isNaN(at)) t.textContent = fmt.format(new Date(at));
    }
    const note = container.querySelector('[data-history="times"]');
    const words = isObj(overlay) && isObj(overlay["entries"]) ? overlay["entries"]["card.footer.local"] : void 0;
    if (note)
      note.textContent = typeof words === "string" ? words : BASE["card.footer.local"] ?? "";
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
.cvh-card{--cvh-ink:#1b1f27;--cvh-slate:#4d5564;--cvh-line:#d3d7de;--cvh-cream:#f4f5f7;--cvh-navy:#2445a8;--cvh-ok:#17603a;--cvh-bad:#a31d1d}
.cvh-card .cvh-header{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;justify-content:space-between}.cvh-tags{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0}
.cvh-tag{border-radius:999px;padding:2px 10px;font-size:13px;background:#eceef2;color:#3d4452}.cvh-tag[data-audience=private]{background:#fcf1dc;color:#6f4700}
.cvh-button{display:inline-block;border-radius:8px;padding:6px 12px;font-weight:600;text-decoration:none;background:#e7ecfb;color:#1f3c94}
.cvh-card .cvh-hero,.cvh-panel,.cvh-card .cvh-row{background:#fff;border:1px solid var(--cvh-line);border-radius:16px;padding:14px 16px}
.cvh-card .cvh-hero-line{font-size:24px;line-height:1.25}.cvh-card .cvh-row{border-radius:12px}.cvh-card .cvh-row[data-deal-state=not_as_agreed]{border-color:#d97a1e;border-width:2px}
.cvh-row-head{display:flex;gap:12px;align-items:flex-start}.cvh-seal-art{flex:none}.cvh-row-item{font-weight:600}.cvh-row-line{font-size:17px}
.cvh-card .cvh-stamp{border-radius:8px;border:1px dashed var(--cvh-line);padding:5px 10px;font-size:13px;color:var(--cvh-slate)}
.cvh-card .cvh-stamp[data-filled=yes]{border:1px solid var(--cvh-ok);background:#e6f3eb;color:var(--cvh-ok)}.cvh-card .cvh-stamp[data-state=failed]{border:1px solid var(--cvh-bad);background:#fbe9e9;color:var(--cvh-bad)}
.cvh-card .cvh-stamp-name{letter-spacing:.06em;display:block}.cvh-card .cvh-stamp-line{margin:0}
.cvh-panel p{margin:0 0 8px}.cvh-panel ul{margin:0;padding-left:18px}.cvh-proof-list{list-style:none;padding:0!important;display:grid;gap:8px}
.cvh-proof-row{display:grid;grid-template-columns:20px minmax(0,1fr);gap:8px}.cvh-proof-row span span{display:block}.cvh-mark{font-weight:700;text-align:center}
.cvh-mark[data-status=pass]{color:var(--cvh-ok)}.cvh-mark[data-status=fail]{color:var(--cvh-bad)}.cvh-code{display:block;font-size:12px;color:var(--cvh-slate)}
.cvh-sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.cvh-check{background:var(--cvh-cream);border-radius:8px;padding:10px 12px;margin-top:12px}.cvh-check-title{font-weight:700}
.cvh-command{margin:0 0 8px;white-space:pre-wrap;overflow-wrap:anywhere;font:13px ui-monospace,Menlo,monospace}
.cvh-wide{display:grid;gap:12px}.cvh-technical summary{cursor:pointer;font-weight:700;color:var(--cvh-navy)}.cvh-technical dd{margin:0 0 8px;overflow-wrap:anywhere}.cvh-id{display:block}
.cvh-footer{font-size:13px;color:var(--cvh-slate)}.cvh-footer p{margin:0 0 4px}.cvh-link{color:var(--cvh-navy);font-weight:600}
@media screen and (prefers-color-scheme:dark){.cv-history{--cvh-ink:#e8eaee;--cvh-slate:#a3a9b3;--cvh-line:#33373e;--cvh-cream:#22262d;--cvh-navy:#c3d0e8;--cvh-ok:#5fcf90;--cvh-bad:#ff8f84;background:#16181c;color-scheme:dark}.cvh-badge[data-audience=private]{background:#3a2f1a;border-color:#e6b85c}.cvh-card .cvh-hero,.cvh-panel,.cvh-card .cvh-row{background:#1d2026}.cvh-tag,.cvh-button{background:#2a2f38;color:#dfe5f2}.cvh-tag[data-audience=private]{background:#3a2f1a;color:#f2d8a7}.cvh-card .cvh-stamp[data-filled=yes]{background:#173325}.cvh-card .cvh-stamp[data-state=failed]{background:#3a1d1d}}
@media (min-width:900px){.cv-history{grid-template-columns:minmax(0,3fr) minmax(0,2fr)}.cvh-header{grid-column:1/-1}.cvh-wide{grid-column:1/-1}}
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
