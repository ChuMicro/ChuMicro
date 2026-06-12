#!/usr/bin/env python3
"""Parse + apply the report.html / compare.html "Copy selection" blob (mechanical, no LLM).

The interactive reports let the human pick, per symbol, which writer pass's docstring+comments to keep
(the selector's winner is pre-checked as "suggested"), or type a replacement docstring, plus free-text
notes. The page's Copy-selection button serializes those choices into a paste-back blob; this script
parses that blob and applies it to the run's FINAL file:

  - `<sym>=run-N`  -> splice that symbol's docstring+comments from runs/run-N.py (splice_symbol guard:
                      executable code must stay AST-identical, else the op is rejected);
  - `<sym>=edit`   -> replace that symbol's docstring with the human's exact text from the blob's
                      `#edit` block (same code-identity guard).

Picks/edits land on FINAL in place. The orchestrator then re-runs polish.py (the cached writer passes
are pre-polish), verify_code.py, and the flaggers, and re-renders — a blob is a batch refine, not an
exit from the Step 8 loop. Notes are echoed for the orchestrator to read (push-backs stay in-session).

Usage:
  apply_selection.py parse <blobfile>                 -> print the parsed selection as JSON
  apply_selection.py apply <rundir> <voice> <blobfile> -> apply picks + edits to <rundir>/FINAL_<voice>.py

Two blob grammars are accepted. The shared picker page (render_report.py / render_library.py via
`_shared/picker/`) emits the PICKS form; the legacy form stays for compare.html and hand-typed blobs:

  PICKS — regen-comments apply (<file.py> | library)
  KVStore.get = run-2                       (library page: kvstore.py#KVStore.get = run-2)
  <module> = edit
    edit <module>: exact docstring text\nwith newlines escaped   (the page's edit box, verbatim)
    note <module>: a plain note (newlines collapsed; on an edit pick with no edit line, the note
                   is decoded as the replacement text — pre-edit-channel pages put it there)

  regen-comments apply (<file.py>): all suggested
  regen-comments apply (<file.py>): KVStore.get=run-2, <module>=edit
  regen-comments voice (<file.py>): cantrill
  #edit <sym>            then a fenced block:  <<<EDIT ... EDIT>>>
  #note <sym>: free text
"""
import ast
import json
import os
import re
import sys

SKILL = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILL)
from splice_symbol import splice, _code_only, _find, _module_doc_node  # noqa: E402

_HEADER = re.compile(r"^\s*regen-comments\s+(apply|voice)\s*(?:\(([^)]*)\))?\s*:\s*(.*)$")
_EDIT_AT = re.compile(r"^#edit\s+(\S+)\s*$")
_NOTE_AT = re.compile(r"^#note\s+(\S+)\s*:\s*(.*)$")
_PICK = re.compile(r"^(.+?)\s*=\s*(run-\d+|edit|suggested)$")
_SHARED_HEADER = re.compile(r"^\s*PICKS\s*[—-]+\s*regen-comments\s+apply\s*\(([^)]*)\)\s*$")
_SHARED_NOTE = re.compile(r"^\s*note\s+(\S+)\s*:\s*(.*)$")
_SHARED_EDIT = re.compile(r"^\s*edit\s+(\S+)\s*:\s*(.*)$")


def _decode_note(text):
    """Reverse the shared picker's edit-channel escaping (backslash doubled, newline as literal \\n)."""
    return text.replace("\\\\", "\x00").replace("\\n", "\n").replace("\x00", "\\")


