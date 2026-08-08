# Audit remediation + drift mechanization

A 16-agent adversarial sweep (2026-05-16, full tracked-file coverage,
prosecutor/defender/research/security mandates) confirmed — across
independent agents and hand-verification — a structural pattern, not
just a defect list.  Fuller backing notes in the working report
(`.scratch/deep-audit-2026-05-16.md`, gitignored); the load-bearing
content is inlined below so this file stands alone.

## The meta-finding (drives the shape of this workstream)

Every code rule **mechanized by a CHU lint** held at 0 violations across
all ~16 K LOC of library source (no `typing`, no `async`, no relative
imports, no `__slots__`, runner-shape, no long sleeps).  Every contract
guarded **only by the AGENTS.md "docs in lockstep" prose rule** drifted
and shipped wrong: a security-relevant false TLS docstring (3 agents +
verified vs MP 1.26 C source), the flagship README example that crashes
on MicroPython, a "future work" docstring for fully-shipped features, 5
phantom CLI commands documented + 5 real ones hidden, a wrong NTP socket
contract, a coverage claim the measurement doesn't support, and a CI
lint job that can't run the CHU rules at all.

Conclusion: **mechanized rules work; prose-maintained lockstep does
not** — because lockstep depends on agent diligence, the exact thing the
project mechanized *code* rules to stop depending on.  Fixing the
defects without mechanizing the checks repeats the failure.  Hence
Phase 4 (mechanize the drift class) is the load-bearing phase, not the
cleanup tail.

## The embedded-cost gate (load-bearing constraint — Phases 1–2 only)

Phases 1–2 touch `libraries/*/src/`, which runs on 256 KB-RAM / 2 MB-flash (~800 KB usable)
boards under MicroPython and CircuitPython.  **A complete fix that costs
100 lines of complex parsing can be the wrong fix** — flash, import-time
RAM, hot-path CPU, and heap fragmentation on a non-compacting GC are
real budgets, and most chumicro devices are LAN/leaf nodes, not
internet-exposed.  Every Phase 1–2 fix states, in its commit body and
the item below:

- **(a) cost** — flash / import RAM / hot-path CPU / fragmentation
- **(b) realistic threat model** — for this device class.  The genuinely
  exposed surface is `http_server` / `websockets` run as a server;
  `msgpack`'s real risk is **power-loss flash corruption**, not a
  network attacker (the persisted-config path, not an untrusted socket)
- **(c) the cheapest fix that closes the realistic threat**
- **(d) the documented residual** if "mostly" fixed

Rules of thumb, in priority order:

1. **Push integrity to the cheaper layer.**  A CRC frame is far cheaper
   than a validating parser *and* catches bit-flips a parser can't.
2. **Reject-and-document beats implement-the-feature.**  Unsupported
   framing → explicit error, never silent mis-handling.
3. **Don't fight an ADR's rationale to "complete" a fix.**  (E.g. ADR
   0014's no-per-tick-allocation rationale: a guard, not a deferred-ops
   queue.)
4. A deliberately weaker outcome is acceptable **only** when the threat
   is low *and* the complete fix is disproportionately costly *and* the
   residual is written down (not hidden).

Phases 0, 3, 4 are host-side tooling or prose — **no flash budget**;
take the complete fix there.

---

## Phase 0 — Decide before coding — RESOLVED 2026-05-17

Three findings were structural decisions, not bugs.  All three resolved:

1. **msgpack decode trust boundary** → **[Decision 0073](../../decisions/0073-msgpack-decode-trust-boundary.md)**
   (accepted).  `unpackb` is a *trusting* decoder, hardened with
   ~15–20 cheap lines against truncation / over-length /
   trailing-garbage / unbounded recursion; **not** a spec validator.
   The audit's "CRC on every backend" is **not adopted** — Decision
   0034's per-substrate model (CRC only on raw-flash CP-NVM; NVS
   atomic-commit + LittleFS atomic-rename close torn-write) is
   confirmed, not amended.  → Phase 1 item 1 narrows to the decoder
   hardening only; no `_backends/` change.
