# Handoff 2026-05-28 — comment-generation experiment: round-11 results + pivot to "fixing"

## What this session was about

Ongoing experiment to make an AI agent write *good* code comments for ChuMicro libraries — a recurring failure mode. The bench strips a library's comments and dispatches many "commenter" persona variants in parallel (3 runs each) against the stripped baseline; a separate analysis session judges which persona writes best. This session: (a) converted the round-11 dispatch to the new `Workflow` tool, (b) added 6 new "parse-legibility" personas, (c) ran round 11 (63 dispatches), (d) analyzed results with the user, (e) discovered that cold-writing structurally loses facts, (f) **pivoted the whole approach** from cold-writing to "fixing," and (g) shipped a real library fix (timing 0.4.5).

The experiment lives entirely under `.scratch/regen-comments/experiment/` (gitignored) except for the durable findings (memory + the timing restore).

## What got done

- **Round-11 dispatch converted to `Workflow`** — `[VERIFIED: file exists]` `.scratch/regen-comments/experiment/round-11/round-11-workflow.js` fans out all dispatches via `parallel()`; the old six-batch hand-dispatch protocol in `RUN.md` is gone. Runner auto-throttles concurrency, so no manual batch cap.
- **6 new personas added** (parse-legibility axis): `commenter-p1-forwardpass`, `p2-rereadtest`, `p3-givennew`, `p4-imitate`, `p5-bans`, `p6-context`. Folded into round 11 → 21 strategies × 3 = 63 dispatches. `[VERIFIED]` all domain-blind (grep for timing/mqtt vocab came back clean).
- **Round 11 ran** — `[VERIFIED: user reported]` 63/63 returned, 252 output files. Output in `.scratch/.../round-11/{w,p}*/run-{1,2,3}/`.
- **`generate_table.py` extended** to 21 strategies; regenerated `.scratch/.../round-11/table.md` `[VERIFIED: ran it, exit 0, 1331 lines]`.
- **timing 0.4.5 restore shipped** — `[VERIFIED: commit 13a4a927, pushed]` restored facts the 0.4.4 cold-write rewrite had deleted (details below).
- **`s2-2pass` deleted along with the other round-8 `s*` agents** — `[VERIFIED]` user said "those agents can go"; `s2` had been leaking timing gold verbatim.
- **Round-11 agents archived** — `[VERIFIED]` all 21 `commenter-w*`/`p*` moved to `.scratch/regen-comments/agents-archive/round-11/`. `.claude/agents/` now holds only infra agents (judge, verifier, casual-friendly, examples, tests, effort-*). Note: `.claude/agents/` is **not git-tracked** — archiving was a plain `mv`, no git impact.
- **mqtt baseline + round-12 structure created** — `.scratch/.../round-12/timing/baseline/` (4 files) and `round-12/mqtt/baseline/` (5 files, stripped from `chumicro_mqtt` via `scripts/strip_comments.py`). Also `round-11/rich-input/` = recovered pre-cold-write timing comments (see Dead ends — partly obviated by the pivot).
- **Two memory files written** (user-specific, `~/.claude/projects/.../memory/`): `feedback_comment_voice_target.md`, `project_cold_write_loses_facts.md`.

## The core finding: cold-writing structurally loses facts

`[VERIFIED: git log -S]` `chumicro_timing/ticks.py` once documented that values wrap every ~6.2 days (`2**29` ms) and that `ticks_diff` is only correct for intervals under ~3.1 days (`2**28` ms, its ±half-period). Commit **`d139e882`** ("chumicro_timing 0.4.4: docstring rewrite via commenter-casual-friendly persona") deleted both. The production cold-writer persona itself destroyed correctness-critical contract — because an agent writing from *stripped* code cannot preserve a fact it can't see, and won't reliably re-derive a non-obvious one (`2**28` ms → 3.1 days).

