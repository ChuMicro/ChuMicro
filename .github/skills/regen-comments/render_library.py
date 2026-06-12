#!/usr/bin/env python3
"""Library-wide decision page: every room's cards on ONE shared-picker page, one combined blob (no LLM).

Composes each finished room's spec entries (render_report.build_file_entry) into a single faceted page:
card ids are namespaced `<file.py>#<qualname>`, a select-style file facet narrows to one file at a time
(plus the flagged/clean chips), and each file's context (summary, rationale, flags, ledger) nests under
one page-top section per file. The Copy/Submit bar serializes ALL files' picks into one shared
`PICKS — regen-comments apply (library)` blob; apply_selection.py groups it per file and the
orchestrator applies room by room (the per-room guards and re-checks are unchanged). The page key
carries the combined content hash of every FINAL file: a mid-review reload restores picks, and any
applied change starts the page clean.

Usage: render_library.py <outdir> <voice> <rundir>=<original.py> [<rundir>=<original.py> ...]
Writes <outdir>/spec.json + <outdir>/picker.html and opens it (REGEN_NO_OPEN suppresses the open).
The orchestrator builds the pairs from batch_manifest.json (file -> room).
"""
import hashlib
import os
import sys

SKILL = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILL)
from render_report import OPTION_HELP, build_file_entry, open_page, render_spec  # noqa: E402


def main():
    outdir = os.path.abspath(sys.argv[1])
    voice = sys.argv[2]
    pairs = []
    for arg in sys.argv[3:]:
        rundir, original = arg.split("=", 1)
        pairs.append((os.path.abspath(rundir), os.path.abspath(original)))
    if not pairs:
        sys.exit("no <rundir>=<original.py> pairs given")

    items, sections, metas = [], [], []
    for rundir, original in pairs:
        file_items, file_sections, meta = build_file_entry(rundir, voice, original, namespaced=True)
        items.extend(file_items)
        flag_note = f" · ⚠ {meta['n_flags']}" if meta["n_flags"] else ""
        sections.append({"title": f"{meta['file']} — {meta['symbols']} symbols · "
                                  f"{meta['ledger']} facts{flag_note}",
                         "sections": file_sections})
        metas.append(meta)

    combined = hashlib.sha1("".join(m["hash"] for m in metas).encode()).hexdigest()[:10]
    n_flagged = sum(1 for m in metas if m["n_flags"])
    spec = {
        "title": f"regen-comments — library review ({len(pairs)} files, {voice})",
        "key": f"regen:library:{combined}",
        "blob_header": "regen-comments apply (library)",
        "subtitle": f"voice: {voice} · {len(pairs)} files · {len(items)} symbols"
                    + (f" · {n_flagged} file(s) with flags" if n_flagged else ""),
        "intro_html": "<p>Review per file (the file dropdown narrows the cards; ⚠ marks flagged "
                      "symbols), pick or edit per symbol, then Submit or Copy ONE blob covering every "
                      "file you touched. Untouched files ride as suggested.</p>",
        "options": ["suggested", "edit"],
        "default": "suggested",
        "page_width": 1280,
        "expand_on": ["edit"],
        "option_help": OPTION_HELP,
        "sections": sections,
        "items": items,
        "facets": [{"key": "flag"}, {"key": "file", "style": "select"}],
    }
    os.makedirs(outdir, exist_ok=True)
    out = render_spec(spec, outdir)
    url, opened = open_page(out)
    print("=== LIBRARY REPORT WRITTEN ===")
    print(f"  {out}")
    print(f"  {url}")
    print("  " + ("opened in your browser." if opened else "open the link above in a browser to review it."))
    for m in metas:
        print(f"  {m['file']}: {m['symbols']} symbols, {m['n_flags']} flag(s), "
              f"validator {'clean' if m['verdict_ok'] else 'FLAGGED'}")


if __name__ == "__main__":
    main()
