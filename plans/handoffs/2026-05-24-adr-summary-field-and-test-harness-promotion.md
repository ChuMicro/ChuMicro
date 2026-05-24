# Handoff 2026-05-24 — ADR Summary-field workstream then test-harness promotion

## What this session was about

Started with "pick the next-up item." Chose the broken `test_real_serve.py` line-37 bullet (`chumicro_sockets_factory` rename from Decision 0081 Phase 4) and the three workspace-template apps with the same issue. Mechanical rename led into a thread on why `/audit-library` didn't catch the test-isolation rule, which led to discovering the `examples/helpers.py` pattern that already solved the cross-library-import problem for examples but had never been applied to functional tests. Discussion spiralled (productively) into where the test harness should live and how it should ship to workspace-template consumers without the mono-repo. That landed two ADRs and kicked off a third workstream about ADR `Summary:` fields for hook surface.

## What's in flight

Nothing uncommitted. Working tree clean, 8 commits ahead of `origin/main`.  `[VERIFIED: git --no-pager status --short returns empty; git log shows 4bf6aa4d as HEAD]`

ChuMicro-Workspace-Template repo is **1 commit ahead of `origin/main`** with the `chumicro_requests` rename fix to the two `examples/` apps + paired README. The third app (`projects/two_board_test/client/{app.py,README.md}`) carries the same edit but in an untracked directory — the user wasn't sure if that project was temporary, so it stays in the working tree there.  `[VERIFIED — confirmed when committing earlier in session]`

## What got done

Eight commits on `main`, in order:

- `90e834c7` — fix Decision 0081 Phase 4 rename fallout (test_real_serve.py + 2 websockets docstrings)
- `bc744b66` — Decision 0082: chumicro_test_harness as infrastructure library + websockets VERSION 0.19.3 (missed bump for previous commit's src/ change)
- `ebc31c79` — Decision 0083: functional tests use controlled endpoints by default
- `4ea8e3ea` — AGENTS.md: surface `--coverage-threshold 94` on preflight + test command-table rows
- `ec3ed1a6` — AGENTS.md: trim duplicated rationale from those rows (user caught the over-imperative phrasing)
- `42cef99d` — AGENTS.md + task-checkpoint: soften "yield after each unit" coupling (named-successor multi-item-plan extension)
- `c72d7e1e` — ADR title-format unification (0011, 0012, 0015) + AGENTS.md "directly-material drift" softener
- `4bf6aa4d` — new-decision skill: require `Summary:` frontmatter field; workstream kicked off

Plus `c4b69f6` on `ChuMicro-Workspace-Template` (3 apps + 2 READMEs renamed).

## Decisions made (not yet captured in ADRs)

The `Summary:` frontmatter field rule itself isn't in an ADR. The workstream file [`plans/workstreams/adr-summary-field-and-hook.md`](../workstreams/adr-summary-field-and-hook.md) has a `## Decision` header that names the rule (Summary field in frontmatter, lint-enforced, hook-surfaced; bold-lead-in-Decision pattern rejected as source of truth), and the `new-decision` skill template now requires the field — but no ADR codifies it. **Open question for the next session:** does the Summary-field rule deserve its own ADR (it's a structural project policy that future agents would otherwise have to rediscover), or is the workstream + skill template sufficient? My read: ADR-shaped, since the *rejected alternative* (bold-lead pattern) has real cost the workstream doesn't capture cleanly.

## What was learned

