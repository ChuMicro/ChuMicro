# Workstream: ADR `Visibility:` tier — active vs dormant for SessionStart surfacing

Status: **parked 2026-05-24.** Superseded by a simpler decision: drop ADR injection from SessionStart entirely (Position A in the active/dormant/full-drop tradeoff discussion). AGENTS.md carries the rules; ADRs are referenceable on demand via `grep ^Summary: plans/decisions/`. The active/dormant classification work becomes moot — there's nothing to partition if nothing is injected. Hook simplified in `.claude/settings.json` to omit the ADR block entirely.

Kept on file because the classification analysis below is reusable if we revisit (e.g. revert to slug-only injection — Position B — if we miss the discoverability surface in practice). If we do revisit, the rubric + 37/41 split is the starting point.

---

(Original problem statement and decision follow — preserved for future reference.)

Surfaced 2026-05-24 as a follow-on to [`adr-summary-field-and-hook.md`](adr-summary-field-and-hook.md). The Summary-field backfill closes the slug-vs-decision gap, but even with a tight one-liner per ADR the SessionStart hook still surfaces every accepted record once per session — including ones that are accepted and factually still true but consulted only when a specific subsystem comes up. Decision 0017 (RingIO build flag, self-removing on upstream fix, code does the thing) is the motivating shape: real ADR, real rationale, zero routine reasoning load.

## Problem

The dead-vs-live axis is already mechanized — `INERT-` and `SUPERSEDED-BY-NNNN-` filename markers (Decision 0076) carry it, and the Phase 4 hook snippet filters both. What's not mechanized is the live-but-niche axis. An accepted ADR may be:

- **Active** — agents reason about it in routine work. Tick budget, runner pattern, library dep policy, naming, deploy modes, workspace shape. The Summary at session start is a quick-scan index that helps agents pick the right invariant.
- **Dormant** — agents only consult it when a specific topic comes up. Build-flag workarounds, library-internal contracts, OS-specific deploy hardening, CI workflow internals, retired-process records. The Summary at session start is context spent on a record the reader skips.

77 active ADRs × ~150-char Summary ≈ 11–12 KB once per session. Roughly 60% of that is dormant signal that pads the active read.

## Decision

A second frontmatter field — `Visibility:` — with enumerated values `active` (default) and `dormant`. The SessionStart hook surfaces three tiers:

- **Active** ADRs get their full Summary line.
- **Dormant** ADRs and **SUPERSEDED** ADRs get slug-only output, so the index stays discoverable without paying the Summary cost. SUPERSEDED slugs are useful because the filename literally names the successor (`NNNN-SUPERSEDED-BY-MMMM-…`).
- **INERT** ADRs are skipped entirely. The topic is genuinely no longer load-bearing and the slug carries no actionable info; a reader can grep `plans/decisions/*INERT*` if curious.

### Rubric

An ADR is **active** when at least one holds:

- The rule or invariant it carries is in AGENTS.md non-negotiables, or is cited regularly across skills / commits.
- It defines structural shape agents work within (workspace layout, library inventory, test tier architecture, runtime tier).
- It states a cross-library pattern multiple libraries implement (constructor injection, runner shape, from_config classmethod).
- It is a recent direction-setting decision not yet fully reflected everywhere downstream.

An ADR is **dormant** when:

- The decision is a workaround or build-flag record — code does the thing, agents don't re-derive it (e.g. 0017 RingIO flag).
- The contract is library-internal — only relevant when touching that library (e.g. 0064 mqtt three-tier sizing, 0067 MP TLS bundle).
- The mechanism is process-internal — CI workflow shape, preflight parallelism, internal sweep ordering. Agents invoke the command; how it's structured doesn't show up in routine work.
- The decision was a one-time process change that has landed and won't be revisited (e.g. 0075 retire `init`, 0038 bootstrap-via-clone).
- The detail is forensic / OS-specific recovery already encoded in code (e.g. 0033 macOS CIRCUITPY hardening).

When the test is ambiguous, default to `dormant` — a missed surface is recoverable via grep; over-surfaced context is the failure mode this workstream exists to address.

## Implementation phases

### Phase 0 — Migrate 0070's rule into AGENTS.md before demoting it

Decision 0070's `__chumicro_host_only__` marker is the only marker rule not already surfaced in AGENTS.md non-negotiables. Demoting it without lifting the rule would lose the surface. Add a sibling bullet to the existing test-marker bullets (around line 49–50) before Phase 2 lands the visibility change for 0070.

### Phase 1 — Template + skill update

`.github/skills/new-decision/SKILL.md`:

- Template adds `Visibility: active` between `Summary:` and `Related:`, with a comment line documenting the enum and the rubric link.
- Verify checklist gains "Visibility field present + value is `active` or `dormant` + rationale matches rubric when `dormant`".
- New ADRs default to `active`. The skill prompts the author to consider `dormant` for build-flag / workaround / library-internal-only / process-mechanic shapes.

