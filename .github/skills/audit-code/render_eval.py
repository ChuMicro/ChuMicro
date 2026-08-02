#!/usr/bin/env python3
"""audit-code — build the decision-page spec from one or more run rooms and render it via the shared picker.

Reads each run room's eval.json + written.json + summary.json + validation.json + patches.json +
phase1.json, joins the writer's prose onto the fact ledger by id, and writes spec.json in the
shared picker schema (.claude/surfaces/render_picker.py), then invokes that renderer to produce
picker.html.

The mapping: one decision card per finding — severity badge, angle chip, effort/confidence meta
line, the writer's mechanism prose as the visible summary paragraph, the symbol as the blue
"where" row's place line with the quoted code on a mono line under it, the consequence as the
amber "why" row, the suggested fix as the green "fix" row, the generated patch as an old→new
diff (replace), a diff with only a + side (add), or evidence-block guidance (manual), and a
validator warning when a finding is unconfirmed. The findings render as
one severity-ordered list narrowed by a facet bar — severity and angle chips (angle help on
hover), plus a file dropdown in merge mode. Context lands above the decision area as collapsible
page-top sections.

Single-file mode (one room): sections are the independent module summary, the domain facts mined
from comments, and the per-symbol summaries with finding back-references.

Merge mode (--merge, library/folder scope): one page covers every room. Finding ids are
namespaced per file (heartbeat#3) so the paste-back blob stays unambiguous; the where row leads
with the file name; every card renders folded to a strip (title row, summary, radios, diff) so a
long list skims like a table — the badge and the warning flag say what deserves a click, nothing
starts open; every file's context nests inside one "Per-file understanding" section (plus a
LIBRARY_FACTS section when --lib names one), so the page top stays two drop-downs at any file
count; and merged.json in the output dir maps each namespace back to its run room + target for
the apply loop.

Defaults encode the apply policy: a validator-confirmed high-severity finding pre-selects apply,
an unconfirmed finding pre-selects discuss (invariant 7's push-back, encoded in the page), and
everything else pre-selects skip.

This script renders only. The orchestrator serves the page with .claude/surfaces/serve_picker.py
(PICKER_NO_OPEN=1, background), opens the printed SERVING url itself, and watches the server's
stdout for the submitted selection.

Usage:
  render_eval.py <rundir> <target.py>
  render_eval.py --merge <outdir> <rundir> <target.py> [<rundir> <target.py> ...] [--lib <LIBRARY_FACTS.md>]

Stdout: the renderer's `RENDERED <path>` line, `MERGED-MAP <path>` in merge mode, then
`file://<path>` as the no-server fallback.
"""
import html
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "_shared"))
import audit_continuity as continuity  # noqa: E402

SEV_RANK = {"high": 0, "med": 1, "low": 2}
EFFORT_RANK = {"small": 0, "medium": 1, "large": 2}
# baseline / waiver status a card can carry (phase 2/3/4): the facet values, hover help, and which
# statuses grey the card. "new" is the only one the eye should land on first, so it stays un-muted.
STATUS_ORDER = ["new", "persisting", "resolved", "waived"]
STATUS_HELP = {
    "new": "not in the baseline audit — raised for the first time this run",
    "persisting": "also in the baseline audit — carried forward, greyed so the new findings lead",
    "resolved": "in the baseline audit and gone now — no longer found",
    "waived": "matches a human waiver in plans/audit-waivers/ — suppressed with the recorded note",
}
MUTED_STATUSES = {"persisting", "resolved", "waived"}
ANGLE_HELP = {
    "trap": "correctness lens — inversions, off-by-ones, code that says one thing and does another, judged from comment-stripped code",
    "hazard": "adversarial-robustness lens — unbounded peer-controlled allocations, untrusted data reaching a sensitive sink, reentrancy windows, resources leaked on error paths",
    "drift": "comment/doc lens — claims a name, comment, or docstring makes that the code does not honor",
    "coverage": "test-gap lens — behaviors no test exercises, hollow tests, and tests that bless a bug",
    "clarity": "craft lens — confusing naming, hard-to-follow control flow, could-be-tighter",
    "path": "usage-path lens — transitive callers (callers of callers, optionally in consumer repos) judged in-session on full commented code, in feature terms; no clean room on purpose",
}
RENDERER = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        os.pardir, os.pardir, os.pardir,
                        ".claude", "surfaces", "render_picker.py")
