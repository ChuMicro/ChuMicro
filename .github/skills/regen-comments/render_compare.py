#!/usr/bin/env python3
"""Render an up-to-3-voice comparison report (mechanical, no LLM).

For each symbol, shows the independent summarizer's plain-English purpose (the bar the human checks against) and
then each voice's docstring side by side, so the human can compare voices and pick one to apply. Per voice it
also surfaces the selection rationale (pick.json) and any legibility flags. Each voice card carries a pick
radio + a notes box; a Copy-selection button serializes the winner into a paste-back blob
(`regen-comments voice (<file>): <key>`) the orchestrator reads, then renders THAT voice's interactive
decision page (picker.html, per-symbol options) from its room.

This file owns the bespoke page machinery (write_page + theme + base CSS): same light/dark theme (OS default, toggle remembered) and the
same staleness rule — the saved pick keys on a combined content hash of every voice's FINAL, so a reload
mid-review restores it but a regenerated voice starts the page clean.

Usage: render_compare.py <rundir> <target.py> <voice1> [voice2] [voice3]
Each voice's outputs are read from <rundir>/v/<voice>/ (see regen_phase2_multi.py).
"""
import ast
import hashlib
import html
import json
import os
import sys
import webbrowser

SKILL = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILL)


# Page machinery moved here from the pre-shared-picker render_report.py: compare.html is its
# only remaining consumer (the decision page renders via webui/render_picker.py).
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


def write_page(out_path, title_html, body_html, run_key, gen, script, extra_css=""):
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
{script}
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

def _load(path, default):
    try:
        return json.load(open(path))
    except Exception:
        return default


def _symbols(src):
    """Ordered qualified names: <module> then every class / function / method."""
    tree = ast.parse(src)
    out = ["<module>"]

    def walk(node, prefix):
        for c in ast.iter_child_nodes(node):
            if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                q = prefix + c.name
                out.append(q)
                walk(c, q + ".")
    walk(tree, "")
    return out


def _doc(tree, qual):
    if qual == "<module>":
        return ast.get_docstring(tree) or ""
    node = tree
    for p in qual.split("."):
        node = next((c for c in ast.iter_child_nodes(node)
                     if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and c.name == p), None)
        if node is None:
            return "(not present)"
    return ast.get_docstring(node) or "(none)"


EXTRA_CSS = """
 .cards{display:flex;gap:12px;margin:10px 0 6px} .cards .card{flex:1}
 .cv{font-weight:700;font-size:14px;font-family:ui-monospace,Menlo,monospace}
 .vwhy,.vconcern{font-size:12px;margin-top:5px} .vconcern{color:var(--amber);font-weight:600}
 .vflags{margin-top:6px}
 .vflag{font-size:12px;background:var(--leak-bg);border:1px solid var(--border);border-radius:5px;padding:4px 7px;margin:3px 0;color:var(--fg)}
 .vok{font-size:12px;color:var(--green)}
 .vpick{display:block;margin-top:10px;font-size:13px;cursor:pointer}
 .vnotes{width:100%;font:inherit;font-size:12px;border:1px dashed var(--border2);border-radius:5px;padding:5px 7px;margin-top:6px;box-sizing:border-box;min-height:30px;background:var(--pre-bg);color:var(--fg)}
 h2.symh{font-family:ui-monospace,Menlo,monospace;font-size:14px;margin:22px 0 6px}
 .bar{background:var(--sig-bg);border:1px solid var(--sig-border);border-radius:6px;padding:7px 10px;margin:6px 0;font-size:13px;color:var(--sig-fg)}
 .vrow{display:flex;gap:10px;align-items:flex-start} .vc{flex:1;min-width:0;padding-left:8px}
 .vn{font-weight:700;font-size:12px;font-family:ui-monospace,Menlo,monospace}
"""

VOICE_SCRIPT = """
<script>
(function () {
  var KEY = 'regen-comments-voice:' + ((window.DATA && window.DATA.run) || 'x') + ':' + ((window.DATA && window.DATA.gen) || '');
  var FILE = (window.DATA && window.DATA.file) || '';
  function load() { try { return JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) { return {}; } }
  function save(s) { try { localStorage.setItem(KEY, JSON.stringify(s)); } catch (e) {} }
  var state = load();
  var radios = document.querySelectorAll('input[name=voicepick]');
  var notes = document.querySelectorAll('textarea.vnotes');
  radios.forEach(function (r) { if (state.v === r.value) r.checked = true; });
  notes.forEach(function (t) { var v = state['n' + t.dataset.voice]; if (v) t.value = v; });
  function picked() {
    var p = null;
    radios.forEach(function (r) { if (r.checked) p = r.value; });
    return p;
  }
  function buildBlob() {
    var p = picked();
    var blob = 'regen-comments voice (' + FILE + '): ' + (p || '(no voice selected)');
    var noteLines = [];
    notes.forEach(function (t) { if (t.value.trim()) noteLines.push('#note ' + t.dataset.voice + ': ' + t.value.trim().replace(/\\n/g, ' ')); });
    if (noteLines.length) blob += '\\n\\n' + noteLines.join('\\n');
    return blob;
  }
  function persist() {
    var s = {};
    var p = picked(); if (p) s.v = p;
    notes.forEach(function (t) { if (t.value.trim()) s['n' + t.dataset.voice] = t.value; });
    save(s); refresh();
  }
  function refresh() {
    var p = picked();
    document.getElementById('vstate').textContent = p ? ('apply: ' + p) : 'no voice selected';
    document.getElementById('blob').value = buildBlob();
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
  radios.forEach(function (r) { r.addEventListener('change', persist); });
  notes.forEach(function (t) { t.addEventListener('input', persist); });
  document.getElementById('copybtn').addEventListener('click', copy);
  // Submit posts the same blob to the serving session; a file:// page has no server, so it stays hidden.
  var sb = document.getElementById('submitbtn');
  if (sb) {
    if (location.protocol === 'http:' || location.protocol === 'https:') sb.hidden = false;
    sb.addEventListener('click', submitSel);
  }
  refresh();
})();
</script>"""


