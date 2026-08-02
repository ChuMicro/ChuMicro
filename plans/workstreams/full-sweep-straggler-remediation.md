# Workstream: full-sweep audit stragglers + un-audited-area coverage

Status: **COMPLETE** (2026-07-03) — both tracks closed; residual items carry their own
next-up bullets (API design pass, runner M49, test-support packaging policy, H37).
Original status detail: Track A fix stage complete: 17-group agent fan-out returned 52 fixed /
8 already-fixed / 5 escalated, all group test lanes green; merged behind one preflight gate with
per-group commits.  **Track B**: area 1 (workspace code) hunted and fixed the same day — the
demo-driver ~10.0 s "marker stall" root-caused to `parse_marker` silently dropping any marker
whose value contains whitespace (the serial-`timeout=10.0` hypothesis was disproven; both
transports stream live) — plus five more findings (W2 destructive marker waits, W3 aliased-import
bypass of the hard-reset brick guard, W4 tar sibling-path escape, W5 non-atomic `secrets.toml`
writes, W6 unreapable stale bootstrap thread), all fixed with tests.  Area 4 (`workbench/checks`)
hunted next, out of listed order, because concurrent fix agents were editing pytest-device.

## Track A — straggler remediation

The 2026-07-02/03 remediation shipped all criticals and ~all highs (135 findings closed across
17 commits, `0cfe5cbb..f1e38cb2`). Remaining: 27 medium + 37 low, plus four tracked follow-ups.
Fix briefs (full finding text + re-verification notes + fix constraints) live outside the repo in
the session scratchpad; results and commits land here.

Execution model: one fix agent per group below; groups touch disjoint file sets so they run in
parallel (requests → sockets chained, because G3 spans both). Every agent re-verifies each finding
against current code before touching it (the audit notes are a day stale), fixes with cross-runtime
tests, bumps its library VERSION once, and does **not** commit. One full preflight gates the merge;
commits land per group, serially, after diff review.

| Group | Items |
|---|---|
| events | L11 L12 |
| config | L2 L3 L4 |
| http_server | M17 M18 M19 L15 L19 L20 |
| logging | L30 L31 L32 L35 L36 L37 |
| mqtt | M33 L39 |
| msgpack | L45 |
| ntp | M41 L52 L53 |
| requests | M44 M47 L56 L57 L60 L61 L62 |
| sockets | M61 L76 + H26-root (CPython TLS adapter SSLWant→EAGAIN) + G3 (deadline through `generators.connect`) |
| runner | M50 M53 L63 L65 L66 |
| timing | L78 |
| websockets | M70 M71 M73 M74 L83 + M44 websockets slice |
| demos | M10 M12 L7 L8 L9 + `sockets_runner_connector` rewrite on `Signal`/`wait_for` (ADR 0091) |
| pytest-device | M82 M83 L88 |
| test-harness | L77 |
| meta/docs | M1 M13 L10 M85 M86 L89 L55 M56 |
| bundle-manager | C7 follow-up (mip/circup channel stages `__chumicro_data_files__`) |

Held out for an API-design pass with the user (escalated by the fan-out or held from the start —
not mechanical fixes):

- **M31** mqtt blocking/pump facade, **M51** runner registration-shape consolidation — both
  reshape public surfaces the demos teach.
- **ntp L52/L53** — relocating `NTPClient.from_config` off the class and deferring its eager
  socket open both change the public construction contract.
- **demos L9** — dropping the `getattr(sock, "sock", sock)` dual-source unwrap in the explicit
  demo is gated on a sockets `io_socket` single-source collapse; relocating that demo to a guide
  appendix is structural.
- **websockets L83 (generalized)** — `testing.py` fakes ship in every pip/circup/mip artifact
  across all 15 libraries; exclusion should key off the `__chumicro_test_support__` marker as a
  workspace-wide packaging policy, not a per-library carve-out.
- **M77** factory-plumbing five-copy divergence and **M28** examples `helpers.py` six-copy drift —
  cross-library refactors; M28 is already
  [examples-helpers-cross-library-drift](examples-helpers-cross-library-drift.md).
