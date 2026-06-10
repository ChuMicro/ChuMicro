#!/usr/bin/env python3
"""Mechanical HTML report for a completed regen-comments run (no LLM).

Builds report.html from a finished run room so the human can judge CORRECTNESS, not just voice:
  1. an INDEPENDENT plain-English summary (summary.json — written from the code, never from the comments),
     so the reader has a higher-level description to check the comments against;
  2. the validated ledger (ledger.json) + the validator verdict (validation.json);
  3. per-symbol BEFORE/AFTER docstrings (original target vs the finished file);
  4. the selection rationale (pick.json) — which whole writer pass was chosen and why, plus any
     auto-routed symbols — and the ledger facts that pertain to each symbol;
  5. an INTERACTIVE per-symbol picker: the suggested take pre-checked, the other cached writer passes
     (runs/run-N.py) offered as alternatives, and an "edit it myself" box that takes the human's exact
     docstring text. Choices + notes persist to localStorage KEYED BY A CONTENT FINGERPRINT of the FINAL
     file — a mid-review reload restores them, but once a selection is applied (FINAL changes) the page
     starts clean instead of restoring stale picks. A Copy-selection button serializes the choices into a
     paste-back blob the orchestrator applies via apply_selection.py.

build_file_section() is reusable: render_library.py composes one section per file into a tabbed
library-wide page with ONE combined blob. Radio groups and state keys are namespaced per section so tabs
never interfere. The static content renders without JavaScript; the picker is the only scripted layer.

Usage: render_report.py <rundir> <voice> <original_target.py>  ->  writes <rundir>/report.html
"""
import ast
import difflib
import glob
import hashlib
import html
import json
import os
import re
import sys
import webbrowser


def _doc_hint(sugg, cand):
    """Chips that guide the picker: how this candidate's docstring compares to the suggested one
    (length delta + shared-wording ratio), plus whether its inline comments differ too."""
    sugg_doc = (sugg.get("doc") or "").strip()
    cand_doc = (cand.get("doc") or "").strip()
    chips = []
    if not cand_doc:
        chips.append("drops the docstring")
    elif not sugg_doc:
        chips.append("adds a docstring")
    else:
        sugg_lines = sugg_doc.count("\n") + 1
        cand_lines = cand_doc.count("\n") + 1
        if cand_lines < sugg_lines:
            chips.append(f"{sugg_lines - cand_lines} line(s) shorter")
        elif cand_lines > sugg_lines:
            chips.append(f"{cand_lines - sugg_lines} line(s) longer")
        else:
            chips.append("same length")
        ratio = difflib.SequenceMatcher(None, sugg_doc, cand_doc).ratio()
        chips.append(f"{round(ratio * 100)}% shared wording")
    # pure-comment lines of the full symbol block; code is identical across passes, so a delta here
    # means the inline comments differ even when the docstrings read the same
    sugg_comments = [ln.strip() for ln in (sugg.get("block") or "").splitlines() if ln.strip().startswith("#")]
    cand_comments = [ln.strip() for ln in (cand.get("block") or "").splitlines() if ln.strip().startswith("#")]
    if sugg_comments != cand_comments:
        chips.append("inline comments differ")
    return chips


def _symbols(path):
    """{qualname: {doc, lineno, sig}} for the module + every class / function / method.

    sig is the source of the `def`/`class` statement (decorators through the colon, docstring excluded), so
    the report shows what each docstring documents. The module row has no signature.
    """
    src = open(path).read()
    lines = src.splitlines()
    tree = ast.parse(src)
    out = {"<module>": {"doc": ast.get_docstring(tree), "lineno": 0, "sig": ""}}

    def sig_of(node):
        start = node.lineno
        if node.decorator_list:
            start = min(start, min(d.lineno for d in node.decorator_list))
        body_start = node.body[0].lineno if node.body else node.lineno + 1
        return "\n".join(lines[start - 1:body_start - 1]).rstrip()

    def walk(node, prefix):
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                q = prefix + child.name
                out[q] = {"doc": ast.get_docstring(child), "lineno": child.lineno, "sig": sig_of(child)}
                if isinstance(child, ast.ClassDef):
                    walk(child, q + ".")

    walk(tree, "")
    return out


def _blocks(path):
    """{qualname: {doc, block}} — block is the symbol's FULL source span (so inline comments show too).

    A class's block is empty: a class pick applies the class DOCSTRING only (methods have their own rows),
    so a full-span expander would imply the methods ride along. The module's block is its docstring span.
    """
    src = open(path).read()
    lines = src.splitlines()
    tree = ast.parse(src)
    out = {}
    mod_doc = None
    if (tree.body and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, ast.Constant) and isinstance(tree.body[0].value.value, str)):
        n = tree.body[0]
        mod_doc = "\n".join(lines[n.lineno - 1:n.end_lineno])
    out["<module>"] = {"doc": ast.get_docstring(tree), "block": mod_doc or ""}

    def walk(node, prefix):
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                q = prefix + child.name
                start = child.lineno
                if child.decorator_list:
                    start = min(start, min(d.lineno for d in child.decorator_list))
                if isinstance(child, ast.ClassDef):
                    out[q] = {"doc": ast.get_docstring(child), "block": ""}
                    walk(child, q + ".")
                else:
                    out[q] = {"doc": ast.get_docstring(child),
                              "block": "\n".join(lines[start - 1:child.end_lineno])}

    walk(tree, "")
    return out


