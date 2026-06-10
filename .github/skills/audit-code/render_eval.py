#!/usr/bin/env python3
"""audit-code — render the evaluation as an interactive HTML document and open it.

Reads the run room's eval.json + summary.json + validation.json + patches.json + (optional) voiced.json +
phase1.json and builds one self-contained HTML file. Each finding leads with a plain "Why it bites"
consequence, keeps the mechanism detail in a collapsible "deeper" panel, and shows the proposed patch as a
red/green before-after diff. When a voice was chosen, the prose is the voiced version. Each finding has a
checkbox + a notes box; the page persists those to localStorage and a Copy-selection button assembles the
line the human pastes back to apply the chosen fixes. The static content renders without JavaScript; the
checkboxes, notes, and copy button are the only scripted layer.

Usage: render_eval.py <rundir> <target.py>   # writes <rundir>/eval.html and opens it
"""
import html
import json
import os
import subprocess
import sys

SEV_RANK = {"high": 0, "med": 1, "low": 2}
EFFORT_RANK = {"small": 0, "medium": 1, "large": 2}

STYLE = """
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, system-ui, "Segoe UI", sans-serif; margin: 0; padding: 0 0 90px;
         color: #1c1c1e; background: #f5f5f7; line-height: 1.5; }
  .wrap { max-width: 960px; margin: 0 auto; padding: 24px 20px; }
  h1 { font-size: 21px; margin: 0 0 2px; }
  h2 { font-size: 16px; margin: 26px 0 10px; color: #3a3a3c; border-bottom: 1px solid #e2e2e7; padding-bottom: 5px; }
  .sub { color: #6e6e73; font-size: 13px; margin-bottom: 14px; }
  .card { background: #fff; border: 1px solid #e2e2e7; border-radius: 10px; padding: 14px 16px; margin: 10px 0;
          box-shadow: 0 1px 2px rgba(0,0,0,.03); }
  .fcard { display: flex; gap: 12px; align-items: flex-start; }
  .fcard.sev-high { border-left: 4px solid #d6334a; }
  .fcard.sev-med  { border-left: 4px solid #d98324; }
  .fcard.sev-low  { border-left: 4px solid #9a9aa2; }
  .pick { display: flex; flex-direction: column; align-items: center; gap: 4px; padding-top: 2px; }
  .pick input { width: 20px; height: 20px; cursor: pointer; }
  .fnum { font-weight: 700; font-size: 15px; color: #1c1c1e; font-variant-numeric: tabular-nums; }
  .fbody { flex: 1; min-width: 0; }
  .ftitle { font-weight: 600; font-size: 15px; margin: 0 0 4px; }
  .meta { display: flex; flex-wrap: wrap; gap: 6px; margin: 4px 0 8px; align-items: center; }
  .chip { font-size: 11px; padding: 2px 8px; border-radius: 999px; font-weight: 600; white-space: nowrap; }
  .a-trap     { background: #fde2e6; color: #a51427; }
  .a-drift    { background: #efe3fb; color: #6b21a8; }
  .a-coverage { background: #dceafb; color: #1d4ed8; }
  .a-clarity  { background: #dff3e6; color: #1a7f37; }
  .sev-high-b{background:#fbe0e4;color:#b00f28;} .sev-med-b{background:#fcecd8;color:#9a5a13;} .sev-low-b{background:#ececed;color:#5a5a60;}
  .dim { color: #6e6e73; font-size: 12px; }
  .site { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; color: #444; }
  .why { background: #fff4f4; border: 1px solid #f3cfd4; border-radius: 8px; padding: 9px 12px; margin: 6px 0 8px; }
  .why.sev-med  { background: #fff8ef; border-color: #f0dcb6; }
  .why.sev-low  { background: #f6f6f8; border-color: #e3e3e8; }
  .why .lbl { font-size: 10.5px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; color: #b00f28; display: block; margin-bottom: 2px; }
  .why.sev-med .lbl { color: #9a5a13; } .why.sev-low .lbl { color: #5a5a60; }
  details.deeper { margin: 4px 0; } details.deeper > summary { cursor: pointer; font-size: 12.5px; color: #2f6fd0; }
  details.deeper .prose { margin-top: 6px; }
  .fix { background: #f6faf6; border: 1px solid #d8ecdd; border-radius: 7px; padding: 8px 10px; margin: 8px 0 4px; font-size: 13.5px; }
  .fix b { color: #1a7f37; }
  .patch { margin: 8px 0 2px; }
  .patch .plbl { font-size: 11px; font-weight: 700; color: #444; margin-bottom: 3px; }
  pre.diff { margin: 0; font-family: ui-monospace, Menlo, monospace; font-size: 12px; line-height: 1.45;
             border: 1px solid #e0e0e6; border-radius: 7px; overflow-x: auto; background: #fbfbfc; }
  pre.diff .ln { display: block; padding: 0 10px; white-space: pre; }
  pre.diff .del { background: #fdecee; color: #8a1226; } pre.diff .add { background: #e7f7ec; color: #0f7a32; }
  pre.diff .loc { color: #6e6e73; padding: 2px 10px; display:block; font-style: italic; }
  .manual { background: #fff7e6; border: 1px solid #f3dca0; border-radius: 7px; padding: 7px 10px; font-size: 12.5px; }
  .vnote { background: #fff7e6; border: 1px solid #f3dca0; border-radius: 7px; padding: 6px 10px; font-size: 12.5px; margin-top: 6px; }
  .notes { width: 100%; margin-top: 8px; border: 1px solid #d7d7dc; border-radius: 6px; padding: 6px 8px;
           font: inherit; font-size: 13px; resize: vertical; min-height: 34px; background: #fcfcfd; }
  .sym { padding: 10px 14px; } .sym .q { font-family: ui-monospace, Menlo, monospace; font-weight: 600; font-size: 13.5px; }
  .sym .sig { font-family: ui-monospace, Menlo, monospace; font-size: 12px; color: #6e6e73; }
  .sym .fids { margin-top: 4px; } .fid-chip { font-size: 11px; padding: 1px 7px; border-radius: 999px; background:#f1f1f4; color:#333; margin-right: 4px; font-weight:600; }
  .fact { font-size: 13px; margin: 3px 0; }
  .bar { position: fixed; left: 0; right: 0; bottom: 0; background: #1c1c1e; color: #fff; padding: 10px 18px;
         display: flex; gap: 14px; align-items: center; box-shadow: 0 -2px 10px rgba(0,0,0,.18); z-index: 50; }
  .bar .count { font-weight: 600; } .bar button { font: inherit; font-size: 13px; padding: 7px 14px; border-radius: 7px; border: none; cursor: pointer; }
  .bar .primary { background: #2f8cf0; color: #fff; font-weight: 600; } .bar .ghost { background: #3a3a3c; color: #fff; } .bar .grow { flex: 1; }
  .blob { width: 100%; margin-top: 10px; font-family: ui-monospace, Menlo, monospace; font-size: 12px; border: 1px solid #d7d7dc; border-radius: 6px; padding: 8px; min-height: 46px; background:#fafafa; }
  .nofind { color: #1a7f37; font-weight: 600; }
  .badge { font-size: 12px; padding: 3px 10px; border-radius: 999px; font-weight: 600; }
  .ok { background: #dff3e6; color: #1a7f37; } .warn { background: #fcecd8; color: #9a5a13; }
</style>
"""