USAGE = (
    "usage: render_eval.py <rundir> <target.py> [--baseline <prior eval.json>]\n"
    "       render_eval.py --merge <outdir> <rundir> <target.py> [<rundir> <target.py> ...] [--lib <LIBRARY_FACTS.md>]"
)


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


def load_room(rundir, target):
    """Read one run room's artifacts, join the writer's prose onto the fact ledger by id, and
    return everything the spec builder needs (findings sorted by severity then effort)."""
    rundir = os.path.abspath(rundir)

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
    return {
        "rundir": rundir,
        "target": target,
        "file_name": os.path.basename(target),
        "findings": findings,
        "facts": evaluation.get("domain_facts", []),
        "summary": summary,
        "validator_map": validator_map,
        "converged": not (validation.get("any_unreal") or validation.get("any_fix_unsound")),
        "patch_map": patch_map,
        "phase1": phase1,
    }


def is_unconfirmed(room, finding_id):
    verdict = room["validator_map"].get(finding_id, {})
    return bool(verdict) and (not verdict.get("real", True) or not verdict.get("fix_sound", True))


def apply_continuity_fields(item, finding):
    """Stamp a card with its baseline / waiver status (phase 2–4): a status chip, greying for a
    carried card, and a skip default plus the recorded note for a waived or prior-skipped finding.
    No-op on a plain first-run audit (the finding carries no continuity metadata)."""
    status = finding.get("baseline_status") or ("waived" if finding.get("suppressed") else None)
    if not status:
        return item
    item["status"] = status
    item.setdefault("facets", {})["status"] = status
    if status in MUTED_STATUSES:
        item["muted"] = True
    riders = []
    if finding.get("suppressed") and finding.get("waiver_note"):
        item["default"] = "skip"
        riders.append(f"Waived (plans/audit-waivers): {finding['waiver_note']}")
    if finding.get("preload_choice"):
        item["default"] = finding["preload_choice"]
        if finding.get("preload_note"):
            riders.append(f"Carried from a prior skip: {finding['preload_note']}")
    if riders:
        item["warning"] = (" ".join(riders) + " " + item.get("warning", "")).strip()
    return item


def resolved_ghost_item(finding, namespace=None):
    """An informational (radio-less) card for a finding that the baseline audit raised and this run
    no longer finds — greyed, chip-stamped resolved, so a fixed defect reads as progress rather than
    vanishing silently."""
    finding_id = finding.get("id")
    severity = finding.get("severity", "low")
    angle = finding.get("angle", "trap")
    file = finding.get("file")
    place = finding.get("symbol", "?")
    if file:
        place = f"{file} · {place}"
    item = {
        "id": f"{namespace}#resolved-{finding_id}" if namespace else f"resolved-{finding_id}",
        "title": (finding.get("title") or finding.get("defect") or "resolved finding")[:80],
        "badge": severity,
        "source": angle,
        "status": "resolved",
        "muted": True,
        "options": [],
        "where": {"place": place, "code": finding.get("site", "")},
        "summary": "Resolved: present in the baseline audit, no longer found this run.",
        "why": finding.get("bite", ""),
        "facets": {"severity": severity, "angle": angle, "status": "resolved"},
        "collapsed": True,
    }
    if namespace:
        item["facets"]["file"] = os.path.basename(file) if file else namespace
    elif file:
        # branch page: the file facet keys on the repo-relative path (build_branch_item does too)
        item["facets"]["file"] = file
    return item


def load_baseline(baseline_path):
    """Prior findings + the prior run's selection picks from a persisted eval.json (its
    selection.txt sibling, when the prior run's blob was persisted alongside)."""
    prior = json.load(open(baseline_path)) if os.path.exists(baseline_path) else {"findings": []}
    prior_findings = prior.get("findings", []) if isinstance(prior, dict) else prior
    picks = {}
    sibling = os.path.join(os.path.dirname(os.path.abspath(baseline_path)), "selection.txt")
    if os.path.exists(sibling):
        picks = continuity.parse_picks(open(sibling).read())
    return prior_findings, picks


def status_facet_needed(findings, resolved):
    return bool(resolved) or any(f.get("baseline_status") or f.get("suppressed") for f in findings)


