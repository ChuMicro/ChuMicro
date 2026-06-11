#!/usr/bin/env python3
"""Render a generic decision page (picker.html) from a JSON spec.

One card per item — id, severity badge, a source chip naming what raised the item,
a plain-words summary, labeled why / fix rows, the evidence in a small mono block —
plus a radio group and a notes box. A sticky bar serializes every choice into a
line-oriented paste-back blob:

    PICKS — <blob_header>
    1 = apply
      note 1: <free text, newlines collapsed>
    2 = skip

A note on an applied item is the user's wording adjustment — there is no separate
"edit" option; the orchestrator honors apply-with-note as apply-with-this-wording.

The page is self-contained (inline CSS + JS) and works from file:// — Copy
selection always works; a Submit button appears only when the page is served
over http (see serve_picker.py, which loops the POST back to the session).
Choices and notes persist in localStorage under the spec's `key`, so a reload
mid-review restores them. A theme button toggles light/dark (default follows
the system).

Spec schema:

    {
      "title": "audit-skill report — git-commit",        // page heading
      "key": "audit-skill:git-commit:20260611T",          // localStorage namespace; change per run
      "blob_header": "audit-skill picks (git-commit)",    // first blob line after "PICKS — "
      "subtitle": "4 findings · 1 high · validated",      // optional metadata line under the title (escaped);
                                                          // use this for counts/status, not intro_html
      "intro_html": "<p>…</p>",                           // optional block above the cards (trusted HTML)
      "sections": [                                       // optional page-top context drop-downs,
        {"title": "What this file does",                  // rendered between intro and the decision
         "html": "<p>…</p>",                              // area (trusted HTML); open: true expands
         "open": true}                                    // the section on load
      ],
      "options": ["apply", "discuss", "skip"],            // page-wide option set
      "default": "skip",                                  // page-wide pre-checked option (omit for none)
      "option_help": {                                    // optional legend, rendered above the cards
        "apply": "make the proposed change (a note adjusts its wording)",
        "discuss": "no change yet — talk it through in chat first",
        "skip": "leave as is"
      },
      "items": [
        {
          "id": "1",                                      // rides back in the blob; unique
          "title": "vague description stem",              // card heading (escaped)
          "badge": "IMPORTANT",                           // optional pill; known severities get colors
          "source": "loader lens — frontmatter contract", // optional chip: what raised this item
          "meta": "effort: small · Foo.bar @ tick",       // optional faint line under the heading
          "summary": "plain-words description…",          // optional paragraph under the heading
          "where": "Foo.bar — ticks_diff(a, b) >= 0",     // optional labeled row, mono — the code
                                                          // location (symbol + quoted expression)
          "why": "consequence in one sentence",           // optional labeled row
          "fix": "the exact proposed change",             // optional labeled row
          "detail": {                                     // optional collapsible block
            "label": "how the code does this",
            "text": "mechanism prose…"
          },
          "warning": "Validator: fix needs review …",     // optional amber callout
          "evidence": "SKILL.md:3 \\"quote\\"",            // optional mono block
          "diff": {                                       // optional old→new block; when the fix is
            "location": "SKILL.md:3",                     // replacement text, emit this INSTEAD of
            "old": "current text",                        // the evidence + fix pair
            "new": "proposed text"
          },
          "body_html": "<p>…</p>",                        // optional extra block (trusted HTML)
          "options": ["high", "medium", "low"],           // optional per-item override; [] makes the card
                                                          // informational: no radios, no blob/tally entry
          "default": "medium",                            // optional per-item override
          "notes": true,                                  // notes box (default: true on decision cards,
                                                          // false on informational ones)
          "tab": "loader",                                // optional: group cards into tabs
          "collapsed": true,                              // optional: fold the card to a strip (title row +
                                                          // radios); a click on the title row expands it.
                                                          // For long pages — items a reader only skims
          "filter": "heartbeat.py"                        // optional facet value; any item carrying one makes
                                                          // the page render a chip row (all · heartbeat.py · …)
                                                          // that narrows the visible cards across every tab
        }
      ],
      "tabs": [                                           // optional tab order; defaults to first appearance
        {"name": "loader", "help": "frontmatter routing — would the loader fire on the right messages"},
        "cold-walk"                                       // bare names are fine; help renders atop the pane
      ]
    }

When any item carries `tab`, the page renders a sticky tab bar with per-tab item
counts; hidden panes stay in the DOM, so the blob, tally, and Reset always cover
every tab. A tab's `help` line names the pane's purpose for a reader who just
clicked in — and makes a per-card `source` chip that merely repeats the tab name
redundant (drop the chip in that case). Items render in spec order within a tab —
ordering (e.g. by severity) is the spec author's job.

When any item carries `filter`, a chip row renders under the tab bar — one chip
per distinct value in first-appearance order, plus "all" — and a click narrows
the visible cards to that value across every tab. Filtered-out cards stay in the
DOM, so the blob, tally, and Reset still cover them. A `collapsed` card folds to
a strip (title row + radios) and expands on a title-row click; a card whose saved
state carries a pick or a note reopens expanded, so a reload never hides work in
progress. The active filter persists alongside the active tab.

body_html and intro_html are written into the page unescaped — the spec author
is the orchestrating session, not an untrusted source.

Usage: render_picker.py <spec.json> [<output-dir>]    (default output dir: the spec's directory)
Stdout: `RENDERED <path>/picker.html` on success.
"""
import html
import json
import os
import sys