**User's important correction** (do not over-rotate on fact-loss): most `audit-comments` trims across the repo were *correct* — they removed workstream pointers, session data, cross-library refs, and essay-length rationale, all of which AGENTS.md bans in comments. True non-derivable fact loss is **rare** (timing's 3.1-day limit is the standout). The widespread damage is **readability**: compaction overshot from too-verbose-essay past clear-and-concise into terse-but-hard-to-read. **Do not build a "facts database" from git history.** Facts are mostly still present in current comments, just soupy.

## The pivot: "fixing" not "cold writing"

`[DECISION — user, this session]` The whole paradigm is under question. Cold-writing (strip → write fresh, blind to original prose) has a structural flaw, not a tuning flaw. The alternative: **fixing** — the agent reads the *existing* comment for its **facts**, but must produce **fresh prose** (a full rewrite, never a trim). Blind to the old phrasing's *style*, not to its *content*. This avoids both failure modes: cold-write loses facts; lazy in-place edit keeps the soup.

This is a **third mode**, distinct from the two existing skills: `/regen-comments` cold-strips; `/audit-comments` rewrites from a fresh *code* read. Neither reads the existing comment as the fact-source.

## Round-11 results + the user's verdicts

Mechanical scoreboard was useless: **0/21 gold matches** (exact and fuzzy) — gold is one exact phrasing; the user judges on voice/quality. The read is everything. My per-symbol analysis (gold symbols only: heartbeat module, `Heartbeat.poll`, `Heartbeat.reset`, `ticks_ms`) found systemic failures — but the user's holistic per-agent verdicts are the ground truth:

| Persona | User verdict |
|---|---|
| W1 adafruit | Solid voice (warmth + tech); unhappy with the opener |
| W2 whiteboard | No |
| W3 use-case-led | Good idea but adafruit did it better |
| W4 strict | Too AI; technically correct but flow issues |
| W5 intent | Decent voice (like adafruit, less warm); some AI. Also skipped the heartbeat module docstring all 3 runs |
| W6 mental-model | Better voice than intent; no AI problems (first line) — but runs a body, concern |
| W7 capability | Too comma-heavy; not their style |
| **W8 lax-when** | **#3** — pretty good, more original, generalizes better |
| W9 adafruit+structural | Degraded over original adafruit |
| W10 problem-statement | Good but too verbose; also a label-prefix tic ("Reading the clock:") |
| W11 workspace | Not bad, good voice |
| **W12 hemingway** | **#2** — tight voice, not bad otherwise |
| **W13 imitate-adafruit** | **#1** — "a better adafruit than the original" |
| W14 module-led | Too verbose |
| W15 ide-skim | Misuses "runtime" (true but irrelevant to the library) |
| P1 forwardpass | Good attempt; r1 rough, r2/r3 not bad |
| P2 rereadtest | OK but generic voice |
| P3 givennew | Not a fan |
| P4 imitate-single-pass | "Best technical voice so far" |
| P5 bans | Not bad, others better |
| P6 context+parse | Not good relative to others |