def baseline_intro_bit(findings, resolved):
    """A `vs baseline: N new · M persisting · K resolved` subtitle fragment, or None."""
    counts = {"new": 0, "persisting": 0, "resolved": len(resolved), "waived": 0}
    for finding in findings:
        status = finding.get("baseline_status") or ("waived" if finding.get("suppressed") else None)
        if status in counts:
            counts[status] += 1
    live = [f"{counts[key]} {key}" for key in STATUS_ORDER if counts[key]]
    return ("vs baseline: " + " · ".join(live)) if live else None


def build_item(room, finding, namespace=None):
    """Build one picker card from a finding. A namespace (merge mode) prefixes the id
    (heartbeat#3), leads the where row with the file name, tags the card for the file-chip
    filter, and folds the card to a strip — nothing starts open; the severity badge and the
    warning flag the picker puts on an unconfirmed card's strip say what deserves a click."""
    finding_id = finding.get("id")
    severity = finding.get("severity", "low")
    verdict = room["validator_map"].get(finding_id, {})
    unconfirmed = is_unconfirmed(room, finding_id)
    angle = finding.get("angle", "trap")
    place = f"{room['file_name']} · {finding.get('symbol', '?')}" if namespace else finding.get("symbol", "?")
    # a merged path finding names the file the fix would edit (often a caller, not the target);
    # lead the where row with it so the reader doesn't assume the target file
    if not namespace and finding.get("file"):
        place = f"{finding['file']} · {finding.get('symbol', '?')}"
    item = {
        "id": f"{namespace}#{finding_id}" if namespace else str(finding_id),
        "title": finding["title"],
        "badge": severity,
        "source": angle,
        "meta": f"effort: {finding.get('effort', '?')} · confidence: {finding.get('confidence', '?')}",
        "where": {"place": place, "code": finding.get("site", "")},
        "why": finding["consequence"],
        "fix": finding["suggested_fix"],
        "facets": {"severity": severity, "angle": angle},
        "default": "discuss" if unconfirmed else ("apply" if severity == "high" else "skip"),
    }
    if namespace:
        item["facets"]["file"] = room["file_name"]
        item["collapsed"] = True
    # the writer's mechanism prose reads as the card summary, in view rather than behind a
    # collapsible -- the reader sees how the code produces the defect without an extra click
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


def card_anchor(item_id):
    """Mirror of the shared picker's per-card element id (card-heartbeat-3): every
    non-alphanumeric in the card id becomes a dash."""
    return "card-" + re.sub(r"[^A-Za-z0-9_-]", "-", item_id)


def summary_section_html(room, namespace=None):
    """One per-symbol understanding block: each symbol's qualname, signature, summary, and
    back-references to the finding ids (namespaced in merge mode) raised against it, each
    linking to its decision card."""
    finding_ids_by_symbol = {}
    for finding in room["findings"]:
        finding_ids_by_symbol.setdefault(finding.get("symbol"), []).append(finding.get("id"))
    symbol_blocks = []
    for symbol in room["summary"].get("symbols", []):
        qualname = symbol.get("qualname", "")
        related = sorted(finding_ids_by_symbol.get(qualname, []))
        links = []
        for finding_id in related:
            card_id = f"{namespace}#{finding_id}" if namespace else str(finding_id)
            label = card_id if namespace else f"#{finding_id}"
            links.append(f'<a href="#{card_anchor(card_id)}">{html.escape(label)}</a>')
        related_text = (" <small>findings: " + ", ".join(links) + "</small>") if links else ""
        symbol_blocks.append(
            f"<p><code>{html.escape(qualname)}</code> <small>{html.escape(symbol.get('signature', ''))}</small><br>"
            f"{html.escape(symbol.get('summary', ''))}{related_text}</p>"
        )
    return "".join(symbol_blocks)


def facts_html(room):
    return "".join(
        f"<p>• {html.escape(str(fact.get('fact', '')))} "
        f"<small>({html.escape(str(fact.get('source_site', '')))}, {html.escape(str(fact.get('confidence', '')))})</small></p>"
        for fact in room["facts"]
    )


def path_features_section(rundir):
    """The usage-path lens's feature map as a page-top section, when the trace produced one."""
    path = os.path.join(rundir, "path_features.json")
    if not os.path.exists(path):
        return None
    features = json.load(open(path)).get("features", [])
    if not features:
        return None
    blocks = []
    for feature in features:
        entries = ", ".join(feature.get("entry_points", []))
        touched = ", ".join(feature.get("touched_by", []))
        blocks.append(
            f"<p><b>{html.escape(feature.get('name', ''))}</b> — {html.escape(feature.get('summary', ''))}<br>"
            f"<small>entry points: {html.escape(entries) or '—'} · touched by: {html.escape(touched) or '—'}</small></p>"
        )
    return {"title": f"Features on the usage path — {len(features)} mapped, and what touches them",
            "html": "".join(blocks)}