BADGE_CLASSES = {
    "critical": "b-critical",
    "important": "b-important",
    "minor": "b-minor",
    "ambiguous": "b-ambiguous",
    "high": "b-critical",
    "medium": "b-important",
    "med": "b-important",
    "low": "b-minor",
}

CSS = """
 :root{color-scheme:light;
  --bg:#f4f6f9; --fg:#1c2230; --faint:#69707e; --card:#ffffff; --border:#dfe4ec;
  --accent:#4f46e5; --blob-bg:#f8fafc; --bar:#ffffffeb; --note-bg:#fbfcfe; --chip:#eef0f6;
  --why:#b45309; --fix:#15803d; --where:#1d4ed8}
 :root[data-theme=dark]{color-scheme:dark;
  --bg:#11141b; --fg:#e3e7f0; --faint:#97a0b3; --card:#1a1f29; --border:#2a3242;
  --accent:#8d97ff; --blob-bg:#11141b; --bar:#1a1f29eb; --note-bg:#161b24; --chip:#232a38;
  --why:#fbbf24; --fix:#4ade80; --where:#93b4ff}
 body{font:16px/1.55 -apple-system,'Segoe UI',sans-serif;background:var(--bg);color:var(--fg);
  margin:0;padding:26px 20px 150px;max-width:920px;margin-inline:auto}
 h1{font-size:24px;font-weight:600;margin:0 44px 6px 0}
 .themebtn{position:fixed;top:14px;right:16px;font:inherit;font-size:13px;padding:6px 12px;border-radius:999px;
  border:1px solid var(--border);background:var(--card);color:var(--fg);cursor:pointer;z-index:10}
 .subtitle{color:var(--faint);font-size:13.5px;margin:0 0 16px}
 .intro{color:var(--faint);font-size:15px;margin-bottom:10px}
 .intro pre{white-space:pre-wrap}
 .legend{font-size:14.5px;color:var(--faint);background:var(--card);border:1px solid var(--border);
  border-radius:10px;padding:9px 14px;margin-bottom:16px}
 details.section{background:var(--card);border:1px solid var(--border);border-radius:12px;
  padding:10px 16px;margin:10px 0}
 details.section>summary{cursor:pointer;font-weight:620;font-size:15px}
 details.section .sbody{margin-top:8px;font-size:14.5px}
 .sbody small{color:var(--faint)}
 .sbody code{font:13px ui-monospace,Menlo,monospace}
 .tabbar{display:flex;gap:5px;flex-wrap:wrap;margin:18px 0 16px;background:color-mix(in srgb,var(--chip) 80%,transparent);
  backdrop-filter:blur(12px) saturate(1.3);-webkit-backdrop-filter:blur(12px) saturate(1.3);border:1px solid var(--border);
  border-radius:13px;padding:5px;width:fit-content;max-width:100%;position:sticky;top:10px;z-index:9}
 .tabbar button{font:inherit;font-size:15px;font-weight:650;padding:9px 18px;border:none;border-radius:9px;
  background:transparent;color:var(--faint);cursor:pointer;transition:color .15s,background .15s}
 .tabbar button:hover{color:var(--fg)}
 .tabbar button.active{background:#4f46e5;color:#fff;box-shadow:0 1px 6px rgba(0,0,0,.2)}
 .tabbar .tcount{font-size:11px;background:var(--chip);color:var(--faint);border-radius:999px;padding:1px 8px;margin-left:7px;font-weight:700}
 .tabbar button.active .tcount{background:color-mix(in srgb,#fff 28%,transparent);color:#fff}
 .tabpane{display:none} .tabpane.active{display:block}
 .tabdesc{color:var(--faint);font-size:14px;margin:2px 2px 10px}
 .filterbar{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 14px}
 .filterbar button{font:inherit;font-size:13px;padding:5px 13px;border-radius:999px;border:1px solid var(--border);
  background:var(--card);color:var(--faint);cursor:pointer}
 .filterbar button:hover{color:var(--fg)}
 .filterbar button.active{border-color:var(--accent);color:var(--accent);font-weight:650}
 .filterbar .fcount{font-size:11px;margin-left:6px;opacity:.75}
 .card.fhidden{display:none}
 .legend b{color:var(--fg);font-weight:620}
 .card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:15px 17px;margin:12px 0}
 .cardhead{display:flex;align-items:baseline;gap:9px;flex-wrap:wrap}
 .chev{display:inline-block;color:var(--faint);font-size:12px;align-self:center;
  transition:transform .15s;transform:rotate(90deg)}
 .card.collapsible>.cardhead{cursor:pointer;user-select:none}
 .card.collapsed{display:flex;align-items:center;gap:16px;flex-wrap:wrap;padding:9px 15px}
 .card.collapsed .chev{transform:rotate(0)}
 .card.collapsed>.cardhead{flex:1 1 auto}
 .card.collapsed>.cardfold,.card.collapsed>.notes{display:none}
 .card.collapsed>.opts{margin:0;flex:0 0 auto}
 .cardid{font-weight:700;color:var(--accent);font-size:17px}
 .cardtitle{font-weight:630}
 .badge{font-size:11px;font-weight:700;letter-spacing:.4px;padding:2px 8px;border-radius:999px;color:#fff;background:#64748b}
 .b-critical{background:#dc2626} .b-important{background:#d97706} .b-minor{background:#64748b} .b-ambiguous{background:#7c3aed}
 .srcchip{font-size:11.5px;color:var(--faint);background:var(--chip);border-radius:999px;padding:2px 9px}
 .cardmeta{margin:6px 0 0;font-size:12.5px;color:var(--faint)}
 .summary{margin:10px 0 0;font-size:15.5px}
 details.detail{margin:10px 0 0}
 details.detail>summary{cursor:pointer;font-size:13.5px;color:var(--accent)}
 details.detail .dtext{margin-top:6px;font-size:14.5px}
 .warning{margin:10px 0 0;background:color-mix(in srgb,#d97706 10%,transparent);
  border:1px solid color-mix(in srgb,#d97706 35%,transparent);border-radius:8px;padding:7px 10px;font-size:14px}
 .field{display:flex;gap:10px;margin:11px 0 0;font-size:15px}
 .flabel{flex:0 0 auto;min-width:30px;text-align:center;font-size:11.5px;font-weight:800;letter-spacing:.6px;
  text-transform:uppercase;border-radius:6px;padding:3px 8px;align-self:flex-start;color:var(--faint);background:var(--chip)}
 .f-why .flabel{color:var(--why);background:color-mix(in srgb,var(--why) 13%,transparent)}
 .f-fix .flabel{color:var(--fix);background:color-mix(in srgb,var(--fix) 13%,transparent)}
 .f-where .flabel{color:var(--where);background:color-mix(in srgb,var(--where) 13%,transparent)}
 .f-where .ftext{font:13.5px/1.7 ui-monospace,Menlo,monospace;padding-top:2px}
 .f-fix{border-left:3px solid color-mix(in srgb,var(--fix) 45%,transparent);padding-left:9px;margin-left:-12px}
 .ftext{flex:1}
 .evidence{margin:9px 0 0;white-space:pre-wrap;background:var(--blob-bg);border:1px solid var(--border);
  border-radius:8px;padding:8px 10px;font:13px/1.5 ui-monospace,Menlo,monospace;color:var(--faint)}
 .diffblock{margin:9px 0 0;border:1px solid var(--border);border-radius:8px;overflow:hidden;
  font:13px/1.55 ui-monospace,Menlo,monospace}
 .diffloc{padding:4px 10px;background:var(--blob-bg);color:var(--faint);font-size:12px;border-bottom:1px solid var(--border)}
 .dline{padding:5px 10px;white-space:pre-wrap}
 .dold{background:color-mix(in srgb,#dc2626 9%,transparent)}
 .dnew{background:color-mix(in srgb,#16a34a 10%,transparent)}
 .cardbody{margin:9px 0 0;font-size:15px}
 .opts{display:flex;gap:16px;flex-wrap:wrap;margin-top:12px}
 .opts label{cursor:pointer;display:flex;align-items:center;gap:6px;font-size:15px}
 .opts input{accent-color:var(--accent)}
 .notes{width:100%;box-sizing:border-box;margin-top:10px;font:14.5px/1.5 inherit;border:1px solid var(--border);
  border-radius:8px;padding:7px 9px;min-height:36px;background:var(--note-bg);color:var(--fg);resize:vertical}
 .selbar{position:fixed;bottom:0;left:0;right:0;background:var(--bar);backdrop-filter:blur(10px);
  border-top:1px solid var(--border);padding:10px 20px;font-size:14px}
 .selbar .row{display:flex;align-items:center;gap:12px;max-width:920px;margin-inline:auto;flex-wrap:wrap}
 .selbar button{font:inherit;padding:7px 16px;border-radius:8px;border:1px solid var(--border);
  background:var(--card);color:var(--fg);cursor:pointer}
 .selbar button.primary{background:#4f46e5;border-color:#4f46e5;color:#fff}
 #count{color:var(--faint)}
 .blobwrap{max-width:920px;margin-inline:auto}
 .blobwrap>summary{font-size:12px;color:var(--faint);cursor:pointer;margin-top:6px}
 .hint{font-size:12px;color:var(--faint);margin:6px 0 0}
 #blob{width:100%;box-sizing:border-box;margin-top:8px;font:12.5px/1.5 ui-monospace,Menlo,monospace;
  border:1px solid var(--border);border-radius:8px;padding:8px;min-height:46px;background:var(--blob-bg);color:var(--fg)}
"""

