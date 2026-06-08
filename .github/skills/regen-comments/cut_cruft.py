#!/usr/bin/env python3
"""Post-consolidation DEDUP pass: delete a fact stated twice, never a fact stated once (clean-room).

A fact sometimes survives in two places -- spelled out in a class docstring AND again in a method, or
echoed within one docstring. This removes the later copy and keeps the single clearest statement at the most
relevant symbol. It does NOT reword, NOT split or merge sentences, and NOT delete a fact that appears only
once -- writing an awkward-but-real sentence more fluently is the WRITER's job (the writer discipline owns
that), not this pass's. It protects parallel lists and distinct-fact sentences, never touches executable
code; unsure -> keep, because over-deletion is the only way it can harm. The executable-code fingerprint
(docstrings stripped) is checked and any pass that changed code is reverted. Writes cut_report.txt.

Usage: cut_cruft.py <rundir> <file.py>
"""
import ast
import os
import shutil
import subprocess
import sys

SKILL = os.path.dirname(os.path.abspath(__file__))


def _code_fingerprint(src):
    """AST of the file with every docstring stripped -- unchanged iff only docstrings/comments moved."""
    tree = ast.parse(src)
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            b = n.body
            if b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant) and isinstance(b[0].value.value, str):
                n.body = b[1:] or [ast.Pass()]
    return ast.dump(tree)


def main():
    rundir = os.path.abspath(sys.argv[1])
    path = sys.argv[2]
    path = path if os.path.isabs(path) else os.path.join(rundir, path)
    fname = os.path.relpath(path, rundir)
    fp0 = _code_fingerprint(open(path).read())
    has_ledger = os.path.exists(os.path.join(rundir, "ledger_final.md"))
    ledger_clause = (" and the nuance ledger ./ledger_final.md (the list of facts that MUST survive)"
                     if has_ledger else "")

    prompt = (
        "Read the Python file ./" + fname + ledger_clause + ". You remove TRUE DUPLICATION from docstrings "
        "and comments, nothing else. You do not reword, do not split or merge sentences, do not improve "
        "phrasing, and do not delete a fact that is stated only once.\n\n"
        "DELETE a statement that REPEATS a fact already given elsewhere in the file -- the SAME fact said "
        "twice. Two shapes:\n"
        "- across symbols: a fact spelled out in full in a class docstring AND again in one of its methods, "
        "or in the module docstring AND a class. Keep the single clearest statement at the most relevant "
        "symbol and delete the echo.\n"
        "- within one docstring: a clause or sentence that says again what an earlier one already said.\n"
        "Keep the FIRST, clearest statement of each fact and delete only the later echo.\n\n"
        "NEVER:\n"
        "- delete a fact that appears only ONCE"
        + (" (every ledger fact must still be present).\n" if has_ledger else ".\n")
        + "- split a sentence, merge sentences, or reword. A sentence packing several DISTINCT facts is the "
        "writer's prose -- leave it EXACTLY, even if it is long or comma-heavy (rewriting it more fluently is "
        "the writer's job, not yours). A parallel list (\"it is A, not B, and C\") is distinct facts -- leave "
        "it.\n"
        "- change a summary's first sentence, an Args/Returns/Raises fact, a directive comment (# noqa, "
        "# type: ignore, # pragma), or any executable code.\n"
        "When UNSURE whether two statements are the same fact, KEEP both. Over-deletion is the only harm.\n\n"
        "Edit the file in place. Then write ./cut_report.txt with one line per deletion: the symbol, the "
        "repeated text removed, and where the kept copy lives. If you removed nothing, write exactly 'no "
        "duplication found'. Reply DONE after both files exist."
    )
    backup = path + ".precut"
    shutil.copy(path, backup)
    subprocess.run(
        ["claude", "-p", prompt, "--allowedTools", "Read", "Edit", "Write",
         "--permission-mode", "acceptEdits", "--model", "opus"],
        cwd=rundir, capture_output=True, text=True,
    )
    if _code_fingerprint(open(path).read()) != fp0:
        print("=== CUT REVERTED: pass changed executable code (guard) ===")
        shutil.copy(backup, path)
        return
    print("=== CUT-CRUFT DONE (code byte-identical) ===")
    rep = os.path.join(rundir, "cut_report.txt")
    if os.path.exists(rep):
        for line in open(rep).read().strip().splitlines():
            print("  " + line)
    print("  Orchestrator: the cut is deletion-only and code-guarded. Review cut_report.txt; if it removed a "
          "real fact, restore from " + os.path.basename(backup) + ".")


if __name__ == "__main__":
    main()
