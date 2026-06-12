#!/usr/bin/env python3
"""Mechanical decision page for a completed regen-comments run (no LLM), on the shared picker.

Builds a picker spec from a finished run room and renders it with the shared renderer
(`../_shared/picker/render_picker.py`), so the human can judge CORRECTNESS, not just voice:
  1. page-top context sections: an INDEPENDENT plain-English summary (summary.json — written from the
     code, never from the comments), the selection rationale (pick.json — which whole writer pass won
     and why, plus auto-routed symbols), the legibility / tic / ban flags, and the validated ledger;
  2. one card per symbol, open on load: the original docstring on top, then the candidates side by side
     (the picker's "columns" pick_ui) — the suggested take leftmost and pre-checked, every *differing*
     cached writer pass (runs/run-N.py) after it with comparison chips and a full-symbol expander, four
     or more scrolling horizontally — plus the symbol's ledger facts behind a detail fold and a ⚠
     warning carrying its flags;
  3. below the columns, an `edit` choice with its own full-width text box seeded with the suggested
     docstring — adjust it in place; its exact text rides back on an `edit <id>:` blob line (newlines
     escaped), and the note box stays a plain note.

The page key carries a content fingerprint of the FINAL file, so a mid-review reload restores picks
but an applied selection (FINAL changes) starts the page clean. The Copy/Submit bar serializes choices
into the shared `PICKS — regen-comments apply (<file>)` blob, which apply_selection.py parses.

build_file_entry() is reusable: render_library.py composes the items and sections of many rooms into
one faceted page with file-namespaced ids (`<file.py>#<sym>`) and ONE combined blob.

Usage: render_report.py <rundir> <voice> <original_target.py>  ->  writes <rundir>/spec.json + picker.html
"""
import ast
import difflib
import glob
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import webbrowser

SKILL = os.path.dirname(os.path.abspath(__file__))
RENDERER = os.path.normpath(os.path.join(SKILL, os.pardir, "_shared", "picker", "render_picker.py"))


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


def _doc_pre(doc):
    return f"<pre>{_esc(doc)}</pre>" if (doc or "").strip() else "<pre><i>(no docstring)</i></pre>"