SCRIPT = """
<script>
(function () {
  var KEY = 'picker:' + (window.SPEC.key || 'x');
  var HEADER = 'PICKS \\u2014 ' + (window.SPEC.blob_header || window.SPEC.key || 'selection');
  var root = document.documentElement;
  var savedTheme = null;
  try { savedTheme = localStorage.getItem('picker:theme'); } catch (e) {}
  var dark = savedTheme ? savedTheme === 'dark' : (window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches);
  function setTheme(d) {
    root.dataset.theme = d ? 'dark' : 'light';
    document.getElementById('themebtn').textContent = d ? 'light mode' : 'dark mode';
    try { localStorage.setItem('picker:theme', d ? 'dark' : 'light'); } catch (e) {}
  }
  function load() { try { return JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) { return {}; } }
  function save(s) { try { localStorage.setItem(KEY, JSON.stringify(s)); } catch (e) {} }
  // informational cards (options: []) carry no radios; they stay out of the blob, tally, and Reset
  var cards = Array.prototype.slice.call(document.querySelectorAll('.card')).filter(function (c) {
    return c.querySelector('input[type=radio]');
  });
  var state = load();
  cards.forEach(function (c) {
    var id = c.dataset.id;
    if (state['p:' + id]) { var r = c.querySelector('input[value="' + state['p:' + id] + '"]'); if (r) r.checked = true; }
    if (state['n:' + id]) { var n = c.querySelector('.notes'); if (n) n.value = state['n:' + id]; }
    // a collapsed card with a saved pick or note reopens expanded — a reload never hides work in progress
    if ((state['p:' + id] || state['n:' + id]) && c.classList.contains('collapsed')) c.classList.remove('collapsed');
  });
  document.querySelectorAll('.card.collapsible > .cardhead').forEach(function (h) {
    h.addEventListener('click', function () { h.parentElement.classList.toggle('collapsed'); });
  });
  function persist() {
    var s = {};
    cards.forEach(function (c) {
      var id = c.dataset.id;
      var r = c.querySelector('input[type=radio]:checked');
      if (r && r.value !== c.dataset.def) s['p:' + id] = r.value;
      var n = c.querySelector('.notes');
      if (n && n.value.trim()) s['n:' + id] = n.value;
    });
    save(s); refresh();
  }
  function buildBlob() {
    var lines = [HEADER];
    cards.forEach(function (c) {
      var id = c.dataset.id;
      var r = c.querySelector('input[type=radio]:checked');
      lines.push(id + ' = ' + (r ? r.value : '(none)'));
      var n = c.querySelector('.notes');
      if (n && n.value.trim()) lines.push('  note ' + id + ': ' + n.value.trim().replace(/\\n/g, ' '));
    });
    return lines.join('\\n');
  }
  function refresh() {
    var unpicked = 0, changed = 0;
    cards.forEach(function (c) {
      var r = c.querySelector('input[type=radio]:checked');
      if (!r) unpicked++;
      else if (r.value !== c.dataset.def) changed++;
    });
    var t = cards.length + ' item(s)';
    if (changed) t += ' \\u00b7 ' + changed + ' changed from default';
    if (unpicked) t += ' \\u00b7 ' + unpicked + ' unpicked';
    document.getElementById('count').textContent = t;
    var b = document.getElementById('blob'); if (b) b.value = buildBlob();
  }
  function copy() {
    var blob = buildBlob();
    var bw = document.querySelector('.blobwrap'); if (bw && !bw.open) bw.open = true;
    var ta = document.getElementById('blob'); ta.value = blob; ta.select();
    var done = function () { var b = document.getElementById('copybtn'); var o = b.textContent; b.textContent = 'copied \\u2713'; setTimeout(function () { b.textContent = o; }, 1400); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(blob).then(done, function () { try { document.execCommand('copy'); done(); } catch (e) {} });
    } else { try { document.execCommand('copy'); done(); } catch (e) {} }
  }
  function submitSel() {
    var sb = document.getElementById('submitbtn'); var o = sb.textContent;
    var flash = function (t) { sb.textContent = t; setTimeout(function () { sb.textContent = o; }, 2200); };
    fetch('/selection', { method: 'POST', body: buildBlob() })
      .then(function (r) { flash(r.ok ? 'submitted \\u2713 (return to the session)' : 'failed: use Copy selection'); })
      .catch(function () { flash('failed: use Copy selection'); });
  }
  setTheme(dark);
  document.getElementById('themebtn').addEventListener('click', function () { setTheme(root.dataset.theme !== 'dark'); });
  document.querySelectorAll('.card input[type=radio]').forEach(function (r) { r.addEventListener('change', persist); });
  document.querySelectorAll('.notes').forEach(function (t) { t.addEventListener('input', persist); });
  document.getElementById('copybtn').addEventListener('click', copy);
  // Submit is the primary action when the page is served; on a file:// page it stays
  // hidden and Copy inherits the primary styling as the only hand-back path.
  var sb = document.getElementById('submitbtn');
  if (location.protocol === 'http:' || location.protocol === 'https:') {
    sb.hidden = false;
    sb.addEventListener('click', submitSel);
  } else {
    document.getElementById('copybtn').classList.add('primary');
  }
  document.getElementById('resetbtn').addEventListener('click', function () {
    cards.forEach(function (c) {
      c.querySelectorAll('input[type=radio]').forEach(function (r) { r.checked = (r.value === c.dataset.def); });
      var n = c.querySelector('.notes'); if (n) n.value = '';
    });
    persist();
  });
  // tab bar (absent on a flat page); hidden panes stay in the DOM, so the blob and tally cover every tab.
  // The active tab persists per page key, so a reload (including a rerender-on-refresh) restores it.
  var tabs = document.querySelectorAll('.tabbar button');
  var TABKEY = KEY + ':tab';
  function activate(t) {
    tabs.forEach(function (x) { x.classList.remove('active'); });
    document.querySelectorAll('.tabpane').forEach(function (p) { p.classList.remove('active'); });
    t.classList.add('active');
    var pane = document.getElementById('pane-' + t.dataset.pane);
    if (pane) pane.classList.add('active');
  }
  tabs.forEach(function (t) {
    t.addEventListener('click', function () {
      activate(t);
      try { localStorage.setItem(TABKEY, t.dataset.pane); } catch (e) {}
    });
  });
  var savedTab = null;
  try { savedTab = localStorage.getItem(TABKEY); } catch (e) {}
  if (savedTab !== null) {
    var saved = Array.prototype.filter.call(tabs, function (t) { return t.dataset.pane === savedTab; })[0];
    if (saved) activate(saved);
  }
  // filter chips (absent unless items carry `filter`); filtered-out cards stay in the
  // DOM, so the blob and tally cover them. The active chip persists like the active tab.
  var chips = document.querySelectorAll('.filterbar button');
  var FILTERKEY = KEY + ':filter';
  function applyFilter(value) {
    chips.forEach(function (b) { b.classList.toggle('active', b.dataset.filter === value); });
    document.querySelectorAll('.card[data-filter]').forEach(function (c) {
      c.classList.toggle('fhidden', value !== '' && c.dataset.filter !== value);
    });
  }
  chips.forEach(function (b) {
    b.addEventListener('click', function () {
      applyFilter(b.dataset.filter);
      try { localStorage.setItem(FILTERKEY, b.dataset.filter); } catch (e) {}
    });
  });
  if (chips.length) {
    var savedFilter = null;
    try { savedFilter = localStorage.getItem(FILTERKEY); } catch (e) {}
    if (savedFilter) {
      var known = Array.prototype.some.call(chips, function (b) { return b.dataset.filter === savedFilter; });
      if (known) applyFilter(savedFilter);
    }
  }
  refresh();
})();
</script>
"""