2. **Coverage-gate honesty** → **correct the ADRs + document residual**.
   [Decision 0009](../../decisions/0009-per-library-test-runs.md) and
   [Decision 0025](../../decisions/0025-dual-coverage-thresholds.md) edited
   in place: per-library gating fires only when `--coverage-threshold`
   is passed (bare CI `test --all` = post-`combine` repo-wide 85 %
   aggregate, no per-library `pyproject.toml` coverage config); 94 % is
   a CPython-reachable, post-`# pragma` figure with no device-execution
   signal.  AGENTS.md corrected.  Closing the gap (per-library CI
   threshold + a device-adapter coverage signal) stays as Phase 1
   item 2 — the ADRs now make the scope honest, they do not claim it
   closed.
3. **Prose-lockstep → mechanization principle** → **[Decision 0074](../../decisions/0074-drift-mechanization-as-project-policy.md)**
   (accepted): a drift class that *can* be deterministically linted
   *must* be.  Charters Phase 4; AGENTS.md "docs in lockstep" rule
   reframed as the backstop for the un-mechanizable remainder.

## Phase 1 — Stop-the-bleeding (Critical / enforcement-not-running)

1. **msgpack decode hardening** (`libraries/msgpack/src/chumicro_msgpack/_pure.py`) — **DONE 2026-05-17**.
   - Landed: `_bounded_end` length-vs-remaining guard on the 5 silent
     slice reads (fixstr/str8/str16/bin8/bin16), a one-byte-per-element
     container-length sanity in `_decode_array`/`_decode_map`, a
     `depth` int threaded through the recursive core (**`_MAX_DEPTH = 8`,
     bench-set not analytical**: the first guess of 32 was 2x too high
     — Pico W under MicroPython faults `pystack exhausted` at 17 nested
     containers / survives 16, so a guard at 32 was never reachable; 8
     fires ~18 frames deep, under the measured ~32-frame ceiling, still
     2x realistic config/kvstore nesting of 2–4), and a
     top-level-only trailing-bytes reject in `unpackb`.  `struct`
     reads left unwrapped — MP/CP `struct.unpack_from` already raises
     `ValueError("buffer too small")` (verified vs both C sources), so
     wrapping them would be the rejected over-fix.  Validated **4/4**
     on-device (Lolin S2 + Pico W, CP + MP); the depth test failed
     Pico W MP at `_MAX_DEPTH=32` and PASSes on all four at 8.
     11 cross-runtime
     tests; residual documented in the `unpackb` docstring + guide.
   - **Load-bearing caller follow-through (same commit):** hardening
     `unpackb` to *raise* broke two documented contracts that the
     silent-short-read had masked — `kvstore._load` ("construction
     never raises") and `config.load_runtime_config` (documented
     `OSError`/`InvalidConfigType` only).  A truncated persisted file
     would have become an unhandled `ValueError` boot-crash — the exact
     failure the embedded-cost gate warns against.  Fix per gate rule
     2 (route into the existing reject channel, no new machinery):
     `_load` → `is_corrupt=True`/empty, `reload` → `KVStoreCorrupt`,
     `load_runtime_config` → `InvalidConfigType`.  4 caller tests.
     msgpack/kvstore/config VERSIONs bumped lockstep.
   - Threat: realistic risk is **power-loss-truncated persisted flash**
     feeding kvstore/config (`core.py:157,178`, `runtime.py:22`) — a
     network attacker is the rarer case; only CP-NVM has a CRC today.
   - Complete fix **rejected**: full spec-validating decoder, per-type
     checks everywhere (~100 lines + per-decode CPU on the hot path —
     the *wrong* fix here).
   - Chosen (~15–20 lines, per Decision 0073): length-vs-remaining
     check at each length-prefixed read + a recursion-depth int counter
     + reject-trailing-bytes in `unpackb` **top-level only** (not in the
     recursive core).  This closes the decode-garbage-as-valid bug at
     the codec layer on **every** backend.
   - CRC-everywhere **dropped** (Decision 0073 / 0034): the CRC stays
     per-substrate (raw-flash CP-NVM only; NVS + LittleFS are
     substrate-atomic).  No `_backends/` change in this phase.
   - Residual (documented in the library's docs/guide + `unpackb`
     docstring, not only the ADR): `unpackb` is a *trusting* decoder —
     safe against truncation/overrun/depth, **not** a spec validator.
2. **CI lint cannot run the CHU rules** — `.github/workflows/ci.yml`
   lint job installs only `ruff`; `scripts/run.py:498` (`run.py lint`)
   calls `python -m chumicro_checks`, never installed on that runner.
   Either CI lint is red every push (private, direct-to-main →
   unnoticed) or the "load-bearing" CHU enforcement never runs in CI.
   Host-side — complete fix: install checks (or `run.py setup`) in the
   lint job, or split CHU into its own job.  Verify against a real CI
   run log first (confirms which branch is true).
