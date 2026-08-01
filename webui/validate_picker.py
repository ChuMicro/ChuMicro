#!/usr/bin/env python3
"""Render a full-feature fixture through render_picker.py and gate the output (no LLM).

A PostToolUse hook (picker_edit_gate.py here, wired in .claude/settings.json) runs this
automatically on every agent edit to render_picker.py or this file.  Agent directive for
every other path to a picker change (scripted edits, edits outside an agent session, a
repo this directory migrates into): run this file plus validate_picker_smoke.py yourself
before committing.  The gates only need to run when the picker changed, so no repo-wide
preflight wiring is assumed.  Gates, in order:

  1. render:     a fixture spec exercising every schema feature (columns pick_ui with an empty
                 candidate and a 4-box scroll row, seeded edit box, all four badge severities,
                 chip + select + help facets, a multiline diff, nested sections, an informational
                 card, page_width) renders without error;
  2. structure:  those features actually landed in the HTML: candidate/edit/radio-row counts,
                 facet bar + select, diff lines, the page-width override, the collapsed card;
  3. js:         every <script> block passes `node --check`;
  4. drift:      the file's three coupled namespaces stay in sync: every class a CSS selector
                 names, every class/id the page JS queries, and every data-* attribute the JS
                 reads must exist in the rendered HTML or be set by the JS itself. Renaming
                 .cardfold in one place and not the others keeps every other tool green, and this
                 gate is the one that catches it;
  5. vnu:        the W3C Nu checker with --also-check-css, when resolvable ($VNU_JAR, `vnu` on
                 PATH, or ./node_modules/vnu-jar); SKIPPED loudly otherwise. The only gate that
                 sees content-model violations and CSS a browser would silently drop.  Both
                 classes shipped before it existed (a <div> inside <span class="ftext">;
                 `font:14.5px/1.5 inherit`, which drops the whole declaration).

Gates 3 and 5 need an external binary (node / java+jar) and SKIP loudly when it is missing;
gates 1, 2, and 4 are pure Python and always run. A sixth gate, floor, proves the content
floor gates: a planted thin spec (bare A/B, no summary, no brief) must refuse to render.

THE CLI CONTRACT: a validator never mutates its subject. The fixture lane renders only into
a directory this file OWNS; the subject lane only ever READS the page it was handed:

  validate_picker.py                     fixture lane: render the all-feature fixture into a
                                         fresh temp dir and run every gate (what the edit hook
                                         and a hand-run after a renderer change want);
  validate_picker.py <page.html|dir>     subject lane: READ-ONLY checks against an already
                                         rendered page (a directory resolves <dir>/picker.html).
                                         Nothing under the argument is written or re-rendered;
                                         the fixture-shaped gates (render/structure/drift) SKIP
                                         loudly because they can only assert about the fixture;
  validate_picker.py --fixture-out DIR   fixture lane into a DIR you name; REFUSES loud when DIR
                                         already holds files rather than overwriting them.

Until 2026-07-27 the positional argument WAS the fixture's output dir: pointing it at a real
rendered decision page silently replaced that page's spec.json and picker.html with the fixture
(the human then opened the served page and saw "some generic template"), and pointing it at a
.html file crashed in os.makedirs. Both are structurally impossible now: the fixture render
takes an owned directory, never the caller's argument.

Stdout: one `OK <gate>` / `SKIPPED <gate> (...)` / `FAIL <gate>: <finding>` line per result.
Exit 0 when no gate failed (skips allowed); exit 1 otherwise.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import render_picker  # noqa: E402

USAGE = """Usage: a validator never mutates its subject:
  validate_picker.py                     fixture lane: render the all-feature fixture into a temp
                                         dir this file owns and run every gate
  validate_picker.py <page.html|dir>     subject lane: READ-ONLY checks against an already
                                         rendered page (a dir resolves <dir>/picker.html);
                                         nothing under the argument is written or re-rendered
  validate_picker.py --fixture-out DIR   fixture lane into a DIR you name; refuses loud when DIR
                                         already holds files"""


FIXTURE = {
    "title": "validator fixture: every renderer feature",
    "key": "validate-fixture",
    "blob_header": "validator fixture picks",
    "subtitle": "4 findings · 1 high · fixture",
    "intro_html": ('<p>Intro block with <a href="#card-3">a deep link</a> and <code>inline code</code>. '
                   "This fixture decides nothing real: it exists so the validator can render every "
                   "renderer feature once and assert each one landed in the emitted HTML.</p>"),
    "sections": [
        {"title": "What this file does", "html": "<p>Top-level section body.</p>", "open": True},
        {"title": "Per-file understanding (2 files)",
         "sections": [
             {"title": "a.py", "html": "<p>child section <small>faint</small> <code>mono</code></p>"},
             {"title": "b.py", "html": "<pre>preformatted\nblock</pre>"},
         ]},
    ],
    "options": ["apply", "discuss", "skip"],
    "default": "skip",
    "decided_facet": True,
    "page_width": 1280,
    "expand_on": ["discuss"],
    "option_help": {
        "apply": "make the proposed change exactly as the card presents it",
        "discuss": "hold the change and talk it through in the session first",
        "skip": "leave the finding exactly as it stands with no change",
    },
    "items": [
        {
            "id": "1",
            "title": "full-featured finding card with <angle brackets> & ampersand",
            "badge": "CRITICAL",
            "source": "correctness lens",
            "meta": "effort: small · Foo.bar @ tick",
            "summary": 'A summary with "quotes" and <tags> to exercise escaping.',
            "where": {"place": "heartbeat.py · Foo.bar", "code": "ticks_diff(a, b) >= 0"},
            "why": "consequence in one sentence",
            "fix": "the exact proposed change",
            "detail": {"label": "how the code does this", "text": "mechanism prose…"},
            "warning": "Validator: fix needs review (seeded warning)",
            "evidence": 'SKILL.md:3 "quoted evidence" <unescaped?>',
            "diff": {
                "location": "SKILL.md:3",
                "old": "current line one\ncurrent line two",
                "new": "proposed line one\nproposed line two",
            },
            "body_html": "<p>trusted body block</p>",
            "collapsed": True,
            "facets": {"severity": "high", "angle": "trap", "file": "heartbeat.py"},
        },
        {
            "id": "2",
            "title": "columns pick_ui card",
            "badge": "MINOR",
            "summary": "side-by-side candidates plus an edit box",
            "pick_ui": {
                "style": "columns",
                "candidates": [
                    {"value": "suggested", "label": "suggested, writer 1",
                     "chips": ["2 lines shorter", "names the actor"],
                     "text": "candidate text one",
                     "more": {"label": "full symbol", "text": "def full(): ..."}},
                    {"value": "alt", "label": "alternative, writer 2", "text": ""},
                    {"value": "third", "label": "third writer", "text": "candidate three"},
                    {"value": "fourth", "label": "fourth writer, forces scroll", "text": "candidate four"},
                ],
                "edit": {"value": "edit", "label": "edit it myself", "seed": "current text\nsecond line"},
                "context": {"label": "original", "text": "the docstring as it stands today"},
            },
            "default": "suggested",
            "facets": {"severity": "med", "angle": "craft", "file": "a.py"},
        },
        {
            "id": "3",
            "title": "informational card, no radios",
            "options": [],
            "badge": "AMBIGUOUS",
            "summary": "informational only",
            "where": "bare-string where · one mono line",
            "prose": [{"id": "impact",
                       "prompt": "Describe anything this report misses about the failure's real impact.",
                       "placeholder": "a paragraph or two"}],
            "facets": {"severity": "low", "angle": "craft", "file": "b.py"},
        },
        {
            "id": "4",
            "title": "plain decision card on the page-wide option set",
            "badge": "IMPORTANT",
            "summary": "page options, page default, a notes box, and the suggested-pick star marker",
            "prose": [{"id": "context",
                       "prompt": "What context should the next reviewer have before re-running this?",
                       "rows": 3}],
            "suggested": "discuss",            # triage bulk layer: ★ marker + the accept-all button
            "facets": {"severity": "med", "angle": "trap", "file": "a.py"},
        },
        {
            "id": "5",
            "title": "carried finding: status chip + greyed card",
            "badge": "MINOR",
            "summary": "baseline/waiver continuity: a persisting card, greyed, chip-stamped",
            "status": "persisting",            # renders a .statuschip in the card head
            "muted": True,                     # greys the card (.card.muted)
            "facets": {"severity": "low", "angle": "trap", "file": "a.py", "status": "persisting"},
        },
    ],
    "facets": [
        {"key": "severity", "values": ["high", "med", "low"]},
        {"key": "angle", "help": {"trap": "correctness lens"}},
        {"key": "file", "style": "select"},
        {"key": "status", "values": ["new", "persisting", "resolved", "waived"]},
    ],
}

findings = []
skips = []


def gate(name, problems):
    if problems:
        for problem in problems:
            print(f"FAIL {name}: {problem}", flush=True)
        findings.extend(problems)
    else:
        print(f"OK {name}", flush=True)


def skip(name, reason):
    print(f"SKIPPED {name} ({reason})", flush=True)
    skips.append(name)


def check_structure(page):
    """Every fixture feature left its mark in the HTML.  A feature the renderer quietly stopped
    emitting fails here even though the page is valid."""
    expectations = [
        ('class="ccol"', 4, "candidate boxes (item 2)"),
        ('class="cedit"', 1, "edit box (item 2)"),
        ('class="editbox"', 1, "edit textarea"),
        ('class="cnone"', 1, "empty-candidate placeholder"),
        ('class="opts"', 3, "default radio rows (items 1 + 4 + 5)"),
        ('class="dline dold"', 2, "diff old lines"),
        ('class="dline dnew"', 2, "diff new lines"),
        ("--pagew:1280px", 1, "page_width override"),
        ('data-fold="1"', 1, "collapsed card (item 1)"),
        ('class="fselect"', 1, "select-style facet group"),
        ('class="ccontext"', 1, "context box (item 2)"),
        ('data-key="decided"', 2, "decided facet chips"),
        ('class="badge b-critical"', 1, "CRITICAL badge"),
        ('class="badge b-important"', 1, "IMPORTANT badge"),
        ('class="badge b-minor"', 2, "MINOR badge (items 2 + 5)"),
        ('class="badge b-ambiguous"', 1, "AMBIGUOUS badge"),
        ('class="statuschip"', 1, "status chip (item 5)"),
        ("card collapsible muted", 1, "greyed carried card (item 5)"),
        ('class="prose"', 2, "prose textareas (items 3 + 4)"),
        ('class="prosefield"', 2, "prose field wrappers"),
        ('id="substate"', 1, "submitted-state line"),
    ]
    problems = []
    for needle, count, label in expectations:
        got = page.count(needle)
        if got != count:
            problems.append(f"{label}: expected {count} × {needle!r}, found {got}")
    if re.search(r'<div class="card[^"]*" id="card-3"[^>]*>.*?input type="radio"', page, re.S):
        first_card = page.split('id="card-3"', 1)[1].split('class="card', 1)[0]
        if 'type="radio"' in first_card:
            problems.append("informational card 3 carries radios")
    return problems


def check_js(outdir, page):
    node = shutil.which("node")
    if not node:
        skip("js", "node not on PATH")
        return
    problems = []
    for index, script in enumerate(re.findall(r"<script>(.*?)</script>", page, re.S)):
        path = os.path.join(outdir, f"script_{index}.js")
        with open(path, "w") as handle:
            handle.write(script)
        result = subprocess.run([node, "--check", path], capture_output=True, text=True)
        if result.returncode != 0:
            problems.append(f"script block {index}: {result.stderr.strip().splitlines()[-1]}")
    gate("js", problems)


def _selector_text(css):
    """The selector part of every rule: class tokens in declarations (hex colors, decimals,
    quoted strings) never enter the namespace comparison."""
    selectors, depth, current = [], 0, []
    for char in css:
        if char == "{":
            if depth == 0:
                selectors.append("".join(current))
                current = []
            depth += 1
        elif char == "}":
            depth = max(0, depth - 1)
        elif depth == 0:
            current.append(char)
    return "\n".join(selectors)


def check_drift(page):
    """The renderer's three coupled namespaces agree: classes the Python emits into HTML,
    selectors in the CSS constant, and query strings and dataset reads in the SCRIPT constant."""
    html_classes = {token for attr in re.findall(r'class="([^"]*)"', page) for token in attr.split()}
    html_ids = set(re.findall(r'id="([^"]*)"', page))
    html_data = set(re.findall(r'data-([\w-]+)="', page))

    css_classes = set(re.findall(r"\.([A-Za-z][\w-]*)", _selector_text(render_picker.CSS)))

    script = render_picker.SCRIPT
    js_set_classes = set(re.findall(r"classList\.(?:add|remove|toggle)\('([\w-]+)'", script))
    query_strings = re.findall(r"(?:querySelector(?:All)?|closest)\('([^']*)'", script)
    js_query_classes = {token for selector in query_strings
                        for token in re.findall(r"\.([A-Za-z][\w-]*)", selector)}
    js_ids = set(re.findall(r"getElementById\('([\w-]+)'\)", script)) | {
        token for selector in query_strings for token in re.findall(r"#([A-Za-z][\w-]*)", selector)}
    js_data_reads = set(re.findall(r"dataset\.(\w+)", script))
    js_data_writes = set(re.findall(r"dataset\.(\w+)\s*=", script))

    known_classes = html_classes | js_set_classes
    problems = []
    for name in sorted(css_classes - known_classes):
        problems.append(f"CSS selector .{name} matches nothing the fixture renders and the JS never sets it")
    for name in sorted(js_query_classes - known_classes):
        problems.append(f"JS queries .{name} but nothing renders or sets it")
    for name in sorted(js_ids - html_ids):
        problems.append(f"JS targets #{name} but no element carries that id")
    for name in sorted(js_data_reads - js_data_writes - html_data):
        problems.append(f"JS reads dataset.{name} but no data-{name} attribute is rendered or assigned")
    gate("drift", problems)


def _resolve_vnu():
    jar = os.environ.get("VNU_JAR")
    if jar and os.path.exists(jar):
        return ["java", "-jar", jar]
    vnu = shutil.which("vnu")
    if vnu:
        return [vnu]
    local_jar = os.path.join(os.getcwd(), "node_modules", "vnu-jar", "build", "dist", "vnu.jar")
    if os.path.exists(local_jar) and shutil.which("java"):
        return ["java", "-jar", local_jar]
    return None


def check_floor(outdir):
    """The content floor actually gates: a planted thin spec (bare A/B options, no summary,
    no brief, no option_help) must refuse to render, with FLOOR defect lines on stderr."""
    bad = {"title": "who wins", "blob_header": "floor probe", "options": ["A", "B"],
           "items": [{"id": "1", "title": "who wins"}]}
    bad_dir = os.path.join(outdir, "floor-probe")
    os.makedirs(bad_dir, exist_ok=True)
    bad_path = os.path.join(bad_dir, "spec.json")
    with open(bad_path, "w") as handle:
        json.dump(bad, handle)
    result = subprocess.run([sys.executable, os.path.join(HERE, "render_picker.py"), bad_path, bad_dir],
                            capture_output=True, text=True)
    problems = []
    if result.returncode != 2:
        problems.append(f"planted floor violation rendered anyway (exit {result.returncode})")
    if "FLOOR" not in result.stderr:
        problems.append("floor defects did not reach stderr")
    if os.path.exists(os.path.join(bad_dir, "picker.html")):
        problems.append("a floor-failing spec still wrote picker.html")
    gate("floor", problems)


def check_vnu(page_path):
    command = _resolve_vnu()
    if not command:
        skip("vnu", "set VNU_JAR, or install via `npm i vnu-jar` / `brew install vnu`")
        return
    result = subprocess.run([*command, "--also-check-css", page_path], capture_output=True, text=True)
    errors = [line for line in result.stderr.splitlines() if "error:" in line]
    for line in result.stderr.splitlines():
        if "warning:" in line:
            print(f"  vnu warning: {line.strip()}", flush=True)
    gate("vnu", errors)


def render_fixture(outdir):
    """Write FIXTURE into `outdir` and render it; return the page path (WS17 E1).

    The ONE place either validator turns the shared fixture into a page: validate_picker_smoke
    calls this too, so the smoke and the static gates cannot drift onto two different pages.

    `outdir` MUST be a directory the validator owns (a temp dir, or an empty --fixture-out): this
    writes spec.json and picker.html into it. Never pass a caller-supplied path here.
    Raises RuntimeError carrying the renderer's stderr when the render fails.
    """
    os.makedirs(outdir, exist_ok=True)
    spec_path = os.path.join(outdir, "spec.json")
    with open(spec_path, "w") as handle:
        json.dump(FIXTURE, handle, indent=1, ensure_ascii=False)
    render = subprocess.run([sys.executable, os.path.join(HERE, "render_picker.py"), spec_path, outdir],
                            capture_output=True, text=True)
    if render.returncode != 0:
        raise RuntimeError(render.stderr.strip() or f"renderer exited {render.returncode}")
    return os.path.join(outdir, "picker.html")


def own_fixture_dir(requested):
    """A directory the validator OWNS to render the fixture into: a fresh temp dir by default.

    An explicitly requested one must be absent or empty. The fixture render overwrites spec.json
    and picker.html; doing that to a directory that already holds someone's real decision page is
    the exact data loss this contract exists to prevent, so a non-empty target EXITS LOUD instead
    of being cleaned, merged into, or silently used.
    """
    if requested is None:
        return tempfile.mkdtemp(prefix="picker-validate-")
    outdir = os.path.abspath(requested)
    if os.path.exists(outdir) and not os.path.isdir(outdir):
        sys.exit(f"--fixture-out {outdir} is a file, not a directory")
    existing = sorted(os.listdir(outdir)) if os.path.isdir(outdir) else []
    if existing:
        sys.exit(f"--fixture-out {outdir} already holds {', '.join(existing[:5])}: rendering the "
                 f"fixture there would overwrite spec.json and picker.html. Name an empty/new "
                 f"directory, or drop the flag to render into a temp dir.")
    os.makedirs(outdir, exist_ok=True)
    return outdir


def subject_page(argument):
    """Resolve the read-only subject: a rendered picker.html, or the directory holding one."""
    path = os.path.abspath(argument)
    if os.path.isdir(path):
        page_path = os.path.join(path, "picker.html")
        if not os.path.isfile(page_path):
            sys.exit(f"no rendered page at {page_path}: render one first:\n"
                     f"  render_picker.py <spec.json> {path}\n"
                     f"(this lane never renders for you: it validates a page as it stands)")
        return page_path
    if os.path.isfile(path):
        return path
    sys.exit(f"{path} does not exist: pass a rendered picker.html, the directory holding one, "
             f"or no argument at all to run the fixture lane.")


def _parse_argv(argv):
    """-> (subject_argument | None, fixture_out | None). Anything else exits loud with the usage."""
    if argv and argv[0] in ("-h", "--help"):
        print(USAGE, flush=True)
        sys.exit(0)
    if argv and argv[0] == "--fixture-out":
        if len(argv) != 2:
            sys.exit(f"--fixture-out takes exactly one directory\n{USAGE}")
        return None, argv[1]
    if len(argv) > 1:
        sys.exit(f"expected at most one argument, got {len(argv)}: {argv}\n{USAGE}")
    return (argv[0] if argv else None), None


def main():
    subject, fixture_out = _parse_argv(sys.argv[1:])

    if subject is None:                                   # fixture lane: our directory, our files
        outdir = own_fixture_dir(fixture_out)
        try:
            page_path = render_fixture(outdir)
        except RuntimeError as error:
            gate("render", [str(error)])
            sys.exit(1)
        gate("render", [])
        page = open(page_path).read()
        gate("structure", check_structure(page))
        check_js(outdir, page)
        check_drift(page)
        check_floor(outdir)
        check_vnu(page_path)
        print(f"fixture page: {page_path}", flush=True)
        sys.exit(1 if findings else 0)

    # subject lane: the page is read, never written; even node's scratch copies go to our temp dir
    page_path = subject_page(subject)
    page = open(page_path).read()
    fixture_only = "fixture-only gate: run with no argument to exercise it"
    skip("render", "read-only lane: validating the page exactly as it stands")
    skip("structure", fixture_only)
    scratch = tempfile.mkdtemp(prefix="picker-validate-scratch-")
    try:
        check_js(scratch, page)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    skip("drift", fixture_only)
    check_vnu(page_path)
    print(f"validated read-only (unchanged): {page_path}", flush=True)
    sys.exit(1 if findings else 0)


if __name__ == "__main__":
    main()
