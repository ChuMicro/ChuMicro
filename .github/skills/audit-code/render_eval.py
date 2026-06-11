#!/usr/bin/env python3
"""audit-code — build the decision-page spec from a run room and render it via the shared picker.

Reads the run room's eval.json + written.json + summary.json + validation.json + patches.json +
phase1.json, joins the writer's prose onto the fact ledger by id, and writes <rundir>/spec.json in
the shared picker schema (../_shared/picker/render_picker.py), then invokes that renderer to
produce <rundir>/picker.html.

The mapping: one decision card per finding — severity badge, angle chip, effort/confidence/site
meta line, the consequence as the amber "why" row, the suggested fix as the green "fix" row, the
generated patch as an old→new diff (replace), a diff with only a + side (add), or evidence-block
guidance (manual), the mechanism prose behind a collapsible detail, and a validator warning when a
finding is unconfirmed. Tabs group findings by angle (trap / drift / coverage / clarity),
severity-ordered within each, each tab opening with a help line naming its lens. Context lands
above the decision area as collapsible page-top sections — the independent module summary (open
on load), the domain facts mined from comments, and the per-symbol summaries with finding
back-references.

Defaults encode the apply policy: a validator-confirmed high-severity finding pre-selects apply,
an unconfirmed finding pre-selects discuss (invariant 7's push-back, encoded in the page), and
everything else pre-selects skip.

This script renders only. The orchestrator serves the page with ../_shared/picker/serve_picker.py
(PICKER_NO_OPEN=1, background), opens the printed SERVING url itself, and watches the server's
stdout for the submitted selection.

Usage: render_eval.py <rundir> <target.py>   # writes <rundir>/spec.json + <rundir>/picker.html
Stdout: the renderer's `RENDERED <path>` line, then `file://<path>` as the no-server fallback.
"""
import html
import json
import os
import subprocess
import sys

SEV_RANK = {"high": 0, "med": 1, "low": 2}
EFFORT_RANK = {"small": 0, "medium": 1, "large": 2}
TAB_HELP = {
    "trap": "correctness lens — inversions, off-by-ones, code that says one thing and does another, judged from comment-stripped code",
    "drift": "comment/doc lens — claims a name, comment, or docstring makes that the code does not honor",
    "coverage": "test-gap lens — behaviors no test exercises, hollow tests, and tests that bless a bug",
    "clarity": "craft lens — confusing naming, hard-to-follow control flow, could-be-tighter",
}
RENDERER = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "_shared", "picker", "render_picker.py")


def patch_fields(patch):
    """Map one generated patch onto picker card fields: a replace patch becomes an old→new diff,
    an add patch a +-only diff, and a manual patch evidence-block guidance."""
    if not patch:
        return {}
    kind = patch.get("kind")
    location = patch.get("location_hint", "")
    if kind == "manual":
        note = patch.get("note") or "This fix is structural — apply it by hand."
        return {"evidence": f"manual patch — {note}"}
    if kind == "add":
        return {"diff": {"location": f"add{(' in ' + location) if location else ''}", "new": patch.get("after", "")}}
    fields = {"diff": {"location": location, "old": patch.get("before", ""), "new": patch.get("after", "")}}
    if patch.get("note"):
        fields["evidence"] = patch["note"]
    return fields


