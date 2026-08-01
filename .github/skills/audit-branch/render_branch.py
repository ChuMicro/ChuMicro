#!/usr/bin/env python3
"""audit-branch — build the decision-page spec from one branch run room and render it via the
shared picker.

Reads the room's eval.json + written.json + summary.json + validation.json + patches.json +
manifest.json + phase1.json, joins the writer's prose onto the fact ledger by id, and writes
spec.json in the shared picker schema, then invokes the shared renderer to produce picker.html.

The mapping mirrors audit-code's single-file page with the change-set twists: every finding
carries a `file`, so the where row leads with the file path, a file dropdown joins the facet bar,
and every card renders folded to a strip (a change-set's list skims like a table; the badge and
the ⚠ on unconfirmed strips say what deserves a click). Page-top context: FEATURE_FACTS (when
phase 0 ran), the summarizer's independent read of what the change-set does, the intent record's
claims (so the human can compare claim against read), and per-file change summaries with finding
back-links.

Defaults encode the apply policy: a validator-confirmed high-severity finding pre-selects apply,
an unconfirmed finding pre-selects discuss, everything else pre-selects skip.

This script renders only. The orchestrator serves the page with webui/serve_picker.py
(PICKER_NO_OPEN=1, background), opens the printed SERVING url itself, and watches the server's
stdout for the submitted selection.

Usage: render_branch.py <rundir>
"""
import html
import json
import os
import sys

SKILL = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.path.join(os.path.dirname(SKILL), "audit-code")
sys.path.insert(0, PIPELINE)
from render_eval import (  # noqa: E402
    STATUS_HELP,
    STATUS_ORDER,
    apply_continuity_fields,
    baseline_intro_bit,
    card_anchor,
    continuity,
    facts_html,
    load_baseline,
    load_room,
    patch_fields,
    path_features_section,
    render,
    resolved_ghost_item,
    status_facet_needed,
)

ANGLE_HELP = {
    "trap": "correctness lens — inversions, off-by-ones, hostile-input and timing hazards the change introduces, judged from comment-stripped code",
    "integration": "contract lens — call/behavior/contract compatibility of the public surface, base vs head, plus the VERSION-bump check",
    "usage": "call-site lens — every traced caller of a changed symbol judged against the new behavior",
    "intent": "alignment lens — where the diff diverges from the stated intent unacknowledged, symptom-masking on claimed bugfixes, unrelated riders",
    "coverage": "test-gap lens — new or altered behavior no test exercises or pins, tests blessing the old behavior",
    "craft": "craft lens — prose the change broke, new code that reads wrong, inconsistency with its surroundings",
    "path": "usage-path lens — transitive callers (callers of callers, optionally in consumer repos) judged in-session on full commented code, in feature terms; no clean room on purpose",
}
ANGLES = list(ANGLE_HELP)


def build_branch_item(room, finding):
    """One picker card per change-set finding: like audit-code's card, with the finding's `file`
    leading the where row and tagging the file facet, and every card folded to a strip."""
    finding_id = finding.get("id")
    severity = finding.get("severity", "low")
    verdict = room["validator_map"].get(finding_id, {})
    unconfirmed = bool(verdict) and (not verdict.get("real", True) or not verdict.get("fix_sound", True))
    angle = finding.get("angle", "trap")
    file_path = finding.get("file", "?")
    item = {
        "id": str(finding_id),
        "title": finding["title"],
        "badge": severity,
        "source": angle,
        "meta": f"effort: {finding.get('effort', '?')} · confidence: {finding.get('confidence', '?')}",
        "where": {"place": f"{file_path} · {finding.get('symbol', '?')}", "code": finding.get("site", "")},
        "why": finding["consequence"],
        "fix": finding["suggested_fix"],
        # the full repo-relative path, not the basename — two packages can share a file name
        "facets": {"severity": severity, "angle": angle, "file": file_path},
        "default": "discuss" if unconfirmed else ("apply" if severity == "high" else "skip"),
        "collapsed": True,
    }
    if finding.get("problem"):
        item["summary"] = finding["problem"]
    if unconfirmed:
        tag = "problem unconfirmed" if not verdict.get("real", True) else "fix needs review"
        item["warning"] = f"Validator: {tag}. {verdict.get('note', '')}".strip()
    if finding.get("in_session"):
        item["warning"] = ("In-session usage-path lens — judged on full commented code with "
                           "project context, outside the clean room, on purpose. "
                           + item.get("warning", "")).strip()
    if finding.get("feature"):
        item["meta"] += f" · feature: {finding['feature']}"
    patch = room["patch_map"].get(finding_id)
    if patch and (patch.get("repro") or "").strip():
        item["meta"] += " · executable repro (apply runs it red→green)"
    item.update(patch_fields(patch))
    apply_continuity_fields(item, finding)
    return item


