#!/usr/bin/env python3
"""Render a generic decision page (picker.html) from a JSON spec.

One card per item, carrying its id, a severity badge, a source chip naming what raised
the item, a plain-words summary, labeled why / fix rows, the evidence in a small mono
block, a pick area, and a notes box. The pick area defaults to a radio row; an item's
`pick_ui` swaps in a different strategy (today: "columns", side-by-side candidate
boxes with an optional seeded edit textarea). A sticky bar serializes every choice
into a line-oriented paste-back blob:

    PICKS \u2014 <blob_header>
    1 = apply
      note 1: <free text, newlines collapsed>
    2 = edit
      edit 2: <the edit box's exact text, newlines as literal \\n, backslashes doubled>
    3 = skip
      other 3: <the write-in text when the pick is the allow_other seat>
      field 3.key: <a text field's answer, escaped like edit>
      multi 3.areas = alpha, beta            (checked values, comma-joined)
      scale 3.confidence = 4/5               (always rides: a range always has a value)
      menu 3.component = playback
      upload 3.shot = /abs/path/under/hub/state/surfaces/<sid>/in/shot.png
                                             (one line per file; copy it out promptly,
                                              resolved surfaces are eventually pruned)

A note on an applied item is the user's wording adjustment: on a default-strategy
page there is no separate "edit" option, so the orchestrator honors apply-with-note as
apply-with-this-wording. A card whose `pick_ui` defines an edit choice carries a
dedicated edit box instead: its exact text rides back on its own `edit <id>:` line
(the consuming parser decodes the escapes), and the note box stays a note.
The Submit button carries a live summary of the picks that differ from their
defaults ("Submit \u2014 3 apply \u00b7 1 discuss"), so the moment of commitment shows
what is being committed.

The page is self-contained (inline CSS + JS) and works from file://. Copy
selection always works; a Submit button appears only when the page is served
over http (see serve_picker.py, which loops the POST back to the session).
Choices and notes persist in localStorage under the spec's `key`, so a reload
mid-review restores them. A theme button toggles light/dark (default follows
the system).

Spec schema:

    {
      "title": "audit-skill report for git-commit",      // page heading
      "key": "audit-skill:git-commit:20260611T",          // localStorage namespace; change per run
      "blob_header": "audit-skill picks (git-commit)",    // first blob line after "PICKS \u2014 "
      "subtitle": "4 findings · 1 high · validated",      // optional metadata line under the title (escaped);
                                                          // use this for counts/status, not intro_html
      "intro_html": "<p>…</p>",                           // optional block above the cards (trusted HTML)
      "sections": [                                       // optional page-top context drop-downs,
        {"title": "What this file does",                  // rendered between intro and the decision
         "html": "<p>…</p>",                              // area (trusted HTML); open: true expands
         "open": true},                                   // the section on load
        {"title": "Per-file understanding (10 files)",    // a section may nest child sections instead of
         "sections": [{"title": "a.py", "html": "…"}]}    // (or alongside) html; ten files stay one
      ],                                                  // top-level row, expanding to one row per file
      "options": ["apply", "discuss", "skip"],            // page-wide option set
      "default": "skip",                                  // page-wide pre-checked option (omit for none)
      "page_width": 1280,                                 // content-column width in px (default 920); a
                                                          // page of side-by-side candidates earns more
                                                          // width than a finding list
      "expand_on": ["discuss"],                           // optional: picking one of these options expands
                                                          // the card and focuses its notes box, for options
                                                          // whose substance lives in the note (a discussion
                                                          // opener, a wording adjustment)
      "option_help": {                                    // optional legend, rendered above the cards AND as
        "apply": "make the proposed change (a note adjusts its wording)",   // hover text on every card's
        "discuss": "no change yet, talk it through in chat first",          // radio labels, so the meaning
        "skip": "leave as is"                                               // travels with each decision
      },
      "items": [
        {
          "id": "1",                                      // rides back in the blob; unique
          "title": "vague description stem",              // card heading (escaped)
          "badge": "IMPORTANT",                           // optional pill; known severities get colors
          "source": "loader lens, frontmatter contract",  // optional chip: what raised this item
          "meta": "effort: small · Foo.bar @ tick",       // optional faint line under the heading
          "summary": "plain-words description…",          // optional paragraph under the heading
          "where": {"place": "heartbeat.py · Foo.bar",    // optional labeled row: place renders as text,
                    "code": "ticks_diff(a, b) >= 0"},     // the quoted code on its own mono line under it
                                                          // (a bare string renders as one mono line)
          "why": "consequence in one sentence",           // optional labeled row
          "fix": "the exact proposed change",             // optional labeled row
          "detail": {                                     // optional collapsible block
            "label": "how the code does this",
            "text": "mechanism prose…"
          },
          "status": "persisting",                         // optional chip in the card head (any short word;
                                                          // the audit skills pass new / persisting / resolved
                                                          // / waived for baseline + waiver continuity)
          "muted": true,                                  // optional: grey the whole card (un-greys on hover),
                                                          // for a carried finding, so the eye lands on new ones
          "warning": "Validator: fix needs review …",     // optional amber callout; also puts an amber
                                                          // ⚠ in the card head (hover shows the text),
                                                          // so even a folded strip signals "go deeper"
          "evidence": "SKILL.md:3 \\"quote\\"",            // optional mono block
          "diff": {                                       // optional old→new block; when the fix is
            "location": "SKILL.md:3",                     // replacement text, emit this INSTEAD of
            "old": "current text",                        // the evidence + fix pair. Multiline old/new
            "new": "proposed text"                        // render one −/+ marked line per source line
          },
          "body_html": "<p>…</p>",                        // optional extra block (trusted HTML)
          "options": ["high", "medium", "low"],           // optional per-item override; [] makes the card
                                                          // informational: no radios, no blob/tally entry
          "default": "medium",                            // optional per-item override
          "pick_ui": {                                    // optional pick-area strategy; absent = the default
            "style": "columns",                           // radio row. "columns": one box per candidate, side
            "candidates": [                               // by side (4+ scroll horizontally), the whole box
              {"value": "suggested",                      // clickable; value rides in the blob like any option
               "label": "suggested, writer pass 3",       // box heading next to its radio
               "chips": ["2 lines shorter"],              // optional faint comparison chips
               "text": "the candidate text…",             // the box body, a mono block
               "more": {"label": "full symbol",           // optional per-candidate expander
                        "text": "…"}}
            ],
            "edit": {"value": "edit",                     // optional editable choice: a full-width textarea
                     "label": "edit it myself",           // seeded with `seed`; its exact text rides back as
                     "seed": "current text"},             // an `edit <id>:` blob line (newline-escaped)
            "context": {"label": "original",              // optional non-selectable lead box above the
                        "text": "the current text…"}      // candidates: the baseline they are read against
          },                                              // with pick_ui, the choice set is candidates[].value
                                                          // + edit.value and the options field is ignored
          "notes": true,                                  // notes box (default: true on decision cards,
                                                          // false on informational ones)
          "prose": [                                      // prompted paragraph answers, when the real
            {"id": "impact",                              // answer is sentences rather than a pick; an
             "prompt": "What did you observe when …?",    // informational card may carry only these.
             "placeholder": "a paragraph or two",         // Each rides the blob as its own line:
             "seed": "", "rows": 4}                       //   prose <item>.<id>: <text, \\n-escaped>
          ],
          "allow_other": true,                            // radio-row cards only: append an "other"
                                                          // write-in seat (radio + text box; typing
                                                          // selects it). Needs option_help["other"].
          "media": [                                      // artifacts ON the card: shown inline AND
            {"kind": "image", "src": "shot.png",          // downloadable. src paths resolve relative
             "caption": "the failing screen",             // to the spec file and are COPIED into
             "alt": "settings screen"},                   // <outdir>/assets/, so the page dir stays
            {"kind": "compare",                           // self-contained (file:// and hub alike;
             "before": {"src": "a.png", "label": "88.0"}, // the hub serves assets Range-capable, so
             "after":  {"src": "b.png", "label": "fix"},  // audio/video scrub). Kinds:
             "caption": "same screen, both builds"},      //   image  : gallery tile + lightbox
            {"kind": "audio", "src": "mix.m4a",           //   compare: before/after opacity slider
             "caption": "the rendered alert tone"},       //   audio  : player + download
            {"kind": "video", "src": "run.webm",          //   video  : player + download
             "caption": "capture of the flow"},           //   file   : a plain download card for
            {"kind": "file", "src": "evidence.zip",       //             anything (zip, pdf, logs…)
             "note": "full run bundle for the ticket"}    // consecutive images share one gallery row
          ],
          "fields": [                                     // structured short-form asks beyond radios
            {"kind": "text", "id": "key",                 //   text : one line, seedable (pre-filled)
             "label": "Jira issue key",
             "help": "The issue this run's evidence should attach to when it posts.",
             "seed": "PMA-", "placeholder": "PMA-…",
             "required": true},                           // required fields gate Submit until answered
            {"kind": "multi", "id": "areas",              //   multi: checkboxes, many picks;
             "label": "Which rooms showed the symptom?",  //           `default` pre-checks values;
             "options": ["bedroom pair", "office"],       //           blob line is comma-joined
             "option_help": {"office": "the Five"},       //           (comma banned in values)
             "default": ["office"]},
            {"kind": "scale", "id": "confidence",         //   scale: a labeled range; BOTH end
             "label": "How confident are you it fixed?",  //           labels are floor-required so
             "min": 1, "max": 5, "default": 3,            //           the number carries meaning
             "low": "not at all", "high": "fully"},
            {"kind": "menu", "id": "component",           //   menu : one pick from a LONG list (a
             "label": "Which component owns this?",       //           radio row past ~6 options);
             "options": ["playback", "setup", "voice"],   //           option_help becomes hover text
             "default": ""},
            {"kind": "upload", "id": "shot",              //   upload: the human hands files TO the
             "label": "Drop the screenshot you took",     //           session (drag or browse; needs
             "accept": "image/*", "multiple": true}       //           the page served via the hub)
          ],
          "collapsed": true,                              // optional: start the card folded to a strip (title
                                                          // row + radios + summary + diff if present). Every
                                                          // card folds/expands on a title-row click; this sets
                                                          // the initial state. For long pages a reader skims
          "facets": {"severity": "high",                  // optional facet values, one per facet group the
                     "angle": "trap",                     // page defines below; the facet bar narrows the
                     "file": "heartbeat.py"}              // list to cards matching every selected group
        }
      ],
      "facets": [                                         // optional facet-bar definition: one row per group.
        {"key": "severity",                               // values: explicit order (others append by first
         "values": ["high", "med", "low"]},               // appearance); label: caption (defaults to key);
        {"key": "angle",                                  // help: hover text per chip value. style: "select"
         "help": {"trap": "correctness lens, …"}},        // renders the group as one dropdown, the right
        {"key": "file", "style": "select"}                // shape past ~6 values. Chip rows render first (in
      ]                                                   // spec order, then picked); select rows render last,
                                                          // keeping the chips in one area
    }

A pick-area strategy changes only how choices render: every strategy emits radios
named pick:<id>, so the blob, tally, picked facet, expand_on, and Reset stay
strategy-agnostic. A new strategy is a new branch in pick_area_html() plus its CSS;
the page JS needs nothing. In the columns strategy the whole candidate box is
clickable, the checked box carries an accent ring, and typing in the edit textarea
selects its radio; Reset returns the textarea to its seed.

The facet bar is the page's one narrowing mechanism, and there are no tabs (a finding
list is one dataset; tabs hide most of it and tax cross-tab comparison). Chips toggle:
multi-select within a group reads as OR, groups combine as AND, an empty group
means no narrowing. A card missing a value for a selected group is narrowed out.
Hidden cards stay in the DOM, so the blob, tally, and Reset always cover them.
A chip's live count ignores its own group's selection (standard faceted search),
so within-group numbers stay stable while you multi-select; a non-active chip
whose count drops to zero dims and stops responding, so a dead-end combination
is visible before the click, and a selection that empties the whole list shows a
"nothing matches" state with its own clear button; a clear-filters button
appears in the bar while anything is active. A select-style group narrows to one
value at a time, its option labels carrying the same live counts. Selections
persist per page key. Items render in spec order, so ordering (e.g. by severity)
is the spec author's job.

When at least one decision card exists, the bar gains a virtual `picked` row
(suppress with "picked_facet": false) whose chips track the live radio values, so you
can narrow to your apply set for a final look before submitting. `picked` is a
reserved facet key. "decided_facet": true adds a `decided` row (pending / done):
a card turns done when the human actively decides it: picks a candidate box,
re-affirms the already-checked one, or re-affirms the edit box after typing in
it (picking the edit choice or typing only opens the work; clicking the box
again settles it, the same gesture as a candidate), so `pending` narrows to
the cards not yet visited; a done card's id carries a ✓. A candidate
pick also re-seeds a pristine edit box with that candidate's text; once the
human types there, their text is never replaced. `decided` is reserved too. Every card carries id card-<id, non-alphanumerics dashed>,
so trusted section or intro HTML can deep-link to a card (#card-heartbeat-3);
navigating to a folded card unfolds it, and the target card flashes an accent
ring that fades out.

A title-row click folds a card to a strip (title row, radios, the summary, and the
diff when one exists); `collapsed: true` sets the initial state, and
fold changes persist in localStorage like picks and notes do. Picking an option listed in
`expand_on` opens the card and focuses its notes box, for options whose
substance lives in the note. Reset returns the page to its rendered defaults:
picks to the default option, notes cleared, cards and page-top sections back to
their spec fold state; only the active tab and the active chip (navigation, not
decision state) survive it.

body_html and intro_html are written into the page unescaped, because the spec author
is the orchestrating session, not an untrusted source.

A CONTENT FLOOR runs before rendering (floor_failures below): a page with decision items
must carry a brief (intro_html or a plain-text `brief` field, 120+ characters, naming what
is being decided and what happens with the answer), every decision card needs a summary a
cold reader can decide from (60+ characters when the options are bare letters like A/B/tie,
whose meaning the summary must define), every radio-row option needs a full-sentence
option_help entry, prose prompts must be real questions, and fragment-joiners are banned
outside quoted spans. Fields hold the same line: every field carries a label, and a short
label needs a help sentence (8+ words) saying what belongs in the answer; a scale names
both of its ends; multi/menu need two or more options (multi values carry no commas); an
allow_other card explains its "other" seat in option_help; an image without a caption or
alt says nothing to a cold reader. Media src paths must exist on disk at render time
(checked after the floor, as MEDIA lines). A failing spec prints one FLOOR line per defect
and exits 2; fix the spec and re-render. `"floor_waived": "<reason, 20+ chars>"` skips the
floor, loudly.

Usage: render_picker.py <spec.json> [<output-dir>]    (default output dir: the spec's directory)
Stdout: `RENDERED <path>/picker.html` on success. Floor defects go to stderr, exit 2.

validate_picker.py (same directory) is this renderer's gate: it renders a full-feature fixture
and checks structure, JS syntax, CSS/JS/HTML namespace drift, and (when vnu is available) markup
+ CSS validity. A PostToolUse hook (picker_edit_gate.py here, wired in .claude/settings.json)
runs it automatically on every agent edit to this file; run it by hand after editing outside
an agent session.
"""
import html
import json
import os
import re
import shutil
import sys

_REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, _REPO)   # repo root, so `from webui import kit` resolves when run as a script
from webui import kit  # the ONE shared palette + content-key
from webui.theme import THEME_KEY, assert_full_dark_override

BADGE_CLASSES = {
    "critical": "b-critical",
    "important": "b-important",
    "minor": "b-minor",
    "ambiguous": "b-ambiguous",
    "high": "b-critical",
    "medium": "b-important",
    "med": "b-important",
    "low": "b-minor",
}

# ── The content floor: rich chrome must carry rich content ──────────────────────────────
# The ask gate holds AskUserQuestion to a wording floor; this is the same floor for picker
# specs, checked at render time. A decision page whose spec is too thin for a cold reader
# ("who wins" over bare letters, options with no help, no brief) prints one FLOOR line per
# defect and exits 2; the author fixes the spec and re-renders. A purely informational
# page passes untouched. `floor_waived` (a reason of at least 20 characters) skips the
# check, loudly, for the rare page the floor genuinely cannot fit.
_JOINER_NAMES = {"—": "an em-dash", " -- ": "' -- '", "→": "an arrow", "·": "a middot"}
_QUOTED_SPANS = re.compile(r'"[^"\n]*"|“[^”\n]*”|`[^`\n]*`')
_TAG_RE = re.compile(r"<[^>]+>")


def _first_joiner(text):
    """The first banned fragment-joiner in text with quoted spans blanked out, or None."""
    scannable = _QUOTED_SPANS.sub(" ", text or "")
    for token, name in _JOINER_NAMES.items():
        if token in scannable:
            return name
    return None


_FIELD_KINDS = ("text", "multi", "scale", "menu", "upload")
_MEDIA_KINDS = ("image", "compare", "audio", "video", "file")


def _field_failures(item_id, fields):
    """Floor defects in an item's `fields` list: unlabeled asks, meaningless scales,
    option sets the blob format cannot carry."""
    problems = []
    for index, field in enumerate(fields, 1):
        fid = field.get("id", index)
        where = f"item {item_id}: field {fid!r}"
        kind = field.get("kind", "text")
        if kind not in _FIELD_KINDS:
            problems.append(f"{where} has unknown kind {kind!r}; one of {list(_FIELD_KINDS)}")
            continue
        label = (field.get("label") or "").strip()
        help_text = (field.get("help") or "").strip()
        if not label:
            problems.append(f"{where} has no label; every field names what it collects")
        elif len(label.split()) < 8 and len(help_text.split()) < 8:
            problems.append(
                f"{where}: a short label needs a help sentence (8+ words) saying what "
                "belongs in the answer and what the session does with it")
        for text, name in ((label, "label"), (help_text, "help")):
            joiner = _first_joiner(text)
            if joiner:
                problems.append(f"{where}: {name} glues fragments with {joiner}: "
                                "write plain sentences (quoted spans are exempt)")
        if kind in ("multi", "menu"):
            options = [str(option) for option in field.get("options") or []]
            if len(options) < 2:
                problems.append(f"{where}: {kind} needs at least two options")
            for option in options:
                if kind == "multi" and "," in option:
                    problems.append(f"{where}: option {option!r} contains a comma, which the "
                                    "comma-joined multi blob line cannot carry")
                if "\n" in option:
                    problems.append(f"{where}: option {option!r} contains a newline, which a "
                                    "line-oriented blob cannot carry")
        if kind == "scale":
            low, high = field.get("min", 1), field.get("max", 5)
            if not (isinstance(low, int) and isinstance(high, int)
                    and low < high and high - low <= 10):
                problems.append(f"{where}: scale needs integer min < max spanning at most 10 steps")
            if not str(field.get("low") or "").strip() or not str(field.get("high") or "").strip():
                problems.append(f"{where}: a scale's numbers mean nothing alone; label both "
                                "ends (low and high)")
    return problems


def _media_failures(item_id, media):
    """Floor defects in an item's `media` list (existence on disk is checked at render
    time, after the floor, because the floor is a pure function of the spec)."""
    problems = []
    for index, entry in enumerate(media, 1):
        where = f"item {item_id}: media {index}"
        kind = entry.get("kind")
        if kind not in _MEDIA_KINDS:
            problems.append(f"{where} has unknown kind {kind!r}; one of {list(_MEDIA_KINDS)}")
            continue
        if kind == "compare":
            for side in ("before", "after"):
                if not (entry.get(side) or {}).get("src"):
                    problems.append(f"{where}: compare needs before.src and after.src")
        elif not entry.get("src"):
            problems.append(f"{where}: {kind} entry has no src")
        if kind == "image" and not (entry.get("caption") or entry.get("alt")):
            problems.append(f"{where}: an image with no caption and no alt says nothing to "
                            "a cold reader; say what the image shows")
    return problems


def floor_failures(spec):
    """Every content-floor defect in the spec, one plain sentence each."""
    page_options = spec.get("options", ["apply", "discuss", "skip"])
    items = spec.get("items", [])
    decision_items = [item for item in items if item_options(item, page_options)]
    problems = []
    if decision_items:
        brief = spec.get("brief") or _TAG_RE.sub(" ", spec.get("intro_html") or "")
        brief = " ".join(brief.split())
        if len(brief) < 120:
            problems.append(
                f"page brief is {len(brief)} characters: intro_html (or brief) must say in two "
                "or three plain sentences what is being decided, why it surfaced, and what "
                "happens with the answer (at least 120 characters)")
        joiner = _first_joiner(brief)
        if joiner:
            problems.append(f"page brief glues fragments with {joiner}: write plain sentences "
                            "(quoted spans are exempt)")
    option_help = spec.get("option_help", {})
    for item in decision_items:
        item_id = item.get("id", "?")
        context = " ".join(f'{item.get("summary", "")} {item.get("why", "")}'.split())
        options = item_options(item, page_options)
        all_short = bool(options) and all(len(str(option)) <= 3 for option in options)
        need = 60 if all_short else 40
        if len(context) < need:
            if all_short:
                problems.append(
                    f"item {item_id}: choices {options} carry no meaning on their own; the "
                    "summary must name the axis (what winning means here, what each choice "
                    f"implies, what happens next), at least {need} characters, found {len(context)}")
            else:
                problems.append(
                    f"item {item_id}: summary (or why) is {len(context)} characters; a cold "
                    "reader decides from the card alone, so say what is being decided and what "
                    f"hangs on it (at least {need} characters)")
        if (item.get("pick_ui") or {}).get("style") != "columns":
            for option in options:
                if len(option_help.get(option, "").split()) < 8:
                    problems.append(
                        f"option {option!r} needs an option_help sentence: at least 8 words on "
                        "what picking it does and when it is the right pick")
        for key in ("summary", "why", "fix"):
            joiner = _first_joiner(item.get(key) or "")
            if joiner:
                problems.append(f"item {item_id}: {key} glues fragments with {joiner}: write "
                                "plain sentences (quoted spans are exempt)")
    for item in items:
        item_id = item.get("id", "?")
        for index, field in enumerate(item.get("prose") or [], 1):
            prompt = (field.get("prompt") or "").strip()
            if len(prompt.split()) < 8:
                problems.append(
                    f"item {item_id}: prose prompt {field.get('id', index)!r} is "
                    f"{len(prompt.split())} words; ask a real question the human can answer "
                    "in paragraphs (at least 8 words)")
            joiner = _first_joiner(prompt)
            if joiner:
                problems.append(f"item {item_id}: prose prompt {field.get('id', index)!r} "
                                f"glues fragments with {joiner}: write plain sentences")
        if item.get("allow_other") and (item.get("pick_ui") or {}).get("style") != "columns":
            if len(option_help.get("other", "").split()) < 8:
                problems.append(
                    f"item {item_id}: allow_other adds an 'other' seat, so option_help "
                    "needs an 'other' entry (8+ words) saying what a write-in should carry")
        problems += _field_failures(item_id, item.get("fields") or [])
        problems += _media_failures(item_id, item.get("media") or [])
    for option, help_text in option_help.items():
        joiner = _first_joiner(help_text)
        if joiner:
            problems.append(f"option_help for {option!r} glues fragments with {joiner}: "
                            "write plain sentences")
    seen = set()
    unique = []
    for problem in problems:
        if problem not in seen:
            seen.add(problem)
            unique.append(problem)
    return unique

# The palette is the ONE kit source. These local names ALIAS the kit's semantic
# vars. Alias values are var(...), so they are theme-correct (resolve per active theme) AND
# exempt from the dark-override lint. The picker's existing CSS (which references --card /
# --why / --fix / --where / --blob-bg / --bar / --note-bg) is left untouched but now draws
# from one palette, which kills the three-different-accents drift. color-scheme stays per-theme
# (native form controls). Every hardcoded hex below is converted to a var (the dark-mode bug).
_KIT_PALETTE = (
    kit.palette_css() + "\n"
    " :root{color-scheme:light; --card:var(--panel); --blob-bg:var(--bg); --bar:var(--panel);"
    " --note-bg:var(--panel); --why:var(--warn); --fix:var(--good); --where:var(--accent)}\n"
    " :root[data-theme=dark]{color-scheme:dark}\n"
)