def main():
    rundir = os.path.abspath(sys.argv[1])
    target = sys.argv[2]
    voices = sys.argv[3:6]
    def esc(s):
        return html.escape(s or "")
    syms = _symbols(open(target).read())
    fname = os.path.basename(target)

    # summarizer bar is voice-independent; read it from whichever voice room has it
    summary = {}
    for v in voices:
        s = _load(os.path.join(rundir, "v", v, "summary.json"), None)
        if s:
            summary = s
            break
    bar = {x["symbol"]: x["purpose"] for x in summary.get("symbols", [])}
    bar["<module>"] = summary.get("module_summary", "")

    colors = ["#3b82d6", "#3d9e62", "#d3528e"]
    trees, picks, flags, hashes = {}, {}, {}, []
    for v in voices:
        f = os.path.join(rundir, "v", v, f"FINAL_{v}.py")
        if os.path.exists(f):
            data = open(f, "rb").read()
            hashes.append(hashlib.sha1(data).hexdigest())
            trees[v] = ast.parse(data.decode())
        else:
            trees[v] = None
        picks[v] = _load(os.path.join(rundir, "v", v, "pick.json"), {})
        # a voice's flags = legibility (LLM watcher) + tics/leaks (deterministic watcher), shown together
        flags[v] = (_load(os.path.join(rundir, "v", v, "legibility.json"), {}).get("flags", [])
                    + [{"symbol": f.get("symbol"), "sentence": f.get("text"),
                        "why": f"{f.get('kind')}: {f.get('why')}"}
                       for f in _load(os.path.join(rundir, "v", v, "tics.json"), {}).get("flags", [])])
    gen = hashlib.sha1("".join(hashes).encode()).hexdigest()[:10]

    # per-voice header cards (rationale + legibility flags + the pick radio)
    cards = []
    for i, v in enumerate(voices):
        c = colors[i % len(colors)]
        fl = flags[v]
        flag_html = "".join(f"<div class=vflag><b>{esc(f.get('symbol', ''))}:</b> {esc(f.get('sentence', ''))} "
                            f"<i>({esc(f.get('why', ''))})</i></div>" for f in fl) or "<div class=vok>no legibility flags</div>"
        concern = picks[v].get("concern", "")
        cards.append(
            f"<div class=card style='border-top:4px solid {c}'><div class=cv style='color:{c}'>{esc(v)}</div>"
            f"<div class=vwhy><b>why this pass won:</b> {esc(picks[v].get('why', ''))}</div>"
            + (f"<div class=vconcern><b>selector concern:</b> {esc(concern)}</div>" if concern else "")
            + f"<div class=vflags>{flag_html}</div>"
            f"<label class=vpick><input type=radio name=voicepick value='{esc(v)}'> apply <b>{esc(v)}</b></label>"
            f"<textarea class=vnotes data-voice='{esc(v)}' placeholder='notes on {esc(v)} (ride back with the pick)…'></textarea>"
            f"</div>")

    # per-symbol comparison
    sections = []
    for sym in syms:
        cells = "".join(
            f"<div class=vc style='border-left:3px solid {colors[i % len(colors)]}'>"
            f"<div class=vn style='color:{colors[i % len(colors)]}'>{esc(v)}</div>"
            f"<pre>{esc(_doc(trees[v], sym)) if trees[v] else '(no FINAL)'}</pre></div>"
            for i, v in enumerate(voices))
        sections.append(
            f"<h2 class=symh>{esc(sym)}</h2>"
            f"<div class=bar><b>summarizer:</b> {esc(bar.get(sym, ''))}</div>"
            f"<div class=vrow>{cells}</div>")

    body = (f"<h1>Voice comparison — <code>{esc(fname)}</code> "
            f"<span style='font-weight:400;font-size:13px;color:var(--muted)'>(pick one to apply)</span></h1>"
            f"<div class=cards>{''.join(cards)}</div>"
            + "".join(sections)
            + """
 <div class="card selbar">
   <div class="row"><span class="grow" id="vstate">no voice selected</span><button class="primary" id="submitbtn" hidden>Submit to session</button><button class="primary" id="copybtn">Copy selection</button></div>
   <details class="blobwrap"><summary>selection blob + how to hand it back</summary>
   <textarea id="blob" readonly></textarea>
   <div class="sub" style="margin:8px 0 0">Pick a voice above, then Submit to session (when served) or copy this blob and paste it back into the Claude session — the per-symbol picker report for that voice comes next.</div>
   </details>
 </div>""")

    out = os.path.join(rundir, "compare.html")
    url, opened = write_page(out, f"voice comparison — {esc(fname)}", body,
                             os.path.basename(rundir), gen, script=VOICE_SCRIPT, extra_css=EXTRA_CSS)
    # window.DATA.file rides separately for the blob header
    src = open(out).read().replace('window.DATA = {', f'window.DATA = {{file: {json.dumps(fname)}, ', 1)
    open(out, "w").write(src)
    print(f"{url}")
    print("  " + ("opened in your browser." if opened else "open the link above in a browser to review it."))


if __name__ == "__main__":
    main()