def render(spec, output_dir):
    spec_path = os.path.join(output_dir, "spec.json")
    with open(spec_path, "w") as handle:
        json.dump(spec, handle, indent=1)
    result = subprocess.run([sys.executable, RENDERER, spec_path, output_dir], capture_output=True, text=True)
    sys.stdout.write(result.stdout)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise SystemExit(result.returncode)


def main_single(rundir, target, baseline=None):
    room = load_room(rundir, target)
    resolved = []
    if baseline:
        prior_findings, prior_picks = load_baseline(baseline)
        room["findings"], resolved = continuity.stamp_baseline(
            room["findings"], prior_findings, prior_picks, default_file=os.path.basename(target))
    items = [build_item(room, finding) for finding in room["findings"]]
    items += [resolved_ghost_item(finding) for finding in resolved]

    sections = []
    if room["summary"].get("module_summary"):
        sections.append({
            "title": "What this file does — read from the code, independent of its comments",
            "html": f"<p>{html.escape(room['summary']['module_summary'])}</p>",
        })
    if room["facts"]:
        sections.append({
            "title": "Domain facts — knowledge the comments carry that the code alone can't show",
            "html": facts_html(room),
        })
    symbols_html = summary_section_html(room)
    if symbols_html:
        sections.append({"title": "Per-symbol understanding", "html": symbols_html})
    features = path_features_section(room["rundir"])
    if features:
        sections.append(features)

    # severity and angle counts live on the facet chips below the title; the subtitle keeps
    # only what the bar cannot say
    status = "validated clean" if room["converged"] else "some findings left unconfirmed — they default to discuss"
    voice = room["phase1"].get("voice", "plain")
    intro_bits = [f"{len(room['findings'])} findings"]
    if voice and voice != "plain":
        intro_bits.append(f"voice: {voice}")
    baseline_bit = baseline_intro_bit(room["findings"], resolved) if baseline else None
    if baseline_bit:
        intro_bits.append(baseline_bit)
    intro_bits.append(status)

    facets = [
        {"key": "severity", "values": ["high", "med", "low"]},
        {"key": "angle", "values": ["trap", "hazard", "drift", "coverage", "clarity", "path"], "help": ANGLE_HELP},
    ]
    if status_facet_needed(room["findings"], resolved):
        facets.append({"key": "status", "values": STATUS_ORDER, "help": STATUS_HELP})

    file_name = room["file_name"]
    render({
        "title": f"audit-code — {file_name}",
        "key": f"audit-code:{file_name}:{os.path.basename(room['rundir'])}",
        "blob_header": f"audit-code apply ({file_name})",
        "subtitle": " · ".join(intro_bits),
        "brief": (f"The audit of {file_name}: one card per finding, with its evidence and the "
                  "generated patch. Applying runs the patch in-session behind the file's tests; "
                  "discussing holds it for the session; skipping closes it for this run."),
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
    }, room["rundir"])
    print(f"file://{os.path.join(room['rundir'], 'picker.html')}", flush=True)


