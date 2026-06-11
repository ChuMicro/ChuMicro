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
The Submit button carries a live summary of the picks that differ from their
defaults ("Submit — 3 apply · 1 discuss"), so the moment of commitment shows
what is being committed.

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
      "expand_on": ["discuss"],                           // optional: picking one of these options expands
                                                          // the card and focuses its notes box — for options
                                                          // whose substance lives in the note (a discussion
                                                          // opener, a wording adjustment)
      "option_help": {                                    // optional legend, rendered above the cards AND as
        "apply": "make the proposed change (a note adjusts its wording)",   // hover text on every card's
        "discuss": "no change yet — talk it through in chat first",         // radio labels, so the meaning
        "skip": "leave as is"                                               // travels with each decision
      },
      "items": [
        {
          "id": "1",                                      // rides back in the blob; unique
          "title": "vague description stem",              // card heading (escaped)
          "badge": "IMPORTANT",                           // optional pill; known severities get colors
          "source": "loader lens — frontmatter contract", // optional chip: what raised this item
          "meta": "effort: small · Foo.bar @ tick",       // optional faint line under the heading
          "summary": "plain-words description…",          // optional paragraph under the heading
          "where": {"place": "heartbeat.py · Foo.bar",    // optional labeled row: place renders as text,
                    "code": "ticks_diff(a, b) >= 0"},     // the quoted code on its own mono line under it
                                                          // (a bare string renders as one mono line)
          "why": "consequence in one sentence",           // optional labeled row
          "fix": "the exact proposed change",             // optional labeled row
          "detail": {                                     // optional collapsible block
            "label": "how the code does this",
            "text": "mechanism prose…"
          },
          "warning": "Validator: fix needs review …",     // optional amber callout; also puts an amber
                                                          // ⚠ in the card head (hover shows the text),
                                                          // so even a folded strip signals "go deeper"
          "evidence": "SKILL.md:3 \\"quote\\"",            // optional mono block
          "diff": {                                       // optional old→new block; when the fix is
            "location": "SKILL.md:3",                     // replacement text, emit this INSTEAD of
            "old": "current text",                        // the evidence + fix pair. Multiline old/new
            "new": "proposed text"                        // render one −/+ marked line per source line
          },
          "body_html": "<p>…</p>",                        // optional extra block (trusted HTML)
          "options": ["high", "medium", "low"],           // optional per-item override; [] makes the card
                                                          // informational: no radios, no blob/tally entry
          "default": "medium",                            // optional per-item override
          "notes": true,                                  // notes box (default: true on decision cards,
                                                          // false on informational ones)
          "collapsed": true,                              // optional: start the card folded to a strip (title
                                                          // row + radios + diff if present). Every card
                                                          // folds/expands on a title-row click; this sets the
                                                          // initial state. For long pages a reader skims
          "facets": {"severity": "high",                  // optional facet values, one per facet group the
                     "angle": "trap",                     // page defines below; the facet bar narrows the
                     "file": "heartbeat.py"}              // list to cards matching every selected group
        }
      ],
      "facets": [                                         // optional facet-bar definition: one chip row per
        {"key": "severity",                               // group, in this order. values: explicit chip order
         "values": ["high", "med", "low"]},               // (others append by first appearance); label:
        {"key": "angle",                                  // row caption (defaults to key); help: hover text
         "help": {"trap": "correctness lens — …"}}        // per chip value
      ],
      "group_by": ["angle", "file"]                       // optional grouping dimensions (facet keys); adds a
                                                          // "group" row to the facet bar — picking one reorders
                                                          // the list under sticky per-value headers, "none"
                                                          // restores spec order
    }