def _load(path, default):
    return json.load(open(path)) if os.path.exists(path) else default


def _esc(s):
    return html.escape(str(s) if s is not None else "")


def _short(qual):
    return qual.split(".")[-1]


def _facts_for(qual, ledger):
    """Ledger facts whose sites mention this symbol's short name (best-effort line-free mapping)."""
    if qual == "<module>":
        return []
    name = _short(qual)
    return [f for f in ledger if name in f.get("sites", "")]


CSS = """
 :root{
  --bg:#f3f5f8; --fg:#171c26; --muted:#5a6472; --faint:#8a93a0; --soft:#33405a;
  --card:#ffffff; --border:#e4e8ed; --border2:#d6dbe2; --line:#edf0f4; --divider:#e4e8ed;
  --pre-bg:#f8fafc; --accent:#4f46e5; --accent2:#7c3aed; --green:#15803d; --amber:#9a4a10;
  --sig-bg:#eef1fb; --sig-border:#dde2f6; --sig-fg:#3730a3;
  --pill-bg:#eef0f4; --pill-fg:#3a4554; --pill-hover:#e4e8ee; --pill-border:#d6dbe2;
  --ok-bg:#dcf5e4; --warn-bg:#fdeadb;
  --legib-bg:#fffaf0; --legib-fg:#7a3a00; --legib-ok-bg:#f3fbf5;
  --tic-bg:#ebe5ff; --tic-fg:#5b3a9a; --leak-bg:#ffe4e6; --leak-fg:#a8323f;
  --tab-bg:#e8ebf0; --blob-bg:#f8fafc; --shadow:rgba(23,28,38,.08); --glow:rgba(79,70,229,.16);
 }
 [data-theme=dark]{
  --bg:#0e1117; --fg:#dfe3ea; --muted:#98a1b0; --faint:#69727f; --soft:#b6c0d0;
  --card:#151922; --border:#252b36; --border2:#323947; --line:#212733; --divider:#2a313d;
  --pre-bg:#11141b; --accent:#8d97ff; --accent2:#b78cf7; --green:#4ade80; --amber:#e8a06a;
  --sig-bg:#1b2030; --sig-border:#2c3450; --sig-fg:#aeb7f5;
  --pill-bg:#222834; --pill-fg:#c3cad4; --pill-hover:#2a3140; --pill-border:#363e4d;
  --ok-bg:#143124; --warn-bg:#3c2616;
  --legib-bg:#2a2218; --legib-fg:#e0b48a; --legib-ok-bg:#182a1e;
  --tic-bg:#2d2547; --tic-fg:#b9a3ee; --leak-bg:#3a2226; --leak-fg:#e89aa4;
  --tab-bg:#1a1f29; --blob-bg:#11141b; --shadow:rgba(0,0,0,.4); --glow:rgba(141,151,255,.18);
 }
 body{font:14px/1.55 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;margin:0;background:var(--bg);color:var(--fg);-webkit-font-smoothing:antialiased}
 ::selection{background:color-mix(in srgb,var(--accent) 22%,transparent)}
 .wrap{max-width:1180px;margin:0 auto;padding:28px 24px 40px}
 h1{font-size:21px;margin:0 0 4px;font-weight:650;letter-spacing:-.01em}
 h2{font-size:16px;margin:30px 0 10px;border-bottom:1px solid var(--border2);padding-bottom:6px;font-weight:650;letter-spacing:-.005em}
 h3{font-size:14px;margin:0 0 6px;font-family:ui-monospace,Menlo,monospace;color:var(--accent)}
 .sub{color:var(--muted);margin-bottom:16px}
 .badge{display:inline-flex;align-items:center;gap:6px;padding:3px 11px;border-radius:999px;font-weight:600;font-size:12px}
 .badge::before{content:'';width:7px;height:7px;border-radius:50%;background:currentColor}
 .badge.ok{background:var(--ok-bg);color:var(--green)} .badge.warn{background:var(--warn-bg);color:var(--amber)}
 .card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:18px;margin-bottom:14px;box-shadow:0 1px 2px var(--shadow)}
 .summary p{margin:0 0 10px} .summary ul{margin:0;padding-left:18px} .summary li{margin:2px 0}
 .summary code{color:var(--accent)}
 table{width:100%;border-collapse:collapse} td,th{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}
 th{font-size:11.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;font-weight:650}
 code{font-family:ui-monospace,Menlo,monospace;font-size:12.5px}
 .c-high{color:var(--green);font-weight:600} .c-med{color:#9a6a10} .c-low{color:#c05a6a}
 [data-theme=dark] .c-med{color:#d8b36a}
 .sym{border-top:1px solid var(--divider);padding:26px 0 20px}
 .sym>details:last-child{margin-top:12px}
 .purpose{color:var(--soft);margin-bottom:8px}
 .ba{display:flex;gap:12px} .col{flex:1;min-width:0} .lbl{font-size:10.5px;color:var(--faint);text-transform:uppercase;letter-spacing:.06em;font-weight:650;margin-bottom:3px}
 pre{white-space:pre-wrap;word-break:break-word;background:var(--pre-bg);border:1px solid var(--line);border-radius:8px;padding:9px 10px;margin:4px 0;font-size:12.5px;color:var(--fg)}
 .ba .col:last-child pre{border-left:3px solid color-mix(in srgb,var(--accent) 50%,transparent)}
 pre.sig{background:var(--sig-bg);border-color:var(--sig-border);color:var(--sig-fg);font-weight:600;margin-bottom:8px}
 input[type=radio]{accent-color:var(--accent)}
 @media (prefers-reduced-motion:reduce){*{transition:none!important}}
 details.card>summary{font-size:16px;cursor:pointer}
 .none{color:var(--faint);font-style:italic}
 details{margin-top:6px} summary{cursor:pointer;color:var(--muted);font-size:12px}
 .facts{margin:8px 0;padding-left:18px} .facts .meta{color:var(--faint)}
 .why{margin-top:6px;color:var(--soft)}
 .sel{color:var(--soft)} .concern{margin-top:8px;color:var(--amber);font-weight:600}
 .legib{border-left:4px solid #e0a020;background:var(--legib-bg);color:var(--legib-fg)}
 .legib.ok{border-left-color:var(--green);background:var(--legib-ok-bg);color:var(--green)}
 .legib .flags{margin:8px 0 0;padding-left:18px} .legib .flagsent{font-style:italic;margin:2px 0 8px}
 .legib .meta{color:var(--faint);font-style:normal}
 .tk{font-size:10.5px;padding:1px 6px;border-radius:3px;font-weight:700;text-transform:uppercase}
 .tk-tic{background:var(--tic-bg);color:var(--tic-fg)} .tk-leak{background:var(--leak-bg);color:var(--leak-fg)}
 .alts{margin:16px 0 4px}
 .alts>summary{font-weight:600;font-size:13px;color:var(--pill-fg);background:var(--pill-bg);border:1px solid var(--pill-border);border-radius:999px;padding:7px 14px;display:inline-block;transition:background .15s,border-color .15s}
 .alts>summary:hover{background:var(--pill-hover);border-color:var(--border2)}
 .pickwrap{border:1px solid var(--border);border-radius:12px;padding:12px;margin-top:8px;background:var(--card);box-shadow:0 1px 2px var(--shadow)}
 .candgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:10px;align-items:stretch;scrollbar-width:thin;scrollbar-color:var(--border2) transparent}
 /* 4+ takes: a cramming grid goes unreadable, so flip to a horizontal snap rail of fixed-width cards */
 .candgrid:has(.cand:nth-child(4)){grid-template-columns:none;grid-auto-flow:column;grid-auto-columns:minmax(300px,340px);overflow-x:auto;scroll-snap-type:x proximity;padding-bottom:8px}
 .candgrid:has(.cand:nth-child(4))>.cand{scroll-snap-align:start}
 .candgrid::-webkit-scrollbar{height:8px}
 .candgrid::-webkit-scrollbar-thumb{background:var(--border2);border-radius:999px}
 .candgrid::-webkit-scrollbar-track{background:transparent}
 .cand{border:1px solid var(--border);border-radius:10px;padding:10px;background:var(--pre-bg);min-width:0;display:flex;flex-direction:column;transition:border-color .15s,box-shadow .15s}
 .candgrid .cand pre{flex:1 1 auto;background:var(--card)}
 .cand:hover{border-color:var(--border2)}
 .cand:has(input:checked){border-color:var(--accent);box-shadow:0 0 0 1px var(--accent),0 4px 16px var(--glow)}
 .cand.edit{margin-top:10px}
 .cand label{cursor:pointer;font-weight:600} .cand.sugg label b{color:var(--green)}
 .dhint{display:flex;gap:5px;flex-wrap:wrap;margin:6px 0 2px}
 .dhint .chip{font-size:10.5px;font-weight:600;color:var(--pill-fg);background:var(--pill-bg);border:1px solid var(--pill-border);border-radius:999px;padding:1px 8px}
 .dedup{font-size:11.5px;color:var(--faint);margin-top:10px;font-style:italic}
 .fbadge{font-size:11px;background:var(--warn-bg);color:var(--amber);padding:1px 8px;border-radius:999px;font-weight:700}
 .editbox{width:100%;min-height:90px;font:12.5px/1.5 ui-monospace,Menlo,monospace;border:1px solid var(--border2);border-radius:8px;padding:9px;margin-top:6px;box-sizing:border-box;background:var(--card);color:var(--fg)}
 .symnotes{width:100%;font:inherit;font-size:12.5px;border:1px dashed var(--border2);border-radius:8px;padding:7px 9px;margin-top:10px;box-sizing:border-box;min-height:34px;background:var(--pre-bg);color:var(--fg)}
 .editbox:focus,.symnotes:focus{outline:2px solid color-mix(in srgb,var(--accent) 55%,transparent);outline-offset:1px;border-color:var(--accent)}
 .selbar{position:sticky;bottom:10px;border-radius:14px;background:color-mix(in srgb,var(--card) 80%,transparent);backdrop-filter:blur(14px) saturate(1.4);-webkit-backdrop-filter:blur(14px) saturate(1.4);border:1px solid var(--border2);box-shadow:0 10px 32px var(--shadow);padding:8px 12px}
 .blobwrap{margin-top:6px} .blobwrap>summary{font-size:11.5px;color:var(--faint)}
 .selbar .row{display:flex;gap:10px;align-items:center}
 .selbar button{font:inherit;font-size:13px;padding:7px 15px;border-radius:999px;border:none;cursor:pointer;transition:filter .15s,background .15s,transform .06s}
 .selbar button:active{transform:translateY(1px)}
 .selbar .primary{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;font-weight:600;box-shadow:0 2px 12px var(--glow)}
 .selbar .primary:hover{filter:brightness(1.08)}
 .selbar .ghost{background:var(--pill-bg);color:var(--fg);border:1px solid var(--pill-border)}
 .selbar .ghost:hover{background:var(--pill-hover)}
 .selbar .grow{flex:1;color:var(--soft);font-weight:600}
 .selbar button:focus-visible,.themebtn:focus-visible{outline:2px solid color-mix(in srgb,var(--accent) 60%,transparent);outline-offset:2px}
 #blob{width:100%;margin-top:10px;font:12px/1.5 ui-monospace,Menlo,monospace;border:1px solid var(--border2);border-radius:8px;padding:8px;min-height:46px;background:var(--blob-bg);color:var(--fg);box-sizing:border-box}
 .tabbar{display:flex;gap:4px;flex-wrap:wrap;margin:16px 0 20px;background:color-mix(in srgb,var(--tab-bg) 80%,transparent);backdrop-filter:blur(12px) saturate(1.3);-webkit-backdrop-filter:blur(12px) saturate(1.3);border:1px solid var(--border);border-radius:12px;padding:4px;width:fit-content;max-width:100%;position:sticky;top:10px;z-index:9}
 .tabbar button{font:inherit;font-size:13px;font-weight:600;padding:7px 14px;border:none;border-radius:9px;background:transparent;color:var(--muted);cursor:pointer;transition:color .15s,background .15s}
 .tabbar button:hover{color:var(--fg)}
 .tabbar button.active{background:var(--card);color:var(--accent);box-shadow:0 1px 5px var(--shadow)}
 .tabbar .tflag{font-size:10.5px;background:var(--warn-bg);color:var(--amber);border-radius:999px;padding:0 7px;margin-left:6px;font-weight:700}
 .filepane{display:none} .filepane.active{display:block}
 .panehead{display:flex;align-items:baseline;gap:10px;margin:2px 0 14px;font-size:16px;font-weight:650;color:var(--accent)}
 .panehead .panemeta{font-size:12px;font-weight:500;color:var(--faint)}
 .themebtn{position:fixed;top:14px;right:16px;font:inherit;font-size:13px;padding:6px 12px;border-radius:999px;border:1px solid var(--pill-border);background:color-mix(in srgb,var(--pill-bg) 75%,transparent);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);color:var(--pill-fg);cursor:pointer;z-index:10;transition:background .15s}
 .themebtn:hover{background:var(--pill-hover)}
"""

