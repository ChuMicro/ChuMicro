#!/usr/bin/env python3
"""Render a generic decision page (picker.html) from a JSON spec.

One card per item, each with a radio group, an optional notes box, and a sticky
selection bar that serializes every choice into a line-oriented paste-back blob:

    PICKS — <blob_header>
    1 = apply
      note 1: <free text, newlines collapsed>
    2 = skip

The page is self-contained (inline CSS + JS) and works from file:// — Copy
selection always works; a Submit button appears only when the page is served
over http (see serve_picker.py, which loops the POST back to the session).
Choices and notes persist in localStorage under the spec's `key`, so a reload
mid-review restores them.

Spec schema:

    {
      "title": "audit-skill report — git-commit",        // page heading
      "key": "audit-skill:git-commit:20260611T",          // localStorage namespace; change per run
      "blob_header": "audit-skill picks (git-commit)",    // first blob line after "PICKS — "
      "intro_html": "<p>…</p>",                           // optional block above the cards (trusted HTML)
      "options": ["apply", "edit", "discuss", "skip"],    // page-wide option set
      "default": "skip",                                  // pre-checked option (omit for none)
      "items": [
        {
          "id": "1",                                      // rides back in the blob; unique
          "title": "[IMPORTANT · loader] vague stem",     // card heading (escaped)
          "badge": "IMPORTANT",                           // optional pill; known severities get colors
          "body_html": "<pre>evidence…</pre>",            // card body (trusted HTML from the orchestrator)
          "options": ["high", "medium", "low"],           // optional per-item override
          "default": "medium",                            // optional per-item override
          "notes": true                                   // notes box (default true)
        }
      ]
    }

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
    "low": "b-minor",
}

CSS = """
 :root{color-scheme:light dark;
  --bg:#f4f6f9; --fg:#1c2230; --faint:#6b7280; --card:#ffffff; --border:#dfe4ec;
  --accent:#4f46e5; --blob-bg:#f8fafc; --bar:#ffffffeb; --note-bg:#fbfcfe}
 @media (prefers-color-scheme: dark){:root{
  --bg:#11141b; --fg:#e3e7f0; --faint:#8a93a6; --card:#1a1f29; --border:#2a3242;
  --accent:#8d97ff; --blob-bg:#11141b; --bar:#1a1f29eb; --note-bg:#161b24}}
 body{font:15px/1.55 -apple-system,'Segoe UI',sans-serif;background:var(--bg);color:var(--fg);
  margin:0;padding:26px 20px 130px;max-width:900px;margin-inline:auto}
 h1{font-size:20px;margin:0 0 6px}
 .intro{color:var(--faint);font-size:13.5px;margin-bottom:18px}
 .intro pre{white-space:pre-wrap}
 .card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:14px 16px;margin:12px 0}
 .cardhead{display:flex;align-items:baseline;gap:9px;flex-wrap:wrap}
 .cardid{font-weight:700;color:var(--accent)}
 .cardtitle{font-weight:620}
 .badge{font-size:10.5px;font-weight:700;letter-spacing:.4px;padding:2px 8px;border-radius:999px;color:#fff;background:#64748b}
 .b-critical{background:#dc2626} .b-important{background:#d97706} .b-minor{background:#64748b} .b-ambiguous{background:#7c3aed}
 .cardbody{margin:9px 0 2px;font-size:13.5px}
 .cardbody pre{white-space:pre-wrap;background:var(--blob-bg);border:1px solid var(--border);border-radius:8px;padding:8px 10px;font-size:12px}
 .opts{display:flex;gap:14px;flex-wrap:wrap;margin-top:10px}
 .opts label{cursor:pointer;display:flex;align-items:center;gap:5px;font-size:13.5px}
 .opts input{accent-color:var(--accent)}
 .notes{width:100%;box-sizing:border-box;margin-top:9px;font:12.5px/1.5 inherit;border:1px solid var(--border);
  border-radius:8px;padding:7px 9px;min-height:34px;background:var(--note-bg);color:var(--fg);resize:vertical}
 .selbar{position:fixed;bottom:0;left:0;right:0;background:var(--bar);backdrop-filter:blur(10px);
  border-top:1px solid var(--border);padding:10px 20px;font-size:13px}
 .selbar .row{display:flex;align-items:center;gap:12px;max-width:900px;margin-inline:auto;flex-wrap:wrap}
 .selbar button{font:inherit;padding:6px 14px;border-radius:8px;border:1px solid var(--border);
  background:var(--card);color:var(--fg);cursor:pointer}
 .selbar button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
 #count{color:var(--faint)}
 .blobwrap{max-width:900px;margin-inline:auto}
 .blobwrap>summary{font-size:11.5px;color:var(--faint);cursor:pointer;margin-top:6px}
 .hint{font-size:11.5px;color:var(--faint);margin:6px 0 0}
 #blob{width:100%;box-sizing:border-box;margin-top:8px;font:12px/1.5 ui-monospace,Menlo,monospace;
  border:1px solid var(--border);border-radius:8px;padding:8px;min-height:46px;background:var(--blob-bg);color:var(--fg)}
"""

SCRIPT = """
<script>
(function () {
  var KEY = 'picker:' + (window.SPEC.key || 'x');
  var HEADER = 'PICKS \\u2014 ' + (window.SPEC.blob_header || window.SPEC.key || 'selection');
  function load() { try { return JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) { return {}; } }
  function save(s) { try { localStorage.setItem(KEY, JSON.stringify(s)); } catch (e) {} }
  var cards = Array.prototype.slice.call(document.querySelectorAll('.card'));
  var state = load();
  cards.forEach(function (c) {
    var id = c.dataset.id;
    if (state['p:' + id]) { var r = c.querySelector('input[value="' + state['p:' + id] + '"]'); if (r) r.checked = true; }
    if (state['n:' + id]) { var n = c.querySelector('.notes'); if (n) n.value = state['n:' + id]; }
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
  document.querySelectorAll('.card input[type=radio]').forEach(function (r) { r.addEventListener('change', persist); });
  document.querySelectorAll('.notes').forEach(function (t) { t.addEventListener('input', persist); });
  document.getElementById('copybtn').addEventListener('click', copy);
  var sb = document.getElementById('submitbtn');
  if (location.protocol === 'http:' || location.protocol === 'https:') sb.hidden = false;
  sb.addEventListener('click', submitSel);
  document.getElementById('resetbtn').addEventListener('click', function () {
    cards.forEach(function (c) {
      c.querySelectorAll('input[type=radio]').forEach(function (r) { r.checked = (r.value === c.dataset.def); });
      var n = c.querySelector('.notes'); if (n) n.value = '';
    });
    persist();
  });
  refresh();
})();
</script>
"""


def card_html(item, page_options, page_default):
    item_id = str(item["id"])
    options = item.get("options", page_options)
    default = item.get("default", page_default)
    badge = ""
    if item.get("badge"):
        badge_class = BADGE_CLASSES.get(str(item["badge"]).lower(), "")
        badge = f'<span class="badge {badge_class}">{html.escape(str(item["badge"]))}</span>'
    radios = "".join(
        f'<label><input type="radio" name="pick:{html.escape(item_id)}" value="{html.escape(option)}"'
        f'{" checked" if option == default else ""}> {html.escape(option)}</label>'
        for option in options
    )
    notes = (
        f'<textarea class="notes" placeholder="notes on {html.escape(item_id)} (ride back with the selection)…"></textarea>'
        if item.get("notes", True)
        else ""
    )
    body = f'<div class="cardbody">{item["body_html"]}</div>' if item.get("body_html") else ""
    return (
        f'<div class="card" data-id="{html.escape(item_id)}" data-def="{html.escape(default or "")}">'
        f'<div class="cardhead"><span class="cardid">{html.escape(item_id)}</span>{badge}'
        f'<span class="cardtitle">{html.escape(item.get("title", ""))}</span></div>'
        f"{body}"
        f'<div class="opts">{radios}</div>'
        f"{notes}</div>"
    )


def main():
    spec_path = os.path.abspath(sys.argv[1])
    with open(spec_path) as handle:
        spec = json.load(handle)
    output_dir = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else os.path.dirname(spec_path)

    page_options = spec.get("options", ["apply", "edit", "discuss", "skip"])
    page_default = spec.get("default")
    cards = "\n".join(card_html(item, page_options, page_default) for item in spec["items"])
    intro = f'<div class="intro">{spec["intro_html"]}</div>' if spec.get("intro_html") else ""
    client_spec = json.dumps({"key": spec.get("key", ""), "blob_header": spec.get("blob_header", "")})

    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(spec.get("title", "decision page"))}</title>
<style>{CSS}</style></head>
<body>
<h1>{html.escape(spec.get("title", "decision page"))}</h1>
{intro}
{cards}
<div class="selbar">
 <div class="row">
  <span id="count"></span>
  <button class="primary" id="copybtn">Copy selection</button>
  <button id="submitbtn" hidden>Submit to session</button>
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
