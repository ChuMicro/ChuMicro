# GA documentation pass: chumicro and the workspace template

Date: 2026-07-19
Status: awaiting user review

## Context

The structural pass (2026-07-18 spec) is complete through Phase 3; the
remaining launch gate is the user-gated stable relaunch to 17 of 17
projects.  The user called for the complementary work on 2026-07-19: both
repos go GA, and the documentation should be GA-quality first.  "There's
still things missing though, gotchas, documentation needs overhauls,
readmes, guides, lets get this place better looking here and in the
workspace template."

State of the surfaces at design time:

- The chumicro README (267 lines) and the template README (188 lines) are
  recently overhauled and strong.  INSTALL.md is 113 lines.
- All 14 libraries carry a README.md and a docs/guide.md, but they have
  not had a single consistency pass against the style guide's
  Documentation tone and Voice rules.
- docs/troubleshooting has 3 pages.  Known traps (Linux port permission,
  macOS CIRCUITPY behavior, the deploy clean-slate wipe) live scattered in
  READMEs, decision records, and workstream notes.
- docs/contributing has 15 pages, some predating the run.py split into
  scripts/run_tasks/ (structural pass Phase 2), so staleness is likely.
- The docs site builds per package with zensical + mkdocstrings, versioned
  by mike, with a generated landing page
  (scripts/generate_landing_page.py).  No recent end-to-end render review.
- Several docs correctly describe the experimental channel as current;
  those references must flip when the stable wave lands, and today they
  are scattered rather than tracked.

User rulings (2026-07-19, session Q&A):

- Scope: all four surfaces (front doors, gotchas/troubleshooting, library
  READMEs + guides, contributing docs) plus the docs-site pass.
- Approach: direct overhaul, not audit-then-sign-off.  Bulked commits;
  fewer, larger commits over per-file ones.
- Model topology: Opus agents where the work is bulk or mechanical; Fable
  (the main session) where reasoning is needed, explicitly including the
  true front-facing docs.

## Goals

1. Every documentation surface in both repos reads GA-quality: accurate
   against current code, consistent in voice per the style guide.
2. A real troubleshooting section, symptom-first, findable from the pages
   a reader is on when things fail.
3. The 14 library READMEs and guides follow one consistency spec.
4. Contributing docs match current tooling and read in the order a new
   contributor actually follows.
5. The docs site renders the above well: landing page, navigation, guide
   pages.
6. A GA flip list in plans/next-up.md so launch day's doc edits are a
   mechanical sweep.

## Non-goals

- No channel flips now.  The stable wave is user-gated; experimental
  references stay accurate until launch and are collected, not changed.
- The template's run.py lint self-rewrite side-finding stays parked
  (already tracked in next-up).
- No workbench README overhaul.  Recon may flag egregious problems there
  as side-findings, but the four workbench tool READMEs are out of scope.
- No new documentation systems, generators, or CI gates.  This pass works
  within the existing zensical/mike pipeline and lint rules.
- No code changes beyond what a doc fix strictly requires (a docstring
  feeding the API reference, for example).

## Phase 0: recon (Opus agents, parallel)

Five scout agents read everything and return per-file defect lists.
These lists are working input for the rewrite phases, not a sign-off
artifact.

1. Library docs: all 14 libraries' README.md + docs/guide.md, checked for
   drift against code and for tone violations.
2. Contributing docs: the 15 docs/contributing pages plus both repos'
   CONTRIBUTING.md, checked for staleness, overlap, ordering.
3. Template docs end to end: README, CONTRIBUTING, CHANGELOG,
   examples/README, projects/_template scaffolding text, AGENTS.md.
4. Gotcha harvest: decision records, workstreams, existing troubleshooting
   pages, demo READMEs, mining every board-bitten trap worth documenting.
5. Docs site: local build, render review of landing page, navigation, and
   one guide per shape.

## Phase 1: front doors (Fable, direct)

chumicro README + INSTALL, template README.  Both READMEs are recently
strong, so this is targeted repair: drift the recon finds, tone slips,
first-ten-minutes stumbling blocks.  No wholesale rewrite of pages that
already work.

## Phase 2: gotchas and troubleshooting

Grow docs/troubleshooting into a real section with a symptom-first index
README.  Sources: the Phase 0 harvest plus a fresh-clone walkthrough of
the template's laptop-only path (setup, scaffold, laptop demo, no board)
run on this machine to catch friction firsthand.  Wire links from
INSTALL.md and both READMEs so the section is findable at the moment of
failure.

## Phase 3: library READMEs and guides (Opus fan-out, Fable review)

First a one-page consistency spec: section order, runtime-support table
shape, voice rules distilled from the style guide.  Then per-library Opus
agents apply it across all 14 libraries.  Fable reviews every diff and
rewrites front-facing pitch sections directly where the agent's version
falls short.  Library READMEs render on PyPI, so CHU006-shaped leak rules
apply in full.

## Phase 4: contributing docs

Fix staleness (cheat sheet and workbench pages against the run.py task
modules), collapse overlap between pages, check the reading order a new
contributor follows.  Both repos' CONTRIBUTING.md included.

## Phase 5: docs site

Local zensical build; review the generated landing page, navigation, and
a rendered guide per shape; fix what's off within the existing pipeline.

## Phase 6: wrap

- GA flip list: every doc line that must change when stable goes live
  (bundle names, channel notes in the template README and guides),
  appended to the existing launch bullet in plans/next-up.md.
- Preflight and docs build green in chumicro; template checks green.
- task-checkpoint to close out.

## Commit shape

One bulked commit per phase per repo: roughly six in chumicro, two or
three in the template.

## Verification

- python scripts/run.py lint (prose lints included) and preflight in
  chumicro; the template's own checks in the template.
- Local docs build passes; landing page and navigation visually reviewed.
- The fresh-clone walkthrough in Phase 2 doubles as end-to-end
  verification of the template's documented first-run path.