- `check_version` diffs `origin/main...HEAD` (committed only), not the working tree. So a VERSION bump for a previous commit's `src/` change needs to land in a later commit, not via `--amend`. Surfaced when `bc744b66` had to include `libraries/websockets/VERSION 0.19.2 → 0.19.3` for `90e834c7`'s docstring edits.  `[VERIFIED: scripts/check_version.py:38-95; scripts/repo_layout.py:646-655]`
- 11 of 82 ADRs already use a bold-lead-sentence in `## Decision` (newer ADRs, ~0070+); 71 don't. The convention exists but isn't enforced and is not the prevailing shape.  `[VERIFIED: awk script that emitted YES/NO counts]`
- Self-loopback functional tests on Pi Pico W fail due to consumer-router hairpinning behavior, not chumicro bugs. `test_real_serve.py`'s loopback design depends on the router reflecting `STA → my-own-IP` packets back, which most consumer APs refuse.  `[VERIFIED: on-device run via test-libraries-functional --library http_server --file test_real_serve --runtime both; MP got HttpTimeoutError, CP got HttpError ECONNABORTED, both after WIFI_OK + SERVER_OK printed]`. Now formally captured in Decision 0083's rejected-alternatives section.
- The `examples/helpers.py` pattern (CP `wifi` + MP `network` + `struct` only, zero `chumicro_<other>` imports) is the canonical wifi-bringup shape that the test-harness `network` submodule will absorb. Pattern exists; copies have drifted.  `[VERIFIED: read libraries/http_server/examples/helpers.py; AGENTS.md test-isolation rule names support/test_harness/ as sanctioned import]`
- AGENTS.md was tightened recently with the planned escape valve of softening sections when they're found being over-applied. This session produced two such softenings (named-successor multi-item-plan extension + directly-material drift extension). The pattern: a strict rule that fires correctly in most cases but over-applies in a specific common subcase, fixed with one targeted sentence extending the rule.  `[VERIFIED: user stated this directly when I was committing the named-successor edit]`

## Riskiest assumption

**The Summary-field surface (Phase 4 of the workstream — replace bare `ls` in the hook with `slug — Summary` per ADR) will be worth the ~5–7 KB context cost.** The H1 title was rejected because it mostly restates the filename. The hope is a hand-written one-sentence Summary will be meaningfully different from the slug — but until 71 backfilled Summaries are read by future agents, that's a belief, not evidence. The cheapest falsifier: backfill 5 ADRs at the start of Phase 2, run the hook output through a side-by-side comparison with the current bare `ls`, and judge whether the Summary lines look like they actually disambiguate. If the first 5 Summaries read as glorified restatements of the slug, kill the workstream and revert to bare `ls`.  `[HYPOTHESIS: cheapest test = 5-ADR pilot before committing to backfill]`

## To re-research / verify next session

The end-goal is the SessionStart hook printing each ADR's Summary line. Two workstreams sequence to get there:

**Sequence 1 — Finish ADR Summary field + hook surface.** [`plans/workstreams/adr-summary-field-and-hook.md`](../workstreams/adr-summary-field-and-hook.md)

- **Phase 2 — backfill 71 existing ADRs.** Audit-shaped, ~8–10 cluster commits.  Suggested first cluster: 0001–0007 (workspace foundations) since the per-ADR judgment calls are smaller there. Each Summary: one sentence, ≤200 chars, no line wraps, plain prose + backticked code identifiers only.  Apply the riskiest-assumption pilot first (5 ADRs → judge → continue or kill).
- **Phase 3 — CHU lint.** `workbench/checks/src/chumicro_checks/chuXXX.py` (next-free CHU number; check current highest). Assert every `plans/decisions/[0-9]*.md` has a non-empty `Summary:` line in the first ten lines. Hooks into `python scripts/run.py lint`.
- **Phase 4 — SessionStart hook switch.** `.claude/settings.json` — replace `ls plans/decisions/` with the per-file loop in the workstream (Phase 4 section has the exact shell snippet).
- **(Optional, possibly first) Write the Summary-field ADR.** See "Decisions made (not yet captured in ADRs)" above.

**Sequence 2 — Test-harness promotion.** [`plans/workstreams/test-harness-promotion-and-network-helper.md`](../workstreams/test-harness-promotion-and-network-helper.md)

After Sequence 1 finishes, move to this workstream. It accepts Decisions 0082 + 0083 and tracks the implementation:

- **Phase 1 — add `chumicro_test_harness.network` submodule in place at `support/test_harness/...`.** Port `wifi_up()` + `runtime_config()` from one canonical `examples/helpers.py` (probably `libraries/mqtt/examples/helpers.py` — most recent). Cross-runtime test file at the harness level.
- **Phase 2 — switch 5 networking libraries' functional tests to import from `chumicro_test_harness.network` + add Category-1/2 declaration to each module docstring per Decision 0083.** Host-side fixtures (Mosquitto, UDP echo) move to `workbench/pytest-device/src/chumicro_pytest_device/fixtures/`. `http_server/test_real_serve.py` becomes Category 1 host-driver-as-client (drops `chumicro_requests`, uses stdlib socket).
- **Phase 3 — examples switch or keep inlined per library** (judgment call).
- **Phase 4 — tree move `support/test_harness/` → `libraries/test_harness/`** with `[tool.chumicro] kind = "infrastructure"`. Inbound path references in AGENTS.md lines 81 + 179, Decisions 0016/0058/0070, scripts/, workbench/pytest-device/ — all update in place.
- **Phase 5 — snapshot publishes `kind` field; CLI filters by it.**
- **Phase 6 — distribution-graph dep declarations** (networking libs add `chumicro-test-harness` to `[project].dependencies`).