def parse_shared_blob(text):
    """A shared-picker PICKS blob -> [selection, ...], grouped per file.

    Card ids are bare qualnames on a single-file page (the header names the file) and
    `<file.py>#<qualname>` on the library page. An `edit <id>:` line carries the replacement
    docstring (newlines escaped by the page, decoded here); notes ride through for the
    orchestrator to read. `suggested` and `(none)` lines are the no-op default.
    """
    scope = None
    raw_picks, raw_notes, raw_edits = {}, [], {}
    for line in text.splitlines():
        m = _SHARED_HEADER.match(line)
        if m:
            scope = m.group(1).strip() or None
            continue
        if scope is None:
            continue
        m = _SHARED_EDIT.match(line)
        if m:
            raw_edits[m.group(1)] = _decode_note(m.group(2))
            continue
        m = _SHARED_NOTE.match(line)
        if m:
            raw_notes.append((m.group(1), m.group(2)))
            continue
        m = _PICK.match(line.strip())
        if m:
            raw_picks[m.group(1).strip()] = m.group(2)

    def split_id(card_id):
        return card_id.split("#", 1) if "#" in card_id else (scope, card_id)

    selections = {}

    def section_for(fname):
        return selections.setdefault(
            fname, {"kind": "apply", "file": fname, "picks": {}, "edits": {}, "notes": [], "voice": None})

    for card_id, choice in raw_picks.items():
        fname, sym = split_id(card_id)
        sel = section_for(fname)
        if choice != "suggested":
            sel["picks"][sym] = choice
    for card_id, edit_text in raw_edits.items():
        fname, sym = split_id(card_id)
        section_for(fname)["edits"][sym] = edit_text
    for card_id, note_text in raw_notes:
        fname, sym = split_id(card_id)
        sel = section_for(fname)
        if sel["picks"].get(sym) == "edit" and sym not in sel["edits"]:
            # pre-edit-channel pages carried the replacement text in the note; decode and honor it
            sel["edits"][sym] = _decode_note(note_text)
        else:
            sel["notes"].append({"symbol": sym, "note": note_text.replace("\n", " / ")})
    return list(selections.values()) or [section_for(scope)]


def parse_blob_multi(text):
    """Blob text -> [selection, ...]: the shared PICKS blob grouped per file, or one element per legacy
    `regen-comments …` header (compare.html and hand-typed blobs).

    Legacy: lines before the first header are ignored; each section's #edit / #note lines bind to the
    header above them. A single-file blob parses to a one-element list.
    """
    lines = text.splitlines()
    if any(_SHARED_HEADER.match(ln) for ln in lines):
        return parse_shared_blob(text)
    starts = [i for i, ln in enumerate(lines) if _HEADER.match(ln)]
    if not starts:
        return [parse_blob(text)]  # headerless: let the single parser report what it can
    chunks = []
    for j, s in enumerate(starts):
        end = starts[j + 1] if j + 1 < len(starts) else len(lines)
        chunks.append("\n".join(lines[s:end]))
    return [parse_blob(c) for c in chunks]


def parse_blob(text):
    """Blob text -> {kind, file, picks, edits, notes, voice}. Unknown lines are ignored (paste slop)."""
    out = {"kind": None, "file": None, "picks": {}, "edits": {}, "notes": [], "voice": None}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _HEADER.match(line)
        if m:
            kind, fname, rest = m.group(1), m.group(2), m.group(3).strip()
            out["kind"] = kind
            out["file"] = fname or out["file"]
            if kind == "voice":
                out["voice"] = None if (not rest or rest.startswith("(")) else rest
            elif rest and "suggested" != rest and not rest.startswith("(") and rest != "all suggested":
                for part in rest.split(","):
                    pm = _PICK.match(part.strip())
                    if pm and pm.group(2) != "suggested":
                        out["picks"][pm.group(1)] = pm.group(2)
            i += 1
            continue
        m = _EDIT_AT.match(line)
        if m:
            sym = m.group(1)
            i += 1
            while i < len(lines) and lines[i].strip() != "<<<EDIT":
                i += 1
            i += 1  # past the fence
            body = []
            while i < len(lines) and lines[i].strip() != "EDIT>>>":
                body.append(lines[i])
                i += 1
            i += 1  # past the closing fence
            out["edits"][sym] = "\n".join(body)
            continue
        m = _NOTE_AT.match(line)
        if m:
            out["notes"].append({"symbol": m.group(1), "note": m.group(2)})
        i += 1
    return out


def set_docstring(src, qual, text):
    """Replace (or insert) one symbol's docstring with the human's exact text; code must stay identical.

    The edit boxes are seeded with ast.get_docstring()'s DEDENTED text, so continuation lines are
    re-indented to the symbol's body indent here.
    """
    lines = src.splitlines()
    tree = ast.parse(src)
    if qual == "<module>":
        doc_node = _module_doc_node(tree)
        indent = ""
        insert_at = (tree.body[0].lineno - 1) if tree.body else len(lines)
    else:
        node = _find(tree, qual)
        if not node.body:
            sys.exit(f"REJECTED: {qual!r} has no body to hold a docstring")
        first = node.body[0]
        if first.lineno == node.lineno:
            sys.exit(f"REJECTED: {qual!r} is a one-line def; cannot insert a docstring mechanically")
        doc_node = first if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                             and isinstance(first.value.value, str)) else None
        indent = " " * first.col_offset
        insert_at = first.lineno - 1

    # the text lands inside a non-raw string literal: double backslashes first so a \t or \n the
    # human typed re-parses as those two characters, not an escape (quote escapes come after and
    # must stay single)
    text = text.replace("\\", "\\\\")
    quote = '"""'
    if '"""' in text:
        quote = "'''" if "'''" not in text else '"""'
        if quote == '"""':
            text = text.replace('"""', '\\"\\"\\"')  # both quote styles present: escape, warn upstream
    t = text.rstrip("\n")
    if "\n" in t:
        first_line, rest = t.split("\n", 1)
        repl = ([indent + quote + first_line]
                + [(indent + ln if ln.strip() else "") for ln in rest.split("\n")]
                + [indent + quote])
    else:
        repl = [indent + quote + t + quote]

    if doc_node:
        new = lines[:doc_node.lineno - 1] + repl + lines[doc_node.end_lineno:]
    else:
        new = lines[:insert_at] + repl + lines[insert_at:]
    return "\n".join(new) + "\n"


