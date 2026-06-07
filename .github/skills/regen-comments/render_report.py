#!/usr/bin/env python3
"""Mechanical HTML report for a completed regen-comments run (no LLM).

Builds report.html from a finished run room so the human can judge CORRECTNESS, not just voice:
  1. an INDEPENDENT plain-English summary (summary.json — written from the code, never from the comments),
     so the reader has a higher-level description to check the comments against;
  2. the validated ledger (ledger.json) + the validator verdict (validation.json);
  3. per-symbol BEFORE/AFTER docstrings (original target vs the finished file);
  4. the consolidation rationale (picks.json) + the ledger facts that pertain to each symbol.

Code/correctness-first by design: voice is the least of what this surfaces. The finished file itself is the
deliverable the human applies; this report is the why behind it.

Usage: render_report.py <rundir> <voice> <original_target.py>  ->  writes <rundir>/report.html
"""
import ast
import html
import json
import os
import sys


def _docstrings(path):
    """{qualname: (docstring_or_None, lineno)} for the module + every class / function / method."""
    tree = ast.parse(open(path).read())
    out = {"<module>": (ast.get_docstring(tree), 0)}

    def walk(node, prefix):
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                q = prefix + child.name
                out[q] = (ast.get_docstring(child), child.lineno)
                if isinstance(child, ast.ClassDef):
                    walk(child, q + ".")

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


