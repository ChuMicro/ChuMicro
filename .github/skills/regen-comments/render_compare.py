#!/usr/bin/env python3
"""Render an up-to-3-voice comparison report (mechanical, no LLM).

For each symbol, shows the independent summarizer's plain-English purpose (the bar the human checks against) and
then each voice's docstring side by side, so the human can compare voices and pick one to apply. Per voice it
also surfaces the selection rationale (pick.json) and any legibility flags. Writes HTML and tries to open it.

Usage: render_compare.py <rundir> <target.py> <voice1> [voice2] [voice3]
Each voice's outputs are read from <rundir>/v/<voice>/ (see regen_phase2_multi.py).
"""
import ast
import html
import json
import os
import subprocess
import sys


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


def main():
    rundir = os.path.abspath(sys.argv[1])
    target = sys.argv[2]
    voices = sys.argv[3:6]
    esc = lambda s: html.escape(s or "")
    syms = _symbols(open(target).read())

    # summarizer bar is voice-independent; read it from whichever voice room has it
    summary = {}
    for v in voices:
        s = _load(os.path.join(rundir, "v", v, "summary.json"), None)
        if s:
            summary = s
            break
    bar = {x["symbol"]: x["purpose"] for x in summary.get("symbols", [])}
    bar["<module>"] = summary.get("module_summary", "")

    colors = ["#1565c0", "#2e7d32", "#c2185b"]
    trees, picks, flags = {}, {}, {}
    for v in voices:
        f = os.path.join(rundir, "v", v, f"FINAL_{v}.py")
        trees[v] = ast.parse(open(f).read()) if os.path.exists(f) else None
        picks[v] = _load(os.path.join(rundir, "v", v, "pick.json"), {})
        flags[v] = _load(os.path.join(rundir, "v", v, "legibility.json"), {}).get("flags", [])

    # per-voice header cards (rationale + legibility flags)
    cards = []
    for i, v in enumerate(voices):
        c = colors[i % len(colors)]
        fl = flags[v]
        flag_html = "".join(f"<div class=flag><b>{esc(f.get('symbol',''))}:</b> {esc(f.get('sentence',''))} "
                            f"<i>({esc(f.get('why',''))})</i></div>" for f in fl) or "<div class=ok>no legibility flags</div>"
        concern = picks[v].get("concern", "")
        cards.append(
            f"<div class=card style='border-top:4px solid {c}'><div class=cv style='color:{c}'>{esc(v)}</div>"
            f"<div class=why><b>why this pass won:</b> {esc(picks[v].get('why',''))}</div>"
            + (f"<div class=concern><b>selector concern:</b> {esc(concern)}</div>" if concern else "")
            + f"<div class=flags>{flag_html}</div></div>")

    # per-symbol comparison
    sections = []
    for sym in syms:
        cells = "".join(
            f"<div class=vc style='border-left:3px solid {colors[i%len(colors)]}'>"
            f"<div class=vn style='color:{colors[i%len(colors)]}'>{esc(v)}</div>"
            f"<pre>{esc(_doc(trees[v], sym)) if trees[v] else '(no FINAL)'}</pre></div>"
            for i, v in enumerate(voices))
        sections.append(
            f"<h2>{esc(sym)}</h2>"
            f"<div class=bar><b>summarizer:</b> {esc(bar.get(sym,''))}</div>"
            f"<div class=row>{cells}</div>")

    doc = f"""<!doctype html><meta charset=utf-8><title>voice comparison — {esc(os.path.basename(target))}</title>
<style>body{{font:14px/1.5 -apple-system,Segoe UI,sans-serif;max-width:1180px;margin:0 auto;padding:22px;color:#1c2330}}
h1{{font-size:19px}} h2{{font-size:14px;margin:22px 0 6px;border-bottom:2px solid #e2e6ea;font-family:ui-monospace,Menlo,monospace}}
.cards{{display:flex;gap:12px;margin:10px 0 6px}} .card{{flex:1;background:#fff;border:1px solid #d7dde6;border-radius:8px;padding:10px}}
.cv{{font-weight:700;font-size:14px;font-family:ui-monospace,Menlo,monospace}} .why,.concern{{font-size:12px;margin-top:5px}} .concern{{color:#a4441a}}
.flags{{margin-top:6px}} .flag{{font-size:12px;background:#fff3f3;border:1px solid #f0c8c8;border-radius:5px;padding:4px 7px;margin:3px 0}} .ok{{font-size:12px;color:#2e7d32}}
.bar{{background:#fff8e6;border:1px solid #f0e0a8;border-radius:6px;padding:7px 10px;margin:6px 0;font-size:13px}}
.row{{display:flex;gap:10px;align-items:flex-start}} .vc{{flex:1;min-width:0;padding-left:8px}} .vn{{font-weight:700;font-size:12px;font-family:ui-monospace,Menlo,monospace}}
pre{{white-space:pre-wrap;word-break:break-word;background:#f8fafc;border:1px solid #e6ebf0;border-radius:5px;padding:8px;margin:3px 0;font:12px/1.5 ui-monospace,Menlo,monospace}}</style>
<h1>Voice comparison — {esc(os.path.basename(target))} <span style='font-weight:400;font-size:13px;color:#667'>(pick one to apply)</span></h1>
<div class=cards>{''.join(cards)}</div>
{''.join(sections)}"""
    out = os.path.join(rundir, "compare.html")
    open(out, "w").write(doc)
    print(f"file://{out}")
    try:
        subprocess.run(["open", out], check=False)
    except Exception:
        pass


if __name__ == "__main__":
    main()