**Top 3: W13 (#1) > W12 (#2) > W8 (#3).** Meta-pattern: **imitation wins** — the two imitation personas (W13, P4) topped voice; rule-based and parse-rule personas lost. The parse axis (p1-p6) didn't help: the candidates were already mostly single-pass, so it fixed a non-bottleneck.

## Good-writing principles (my articulation, refined by the user)

The target voice: **warm-but-technically-correct "Adafruit-Learn" register** — friendly but precise, no AI tics, concise (one line, no body), not comma-heavy, not verbose. Reached by **imitation of exemplars**, not rule enumeration. Specific moves:

1. **Single forward pass** — reads left-to-right with no backtracking: subject + verb early, modifiers trail right, never open a sentence with a backward pointer (`it`/`this`/`that`/a bare `the X` referring to a prior sentence). (Necessary but not the bottleneck on timing.)
2. **Effect over mechanism on mutators** — say what the caller gets ("Prime the next heartbeat to fire after `period_ms`"), not the internal mutation ("Marks `now_ms` as the last beat" / "Anchors the next beat window to `now_ms`" — the user called this "mostly wrong").
3. **Code's own noun, no paraphrase** — `tick`, not "reading"/"count"/"clock"/"time in milliseconds".
4. **A literal that IS the contract stays; a token that substitutes for a named concept goes.** `[0, TICKS_MAX]` / `2**29` on a wrapping counter is *vital* (the wrap point a caller must respect) — **not** a leak. `MAX_RETRIES` → "retry budget" *is* a substitutable token. `[USER OVERRULED my initial "token-leak" flag here — important.]`
5. **No coined-noun class labels** — "Periodic-interval poller", "Fixed-period beat detector".
6. **Recurrence reads as "every X"**, not "once per X window".
7. **No docstring bodies** (per AGENTS.md / chumicro rule) — facts go in the summary line or in `Args`/`Returns`/`Raises`, which may wrap across lines.

## Plans for round 12 (the fixing bench)

`[HYPOTHESIS — not built yet]`

- **Input:** a library's *current* (over-compressed, soupy) comments + its code. NOT recovered historical comments (no git archaeology — see the user correction).
- **Fixing personas (build ~3):** (a) imitate-adafruit voice + preserve-every-fact, (b) fact-first (extract facts, then rewrite around them), (c) conservative prose-only control. Hard rule: *you may rewrite the sentence, you may not drop the fact* — the inverse of what killed `d139e882`.
- **Control:** cold-write `W13` (copy back from the archive at `.scratch/regen-comments/agents-archive/round-11/commenter-w13-imitate-adafruit.md`).
- **Test libraries:** mqtt + runner and/or sockets — heavily-audited, genuinely soupy *current* comments. Timing is a poor test (its current comments are already terse).
- **Judge on:** fact-preservation, voice, conciseness (de-souped without dropping facts).
- **Restart required** so any new fixing personas load into the `agentType` registry.

`[HYPOTHESIS]` the earlier "round 12 = 21 cold-writers × 2 libraries full-factorial" plan is **superseded** by the fixing bench. The `round-12/{timing,mqtt}/baseline/` cold-write substrate may not be needed if we commit to fixing; revisit before building.

## The timing 0.4.5 restore (what shipped)

`[VERIFIED: commit 13a4a927]` Restored in `ticks.py`, line-limit-compliant: the ~6.2-day wrap period + big-int rationale on `TICKS_PERIOD`; `ticks_diff`'s ~3.1-day max interval + aliasing (in a wrapped `Returns`); `ticks_add`'s OverflowError threshold in human terms; `ticks_ms`'s compare-with-`ticks_diff` guidance; and the verb fix ("Yields" → "Returns"). `__init__`/`heartbeat`/`testing` docstring rewrites from an older uncommitted session rode along (user confirmed safe; voice-only). VERSION 0.4.4 → 0.4.5 (patch). `next-up.md` got a bullet queuing the broader restore across mqtt/websockets/wifi.

## Riskiest assumption

That **fixing beats cold-writing** on the metrics that matter. Cheapest test: build the 3 fixing personas, run on one soupy library (mqtt `client.py`), and check whether the output keeps the facts the existing comment carries *and* reads as well as `W13`'s cold-write. If fixing under-rewrites (anchors on the soupy prose, just trims) it's no better than the audit passes that caused the problem — that's the failure mode to watch.

## To re-research / verify next session

- Confirm which of mqtt / runner / sockets has the soupiest *current* comments — scan `libraries/{mqtt,runner,sockets}/src/` docstrings. `[HYPOTHESIS: mqtt client.py is worst; 5 audit passes]`
- `[VERIFY]` whether the round-12 cold-write baselines (`round-12/{timing,mqtt}/baseline/`) are still wanted, or should be dropped now the approach is fixing-not-cold-write.
- Optional: add `ticks_diff`'s ~3.1-day magnitude to `generate_table.py`'s `GOLD` so future rounds can *score* fact-preservation (the bench currently can't see this failure class).

## Dead ends

- **Git-archaeology recovery of lost facts** — I built `round-11/rich-input/` (recovered `d139e882^` timing comments) and proposed a repo-wide "facts database" mined from history. The user shut this down: true fact-loss is rare, most trims were legitimate, and the input for fixing is the *current* comments, not historical ones. `rich-input/` can stay as reference but isn't the plan.
- **Parse-legibility axis (p1-p6)** — didn't move the needle on timing; candidates were already single-pass. May matter more on mqtt `client.py`'s long methods where left-loading actually happens — worth keeping `p4-imitate` (it tied for best technical voice) but not the rule-based parse personas.
- **Scoring on exact gold-match** — 0/21; meaningless for voice judgment. Don't lead with it.

## How to rebuild context fast

- **Read first:** the two memory files — `feedback_comment_voice_target.md`, `project_cold_write_loses_facts.md`.
- **Experiment root:** `.scratch/regen-comments/experiment/` — `round-11/table.md` (the 21-strategy comparison), `round-11/RUN.md` (workflow-driven dispatch), `round-11/round-11-workflow.js`, `round-11/{w,p}*/run-*/` (252 outputs), `round-12/{timing,mqtt}/baseline/`.
- **Archived personas:** `.scratch/regen-comments/agents-archive/round-11/` (21 files). Copy `W13`/`W12`/`W8` back to `.claude/agents/` + restart to use them as controls.
- **The loss:** `git --no-pager show d139e882 -- libraries/timing/src/chumicro_timing/ticks.py`; `git --no-pager log -S'3.1 days' --follow -- libraries/timing/src/chumicro_timing/ticks.py`.
- **The restore:** `git --no-pager show 13a4a927`.
- **Existing skills to contrast:** `.github/skills/regen-comments/`, `.github/skills/audit-comments/`, persona `.claude/agents/commenter-casual-friendly.md` (the production cold-writer).

## Gotchas

- **Facts-vs-line-limit tension is real.** My first restore draft produced 5 E501s (110-char limit) `[VERIFIED: preflight failed at lint]`. Facts that don't fit a one-line summary go into a wrapped `Returns`/`Raises`. The fixing personas will hit this constantly — they need an explicit "wrap into a section, don't drop the fact" rule.
- **The cold-writer is the production tool AND the culprit.** `commenter-casual-friendly` (`.claude/agents/`) is what `/regen-comments` uses, and it's what deleted timing's facts in `d139e882`. Fixing the experiment ≈ fixing this persona's paradigm.
- **`strip_comments.py` strips deliberately** to avoid prose influence — which is exactly why cold-write can't preserve facts. The fixing approach deliberately does NOT strip.
- **Older-session uncommitted work** landed in `libraries/timing/src/chumicro_timing/{__init__,heartbeat,testing}.py` and `.idea/chumicro.iml` — surfaced to the user, who confirmed the timing ones were safe (committed in 13a4a927); `.idea/.iml` left unstaged. Re-check `git status` on resume for any new parallel-session dirt.
- **`generate_table.py` is hardcoded** (STRATEGIES list, GOLD dict, FILES) and lives in `.scratch` (gitignored). Extended to 21 strategies this session. To add a library/strategy, edit it.
- **Model confound across rounds.** `model: "opus"` now resolves to Opus 4.8; rounds 1–8 ran on 4.7. Within-round comparison is clean; cross-round (e.g. round 8 vs 11) is confounded. `[VERIFY: web]` exact model-version-to-date mapping if it matters.
- **User judges on VOICE first**, per-symbol semantic precision second. Don't present mechanical/grep findings as verdicts — they overruled my `[0, TICKS_MAX]` "token-leak" flag.