CSS = _KIT_PALETTE + kit.TOKENS_CSS + """
 body{font:15px/1.55 -apple-system,'Segoe UI',sans-serif;background:var(--bg);color:var(--fg);
  margin:0;padding:var(--s5) var(--s4) 110px;max-width:var(--pagew,920px);margin-inline:auto}
 .phead{display:flex;flex-direction:column;gap:var(--s2);margin:0 96px var(--s4) 0}
 h1{font-size:var(--t-title);font-weight:650;letter-spacing:-.01em;line-height:1.3;margin:0}
 .themebtn{position:fixed;top:14px;right:16px;font:inherit;font-size:13px;padding:6px 12px;border-radius:999px;
  border:1px solid var(--border);background:var(--card);color:var(--fg);cursor:pointer;z-index:10}
 .readout{display:flex;flex-wrap:wrap;gap:var(--s1) var(--s4);font:500 var(--t-micro)/1.7 var(--mono);
  color:var(--faint);text-transform:uppercase;letter-spacing:.07em}
 .intro{color:var(--faint);font-size:var(--t-body);margin:0;max-width:76ch}
 .intro pre{white-space:pre-wrap}
 .legend{font-size:var(--t-small);color:var(--faint);margin:0;max-width:90ch}
 details.section{background:var(--card);border:1px solid var(--border);border-radius:12px;
  padding:10px 16px;margin:10px 0}
 details.section>summary{cursor:pointer;font-weight:620;font-size:15px}
 details.section .sbody{margin-top:8px;font-size:14.5px}
 .sbody>details.section{background:var(--bg);margin:8px 0}
 .sbody>details.section>summary{font-size:14px}
 .sbody small{color:var(--faint)}
 .sbody code{font:13px ui-monospace,Menlo,monospace}
 .facetbar{display:flex;flex-direction:column;gap:7px;margin:18px 0 16px;
  background:var(--card);border:1px solid var(--border);border-radius:13px;padding:10px 14px}
 .fgroup{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
 .fglabel{font-size:11px;font-weight:800;letter-spacing:.5px;text-transform:uppercase;color:var(--fg);
  opacity:.75;min-width:64px}
 .fgroup button{font:inherit;font-size:13px;padding:3px 11px;border-radius:999px;border:1px solid var(--border);
  background:var(--card);color:var(--faint);cursor:pointer}
 .fgroup button:hover{color:var(--fg)}
 .fgroup button.active{border-color:var(--accent);background:var(--accent);color:#fff;font-weight:650}
 .fgroup button.dead{opacity:.35;pointer-events:none}
 .fgroup .fcount{font-size:11px;margin-left:6px;opacity:.8}
 .nomatch{background:var(--card);border:1px dashed var(--border);border-radius:12px;padding:18px;
  margin:12px 0;color:var(--faint);font-size:15px;text-align:center}
 .nomatch button{font:inherit;font-size:13px;border:none;background:none;color:var(--accent);
  cursor:pointer;padding:0 2px}
 .facetclear{align-self:flex-start;font:inherit;font-size:12px;border:none;background:none;
  color:var(--accent);cursor:pointer;padding:0 2px}
 .fselect{font:inherit;font-size:13px;padding:3px 8px;border-radius:8px;border:1px solid var(--border);
  background:var(--card);color:var(--fg)}
 .card.fhidden,.card.collapsed.fhidden{display:none}
 .legend b{color:var(--fg);font-weight:620}
 .card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:15px 17px;margin:12px 0;
  scroll-margin-top:14px}
 .card.muted{opacity:.6}
 .card.muted:hover,.card.muted:focus-within{opacity:1}
 .card.flash{animation:cardflash 1.8s ease-out}
 @keyframes cardflash{0%,30%{border-color:var(--accent);box-shadow:0 0 0 2px var(--accent)}
  100%{border-color:var(--border);box-shadow:0 0 0 0 transparent}}
 .cardhead{display:flex;align-items:baseline;gap:9px;flex-wrap:wrap}
 .chev{display:inline-block;color:var(--faint);font-size:12px;align-self:center;
  transition:transform .15s;transform:rotate(90deg)}
 .card.collapsible>.cardhead{cursor:pointer;user-select:none}
 .card.collapsed{display:flex;align-items:center;gap:8px 16px;flex-wrap:wrap;padding:9px 15px}
 .card.collapsed .chev{transform:rotate(0)}
 .card.collapsed>.cardhead{flex:1 1 auto;order:1}
 .card.collapsed>.cardfold,.card.collapsed>.notes{display:none}
 .card.collapsed>.opts{margin:0;flex:0 0 auto;order:2}
 .card.collapsed>.summary{order:3;flex:1 1 100%;margin:0;font-size:14.5px;color:var(--faint)}
 .card.collapsed>.diffblock{order:4;flex:1 1 100%;margin:0}
 .cardid{font-weight:700;color:var(--accent);font-size:17px}
 .cardtitle{font-weight:630}
 .badge{font-size:11px;font-weight:700;letter-spacing:.4px;padding:2px 8px;border-radius:999px;color:#fff;background:var(--faint)}
 .b-critical{background:var(--bad)} .b-important{background:var(--warn)} .b-minor{background:var(--faint)} .b-ambiguous{background:var(--accent)}
 .srcchip{font-size:11.5px;color:var(--faint);background:var(--chip);border-radius:999px;padding:2px 9px}
 .statuschip{font-size:11px;font-weight:700;letter-spacing:.3px;color:var(--faint);background:var(--chip);
  border:1px solid var(--border);border-radius:999px;padding:1px 8px;text-transform:uppercase}
 .cardmeta{margin:6px 0 0;font-size:12.5px;color:var(--faint)}
 .summary{margin:10px 0 0;font-size:15.5px}
 details.detail{margin:10px 0 0}
 details.detail>summary{cursor:pointer;font-size:13.5px;color:var(--accent)}
 details.detail .dtext{margin-top:6px;font-size:14.5px}
 .warning{margin:10px 0 0;background:color-mix(in srgb,var(--warn) 10%,transparent);
  border:1px solid color-mix(in srgb,var(--warn) 35%,transparent);border-radius:8px;padding:7px 10px;font-size:14px}
 .warnflag{color:var(--why);font-size:15px;align-self:center;cursor:help}
 .field{display:flex;gap:10px;margin:11px 0 0;font-size:15px}
 .flabel{flex:0 0 auto;width:60px;box-sizing:border-box;text-align:center;font-size:11.5px;font-weight:800;
  letter-spacing:.6px;text-transform:uppercase;border-radius:6px;padding:3px 6px;align-self:flex-start;
  color:var(--faint);background:var(--chip);overflow:hidden}
 .f-why .flabel{color:var(--why);background:color-mix(in srgb,var(--why) 13%,transparent)}
 .f-fix .flabel{color:var(--fix);background:color-mix(in srgb,var(--fix) 13%,transparent)}
 .f-where .flabel{color:var(--where);background:color-mix(in srgb,var(--where) 13%,transparent)}
 .f-where .ftext{padding-top:1px;font-size:14.5px}
 .f-where .ftext.mono{font:13.5px/1.7 ui-monospace,Menlo,monospace;padding-top:2px}
 .fcode{font:13px/1.6 ui-monospace,Menlo,monospace;color:var(--faint);margin-top:3px;white-space:pre-wrap}
 .f-fix{border-left:3px solid color-mix(in srgb,var(--fix) 45%,transparent);padding-left:9px;margin-left:-12px}
 .ftext{flex:1}
 .evidence{margin:9px 0 0;white-space:pre-wrap;background:var(--blob-bg);border:1px solid var(--border);
  border-radius:8px;padding:8px 10px;font:13px/1.5 ui-monospace,Menlo,monospace;color:var(--faint)}
 .diffblock{margin:9px 0 0;border:1px solid var(--border);border-radius:8px;overflow:hidden;
  font:13px/1.55 ui-monospace,Menlo,monospace}
 .diffloc{padding:4px 10px;background:var(--blob-bg);color:var(--faint);font-size:12px;border-bottom:1px solid var(--border)}
 .dline{padding:5px 10px;white-space:pre-wrap}
 .dold{background:color-mix(in srgb,var(--bad) 9%,transparent)}
 .dnew{background:color-mix(in srgb,var(--good) 10%,transparent)}
 .cardbody{margin:9px 0 0;font-size:15px}
 .opts{display:flex;gap:16px;flex-wrap:wrap;margin-top:12px}
 .opts label{cursor:pointer;display:flex;align-items:center;gap:6px;font-size:15px}
 .opts input{accent-color:var(--accent)}
 .candwrap{margin-top:12px}
 .candrow{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:10px;align-items:stretch;
  scrollbar-width:thin;scrollbar-color:var(--border) transparent}
 .candrow:has(.ccol:nth-child(4)){grid-template-columns:none;grid-auto-flow:column;
  grid-auto-columns:minmax(300px,340px);overflow-x:auto;scroll-snap-type:x proximity;padding-bottom:8px}
 .candrow:has(.ccol:nth-child(4))>.ccol{scroll-snap-align:start}
 .candrow::-webkit-scrollbar{height:8px}
 .candrow::-webkit-scrollbar-thumb{background:var(--border);border-radius:999px}
 .candrow::-webkit-scrollbar-track{background:transparent}
 .ccol{border:1px solid var(--border);border-radius:10px;padding:9px 11px;background:var(--blob-bg);
  min-width:0;display:flex;flex-direction:column;cursor:pointer;transition:border-color .15s,box-shadow .15s}
 .ccol:hover{border-color:var(--accent)}
 .ccol:has(input:checked),.cedit:has(input:checked){border-color:var(--accent);box-shadow:0 0 0 1px var(--accent),0 4px 16px var(--glow)}
 .ccol>label,.cedit>label{cursor:pointer;font-size:14px;font-weight:620;display:flex;gap:7px;align-items:baseline}
 .ccol input,.cedit input{accent-color:var(--accent);flex:0 0 auto}
 .cchips{display:flex;gap:5px;flex-wrap:wrap;margin-top:5px}
 .cchip{font-size:11px;color:var(--faint);background:var(--chip);border-radius:999px;padding:1px 8px}
 .ccol pre{flex:1 1 auto;margin:7px 0 0;background:var(--card);border:1px solid var(--border);border-radius:8px;
  padding:8px 10px;font:12.5px/1.55 ui-monospace,Menlo,monospace;white-space:pre-wrap;overflow-wrap:break-word;
  min-height:40px}
 .ccol pre.cnone{color:var(--faint);font-style:italic}
 .ccol details{margin-top:6px}
 .ccol details>summary{cursor:pointer;font-size:12px;color:var(--accent)}
 .ccol details pre{flex:none}
 .cedit{margin-top:10px;border:1px solid var(--border);border-radius:10px;padding:9px 11px;background:var(--blob-bg);
  cursor:pointer;transition:border-color .15s,box-shadow .15s}
 .cedit:hover{border-color:var(--accent)}
 .ccontext{border:1px dashed var(--border);border-radius:10px;padding:9px 11px;background:var(--blob-bg);
  margin-bottom:10px}
 .cclabel{font-size:11px;font-weight:800;letter-spacing:.5px;text-transform:uppercase;color:var(--faint)}
 .ccontext pre{margin:7px 0 0;background:var(--card);border:1px solid var(--border);border-radius:8px;
  padding:8px 10px;font:12.5px/1.55 ui-monospace,Menlo,monospace;white-space:pre-wrap;overflow-wrap:break-word}
 .ccontext pre.cnone{color:var(--faint);font-style:italic}
 .card.done .cardid::after{content:" ✓";color:var(--fix)}
 .editbox{width:100%;box-sizing:border-box;margin-top:7px;min-height:90px;resize:vertical;
  font:12.5px/1.55 ui-monospace,Menlo,monospace;border:1px solid var(--border);border-radius:8px;
  padding:8px 10px;background:var(--card);color:var(--fg)}
 .card.collapsed>.candwrap{display:none}
 .notes{width:100%;box-sizing:border-box;margin-top:10px;font:inherit;font-size:14.5px;line-height:1.5;
  border:1px solid var(--border);border-radius:8px;padding:7px 9px;min-height:36px;background:var(--note-bg);
  color:var(--fg);resize:vertical}
 .prosefield{margin-top:12px}
 .proselabel{display:block;font-size:13.5px;font-weight:650;color:var(--fg);margin-bottom:5px}
 .prose{width:100%;box-sizing:border-box;font:inherit;font-size:14.5px;line-height:1.55;
  border:1px solid var(--border);border-radius:8px;padding:8px 10px;min-height:84px;
  background:var(--note-bg);color:var(--fg);resize:vertical}
 .card.collapsed>.prosefield{display:none}
 #substate{color:var(--fix);font-size:12.5px}
 .selbar{position:fixed;bottom:0;left:50%;transform:translateX(-50%);width:calc(100% - 24px);max-width:var(--pagew,920px);
  box-sizing:border-box;background:var(--bar);backdrop-filter:blur(10px);border:1px solid var(--border);
  border-bottom:none;border-radius:var(--r2) var(--r2) 0 0;padding:var(--s2) var(--s4);font-size:var(--t-small);
  box-shadow:0 -8px 28px rgba(0,0,0,.20)}
 :root[data-theme=dark] .selbar{box-shadow:0 -8px 28px rgba(0,0,0,.55)}
 .selbar .row{display:flex;align-items:center;gap:var(--s3);flex-wrap:wrap}
 .selbar button{font:inherit;font-size:var(--t-small);padding:7px 15px;border-radius:var(--r2);border:1px solid var(--border);
  background:var(--card);color:var(--fg);cursor:pointer;transition:background .5s,color .5s,border-color .5s}
 .selbar button.primary{background:linear-gradient(135deg,var(--accent),var(--accent2));border-color:var(--accent);color:#fff;box-shadow:0 2px 12px var(--glow)}
 .selbar button.primary:hover{filter:brightness(1.07)}
 .selbar button:disabled{opacity:.5;cursor:not-allowed;filter:saturate(.4)}
 .selbar button.blocked{opacity:.55;filter:saturate(.4)}
 .ffield.missing{border-left:3px solid var(--bad);padding-left:10px;margin-left:-13px}
 .ffield.missing .proselabel{color:var(--bad)}
 .ffield.pulse{animation:fieldpulse 1.6s ease-out}
 @keyframes fieldpulse{0%,30%{background:color-mix(in srgb,var(--bad) 8%,transparent);
  box-shadow:0 0 0 2px var(--bad)}100%{background:transparent;box-shadow:0 0 0 0 transparent}}
 .selbar button.confirm{background:var(--good);border-color:var(--good);color:#fff;transition:none}
 .selbar #copybtn,.selbar #resetbtn{border-color:transparent;background:none;color:var(--faint)}
 .selbar #copybtn:hover,.selbar #resetbtn:hover{color:var(--fg);border-color:var(--border)}
 .selbar #copybtn.primary{border-color:var(--accent);background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff}
 .selbar #acceptall{border-color:var(--accent);color:var(--accent);background:none}
 .opts label.issugg{outline:2px solid color-mix(in srgb,var(--accent) 45%,transparent);outline-offset:1px;border-radius:6px}
 .sugg{color:var(--accent);font-size:11px;margin-left:3px}
 .card.kbfocus{box-shadow:0 0 0 2px var(--accent)}
 .kbhint{color:var(--faint);font-size:12px;margin-left:4px}
 #count{font:500 var(--t-micro)/1.7 var(--mono);color:var(--faint);text-transform:uppercase;letter-spacing:.07em}
 .blobwrap{margin-left:auto}
 .blobwrap[open]{flex-basis:100%;margin-left:0}
 .blobwrap>summary{font-size:12px;color:var(--faint);cursor:pointer}
 .hint{font-size:12px;color:var(--faint);margin:6px 0 0}
 #blob{width:100%;box-sizing:border-box;margin-top:8px;font:12.5px/1.5 ui-monospace,Menlo,monospace;
  border:1px solid var(--border);border-radius:8px;padding:8px;min-height:46px;background:var(--blob-bg);color:var(--fg)}
 .mediablock{margin:10px 0 0}
 .ffield{margin-top:12px}
 .card.collapsed>.ffield{display:none}
 .flhead{display:flex;align-items:baseline;gap:6px}
 .freq{color:var(--bad);font-weight:700;cursor:help}
 .fhelp{font-size:12.5px;color:var(--faint);margin:2px 0 6px;max-width:80ch}
 .fld-text{width:100%;box-sizing:border-box;font:inherit;font-size:14.5px;border:1px solid var(--border);
  border-radius:8px;padding:7px 10px;background:var(--note-bg);color:var(--fg)}
 .fchkrow{display:flex;gap:14px;flex-wrap:wrap}
 .fchk{cursor:pointer;display:flex;align-items:center;gap:6px;font-size:14.5px}
 .fchk input{accent-color:var(--accent)}
 .fld-menu{font:inherit;font-size:14px;padding:6px 10px;border-radius:8px;border:1px solid var(--border);
  background:var(--note-bg);color:var(--fg);max-width:100%}
 .scalewrap{display:flex;align-items:center;gap:10px}
 .scale-end{font-size:12px;color:var(--faint);flex:0 0 auto;max-width:14ch}
 .scalewrap input{flex:1;accent-color:var(--accent)}
 .scaleval{font:600 13px ui-monospace,Menlo,monospace;color:var(--accent);min-width:34px;text-align:center}
 .otherwrap{display:flex;align-items:center;gap:6px}
 .otherbox{font:inherit;font-size:14px;border:1px solid var(--border);border-radius:8px;padding:4px 8px;
  background:var(--note-bg);color:var(--fg);min-width:180px}
 .uplist{list-style:none;margin:8px 0 0;padding:0;font-size:13px;text-align:left}
 .uplist li{display:flex;align-items:center;gap:8px;padding:3px 0;color:var(--fg)}
 .uplist .rm{border:none;background:none;color:var(--bad);cursor:pointer;font-size:13px;padding:0 4px}
 .upmsg{font-size:12px;margin-top:6px}
 .upmsg.bad{color:var(--bad)}
""" + kit.MEDIA_CSS