The facet bar is the page's one narrowing mechanism — no tabs (a finding list is
one dataset; tabs hide most of it and tax cross-tab comparison). Chips toggle:
multi-select within a group reads as OR, groups combine as AND, an empty group
means no narrowing. A card missing a value for a selected group is narrowed out.
Hidden cards stay in the DOM, so the blob, tally, and Reset always cover them.
A chip's live count ignores its own group's selection (standard faceted search),
so within-group numbers stay stable while you multi-select; a non-active chip
whose count drops to zero dims and stops responding, so a dead-end combination
is visible before the click, and a selection that empties the whole list shows a
"nothing matches" state with its own clear button; a clear-filters button
appears in the bar while any chip is active. The `group_by` row reorders the list
under sticky per-value headers without hiding anything — narrowing and grouping
compose. Selections and the grouping choice persist per page key. Items render
in spec order — ordering (e.g. by severity) is the spec author's job.

When at least one decision card exists, the bar gains a virtual `picked` row
(suppress with "picked_facet": false) whose chips track the live radio values —
narrow to your apply set for a final look before submitting. `picked` is a
reserved facet key. Every card carries id card-<id, non-alphanumerics dashed>,
so trusted section or intro HTML can deep-link to a card (#card-heartbeat-3);
navigating to a folded card unfolds it, and the target card flashes an accent
ring that fades out.

Every card folds to a strip — title row, radios, and the diff when one exists —
on a title-row click; `collapsed: true` sets the initial state, and fold changes
persist in localStorage like picks and notes do. Picking an option listed in
`expand_on` opens the card and focuses its notes box, for options whose
substance lives in the note. Reset returns the page to its rendered defaults —
picks to the default option, notes cleared, cards and page-top sections back to
their spec fold state; only the active tab and the active chip (navigation, not
decision state) survive it.

body_html and intro_html are written into the page unescaped — the spec author
is the orchestrating session, not an untrusted source.

Usage: render_picker.py <spec.json> [<output-dir>]    (default output dir: the spec's directory)
Stdout: `RENDERED <path>/picker.html` on success.
"""
import html
import json
import os
import re
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
 .facetbar{display:flex;flex-direction:column;gap:7px;margin:18px 0 16px;position:sticky;top:10px;z-index:9;
  background:color-mix(in srgb,var(--card) 90%,transparent);backdrop-filter:blur(12px) saturate(1.3);
  -webkit-backdrop-filter:blur(12px) saturate(1.3);border:1px solid var(--border);border-radius:13px;padding:10px 14px}
 .fgroup{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
 .fglabel{font-size:11px;font-weight:700;letter-spacing:.5px;text-transform:uppercase;color:var(--faint);min-width:64px}
 .fgroup button{font:inherit;font-size:13px;padding:4px 13px;border-radius:999px;border:1px solid var(--border);
  background:var(--card);color:var(--faint);cursor:pointer}
 .fgroup button:hover{color:var(--fg)}
 .fgroup button.active{border-color:#4f46e5;background:#4f46e5;color:#fff;font-weight:650}
 .fgroup button.dead{opacity:.35;pointer-events:none}
 .fgroup .fcount{font-size:11px;margin-left:6px;opacity:.8}
 .nomatch{background:var(--card);border:1px dashed var(--border);border-radius:12px;padding:18px;
  margin:12px 0;color:var(--faint);font-size:15px;text-align:center}
 .nomatch button{font:inherit;font-size:13px;border:none;background:none;color:var(--accent);
  cursor:pointer;padding:0 2px}
 .facetclear{align-self:flex-start;font:inherit;font-size:12px;border:none;background:none;
  color:var(--accent);cursor:pointer;padding:0 2px}
 .ghead{position:sticky;z-index:8;font-size:12.5px;font-weight:700;letter-spacing:.5px;text-transform:uppercase;
  color:var(--faint);background:var(--bg);padding:10px 2px 4px;margin-top:14px}
 .card.fhidden,.card.collapsed.fhidden{display:none}
 .legend b{color:var(--fg);font-weight:620}
 .card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:15px 17px;margin:12px 0;
  scroll-margin-top:var(--anchor-clear,40px)}
 .card.flash{animation:cardflash 1.8s ease-out}
 @keyframes cardflash{0%,30%{border-color:var(--accent);box-shadow:0 0 0 2px var(--accent)}
  100%{border-color:var(--border);box-shadow:0 0 0 0 transparent}}
 .cardhead{display:flex;align-items:baseline;gap:9px;flex-wrap:wrap}
 .chev{display:inline-block;color:var(--faint);font-size:12px;align-self:center;
  transition:transform .15s;transform:rotate(90deg)}
 .card.collapsible>.cardhead{cursor:pointer;user-select:none}
 .card.collapsed{display:flex;align-items:center;gap:12px 16px;flex-wrap:wrap;padding:9px 15px}
 .card.collapsed .chev{transform:rotate(0)}
 .card.collapsed>.cardhead{flex:1 1 auto;order:1}
 .card.collapsed>.cardfold,.card.collapsed>.notes{display:none}
 .card.collapsed>.opts{margin:0;flex:0 0 auto;order:2}
 .card.collapsed>.diffblock{order:3;flex:1 1 100%;margin:0}
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
 .warnflag{color:var(--why);font-size:15px;align-self:center;cursor:help}
 .field{display:flex;gap:10px;margin:11px 0 0;font-size:15px}
 .flabel{flex:0 0 auto;width:60px;box-sizing:border-box;text-align:center;font-size:11.5px;font-weight:800;
  letter-spacing:.6px;text-transform:uppercase;border-radius:6px;padding:3px 6px;align-self:flex-start;
  color:var(--faint);background:var(--chip);overflow:hidden}
 .f-why .flabel{color:var(--why);background:color-mix(in srgb,var(--why) 13%,transparent)}
 .f-fix .flabel{color:var(--fix);background:color-mix(in srgb,var(--fix) 13%,transparent)}
 .f-where .flabel{color:var(--where);background:color-mix(in srgb,var(--where) 13%,transparent)}
 .f-where .ftext{padding-top:1px;font-size:14.5px}
 .f-where .ftext.mono{font:13.5px/1.7 ui-monospace,Menlo,monospace;padding-top:2px}
 .fcode{font:13px/1.6 ui-monospace,Menlo,monospace;color:var(--faint);margin-top:3px;white-space:pre-wrap}
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
  });
  // every card folds on a title-row click; spec sets the initial state (data-fold). A saved
  // 'e:' key (1 = opened, 0 = folded) is a deviation from that default restored on reload.
  document.querySelectorAll('.card.collapsible').forEach(function (c) {
    var saved = state['e:' + c.dataset.id];
    if (saved === 1) c.classList.remove('collapsed');
    else if (saved === 0) c.classList.add('collapsed');
    c.querySelector('.cardhead').addEventListener('click', function () {
      c.classList.toggle('collapsed');
      persist();
    });
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
    document.querySelectorAll('.card.collapsible').forEach(function (c) {
      var folded = c.classList.contains('collapsed');
      if (folded !== (c.dataset.fold === '1')) s['e:' + c.dataset.id] = folded ? 0 : 1;
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
    var unpicked = 0, changed = 0, byValue = {};
    cards.forEach(function (c) {
      var r = c.querySelector('input[type=radio]:checked');
      if (!r) unpicked++;
      else if (r.value !== c.dataset.def) {
        changed++;
        byValue[r.value] = (byValue[r.value] || 0) + 1;
      }
    });
    var t = cards.length + ' item(s)';
    if (changed) t += ' \\u00b7 ' + changed + ' changed from default';
    if (unpicked) t += ' \\u00b7 ' + unpicked + ' unpicked';
    document.getElementById('count').textContent = t;
    // the Submit label carries what would be sent — the moment of commitment shows the commitment
    var summary = Object.keys(byValue).map(function (v) { return byValue[v] + ' ' + v; }).join(' \\u00b7 ');
    document.getElementById('submitbtn').textContent = summary ? 'Submit \\u2014 ' + summary : 'Submit to session';
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
  var EXPAND_ON = window.SPEC.expand_on || [];
  document.querySelectorAll('.card input[type=radio]').forEach(function (r) {
    r.addEventListener('change', function () {
      // a pick whose substance lives in the note (e.g. discuss) opens the card and puts the cursor there
      if (EXPAND_ON.indexOf(r.value) !== -1) {
        var c = r.closest('.card');
        c.classList.remove('collapsed');
        var n = c.querySelector('.notes'); if (n) n.focus();
      }
      persist();
      if (fchips.length) applyFacets(); // the virtual 'picked' facet follows the live radios
    });
  });
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
  // page-top sections record their rendered open/closed state before any user toggles, so Reset can restore it
  var sections = document.querySelectorAll('details.section');
  sections.forEach(function (d) { d.dataset.open0 = d.open ? '1' : ''; });
  document.getElementById('resetbtn').addEventListener('click', function () {
    cards.forEach(function (c) {
      c.querySelectorAll('input[type=radio]').forEach(function (r) { r.checked = (r.value === c.dataset.def); });
      var n = c.querySelector('.notes'); if (n) n.value = '';
    });
    // fold state returns to spec defaults too, cards and sections both — Reset means "as first rendered"
    document.querySelectorAll('.card.collapsible').forEach(function (c) {
      c.classList.toggle('collapsed', c.dataset.fold === '1');
    });
    sections.forEach(function (d) { d.open = d.dataset.open0 === '1'; });
    persist();
    if (fchips.length) applyFacets();
  });
  // facet bar: chips toggle — OR within a group, AND across groups, empty group = no narrowing.
  // Hidden cards stay in the DOM, so the blob and tally cover them. Selections persist per page key.
  var fchips = document.querySelectorAll('.facetbar .fchip');
  var FACETKEY = KEY + ':facets';
  var fsel = {};
  try { fsel = JSON.parse(localStorage.getItem(FACETKEY) || '{}'); } catch (e) { fsel = {}; }
  var cardlist = document.getElementById('cardlist');
  var allCards = Array.prototype.slice.call(document.querySelectorAll('#cardlist .card'));
  var facetsOf = new Map();
  allCards.forEach(function (c) {
    var f = {};
    try { f = JSON.parse(c.dataset.facets || '{}'); } catch (e) {}
    facetsOf.set(c, f);
  });
  var FKEYS = [];
  fchips.forEach(function (b) { if (FKEYS.indexOf(b.dataset.key) === -1) FKEYS.push(b.dataset.key); });
  // 'picked' is the virtual facet: its value is the card's live radio state, not spec data
  function facetValue(c, key) {
    if (key === 'picked') {
      var r = c.querySelector('input[type=radio]:checked');
      return r ? r.value : undefined;
    }
    return facetsOf.get(c)[key];
  }
  function matches(c, skipKey) {
    for (var k = 0; k < FKEYS.length; k++) {
      if (FKEYS[k] === skipKey) continue;
      var sel = fsel[FKEYS[k]] || [];
      if (sel.length && sel.indexOf(facetValue(c, FKEYS[k])) === -1) return false;
    }
    return true;
  }
  function applyFacets() {
    var any = false;
    fchips.forEach(function (b) {
      var sel = fsel[b.dataset.key] || [];
      var on = sel.indexOf(b.dataset.value) !== -1;
      b.classList.toggle('active', on);
      if (on) any = true;
    });
    var visible = 0;
    allCards.forEach(function (c) {
      var hide = !matches(c, null);
      c.classList.toggle('fhidden', hide);
      if (!hide) visible++;
    });
    // a chip's count ignores its own group's selection (standard faceted search), so
    // within-group numbers stay stable while you multi-select. A non-active chip whose
    // count is zero dims and stops responding — a dead-end combination shows before the click.
    fchips.forEach(function (b) {
      var n = 0;
      allCards.forEach(function (c) {
        if (facetValue(c, b.dataset.key) === b.dataset.value && matches(c, b.dataset.key)) n++;
      });
      var fc = b.querySelector('.fcount'); if (fc) fc.textContent = n;
      b.classList.toggle('dead', n === 0 && !b.classList.contains('active'));
    });
    var clear = document.getElementById('facetclear'); if (clear) clear.hidden = !any;
    var nomatch = document.getElementById('nomatch'); if (nomatch) nomatch.hidden = visible !== 0;
  }
  fchips.forEach(function (b) {
    b.addEventListener('click', function () {
      var sel = fsel[b.dataset.key] || (fsel[b.dataset.key] = []);
      var at = sel.indexOf(b.dataset.value);
      if (at === -1) sel.push(b.dataset.value); else sel.splice(at, 1);
      applyFacets();
      try { localStorage.setItem(FACETKEY, JSON.stringify(fsel)); } catch (e) {}
    });
  });
  function clearFacets() {
    fsel = {};
    applyFacets();
    try { localStorage.setItem(FACETKEY, '{}'); } catch (e) {}
  }
  ['facetclear', 'nomatchclear'].forEach(function (id) {
    var b = document.getElementById(id);
    if (b) b.addEventListener('click', clearFacets);
  });
  // group row: reorders the list under sticky per-value headers; "none" restores spec order.
  // Grouping moves DOM nodes (state rides along) and composes with the facet narrowing above.
  var gchips = document.querySelectorAll('.facetbar .gchip');
  var GROUPKEY = KEY + ':group';
  var specOrder = allCards.slice();
  function applyGroup(key) {
    gchips.forEach(function (b) { b.classList.toggle('active', b.dataset.group === key); });
    document.querySelectorAll('.ghead').forEach(function (h) { h.remove(); });
    if (!key) {
      specOrder.forEach(function (c) { cardlist.appendChild(c); });
      return;
    }
    var bar = document.querySelector('.facetbar');
    var headTop = (bar ? bar.offsetHeight + 14 : 10) + 'px';
    var values = [];
    fchips.forEach(function (b) { if (b.dataset.key === key && values.indexOf(b.dataset.value) === -1) values.push(b.dataset.value); });
    specOrder.forEach(function (c) {
      var v = facetsOf.get(c)[key];
      if (v !== undefined && values.indexOf(v) === -1) values.push(v);
    });
    values.forEach(function (v) {
      var members = specOrder.filter(function (c) { return facetsOf.get(c)[key] === v; });
      if (!members.length) return;
      var h = document.createElement('div');
      h.className = 'ghead';
      h.style.top = headTop;
      h.textContent = v + ' \\u00b7 ' + members.length;
      cardlist.appendChild(h);
      members.forEach(function (c) { cardlist.appendChild(c); });
    });
    var rest = specOrder.filter(function (c) { return facetsOf.get(c)[key] === undefined; });
    if (rest.length) {
      var oh = document.createElement('div');
      oh.className = 'ghead';
      oh.style.top = headTop;
      oh.textContent = 'other \\u00b7 ' + rest.length;
      cardlist.appendChild(oh);
      rest.forEach(function (c) { cardlist.appendChild(c); });
    }
  }
  gchips.forEach(function (b) {
    b.addEventListener('click', function () {
      applyGroup(b.dataset.group);
      try { localStorage.setItem(GROUPKEY, b.dataset.group); } catch (e) {}
    });
  });
  if (fchips.length) applyFacets();
  if (gchips.length) {
    var savedGroup = '';
    try { savedGroup = localStorage.getItem(GROUPKEY) || ''; } catch (e) {}
    var knownGroup = Array.prototype.some.call(gchips, function (b) { return b.dataset.group === savedGroup; });
    if (savedGroup && knownGroup) applyGroup(savedGroup);
  }
  // anchor scrolls must clear the sticky facet bar, whose height varies with its row count
  // and viewport width — measure it and feed scroll-margin-top through a CSS variable
  function setAnchorClearance() {
    var bar = document.querySelector('.facetbar');
    root.style.setProperty('--anchor-clear', (bar ? bar.offsetHeight + 26 : 40) + 'px');
  }
  window.addEventListener('resize', setAnchorClearance);
  setAnchorClearance();
  // a deep link from a context section can land on a folded card — unfold it, flash it, and let
  // the flash fade out. The hash is a transient navigation aid, not state: it clears as soon as
  // it is handled, so a reload replays nothing and a re-click of the same link is a fresh jump.
  function revealHash() {
    if (!location.hash) return;
    var target = document.getElementById(location.hash.slice(1));
    try { history.replaceState(null, '', location.pathname + location.search); } catch (e) {}
    if (!target || !target.classList.contains('card')) return;
    target.classList.remove('collapsed');
    target.classList.remove('flash');
    void target.offsetWidth;
    target.classList.add('flash');
    target.addEventListener('animationend', function () { target.classList.remove('flash'); }, { once: true });
  }
  window.addEventListener('hashchange', revealHash);
  revealHash();
  refresh();
})();
</script>
"""


def anchor_id(item_id):
    """One stable element id per card (card-heartbeat-3) — '#' and friends would break a URL
    fragment, so every non-alphanumeric becomes a dash. Section HTML deep-links against this."""
    return "card-" + re.sub(r"[^A-Za-z0-9_-]", "-", item_id)


def card_html(item, page_options, page_default, option_help):
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
    where_html = ""
    where_value = item.get("where")
    if isinstance(where_value, dict):
        code = f'<div class="fcode">{html.escape(where_value["code"])}</div>' if where_value.get("code") else ""
        where_html = (f'<div class="field f-where"><span class="flabel">where</span>'
                      f'<span class="ftext">{html.escape(where_value.get("place", ""))}{code}</span></div>')
    elif where_value:
        where_html = (f'<div class="field f-where"><span class="flabel">where</span>'
                      f'<span class="ftext mono">{html.escape(where_value)}</span></div>')
    fields = where_html + "".join(
        f'<div class="field f-{key}"><span class="flabel">{key}</span><span class="ftext">{html.escape(item[key])}</span></div>'
        for key in ("why", "fix")
        if item.get(key)
    )
    evidence = f'<div class="evidence">{html.escape(item["evidence"])}</div>' if item.get("evidence") else ""
    diff_html = ""
    if item.get("diff"):
        diff = item["diff"]
        location = f'<div class="diffloc">{html.escape(diff["location"])}</div>' if diff.get("location") else ""
        old_lines = "".join(
            f'<div class="dline dold">− {html.escape(line)}</div>' for line in diff.get("old", "").split("\n") if diff.get("old")
        )
        new_lines = "".join(
            f'<div class="dline dnew">+ {html.escape(line)}</div>' for line in diff.get("new", "").split("\n") if diff.get("new")
        )
        diff_html = f'<div class="diffblock">{location}{old_lines}{new_lines}</div>'
    detail = ""
    if item.get("detail"):
        detail = (
            f'<details class="detail"><summary>{html.escape(item["detail"].get("label", "more"))}</summary>'
            f'<div class="dtext">{html.escape(item["detail"].get("text", ""))}</div></details>'
        )
    warning = f'<div class="warning">{html.escape(item["warning"])}</div>' if item.get("warning") else ""
    warn_flag = f'<span class="warnflag" title="{html.escape(item["warning"])}">&#9888;</span>' if item.get("warning") else ""
    body = f'<div class="cardbody">{item["body_html"]}</div>' if item.get("body_html") else ""
    opts = ""
    if options:
        radio_labels = []
        for option in options:
            help_attr = f' title="{html.escape(option_help[option])}"' if option in option_help else ""
            checked = " checked" if option == default else ""
            radio_labels.append(
                f'<label{help_attr}><input type="radio" name="pick:{html.escape(item_id)}" '
                f'value="{html.escape(option)}"{checked}> {html.escape(option)}</label>'
            )
        opts = f'<div class="opts">{"".join(radio_labels)}</div>'
    notes = (
        f'<textarea class="notes" placeholder="notes on {html.escape(item_id)} (on an apply, this adjusts the wording)…"></textarea>'
        if item.get("notes", bool(options))
        else ""
    )
    collapsed = bool(item.get("collapsed"))
    card_classes = "card collapsible collapsed" if collapsed else "card collapsible"
    chevron = '<span class="chev">▸</span>'
    fold_attr = ' data-fold="1"' if collapsed else ""
    facets_attr = ""
    if item.get("facets"):
        facets_attr = f' data-facets="{html.escape(json.dumps(item["facets"]), quote=True)}"'
    return (
        f'<div class="{card_classes}" id="{anchor_id(item_id)}" data-id="{html.escape(item_id)}"'
        f' data-def="{html.escape(default or "")}"{fold_attr}{facets_attr}>'
        f'<div class="cardhead">{chevron}<span class="cardid">{html.escape(item_id)}</span>{badge}{warn_flag}{source}'
        f'<span class="cardtitle">{html.escape(item.get("title", ""))}</span></div>'
        f'<div class="cardfold">{meta}{summary}{fields}{evidence}{detail}{warning}{body}</div>'
        f"{diff_html}{opts}{notes}</div>"
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

    facet_rows = []
    for group in spec.get("facets", []):
        key = group["key"]
        values = list(group.get("values", []))
        for item in spec["items"]:
            value = (item.get("facets") or {}).get(key)
            if value and value not in values:
                values.append(value)
        help_map = group.get("help", {})
        counts = {value: 0 for value in values}
        for item in spec["items"]:
            value = (item.get("facets") or {}).get(key)
            if value in counts:
                counts[value] += 1
        chips = "".join(
            f'<button class="fchip" data-key="{html.escape(key)}" data-value="{html.escape(value)}"'
            + (f' title="{html.escape(help_map[value])}"' if value in help_map else "")
            + f'>{html.escape(value)}<span class="fcount">{counts[value]}</span></button>'
            for value in values
        )
        facet_rows.append(
            f'<div class="fgroup"><span class="fglabel">{html.escape(group.get("label", key))}</span>{chips}</div>'
        )
    decision_items = [item for item in spec["items"] if item.get("options", page_options)]
    if decision_items and spec.get("picked_facet", True):
        picked_values = list(page_options)
        for item in decision_items:
            for option in item.get("options", page_options):
                if option not in picked_values:
                    picked_values.append(option)
        # server-side counts reflect the spec defaults; the page recomputes from the live
        # radios on load and on every change
        picked_counts = {value: 0 for value in picked_values}
        for item in decision_items:
            default = item.get("default", page_default)
            if default in picked_counts:
                picked_counts[default] += 1
        picked_chips = "".join(
            f'<button class="fchip" data-key="picked" data-value="{html.escape(value)}">'
            f'{html.escape(value)}<span class="fcount">{picked_counts[value]}</span></button>'
            for value in picked_values
        )
        facet_rows.append(f'<div class="fgroup"><span class="fglabel">picked</span>{picked_chips}</div>')
    if spec.get("group_by"):
        group_chips = '<button class="gchip active" data-group="">none</button>' + "".join(
            f'<button class="gchip" data-group="{html.escape(key)}">{html.escape(key)}</button>'
            for key in spec["group_by"]
        )
        facet_rows.append(f'<div class="fgroup"><span class="fglabel">group</span>{group_chips}</div>')
    facetbar = ""
    if facet_rows:
        facetbar = ('<div class="facetbar">' + "".join(facet_rows)
                    + '<button class="facetclear" id="facetclear" hidden>clear filters ×</button></div>\n')

    option_help = spec.get("option_help", {})
    card_list = "\n".join(card_html(item, page_options, page_default, option_help) for item in spec["items"])
    nomatch = ""
    if facetbar:
        nomatch = ('<div class="nomatch" id="nomatch" hidden>Nothing matches the current filters. '
                   '<button id="nomatchclear">clear filters</button></div>')
    cards = f'{facetbar}<div id="cardlist">\n{card_list}\n</div>{nomatch}'

    subtitle = f'<p class="subtitle">{html.escape(spec["subtitle"])}</p>' if spec.get("subtitle") else ""
    intro = f'<div class="intro">{spec["intro_html"]}</div>' if spec.get("intro_html") else ""
    sections = "".join(
        f'<details class="section"{" open" if section.get("open") else ""}>'
        f'<summary>{html.escape(section["title"])}</summary>'
        f'<div class="sbody">{section["html"]}</div></details>'
        for section in spec.get("sections", [])
    )
    legend = legend_html(spec.get("option_help"))
    client_spec = json.dumps({"key": spec.get("key", ""), "blob_header": spec.get("blob_header", ""),
                              "expand_on": spec.get("expand_on", [])})

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
