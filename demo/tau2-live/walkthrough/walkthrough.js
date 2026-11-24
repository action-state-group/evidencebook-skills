// SPDX-License-Identifier: Apache-2.0
// Judge walkthrough: plays one recorded live case (data.js, written by
// export_walkthrough.py) step by step. Every name, id, verdict and digest shown
// comes from that file; the page computes nothing and checks nothing itself.
(function () {
  "use strict";
  var D = window.TAU2_CASE;
  var $ = function (id) { return document.getElementById(id); };
  if (!D) { $("nodata").hidden = false; return; }

  var short = function (s) { return s ? String(s).slice(0, 12) : "none"; };
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function kv(pairs) {
    var box = el("div", "kv");
    pairs.forEach(function (p) { box.appendChild(el("span", null, p[0])); var v = el("span"); v.appendChild(el("code", null, p[1])); box.appendChild(v); });
    return box;
  }

  // ---- the stage: cumulative state rebuilt from step 0 to the current step ----
  var stage;
  function reset() {
    stage = { books: [], strips: {}, talk: [], spans: [], stamped: {}, detail: null, newest: {} };
  }
  function book(id, title, sub) { stage.books.push({ id: id, title: title, sub: sub }); stage.strips[id] = []; }
  function strip(bookId, cls, label, id) { stage.strips[bookId].push({ cls: cls, label: label, id: id }); }
  function span(match) {
    D.spans.filter(match).forEach(function (s) { if (stage.spans.indexOf(s) < 0) stage.spans.push(s); });
  }

  var air = D.case.book;
  var calls = D.tool_calls || [];
  var writes = calls.filter(function (c) { return c.perform; });
  var turnSpans = function (n, who) { return function (s) { return s.name === "turn " + n + " " + who; }; };

  // ---- the steps ----
  var steps = [];
  function step(chip, title, text, apply, key) { steps.push({ chip: chip, title: title, text: text, apply: apply, key: !!key }); }

  step("Case", "A live support case", "Two agents talk in real time: a Goose airline agent with the tau2 airline policy and tools, and a simulated customer given one tau2 scenario. Nothing is replayed from a benchmark transcript.", function () {
    stage.detail = kv([["scenario", D.case.reason_for_call.split("\n")[0]], ["tau2 task", D.case.task_id], ["opened", D.case.opened_at]]);
  });
  step("Window", "The airline's deal store, split into windows", "The airline keeps one deal store. capsulectl splits its journal into calendar windows in UTC, and each case's deal book stays whole in the window its agreement is sealed in, even if the case runs past the window's end, and `deal window list` says which window that is. The conversation, the check and the citation are journal records, each in the window it was sealed in.", function () {
    book(air, air, "the airline's deal store; this case is placed in window " + (D.case.window || "?"));
    stage.detail = kv([["store", air], ["window", (D.case.window || "?") + " (the store's period is chosen when it is created: day, week, month, quarter or year)"]]);
  }, true);
  step("Deal", "One case, one deal", "The airline offers to a customer who keeps no signed records of its own and agrees alone. The deal's rows are the three checks of the tau2 airline rubric, owed by the airline.", function () {
    strip(air, "journal", "offer (to: null)", D.records.offer);
    strip(air, "", "agreement: deal book opens", D.records.agreement);
    stage.detail = kv([["deal", D.case.deal_id], ["rows", "policy_compliance, task_resolution, grounded_communication"], ["owed by", "the airline"], ["adjudicator", "the evaluator's own key"]]);
  }, true);

  var turns = D.turns || [];
  var n = 0;
  turns.forEach(function (t, i) {
    var isUser = t.role === "user";
    if (isUser) n += 1;
    var turnNo = n;
    var nextAirSpan = D.spans.filter(turnSpans(turnNo, "airline agent"))[0];
    var spanOf = {};
    D.spans.forEach(function (s) { spanOf[s.span_id] = s; });
    var turnCalls = (!isUser && nextAirSpan) ? calls.filter(function (c) {
      var s = spanOf[c.span_id];
      return s && s.parent_id === nextAirSpan.span_id;
    }) : [];
    var isConfirm = isUser && writes.some(function (w) { return w.confirmation === t.capsule_id; });
    var label = isUser ? "Customer" : "Agent";
    step(label + " " + (isUser ? turnNo : (turnNo || "")), isUser ? "The customer says" : "The airline agent says",
      isConfirm ? "The customer's explicit \"yes\". It is sealed as a received message; the airline's policy check will read it. It is not an approval: an approval is the airline's own principal's word."
        : (isUser ? "Each turn is sealed in the airline's journal as it is said, and its OTel span carries the record's capsule id."
          : (turnCalls.length ? "The agent calls the airline's tools during its turn. Each call is a span under this turn's span." : "The agent's reply is sealed the same way.")),
      function () {
        turnCalls.forEach(function (c) {
          stage.talk.push({ tool: c });
          if (c.perform) {
            strip(air, "check", "policy check reads " + short(c.confirmation), c.check);
            strip(air, "act", "perform " + c.tool, c.perform);
            stage.stamped[c.perform] = true;
          }
          span(function (s) { return s.span_id === c.span_id; });
        });
        stage.talk.push({ msg: t, confirm: isConfirm });
        strip(air, "journal", "message from " + (isUser ? "customer" : "agent"), t.capsule_id);
        span(function (s) { return s.capsule_id && s.capsule_id === t.capsule_id; });
        var w = turnCalls.filter(function (c) { return c.perform; })[0];
        stage.detail = w ? kv([["tool", w.tool], ["confirmed by", short(w.confirmation)], ["policy check", short(w.check)], ["perform", short(w.perform)], ["span", w.span_id], ["trace", short(w.trace_id)]])
          : kv([["sealed as", short(t.capsule_id)], ["at", t.at]]);
      }, isConfirm || turnCalls.some(function (c) { return c.perform; }));
  });

  step("Checkpoint", "The book is checkpointed", "A report rests on a checkpoint of the book: the airline signs the book's head. A record changed later shows to anyone who already holds this checkpoint. No witness co-signs it here, so it is the airline's own word.", function () {
    strip(air, "", "checkpoint", null);
    stage.detail = kv([["book", air], ["covers", "every record above"]]);
    span(function (s) { return s.service === "tau2-roleplay" && !s.parent_id; });
  });
  if (D.evaluation) {
    step("Evaluator", "The evaluator signs its own verdict", "An evaluator judges the case on the rubric and signs its verdict with its own key, in its own book. The airline's journal cites it; the airline does not restate it as its own. In this demo the operator runs the evaluator, like both agents, so it is not independent.", function () {
      book("evaluator", "tau2 evaluator", "the evaluator's own book");
      strip("evaluator", "verdict", "verdict on " + short(D.case.deal_id), D.evaluation.evaluation_capsule_id);
      strip(air, "journal", "cites the evaluator's verdict", D.evaluation.cited_by);
      var pairs = Object.keys(D.evaluation.checks).map(function (k) { return [k, D.evaluation.checks[k]]; });
      pairs.push(["judge", D.evaluation.judge_model_id]);
      stage.detail = kv(pairs);
    }, true);
  }
  if (D.report) {
    step("Disclosure", "Two disclosure levels of one report", "The airline seals its report and writes two Evidence Bundles of it: its own full view, and the copy for the judge with the rows withheld. Both carry the same records: the agreement and the acts the report cites. The rows read not_due because they fall due a week after the case opens; the evaluator's verdict is cited, not applied to them.", function () {
      stage.detail = levels(false);
    }, true);
    step("Verify", "Both copies verify", "capsulectl deal verify checks each bundle on its own: signatures, record identity, the checkpoint, what each copy discloses, and the x-deal-v1 report rule. VALID covers the sealed report and the records in the bundle. The conversation, the customer's yes, the policy check and the verdict sit in the books, outside these bundles. VALID does not say the airline handled the case well.", function () {
      stage.detail = levels(true);
    }, true);
  }
  step("Not here", "What this demo does not show", "Kept honest on purpose.", function () {
    var ul = el("ul");
    ["A report over a range of windows with its coverage check. capsulectl can build one (deal window chain, book report derive --chain); this demo reports on one case.",
      "A person's own signature on each act: every act shows person_signature: missing (agent-action-capsule#627).",
      "A witness: checkpoints and as_of are the airline's own word.",
      "Proof that the database change matches the act: the records show the gate's order, not its effect.",
      "A person as the customer: the customer is a model, signs nothing, and its words are as the airline's agent recorded them.",
      "An independent evaluator: the demo operator runs the evaluator and both agents. The default judge is the operator's Goose model, not the rubric's pinned judge.",
      "Core capsulectl verify alone: it does not run the x-deal-v1 report rule and says so in a \"Not checked here\" note; capsulectl deal verify runs it.",
      "Reading OTel back into books: spans here carry references only.",
      "A counterparty copy: this customer keeps no signed records of its own."].forEach(function (s) { ul.appendChild(el("li", null, s)); });
    stage.detail = ul;
  });

  function levels(showVerify) {
    var box = el("div", "levels");
    ["keep", "adjudicator"].forEach(function (lv) {
      var b = D.report.bundles[lv];
      if (!b) return;
      var c = el("div", "level");
      c.appendChild(el("h4", null, lv === "keep" ? "The airline's own view" : "The judge's copy"));
      c.appendChild(el("div", null, "audience: " + b.audience));
      c.appendChild(el("div", null, b.rows.length ? ("rows: " + b.rows.map(function (r) { return r.row + " " + (r.status || ""); }).join(", ")) : ("rows: " + (b.rows_state || "withheld"))));
      if (showVerify) {
        c.appendChild(el("div", b.verify === "VALID" ? "ok" : "bad", "verify: " + b.verify));
        c.appendChild(el("div", null, "digest " + short(b.bundle_digest)));
      }
      box.appendChild(c);
    });
    return box;
  }

  // ---- render ----
  var cur = 0, timer = null;
  function render() {
    reset();
    for (var i = 0; i <= cur; i++) steps[i].apply();
    var s = steps[cur];
    $("stitle").textContent = s.title;
    $("stext").textContent = s.text;
    $("count").textContent = (cur + 1) + " / " + steps.length;
    var det = $("detail"); det.textContent = ""; if (stage.detail) det.appendChild(stage.detail);
    var books = $("books"); books.textContent = "";
    stage.books.forEach(function (b) {
      var box = el("div", "book");
      var h = el("h3", null, b.title + " "); h.appendChild(el("small", null, b.sub)); box.appendChild(h);
      stage.strips[b.id].forEach(function (st, j) {
        var row = el("div", "strip " + st.cls + (j === stage.strips[b.id].length - 1 ? " new" : ""));
        row.appendChild(el("b", null, st.label)); if (st.id) row.appendChild(el("code", null, short(st.id)));
        box.appendChild(row);
      });
      books.appendChild(box);
    });
    var talk = $("talk"); talk.textContent = "";
    stage.talk.forEach(function (item, j) {
      var last = j === stage.talk.length - 1 ? " new" : "";
      if (item.msg) {
        var m = el("div", "msg " + item.msg.role + (item.confirm ? " confirm" : "") + last, item.msg.content);
        m.appendChild(el("span", "seal", "sealed " + short(item.msg.capsule_id)));
        talk.appendChild(m);
      } else {
        var c = item.tool;
        var cls = c.kind === "write" ? (c.perform ? " write" : " refused") : "";
        var t = el("div", "tool" + cls + last, "tool " + c.tool + " " + JSON.stringify(c.arguments) + (c.perform ? "  ->  perform " + short(c.perform) : (c.gate ? "  ->  " + c.gate : "")));
        talk.appendChild(t);
      }
    });
    var pane = talk.parentNode, lane = $("spans").parentNode;
    requestAnimationFrame(function () { pane.scrollTop = pane.scrollHeight; lane.scrollTop = lane.scrollHeight; });
    renderSpans();
    var tl = $("timeline");
    Array.prototype.forEach.call(tl.children, function (chip, j) { chip.className = "chip" + (steps[j].key ? " key" : "") + (j < cur ? " done" : j === cur ? " cur" : ""); });
  }
  function renderSpans() {
    var box = $("spans"); box.textContent = "";
    if (!D.spans.length) return;
    $("traceid").textContent = D.spans[0].trace_id;
    var t0 = Math.min.apply(null, D.spans.map(function (s) { return Date.parse(s.start); }));
    var t1 = Math.max.apply(null, D.spans.map(function (s) { return Date.parse(s.end); }));
    var w = Math.max(1, t1 - t0);
    stage.spans.slice().sort(function (a, b) { return Date.parse(a.start) - Date.parse(b.start); }).forEach(function (s) {
      var row = el("div", "span" + (s.service === "airline-tools" ? " s-tool" : "") + (!s.parent_id ? " root" : "") + (s.capsule_id && stage.stamped[s.capsule_id] ? " stamped" : ""));
      var bar = el("div", "barx", s.name + (s.capsule_id ? "  aac.capsule_id=" + short(s.capsule_id) : ""));
      var left = 100 * (Date.parse(s.start) - t0) / w, width = Math.max(0.5, 100 * (Date.parse(s.end) - Date.parse(s.start)) / w);
      // A bar late in the trace grows leftward from its end, so its label stays on screen.
      if (left > 55) bar.style.right = Math.max(0, 100 - left - width) + "%"; else bar.style.left = left + "%";
      bar.style.minWidth = width + "%";
      row.appendChild(bar); box.appendChild(row);
    });
  }
  function go(i) { cur = Math.max(0, Math.min(steps.length - 1, i)); render(); }
  function play() {
    if (timer) { clearInterval(timer); timer = null; $("play").textContent = "Play"; return; }
    $("play").textContent = "Pause";
    timer = setInterval(function () { if (cur >= steps.length - 1) { play(); return; } go(cur + 1); }, 2600);
  }
  steps.forEach(function (s, j) {
    var b = el("button", "chip", s.chip); b.type = "button";
    b.addEventListener("click", function () { go(j); });
    $("timeline").appendChild(b);
  });
  $("restart").addEventListener("click", function () { go(0); });
  $("prev").addEventListener("click", function () { go(cur - 1); });
  $("next").addEventListener("click", function () { go(cur + 1); });
  $("play").addEventListener("click", play);
  document.addEventListener("keydown", function (e) {
    if (e.key === "ArrowRight") go(cur + 1);
    else if (e.key === "ArrowLeft") go(cur - 1);
    else if (e.key === "Home") go(0);
    else if (e.key === " ") { e.preventDefault(); play(); }
  });
  var m = /step=(\d+)/.exec(location.hash || "");
  if (m) cur = Math.min(steps.length - 1, parseInt(m[1], 10));
  render();
})();