## Dead ends

- **Proposed making `--coverage-threshold 94` the tool default** to make bare `preflight` do the right thing. User caught this — Decision 0025 establishes a dual threshold (humans 85% via pyproject default, agents 94% via flag). The tool default must stay at 85%. Fix instead landed in `4ea8e3ea` + `ec3ed1a6`: command-table shows the flag in the canonical invocation, rule stays at AGENTS.md line 47.
- **Proposed a SessionStart hook approach for ADR titles**. User pointed out AGENTS.md is already loaded once-per-session (not per-turn), so the "embedded-in-AGENTS.md" approach was lighter than a new hook. Then user further observed that the ADR H1 just restates the filename slug, so the *title* pull wasn't worth doing at all. Landed on `Summary:` frontmatter field instead. Hook stayed at bare `ls plans/decisions/` for now.

## How to rebuild context fast

- **Resume command**: `/session-resume` (it'll find this file via the `## Now` pointer in next-up.md).
- **The two workstream files** are the load-bearing source of truth:
  - [`plans/workstreams/adr-summary-field-and-hook.md`](../workstreams/adr-summary-field-and-hook.md) — Sequence 1
  - [`plans/workstreams/test-harness-promotion-and-network-helper.md`](../workstreams/test-harness-promotion-and-network-helper.md) — Sequence 2
- **The two ADRs landed this session** carry the architectural framing:
  - [`plans/decisions/0082-test-harness-as-infrastructure-library.md`](../decisions/0082-test-harness-as-infrastructure-library.md)
  - [`plans/decisions/0083-functional-test-endpoint-taxonomy.md`](../decisions/0083-functional-test-endpoint-taxonomy.md)
- **`.github/skills/new-decision/SKILL.md`** template now has the `Summary:` field — read lines 60–80.
- **Recent commits 90e834c7..4bf6aa4d** are this session's work (`git log --oneline 90e834c7~1..HEAD`).
- **AGENTS.md edits** to revisit if the softener pattern comes up again:
  - line 51 (Always clean up after yourself — directly-material drift exception)
  - around line 130 (named successor is a directive — multi-item-plan extension)
  - line 47 (coverage-threshold rule — load-bearing original)
  - lines 224–225 (command table — flag shown in canonical invocation)

## Gotchas

- **8 commits ahead of `origin/main`** (chumicro) + **1 ahead** (workspace-template) — neither pushed. The user pushes manually when ready.
- **`projects/two_board_test/client/{app.py,README.md}`** in the workspace-template has my untracked rename edits sitting in an untracked directory. User said the project may be temporary; the edits ride along if they commit, vanish cleanly if they `rm -rf` it.  Point-in-time as of write — re-verify on resume.
- **The on-device functional run for `test_real_serve.py`** failed on both Pi Pico W boards (MP timeout, CP ECONNABORTED) — *not* a regression from this session's rename; it's the hairpinning issue Decision 0083 now formally owns. Don't retry the test expecting it to pass until Phase 2 of the test-harness workstream rewrites it to Category 1 (host-driver-as-client).
- **Decisions 0082 and 0083 themselves lack `Summary:` fields** — they were written before the field was required. They ride the Phase 2 backfill (so 71 total = 69 older + 0082 + 0083).
- **The `Summary` field's verify checklist gate** says "≤200 chars, no line wraps, machine-extractable" — this is what the CHU lint (Phase 3) will enforce. Don't write multi-line Summaries.
- **4 boards plugged in as of write** — 2 MicroPython (`pi-pico-w-micropython-board`, `lolin-s2-micropython-board`), 2 CircuitPython (`pi-pico-w-circuitpython-board`, `lolin-s2-circuitpython-board`). Re-probe with `chumicro-workspace devices` on resume — point-in-time.
