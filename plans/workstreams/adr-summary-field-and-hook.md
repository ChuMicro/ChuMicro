# Workstream: ADR `Summary:` frontmatter field + SessionStart hook surface

Status: **proposed.**  Surfaced 2026-05-24 during a discussion of the SessionStart hook ADR listing.  The filename slugs the hook emits (and the H1 titles inside each ADR) mostly restate each other, so an agent landing in a session sees *that* an ADR exists but not *what it decided*.  A canonical one-line summary in each ADR's frontmatter, surfaced by the hook, closes that gap with bounded context cost (~5–7 KB once per session).

## Problem

`chumicro-workspace library add` users and in-mono-repo agents both need to scan "what's already been decided about X" at session start.  Today's hook output (`ls plans/decisions/`) gives slugs; the slug usually restates the H1 title.  Neither surfaces the decision itself.  The bold-lead-sentence convention in `## Decision` is partly in use (11 of 82 ADRs, mostly post-0070) but not enforced and not machine-extractable cleanly.

## Decision

A new frontmatter field — `Summary:` — captures one machine-extractable sentence per ADR.  Required for new ADRs (skill template enforces); backfilled across the existing 71 entries; lint-checked; emitted by the SessionStart hook in place of the bare `ls`.

## Implementation phases

### Phase 1 — Template + skill update (DONE — commit pending)

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

### Phase 3 — CHU lint enforcement

`workbench/checks/src/chumicro_checks/chuXXX.py` (next free CHU number — currently 029, so likely CHU030 or whatever the next-free check is): assert that every `plans/decisions/[0-9]*.md` file has a non-empty `Summary:` line in the first ten lines.  Hooks into `python scripts/run.py lint`.  Drift-mechanization policy per Decision 0074 — make the rule self-enforcing rather than dependent on review discipline.

### Phase 4 — SessionStart hook surface

`.claude/settings.json` — replace `ls plans/decisions/` with:

```sh
for f in plans/decisions/[0-9]*.md; do
  base=$(basename "$f" .md)
  summary=$(grep -m1 '^Summary:' "$f" | sed -E 's/^Summary:[[:space:]]*//')
  printf '%s — %s\n' "$base" "$summary"
done
```

Output ~6–8 KB total (depending on summary length distribution), one-time-per-session cost.  Filename markers (`SUPERSEDED-BY-`, `INERT-`) stay visible via the slug; status is implicit in the marker.

## Validation history

<!-- One line per phase as it lands.  Format: `- **YYYY-MM-DD** Phase N. <short summary> + commit hash.` -->

## Out of scope

- Adding a `Summary` field to workstream files.  Workstreams are tracked in-progress work, not durable decisions; the ADR convention is the right one to mechanize.
- Promoting infrequent fields (e.g. `Superseded by:`) into the hook output.  The filename markers already surface that.
- Auto-generating Summary fields from the ADR body via NLP.  Hand-written is better — the act of summarizing is itself the discipline this workstream is establishing.