def _is_class(src, qual):
    if qual == "<module>":
        return False
    try:
        return isinstance(_find(ast.parse(src), qual), ast.ClassDef)
    except SystemExit:
        return False


def apply_selection(rundir, voice, sel):
    final = os.path.join(rundir, f"FINAL_{voice}.py")
    if not os.path.exists(final):
        sys.exit(f"no {final} — run phase 2 first")
    src = open(final).read()
    fingerprint = _code_only(src)
    ops = []

    for sym, pick in sel["picks"].items():
        if pick == "edit":
            if sym not in sel["edits"]:
                sys.exit(f"REJECTED: {sym!r} marked edit but the blob carries no #edit block for it")
            src = set_docstring(src, sym, sel["edits"][sym])
            ops.append(f"{sym}: replaced docstring with the human's text")
        else:
            run_file = os.path.join(rundir, "runs", f"{pick}.py")
            if not os.path.exists(run_file):
                sys.exit(f"REJECTED: {sym!r} -> {pick} but {run_file} does not exist")
            run_src = open(run_file).read()
            if _is_class(src, sym):
                # a class's span contains its methods — splicing it would silently sweep their
                # docstrings along. A class pick means the CLASS DOCSTRING only; methods have
                # their own picker rows.
                new_doc = ast.get_docstring(_find(ast.parse(run_src), sym))
                if new_doc is None:
                    sys.exit(f"REJECTED: {sym!r} -> {pick} but that pass has no class docstring to take")
                src = set_docstring(src, sym, new_doc)
                ops.append(f"{sym}: class docstring taken from {pick} (methods untouched)")
            else:
                src = splice(src, run_src, sym)
                ops.append(f"{sym}: spliced from {pick}")
    # an #edit block without a matching pick line still counts (hand-typed blobs)
    for sym, text in sel["edits"].items():
        if sel["picks"].get(sym) != "edit":
            src = set_docstring(src, sym, text)
            ops.append(f"{sym}: replaced docstring with the human's text")

    if _code_only(src) != fingerprint:
        sys.exit("REJECTED: selection changed executable code — nothing written")
    ast.parse(src)
    open(final, "w").write(src)
    return ops


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "parse":
        sels = parse_blob_multi(open(sys.argv[2]).read())
        print(json.dumps(sels[0] if len(sels) == 1 else sels, indent=2))
    elif mode == "apply":
        rundir, voice, blobfile = os.path.abspath(sys.argv[2]), sys.argv[3], sys.argv[4]
        want = sys.argv[5] if len(sys.argv) > 5 else None  # basename filter for a multi-file (library) blob
        sels = parse_blob_multi(open(blobfile).read())
        if want:
            sels = [s for s in sels if s.get("file") == want]
            if not sels:
                sys.exit(f"no section for {want!r} in the blob")
        if len(sels) > 1:
            sys.exit("blob has sections for multiple files — pass the file basename as the 5th arg and "
                     "apply once per room: apply <rundir> <voice> <blobfile> <file.py>")
        sel = sels[0]
        if sel["kind"] == "voice":
            sys.exit("this is a VOICE blob — pick the voice's room and render its report instead of applying")
        if not sel["picks"] and not sel["edits"]:
            print(f"all suggested — FINAL unchanged.{f'  ({want})' if want else ''}")
        else:
            for op in apply_selection(rundir, voice, sel):
                print(f"  {op}")
            print(f"FINAL_{voice}.py updated (code identity verified).")
            print("now re-run: polish.py, verify_code.py, flag_legibility.py, flag_tics.py, render_report.py")
        for n in sel["notes"]:
            print(f"  note [{n['symbol']}]: {n['note']}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