def card_html(item, page_options, page_default):
    item_id = str(item["id"])
    options = item.get("options", page_options)
    default = item.get("default", page_default) if options else None
    badge = ""
    if item.get("badge"):
        badge_class = BADGE_CLASSES.get(str(item["badge"]).lower(), "")
        badge = f'<span class="badge {badge_class}">{html.escape(str(item["badge"]))}</span>'
    source = f'<span class="srcchip">{html.escape(item["source"])}</span>' if item.get("source") else ""
    meta = f'<div class="cardmeta">{html.escape(item["meta"])}</div>' if item.get("meta") else ""
    summary = f'<p class="summary">{html.escape(item["summary"])}</p>' if item.get("summary") else ""
    fields = "".join(
        f'<div class="field f-{key}"><span class="flabel">{label}</span><span class="ftext">{html.escape(item[key])}</span></div>'
        for key, label in (("where", "where"), ("why", "why"), ("fix", "fix"))
        if item.get(key)
    )
    evidence = f'<div class="evidence">{html.escape(item["evidence"])}</div>' if item.get("evidence") else ""
    diff_html = ""
    if item.get("diff"):
        diff = item["diff"]
        location = f'<div class="diffloc">{html.escape(diff["location"])}</div>' if diff.get("location") else ""
        old_line = f'<div class="dline dold">− {html.escape(diff["old"])}</div>' if diff.get("old") else ""
        new_line = f'<div class="dline dnew">+ {html.escape(diff["new"])}</div>' if diff.get("new") else ""
        diff_html = f'<div class="diffblock">{location}{old_line}{new_line}</div>'
    detail = ""
    if item.get("detail"):
        detail = (
            f'<details class="detail"><summary>{html.escape(item["detail"].get("label", "more"))}</summary>'
            f'<div class="dtext">{html.escape(item["detail"].get("text", ""))}</div></details>'
        )
    warning = f'<div class="warning">{html.escape(item["warning"])}</div>' if item.get("warning") else ""
    body = f'<div class="cardbody">{item["body_html"]}</div>' if item.get("body_html") else ""
    opts = ""
    if options:
        radios = "".join(
            f'<label><input type="radio" name="pick:{html.escape(item_id)}" value="{html.escape(option)}"'
            f'{" checked" if option == default else ""}> {html.escape(option)}</label>'
            for option in options
        )
        opts = f'<div class="opts">{radios}</div>'
    notes = (
        f'<textarea class="notes" placeholder="notes on {html.escape(item_id)} (on an apply, this adjusts the wording)…"></textarea>'
        if item.get("notes", bool(options))
        else ""
    )
    collapsible = bool(item.get("collapsed"))
    card_classes = "card collapsible collapsed" if collapsible else "card"
    chevron = '<span class="chev">▸</span>' if collapsible else ""
    filter_attr = f' data-filter="{html.escape(item["filter"])}"' if item.get("filter") else ""
    return (
        f'<div class="{card_classes}" data-id="{html.escape(item_id)}" data-def="{html.escape(default or "")}"{filter_attr}>'
        f'<div class="cardhead">{chevron}<span class="cardid">{html.escape(item_id)}</span>{badge}{source}'
        f'<span class="cardtitle">{html.escape(item.get("title", ""))}</span></div>'
        f'<div class="cardfold">{meta}{summary}{fields}{evidence}{diff_html}{detail}{warning}{body}</div>'
        f"{opts}{notes}</div>"
    )