SCRIPT = """
<script>
(function () {
  var KEY = 'regen-comments:' + ((window.DATA && window.DATA.run) || 'x') + ':' + ((window.DATA && window.DATA.gen) || '');
  function load() { try { return JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) { return {}; } }
  function save(s) { try { localStorage.setItem(KEY, JSON.stringify(s)); } catch (e) {} }
  var state = load();
  var wraps = document.querySelectorAll('.pickwrap');
  function sk(w) { return (w.dataset.ns || '') + ':' + w.dataset.idx; }
  wraps.forEach(function (w) {
    var k = sk(w);
    if (state['p' + k]) { var r = w.querySelector('input[value="' + state['p' + k] + '"]'); if (r) r.checked = true; }
    if (state['e' + k] !== undefined) { var e = w.querySelector('.editbox'); if (e) e.value = state['e' + k]; }
    if (state['n' + k]) { var n = w.querySelector('.symnotes'); if (n) n.value = state['n' + k]; }
  });
  function persist() {
    var s = {};
    wraps.forEach(function (w) {
      var k = sk(w);
      var r = w.querySelector('input[type=radio]:checked');
      if (r && r.value !== 'suggested') s['p' + k] = r.value;
      var e = w.querySelector('.editbox');
      if (e && e.value !== e.defaultValue) s['e' + k] = e.value;
      var n = w.querySelector('.symnotes');
      if (n && n.value.trim()) s['n' + k] = n.value;
    });
    save(s); refresh();
  }
  function buildBlob() {
    var order = [], byFile = {};
    wraps.forEach(function (w) {
      var f = w.dataset.file || 'file.py';
      if (!byFile[f]) { byFile[f] = { devs: [], edits: [], notes: [] }; order.push(f); }
      var sec = byFile[f];
      var sym = w.dataset.sym;
      var r = w.querySelector('input[type=radio]:checked');
      var v = r ? r.value : 'suggested';
      if (v !== 'suggested') sec.devs.push(sym + '=' + v);
      if (v === 'edit') {
        var e = w.querySelector('.editbox');
        sec.edits.push('#edit ' + sym + '\\n<<<EDIT\\n' + (e ? e.value : '') + '\\nEDIT>>>');
      }
      var n = w.querySelector('.symnotes');
      if (n && n.value.trim()) sec.notes.push('#note ' + sym + ': ' + n.value.trim().replace(/\\n/g, ' '));
    });
    var parts = [];
    order.forEach(function (f) {
      var sec = byFile[f];
      // single-file page: always emit the header. library page: skip untouched files to keep the blob lean
      if (order.length > 1 && !sec.devs.length && !sec.edits.length && !sec.notes.length) return;
      var t = 'regen-comments apply (' + f + '): ' + (sec.devs.length ? sec.devs.join(', ') : 'all suggested');
      if (sec.edits.length) t += '\\n\\n' + sec.edits.join('\\n\\n');
      if (sec.notes.length) t += '\\n\\n' + sec.notes.join('\\n');
      parts.push(t);
    });
    return parts.length ? parts.join('\\n\\n') : 'regen-comments apply: all suggested';
  }
  function refresh() {
    var devs = 0;
    wraps.forEach(function (w) {
      var r = w.querySelector('input[type=radio]:checked');
      if (r && r.value !== 'suggested') devs++;
    });
    var c = document.getElementById('devcount');
    if (c) c.textContent = devs ? (devs + ' symbol(s) changed from suggested') : 'all suggested';
    var b = document.getElementById('blob');
    if (b) b.value = buildBlob();
  }
  function copy() {
    var blob = buildBlob();
    // the execCommand fallback (file:// pages: no clipboard API) needs the textarea visible + selected
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
  document.querySelectorAll('.pickwrap input[type=radio]').forEach(function (r) { r.addEventListener('change', persist); });
  document.querySelectorAll('.editbox, .symnotes').forEach(function (t) { t.addEventListener('input', persist); });
  var cb = document.getElementById('copybtn'); if (cb) cb.addEventListener('click', copy);
  // Submit posts the same blob to the serving session; a file:// page has no server, so it stays hidden.
  var sb = document.getElementById('submitbtn');
  if (sb) {
    if (location.protocol === 'http:' || location.protocol === 'https:') sb.hidden = false;
    sb.addEventListener('click', submitSel);
  }
  var rb = document.getElementById('resetbtn');
  if (rb) rb.addEventListener('click', function () {
    wraps.forEach(function (w) {
      var s = w.querySelector('input[value="suggested"]'); if (s) s.checked = true;
      var e = w.querySelector('.editbox'); if (e) e.value = e.defaultValue;
      var n = w.querySelector('.symnotes'); if (n) n.value = '';
    });
    persist();
  });
  // tab bar (library page only; absent on the single-file page)
  var tabs = document.querySelectorAll('.tabbar button');
  tabs.forEach(function (t) {
    t.addEventListener('click', function () {
      tabs.forEach(function (x) { x.classList.remove('active'); });
      document.querySelectorAll('.filepane').forEach(function (p) { p.classList.remove('active'); });
      t.classList.add('active');
      var pane = document.getElementById('pane-' + t.dataset.pane);
      if (pane) pane.classList.add('active');
    });
  });
  refresh();
})();
</script>"""