def main_merge(output_dir, room_args, library_facts):
    output_dir = os.path.abspath(output_dir)
    rooms = []
    used_namespaces = set()
    for rundir, target in room_args:
        room = load_room(rundir, target)
        namespace = os.path.splitext(room["file_name"])[0]
        bump = 2
        while namespace in used_namespaces:
            namespace = f"{os.path.splitext(room['file_name'])[0]}-{bump}"
            bump += 1
        used_namespaces.add(namespace)
        room["namespace"] = namespace
        rooms.append(room)

    # one global ordering across files: worst first, then cheapest, so the top of every
    # angle tab is the library's most pressing item regardless of which file it lives in
    pairs = [(room, finding) for room in rooms for finding in room["findings"]]
    pairs.sort(key=lambda pair: (SEV_RANK.get(pair[1].get("severity"), 3),
                                 EFFORT_RANK.get(pair[1].get("effort"), 3),
                                 pair[0]["namespace"], pair[1].get("id", 0)))
    items = [build_item(room, finding, namespace=room["namespace"]) for room, finding in pairs]

    sections = []
    if library_facts and os.path.exists(library_facts):
        with open(library_facts) as handle:
            facts_text = handle.read()
        sections.append({
            "title": "Library facts — domain, cross-file contracts, glossary",
            "html": f'<pre style="white-space:pre-wrap;font:13px/1.5 ui-monospace,Menlo,monospace">{html.escape(facts_text)}</pre>',
        })
    # one drop-down per file would stack into a wall at library scale; every file nests
    # inside a single top-level section, each row titled with the summarizer's first sentence
    # so the collapsed list already says what each file is
    per_file = []
    for room in rooms:
        module_summary = room["summary"].get("module_summary", "")
        blocks = []
        if module_summary:
            blocks.append(f"<p>{html.escape(module_summary)}</p>")
        blocks.append(facts_html(room))
        blocks.append(summary_section_html(room, namespace=room["namespace"]))
        body = "".join(blocks)
        if not body:
            continue
        title = room["file_name"]
        if module_summary:
            # the gist is the summary's first clause: cut at a colon (summaries often lead
            # "Implements X: details…"), else at the first sentence, capped as a backstop
            gist = module_summary.split(". ")[0].split(":")[0].rstrip(".")
            if len(gist) > 90:
                gist = gist[:87].rstrip() + "…"
            title = f"{room['file_name']} — {gist}"
        per_file.append({"title": title, "html": body})
    if per_file:
        sections.append({"title": f"Per-file understanding — {len(per_file)} files", "sections": per_file})

    converged = all(room["converged"] for room in rooms)
    status = "validated clean" if converged else "some findings left unconfirmed — they default to discuss"
    voices = {room["phase1"].get("voice", "plain") for room in rooms}
    intro_bits = [f"{len(rooms)} files", f"{len(pairs)} findings"]
    if len(voices) == 1 and "plain" not in voices:
        intro_bits.append(f"voice: {voices.pop()}")
    intro_bits.append(status)

    file_names = [room["file_name"] for room in rooms]
    title_scope = ", ".join(file_names) if len(file_names) <= 3 else f"{len(file_names)} files"
    facets = [
        {"key": "severity", "values": ["high", "med", "low"]},
        {"key": "angle", "values": ["trap", "hazard", "drift", "coverage", "clarity", "path"], "help": ANGLE_HELP},
        {"key": "file", "values": file_names, "style": "select"},
    ]
    if status_facet_needed([finding for _room, finding in pairs], []):
        facets.append({"key": "status", "values": STATUS_ORDER, "help": STATUS_HELP})
    render({
        "title": f"audit-code — {title_scope}",
        "key": f"audit-code:merged:{os.path.basename(output_dir)}",
        "blob_header": f"audit-code apply ({len(rooms)} files)",
        "subtitle": " · ".join(intro_bits),
        "brief": (f"The merged audit of {title_scope}: every room's findings on one page, one card "
                  "per finding with its evidence and generated patch. Applying runs a patch "
                  "in-session behind its file's tests; skipping closes it for this run."),
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
    }, output_dir)

    merged_map = {room["namespace"]: {"rundir": room["rundir"], "target": room["target"]} for room in rooms}
    merged_path = os.path.join(output_dir, "merged.json")
    with open(merged_path, "w") as handle:
        json.dump(merged_map, handle, indent=1)
    print(f"MERGED-MAP {merged_path}", flush=True)
    print(f"file://{os.path.join(output_dir, 'picker.html')}", flush=True)


def main():
    arguments = sys.argv[1:]
    baseline = None
    if "--baseline" in arguments:
        index = arguments.index("--baseline")
        baseline = arguments[index + 1]
        arguments = arguments[:index] + arguments[index + 2:]
    if arguments and arguments[0] == "--merge":
        arguments = arguments[1:]
        library_facts = None
        if "--lib" in arguments:
            index = arguments.index("--lib")
            library_facts = arguments[index + 1]
            arguments = arguments[:index] + arguments[index + 2:]
        if len(arguments) < 3 or len(arguments[1:]) % 2:
            raise SystemExit(USAGE)
        room_args = [(arguments[i], arguments[i + 1]) for i in range(1, len(arguments), 2)]
        main_merge(arguments[0], room_args, library_facts)
    elif len(arguments) == 2:
        main_single(arguments[0], arguments[1], baseline=baseline)
    else:
        raise SystemExit(USAGE)


if __name__ == "__main__":
    main()
