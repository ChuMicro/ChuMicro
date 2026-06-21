#!/usr/bin/env python3
"""Render the voice-comparison page on the shared picker (mechanical, no LLM).

For an up-to-3-voice run, the human reads each voice's docstrings symbol by symbol and picks ONE
voice to apply. The page is a shared-picker spec: a single decision card whose candidate boxes are
the voices (each showing that voice's selection rationale and any legibility-flag count), plus one
informational card per symbol laying the voices' docstrings side by side under the summarizer's
independent purpose line. The Copy/Submit bar serializes the choice into a
`PICKS — regen-comments voice (<file>)` blob that apply_selection.py reads as a voice pick; the
orchestrator then renders that voice's per-symbol decision page (render_report.py) from its room.

Each voice's outputs are read from <rundir>/v/<voice>/ (see regen_phase2_multi.py). The page key
carries a combined content hash of every voice's FINAL, so a reload mid-review restores the pick but
a regenerated voice starts the page clean.

Usage: render_compare.py <rundir> <target.py> <voice1> [voice2] [voice3]
Writes <rundir>/spec.json + <rundir>/picker.html.
"""
import ast
import hashlib
import html
import json
import os
import sys

SKILL = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILL)
from render_report import open_page, render_spec  # noqa: E402

# one stable accent per voice column, in voice order — purely decorative, legible on both themes
VOICE_COLORS = ["#3b82d6", "#3d9e62", "#d3528e"]


def _symbols(src):
    """Ordered qualified names: <module> then every class / function / method."""
    tree = ast.parse(src)
    out = ["<module>"]

    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qualname = prefix + child.name
                out.append(qualname)
                walk(child, qualname + ".")

    walk(tree, "")
    return out


def _doc(tree, qualname):
    """One symbol's docstring text in `tree`, or a placeholder when the symbol or tree is absent."""
    if qualname == "<module>":
        return ast.get_docstring(tree) or ""
    node = tree
    for part in qualname.split("."):
        node = next((child for child in ast.iter_child_nodes(node)
                     if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                     and child.name == part), None)
        if node is None:
            return "(not present)"
    return ast.get_docstring(node) or "(none)"


def _load(path, default):
    try:
        return json.load(open(path))
    except Exception:  # noqa: BLE001 — a missing / unreadable artifact falls back to the default
        return default


def _flag_count(rundir, voice):
    """How many legibility + AI-tic flags this voice's room raised — the comparison chip count."""
    legibility = _load(os.path.join(rundir, "v", voice, "legibility.json"), {})
    tics = _load(os.path.join(rundir, "v", voice, "tics.json"), {})
    legibility_flags = legibility.get("flags", []) if isinstance(legibility, dict) else []
    tic_flags = tics.get("flags", []) if isinstance(tics, dict) else []
    return len(legibility_flags) + len(tic_flags)


def _comparison_html(symbol, voices, trees, purpose):
    """One symbol's per-voice docstrings side by side as inline-styled body_html.

    Inline styles reference the picker's own CSS custom properties (var(--card) and friends), so the
    matrix themes with the page and needs no picker-CSS class of its own — keeping the renderer generic.
    """
    bar = (f'<div style="background:var(--blob-bg);border:1px solid var(--border);border-radius:6px;'
           f'padding:7px 10px;margin:0 0 8px;font-size:13px;color:var(--faint)">'
           f'<b>summarizer:</b> {html.escape(purpose or "")}</div>')
    columns = []
    for index, voice in enumerate(voices):
        color = VOICE_COLORS[index % len(VOICE_COLORS)]
        docstring = html.escape(_doc(trees[voice], symbol)) if trees[voice] else "(no FINAL)"
        columns.append(
            f'<div style="flex:1;min-width:0;border-left:3px solid {color};padding-left:8px">'
            f'<div style="font:700 12px ui-monospace,Menlo,monospace;color:{color}">{html.escape(voice)}</div>'
            f'<pre style="white-space:pre-wrap;word-break:break-word;background:var(--blob-bg);'
            f'border:1px solid var(--border);border-radius:8px;padding:8px 10px;margin:4px 0;'
            f'font:12.5px/1.5 ui-monospace,Menlo,monospace;color:var(--fg)">{docstring}</pre></div>')
    return bar + f'<div style="display:flex;gap:10px;align-items:flex-start">{"".join(columns)}</div>'


def main():
    rundir = os.path.abspath(sys.argv[1])
    target = sys.argv[2]
    voices = sys.argv[3:6]
    fname = os.path.basename(target)
    symbols = _symbols(open(target).read())

    # the summarizer's purpose line is voice-independent; read it from whichever room recorded it
    summary = {}
    for voice in voices:
        recorded = _load(os.path.join(rundir, "v", voice, "summary.json"), None)
        if recorded:
            summary = recorded
            break
    purpose = {entry["symbol"]: entry["purpose"] for entry in summary.get("symbols", [])}
    purpose["<module>"] = summary.get("module_summary", "")

    trees, picks, hashes = {}, {}, []
    for voice in voices:
        final = os.path.join(rundir, "v", voice, f"FINAL_{voice}.py")
        if os.path.exists(final):
            data = open(final, "rb").read()
            hashes.append(hashlib.sha1(data).hexdigest())
            trees[voice] = ast.parse(data.decode())
        else:
            trees[voice] = None
        picks[voice] = _load(os.path.join(rundir, "v", voice, "pick.json"), {})
    gen = hashlib.sha1("".join(hashes).encode()).hexdigest()[:10]

    # one decision card: a candidate box per voice, each carrying its winning rationale + flag count
    candidates = []
    for voice in voices:
        chips = []
        flags = _flag_count(rundir, voice)
        if flags:
            chips.append(f"⚠ {flags} legibility flag(s)")
        if picks[voice].get("concern"):
            chips.append(f"concern: {picks[voice]['concern']}")
        candidates.append({"value": voice, "label": voice, "chips": chips,
                           "text": picks[voice].get("why") or "(no rationale recorded)"})
    voice_card = {
        "id": "voice",
        "title": "Apply which voice?",
        "summary": "Pick the voice whose register reads best across the symbols below.",
        "pick_ui": {"style": "columns", "candidates": candidates},
    }

    # informational cards (no radios): the per-symbol docstring matrix the human reads to decide
    symbol_cards = [
        {"id": f"sym:{symbol}", "title": symbol, "options": [],
         "body_html": _comparison_html(symbol, voices, trees, purpose.get(symbol, ""))}
        for symbol in symbols
    ]

    spec = {
        "title": f"regen-comments — voice comparison ({fname})",
        "key": f"regen:voice:{fname}:{gen}",
        "blob_header": f"regen-comments voice ({fname})",
        "subtitle": f"{len(voices)} voices · {len(symbols)} symbols · pick one to apply",
        "intro_html": "<p>Read each voice symbol by symbol below, then pick the voice whose register "
                      "you want and Submit (or Copy the blob). The per-symbol decision page for that "
                      "voice comes next.</p>",
        "options": voices,
        "picked_facet": False,
        "page_width": 1280,
        "items": [voice_card, *symbol_cards],
    }
    out = render_spec(spec, rundir)
    url, opened = open_page(out)
    print(f"{url}")
    print("  " + ("opened in your browser." if opened else "open the link above in a browser to review it."))


if __name__ == "__main__":
    main()