# Theme toggle binding — its own script so every page (report, library, compare) gets it from write_page
# regardless of which interaction script the page uses. Explicit choice persists globally (not per run).
THEME_JS = """
<script>
(function () {
  var tb = document.getElementById('themebtn');
  if (!tb) return;
  function glyph() { tb.textContent = document.documentElement.dataset.theme === 'dark' ? '\\u263e dark' : '\\u2600 light'; }
  glyph();
  tb.addEventListener('click', function () {
    var next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('regen-comments-theme', next); } catch (e) {}
    glyph();
  });
})();
</script>"""

# Runs in <head>, before first paint, so the page never flashes the wrong theme: an explicit saved choice
# wins; otherwise follow the OS (and keep following it live until the user picks explicitly).
THEME_BOOT = """
<script>
(function () {
  var t = null;
  try { t = localStorage.getItem('regen-comments-theme'); } catch (e) {}
  var mq = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)');
  document.documentElement.dataset.theme = t || (mq && mq.matches ? 'dark' : 'light');
  if (!t && mq && mq.addEventListener) {
    mq.addEventListener('change', function (e) {
      var saved = null;
      try { saved = localStorage.getItem('regen-comments-theme'); } catch (x) {}
      if (!saved) {
        document.documentElement.dataset.theme = e.matches ? 'dark' : 'light';
        var b = document.getElementById('themebtn');
        if (b) b.textContent = e.matches ? '\\u263e dark' : '\\u2600 light';
      }
    });
  }
})();
</script>"""