3. **`release.yml` uncoupled from CI-green** — `release.yml:99`
   `needs: detect` only; a VERSION bump on main publishes to *immutable*
   PyPI independent of ci.yml status, before the in-job `validate-mip`.
   Host-side — complete fix: gate publish on CI success or move publish
   after `validate-mip`.

**Items 2–3 re-homed (2026-05-18).**  Both are CI-infrastructure
defects, not audit-remediation tail, and the CI surface has more wrong
with it than this audit surfaced.  They are handed off to a future
dedicated CI workstream rather than carried here — analysis above is
preserved as the starting brief for that workstream.  This workstream
no longer tracks them.

## Phase 2 — Confirmed High correctness defects (embedded-aware) — DONE 2026-05-18 (`42d5bbd1`)

All six items landed in `42d5bbd1` with tests + lockstep VERSION bumps:
http_server `Transfer-Encoding` → 400; requests CRLF reject in
method/path/headers; NTP era-1 lift; ws/mqtt liveness (`MQTTProtocolError`
on malformed framing, websockets drain rework); runner `_ticking`
re-entrancy guard; CHU009 widened (Decision 0058 updated in lockstep).
Verified against current source 2026-05-18.


| Item | Complete fix (rejected) | Chosen (cheap) fix | Residual |
|---|---|---|---|
| **http_server `Transfer-Encoding`** (`_wire.py:558`) — smuggling: silently mis-framed as zero-length | implement chunked request decode (complex, allocating) | ~3 lines: any `Transfer-Encoding` header → 400 | chunked request bodies unsupported (documented, not silently mis-framed) |
| **requests CRLF injection** (`_wire.py:456`) | — | ~2 lines: reject `\r`/`\n`/`\0` in method/path/header name+value | none (complete == cheap) |
| **NTP 2036 era** (`ntp/core.py:89`) | full RFC era-disambiguation (needs current-date ref → circular with no boot RTC) | ~2 lines: `if seconds_1900 < NTP_TO_UNIX: seconds_1900 += 2**32` | hard 2104 bound (documented) |
| **ws/mqtt liveness** (`websockets/_wire.py:710`, `mqtt/_wire.py:114,655`) | full flow-control rework | ~3–6 lines: no-progress / max-fragment int counter; distinguish `decode_varlen`'s two zero-returns via sentinel; `MQTTProtocolError` (not `struct.error`) on `remaining_length<2` | none meaningful |
| **runner re-entrancy** (`runner/core.py:198`) | deferred-ops queue (more code + per-tick alloc — fights ADR 0014) | ~3 lines: `if self._ticking: raise RuntimeError(...)` guard, zero per-tick alloc | re-entrant `tick()` from a handler forbidden + documented (preserves ADR 0014 rationale) |
| **CHU009 widening** (`workbench/checks/.../chu009_chu010.py`) | — | host-side, no flash budget — complete fix: flag `Return`/`Pass` as last stmt of any `if` body + bare top-of-body early return; contradicts Decision 0058's "can't come back" claim until done | none |

Deliberately-weaker, by the gate's rule 4: **NTP source-address spoof
check** (`ntp/core.py:316`) — best-effort host compare where the runtime
makes `recvfrom` address format reliable, skipped where not; low threat
for a LAN leaf, high cross-runtime cost.  Residual stated; lean on the
existing plausibility-window sanity check.

## Phase 3 — Docs-vs-code drift cleanup (host/prose) — DONE 2026-05-18

Every item re-verified against current source before editing (one was
already false — see below).  Docstring-only library edits do not bump
VERSION (project precedent `239217ed`: VERSION tracks behavior, not doc
corrections).

- ✅ False MP TLS docstring (`sockets/_adapters/mp.py`) — verified false
  against pinned MP v1.26.0 `extmod/modtls_mbedtls.c:319-324`
  (`MBEDTLS_SSL_IS_CLIENT` → `VERIFY_REQUIRED`).  Rewritten: client
  default is `CERT_REQUIRED`, this helper explicitly downgrades.
- ✅ requests `client.py` — "future work" docstring rewritten to the
  shipped surface; all five (GET/POST/PUT/PATCH/DELETE, JSON, TLS via
  `https://`, capped redirects, chunked response decode) confirmed
  shipped in `client.py` / `_wire.py`.
