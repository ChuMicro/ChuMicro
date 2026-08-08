---
name: surfaces
description: Put a rich HTML surface in front of the human when the terminal is not enough - a decision picker over many items, an A/B compare, prose questionnaires, media hand-off (images, audio, video, files), uploads the human hands back, reports, or live status. Use when AskUserQuestion or a plain prompt would lose the shape of the question.
---

# Surfaces

Rich pages the agent puts in front of the human, all through one hub: decision pickers,
compare-and-edit, prose questionnaires, reports, live status. Pure stdlib, self-contained
pages (inline CSS and JS, work from `file://`), one shared kit so a palette or affordance
fix lands once. This is agent-to-human tooling, not a product UI; the name `webui` stays
reserved for product-facing surfaces.

## Reach for a surface instead of AskUserQuestion when

- **Many items** - more than a handful, or options that need explaining to choose between.
- **A/B compare** - candidate texts side by side, pick one or edit the winner in place.
- **Something visual** - a diff, a table, structured findings, a report to read first.
- **Real prose** - the human types paragraphs into several fields, not one short line.
- **A batch of decisions** - one card per item, each with its own verdict and notes.
- **An artifact changes hands** - the human must see, take, or hand back a file.

`AskUserQuestion` stays right for a single small choice with short options. An ask that
outgrows the widget renders a surface instead, even for two items.

## The hub

One server per repo (`python3 -m surfaces.hub`, port 17874, state in `.scratch/hub/`),
owning ONE browser tab. Everything the agent wants seen is a posted surface with a
lifecycle: pending, then answered or withdrawn or expired.

- Never open the URL yourself and never set `PICKER_NO_OPEN`: the hub opens the browser
  only when no tab is connected and pushes into the open shell otherwise.
- A pending question the conversation has moved past gets withdrawn
  (`PYTHONPATH=.claude python3 -m surfaces.hub withdraw <id>`, id from the ASKED line) or
  superseded (`--supersede` on the re-serve). Its stale URL then answers 410.
- The hub starts on demand (race-safe lockfile), reuses its port so a reopened hub revives
  the old tab, and exits after 15 idle minutes with nothing pending. Named terminator,
  nothing outliving its usefulness, and doctor can reap a `.scratch/hub/hub.lock` stray.

## The loop

```bash
# spec.json into the effort's dir (a workstream surfaces/ dir, or .scratch/)
python3 .claude/surfaces/render_picker.py <dir>/spec.json <dir>   # RENDERED <dir>/picker.html
python3 .claude/surfaces/serve_picker.py <dir>                    # run_in_background
# exit 0 answered -> read <dir>/selection.txt; 3 withdrawn; 4 expired; 5 hub unreachable
```

Status surfaces: `hub post page.html --kind status --tag <t>` once, then
`hub update <id> page.html` each turn: same card, same tab, live progress via
`hub push <id> --progress 0.6`.

## Choosing the surface (route by shape, never by habit)

- Many items, one call each -> the decision picker (cards, facets, notes).
- Candidate texts differing by ONE named variable against a shared baseline -> the
  `columns` pick_ui, axis named in the summary. Apples-to-oranges is not a pick-one: give
  each its own card and verdict.
- The real answer is sentences -> `prose` fields (prompted paragraph boxes; each rides the
  blob as its own `prose <item>.<id>:` line).
- The real answer is short and structured -> `fields` on the card: `text` (one line,
  seedable), `multi` (checkboxes), `scale` (a range with BOTH ends labeled), `menu` (one
  pick from a long list), and `allow_other` on a radio row for a write-in seat.
  `required: true` gates Submit until answered. Each rides the blob as its own kind-named
  line (`field` / `multi` / `scale` / `menu` / `other`).
- The human needs to SEE or TAKE an artifact -> `media` on the card: image galleries
  (lightbox), a before/after `compare` slider, audio and video players (the hub serves
  Range, so they scrub), and `file` cards. A markdown or text file renders ON the card;
  everything else is a download card. Everything shown is also downloadable; src paths are
  staged into the page dir, so `file://` and the hub serve the same bytes. A pure exhibit
  is an informational card (`options: []`) carrying only media.
- The human needs to HAND OVER a file -> an `upload` field: drag or browse, the hub stores
  it under the surface's state (`in/`), and the blob carries the absolute path. Copy the
  file out promptly; resolved surfaces are eventually pruned.
- Ongoing status -> a hub status surface.
- None of these fit -> design the page: `kit.page(title, body)` inherits shell, palette,
  affordance, media components, and the submit path.

## The content floor

`render_picker.py` refuses a decision page a cold reader could not act on: a 120+ char
brief (`intro_html` or `brief`), a real summary per decision card (60+ and axis-defining
when options are bare letters, never a naked "who wins"), full-sentence `option_help` per
radio option, real prose prompts, no fragment-joiners outside quoted spans. Fields hold the
same line: every field is labeled (a short label needs a help sentence), a scale names both
ends, multi and menu carry real option sets, an image carries a caption or alt, and a media
src missing on disk refuses to render (MEDIA lines). FLOOR lines plus exit 2; fix the spec.
`floor_waived` (a written reason, 20+ chars) is for the rare page the floor cannot fit,
never a shortcut.

## Wording the ask

`ask_gate.py` is the PreToolUse hook on AskUserQuestion: the question text opens with one
or two plain sentences naming what is being decided and what hangs on it; every option
description is a full sentence on what picking it does and when it is right; no
fragment-joiners outside quotes; comparison text goes in previews.

## Authoring rules (the kit enforces them)

- **Theme through CSS variables only.** Every color is a `--var`; `kit.page()` runs the
  dark-override linter (`theme.py`) and refuses to ship a page that defines a light color
  with no `:root[data-theme=dark]` override (the half-theme trap).
- **One construction layer.** Palette, page shell, affordance helpers, content-key, and the
  SSE client all live in `kit.py`, so a fix lands once and every surface inherits it. Never
  re-roll a palette in a surface.
- **The server is transport only.** It never parses or applies a submission; it writes the
  blob to a file and the session reads it. Decision logic stays in the session.

## Validation

```bash
PYTHONPATH=.claude python3 -m surfaces.check_kit    # kit + session + canvas + hub round-trip
python3 .claude/surfaces/validate_picker.py         # render/structure/js/drift/floor/vnu
python3 .claude/surfaces/validate_picker_smoke.py   # headless chromium; skips loudly
```

A validator never mutates its subject: no argument = fixture into its own temp dir;
`<page.html|dir>` = read-only; `--fixture-out` refuses a non-empty directory.
`picker_edit_gate.py` runs `validate_picker.py` automatically after any edit to the
renderer or validator.

## Editing the package

`.claude/surfaces/` and this skill are one unit: a change to the renderer or the kit
usually needs a matching change here, and the validators above are what prove the pair
still agree. Keep the palette, the JS name prefix, and the hub constants in the repo's own
theme file rather than inlining them at each call site.
