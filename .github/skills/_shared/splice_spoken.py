#!/usr/bin/env python3
"""Splice speaker prose over a raw audit ledger to produce the decision-page spec.

Reads <report-dir>/ledger.json (a picker spec whose item wording is raw lens
shorthand) and <report-dir>/spoken.json (a speak_wf.js return value: per-id
rewritten title / summary / why / fix plus page-level intro_html / option_help /
gate), and writes <report-dir>/spec.json. Structure — evidence, where, diff,
facets, defaults, options — comes from the ledger; prose comes from the speaker.
A non-empty speaker string replaces the ledger field; an empty one never
overwrites, so a misbehaving speaker cannot erase a fact. An id missing from the
speaker output keeps its ledger wording and gains a warning so the card itself
says its prose was not rewritten.

Usage: splice_spoken.py <report-dir>
Stdout: one line of counts plus the spec path.
"""
import json
import os
import sys

SPEAKER_FIELDS = ("title", "summary", "why", "fix")


def main():
    report_dir = os.path.abspath(sys.argv[1])
    with open(os.path.join(report_dir, "ledger.json")) as handle:
        ledger = json.load(handle)
    with open(os.path.join(report_dir, "spoken.json")) as handle:
        spoken = json.load(handle)
    rendered = spoken.get("items") or {}
    page = spoken.get("page") or {}

    spliced = 0
    kept = 0
    for item in ledger.get("items", []):
        spoken_item = rendered.get(str(item.get("id")))
        if not spoken_item:
            kept += 1
            note = "speaker did not rewrite this card — wording is the lens's own"
            item["warning"] = f"{item['warning']} · {note}" if item.get("warning") else note
            continue
        spliced += 1
        for field in SPEAKER_FIELDS:
            value = (spoken_item.get(field) or "").strip()
            if value:
                item[field] = value
    if page.get("intro_html"):
        ledger["intro_html"] = page["intro_html"]
    if page.get("option_help"):
        ledger["option_help"] = page["option_help"]

    spec_path = os.path.join(report_dir, "spec.json")
    with open(spec_path, "w") as handle:
        json.dump(ledger, handle, indent=1, ensure_ascii=False)
    print(f"spliced {spliced} · ledger-wording {kept} -> {spec_path}")


if __name__ == "__main__":
    main()