SCRIPT = """
<script>
(function () {
  var KEY = 'picker:' + (window.SPEC.key || 'x');
  var HEADER = 'PICKS \\u2014 ' + (window.SPEC.blob_header || window.SPEC.key || 'selection');
  var root = document.documentElement;
  // one theme model: THEME_KEY is the single source of truth. Embedded under the hub shell
  // (framed), this page hides its own toggle and follows the shell live via storage events.
  var framed = (window.self !== window.top);
  var savedTheme = null;
  try { savedTheme = localStorage.getItem('__THEME_KEY__'); } catch (e) {}
  var dark = savedTheme ? savedTheme === 'dark' : (window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches);
  function applyTheme(d) {
    root.dataset.theme = d ? 'dark' : 'light';
    var tb = document.getElementById('themebtn');
    tb.hidden = framed;
    tb.textContent = d ? 'light mode' : 'dark mode';
  }
  function setTheme(d) {
    applyTheme(d);
    try { localStorage.setItem('__THEME_KEY__', d ? 'dark' : 'light'); } catch (e) {}
  }
  window.addEventListener('storage', function (e) { if (e.key === '__THEME_KEY__') applyTheme(e.newValue === 'dark'); });
  function load() { try { return JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) { return {}; } }
  function save(s) { try { localStorage.setItem(KEY, JSON.stringify(s)); } catch (e) {} }
  // informational cards (options: []) carry no radios; they stay out of the blob, tally, and Reset
  var cards = Array.prototype.slice.call(document.querySelectorAll('.card')).filter(function (c) {
    return c.querySelector('input[type=radio]');
  });
  var state = load();
  // done = the human actively decided this card (picked a box, typed an edit, or re-affirmed the
  // checked one); the virtual 'decided' facet narrows on it. A dirty edit box (the human typed)
  // keeps its text when a later candidate pick would otherwise re-seed it.
  var doneSet = new Set();
  var dirtyEdits = new Set();
  cards.forEach(function (c) {
    var id = c.dataset.id;
    if (state['p:' + id]) { var r = c.querySelector('input[value="' + state['p:' + id] + '"]'); if (r) r.checked = true; }
    if (state['n:' + id]) { var n = c.querySelector('.notes'); if (n) n.value = state['n:' + id]; }
    if (state['d:' + id] !== undefined) { var e = c.querySelector('.editbox'); if (e) e.value = state['d:' + id]; }
    if (state['k:' + id]) { doneSet.add(id); c.classList.add('done'); }
    if (state['dd:' + id]) dirtyEdits.add(id);
  });
  // prose fields live on any card, informational ones included; deviations restore per field
  var proseBoxes = Array.prototype.slice.call(document.querySelectorAll('.prose'));
  proseBoxes.forEach(function (t) {
    var key = 'r:' + t.dataset.item + '.' + t.dataset.pid;
    if (state[key] !== undefined) t.value = state[key];
    t.addEventListener('input', function () { persist(); });
  });
  // structured fields (text / multi / scale / menu) restore the same way; uploads restore their
  // saved {name, path, bytes} lists (the files themselves live under the hub's surface state)
  var uploads = {};
  Object.keys(state).forEach(function (k) { if (k.slice(0, 2) === 'u:') uploads[k.slice(2)] = state[k]; });
  document.querySelectorAll('.fld-text,.fld-scale,.fld-menu').forEach(function (el) {
    var key = 'f:' + el.dataset.item + '.' + el.dataset.fid;
    if (state[key] !== undefined) el.value = state[key];
  });
  document.querySelectorAll('.fchkrow').forEach(function (group) {
    var key = 'm:' + group.dataset.item + '.' + group.dataset.fid;
    if (state[key] !== undefined) {
      group.querySelectorAll('.fld-multi').forEach(function (cb) {
        cb.checked = state[key].indexOf(cb.value) !== -1;
      });
    }
  });
  function syncScales() {
    document.querySelectorAll('.fld-scale').forEach(function (r) {
      var out = r.closest('.scalewrap').querySelector('.scaleval');
      if (out) out.textContent = r.value + '/' + r.max;
    });
  }
  syncScales();
  document.querySelectorAll('.fld-text').forEach(function (el) { el.addEventListener('input', persist); });
  document.querySelectorAll('.fld-scale').forEach(function (el) {
    el.addEventListener('input', function () { syncScales(); persist(); });
  });
  document.querySelectorAll('.fld-menu').forEach(function (el) { el.addEventListener('change', persist); });
  document.querySelectorAll('.fld-multi').forEach(function (el) { el.addEventListener('change', persist); });
  // the allow_other write-in: typing in the box is choosing it, same gesture as the edit box
  document.querySelectorAll('.otherbox').forEach(function (box) {
    var key = 'o:' + box.closest('.card').dataset.id;
    if (state[key] !== undefined) box.value = state[key];
    box.addEventListener('input', function () {
      var r = box.closest('.card').querySelector('input[value="' + box.dataset.val + '"]');
      if (r && !r.checked) { r.checked = true; r.dispatchEvent(new Event('change', { bubbles: true })); }
      persist();
    });
  });
  // every card folds on a title-row click; spec sets the initial state (data-fold). A saved
  // 'e:' key (1 = opened, 0 = folded) is a deviation from that default restored on reload.
  document.querySelectorAll('.card.collapsible').forEach(function (c) {
    var saved = state['e:' + c.dataset.id];
    if (saved === 1) c.classList.remove('collapsed');
    else if (saved === 0) c.classList.add('collapsed');
    c.querySelector('.cardhead').addEventListener('click', function () {
      c.classList.toggle('collapsed');
      persist();
    });
  });
  function persist() {
    var s = {};
    cards.forEach(function (c) {
      var id = c.dataset.id;
      var r = c.querySelector('input[type=radio]:checked');
      if (r && r.value !== c.dataset.def) s['p:' + id] = r.value;
      var n = c.querySelector('.notes');
      if (n && n.value.trim()) s['n:' + id] = n.value;
      var e = c.querySelector('.editbox');
      if (e && e.value !== e.defaultValue) s['d:' + id] = e.value;
      if (doneSet.has(id)) s['k:' + id] = 1;
      if (dirtyEdits.has(id)) s['dd:' + id] = 1;
    });
    proseBoxes.forEach(function (t) {
      if (t.value !== t.defaultValue) s['r:' + t.dataset.item + '.' + t.dataset.pid] = t.value;
    });
    document.querySelectorAll('.fld-text,.fld-scale').forEach(function (el) {
      if (el.value !== el.defaultValue) s['f:' + el.dataset.item + '.' + el.dataset.fid] = el.value;
    });
    document.querySelectorAll('.fld-menu').forEach(function (el) {
      if (el.value !== (el.dataset.def || '')) s['f:' + el.dataset.item + '.' + el.dataset.fid] = el.value;
    });
    document.querySelectorAll('.fchkrow').forEach(function (group) {
      var vals = [], defs = [];
      group.querySelectorAll('.fld-multi').forEach(function (cb) {
        if (cb.checked) vals.push(cb.value);
        if (cb.defaultChecked) defs.push(cb.value);
      });
      if (vals.join('\\u0000') !== defs.join('\\u0000')) {
        s['m:' + group.dataset.item + '.' + group.dataset.fid] = vals;
      }
    });
    Object.keys(uploads).forEach(function (k) { if (uploads[k] && uploads[k].length) s['u:' + k] = uploads[k]; });
    document.querySelectorAll('.otherbox').forEach(function (box) {
      if (box.value.trim()) s['o:' + box.closest('.card').dataset.id] = box.value;
    });
    document.querySelectorAll('.card.collapsible').forEach(function (c) {
      var folded = c.classList.contains('collapsed');
      if (folded !== (c.dataset.fold === '1')) s['e:' + c.dataset.id] = folded ? 0 : 1;
    });
    save(s); refresh();
  }
  function besc(text) { return text.replace(/\\\\/g, '\\\\\\\\').replace(/\\n/g, '\\\\n'); }
  // every structured field rides the blob as its own kind-named line under its card
  function fieldLines(c, lines) {
    c.querySelectorAll('.fld-text').forEach(function (el) {
      if (el.value.trim()) lines.push('  field ' + el.dataset.item + '.' + el.dataset.fid + ': ' + besc(el.value));
    });
    c.querySelectorAll('.fchkrow').forEach(function (group) {
      var vals = [];
      group.querySelectorAll('.fld-multi').forEach(function (cb) { if (cb.checked) vals.push(cb.value); });
      if (vals.length) lines.push('  multi ' + group.dataset.item + '.' + group.dataset.fid + ' = ' + vals.join(', '));
    });
    c.querySelectorAll('.fld-scale').forEach(function (el) {
      lines.push('  scale ' + el.dataset.item + '.' + el.dataset.fid + ' = ' + el.value + '/' + el.max);
    });
    c.querySelectorAll('.fld-menu').forEach(function (el) {
      if (el.value) lines.push('  menu ' + el.dataset.item + '.' + el.dataset.fid + ' = ' + el.value);
    });
    c.querySelectorAll('.fld-drop').forEach(function (drop) {
      (uploads[drop.dataset.item + '.' + drop.dataset.fid] || []).forEach(function (u) {
        lines.push('  upload ' + drop.dataset.item + '.' + drop.dataset.fid + ' = ' + u.path);
      });
    });
  }
  function buildBlob() {
    var lines = [HEADER];
    cards.forEach(function (c) {
      var id = c.dataset.id;
      var r = c.querySelector('input[type=radio]:checked');
      lines.push(id + ' = ' + (r ? r.value : '(none)'));
      var n = c.querySelector('.notes');
      if (n && n.value.trim()) lines.push('  note ' + id + ': ' + n.value.trim().replace(/\\n/g, ' '));
      // the edit box's exact text rides only when its choice is the pick; newline-escaped so the
      // line-oriented blob survives a multiline replacement (the consuming parser decodes)
      var e = c.querySelector('.editbox');
      if (e && r && r.value === e.dataset.val && e.value.trim()) {
        lines.push('  edit ' + id + ': ' + besc(e.value));
      }
      // the allow_other write-in rides only when the "other" seat is the pick
      var ob = c.querySelector('.otherbox');
      if (ob && r && r.value === ob.dataset.val && ob.value.trim()) {
        lines.push('  other ' + id + ': ' + besc(ob.value));
      }
      c.querySelectorAll('.prose').forEach(function (t) {
        if (t.value.trim()) {
          lines.push('  prose ' + t.dataset.item + '.' + t.dataset.pid + ': ' + besc(t.value));
        }
      });
      fieldLines(c, lines);
    });
    // an informational card carries no radios, so its prose and fields ride after the decision lines
    document.querySelectorAll('#cardlist .card').forEach(function (c) {
      if (c.querySelector('input[type=radio]')) return;
      c.querySelectorAll('.prose').forEach(function (t) {
        if (t.value.trim()) {
          lines.push('  prose ' + t.dataset.item + '.' + t.dataset.pid + ': ' + besc(t.value));
        }
      });
      fieldLines(c, lines);
    });
    return lines.join('\\n');
  }
  // a required field (data-req) gates Submit until it holds an answer. The gate explains
  // itself in three places at once: the unanswered field lights up (.missing), the count line
  // names how many remain, and the blocked Submit stays CLICKABLE: clicking it scrolls to the
  // first missing field and pulses it, so finding what to fill in never takes a hunt.
  function requiredFields() {
    return Array.prototype.slice.call(document.querySelectorAll(
      '.fld-text[data-req],.fld-menu[data-req],.fchkrow[data-req],.fld-drop[data-req]'));
  }
  function fieldAnswered(el) {
    if (el.classList.contains('fchkrow')) return !!el.querySelector('input:checked');
    if (el.classList.contains('fld-drop')) {
      var key = el.dataset.item + '.' + el.dataset.fid;
      return !!(uploads[key] && uploads[key].length);
    }
    return !!el.value.trim();
  }
  function missingRequired() {
    var missing = [];
    requiredFields().forEach(function (el) {
      var open = !fieldAnswered(el);
      var wrap = el.closest('.ffield');
      if (wrap) wrap.classList.toggle('missing', open);
      if (open) missing.push(el.dataset.item + '.' + el.dataset.fid);
    });
    return missing;
  }
  function refresh() {
    var unpicked = 0, changed = 0, byValue = {};
    cards.forEach(function (c) {
      var r = c.querySelector('input[type=radio]:checked');
      if (!r) unpicked++;
      else if (r.value !== c.dataset.def) {
        changed++;
        byValue[r.value] = (byValue[r.value] || 0) + 1;
      }
    });
    var missing = missingRequired();
    var t = cards.length + ' item(s)';
    if (changed) t += ' \\u00b7 ' + changed + ' changed from default';
    if (unpicked) t += ' \\u00b7 ' + unpicked + ' unpicked';
    if (missing.length) t += ' \\u00b7 ' + missing.length + ' required missing';
    document.getElementById('count').textContent = t;
    // the Submit label carries what would be sent, so the moment of commitment shows the commitment
    var summary = Object.keys(byValue).map(function (v) { return byValue[v] + ' ' + v; }).join(' \\u00b7 ');
    var sb = document.getElementById('submitbtn');
    sb.textContent = summary ? 'Submit \\u2014 ' + summary : 'Submit to session';
    sb.classList.toggle('blocked', missing.length > 0);
    sb.title = missing.length
      ? ('required first: ' + missing.join(', ') + ' \\u00b7 click to jump there')
      : '';
    var b = document.getElementById('blob'); if (b) b.value = buildBlob();
  }
  // one acknowledgment for every selbar button: swap the label, hold a green confirm tint,
  // then let the tint fade back over the button's color transition
  function confirmFlash(button, label) {
    if (!button.dataset.restore) button.dataset.restore = button.textContent;
    button.textContent = label;
    button.classList.add('confirm');
    clearTimeout(button.flashTimer);
    button.flashTimer = setTimeout(function () {
      button.classList.remove('confirm');
      button.textContent = button.dataset.restore;
      delete button.dataset.restore;
      refresh();
    }, 1500);
  }
  function copy() {
    var blob = buildBlob();
    var done = function () { confirmFlash(document.getElementById('copybtn'), 'Copied \\u2713'); };
    // the execCommand fallback needs a visible, selected textarea, so only that path opens the blob drawer
    var fallback = function () {
      var bw = document.querySelector('.blobwrap'); if (bw && !bw.open) bw.open = true;
      var ta = document.getElementById('blob'); ta.value = blob; ta.select();
      try { document.execCommand('copy'); done(); } catch (e) {}
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(blob).then(done, fallback);
    } else { fallback(); }
  }
  function submitSel() {
    var sb = document.getElementById('submitbtn');
    var missing = missingRequired();
    if (missing.length) {
      // the blocked submit is a guide, not a wall: take the human to the first missing field
      var wrap = document.querySelector('.ffield.missing');
      if (wrap) {
        var card = wrap.closest('.card');
        if (card) card.classList.remove('collapsed');
        wrap.scrollIntoView({ block: 'center', behavior: 'smooth' });
        wrap.classList.remove('pulse');
        void wrap.offsetWidth;
        wrap.classList.add('pulse');
        var target = wrap.querySelector('.fld-text,.fld-menu');
        if (target) target.focus({ preventScroll: true });
      }
      var st = document.getElementById('substate');
      if (st) st.textContent = missing.length + ' required field(s) to answer first';
      return;
    }
    var fail = function () { var o = sb.textContent; sb.textContent = 'failed: use Copy selection'; setTimeout(function () { sb.textContent = o; }, 2200); };
    fetch('selection', { method: 'POST', body: buildBlob() })
      .then(function (r) {
        if (!r.ok) { fail(); return; }
        confirmFlash(sb, 'Submitted \\u2713 (return to the session)');
        var st = document.getElementById('substate');
        if (st) st.textContent = 'submitted ' + new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + ' \\u2713';
      })
      .catch(fail);
  }
  setTheme(dark);
  document.getElementById('themebtn').addEventListener('click', function () { setTheme(root.dataset.theme !== 'dark'); });
  var EXPAND_ON = window.SPEC.expand_on || [];
  document.querySelectorAll('.card input[type=radio]').forEach(function (r) {
    r.addEventListener('change', function () {
      // a pick whose substance lives in a text box (edit, discuss) opens the card and puts the cursor
      // there: the edit box when this pick owns one, the notes box otherwise
      if (EXPAND_ON.indexOf(r.value) !== -1) {
        var c = r.closest('.card');
        c.classList.remove('collapsed');
        var e = c.querySelector('.editbox');
        var target = (e && e.dataset.val === r.value) ? e : c.querySelector('.notes');
        if (target) target.focus();
      }
      var card = r.closest('.card');
      var box = card.querySelector('.editbox');
      // picking the edit choice opens the work rather than finishing it: the card turns done when
      // the human leaves the box having typed (focusout below), not on the pick itself
      if (!(box && r.value === box.dataset.val)) {
        doneSet.add(card.dataset.id);
        card.classList.add('done');
      }
      // a candidate pick re-seeds a pristine edit box with that candidate's text; once the human
      // has typed in the box their text is never replaced
      if (box && r.value !== box.dataset.val && !dirtyEdits.has(card.dataset.id)) {
        var col = r.closest('.ccol');
        var pre = col && col.querySelector(':scope > pre');
        if (pre && !pre.classList.contains('cnone')) box.value = pre.textContent;
      }
      persist();
      if (fchips.length || fselects.length) applyFacets(); // the virtual 'picked' facet follows the live radios
    });
  });
  document.querySelectorAll('.notes').forEach(function (t) { t.addEventListener('input', persist); });
  // columns strategy: the whole candidate box picks its radio (expanders and the radio itself excepted)
  document.querySelectorAll('.ccol').forEach(function (col) {
    col.addEventListener('click', function (event) {
      if (event.target.closest('details') || event.target.tagName === 'INPUT') return;
      var r = col.querySelector('input[type=radio]');
      if (r && !r.checked) { r.checked = true; r.dispatchEvent(new Event('change', { bubbles: true })); }
      else if (r) {
        // re-affirming the already-checked box is the agree act: it marks the card decided
        var card = col.closest('.card');
        doneSet.add(card.dataset.id);
        card.classList.add('done');
        persist();
        if (fchips.length || fselects.length) applyFacets();
      }
    });
  });
  // the edit container behaves like a candidate box: a click anywhere in it selects the edit
  // choice and puts the cursor in the textarea. Re-affirming it (a second click once edit is
  // picked and text has been typed) finishes the edit decision, same gesture as a candidate.
  // blur cannot finish it, because clicking back to a suggestion mid-think would fire blur and
  // yank the card out of an active pending filter.
  document.querySelectorAll('.cedit').forEach(function (box) {
    box.addEventListener('click', function (event) {
      if (event.target.tagName === 'INPUT' || event.target.tagName === 'TEXTAREA') return;
      var r = box.querySelector('input[type=radio]');
      if (r && !r.checked) { r.checked = true; r.dispatchEvent(new Event('change', { bubbles: true })); }
      else if (r) {
        var card = box.closest('.card');
        if (dirtyEdits.has(card.dataset.id)) {
          doneSet.add(card.dataset.id);
          card.classList.add('done');
          persist();
          if (fchips.length || fselects.length) applyFacets();
        }
      }
      var t = box.querySelector('.editbox'); if (t) t.focus();
    });
  });
  // typing in the edit box is choosing it: check its radio so the text can ride in the blob
  document.querySelectorAll('.editbox').forEach(function (e) {
    e.addEventListener('input', function () {
      dirtyEdits.add(e.closest('.card').dataset.id);
      var r = e.closest('.card').querySelector('input[value="' + e.dataset.val + '"]');
      if (r && !r.checked) { r.checked = true; r.dispatchEvent(new Event('change', { bubbles: true })); }
      persist();
    });
  });
  document.getElementById('copybtn').addEventListener('click', copy);
  var acceptAll = document.getElementById('acceptall');
  if (acceptAll) acceptAll.addEventListener('click', function () {
    var n = 0;
    document.querySelectorAll('.card[data-suggested]').forEach(function (c) {
      if (c.classList.contains('fhidden')) return;            // respect the active facet filter
      var v = c.dataset.suggested;
      c.querySelectorAll('input[type=radio]').forEach(function (r) {
        if (r.value === v && !r.checked) { r.checked = true; r.dispatchEvent(new Event('change', { bubbles: true })); n++; }
      });
    });
    confirmFlash(acceptAll, n ? ('accepted ' + n) : 'all set');
  });

  // keyboard nav for fast triage: j/k (or arrows) move a focus ring; 'a' accepts the focused suggestion
  var kbi = -1;
  function kbCards() {
    return Array.prototype.slice.call(document.querySelectorAll('.card')).filter(function (c) {
      return !c.classList.contains('fhidden');
    });
  }
  function kbFocus(i) {
    var cards = kbCards();
    if (!cards.length) return;
    document.querySelectorAll('.card.kbfocus').forEach(function (c) { c.classList.remove('kbfocus'); });
    kbi = (i + cards.length) % cards.length;
    var c = cards[kbi];
    c.classList.add('kbfocus');
    c.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }
  document.addEventListener('keydown', function (e) {
    // cmd/ctrl+Enter submits from anywhere, textareas included: commit without a mouse trip
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      if (!document.getElementById('submitbtn').hidden) { e.preventDefault(); submitSel(); }
      return;
    }
    var lbOpen = document.getElementById('lightbox');
    if (lbOpen && !lbOpen.hidden) return;   // the lightbox owns the keys while it is up
    var tag = e.target.tagName;
    if (tag === 'TEXTAREA' || tag === 'INPUT' || tag === 'SELECT') return;   // don't hijack typing
    if (e.key === 'j' || e.key === 'ArrowDown') { e.preventDefault(); kbFocus(kbi + 1); }
    else if (e.key === 'k' || e.key === 'ArrowUp') { e.preventDefault(); kbFocus(kbi - 1); }
    else if (e.key === 'a') {
      var cards = kbCards();
      if (kbi < 0 || kbi >= cards.length) return;
      var card = cards[kbi], v = card.dataset.suggested;
      if (!v) return;
      card.querySelectorAll('input[type=radio]').forEach(function (r) {
        if (r.value === v && !r.checked) { r.checked = true; r.dispatchEvent(new Event('change', { bubbles: true })); }
      });
    }
  });
  // Submit is the primary action when the page is served; on a file:// page it stays
  // hidden and Copy inherits the primary styling as the only hand-back path.
  var sb = document.getElementById('submitbtn');
  if (location.protocol === 'http:' || location.protocol === 'https:') {
    sb.hidden = false;
    sb.addEventListener('click', submitSel);
  } else {
    document.getElementById('copybtn').classList.add('primary');
  }
  // page-top sections record their rendered open/closed state before any user toggles, so Reset can restore it
  var sections = document.querySelectorAll('details.section');
  sections.forEach(function (d) { d.dataset.open0 = d.open ? '1' : ''; });
  document.getElementById('resetbtn').addEventListener('click', function () {
    cards.forEach(function (c) {
      c.querySelectorAll('input[type=radio]').forEach(function (r) { r.checked = (r.value === c.dataset.def); });
      var n = c.querySelector('.notes'); if (n) n.value = '';
      var e = c.querySelector('.editbox'); if (e) e.value = e.defaultValue;
      c.classList.remove('done');
    });
    proseBoxes.forEach(function (t) { t.value = t.defaultValue; });
    document.querySelectorAll('.fld-text,.fld-scale').forEach(function (el) { el.value = el.defaultValue; });
    document.querySelectorAll('.fld-menu').forEach(function (el) { el.value = el.dataset.def || ''; });
    document.querySelectorAll('.fld-multi').forEach(function (cb) { cb.checked = cb.defaultChecked; });
    document.querySelectorAll('.otherbox').forEach(function (box) { box.value = ''; });
    uploads = {};
    document.querySelectorAll('.fld-drop').forEach(function (drop) { if (drop._render) drop._render(); });
    syncScales();
    doneSet.clear();
    dirtyEdits.clear();
    // fold state returns to spec defaults too, cards and sections both: Reset means "as first rendered"
    document.querySelectorAll('.card.collapsible').forEach(function (c) {
      c.classList.toggle('collapsed', c.dataset.fold === '1');
    });
    sections.forEach(function (d) { d.open = d.dataset.open0 === '1'; });
    persist();
    if (fchips.length || fselects.length) applyFacets();
    confirmFlash(document.getElementById('resetbtn'), 'Defaults restored \\u2713');
  });
  // facet bar: chips toggle. OR within a group, AND across groups, empty group = no narrowing.
  // Hidden cards stay in the DOM, so the blob and tally cover them. Selections persist per page key.
  var fchips = document.querySelectorAll('.facetbar .fchip');
  var fselects = document.querySelectorAll('.facetbar .fselect');
  var FACETKEY = KEY + ':facets';
  var fsel = {};
  try { fsel = JSON.parse(localStorage.getItem(FACETKEY) || '{}'); } catch (e) { fsel = {}; }
  var allCards = Array.prototype.slice.call(document.querySelectorAll('#cardlist .card'));
  var facetsOf = new Map();
  allCards.forEach(function (c) {
    var f = {};
    try { f = JSON.parse(c.dataset.facets || '{}'); } catch (e) {}
    facetsOf.set(c, f);
  });
  var FKEYS = [];
  fchips.forEach(function (b) { if (FKEYS.indexOf(b.dataset.key) === -1) FKEYS.push(b.dataset.key); });
  fselects.forEach(function (s) { if (FKEYS.indexOf(s.dataset.key) === -1) FKEYS.push(s.dataset.key); });
  // 'picked' is the virtual facet: its value is the card's live radio state, not spec data
  function facetValue(c, key) {
    if (key === 'picked') {
      var r = c.querySelector('input[type=radio]:checked');
      return r ? r.value : undefined;
    }
    if (key === 'decided') {
      if (!c.querySelector('input[type=radio]')) return undefined;
      return doneSet.has(c.dataset.id) ? 'done' : 'pending';
    }
    return facetsOf.get(c)[key];
  }
  function matches(c, skipKey) {
    for (var k = 0; k < FKEYS.length; k++) {
      if (FKEYS[k] === skipKey) continue;
      var sel = fsel[FKEYS[k]] || [];
      if (sel.length && sel.indexOf(facetValue(c, FKEYS[k])) === -1) return false;
    }
    return true;
  }
  function applyFacets() {
    var any = false;
    fchips.forEach(function (b) {
      var sel = fsel[b.dataset.key] || [];
      var on = sel.indexOf(b.dataset.value) !== -1;
      b.classList.toggle('active', on);
      if (on) any = true;
    });
    var visible = 0;
    allCards.forEach(function (c) {
      var hide = !matches(c, null);
      c.classList.toggle('fhidden', hide);
      if (!hide) visible++;
    });
    // a chip's count ignores its own group's selection (standard faceted search), so
    // within-group numbers stay stable while you multi-select. A non-active chip whose
    // count is zero dims and stops responding, so a dead-end combination shows before the click.
    fchips.forEach(function (b) {
      var n = 0;
      allCards.forEach(function (c) {
        if (facetValue(c, b.dataset.key) === b.dataset.value && matches(c, b.dataset.key)) n++;
      });
      var fc = b.querySelector('.fcount'); if (fc) fc.textContent = n;
      b.classList.toggle('dead', n === 0 && !b.classList.contains('active'));
    });
    // a select group narrows to one value (or all); its option labels carry the same live counts
    fselects.forEach(function (s) {
      var key = s.dataset.key;
      var sel = fsel[key] || [];
      s.value = sel.length ? sel[0] : '';
      if (sel.length) any = true;
      Array.prototype.forEach.call(s.options, function (o) {
        var n = 0;
        allCards.forEach(function (c) {
          if ((o.value === '' || facetValue(c, key) === o.value) && matches(c, key)) n++;
        });
        o.textContent = o.dataset.base + ' (' + n + ')';
        o.disabled = n === 0 && o.value !== s.value && o.value !== '';
      });
    });
    var clear = document.getElementById('facetclear'); if (clear) clear.hidden = !any;
    var nomatch = document.getElementById('nomatch'); if (nomatch) nomatch.hidden = visible !== 0;
  }
  fchips.forEach(function (b) {
    b.addEventListener('click', function () {
      var sel = fsel[b.dataset.key] || (fsel[b.dataset.key] = []);
      var at = sel.indexOf(b.dataset.value);
      if (at === -1) sel.push(b.dataset.value); else sel.splice(at, 1);
      applyFacets();
      try { localStorage.setItem(FACETKEY, JSON.stringify(fsel)); } catch (e) {}
    });
  });
  fselects.forEach(function (s) {
    s.addEventListener('change', function () {
      fsel[s.dataset.key] = s.value ? [s.value] : [];
      applyFacets();
      try { localStorage.setItem(FACETKEY, JSON.stringify(fsel)); } catch (e) {}
    });
  });
  function clearFacets() {
    fsel = {};
    applyFacets();
    try { localStorage.setItem(FACETKEY, '{}'); } catch (e) {}
  }
  ['facetclear', 'nomatchclear'].forEach(function (id) {
    var b = document.getElementById(id);
    if (b) b.addEventListener('click', clearFacets);
  });
  if (fchips.length || fselects.length) applyFacets();
  // a deep link from a context section can land on a folded card, so unfold it, flash it, and let
  // the flash fade out. The hash is a transient navigation aid, not state: it clears as soon as
  // it is handled, so a reload replays nothing and a re-click of the same link is a fresh jump.
  function revealHash() {
    if (!location.hash) return;
    var target = document.getElementById(location.hash.slice(1));
    try { history.replaceState(null, '', location.pathname + location.search); } catch (e) {}
    if (!target || !target.classList.contains('card')) return;
    target.classList.remove('collapsed');
    target.classList.remove('flash');
    void target.offsetWidth;
    target.classList.add('flash');
    target.addEventListener('animationend', function () { target.classList.remove('flash'); }, { once: true });
  }
  window.addEventListener('hashchange', revealHash);
  revealHash();
  // media: the gallery lightbox (a click opens; arrows move between the page's images; Esc or
  // a click anywhere closes). The overlay is rendered by the page, one per document.
  var lb = document.getElementById('lightbox');
  if (lb) {
    var lbImg = lb.querySelector('img');
    var lbCap = lb.querySelector('.cap');
    var lbLinks = Array.prototype.slice.call(document.querySelectorAll('a.lbimg'));
    var lbAt = -1;
    var lbShow = function (i) {
      lbAt = (i + lbLinks.length) % lbLinks.length;
      lbImg.src = lbLinks[lbAt].getAttribute('href');
      lbCap.textContent = lbLinks[lbAt].dataset.cap || '';
      lb.hidden = false;
    };
    lbLinks.forEach(function (a, i) {
      a.addEventListener('click', function (e) { e.preventDefault(); lbShow(i); });
    });
    lb.addEventListener('click', function () { lb.hidden = true; });
    document.addEventListener('keydown', function (e) {
      if (lb.hidden) return;
      if (e.key === 'Escape') lb.hidden = true;
      else if (e.key === 'ArrowRight') { e.preventDefault(); lbShow(lbAt + 1); }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); lbShow(lbAt - 1); }
    });
  }
  // media: the before/after compare frame (the slider blends the top image over the bottom one)
  document.querySelectorAll('.cmprange').forEach(function (range) {
    var top = range.closest('.chu-compare').querySelector('img.top');
    var applyBlend = function () { top.style.opacity = range.value / 100; };
    range.addEventListener('input', applyBlend);
    applyBlend();
  });
  // the upload lane: files the HUMAN hands the session. Served through the hub, the page POSTs
  // raw bytes to its own scoped upload route and rides the returned absolute path in the blob;
  // from file:// there is no hub behind the page, so the zone says so and stays inert.
  function fmtSize(n) {
    if (!(n > 0)) return '';
    var units = ['B', 'KB', 'MB', 'GB'], i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return (i ? n.toFixed(1) : n) + ' ' + units[i];
  }
  var SERVED = (location.protocol === 'http:' || location.protocol === 'https:');
  document.querySelectorAll('.fld-drop').forEach(function (drop) {
    var key = drop.dataset.item + '.' + drop.dataset.fid;
    var list = drop.querySelector('.uplist');
    var msg = drop.querySelector('.upmsg');
    var input = drop.querySelector('input[type=file]');
    function renderList() {
      list.innerHTML = '';
      (uploads[key] || []).forEach(function (u, i) {
        var li = document.createElement('li');
        var name = document.createElement('span');
        name.textContent = u.name + (u.bytes ? ' (' + fmtSize(u.bytes) + ')' : '');
        var rm = document.createElement('button');
        rm.type = 'button';
        rm.classList.add('rm');
        rm.textContent = 'remove';
        rm.addEventListener('click', function () { uploads[key].splice(i, 1); renderList(); persist(); });
        li.appendChild(name); li.appendChild(rm); list.appendChild(li);
      });
    }
    drop._render = renderList;
    renderList();
    if (!SERVED) {
      drop.classList.add('off');
      msg.hidden = false;
      msg.textContent = 'attaching files needs this page served through the hub; hand the path over in chat instead.';
      return;
    }
    function send(files) {
      var chosen = Array.prototype.slice.call(files);
      if (!drop.dataset.multiple) chosen = chosen.slice(0, 1);
      chosen.forEach(function (f) {
        msg.hidden = false; msg.classList.remove('bad'); msg.textContent = 'uploading ' + f.name + '\\u2026';
        fetch('upload?name=' + encodeURIComponent(f.name), { method: 'POST', body: f })
          .then(function (r) { return r.json(); })
          .then(function (j) {
            if (!j.ok) { msg.classList.add('bad'); msg.textContent = 'upload failed: ' + (j.error || 'refused'); return; }
            if (!drop.dataset.multiple) uploads[key] = [];
            (uploads[key] = uploads[key] || []).push({ name: j.name, path: j.path, bytes: j.bytes });
            msg.hidden = true;
            renderList(); persist();
          })
          .catch(function () { msg.classList.add('bad'); msg.textContent = 'upload failed: network error'; });
      });
    }
    drop.querySelector('.browse').addEventListener('click', function () { input.click(); });
    input.addEventListener('change', function () { if (input.files.length) send(input.files); input.value = ''; });
    ['dragover', 'dragenter'].forEach(function (evt) {
      drop.addEventListener(evt, function (e) { e.preventDefault(); drop.classList.add('armed'); });
    });
    ['dragleave', 'drop'].forEach(function (evt) {
      drop.addEventListener(evt, function (e) { e.preventDefault(); drop.classList.remove('armed'); });
    });
    drop.addEventListener('drop', function (e) {
      if (e.dataTransfer && e.dataTransfer.files.length) send(e.dataTransfer.files);
    });
  });
  refresh();
})();
</script>
"""