### Phase 2 — Apply classification to existing 77 active ADRs

Per the classification roster below. One commit per group of related demotions so a regression in one judgment doesn't block the rest. Estimate: 3–5 commits.

The roster is initial — author judgment, not committee. Borderline calls flagged with a note so a reviewer can challenge before the edit lands.

### Phase 3 — CHU lint enforcement

Extend the CHU lint added by the parent workstream's Phase 3 to also assert `Visibility:` present + value in `{active, dormant}`. Same lint pass, two field checks. Drift-mechanization policy per Decision 0074.

### Phase 4 — SessionStart hook surface

**Replaces** the parent workstream's Phase 4 snippet rather than extending it — the two-pass shape supersedes the one-loop "emit Summary for every non-dead ADR" version. Land this once, not first-the-simple-then-the-partitioned. Gated on Phase 2 of this workstream finishing so the first user-visible hook change ships the final shape (with no Visibility fields populated, the snippet degrades to emitting every ADR in the active block — equivalent to the parent's simpler version, but better to skip that intermediate state).

Two passes — full Summary lines for active, slug-only for dormant + SUPERSEDED, nothing for INERT:

```sh
echo "## Active ADRs"
echo
for f in plans/decisions/[0-9]*.md; do
  base=$(basename "$f" .md)
  case "$base" in *INERT*|*SUPERSEDED*) continue ;; esac
  visibility=$(grep -m1 '^Visibility:' "$f" | sed -E 's/^Visibility:[[:space:]]*//')
  [ "$visibility" = "dormant" ] && continue
  summary=$(grep -m1 '^Summary:' "$f" | sed -E 's/^Summary:[[:space:]]*//')
  printf '%s — %s\n' "$base" "$summary"
done

echo
echo "## Dormant + superseded ADRs (slugs only — grep ^Summary: plans/decisions/<slug>.md for context)"
echo
for f in plans/decisions/[0-9]*.md; do
  base=$(basename "$f" .md)
  case "$base" in *INERT*) continue ;; esac
  case "$base" in *SUPERSEDED*) printf '%s\n' "$base"; continue ;; esac
  visibility=$(grep -m1 '^Visibility:' "$f" | sed -E 's/^Visibility:[[:space:]]*//')
  [ "$visibility" = "dormant" ] && printf '%s\n' "$base"
done
```

Expected output: ~5.4 KB across 36 active Summary lines + ~2.4 KB across 44 dormant/SUPERSEDED slugs ≈ ~7.8 KB total. Comparable to Phase 4 of the parent workstream, but with the active-vs-dormant signal cleanly separated and INERT entries dropped.

## Initial classification roster

77 accepted ADRs (5 dead — 0004, 0005, 0006, 0008, 0035 — already filtered by filename marker).

### Active (37)

Plain bullets — rule / structure / pattern that an agent benefits from seeing in a random session in either the mono-repo or the workspace-template repo.

- **0001** mono-workspace layout — fundamental tree shape (libraries / workbench / support)
- **0002** per-library version files — VERSION bump rule
- **0003** test runtime boundaries — three-tier test architecture
- **0007** cross-platform dependency strategy — dep-picking rule (no Blinka, cross-runtime)
- **0009** per-library test runs — `scripts/run.py test` model
- **0010** library testability — constructor injection + `testing.py` per library
- **0013** docs and examples standards — per-library doc + examples shape + example-import rule
- **0014** runner pattern — `check(now_ms)` + `handle(now_ms)` central contract
- **0015** board architecture support — 256 KB / 800 KB usable flash minimum tier
- **0016** cross-runtime unit tests — UnixPortBackend + DeviceBackend split
- **0020** API breakage detection — griffe check + VERSION bump validation
- **0021** docstring type policy — PEP 604/585, no `typing`, no `__future__`
- **0022** naming conventions — CHU001 banned-abbrev list
- **0025** dual coverage thresholds — `--coverage-threshold 94` for agents
- **0028** deploy modes — RAM vs flash transport semantics (mono-repo functional tests + workspace-template project deploys)
- **0029** project workspace — workspace shape + UID identity + import-graph deploy (workspace-template sessions)
- **0030** config and state — TOML deploy-baked vs kvstore mutable split
- **0031** chumicro-sockets — thin protocol + per-runtime adapters
- **0032** workbench host tools — `workbench/` vs `libraries/` distinction
- **0036** chumicro-config library — `from_config` / `try_from_config` cross-lib pattern
- **0037** runtime file marking — `__chumicro_runtimes__` marker convention
- **0042** library dependency policy — Class 1 / Class 2 + substrate optionality
- **0046** shared/ + lazy libraries/ — workspace-template folder layout
- **0049** three-runtime trinity — CPython is testing seam, not deployment target
- **0051** runner-shaped as project policy — extends 0014 project-wide
- **0052** workbench no library imports — non-negotiable rule
- **0057** two-file config — workspace.yml + secrets.toml + project_config.toml (mono-repo dogfoods it; agents see these in pwd)
- **0058** test skips must be loud — non-negotiable
- **0065** device-library scaffolding cost — no `__slots__`, no passthrough `@property`
- **0066** agent-runnable CLIs need non-interactive mode
- **0074** drift mechanization as project policy — central meta-policy
- **0077** one device-staging path — deploy invariant
- **0078** library acquisition is host-local — `chumicro-workspace library add` (workspace-template sessions)
- **0080** runner reactor — central poll-and-wait
- **0081** non-blocking connect via tick-driven connector — non-negotiable
- **0082** chumicro_test_harness as infrastructure library — test-dep policy
- **0084** `gc.collect()` policy — forbidden / required / allowed three-context rule

