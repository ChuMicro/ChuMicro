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

Phases 1–2 touch `libraries/*/src/`, which runs on 256 KB-RAM / 4 MB-flash
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

## Phase 0 — Decide before coding

Three findings are structural decisions, not bugs.  They become
open-questions entries now (filed 2026-05-16) and resolve into ADR
edits/new ADRs before Phases 1/4 build on them:

1. **msgpack decode trust boundary** — is `unpackb` a validating or a
   trusting decoder, and must every persistence backend carry CRC
   framing?  (Resolution shapes Phase 1 item 1.)
2. **Coverage-gate honesty** — ADR 0009/0025 claim per-library +
   on-device enforcement the measurement doesn't deliver (CI enforces a
   repo-wide aggregate; 94 % is CPython-only with device adapters
   `# pragma: no cover`'d out).  Either fix the gate or correct the
   ADRs.  (Shapes Phase 1 item 2 and Phase 4.)
3. **Prose-lockstep → mechanization principle** — ratify (likely as an
   ADR) that drift classes which can be linted *must* be, mirroring the
   CHU-rule philosophy for code.  (Charters Phase 4.)

## Phase 1 — Stop-the-bleeding (Critical / enforcement-not-running)

1. **msgpack decode hardening** (`libraries/msgpack/src/chumicro_msgpack/_pure.py`).
   - Threat: realistic risk is **power-loss-truncated persisted flash**
     feeding kvstore/config (`core.py:157,178`, `runtime.py:22`) — a
     network attacker is the rarer case; only CP-NVM has a CRC today.
   - Complete fix **rejected**: full spec-validating decoder, per-type
     checks everywhere (~100 lines + per-decode CPU on the hot path —
     the *wrong* fix here).
   - Chosen (~15–20 lines): length-vs-remaining check at each
     length-prefixed read + a recursion-depth int counter +
     reject-trailing-bytes in `unpackb` **top-level only** (not in the
     recursive core).  **Push integrity to the cheap layer**: require
     the CRC frame (already in CP-NVM) on the MP-NVS / LittleFS /
     memory kvstore backends.
   - Residual (documented): `unpackb` is a *trusting* decoder — safe
     against truncation/overrun/depth, **not** a spec validator.
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

## Phase 2 — Confirmed High correctness defects (embedded-aware)

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

## Phase 3 — Docs-vs-code drift cleanup (host/prose — complete fix)

- False MP TLS docstring (`sockets/_adapters/mp.py:536`) — rewrite to
  "client contexts default to VERIFY_REQUIRED; this helper downgrades
  it."  Code at :542 is already correct.
- requests `client.py:22` — rewrite the "future work" docstring to the
  shipped surface (POST/PUT/PATCH/DELETE/JSON/TLS/redirects/chunked).
- NTP socket-contract docstring (`ntp/core.py:160`) — document
  `recvfrom_into`, matching the real call at :316; fix the guide's
  stdlib example.
- README flagship example crashing on MP (`README.md:129,207,211`;
  `ntp/docs/guide.md:37`) — expose a runtime-neutral `wifi.radio`
  accessor on `WifiService`; propagate.  The mqtt guide already shows
  the correct pattern.
- workspace phantom/hidden commands (`cli/__init__.py:10-26`,
  `workspace/README.md:96`) — delete the stub-tier docstring + README
  "Stubs" row; add the 5 real omitted commands to the table.
- Re-ground ADR 0051's "asyncio is partial across the trinity" — stale
  for the project's board tier post CP-asyncio-2025-10; rewrite the
  "Rejected → async" paragraph onto the transparency/debuggability
  argument it actually rests on.

## Phase 4 — Mechanize the drift (the load-bearing structural fix)

New CHU-style checks in `workbench/checks/` so Phase 3's class can't
recur (host-side — no flash budget):

- doc-command-vs-registered-subcommand parity (catches phantom/hidden
  CLI commands)
- module-docstring "future work"/capability claims vs shipped symbols
- example-script imports resolve on every declared runtime (catches the
  README MP-crash class)
- coverage-claim honesty (the ADR 0009/0025 measurement gap, once
  Phase 0 item 2 decides the contract)

Each ships with the `# noqa: CHU0NN` + one-line-why escape valve, per
the existing CHU-rule philosophy.

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

Opened 2026-05-16.  Phase 0 open-questions entries filed (msgpack trust
boundary, coverage-gate honesty, prose-lockstep mechanization).  No code
phase started — proposal awaiting prioritization.