def anchor_id(item_id):
    """One stable element id per card (card-heartbeat-3). '#' and friends would break a URL
    fragment, so every non-alphanumeric becomes a dash. Section HTML deep-links against this."""
    return "card-" + re.sub(r"[^A-Za-z0-9_-]", "-", item_id)


def item_options(item, page_options):
    """The card's choice set: candidates[].value + edit.value under a pick_ui strategy, the
    options field (page-wide set as fallback) otherwise. [] means an informational card."""
    pick_ui = item.get("pick_ui") or {}
    if pick_ui.get("style") == "columns":
        values = [candidate["value"] for candidate in pick_ui.get("candidates", [])]
        if pick_ui.get("edit"):
            values.append(pick_ui["edit"].get("value", "edit"))
        return values
    return item.get("options", page_options)


def pick_area_html(item, options, default, option_help, suggested=None):
    """The card's interactive choice block, the strategy seam.

    Default strategy: one radio-label row. "columns" (item.pick_ui): one bordered box per candidate
    laid out side by side (radio + label heading, comparison chips, the candidate text in its own
    mono block, an optional expander), plus a full-width edit box seeded with pick_ui.edit.seed.
    An optional pick_ui.context renders first as a full-width non-selectable box (label + mono
    text): the baseline the candidates are read against.
    Every strategy emits radios named pick:<id>; the page JS is strategy-agnostic. A new strategy
    is a new branch here plus its CSS.
    """
    item_id = str(item["id"])
    pick_ui = item.get("pick_ui") or {}
    if pick_ui.get("style") == "columns":
        name = f'name="pick:{html.escape(item_id)}"'
        columns = []
        for candidate in pick_ui.get("candidates", []):
            checked = " checked" if candidate["value"] == default else ""
            chips = ""
            if candidate.get("chips"):
                chips = ('<div class="cchips">'
                         + "".join(f'<span class="cchip">{html.escape(chip)}</span>' for chip in candidate["chips"])
                         + "</div>")
            text = candidate.get("text") or ""
            body = f"<pre>{html.escape(text)}</pre>" if text.strip() else '<pre class="cnone">(empty)</pre>'
            more = ""
            if candidate.get("more"):
                more = (f'<details><summary>{html.escape(candidate["more"].get("label", "more"))}</summary>'
                        f'<pre>{html.escape(candidate["more"].get("text", ""))}</pre></details>')
            columns.append(
                f'<div class="ccol"><label><input type="radio" {name} value="{html.escape(candidate["value"])}"'
                f'{checked}> {html.escape(candidate.get("label", candidate["value"]))}</label>'
                f"{chips}{body}{more}</div>"
            )
        edit_html = ""
        edit = pick_ui.get("edit")
        if edit:
            value = edit.get("value", "edit")
            checked = " checked" if value == default else ""
            edit_html = (
                f'<div class="cedit"><label><input type="radio" {name} value="{html.escape(value)}"{checked}> '
                f'{html.escape(edit.get("label", value))}</label>'
                f'<textarea class="editbox" data-val="{html.escape(value)}" spellcheck="false">'
                f'{html.escape(edit.get("seed", ""))}</textarea></div>'
            )
        context_html = ""
        context = pick_ui.get("context")
        if context:
            text = context.get("text") or ""
            body = f"<pre>{html.escape(text)}</pre>" if text.strip() else '<pre class="cnone">(none)</pre>'
            context_html = (f'<div class="ccontext"><span class="cclabel">'
                            f'{html.escape(context.get("label", "context"))}</span>{body}</div>')
        return f'<div class="candwrap">{context_html}<div class="candrow">{"".join(columns)}</div>{edit_html}</div>'
    if not options:
        return ""
    radio_labels = []
    for option in options:
        help_attr = f' title="{html.escape(option_help[option])}"' if option in option_help else ""
        checked = " checked" if option == default else ""
        is_sugg = suggested is not None and option == suggested
        cls = ' class="issugg"' if is_sugg else ""
        mark = '<span class="sugg" title="agent suggestion">★</span>' if is_sugg else ""
        radio_labels.append(
            f'<label{cls}{help_attr}><input type="radio" name="pick:{html.escape(item_id)}" '
            f'value="{html.escape(option)}"{checked}> {html.escape(option)}{mark}</label>'
        )
    if item.get("allow_other"):
        # the write-in seat: a radio plus a text box; typing in the box selects the radio and
        # the text rides back as its own `other <id>:` blob line
        help_attr = (f' title="{html.escape(option_help["other"])}"'
                     if "other" in option_help else "")
        checked = " checked" if default == "other" else ""
        radio_labels.append(
            f'<span class="otherwrap"><label{help_attr}>'
            f'<input type="radio" name="pick:{html.escape(item_id)}" value="other"{checked}> '
            f'other:</label><input type="text" class="otherbox" data-val="other"'
            f' aria-label="the write-in answer" spellcheck="true"></span>'
        )
    return f'<div class="opts">{"".join(radio_labels)}</div>'