def per_file_section_html(room):
    """The summarizer's per-file change summaries (qualname = the file path), each with
    back-links to the finding cards raised against that file."""
    findings_by_file = {}
    for finding in room["findings"]:
        findings_by_file.setdefault(finding.get("file"), []).append(finding.get("id"))
    blocks = []
    for entry in room["summary"].get("symbols", []):
        path = entry.get("qualname", "")
        links = [f'<a href="#{card_anchor(str(fid))}">#{fid}</a>'
                 for fid in sorted(findings_by_file.get(path, []))]
        related = (" <small>findings: " + ", ".join(links) + "</small>") if links else ""
        blocks.append(
            f"<p><code>{html.escape(path)}</code> <small>{html.escape(entry.get('signature', ''))}</small><br>"
            f"{html.escape(entry.get('summary', ''))}{related}</p>"
        )
    return "".join(blocks)


def main():
    args = sys.argv[1:]
    baseline = None
    if "--baseline" in args:
        index = args.index("--baseline")
        baseline = args[index + 1]
        args = args[:index] + args[index + 2:]
    if len(args) != 1:
        raise SystemExit("usage: render_branch.py <rundir> [--baseline <prior eval.json>]")
    rundir = os.path.abspath(args[0])
    manifest_path = os.path.join(rundir, "manifest.json")
    manifest = json.load(open(manifest_path)) if os.path.exists(manifest_path) else {}
    label = manifest.get("label", os.path.basename(rundir))
    room = load_room(rundir, label)

    resolved = []
    if baseline:
        prior_findings, prior_picks = load_baseline(baseline)
        room["findings"], resolved = continuity.stamp_baseline(
            room["findings"], prior_findings, prior_picks)

    items = [build_branch_item(room, finding) for finding in room["findings"]]
    items += [resolved_ghost_item(finding) for finding in resolved]

    sections = []
    facts_file = os.path.join(rundir, "FEATURE_FACTS.md")
    if os.path.exists(facts_file):
        sections.append({
            "title": "Feature facts — the pre-change world this lands in",
            "html": '<pre style="white-space:pre-wrap;font:13px/1.5 ui-monospace,Menlo,monospace">'
                    f"{html.escape(open(facts_file).read())}</pre>",
        })
    if room["summary"].get("module_summary"):
        sections.append({
            "title": "What this change-set does — read from the diff, independent of its commit messages",
            "html": f"<p>{html.escape(room['summary']['module_summary'])}</p>",
        })
    if room["facts"]:
        sections.append({
            "title": "What the branch claims — from the commit messages and stated intent",
            "html": facts_html(room),
        })
    per_file = per_file_section_html(room)
    if per_file:
        sections.append({"title": "Per-file changes", "html": per_file})
    features = path_features_section(rundir)
    if features:
        sections.append(features)

    status = "validated clean" if room["converged"] else "some findings left unconfirmed — they default to discuss"
    voice = room["phase1"].get("voice", "plain")
    n_files = len(manifest.get("files", [])) or len({f.get("file") for f in room["findings"]})
    intro_bits = [f"{n_files} changed files", f"{len(room['findings'])} findings"]
    if voice and voice != "plain":
        intro_bits.append(f"voice: {voice}")
    baseline_bit = baseline_intro_bit(room["findings"], resolved) if baseline else None
    if baseline_bit:
        intro_bits.append(baseline_bit)
    intro_bits.append(status)

    file_values = sorted({item["facets"].get("file") for item in items} - {None})
    facets = [
        {"key": "severity", "values": ["high", "med", "low"]},
        {"key": "angle", "values": ANGLES, "help": ANGLE_HELP},
    ]
    if len(file_values) > 1:
        facets.append({"key": "file", "values": file_values, "style": "select"})
    if status_facet_needed(room["findings"], resolved):
        facets.append({"key": "status", "values": STATUS_ORDER, "help": STATUS_HELP})

    render({
        "title": f"audit-branch — {label}",
        "key": f"audit-branch:{os.path.basename(rundir)}",
        "blob_header": f"audit-branch apply ({label})",
        "subtitle": " · ".join(intro_bits),
        "brief": (f"The audit of branch {label}: one card per finding across the changed files, "
                  "with evidence and the generated patch. Applying runs the patch in-session "
                  "behind tests; discussing holds it; skipping closes it for this run."),
        "options": ["apply", "discuss", "skip"],
        "default": "skip",
        "expand_on": ["discuss"],
        "option_help": {
            "apply": "apply the generated patch in-session, gated by the file's tests and a shown diff; a note adjusts it",
            "discuss": "no change yet; talk it through in the session first (unconfirmed findings start here)",
            "skip": "leave the finding as it stands with no change made this run",
        },
        "facets": facets,
        "sections": sections,
        "items": items,
    }, rundir)
    print(f"file://{os.path.join(rundir, 'picker.html')}", flush=True)


if __name__ == "__main__":
    main()