SCRIPT = """
<script>
(function () {
  var KEY = 'audit-code:' + (window.DATA && window.DATA.target || 'x');
  function load() { try { return JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) { return {}; } }
  function save(s) { try { localStorage.setItem(KEY, JSON.stringify(s)); } catch (e) {} }
  var state = load();
  var checks = document.querySelectorAll('input.pickbox');
  var notes = document.querySelectorAll('textarea.notes');
  checks.forEach(function (c) { if (state['c' + c.dataset.id]) c.checked = true; });
  notes.forEach(function (t) { var v = state['n' + t.dataset.id]; if (v) t.value = v; });
  function persist() {
    var s = {};
    checks.forEach(function (c) { if (c.checked) s['c' + c.dataset.id] = 1; });
    notes.forEach(function (t) { if (t.value.trim()) s['n' + t.dataset.id] = t.value; });
    save(s); refresh();
  }
  function selectedIds() {
    var ids = []; checks.forEach(function (c) { if (c.checked) ids.push(parseInt(c.dataset.id, 10)); });
    ids.sort(function (a, b) { return a - b; }); return ids;
  }
  function noteFor(id) { var t = document.querySelector('textarea.notes[data-id="' + id + '"]'); return t && t.value.trim() ? t.value.trim() : ''; }
  function buildBlob() {
    var ids = selectedIds();
    var line = 'audit-code apply: ' + (ids.length ? ids.join(', ') : '(none selected)');
    var noteLines = [];
    ids.forEach(function (id) { var n = noteFor(id); if (n) noteLines.push('[' + id + '] ' + n.replace(/\\n/g, ' ')); });
    notes.forEach(function (t) {
      var id = parseInt(t.dataset.id, 10);
      if (ids.indexOf(id) === -1 && t.value.trim()) noteLines.push('[' + id + ' note-only] ' + t.value.trim().replace(/\\n/g, ' '));
    });
    if (noteLines.length) line += '\\n\\n# notes\\n' + noteLines.join('\\n');
    return line;
  }
  function refresh() {
    document.getElementById('count').textContent = selectedIds().length + ' selected';
    document.getElementById('blob').value = buildBlob();
  }
  function copy() {
    var blob = buildBlob(); var ta = document.getElementById('blob'); ta.value = blob; ta.select();
    var done = function () { var b = document.getElementById('copybtn'); var o = b.textContent; b.textContent = 'copied \\u2713'; setTimeout(function () { b.textContent = o; }, 1400); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(blob).then(done, function () { try { document.execCommand('copy'); done(); } catch (e) {} });
    } else { try { document.execCommand('copy'); done(); } catch (e) {} }
  }
  checks.forEach(function (c) { c.addEventListener('change', persist); });
  notes.forEach(function (t) { t.addEventListener('input', persist); });
  document.getElementById('copybtn').addEventListener('click', copy);
  document.getElementById('selhigh').addEventListener('click', function () { checks.forEach(function (c) { if (c.dataset.sev === 'high') c.checked = true; }); persist(); });
  document.getElementById('clearall').addEventListener('click', function () { checks.forEach(function (c) { c.checked = false; }); persist(); });
  refresh();
})();
</script>
"""