def build_file_entry(rundir, voice, original, namespaced=False):
    """Spec items + page-top context sections + meta for one finished run room.

    namespaced=True (the library page) prefixes every card id as "<file.py>#<qualname>" so one combined
    blob routes picks back to their rooms; a single-file page uses bare qualnames.
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
    run_files = sorted(glob.glob(os.path.join(rundir, "runs", "run-*.py")))
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
    badge = "ledger validated clean" if verdict_ok else "validator flagged issues — see facts"

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

    # ---- per-symbol cards ----
    items = []
    for qual, fin in after.items():
        sugg = final_blocks.get(qual, {"doc": fin.get("doc"), "block": ""})
        is_class = qual != "<module>" and not (sugg.get("block") or "").strip() and qual in final_blocks

        # the original docstring sits above the candidate columns, full width, so every candidate
        # below is read against the same starting point
        parts = [f"<small><b>ORIGINAL</b></small>{_doc_pre(before.get(qual, {}).get('doc'))}"]
        if is_class:
            parts.append("<p><small>A class pick applies the class docstring only; methods have "
                         "their own cards.</small></p>")

        if qual in autoroute:
            sugg_label = f"suggested — auto-routed to writer pass {autoroute[qual]}"
        elif winner is not None:
            sugg_label = f"suggested — writer pass {winner}, polished"
        else:
            sugg_label = "suggested"
        candidates = [{"value": "suggested", "label": sugg_label, "text": sugg.get("doc") or ""}]
        if (sugg.get("block") or "").strip() and qual != "<module>":
            candidates[0]["more"] = {"label": "full symbol (inline comments)", "text": sugg["block"]}
        for n in sorted(run_blocks):
            cand = run_blocks[n].get(qual)
            if not cand:
                continue
            same_doc = (cand.get("doc") or "") == (sugg.get("doc") or "")
            same_block = (cand.get("block") or "") == (sugg.get("block") or "")
            if same_doc and same_block:
                continue
            entry = {"value": f"run-{n}", "label": f"writer pass {n}",
                     "chips": _doc_hint(sugg, cand), "text": cand.get("doc") or ""}
            if not same_block and (cand.get("block") or "").strip() and qual != "<module>":
                entry["more"] = {"label": "full symbol (inline comments)", "text": cand["block"]}
            candidates.append(entry)

        sym_flags = ([f"legibility: {f.get('sentence')}" for f in flags if f.get("symbol") == qual]
                     + [f"{f.get('kind')}: {f.get('text')}" for f in tflags if f.get("symbol") == qual])
        facts = _facts_for(qual, ledger)
        item = {
            "id": f"{fname}#{qual}" if namespaced else qual,
            "title": qual,
            "summary": purpose.get(qual, purpose.get(_short(qual), "")),
            "body_html": "".join(parts),
            "pick_ui": {"style": "columns", "candidates": candidates,
                        "edit": {"value": "edit",
                                 "label": "edit it myself — replaces the docstring with this exact text",
                                 "seed": sugg.get("doc") or ""}},
            "default": "suggested",
            "facets": ({"flag": "flagged" if qual in flagged_syms else "clean"}
                       | ({"file": fname} if namespaced else {})),
        }
        if fin.get("sig"):
            item["where"] = {"place": f"{fname} · {qual}", "code": fin["sig"]}
        if sym_flags:
            item["warning"] = " · ".join(sym_flags)
        if facts:
            item["detail"] = {"label": f"ledger facts ({len(facts)})",
                              "text": "\n".join(f"- {f.get('gloss') or f.get('stub')} "
                                                f"[{f.get('confidence')}]" for f in facts)}
        items.append(item)

    # ---- page-top context sections ----
    summary_html = (f"<p>{_esc(summary.get('module_summary'))}</p><ul>"
                    + ("".join(f"<li><code>{_esc(s['symbol'])}</code> — {_esc(s['purpose'])}</li>"
                               for s in summary.get("symbols", [])) or "<li><i>no symbol summaries</i></li>")
                    + "</ul>")
    sel_html = ""
    if winner is not None:
        sel_html = (f"<p><b>Selected writer pass {_esc(winner)}"
                    + (f" of {n_passes}" if n_passes else "") + f"</b> — {_esc(why)}</p>")
        if concern:
            sel_html += f"<p>⚠ selector concern: {_esc(concern)}</p>"
        if autoroute:
            sel_html += ("<p>auto-routed around flags: "
                         + ", ".join(f"<code>{_esc(s)}</code> → pass {_esc(n)}" for s, n in autoroute.items())
                         + "</p>")
    flag_bits = []
    if flags:
        flag_bits.append(f"<p><b>⚠ {len(flags)} sentence(s) flagged for legibility</b> — they read "
                         "awkwardly even when the facts are right.</p><ul>"
                         + "".join(f"<li><code>{_esc(f.get('symbol'))}</code> ({_esc(f.get('why'))}): "
                                   f"<i>{_esc(f.get('sentence'))}</i></li>" for f in flags) + "</ul>")
    if tflags:
        flag_bits.append(f"<p><b>⚠ {len(tflags)} AI-tic / voice-leak flag(s)</b> — formulaic phrasing or "
                         "voice-descriptor words that slipped into the comments.</p><ul>"
                         + "".join(f"<li><code>{_esc(f.get('symbol'))}</code> [{_esc(f.get('kind'))}]: "
                                   f"<i>{_esc(f.get('text'))}</i></li>" for f in tflags) + "</ul>")
    if bflags:
        flag_bits.append(f"<p><b>⚠ {len(bflags)} mechanical-ban violation(s) remain</b> — no cached pass "
                         "had a clean take and one polish round did not clear them; fix via a different "
                         "take or an edit.</p><ul>"
                         + "".join(f"<li><code>{_esc(b.get('where'))}</code> [{_esc(b.get('kind'))}]: "
                                   f"<i>{_esc(b.get('text'))}</i></li>" for b in bflags) + "</ul>")
    n_flags = len(flags) + len(tflags)
    ledger_html = ("<table><tr><th>fact</th><th>sites</th><th>lenses</th><th>conf</th></tr>"
                   + ("".join(
                       f"<tr><td>{(_esc(f.get('gloss')) + '<br>') if f.get('gloss') else ''}"
                       f"<code>{_esc(f.get('stub'))}</code></td><td>{_esc(f.get('sites'))}</td>"
                       f"<td>{_esc(','.join(f.get('source_lenses', [])))}</td>"
                       f"<td>{_esc(f.get('confidence'))}</td></tr>" for f in ledger)
                      or "<tr><td colspan=4><i>empty ledger</i></td></tr>") + "</table>")

    sections = [{"title": f"What {fname} does — independent summary"
                          + (" · library-aware" if has_lib else ""),
                 "html": summary_html, "open": not namespaced}]
    if sel_html:
        sections.append({"title": f"Selection rationale — {badge}", "html": sel_html})
    if flag_bits:
        sections.append({"title": f"⚠ flags — {n_flags + len(bflags)} item(s)",
                         "html": "".join(flag_bits), "open": True})
    sections.append({"title": f"Validated ledger — {len(ledger)} facts", "html": ledger_html})

    meta = {"file": fname, "final": final, "hash": fhash, "symbols": len(after),
            "ledger": len(ledger), "verdict_ok": verdict_ok, "n_flags": n_flags,
            "n_passes": n_passes, "badge": badge}
    return items, sections, meta


OPTION_HELP = {
    "suggested": "keep the selector's winning take for this symbol",
    "edit": "replace the docstring with the edit box's exact text (it starts seeded with the suggested take)",
}


def render_spec(spec, outdir):
    """Write spec.json and render picker.html via the shared renderer; return the page path."""
    spec_path = os.path.join(outdir, "spec.json")
    with open(spec_path, "w") as handle:
        json.dump(spec, handle, indent=1, ensure_ascii=False)
    subprocess.run([sys.executable, RENDERER, spec_path, outdir], check=True)
    return os.path.join(outdir, "picker.html")


def open_page(out):
    url = f"file://{out}"
    if os.environ.get("REGEN_NO_OPEN"):  # a serve session owns the open; re-renders just rewrite the file
        return url, False
    try:
        opened = webbrowser.open(url)  # best-effort; no-op on headless/SSH
    except Exception:  # noqa: BLE001 - any browser failure means "tell the user to open it by hand"
        opened = False
    return url, opened


def main():
    rundir = os.path.abspath(sys.argv[1])
    voice = sys.argv[2]
    original = os.path.abspath(sys.argv[3])

    items, sections, meta = build_file_entry(rundir, voice, original)
    spec = {
        "title": f"regen-comments — {meta['file']} ({voice})",
        "key": f"regen:{meta['file']}:{meta['hash']}",
        "blob_header": f"regen-comments apply ({meta['file']})",
        "subtitle": f"voice: {voice} · {meta['symbols']} symbols · {meta['n_passes']} cached passes · "
                    f"{meta['badge']}",
        "intro_html": "<p>Pick per symbol below — click a candidate box to choose it (the suggested "
                      "take is pre-checked), or adjust the seeded <b>edit</b> box to rewrite a docstring "
                      "yourself. Then Submit to session (shown when the page is served) or Copy the blob "
                      "and paste it back into the Claude session — or just describe what you want in "
                      "chat.</p>",
        "options": ["suggested", "edit"],
        "default": "suggested",
        "page_width": 1280,
        "expand_on": ["edit"],
        "option_help": OPTION_HELP,
        "sections": sections,
        "items": items,
        "facets": [{"key": "flag"}],
    }
    out = render_spec(spec, rundir)
    url, opened = open_page(out)
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
