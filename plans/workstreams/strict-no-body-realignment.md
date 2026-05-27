# Strict-no-body docstring rule: codification + audit-comments realignment + body-slim sweep

Status: queued

Surfaced 2026-05-26 by the audit-comments retrofit-test run on kvstore (commit `2356830e`).  The new verifier-blind dispatch surfaced ~30 CRITICAL body-paragraph violations in `libraries/kvstore/src/`.  The auditor (audit-comments dim 4 / dim 6) had judged those bodies as KEEPs under the essay-bloat detector + cold-maintainer test.  The verifier inherited strict no-body rules from the commenter-verifier persona, matching `feedback_no_docstring_bodies.md`: "summary line + Args/Returns/Raises only; flash budget + kills prose-bug surface."

Resolution: strict no-body is canonical.  Auditor needs to align with the verifier, AGENTS.md needs to carry the rule explicitly, and the previously-audited libraries (kvstore + any others with surviving bodies) need a slim pass with content lift to `docs/guide.md` per library before the slim lands.

## Implementation phases

### Phase 1 — Codify in AGENTS.md

Add the rule to AGENTS.md `Code comments` section:
- "No docstring bodies in library code (`libraries/*/src/`, `support/<name>/src/`) — summary line plus optional `Args:` / `Returns:` / `Raises:`, nothing else."
- Rare-body exception (single additional sentence, narrow): only when a load-bearing nuance cannot fold into the summary AND that nuance is non-obvious from code.  Typical earned cases: structural-not-behavioral protocol parameters, multi-attribute side-effects the summary can't list.  No two-sentence bodies, no em-dash continuation, no rationale paragraphs.

Workbench / scripts / tests can still carry bodies — the rule is library-code-scoped.

### Phase 2 — Realign /audit-comments dimensions

Update `.github/skills/audit-comments/SKILL.md`:
- Dim 4 (Signal-to-noise) "Essay-bloat" bullet: drop the "calibrate before cutting" KEEP carve-outs that allowed Protocol method bodies, `@abstractmethod` stubs, destructive-API `Args:` blocks to legitimately run long.  Long Args blocks stay; multi-sentence prose bodies don't.
- Dim 6 (Top-to-bottom readability via /audit-library cross-reference) "essay-bloat" bullet: drop the cold-maintainer test as a KEEP gate for bodies in library code — strict no-body wins.
- Pass 2 step 6's four-check evaluation: add a fifth check, "any body paragraph in library `src/` is a REWRITE candidate by rule, not by cold-reader test."

The audit-comments-verifier persona is already aligned — no persona change needed, only auditor dimensions.

### Phase 3 — Re-run audit on kvstore to validate the realigned procedure

`/audit-comments libraries/kvstore` after Phase 2 lands.  Expectation: auditor surfaces what the verifier previously surfaced alone.  If the auditor's REWRITE proposals match the verifier's CRITICAL findings ≥ 80%, the realignment is working.  If gaps persist, dim updates need a second iteration.

### Phase 4 — Body-slim sweep with doc-lift

For each library with surviving bodies in `src/`, before slimming:
1. Identify body content carrying load-bearing why (wire-format tables, atomic-rename rationale, single-blob design choice, lazy-import flash-budget rationale, etc.).
2. Lift that content to the library's `docs/guide.md` (the named home for user-facing prose per AGENTS.md).
3. Slim the docstring to summary + Args/Returns/Raises only.
4. Run preflight + `check-api` + (for I/O libraries) real-board verification.
5. Bump VERSION patch-level per AGENTS.md.

Library order: start with `kvstore` (verifier-surfaced findings already enumerated in commit `2356830e` message).  Then sweep the rest based on grep — `git grep -l '^[[:space:]]*"""' libraries/*/src/*.py | xargs -I{} sh -c 'wc -l {} | awk "{print \$1, \$2}"'` to identify candidates by docstring line-count outliers.

Likely candidates per quick scan: `chumicro_runner`, `chumicro_mqtt`, `chumicro_sockets`, `chumicro_websockets`, `chumicro_requests`, `chumicro_http_server`.  Recently /regen-comments'd libraries (`chumicro_timing 0.4.4`, `chumicro_events 0.2.4`) should be recheck targets — the writer persona allows rare-body exceptions; verify the existing bodies actually meet the strict bar.

## Validation history

- 2026-05-26: surfaced via kvstore retrofit-test; resolution recorded (strict no-body canonical), workstream queued.

## Open questions

- Does the strict no-body rule apply equally to `__init__.py` module docstrings (which historically teach what the library is + Public API examples)?  Or do module docstrings earn a special carve-out for user-facing landing-page text?  Phase 1 needs to decide; if module docstrings get a carve-out, audit-comments dim 4 needs to know.
- Once kvstore's bodies lift to `docs/guide.md`, does the README also need a touch-up?  Guide content sometimes mirrors README content; deduplication may surface.
- Workbench packages: rule scope says library-code only.  Workbench `src/` follows different conventions per AGENTS.md.  Confirm before phase 2 widens the audit-comments rule application.