- **H37** unix-port heap cap — needs per-library heap budgets (own workstream, unchanged).

Resolved during the merge rather than deferred: **demos L8** (the mqtt driver's
poll-in-20ms-slices workaround) got its root fix — a non-blocking `MarkerQueue.poll` — and the
driver now ticks its host client between polls with no exception-as-control-flow.  The
`requests_fetch` and `websockets_stream` preambles were rewritten on `Signal`/`wait_for` alongside
`sockets_runner_connector` (the fan-out surfaced that the brief's "post-rewrite exemplars" claim
was stale).  Four demos' `payload={payload!r}` markers (whitespace in values — the stall's
demo-side half) now ride as `payload_hex`, and `websockets_stream`'s MESSAGE marker carries
counts with the text as prose.

After merge: dependency graph regenerated (three dead `chumicro-config` deps dropped).  Bakes
complete 2026-07-03: `sockets_runner_connector` green on BOTH Pico W boards (MP + CP; the CP board
needed a reflash to stock 10.2.1 — its custom alpha build wedged flash staging, matching the
tracked bench issue), `requests_fetch` and `websockets_stream` green on Pico W MP.  The
websockets bake caught two real bugs the host lanes could not: the client's inlined `io_socket`
still unwrapped via the non-existent `._sock` (June's five-site fix missed this sixth site;
MP-only because only the MP adapter wraps plain TCP), and the rewritten demo crashed its
generator on text frames (`len(message.data)` with `data=None`) — the death was silent
per deferred M49, which this incident upgrades from nice-to-have to next-in-line.

## Track B — un-audited areas

The full-sweep audit hunted the 15 libraries, demos, packaging, workspace *docs*, and the
harness/deploy seam. Never hunted: the dev-tooling code below. One area at a time: hunter →
adversarial verify → triage → fix → commit, before the next area starts.

1. **DONE** `workbench/workspace` code — 6 findings (W1–W6), all fixed 2026-07-03; report at
   [reviews/2026-07-03-workspace-code-audit.md](../reviews/2026-07-03-workspace-code-audit.md).
   Root-caused the demo-driver ~10.0 s marker stall (whitespace-valued markers silently dropped
   by `parse_marker`, not a serial timeout).
2. **DONE** `workbench/checks` — hunted out of listed order (fix agents were editing
   pytest-device); 21 probe-confirmed findings (K1–K21, five critical false-pass holes in the
   gate rules), all fixed 2026-07-03 with the probes lifted into the unit suite; report at
   [reviews/2026-07-03-checks-rules-audit.md](../reviews/2026-07-03-checks-rules-audit.md).
3. **DONE** `workbench/pytest-device` — 5 findings (P1–P5; core reconcile defenses verified
   sound — crash/OOM/truncation/dropped-FAIL all go red), all fixed 2026-07-03; report at
   [reviews/2026-07-03-pytest-device-audit.md](../reviews/2026-07-03-pytest-device-audit.md).
4. **DONE** `scripts/` — 7 findings (S1–S7; top: circup zips shipped stale/removed modules,
   check_api could baseline against an `-experimental` tag), all fixed 2026-07-03; report at
   [reviews/2026-07-03-scripts-pipeline-audit.md](../reviews/2026-07-03-scripts-pipeline-audit.md).
5. **DONE** `support/test_harness` — 5 findings (T1–T5; top: generator/async-bodied tests
   reported PASS with the body never executed — the one false-green the host reconcile could not
   see; device now FAILs them and the host collector recognizes async defs), all fixed
   2026-07-03; report at
   [reviews/2026-07-03-test-harness-audit.md](../reviews/2026-07-03-test-harness-audit.md).
6. **DONE** `workbench/repl` + 7. `.claude/surfaces/` — combined tail hunt: 5 repl findings (top: TUI
   Ctrl-X wedge against a streaming board; CLI connect now wrapped in the Decision-0053 coaching
   loop) + webui clean bar one escaping nit, all fixed 2026-07-03; report at
   [reviews/2026-07-03-repl-webui-audit.md](../reviews/2026-07-03-repl-webui-audit.md).
