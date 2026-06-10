#!/usr/bin/env python3
"""Render an up-to-3-voice comparison report (mechanical, no LLM).

For each symbol, shows the independent summarizer's plain-English purpose (the bar the human checks against) and
then each voice's docstring side by side, so the human can compare voices and pick one to apply. Per voice it
also surfaces the selection rationale (pick.json) and any legibility flags. Each voice card carries a pick
radio + a notes box; a Copy-selection button serializes the winner into a paste-back blob
(`regen-comments voice (<file>): <key>`) the orchestrator reads, then renders THAT voice's interactive
report.html (per-symbol picker) from its room.

Built on render_report's shared page machinery: same light/dark theme (OS default, toggle remembered) and the
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

SKILL = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILL)
from render_report import write_page  # noqa: E402


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
    var ta = document.getElementById('blob'); ta.value = blob; ta.select();
    var done = function () { var b = document.getElementById('copybtn'); var o = b.textContent; b.textContent = 'copied \\u2713'; setTimeout(function () { b.textContent = o; }, 1400); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(blob).then(done, function () { try { document.execCommand('copy'); done(); } catch (e) {} });
    } else { try { document.execCommand('copy'); done(); } catch (e) {} }
  }
  radios.forEach(function (r) { r.addEventListener('change', persist); });
  notes.forEach(function (t) { t.addEventListener('input', persist); });
  document.getElementById('copybtn').addEventListener('click', copy);
  refresh();
})();
</script>"""


def main():
    rundir = os.path.abspath(sys.argv[1])
    target = sys.argv[2]
    voices = sys.argv[3:6]
    esc = lambda s: html.escape(s or "")
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
   <div class="row"><span class="grow" id="vstate">no voice selected</span><button class="primary" id="copybtn">Copy selection</button></div>
   <textarea id="blob" readonly></textarea>
   <div class="sub" style="margin:8px 0 0">Pick a voice above, then copy this blob and paste it back into the Claude session — the per-symbol picker report for that voice comes next.</div>
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