- ✅ NTP socket-contract docstring (`ntp/core.py`) + guide contract
  table — `recvfrom` → `recvfrom_into`, matching the real call at
  `core.py:321`.  Guide stdlib example unchanged (CPython socket has
  `recvfrom_into`).
- ❌ **README "crashing on MP" — FALSE audit finding.**  `WifiAdapter`
  base has defined `radio = None` since `ff6f1ec1` (2026-04-28,
  *predating* the 2026-05-16 audit), so `wifi.adapter.radio` returns
  `None` on MP and `HttpClient.from_config(radio=None)` is the valid MP
  path — no AttributeError.  The runtime-neutral accessor the audit
  asked to create already exists.  No change made; recorded so the
  finding isn't relitigated.
- ✅ workspace stub-tier docstring + README — zero `NotImplementedError`
  stubs remain in `cli/*.py`; docstring rewritten to point at `--help`
  as source of truth (drift-resistant, no enumerated list to rot).
  README phantom "Stubs" row (`sim/env/use/sync/upgrade` — all verified
  unregistered) deleted; the 5 hidden real commands (`config-validate`,
  `deploy-example`, `install-libraries`, `library`, `reset-board`)
  added to the table.
- ✅ ADR 0051 async-rejection paragraph rewritten.  Per user steer: the
  gripe was never asyncio *support* (the docs never claimed one) — it
  is shape.  Now rests on (1) transparency, aligned with the existing
  README / `chumicro-runner` README framing, and (2) a concrete
  embedded defect — MP asyncio still blocks on `getaddrinfo`, so the
  non-blocking guarantee doesn't survive its socket layer without the
  runner machinery anyway.

## Phase 4 — Mechanize the drift (the load-bearing structural fix)

New CHU-style checks in `workbench/checks/` so Phase 3's class can't
recur (host-side — no flash budget).  One lint per commit; each ships
the `# noqa: CHU0NN` + one-line-why escape valve.

- ✅ **CHU014** doc-command↔registered-subcommand parity — DONE
  2026-05-18.  AST-extracts `subparsers.add_parser("name")` (receiver
  typed `argparse._SubParsersAction`; nested `verbs.add_parser` for
  sub-verbs excluded) vs the README `| Group | Commands |` table's
  command-shaped backtick tokens.  Flags phantom (documented, not
  registered) + hidden (registered, not documented).  Found + fixed a
  real GFM bug while validating against the live repo: cells contain
  escaped pipes (`list\|add\|…`) that a naive `split("|")` shreds —
  the rule splits on unescaped pipe only (regression test).  0
  findings on current main (validates the Phase 3 README fix was
  complete).  README rule catalog brought current (was stale at
  CHU012; CHU002–005/013/014 added).  `workbench/checks` 0.4.1→0.5.0.