def _human_size(nbytes):
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024 or unit == "GB":
            return f"{nbytes:.0f} {unit}" if unit == "B" else f"{nbytes / 1.0:.1f} {unit}"
        nbytes /= 1024.0
    return f"{nbytes:.1f} GB"


def _dl_link(src):
    return f'<a href="{html.escape(src)}" download>download</a>'


def _caption_line(entry, size):
    parts = []
    if entry.get("caption"):
        parts.append(html.escape(entry["caption"]))
    if size:
        parts.append(html.escape(size))
    parts.append(_dl_link(entry["src"]))
    return '<div class="chu-figcap">' + " &middot; ".join(parts) + "</div>"


def media_html(item):
    """The card's artifact area: galleries (consecutive images share a row), a before/after
    compare frame, audio/video players, and file download cards. Every entry's src has been
    staged into <outdir>/assets/ (stage_assets) before this runs, so src is page-relative and
    `_size` carries the staged byte count. Everything shown is also downloadable."""
    entries = item.get("media") or []
    if not entries:
        return ""
    blocks, gallery = [], []

    def flush_gallery():
        if gallery:
            blocks.append('<div class="chu-gallery">' + "".join(gallery) + "</div>")
            del gallery[:]

    for entry in entries:
        kind = entry["kind"]
        size = entry.get("_size", "")
        if kind == "image":
            src = html.escape(entry["src"])
            caption = entry.get("caption") or ""
            alt = entry.get("alt") or caption or "image"
            gallery.append(
                f'<figure class="chu-fig"><a href="{src}" class="lbimg"'
                f' data-cap="{html.escape(caption, quote=True)}">'
                f'<img src="{src}" alt="{html.escape(alt)}" loading="lazy"></a>'
                f'<figcaption class="chu-figcap">'
                + (html.escape(caption) + " &middot; " if caption else "")
                + (html.escape(size) + " &middot; " if size else "")
                + _dl_link(entry["src"]) + "</figcaption></figure>")
            continue
        flush_gallery()
        if kind == "compare":
            before, after = entry["before"], entry["after"]
            caption = (f'<div class="chu-figcap">{html.escape(entry["caption"])}</div>'
                       if entry.get("caption") else "")
            blocks.append(
                f'<div class="chu-compare"><div class="frame">'
                f'<img src="{html.escape(before["src"])}" alt="{html.escape(before.get("label", "before"))}">'
                f'<img class="top" src="{html.escape(after["src"])}"'
                f' alt="{html.escape(after.get("label", "after"))}" style="opacity:.5"></div>'
                f'<div class="chu-comparebar"><span>{html.escape(before.get("label", "before"))}</span>'
                f'<input type="range" class="cmprange" min="0" max="100" value="50"'
                f' aria-label="blend between the two images">'
                f'<span>{html.escape(after.get("label", "after"))}</span></div>{caption}</div>')
        elif kind in ("audio", "video"):
            tag = ("audio" if kind == "audio" else "video")
            blocks.append(
                f'<div class="chu-player"><{tag} controls preload="metadata"'
                f' src="{html.escape(entry["src"])}"></{tag}>'
                + _caption_line(entry, size) + "</div>")
        elif kind == "file":
            name = os.path.basename(entry["src"])
            ext = (os.path.splitext(name)[1].lstrip(".") or "file").upper()
            note = (f'<p class="chu-filenote">{html.escape(entry["note"])}</p>'
                    if entry.get("note") else "")
            blocks.append(
                f'<div class="chu-filecard"><span class="chu-fileext">{html.escape(ext)}</span>'
                f'<span class="chu-filename">{html.escape(name)}</span>'
                f'<span class="chu-filesize">{html.escape(size)}</span>'
                f'<a class="chu-dl" href="{html.escape(entry["src"])}" download>download</a>'
                f"{note}</div>")
    flush_gallery()
    return '<div class="mediablock">' + "".join(blocks) + "</div>"