def _esc(s):
    return html.escape(str(s) if s is not None else "")


def _chip(text, cls):
    return f'<span class="chip {cls}">{_esc(text)}</span>'


def _difflines(text, cls):
    return "".join(f'<span class="ln {cls}">{_esc(line) or "&nbsp;"}</span>' for line in text.rstrip("\n").split("\n"))


def _patch_html(p):
    """Render one patch as a before/after diff (replace), an addition (add), or a manual note."""
    if not p:
        return ""
    kind = p.get("kind")
    loc = p.get("location_hint", "")
    if kind == "manual":
        note = p.get("note") or "This fix is structural — apply it by hand."
        return f'<div class="patch"><div class="plbl">Proposed change (manual)</div><div class="manual">{_esc(note)}</div></div>'
    if kind == "add":
        body = (f'<span class="loc">add{(" in " + _esc(loc)) if loc else ""}:</span>'
                + _difflines(p.get("after", ""), "add"))
        return f'<div class="patch"><div class="plbl">Proposed patch</div><pre class="diff">{body}</pre></div>'
    # replace
    body = _difflines(p.get("before", ""), "del") + _difflines(p.get("after", ""), "add")
    note = f'<div class="dim" style="margin-top:3px">{_esc(p.get("note"))}</div>' if p.get("note") else ""
    return f'<div class="patch"><div class="plbl">Proposed patch</div><pre class="diff">{body}</pre>{note}</div>'