def legend_html(option_help):
    if not option_help:
        return ""
    parts = " &nbsp;·&nbsp; ".join(
        f"<b>{html.escape(option)}</b> — {html.escape(meaning)}" for option, meaning in option_help.items()
    )
    return f'<div class="legend">{parts}</div>'


def main():
    spec_path = os.path.abspath(sys.argv[1])
    with open(spec_path) as handle:
        spec = json.load(handle)
    output_dir = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else os.path.dirname(spec_path)

    page_options = spec.get("options", ["apply", "discuss", "skip"])
    page_default = spec.get("default")

    filter_values = []
    for item in spec["items"]:
        value = item.get("filter")
        if value and value not in filter_values:
            filter_values.append(value)
    filterbar = ""
    if filter_values:
        counts = {value: 0 for value in filter_values}
        for item in spec["items"]:
            if item.get("filter") in counts:
                counts[item["filter"]] += 1
        chips = [f'<button class="active" data-filter="">all<span class="fcount">{len(spec["items"])}</span></button>'] + [
            f'<button data-filter="{html.escape(value)}">{html.escape(value)}<span class="fcount">{counts[value]}</span></button>'
            for value in filter_values
        ]
        filterbar = f'<div class="filterbar">{"".join(chips)}</div>\n'

    if any(item.get("tab") for item in spec["items"]):
        # spec["tabs"] entries are names or {name, help}; help renders at the top of the pane
        tab_order = []
        tab_help = {}
        for entry in spec.get("tabs", []):
            if isinstance(entry, dict):
                tab_order.append(entry["name"])
                if entry.get("help"):
                    tab_help[entry["name"]] = entry["help"]
            else:
                tab_order.append(entry)
        for item in spec["items"]:
            tab_name = item.get("tab", "general")
            if tab_name not in tab_order:
                tab_order.append(tab_name)
        groups = {tab_name: [] for tab_name in tab_order}
        for item in spec["items"]:
            groups[item.get("tab", "general")].append(item)
        buttons = []
        panes = []
        for index, tab_name in enumerate(tab_order):
            if not groups[tab_name]:
                continue
            active = " active" if not buttons else ""
            buttons.append(
                f'<button class="tab{active}" data-pane="{index}">{html.escape(tab_name)}'
                f'<span class="tcount">{len(groups[tab_name])}</span></button>'
            )
            description = f'<p class="tabdesc">{html.escape(tab_help[tab_name])}</p>' if tab_name in tab_help else ""
            pane_cards = "\n".join(card_html(item, page_options, page_default) for item in groups[tab_name])
            panes.append(f'<div class="tabpane{active}" id="pane-{index}">{description}{pane_cards}</div>')
        cards = f'<div class="tabbar">{"".join(buttons)}</div>\n{filterbar}' + "\n".join(panes)
    else:
        cards = filterbar + "\n".join(card_html(item, page_options, page_default) for item in spec["items"])

    subtitle = f'<p class="subtitle">{html.escape(spec["subtitle"])}</p>' if spec.get("subtitle") else ""
    intro = f'<div class="intro">{spec["intro_html"]}</div>' if spec.get("intro_html") else ""
    sections = "".join(
        f'<details class="section"{" open" if section.get("open") else ""}>'
        f'<summary>{html.escape(section["title"])}</summary>'
        f'<div class="sbody">{section["html"]}</div></details>'
        for section in spec.get("sections", [])
    )
    legend = legend_html(spec.get("option_help"))
    client_spec = json.dumps({"key": spec.get("key", ""), "blob_header": spec.get("blob_header", "")})

    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(spec.get("title", "decision page"))}</title>
<style>{CSS}</style></head>
<body>
<button class="themebtn" id="themebtn">dark mode</button>
<h1>{html.escape(spec.get("title", "decision page"))}</h1>
{subtitle}
{intro}
{legend}
{sections}
{cards}
<div class="selbar">
 <div class="row">
  <span id="count"></span>
  <button class="primary" id="submitbtn" hidden>Submit to session</button>
  <button id="copybtn">Copy selection</button>
  <button id="resetbtn">Reset</button>
 </div>
 <details class="blobwrap"><summary>selection blob + how to hand it back</summary>
 <textarea id="blob" readonly></textarea>
 <p class="hint">Submit sends this blob straight to the waiting session. No server? Copy it and paste it into the chat instead — same effect.</p>
 </details>
</div>
<script>window.SPEC = {client_spec};</script>
{SCRIPT}
</body></html>
"""
    output_path = os.path.join(output_dir, "picker.html")
    with open(output_path, "w") as handle:
        handle.write(page)
    print(f"RENDERED {output_path}", flush=True)


if __name__ == "__main__":
    main()