def main():
    rundir, target = os.path.abspath(sys.argv[1]), sys.argv[2]

    def load(name, default):
        path = os.path.join(rundir, name)
        return json.load(open(path)) if os.path.exists(path) else default

    evaluation = load("eval.json", {"findings": [], "domain_facts": []})
    if isinstance(evaluation, list):
        evaluation = {"findings": evaluation, "domain_facts": []}
    summary = load("summary.json", {"module_summary": "", "symbols": []})
    validation = load("validation.json", {})
    phase1 = load("phase1.json", {})
    patch_map = {p.get("id"): p for p in load("patches.json", {"patches": []}).get("patches", [])}
    written = load("written.json", {"findings": []})
    written_map = {w.get("id"): w for w in (written.get("findings", []) if isinstance(written, dict) else [])}

    findings = evaluation.get("findings", [])
    # eval.json holds the FACTS (defect / bite / fix fragments); written.json holds the reader PROSE
    # the writer composed in the chosen register. Join by id, falling back to the fragments when the
    # writer skipped one, so a finding always renders.
    for finding in findings:
        prose = written_map.get(finding.get("id"), {})
        finding["title"] = prose.get("title") or (finding.get("defect", "") or "finding")[:80]
        finding["consequence"] = prose.get("consequence") or finding.get("bite", "")
        finding["problem"] = prose.get("problem") or finding.get("defect", "")
        finding["suggested_fix"] = prose.get("suggested_fix") or finding.get("fix", "")
    findings.sort(key=lambda finding: (SEV_RANK.get(finding.get("severity"), 3),
                                       EFFORT_RANK.get(finding.get("effort"), 3), finding.get("id", 0)))
    validator_map = {entry.get("id"): entry for entry in validation.get("findings", [])}
    converged = not (validation.get("any_unreal") or validation.get("any_fix_unsound"))
    file_name = os.path.basename(target)
    voice = phase1.get("voice", "plain")

    items = []
    for finding in findings:
        finding_id = finding.get("id")
        severity = finding.get("severity", "low")
        angle = finding.get("angle", "trap")
        verdict = validator_map.get(finding_id, {})
        unconfirmed = bool(verdict) and (not verdict.get("real", True) or not verdict.get("fix_sound", True))
        item = {
            "id": str(finding_id),
            "title": finding["title"],
            "badge": severity,
            "meta": f"effort: {finding.get('effort', '?')} · confidence: {finding.get('confidence', '?')}"
                    f" · {finding.get('symbol', '?')} @ {finding.get('site', '?')}",
            "why": finding["consequence"],
            "fix": finding["suggested_fix"],
            "tab": angle,
            "default": "discuss" if unconfirmed else ("apply" if severity == "high" else "skip"),
        }
        if finding.get("problem"):
            item["detail"] = {"label": "how the code does this", "text": finding["problem"]}
        if unconfirmed:
            tag = "problem unconfirmed" if not verdict.get("real", True) else "fix needs review"
            item["warning"] = f"Validator: {tag}. {verdict.get('note', '')}".strip()
        item.update(patch_fields(patch_map.get(finding_id)))
        items.append(item)

    sections = []
    if summary.get("module_summary"):
        sections.append({
            "title": "What this file does — read from the code, independent of its comments",
            "html": f"<p>{html.escape(summary['module_summary'])}</p>",
            "open": True,
        })
    facts = evaluation.get("domain_facts", [])
    if facts:
        fact_lines = "".join(
            f"<p>• {html.escape(str(fact.get('fact', '')))} "
            f"<small>({html.escape(str(fact.get('source_site', '')))}, {html.escape(str(fact.get('confidence', '')))})</small></p>"
            for fact in facts
        )
        sections.append({
            "title": "Domain facts — knowledge the comments carry that the code alone can't show",
            "html": fact_lines,
        })
    symbols = summary.get("symbols", [])
    if symbols:
        finding_ids_by_symbol = {}
        for finding in findings:
            finding_ids_by_symbol.setdefault(finding.get("symbol"), []).append(finding.get("id"))
        symbol_blocks = []
        for symbol in symbols:
            qualname = symbol.get("qualname", "")
            related = sorted(finding_ids_by_symbol.get(qualname, []))
            related_text = (" <small>findings: " + ", ".join(f"#{finding_id}" for finding_id in related) + "</small>") if related else ""
            symbol_blocks.append(
                f"<p><code>{html.escape(qualname)}</code> <small>{html.escape(symbol.get('signature', ''))}</small><br>"
                f"{html.escape(symbol.get('summary', ''))}{related_text}</p>"
            )
        sections.append({
            "title": "Per-symbol understanding",
            "html": "".join(symbol_blocks),
        })

    by_severity = phase1.get("by_severity", {})
    by_angle = phase1.get("by_angle", {})
    severity_line = ", ".join(f"{by_severity[key]} {key}" for key in ("high", "med", "low") if by_severity.get(key))
    angle_line = ", ".join(f"{by_angle[key]} {key}" for key in ("trap", "drift", "coverage", "clarity") if by_angle.get(key))
    status = "validated clean" if converged else "some findings left unconfirmed — they default to discuss"
    intro_bits = [f"{len(findings)} findings"]
    if severity_line:
        intro_bits.append(severity_line)
    if angle_line:
        intro_bits.append(angle_line)
    if voice and voice != "plain":
        intro_bits.append(f"voice: {voice}")
    intro_bits.append(status)

    spec = {
        "title": f"audit-code — {file_name}",
        "key": f"audit-code:{file_name}:{os.path.basename(rundir)}",
        "blob_header": f"audit-code apply ({file_name})",
        "intro_html": f"<pre>{html.escape(' · '.join(intro_bits))}</pre>",
        "options": ["apply", "discuss", "skip"],
        "default": "skip",
        "option_help": {
            "apply": "apply the generated patch in-session, gated by the file's tests and a shown diff — a note adjusts it",
            "discuss": "no change yet; talk it through in the session first (unconfirmed findings start here)",
            "skip": "leave as is",
        },
        "tabs": [{"name": name, "help": TAB_HELP[name]}
                 for name in ("trap", "drift", "coverage", "clarity")],
        "sections": sections,
        "items": items,
    }
    spec_path = os.path.join(rundir, "spec.json")
    with open(spec_path, "w") as handle:
        json.dump(spec, handle, indent=1)

    render = subprocess.run([sys.executable, RENDERER, spec_path, rundir], capture_output=True, text=True)
    sys.stdout.write(render.stdout)
    if render.returncode != 0:
        sys.stderr.write(render.stderr)
        raise SystemExit(render.returncode)
    print(f"file://{os.path.join(rundir, 'picker.html')}", flush=True)


if __name__ == "__main__":
    main()