- ✅ **CHU015** module-docstring "future work" claims vs shipped
  symbols — DONE 2026-05-18.  Module docstring split into clauses on
  `.`/`;`/blank; a clause with a not-yet predicate (`future work`,
  `not yet implemented`, `planned`, `TODO`, `unimplemented`, `is a
  stub`, `will be added/…`) is matched whole-word against the
  module's public top-level def/class names + public methods.
  Clause-scoping is the false-positive guard (`entry point; … is
  planned` doesn't flag the entry-point symbol).  Catches the
  `chumicro_requests.client` "TLS/POST/JSON/redirects … future work"
  class.  0 findings on main (validates the Phase 3 requests fix).
  `workbench/checks` 0.5.0→0.6.0.
- ✅ **CHU016** example imports resolve on every declared runtime —
  DONE 2026-05-18.  Closes the gap `verify_examples` leaves: it skips
  every platform built-in for hardware-marked files, so a dual-runtime
  example with an unguarded module-top-level `import board` (CP-only)
  passes that gate then crashes on MicroPython.  CHU016 flags a
  module-body-level import of a runtime-exclusive module when
  `__chumicro_runtimes__` also declares the runtime it's absent on;
  guarded (`if sys.implementation.name == …`), function-local, and
  `try`-wrapped imports are module-body-*nested* and not flagged, so
  the established correct pattern passes.  Conservative CP-only / MP-
  only module sets.  0 findings on main (validates the examples are
  correctly guarded).  `workbench/checks` 0.6.0→0.7.0.
- ✅ **CHU017** coverage-claim honesty — DONE 2026-05-18.
  Tractability was assessed before building (Decision 0074 flagged it
  judgement-adjacent) and found **tractable, not deferred**: the
  *prohibited* set is closed (affirmative codebase-extent scope
  phrases — `shipped code`, `the codebase`, `all code`, `every line`,
  `fully covered`, …) and the false-positive exemption is mechanical
  (a sentence carrying a negator or an honest-scope qualifier —
  `not`, `CPython-reachable`, `post-exclusion`, `device-execution`,
  `reachable`, `aggregate`, the meta "must carry this scope" framing
  — is the corrected/meta statement, not drift).  Validated against
  the live corrected text: the AGENTS.md and ADR-0025 sentences that
  *state* the honest contract are correctly **not** flagged; a
  synthetic whole-codebase overclaim **is**.  Scope:
  `AGENTS.md` + `docs/` + `plans/decisions/` (where the contract and
  its claims live; the churny next-up/workstreams ledger excluded).
  0 findings on main.  `workbench/checks` 0.7.0→0.8.0.

## Explicitly NOT in this workstream

- The prosecution's governance-mass reductions (`open-questions.md` /
  `patterns.md` pruning, 7 audit-skill consolidation, the 26 ADRs over
  the project's own brevity cap) — a separate owner/decision, not
  remediation.
- ~3 trivial papercuts better as standalone `next-up.md` bullets: the
  `mike` two-SHA pin (`requirements-dev.txt:30` vs
  `requirements-docs.txt:5`), unpinned third-party GitHub Actions in
  OIDC/secret jobs, the `_noqa` fail-open matcher.

## Sequence

Phase 0 (decisions) → Phase 1 (msgpack + CI-lint + release-gate, the
stop-the-bleeding set; item 1 waits on Phase 0 item 1) → Phase 2
(High correctness; independent items, parallelizable) → Phase 3 (docs
drift) → Phase 4 (mechanization; coverage-honesty lint waits on Phase 0
item 2).  Phase 3 and Phase 4 can overlap once Phase 0 lands.

## Status

Opened 2026-05-16.  **Phase 0 RESOLVED 2026-05-17** — Decision 0073
(msgpack trusting decoder, per-substrate CRC confirmed), Decisions
0009 + 0025 corrected in place (coverage honesty) + AGENTS.md, Decision
0074 (drift-mechanization as policy, charters Phase 4).  Open-questions
threads deleted.  **Phase 1 item 1 DONE 2026-05-17** — msgpack decoder
hardened decoder-only + the load-bearing kvstore/config caller
follow-through (see Phase 1 item 1 above); preflight green, 4/4 runtime
matrix not yet bench-run (CPython + MP/CP unix-port green).  Phase 1
items 2–3 (CI-lint CHU gap, release-not-gated-on-CI) **deferred by the
user — CI is disabled; revisit when CI is re-enabled.**  **Phase 2 DONE
2026-05-17 (`42d5bbd1`)** — all six correctness defects landed (recorded
late; the ship commit predated this Status update).  **Phase 3 DONE
2026-05-18** — five real docs-vs-code fixes (sockets TLS docstring,
requests future-work docstring, NTP recvfrom_into, workspace stub-tier
docstring + README, ADR 0051 async paragraph); the sixth ("README
crashes on MP") was re-verified as a **false audit finding** (base-class
`radio = None` predated the audit) and recorded, not actioned.
**Phase 4 DONE 2026-05-18** — the load-bearing phase per Decision 0074:
four lints shipped one per commit, CHU014 (command-table parity,
`487d2216`) / CHU015 (docstring capability vs shipped symbols,
`d7c75139`) / CHU016 (example imports per declared runtime, `d5ec8487`)
/ CHU017 (coverage-claim honesty, this commit).  Each reports 0 on main
— every defect Phase 3 hand-fixed is now mechanically guarded against
recurrence, and CHU014's live-repo validation surfaced + fixed a real
GFM-parsing bug in the bargain.  `workbench/checks` 0.4.1→0.8.0.

**Workstream COMPLETE 2026-05-18.**  Phases 0–4 and the embedded-cost
gate are closed.  Phase 1 items 2–3 (CI-lint CHU gap,
release-not-gated-on-CI) are **re-homed to a future dedicated CI
workstream** — they are CI-infrastructure defects with more wrong
around them than this audit surfaced, and can't be validated with CI
disabled; the analysis in the Phase 1 section is preserved as that
workstream's starting brief.  Nothing further is tracked here.
