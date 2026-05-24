# Workstream: ADR `Summary:` frontmatter field + SessionStart hook surface

Status: **proposed.**  Surfaced 2026-05-24 during a discussion of the SessionStart hook ADR listing.  The filename slugs the hook emits (and the H1 titles inside each ADR) mostly restate each other, so an agent landing in a session sees *that* an ADR exists but not *what it decided*.  A canonical one-line summary in each ADR's frontmatter, surfaced by the hook, closes that gap with bounded context cost (~5–7 KB once per session).

## Problem

`chumicro-workspace library add` users and in-mono-repo agents both need to scan "what's already been decided about X" at session start.  Today's hook output (`ls plans/decisions/`) gives slugs; the slug usually restates the H1 title.  Neither surfaces the decision itself.  The bold-lead-sentence convention in `## Decision` is partly in use (11 of 82 ADRs, mostly post-0070) but not enforced and not machine-extractable cleanly.

## Decision

A new frontmatter field — `Summary:` — captures one machine-extractable sentence per ADR.  Required for new ADRs (skill template enforces); backfilled across the existing 71 entries; lint-checked; emitted by the SessionStart hook in place of the bare `ls`.

## Implementation phases

### Phase 1 — Template + skill update (DONE in `4bf6aa4d`)

`.github/skills/new-decision/SKILL.md`:

- Template adds `Summary: <!-- one-sentence machine-extractable… -->` between `Date:` and `Related:`.
- Verify checklist gains "Summary field present + one sentence + ≤200 chars + no line wraps".

### Phase 2 — Backfill the 71 existing ADRs

Per ADR: read the file, write one sentence that states what was decided (not what the topic is — the H1 already does that).  Constraints: under ~200 chars, no line wraps, plain prose + backticked code identifiers only, no markdown formatting that would break a `grep ^Summary:` extraction.

Backfill works as an audit-shaped pass:
- Group ADRs by topic cluster (sockets/0031+0043, mqtt/0064, library policy/0042+0078, etc.) so adjacent reads carry context.
- Per cluster, draft the Summary, confirm against the Decision section's bold lead (where present) or the ADR's load-bearing rule (where not).
- Each cluster commits separately so a regression in one Summary doesn't block the rest.

Estimate: ~8–10 cluster commits, ~70 ADRs total.  No code change; lint stays advisory until Phase 3.

### Phase 3 — CHU lint enforcement (DONE — `CHU029`)

`workbench/checks/src/chumicro_checks/rules/chu029.py` asserts that every `plans/decisions/[0-9]*.md` file (excluding `README.md` and non-numbered files) has a `Summary:` line in the first ten lines, that the value is non-empty, and that it is ≤200 chars.  Hooks into `python scripts/run.py lint` via the existing rule registry.  Suppression: `<!-- noqa: CHU029 -->`.  Drift-mechanization per Decision 0074 — the contract no longer depends on review discipline.

### Phase 4 — SessionStart hook surface

`.claude/settings.json` — replace `ls plans/decisions/` with:

```sh
for f in plans/decisions/[0-9]*.md; do
  base=$(basename "$f" .md)
  case "$base" in *INERT*|*SUPERSEDED*) continue ;; esac
  summary=$(grep -m1 '^Summary:' "$f" | sed -E 's/^Summary:[[:space:]]*//')
  printf '%s — %s\n' "$base" "$summary"
done
```

Dead ADRs (`INERT-` per Decision 0076, `SUPERSEDED-BY-` per the supersession rule) are filtered from the hook — their filenames already announce dead-ness, and surfacing each at session start spends context on records the reader will skip.  They still carry `Summary:` fields (backfill is corpus-wide, CHU lint applies uniformly) so `grep ^Summary plans/decisions/` remains a complete corpus index for anyone who asks.

Output ~10–12 KB total at ~150-char average across 77 active ADRs, one-time-per-session cost.

## Validation history

<!-- One line per phase as it lands.  Format: `- **YYYY-MM-DD** Phase N. <short summary> + commit hash.` -->

- **2026-05-24** Phase 1.  `new-decision` SKILL template gains required `Summary:` frontmatter field + verify checklist.  Commit `4bf6aa4d`.
- **2026-05-24** Phase 2 pilot (5 ADRs: 0001, 0002, 0003, 0004, 0005).  Riskiest-assumption gate cleared — 4 strong disambiguations + 1 mild (0005 slug already half-answers).  Dead-ADR scope resolved: backfill all 82 (uniform CHU lint), hook filters `INERT|SUPERSEDED` filename markers (Phase 4 snippet updated).
- **2026-05-24** Phase 2 cluster 2 — workspace + test + project standards (0006–0013, 8 ADRs).
- **2026-05-24** Phase 2 cluster 3 — runtime foundations (0014–0017, 4 ADRs); 0015 correction surfaced + landed separately (`2 MB physical / ~800 KB usable flash`, not `4 MB`).
- **2026-05-24** Phase 2 cluster 4 — distribution + workflow + standards (0018–0023, 6 ADRs).
- **2026-05-24** Phase 2 cluster 5 — mpy serving, coverage, deploy, workspace, config (0024–0030, 7 ADRs).
- **2026-05-24** Phase 2 final sweep — 0031–0083 in one commit (52 ADRs, batched 8 at a time during drafting).  All 82 ADRs now carry a `Summary:` field, range 125–197 chars (cap 200).
- **2026-05-24** Phase 3.  `CHU029` lands in `chumicro-checks` — asserts every `plans/decisions/NNNN*.md` carries a non-empty `Summary:` line in the first 10 lines, ≤200 chars.  Zero violations on the current corpus.

## Out of scope

- Adding a `Summary` field to workstream files.  Workstreams are tracked in-progress work, not durable decisions; the ADR convention is the right one to mechanize.
- Promoting infrequent fields (e.g. `Superseded by:`) into the hook output.  The filename markers already surface that.
- Auto-generating Summary fields from the ADR body via NLP.  Hand-written is better — the act of summarizing is itself the discipline this workstream is establishing.