def main():
    rundir, target = os.path.abspath(sys.argv[1]), sys.argv[2]
    def _load(name, default):
        fp = os.path.join(rundir, name)
        return json.load(open(fp)) if os.path.exists(fp) else default

    ev = _load("eval.json", {"findings": [], "domain_facts": []})
    if isinstance(ev, list):
        ev = {"findings": ev, "domain_facts": []}
    summary = _load("summary.json", {"module_summary": "", "symbols": []})
    val = _load("validation.json", {})
    phase1 = _load("phase1.json", {})
    patch_map = {p.get("id"): p for p in _load("patches.json", {"patches": []}).get("patches", [])}
    written = _load("written.json", {"findings": []})
    written_map = {w.get("id"): w for w in (written.get("findings", []) if isinstance(written, dict) else [])}

    findings = ev.get("findings", [])
    # eval.json holds the FACTS (defect / bite / fix fragments); written.json holds the reader PROSE the writer
    # composed in the chosen register. Join the prose onto each finding by id, falling back to the fragments
    # when the writer skipped one, so a finding always renders.
    for f in findings:
        w = written_map.get(f.get("id"), {})
        f["title"] = w.get("title") or (f.get("defect", "") or "finding")[:80]
        f["consequence"] = w.get("consequence") or f.get("bite", "")
        f["problem"] = w.get("problem") or f.get("defect", "")
        f["suggested_fix"] = w.get("suggested_fix") or f.get("fix", "")
    findings.sort(key=lambda f: (SEV_RANK.get(f.get("severity"), 3),
                                 EFFORT_RANK.get(f.get("effort"), 3), f.get("id", 0)))
    vmap = {x.get("id"): x for x in val.get("findings", [])}
    converged = not (val.get("any_unreal") or val.get("any_fix_unsound"))
    fname = os.path.basename(target)
    voice = phase1.get("voice", "plain")

    by_sev = phase1.get("by_severity", {})
    by_angle = phase1.get("by_angle", {})
    sev_line = ", ".join(f"{by_sev[k]} {k}" for k in ("high", "med", "low") if by_sev.get(k))
    angle_line = ", ".join(f"{by_angle[k]} {k}" for k in ("trap", "drift", "coverage", "clarity") if by_angle.get(k))
    badge = ('<span class="badge ok">validated clean</span>' if converged
             else '<span class="badge warn">some findings left unconfirmed — see notes</span>')

    parts = ['<!doctype html><html><head><meta charset="utf-8">',
             f'<title>audit-code: {_esc(fname)}</title>', STYLE, '</head><body><div class="wrap">']
    parts.append(f'<h1>Evaluation — <span class="site">{_esc(fname)}</span> {badge}</h1>')
    parts.append(f'<div class="sub">{len(findings)} findings'
                 + (f' ({sev_line})' if sev_line else '')
                 + (f' · {angle_line}' if angle_line else '')
                 + f' · {phase1.get("n_symbols", len(summary.get("symbols", [])))} symbols'
                 + (f' · voice: {_esc(voice)}' if voice and voice != "plain" else '')
                 + '</div>')

    parts.append('<h2>What this file does <span class="dim">(read from the code, independent of its comments)</span></h2>')
    parts.append(f'<div class="card">{_esc(summary.get("module_summary", "")) or "<span class=dim>(no summary)</span>"}</div>')

    facts = ev.get("domain_facts", [])
    if facts:
        parts.append('<h2>Domain facts <span class="dim">(knowledge the comments carry that the code alone can\'t show)</span></h2>')
        parts.append('<div class="card">')
        for d in facts:
            parts.append(f'<div class="fact">• {_esc(d.get("fact"))} <span class="dim site">({_esc(d.get("source_site"))}, {_esc(d.get("confidence"))})</span></div>')
        parts.append('</div>')

    parts.append('<h2>Findings &amp; proposed fixes <span class="dim">(check the ones to apply; type fix numbers back in the terminal)</span></h2>')
    if not findings:
        parts.append('<div class="card nofind">No findings — the evaluation surfaced nothing worth changing.</div>')
    for f in findings:
        fid = f.get("id")
        sev = f.get("severity", "low")
        v = vmap.get(fid, {})
        vnote = ""
        if v and (not v.get("real", True) or not v.get("fix_sound", True)):
            tag = "problem unconfirmed" if not v.get("real", True) else "fix needs review"
            vnote = f'<div class="vnote"><b>Validator: {tag}.</b> {_esc(v.get("note"))}</div>'
        parts.append(f'<div class="card fcard sev-{sev}">')
        parts.append(f'<div class="pick"><input type="checkbox" class="pickbox" data-id="{fid}" data-sev="{_esc(sev)}"><span class="fnum">{fid}</span></div>')
        parts.append('<div class="fbody">')
        parts.append(f'<div class="ftitle">{_esc(f.get("title"))}</div>')
        parts.append('<div class="meta">'
                     + _chip(f.get("angle"), f'a-{f.get("angle")}')
                     + _chip(f'severity: {sev}', f'sev-{sev}-b')
                     + f'<span class="dim">effort: {_esc(f.get("effort"))} · confidence: {_esc(f.get("confidence"))}</span>'
                     + f'<span class="site dim">· {_esc(f.get("symbol"))} @ {_esc(f.get("site"))}</span>'
                     + '</div>')
        parts.append(f'<div class="why sev-{sev}"><span class="lbl">Why it bites</span>{_esc(f.get("consequence"))}</div>')
        if f.get("problem"):
            parts.append(f'<details class="deeper"><summary>how the code does this</summary><div class="prose">{_esc(f.get("problem"))}</div></details>')
        parts.append(f'<div class="fix"><b>Suggested fix:</b> {_esc(f.get("suggested_fix"))}</div>')
        parts.append(_patch_html(patch_map.get(fid)))
        parts.append(vnote)
        parts.append(f'<textarea class="notes" data-id="{fid}" placeholder="your notes on #{fid} (saved in this page)…"></textarea>')
        parts.append('</div></div>')

    syms = summary.get("symbols", [])
    if syms:
        parts.append('<h2>Per-symbol understanding</h2>')
        fids_by_sym = {}
        for f in findings:
            fids_by_sym.setdefault(f.get("symbol"), []).append(f.get("id"))
        for s in syms:
            q = s.get("qualname", "")
            ids = sorted(fids_by_sym.get(q, []))
            chips = ('<div class="fids">' + "".join(f'<span class="fid-chip">#{i}</span>' for i in ids) + '</div>') if ids else ""
            parts.append('<div class="card sym">'
                         + f'<div class="q">{_esc(q)}</div><div class="sig">{_esc(s.get("signature"))}</div>'
                         + f'<div class="prose">{_esc(s.get("summary"))}</div>' + chips + '</div>')

    parts.append('<textarea id="blob" class="blob" readonly></textarea>')
    parts.append('<div class="bar"><span class="count" id="count">0 selected</span>'
                 '<button class="ghost" id="selhigh">Select all high</button>'
                 '<button class="ghost" id="clearall">Clear</button><span class="grow"></span>'
                 '<button class="primary" id="copybtn">Copy selection</button></div>')
    data_js = json.dumps({"target": os.path.abspath(target)}).replace("<", "\\u003c")
    parts.append(f'<script>window.DATA = {data_js};</script>')
    parts.append(SCRIPT)
    parts.append('</div></body></html>')

    out = os.path.join(rundir, "eval.html")
    open(out, "w", encoding="utf-8").write("\n".join(p for p in parts if p))

    opened = False
    try:
        opened = subprocess.run(["open", out], capture_output=True).returncode == 0
    except Exception:  # noqa: BLE001
        pass
    if not opened:
        try:
            import webbrowser
            webbrowser.open(f"file://{out}")
        except Exception:  # noqa: BLE001
            pass
    print(f"wrote {out}")
    print(f"file://{out}")


if __name__ == "__main__":
    main()