def fields_html(item):
    """The card's structured short-form asks: text (seedable), multi checkboxes, a labeled
    scale, a menu for long option lists, and the upload drop zone (the human->session file
    lane; needs the page served through the hub). Each field rides the blob as its own
    kind-named line; `required: true` gates Submit until the field is answered."""
    item_id = str(item["id"])
    out = []
    for index, field in enumerate(item.get("fields") or [], 1):
        fid = str(field.get("id") or index)
        kind = field.get("kind", "text")
        box_id = f"{anchor_id(item_id)}-fld-{re.sub(r'[^A-Za-z0-9_-]', '-', fid)}"
        required = (' <span class="freq" title="required before submit">*</span>'
                    if field.get("required") else "")
        data = (f' data-item="{html.escape(item_id)}" data-fid="{html.escape(fid)}"'
                + (' data-req="1"' if field.get("required") else ""))
        label_text = html.escape(field.get("label", ""))
        # a <label for> must point at a labelable element; group controls get a span head
        label_for = (f'<div class="flhead"><label class="proselabel" for="{box_id}">'
                     f"{label_text}</label>{required}</div>")
        label_span = (f'<div class="flhead"><span class="proselabel">{label_text}</span>'
                      f"{required}</div>")
        help_html = (f'<p class="fhelp">{html.escape(field["help"])}</p>'
                     if field.get("help") else "")
        if kind == "text":
            placeholder = (f' placeholder="{html.escape(field["placeholder"], quote=True)}"'
                           if field.get("placeholder") else "")
            control = (f'<input type="text" class="fld-text" id="{box_id}"{data}'
                       f' value="{html.escape(field.get("seed", ""), quote=True)}"{placeholder}'
                       f' spellcheck="true">')
            head = label_for
        elif kind == "multi":
            defaults = set(field.get("default") or [])
            help_map = field.get("option_help", {})
            boxes = []
            for option in field.get("options") or []:
                option = str(option)
                title = (f' title="{html.escape(help_map[option], quote=True)}"'
                         if option in help_map else "")
                checked = " checked" if option in defaults else ""
                boxes.append(f'<label class="fchk"{title}><input type="checkbox" class="fld-multi"'
                             f' value="{html.escape(option)}"{checked}> {html.escape(option)}</label>')
            control = f'<div class="fchkrow" id="{box_id}"{data}>{"".join(boxes)}</div>'
            head = label_span
        elif kind == "scale":
            low, high = int(field.get("min", 1)), int(field.get("max", 5))
            value = int(field.get("default", low))
            control = (
                f'<div class="scalewrap"><span class="scale-end">{html.escape(str(field.get("low", "")))}</span>'
                f'<input type="range" class="fld-scale" id="{box_id}"{data} min="{low}" max="{high}"'
                f' step="1" value="{value}">'
                f'<span class="scaleval">{value}/{high}</span>'
                f'<span class="scale-end">{html.escape(str(field.get("high", "")))}</span></div>')
            head = label_for
        elif kind == "menu":
            default = str(field.get("default", ""))
            help_map = field.get("option_help", {})
            options = ['<option value="">(unanswered)</option>']
            for option in field.get("options") or []:
                option = str(option)
                title = (f' title="{html.escape(help_map[option], quote=True)}"'
                         if option in help_map else "")
                selected = " selected" if option == default else ""
                options.append(f'<option value="{html.escape(option)}"{title}{selected}>'
                               f"{html.escape(option)}</option>")
            control = (f'<select class="fld-menu" id="{box_id}"{data}'
                       f' data-def="{html.escape(default, quote=True)}">{"".join(options)}</select>')
            head = label_for
        else:  # upload
            accept = (f' accept="{html.escape(field["accept"], quote=True)}"'
                      if field.get("accept") else "")
            multiple_attr = " multiple" if field.get("multiple") else ""
            multiple_data = ' data-multiple="1"' if field.get("multiple") else ""
            control = (
                f'<div class="chu-drop fld-drop" id="{box_id}"{data}{multiple_data}>'
                f'<input type="file" hidden{accept}{multiple_attr}>'
                f'<span>drop a file here, or <button type="button" class="browse">browse</button></span>'
                f'<ul class="uplist"></ul><p class="upmsg" hidden></p></div>')
            head = label_span
        out.append(f'<div class="ffield">{head}{help_html}{control}</div>')
    return "".join(out)


def card_html(item, page_options, page_default, option_help):
    item_id = str(item["id"])
    options = item_options(item, page_options)
    # `suggested` = the agent's recommended pick (the triage bulk layer): it pre-checks + marks the
    # option and feeds the "accept all suggested" bulk action; falls back to a neutral default.
    suggested = item.get("suggested") if options else None
    default = suggested or (item.get("default", page_default) if options else None)
    badge = ""
    if item.get("badge"):
        badge_class = BADGE_CLASSES.get(str(item["badge"]).lower(), "")
        badge = f'<span class="badge {badge_class}">{html.escape(str(item["badge"]))}</span>'
    source = f'<span class="srcchip">{html.escape(item["source"])}</span>' if item.get("source") else ""
    # a status chip (baseline/waiver continuity: new / persisting / resolved / waived) and, paired
    # with it, a `muted` card class that greys a carried card so the eye lands on the new findings
    status = f'<span class="statuschip">{html.escape(str(item["status"]))}</span>' if item.get("status") else ""
    meta = f'<div class="cardmeta">{html.escape(item["meta"])}</div>' if item.get("meta") else ""
    summary = f'<p class="summary">{html.escape(item["summary"])}</p>' if item.get("summary") else ""
    where_html = ""
    where_value = item.get("where")
    if isinstance(where_value, dict):
        code = f'<div class="fcode">{html.escape(where_value["code"])}</div>' if where_value.get("code") else ""
        # the code line is a <div>, so its wrapper must be flow content; a <span> here violates
        # the HTML content model and makes validators suppress errors in the whole subtree
        where_html = (f'<div class="field f-where"><span class="flabel">where</span>'
                      f'<div class="ftext">{html.escape(where_value.get("place", ""))}{code}</div></div>')
    elif where_value:
        where_html = (f'<div class="field f-where"><span class="flabel">where</span>'
                      f'<span class="ftext mono">{html.escape(where_value)}</span></div>')
    fields = where_html + "".join(
        f'<div class="field f-{key}"><span class="flabel">{key}</span><span class="ftext">{html.escape(item[key])}</span></div>'
        for key in ("why", "fix")
        if item.get(key)
    )
    evidence = f'<div class="evidence">{html.escape(item["evidence"])}</div>' if item.get("evidence") else ""
    diff_html = ""
    if item.get("diff"):
        diff = item["diff"]
        location = f'<div class="diffloc">{html.escape(diff["location"])}</div>' if diff.get("location") else ""
        old_lines = "".join(
            f'<div class="dline dold">− {html.escape(line)}</div>' for line in diff.get("old", "").split("\n") if diff.get("old")
        )
        new_lines = "".join(
            f'<div class="dline dnew">+ {html.escape(line)}</div>' for line in diff.get("new", "").split("\n") if diff.get("new")
        )
        diff_html = f'<div class="diffblock">{location}{old_lines}{new_lines}</div>'
    detail = ""
    if item.get("detail"):
        detail = (
            f'<details class="detail"><summary>{html.escape(item["detail"].get("label", "more"))}</summary>'
            f'<div class="dtext">{html.escape(item["detail"].get("text", ""))}</div></details>'
        )
    warning = f'<div class="warning">{html.escape(item["warning"])}</div>' if item.get("warning") else ""
    warn_flag = f'<span class="warnflag" title="{html.escape(item["warning"])}">&#9888;</span>' if item.get("warning") else ""
    body = f'<div class="cardbody">{item["body_html"]}</div>' if item.get("body_html") else ""
    opts = pick_area_html(item, options, default, option_help, suggested=suggested)
    note_hint = " (on an apply, this adjusts the wording)" if "apply" in options else ""
    notes = (
        f'<textarea class="notes" placeholder="notes on {html.escape(item_id)}{note_hint}…"></textarea>'
        if item.get("notes", bool(options))
        else ""
    )
    # prose fields: prompted paragraph answers that ride the blob as their own lines, for the
    # cards whose real answer is sentences, not a pick (an informational card may carry only these)
    prose_html = ""
    for index, field in enumerate(item.get("prose") or [], 1):
        pid = str(field.get("id") or index)
        box = f"{anchor_id(item_id)}-prose-{re.sub(r'[^A-Za-z0-9_-]', '-', pid)}"
        placeholder = (f' placeholder="{html.escape(field["placeholder"])}"'
                       if field.get("placeholder") else "")
        prose_html += (
            f'<div class="prosefield"><label class="proselabel" for="{box}">'
            f'{html.escape(field.get("prompt", ""))}</label>'
            f'<textarea class="prose" id="{box}" data-item="{html.escape(item_id)}"'
            f' data-pid="{html.escape(pid)}" rows="{int(field.get("rows", 4))}"{placeholder}'
            f' spellcheck="true">{html.escape(field.get("seed", ""))}</textarea></div>'
        )
    collapsed = bool(item.get("collapsed"))
    card_classes = "card collapsible collapsed" if collapsed else "card collapsible"
    if item.get("muted"):
        card_classes += " muted"
    chevron = '<span class="chev">▸</span>'
    fold_attr = ' data-fold="1"' if collapsed else ""
    facets_attr = ""
    if item.get("facets"):
        facets_attr = f' data-facets="{html.escape(json.dumps(item["facets"]), quote=True)}"'
    sugg_attr = f' data-suggested="{html.escape(suggested)}"' if suggested else ""
    return (
        f'<div class="{card_classes}" id="{anchor_id(item_id)}" data-id="{html.escape(item_id)}"'
        f' data-def="{html.escape(default or "")}"{sugg_attr}{fold_attr}{facets_attr}>'
        f'<div class="cardhead">{chevron}<span class="cardid">{html.escape(item_id)}</span>{badge}{warn_flag}{source}{status}'
        f'<span class="cardtitle">{html.escape(item.get("title", ""))}</span></div>'
        f"{summary}"
        f'<div class="cardfold">{meta}{fields}{evidence}{detail}{warning}{body}{media_html(item)}</div>'
        f"{diff_html}{opts}{prose_html}{fields_html(item)}{notes}</div>"
    )