def main():
    rundir = os.path.abspath(sys.argv[1])
    voice = sys.argv[2]
    original = os.path.abspath(sys.argv[3])

    final = os.path.join(rundir, f"FINAL_{voice}.py")
    if not os.path.exists(final):
        final = os.path.join(rundir, "merged.py")
    summary = _load(os.path.join(rundir, "summary.json"), {"module_summary": "", "symbols": []})
    ledger = _load(os.path.join(rundir, "ledger.json"), [])
    val = _load(os.path.join(rundir, "validation.json"), {})
    picks_raw = _load(os.path.join(rundir, "picks.json"), [])
    picks = picks_raw.get("picks", []) if isinstance(picks_raw, dict) else picks_raw
    libfacts = os.path.join(rundir, "LIBRARY_FACTS.md")
    has_lib = os.path.exists(libfacts)

    before = _docstrings(original)
    after = _docstrings(final)
    purpose = {s["symbol"]: s["purpose"] for s in summary.get("symbols", [])}
    pick = {}
    for p in picks:
        sym = p.get("symbol", "")
        pick[sym] = p
        pick[_short(sym)] = p  # also index by short name for loose matching
        if "module" in sym.lower():
            pick["<module>"] = p  # judges label this "module docstring"; map to the module row

    verdict_ok = not (val.get("any_wrong") or val.get("any_underspecified"))
    badge = ("ledger validated clean" if verdict_ok else "validator flagged issues — see facts")
    badge_cls = "ok" if verdict_ok else "warn"

    rows = []
    for qual, (doc_after, _) in after.items():
        doc_before = before.get(qual, (None, 0))[0]
        pur = purpose.get(qual) or purpose.get(_short(qual)) or ""
        facts = _facts_for(qual, ledger)
        pk = pick.get(qual) or pick.get(_short(qual))
        fact_html = "".join(
            f"<li><code>{_esc(f.get('stub'))}</code> "
            f"<span class='meta'>({_esc(f.get('confidence'))}, {_esc(','.join(f.get('source_lenses', [])))})</span></li>"
            for f in facts) or "<li class='none'>none mapped to this symbol</li>"
        why = f"<div class='why'><b>pick:</b> {_esc(pk['why'])} <span class='meta'>(pass {pk['winner']})</span></div>" if pk else ""
        rows.append(f"""
        <div class="sym">
          <h3>{_esc(qual)}</h3>
          {f'<div class="purpose">{_esc(pur)}</div>' if pur else ''}
          <div class="ba">
            <div class="col"><div class="lbl">before</div><pre>{_esc(doc_before) or '<span class=none>(no docstring)</span>'}</pre></div>
            <div class="col"><div class="lbl">after</div><pre>{_esc(doc_after) or '<span class=none>(no docstring)</span>'}</pre></div>
          </div>
          <details><summary>ledger facts + rationale</summary>
            <ul class="facts">{fact_html}</ul>{why}
          </details>
        </div>""")

    ledger_rows = "".join(
        f"<tr><td><code>{_esc(f.get('stub'))}</code></td><td>{_esc(f.get('sites'))}</td>"
        f"<td>{_esc(','.join(f.get('source_lenses', [])))}</td><td class='c-{_esc(f.get('confidence'))}'>{_esc(f.get('confidence'))}</td></tr>"
        for f in ledger) or "<tr><td colspan=4 class=none>empty ledger</td></tr>"

    doc = f"""<!doctype html><html><head><meta charset="utf-8">
<title>regen-comments report — {_esc(os.path.basename(original))}</title>
<style>
 body{{font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#f6f7f9;color:#1c2330}}
 .wrap{{max-width:1000px;margin:0 auto;padding:24px}}
 h1{{font-size:20px;margin:0 0 4px}} h2{{font-size:16px;margin:28px 0 10px;border-bottom:1px solid #d7dbe0;padding-bottom:4px}}
 h3{{font-size:14px;margin:0 0 6px;font-family:ui-monospace,Menlo,monospace;color:#0b4f8a}}
 .sub{{color:#5a6472;margin-bottom:16px}}
 .badge{{display:inline-block;padding:2px 10px;border-radius:10px;font-weight:600;font-size:12px}}
 .badge.ok{{background:#d9f2e0;color:#1a7a3c}} .badge.warn{{background:#fde4d3;color:#9a4a10}}
 .card{{background:#fff;border:1px solid #e2e6ea;border-radius:8px;padding:16px;margin-bottom:14px}}
 .summary p{{margin:0 0 10px}} .summary ul{{margin:0;padding-left:18px}} .summary li{{margin:2px 0}}
 .summary code{{color:#0b4f8a}}
 table{{width:100%;border-collapse:collapse}} td,th{{text-align:left;padding:6px 8px;border-bottom:1px solid #eef0f3;vertical-align:top}}
 th{{font-size:12px;color:#5a6472;text-transform:uppercase;letter-spacing:.03em}}
 code{{font-family:ui-monospace,Menlo,monospace;font-size:12.5px}}
 .c-high{{color:#1a7a3c;font-weight:600}} .c-med{{color:#9a6a10}} .c-low{{color:#a23}}
 .sym{{border-top:1px solid #eef0f3;padding:14px 0}}
 .purpose{{color:#33405a;margin-bottom:8px}}
 .ba{{display:flex;gap:12px}} .col{{flex:1;min-width:0}} .lbl{{font-size:11px;color:#8a93a0;text-transform:uppercase}}
 pre{{white-space:pre-wrap;word-break:break-word;background:#fafbfc;border:1px solid #eef0f3;border-radius:6px;padding:8px;margin:4px 0;font-size:12.5px}}
 .none{{color:#aab1bb;font-style:italic}}
 details{{margin-top:6px}} summary{{cursor:pointer;color:#5a6472;font-size:12px}}
 .facts{{margin:8px 0;padding-left:18px}} .facts .meta{{color:#8a93a0}}
 .why{{margin-top:6px;color:#33405a}}
</style></head><body><div class="wrap">
 <h1>regen-comments — <code>{_esc(os.path.basename(original))}</code></h1>
 <div class="sub">voice: <b>{_esc(voice)}</b> · <span class="badge {badge_cls}">{_esc(badge)}</span>{' · library-aware' if has_lib else ''}</div>

 <h2>What this file does (independent of the comments)</h2>
 <div class="card summary">
   <p>{_esc(summary.get('module_summary'))}</p>
   <ul>{''.join(f"<li><code>{_esc(s['symbol'])}</code> — {_esc(s['purpose'])}</li>" for s in summary.get('symbols', [])) or '<li class=none>no symbol summaries</li>'}</ul>
 </div>

 <h2>Validated ledger</h2>
 <div class="card">
   <table><tr><th>fact (telegraphic stub)</th><th>sites</th><th>lenses</th><th>conf</th></tr>{ledger_rows}</table>
 </div>

 <h2>Per-symbol: before → after</h2>
 <div class="card">{''.join(rows)}</div>

 <div class="sub" style="margin-top:18px">The finished file is <code>{_esc(final)}</code>. Apply it to your working tree, then review the diff in your editor.</div>
</div></body></html>"""

    out = os.path.join(rundir, "report.html")
    open(out, "w").write(doc)
    print("=== REPORT WRITTEN ===")
    print(f"  {out}")
    print(f"  file://{out}")
    print(f"  symbols: {len(after)}   ledger facts: {len(ledger)}   validator: {'clean' if verdict_ok else 'flagged'}")


if __name__ == "__main__":
    main()