### Dormant (41)

Bullets with a short reason.

- **0011** platform targeting — `[tool.chumicro] platforms` set once at lib creation by the new-library skill
- **0012** IDE type stubs — install-time mechanism, code does it
- **0017** CircuitPython RingIO build workaround — build flag, self-removing on upstream fix
- **0018** distribution bundle repo — publishing-time, only relevant when touching bundle repos
- **0019** branching model — AGENTS.md carries the "commit to main" rule; release-branch detail is future-state
- **0023** standalone promote workflow — CI workflow internal
- **0024** mip/circup folder serving — bundle repo internal layout
- **0026** editable installs — setup-time fact
- **0027** device testing infrastructure — transport internals (mpremote, pyserial raw REPL); the CLI is the surface
- **0033** macOS CIRCUITPY deploy hardening — OS-specific, code does it
- **0034** kvstore API and backends — library-internal contract, applies when touching persistence
- **0038** workspace bootstrap via clone — bootstrap-time, not revisited
- **0039** firmware version floor — fixed in `chumicro_workspace.firmware_support`
- **0040** chumicro-requests — library-internal contract
- **0041** chumicro-http-server — library-internal contract
- **0043** chumicro-sockets UDP — sockets extension, only when touching UDP
- **0044** deploy-time runtime-file filtering — mechanism encoded in deploy walker
- **0045** chumicro-websockets — library-internal contract
- **0047** deploy mode flash default — default + opt-out, code does it
- **0048** preflight phase-level parallel — internal preflight mechanism
- **0053** recovery layer philosophy — rule is verbatim in AGENTS.md non-negotiables
- **0054** streaming output and status modes — preflight output internals
- **0055** config pipeline unification — mono-repo dogfoods workspace-template flow, landed
- **0056** transport.stage extra_files — transport API extension
- **0059** deploy-example front-door command — command-level choice
- **0060** chumicro-checks CHU rules home — only relevant when modifying CHU lints
- **0061** WhenOversized cross-library contract — specific to requests / websockets
- **0062** entrypoint factory skip — deploy-walker rule, automatic
- **0063** duck-typed factory contract — factory submodule internal
- **0064** mqtt three-tier sizing + prefix sugar — mqtt-internal
- **0067** MP TLS default trust — CA bundle in sockets, code does it
- **0068** unified deploy-mode resolution — deploy + unit-sweep mechanism
- **0069** test-support module marker — `__chumicro_test_support__` rule is in AGENTS.md non-negotiables
- **0070** host-only test marker — `__chumicro_host_only__` rule migrated to AGENTS.md (Phase 0 of this workstream)
- **0071** per-library soft-reset in flash sweep — on-device sweep internal
- **0072** chunked test-module exec — on-device sweep internal
- **0073** msgpack decode trust boundary — only applies when decoding untrusted msgpack
- **0075** retire init creation is clone-only — process change, landed
- **0076** archive dead decisions in filename — only applies when archiving (new-decision skill handles)
- **0079** prose drift mechanization — audit-* skills carry the policy
- **0083** functional test endpoint taxonomy — applies when writing functional tests for network libs

## Validation history

<!-- One line per phase as it lands.  Format: `- **YYYY-MM-DD** Phase N. <short summary> + commit hash.` -->

## Out of scope

- Multi-level visibility tiers (`high` / `medium` / `low`). Two values cover the observed shape; expanding the enum trades clarity for fine-grained tuning agents won't actually use.
- Per-session opt-in (e.g. a flag that surfaces dormant ADRs too). Anyone who wants the full corpus runs `grep ^Summary: plans/decisions/`.
- Auto-promoting dormant → active when an ADR is cited in a recent commit. Citation frequency is a fuzzy signal; the author's judgment at write time + audit-shaped recalibration is the right shape, not a heuristic.
- Splitting the `Visibility` field across runtime / library / workbench scopes. The hook surface is one stream; scoping is what the Summary itself does.