def legend_html(option_help):
    if not option_help:
        return ""
    parts = " &nbsp;·&nbsp; ".join(
        f"<b>{html.escape(option)}</b>: {html.escape(meaning)}" for option, meaning in option_help.items()
    )
    return f'<div class="legend">{parts}</div>'


def stage_assets(spec, spec_dir, output_dir):
    """Copy every media src into <output_dir>/assets/ and rewrite each entry's src to the
    page-relative path (adding `_size`, the human-readable byte count the templates show), so
    the rendered directory is self-contained: the page works from file:// and the hub serves
    the same files Range-capably under the surface's a/ path. Idempotent across re-renders;
    two different sources sharing a basename get numbered. Returns problem sentences (missing
    files) rather than raising, so main prints MEDIA lines and exits 2 the way the floor does."""
    problems, staged, used = [], {}, set()
    assets_dir = os.path.join(output_dir, "assets")

    def stage(src, where):
        if not src:
            return None
        full = os.path.abspath(src if os.path.isabs(src) else os.path.join(spec_dir, src))
        if not os.path.isfile(full):
            problems.append(f"{where}: {src} does not exist (paths resolve against the "
                            "spec's directory)")
            return None
        if full in staged:
            return staged[full]
        os.makedirs(assets_dir, exist_ok=True)
        name = os.path.basename(full)
        stem, ext = os.path.splitext(name)
        n = 1
        while name in used:
            name = f"{stem}-{n}{ext}"
            n += 1
        used.add(name)
        dest = os.path.join(assets_dir, name)
        if not (os.path.exists(dest) and os.path.samefile(full, dest)):
            shutil.copy2(full, dest)
        staged[full] = ("assets/" + name, os.path.getsize(full))
        return staged[full]

    for item in spec.get("items", []):
        for index, entry in enumerate(item.get("media") or [], 1):
            where = f"item {item.get('id', '?')}: media {index}"
            if entry.get("kind") == "compare":
                for side in ("before", "after"):
                    part = entry.get(side) or {}
                    result = stage(part.get("src", ""), where)
                    if result:
                        part["src"] = result[0]
            else:
                result = stage(entry.get("src", ""), where)
                if result:
                    entry["src"] = result[0]
                    entry["_size"] = _human_size(result[1])
    return problems


def main():
    spec_path = os.path.abspath(sys.argv[1])
    with open(spec_path) as handle:
        spec = json.load(handle)
    output_dir = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else os.path.dirname(spec_path)

    waiver = spec.get("floor_waived")
    if isinstance(waiver, str) and len(waiver.strip()) >= 20:
        print(f"FLOOR WAIVED: {waiver.strip()}", file=sys.stderr, flush=True)
    else:
        problems = floor_failures(spec)
        if problems:
            for problem in problems:
                print(f"FLOOR {problem}", file=sys.stderr, flush=True)
            print("FLOOR: page not rendered. A decision surface must explain itself to a cold "
                  "reader; fix the spec and re-render (floor_waived, a reason of 20+ characters, "
                  "skips this only when the floor genuinely cannot apply).",
                  file=sys.stderr, flush=True)
            sys.exit(2)

    media_problems = stage_assets(spec, os.path.dirname(spec_path), output_dir)
    if media_problems:
        for problem in media_problems:
            print(f"MEDIA {problem}", file=sys.stderr, flush=True)
        print("MEDIA: page not rendered; every media src must exist on disk at render time.",
              file=sys.stderr, flush=True)
        sys.exit(2)

    page_options = spec.get("options", ["apply", "discuss", "skip"])
    page_default = spec.get("default")

    facet_rows = []
    select_rows = []
    for group in spec.get("facets", []):
        key = group["key"]
        values = list(group.get("values", []))
        for item in spec["items"]:
            value = (item.get("facets") or {}).get(key)
            if value and value not in values:
                values.append(value)
        help_map = group.get("help", {})
        counts = {value: 0 for value in values}
        for item in spec["items"]:
            value = (item.get("facets") or {}).get(key)
            if value in counts:
                counts[value] += 1
        label = html.escape(group.get("label", key))
        if group.get("style") == "select":
            # one compact control regardless of value count, the right shape past ~6 values
            options = [f'<option value="" data-base="all">all ({sum(counts.values())})</option>'] + [
                f'<option value="{html.escape(value)}" data-base="{html.escape(value)}">'
                f'{html.escape(value)} ({counts[value]})</option>'
                for value in values
            ]
            control = f'<select class="fselect" data-key="{html.escape(key)}">{"".join(options)}</select>'
            select_rows.append(f'<div class="fgroup"><span class="fglabel">{label}</span>{control}</div>')
        else:
            chips = "".join(
                f'<button class="fchip" data-key="{html.escape(key)}" data-value="{html.escape(value)}"'
                + (f' title="{html.escape(help_map[value])}"' if value in help_map else "")
                + f'>{html.escape(value)}<span class="fcount">{counts[value]}</span></button>'
                for value in values
            )
            facet_rows.append(f'<div class="fgroup"><span class="fglabel">{label}</span>{chips}</div>')
    decision_items = [item for item in spec["items"] if item_options(item, page_options)]
    # the picked row earns its space only on real batches; a page of a few cards reads
    # faster without a filter bar tracking it (explicit "picked_facet": true forces it)
    if decision_items and spec.get("picked_facet", len(decision_items) >= 5):
        picked_values = list(page_options)
        for item in decision_items:
            extra = ["other"] if item.get("allow_other") else []
            for option in list(item_options(item, page_options)) + extra:
                if option not in picked_values:
                    picked_values.append(option)
        # server-side counts reflect the spec defaults; the page recomputes from the live
        # radios on load and on every change
        picked_counts = {value: 0 for value in picked_values}
        for item in decision_items:
            default = item.get("default", page_default)
            if default in picked_counts:
                picked_counts[default] += 1
        picked_chips = "".join(
            f'<button class="fchip" data-key="picked" data-value="{html.escape(value)}">'
            f'{html.escape(value)}<span class="fcount">{picked_counts[value]}</span></button>'
            for value in picked_values
        )
        facet_rows.append(f'<div class="fgroup"><span class="fglabel">picked</span>{picked_chips}</div>')
    if decision_items and spec.get("decided_facet"):
        # everything starts pending server-side; the page recomputes from the live done flags
        decided_chips = "".join(
            f'<button class="fchip" data-key="decided" data-value="{value}">'
            f'{value}<span class="fcount">{count}</span></button>'
            for value, count in (("pending", len(decision_items)), ("done", 0)))
        facet_rows.append(f'<div class="fgroup"><span class="fglabel">decided</span>{decided_chips}</div>')
    # select rows land after every chip row, so the chips read as one area
    facet_rows += select_rows
    facetbar = ""
    if facet_rows:
        facetbar = ('<div class="facetbar">' + "".join(facet_rows)
                    + '<button class="facetclear" id="facetclear" hidden>clear filters ×</button></div>\n')

    option_help = spec.get("option_help", {})
    card_list = "\n".join(card_html(item, page_options, page_default, option_help) for item in spec["items"])
    nomatch = ""
    if facetbar:
        nomatch = ('<div class="nomatch" id="nomatch" hidden>Nothing matches the current filters. '
                   '<button id="nomatchclear">clear filters</button></div>')
    cards = f'{facetbar}<div id="cardlist">\n{card_list}\n</div>{nomatch}'

    readout = ""
    if spec.get("subtitle"):
        # the readout strip: the page's vitals as one mono line (middot-separated in the spec)
        parts = [html.escape(part.strip()) for part in str(spec["subtitle"]).split("·") if part.strip()]
        readout = '<div class="readout">' + "".join(f"<span>{part}</span>" for part in parts) + "</div>"
    intro = f'<div class="intro">{spec["intro_html"]}</div>' if spec.get("intro_html") else ""

    def section_html(section):
        children = "".join(section_html(child) for child in section.get("sections", []))
        return (
            f'<details class="section"{" open" if section.get("open") else ""}>'
            f'<summary>{html.escape(section["title"])}</summary>'
            f'<div class="sbody">{section.get("html", "")}{children}</div></details>'
        )

    sections = "".join(section_html(section) for section in spec.get("sections", []))
    legend = legend_html(spec.get("option_help"))
    # localStorage namespace: an explicit author `key` wins; otherwise derive a CONTENT key so a
    # regenerated page can't restore a DIFFERENT page's picks (the stale-verdict guard the kit
    # gives every surface).
    spec_key = spec.get("key") or kit.content_key(
        {k: v for k, v in spec.items() if k != "key"}, prefix="auto")
    client_spec = json.dumps({"key": spec_key, "blob_header": spec.get("blob_header", ""),
                              "expand_on": spec.get("expand_on", [])})

    has_suggestions = any(it.get("suggested") for it in spec.get("items", []))
    accept_btn = ('<button id="acceptall" title="select every suggested pick (respects the filter)">'
                  '★ accept suggested</button>') if has_suggestions else ""
    # `live` (spec field or --live) lets this page be DRIVEN through the live canvas (webui.session):
    # inject the kit's re-serve channel (toast/progress CSS; the picker is --shadow-clash-free) + the
    # SSE client, so the agent can push reload/toast into the open picker tab. Default off = unchanged.
    live = bool(spec.get("live")) or ("--live" in sys.argv)
    live_block = (f"<style>{kit.live_css()}</style><script>{kit.sse_client_js()}</script>") if live else ""
    # the gallery lightbox overlay: one per document, only when an image media entry exists
    has_images = any(entry.get("kind") == "image"
                     for item in spec.get("items", []) for entry in item.get("media") or [])
    lightbox = ('<div class="chu-lightbox" id="lightbox" hidden>'
                '<img src="data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw=="'
                ' alt="expanded view"><div class="cap"></div></div>') if has_images else ""
    page_width = int(spec.get("page_width", 920))
    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(spec.get("title", "decision page"))}</title>
<style>{CSS}
:root{{--pagew:{page_width}px}}</style></head>
<body>
<button class="themebtn" id="themebtn">dark mode</button>
<div class="phead">
<h1>{html.escape(spec.get("title", "decision page"))}</h1>
{readout}
{intro}
{legend}
</div>
{sections}
{cards}
{lightbox}
<div class="selbar">
 <div class="row">
  <span id="count"></span>
  <span id="substate"></span>
  <button class="primary" id="submitbtn" hidden>Submit to session</button>
  <button id="copybtn">Copy selection</button>
  <button id="resetbtn">Reset</button>
  {accept_btn}
  <span class="kbhint">j / k move · a accept</span>
  <details class="blobwrap"><summary>selection blob</summary>
  <textarea id="blob" readonly></textarea>
  <p class="hint">Submit sends this blob straight to the waiting session. No server? Copy it and paste it into the chat instead, same effect.</p>
  </details>
 </div>
</div>
<script>window.SPEC = {client_spec};</script>
{SCRIPT.replace("__THEME_KEY__", THEME_KEY)}
{live_block}
</body></html>
"""
    output_path = os.path.join(output_dir, "picker.html")
    assert_full_dark_override(page, label="decision picker")   # fail loud, never ship a half-theme
    with open(output_path, "w") as handle:
        handle.write(page)
    print(f"RENDERED {output_path}", flush=True)


if __name__ == "__main__":
    main()