def build_file_section(rundir, voice, original, ns="f0"):
    """One file's full report body (summary, rationale, flags, ledger, per-symbol pickers).

    ns namespaces the radio-group names and the localStorage state keys so multiple sections coexist on
    one page (the library tabs). Returns (section_html, meta); meta carries what a page header or tab
    label needs, plus a content hash of the FINAL file for the staleness-proof storage key.
    """
    rundir = os.path.abspath(rundir)
    original = os.path.abspath(original)
    final = os.path.join(rundir, f"FINAL_{voice}.py")
    if not os.path.exists(final):
        final = os.path.join(rundir, "merged.py")
    summary = _load(os.path.join(rundir, "summary.json"), {"module_summary": "", "symbols": []})
    ledger = _load(os.path.join(rundir, "ledger.json"), [])
    val = _load(os.path.join(rundir, "validation.json"), {})
    pick = _load(os.path.join(rundir, "pick.json"), {})
    if not isinstance(pick, dict):
        pick = {}
    winner = pick.get("winner")
    why = pick.get("why", "")
    concern = pick.get("concern", "")
    autoroute = {r["symbol"]: r["to_run"] for r in pick.get("autoroute", [])}
    runs_dir = os.path.join(rundir, "runs")
    run_files = sorted(glob.glob(os.path.join(runs_dir, "run-*.py")))
    n_passes = len(run_files)
    has_lib = os.path.exists(os.path.join(rundir, "LIBRARY_FACTS.md"))

    final_bytes = open(final, "rb").read()
    fhash = hashlib.sha1(final_bytes).hexdigest()[:10]

    before = _symbols(original)
    after = _symbols(final)
    final_blocks = _blocks(final)
    run_blocks = {}
    for rf in run_files:
        n = int(re.search(r"run-(\d+)\.py$", rf).group(1))
        try:
            run_blocks[n] = _blocks(rf)
        except SyntaxError:
            pass
    purpose = {s["symbol"]: s["purpose"] for s in summary.get("symbols", [])}

    verdict_ok = not (val.get("any_wrong") or val.get("any_underspecified"))
    badge = ("ledger validated clean" if verdict_ok else "validator flagged issues — see facts")
    badge_cls = "ok" if verdict_ok else "warn"

    legib = _load(os.path.join(rundir, "legibility.json"), {})
    flags = legib.get("flags", []) if isinstance(legib, dict) else []
    ticj = _load(os.path.join(rundir, "tics.json"), {})
    tflags = ticj.get("flags", []) if isinstance(ticj, dict) else []
    banj = _load(os.path.join(rundir, "bans.json"), {})
    bflags = banj.get("flags", []) if isinstance(banj, dict) else []
    flagged_syms = {f.get("symbol") for f in flags} | {f.get("symbol") for f in tflags}
    for b in bflags:                              # mechanical-ban leftovers badge their symbols too
        w = b.get("where", "")
        if w.startswith("docstring:"):
            short = w.split(":", 1)[1]
            flagged_syms |= {q for q in after if q.split(".")[-1] == short} or {short}

    fname = os.path.basename(original)
    rows = []
    for i, (qual, info) in enumerate(after.items()):
        doc_after = info["doc"]
        sig = info["sig"]
        doc_before = before.get(qual, {}).get("doc")
        pur = purpose.get(qual) or purpose.get(_short(qual)) or ""
        facts = _facts_for(qual, ledger)
        # gloss (plain English) leads for the human; the writer-facing stub rides as secondary notation
        fact_html = "".join(
            f"<li>{_esc(f.get('gloss')) + ' ' if f.get('gloss') else ''}<code>{_esc(f.get('stub'))}</code> "
            f"<span class='meta'>({_esc(f.get('confidence'))}, {_esc(','.join(f.get('source_lenses', [])))})</span></li>"
            for f in facts) or "<li class='none'>none mapped to this symbol</li>"

        sugg = final_blocks.get(qual, {"doc": doc_after, "block": ""})
        sugg_key = ((sugg.get("doc") or "").strip(), (sugg.get("block") or "").strip())
        sugg_from = autoroute.get(qual, winner)
        # identical takes are shown once; `hidden` remembers who matched whom so the picker can SAY so
        # instead of leaving the human wondering where a pass went
        alts, seen, hidden = [], {sugg_key: "the suggested text"}, []
        for n in sorted(run_blocks):
            if n == sugg_from:
                continue  # this pass IS the suggested text (modulo polish/reattach)
            cand = run_blocks[n].get(qual)
            if not cand:
                continue
            key = ((cand.get("doc") or "").strip(), (cand.get("block") or "").strip())
            if key in seen:
                hidden.append((n, seen[key]))
                continue
            seen[key] = f"pass {n}"
            alts.append((n, cand))
        flag_badge = "<span class='fbadge'>⚠ flagged</span>" if qual in flagged_syms else ""
        sugg_label = (f"auto-routed to writer pass {_esc(sugg_from)} (pass {_esc(winner)} was flagged)"
                      if qual in autoroute else f"writer pass {_esc(winner)}, polished")
        sugg_details = (f"<details><summary>full symbol (incl. inline comments)</summary>"
                        f"<pre>{_esc(sugg.get('block'))}</pre></details>"
                        if (sugg.get("block") or "").strip() else "")
        alt_html = "".join(
            f"""<div class="cand">
              <label><input type="radio" name="pick-{ns}-{i}" value="run-{n}"> writer pass {n}</label>
              <div class="dhint">{''.join(f"<span class='chip'>{_esc(c)}</span>" for c in _doc_hint(sugg, cand))}</div>
              <pre>{_esc(cand.get('doc')) or '<span class=none>(no docstring)</span>'}</pre>
              {f"<details><summary>full symbol (incl. inline comments)</summary><pre>{_esc(cand.get('block'))}</pre></details>" if (cand.get('block') or '').strip() else ''}
            </div>""" for n, cand in alts)
        dedup_note = ""
        if hidden:
            listing = ", ".join(f"pass {n} (matches {label})" for n, label in hidden)
            dedup_note = f"<div class='dedup'>shown once: {listing} — identical takes aren't repeated</div>"
        picker = f"""
          <details class="alts">
            <summary>pick a different take or edit ({len(alts)} alternative pass(es)){' <span class="fbadge">⚠ flagged</span>' if qual in flagged_syms else ''}</summary>
            <div class="pickwrap" data-sym="{_esc(qual)}" data-idx="{i}" data-ns="{_esc(ns)}" data-file="{_esc(fname)}">
              <div class="candgrid">
                <div class="cand sugg">
                  <label><input type="radio" name="pick-{ns}-{i}" value="suggested" checked>
                    <b>suggested</b> — {sugg_label} {flag_badge}</label>
                  <pre>{_esc(sugg.get('doc')) or '<span class=none>(no docstring)</span>'}</pre>
                  {sugg_details}
                </div>
                {alt_html}
              </div>
              {dedup_note}
              <div class="cand edit">
                <label><input type="radio" name="pick-{ns}-{i}" value="edit"> edit it myself (replaces the docstring with your exact text)</label>
                <textarea class="editbox" spellcheck="false">{_esc(sugg.get('doc'))}</textarea>
              </div>
              <textarea class="symnotes" placeholder="notes on {_esc(_short(qual))} (ride back with the selection)…"></textarea>
            </div>
          </details>"""

        rows.append(f"""
        <div class="sym">
          <h3>{_esc(qual)}</h3>
          {f'<pre class="sig">{_esc(sig)}</pre>' if sig else ''}
          {f'<div class="purpose">{_esc(pur)}</div>' if pur else ''}
          <div class="ba">
            <div class="col"><div class="lbl">before</div><pre>{_esc(doc_before) or '<span class=none>(no docstring)</span>'}</pre></div>
            <div class="col"><div class="lbl">after — suggested</div><pre>{_esc(doc_after) or '<span class=none>(no docstring)</span>'}</pre></div>
          </div>
          {picker}
          <details><summary>ledger facts</summary>
            <ul class="facts">{fact_html}</ul>
          </details>
        </div>""")

    ledger_rows = "".join(
        f"<tr><td>{_esc(f.get('gloss')) + '<br>' if f.get('gloss') else ''}<code>{_esc(f.get('stub'))}</code></td><td>{_esc(f.get('sites'))}</td>"
        f"<td>{_esc(','.join(f.get('source_lenses', [])))}</td><td class='c-{_esc(f.get('confidence'))}'>{_esc(f.get('confidence'))}</td></tr>"
        for f in ledger) or "<tr><td colspan=4 class=none>empty ledger</td></tr>"

    concern_html = f"<div class='concern'>⚠ selector concern: {_esc(concern)}</div>" if concern else ""
    route_html = ("<div class='why'>auto-routed around flags: "
                  + ", ".join(f"<code>{_esc(s)}</code> → pass {_esc(n)}" for s, n in autoroute.items())
                  + "</div>") if autoroute else ""
    sel_html = (f"<div class='card sel'><b>Selected writer pass {_esc(winner)}"
                + (f" of {n_passes}" if n_passes else "")
                + f"</b> — {_esc(why)}{concern_html}{route_html}</div>") if winner is not None else ""

    if flags:
        items = "".join(
            f"<li><code>{_esc(f.get('symbol'))}</code> <span class='meta'>({_esc(f.get('why'))})</span>"
            f"<div class='flagsent'>{_esc(f.get('sentence'))}</div></li>" for f in flags)
        legib_html = (f"<div class='card legib'><b>⚠ {len(flags)} sentence(s) flagged for legibility</b> — "
                      f"review these in the refine loop. They read awkwardly even when the facts are right."
                      f"<ul class='flags'>{items}</ul></div>")
    elif os.path.exists(os.path.join(rundir, "legibility.json")):
        legib_html = "<div class='card legib ok'>✓ legibility: no sentences flagged.</div>"
    else:
        legib_html = ""

    if tflags:
        titems = "".join(
            f"<li><code>{_esc(f.get('symbol'))}</code> <span class='tk tk-{_esc(f.get('kind'))}'>{_esc(f.get('kind'))}</span> "
            f"<span class='meta'>({_esc(f.get('why'))})</span>"
            f"<div class='flagsent'>{_esc(f.get('text'))}</div></li>" for f in tflags)
        nt = sum(1 for f in tflags if f.get("kind") == "tic")
        nl = sum(1 for f in tflags if f.get("kind") == "leak")
        tics_html = (f"<div class='card legib'><b>⚠ {nt} AI-tic(s) + {nl} voice-leak(s) flagged</b> — "
                     f"formulaic phrasing and voice-descriptor words that slipped into the comments; cut them "
                     f"in the refine loop.<ul class='flags'>{titems}</ul></div>")
    elif os.path.exists(os.path.join(rundir, "tics.json")):
        tics_html = "<div class='card legib ok'>✓ no AI-tics or voice-leaks flagged.</div>"
    else:
        tics_html = ""

    # mechanical-ban leftovers (bans.json, written by polish.py): violations that survived ban-aware
    # autoroute + the single polish round because every cached pass was dirty — the human fixes these
    # via the picker/edit
    if bflags:
        bitems = "".join(
            f"<li><code>{_esc(b.get('where'))}</code> <span class='tk tk-leak'>{_esc(b.get('kind'))}</span>"
            f"<div class='flagsent'>{_esc(b.get('text'))}</div></li>" for b in bflags)
        bans_html = (f"<div class='card legib'><b>⚠ {len(bflags)} mechanical-ban violation(s) remain</b> — "
                     f"no cached pass had a clean take and one polish round did not clear them; fix via "
                     f"pick-a-different-take or edit-it-myself.<ul class='flags'>{bitems}</ul></div>")
    elif os.path.exists(os.path.join(rundir, "bans.json")):
        bans_html = "<div class='card legib ok'>✓ mechanical bans: clean.</div>"
    else:
        bans_html = ""

    section = f"""
 <div class="sub">voice: <b>{_esc(voice)}</b> · <span class="badge {badge_cls}">{_esc(badge)}</span>{' · library-aware' if has_lib else ''}</div>

 <h2>What this file does (independent of the comments)</h2>
 <div class="card summary">
   <p>{_esc(summary.get('module_summary'))}</p>
   <ul>{''.join(f"<li><code>{_esc(s['symbol'])}</code> — {_esc(s['purpose'])}</li>" for s in summary.get('symbols', [])) or '<li class=none>no symbol summaries</li>'}</ul>
 </div>

 {sel_html}
 {legib_html}
 {tics_html}
 {bans_html}

 <details class="card ledger"><summary><b>Validated ledger</b> — {len(ledger)} facts (click to expand)</summary>
   <table><tr><th>fact (telegraphic stub)</th><th>sites</th><th>lenses</th><th>conf</th></tr>{ledger_rows}</table>
 </details>

 <h2>Per-symbol: before → after</h2>
 <div class="card">{''.join(rows)}</div>
"""
    meta = {"file": fname, "final": final, "hash": fhash, "symbols": len(after),
            "ledger": len(ledger), "verdict_ok": verdict_ok,
            "n_flags": len(flags) + len(tflags), "n_passes": n_passes}
    return section, meta


