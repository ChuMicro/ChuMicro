#!/usr/bin/env python3
"""Tabbed library-wide report: one page, a tab per file, ONE combined Copy-selection blob (no LLM).

Library mode used to present each file's report sequentially; this composes every finished room's report
section (render_report.build_file_section) into a single page so the human reviews files in any order.
Each tab is a full per-file report (summary, rationale, flags, ledger, per-symbol pickers); radio groups
and saved state are namespaced per tab, so picks never interfere. The sticky Copy-selection bar serializes
ALL files' picks into one blob — one `regen-comments apply (<file>): …` section per touched file — which
apply_selection.py parses per section and the orchestrator applies room by room (the per-room guards and
re-checks are unchanged). Saved picks key on the combined content hash of every FINAL file: a mid-review
reload restores them; any applied change starts the page clean.

Usage: render_library.py <outdir> <voice> <rundir>=<original.py> [<rundir>=<original.py> ...]
Writes <outdir>/library_report.html and opens it. The orchestrator builds the pairs from
batch_manifest.json (file -> room).
"""
import hashlib
import os
import sys

SKILL = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILL)
from render_report import build_file_section, selbar_html, write_page, _esc  # noqa: E402


def main():
    outdir = os.path.abspath(sys.argv[1])
    voice = sys.argv[2]
    pairs = []
    for arg in sys.argv[3:]:
        rundir, original = arg.split("=", 1)
        pairs.append((os.path.abspath(rundir), os.path.abspath(original)))
    if not pairs:
        sys.exit("no <rundir>=<original.py> pairs given")

    tabs, panes, metas = [], [], []
    for k, (rundir, original) in enumerate(pairs):
        section, meta = build_file_section(rundir, voice, original, ns=f"f{k}")
        metas.append(meta)
        flag_chip = f"<span class='tflag'>⚠ {meta['n_flags']}</span>" if meta["n_flags"] else ""
        tabs.append(f"<button data-pane='{k}'{' class=active' if k == 0 else ''}>"
                    f"{_esc(meta['file'])}{flag_chip}</button>")
        # every pane leads with its own filename: with the sticky tab bar this makes the active file
        # unmistakable at any scroll depth (panes can otherwise open on similar-looking summary cards)
        panes.append(f"<div class='filepane{' active' if k == 0 else ''}' id='pane-{k}'>"
                     f"<div class='panehead'><code>{_esc(meta['file'])}</code>"
                     f"<span class='panemeta'>{meta['symbols']} symbols · {meta['ledger']} ledger facts</span></div>"
                     f"{section}</div>")

    gen = hashlib.sha1("".join(m["hash"] for m in metas).encode()).hexdigest()[:10]
    n_flagged = sum(1 for m in metas if m["n_flags"])
    hint = ("Review each tab (flag chips mark files with tic/legibility hits), pick or edit per symbol, "
            "then copy ONE blob covering every file you touched and paste it back into the Claude session. "
            "Untouched files ride as suggested.")
    body = (f" <h1>regen-comments — library review <span style='font-weight:400;font-size:13px;color:#667'>"
            f"({len(pairs)} files, voice: {_esc(voice)}{f', {n_flagged} with flags' if n_flagged else ''})</span></h1>"
            f"<div class='tabbar'>{''.join(tabs)}</div>"
            + "".join(panes) + selbar_html(hint))

    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, "library_report.html")
    url, opened = write_page(out, f"regen-comments — library review ({len(pairs)} files)",
                             body, os.path.basename(outdir), gen)
    print("=== LIBRARY REPORT WRITTEN ===")
    print(f"  {out}")
    print(f"  {url}")
    print("  " + ("opened in your browser." if opened else "open the link above in a browser to review it."))
    for m in metas:
        print(f"  {m['file']}: {m['symbols']} symbols, {m['n_flags']} flag(s), "
              f"validator {'clean' if m['verdict_ok'] else 'FLAGGED'}")


if __name__ == "__main__":
    main()