def selbar_html(hint):
    # one slim row at rest; the blob textarea + the hand-back hint live behind the disclosure so the
    # sticky bar costs minimal height (Submit/Copy carry the blob without showing it)
    return f"""
 <div class="card selbar">
   <div class="row">
     <span class="grow" id="devcount">all suggested</span>
     <button class="ghost" id="resetbtn">Reset to suggested</button>
     <button class="primary" id="submitbtn" hidden>Submit to session</button>
     <button class="primary" id="copybtn">Copy selection</button>
   </div>
   <details class="blobwrap"><summary>selection blob + how to hand it back</summary>
   <textarea id="blob" readonly></textarea>
   <div class="sub" style="margin:8px 0 0">{hint}</div>
   </details>
 </div>"""


def write_page(out_path, title_html, body_html, run_key, gen, script=None, extra_css=""):
    doc = f"""<!doctype html><html><head><meta charset="utf-8">
<title>{title_html}</title>
{THEME_BOOT}
<style>{CSS}{extra_css}</style></head><body>
<button class="themebtn" id="themebtn" title="toggle light/dark (remembered)"></button>
<div class="wrap">
{body_html}
</div>
<script>window.DATA = {{run: {json.dumps(run_key)}, gen: {json.dumps(gen)}}};</script>
{THEME_JS}
{script if script is not None else SCRIPT}
</body></html>"""
    open(out_path, "w").write(doc)
    url = f"file://{out_path}"
    if os.environ.get("REGEN_NO_OPEN"):  # a serve_report.py session owns the open; re-renders just rewrite the file
        return url, False
    try:
        opened = webbrowser.open(url)  # best-effort; no-op on headless/SSH
    except Exception:  # noqa: BLE001
        opened = False
    return url, opened


def main():
    rundir = os.path.abspath(sys.argv[1])
    voice = sys.argv[2]
    original = os.path.abspath(sys.argv[3])

    section, meta = build_file_section(rundir, voice, original, ns="f0")
    hint = ("Pick per symbol above (the suggested take is pre-checked), edit any docstring directly, then "
            "hit Submit to session (shown when the page is served) or copy this blob and paste it back into "
            "the Claude session — or just describe what you want in chat.")
    body = (f" <h1>regen-comments — <code>{_esc(meta['file'])}</code></h1>"
            + section + selbar_html(hint)
            + f"<div class='sub' style='margin-top:18px'>The finished file is <code>{_esc(meta['final'])}</code>. "
              f"Apply it to your working tree, then review the diff in your editor.</div>")

    out = os.path.join(rundir, "report.html")
    url, opened = write_page(out, f"regen-comments report — {_esc(meta['file'])}",
                             body, os.path.basename(rundir), meta["hash"])
    print("=== REPORT WRITTEN ===")
    print(f"  {out}")
    print(f"  {url}")
    print("  " + ("opened in your browser." if opened else "open the link above in a browser to review it."))
    print(f"  symbols: {meta['symbols']}   ledger facts: {meta['ledger']}   "
          f"validator: {'clean' if meta['verdict_ok'] else 'flagged'}")
    print(f"  picker: {meta['n_passes']} cached passes offered per symbol; "
          f"Submit (served page) or paste the Copy-selection blob back to apply picks/edits")


if __name__ == "__main__":
    main()
