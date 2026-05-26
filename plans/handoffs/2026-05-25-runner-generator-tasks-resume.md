# Handoff 2026-05-25 — re-verify and start runner.add_generator workstream

## What this session was about

User asked for deep research on the newly-proposed `async`/`await` workstream (Decision 0087 as originally accepted 2026-05-25). The research turned up two pieces of evidence that reopened the syntax choice:

1. The yield-point-hygiene argument the original ADR didn't consider (user's framing — `yield from` syntactically enforces that every yield is a deliberate scheduler checkpoint, `async`/`await` invites the "coroutine-without-await" anti-pattern).
2. The "byte-identical" technical claim the original ADR rested on doesn't hold on CircuitPython — CP's `py/compile.c:2790-2796` explicitly diverges from MP and adds a `__await__()` method lookup per `await`, allocating a fresh generator on every call.

The session resolved by amending Decision 0087 in place (per the README's "correction of reasoning that was wrong is an in-place edit" rule) — flipped from `async`/`await` syntax + asyncio-module-only ban to `def` + `yield`/`yield from` + ban on both async syntax *and* the asyncio module. Workstream rewritten in lockstep.

## What got done

- Commit `b434881f` — Decision 0087 amendment + workstream rewrite + cross-link fixes (5 plans-doc files).
  - `plans/decisions/0087-async-await-syntax-without-asyncio-module.md` → `plans/decisions/0087-generators-for-sequential-io.md`
  - `plans/workstreams/async-await-coroutine-service.md` → `plans/workstreams/runner-generator-tasks.md`
  - Cross-link sentences in Decisions 0051 and 0080 updated
  - `plans/next-up.md` bullet swapped
- No implementation work — `chumicro_runner`, `chumicro_sockets`, and `workbench/checks` are untouched.

## What's in flight

Nothing from this session. `.idea/chumicro.iml` has PyCharm-driven drift in the working tree (stripped leading XML comment + added a `.scratch/fresh-clone-test/chumicro/.venv` exclude) — not from this work, left uncommitted intentionally.

## Pickup intent

Per AGENTS.md "a `plans/workstreams/<name>.md` file you're picking up is a directive, not a research artifact. Execute the next unshipped phase." The next phase is Phase 1 — wait-token vocabulary in `chumicro_runner`.

Before executing, re-verify the workstream against current code (per AGENTS.md "sub-agent reports and session handoffs describe intent, not state. Never build on a concrete claim from a … `plans/handoffs/` file without re-deriving"). Specifically:

- Read `libraries/runner/src/chumicro_runner/core.py` end-to-end to confirm the `_GeneratorWrapper` integrates cleanly with the existing `TaskHandle` machinery — the workstream's pseudo-code (Phase 2) was written from one read of `core.py:111-353` and the duck-typed `io_socket` / `io_wants_read` / `io_wants_write` / `io_error` / `next_deadline` contract. Re-check that re-entrancy via `_ticking` doesn't bite when the wrapper's `_advance` raises StopIteration mid-tick. [VERIFY]
- Confirm the wait-tokens land in a new private module (workstream says private, re-exported at package root) without breaking the existing `chumicro_runner` import surface. Read `libraries/runner/src/chumicro_runner/__init__.py`. [VERIFY]
- Confirm `runner.add_generator` name doesn't collide with anything in `core.py`'s public surface. `grep -n "def add" libraries/runner/src/chumicro_runner/core.py` is the check.

## Riskiest assumption

**The wait-token cache-outside-the-loop pattern actually achieves zero steady-state allocation under tracemalloc on MP and CP.** [HYPOTHESIS: cheapest test = write a fake-sock pytest that runs `recv_until` through 1000 EAGAIN polls with `gc.disable(); start = gc.mem_alloc(); …; assert gc.mem_alloc() - start < 64` bracketing the loop. Run it on CPython first, then on MP/CP via `python scripts/run.py test-all-runtimes --libraries sockets`.]

If this fails on CP, the whole "generators avoid CP's per-await allocation" argument in the ADR's *Why generators, not async/await* §3 still holds (the savings vs. `await` are real), but the steady-state-zero claim in the workstream's Phase 3 contract would need softening. The decision survives either way; the workstream's tracemalloc test would just gate at a higher threshold.

## What was learned

- **MP and CP compile `await` differently.** MP `py/compile.c:2768-2780` does `evaluate; YIELD_FROM`. CP `py/compile.c:2790-2796` does `load_method __await__; call; YIELD_FROM` with an in-source `// CIRCUITPY-CHANGE: Use __await__ instead of yield from.` comment. This is the load-bearing technical finding the whole flip rests on. [VERIFIED: read both files]
- **`MICROPY_PY_ASYNC_AWAIT` and `MICROPY_PY_ASYNCIO` are independent firmware flags** on both MP 1.26.0 and CP 10.2.0 — async syntax is at `CORE_FEATURES`, asyncio module is at `EXTRA_FEATURES`. So banning the module while permitting the keywords is firmware-supported. (Now moot since we banned both, but verifies the *original* ADR's foundational claim was technically sound.) [VERIFIED: `grep -nE 'MICROPY_PY_ASYNC_AWAIT|MICROPY_PY_ASYNCIO' .tools/{micropython,circuitpython}*/py/mpconfig.h`]
- **MP 1.26.0 has no separate `mp_type_coro_instance`** — both `async def` and generator functions allocate `mp_type_gen_instance` (`py/objgenerator.c:44-71`). CP 10.2.0 has both types but `mp_obj_gen_resume` accepts either (`py/objgenerator.c:215`). The original ADR's "differing only by type tag" wording was right for CP, slightly off for MP. The new ADR sidesteps this entirely.
- **PEP 380 `return value` from a generator works on both runtimes** — `mp_obj_gen_resume` at MP `objgenerator.c:218-227` puts the return value in `ret_val` on `MP_VM_RETURN_NORMAL` and raises `StopIteration` with it as the argument. [VERIFIED: read MP source; CP has matching code at the same path]

## Dead ends / rejected paths

- **The original async/await framing was rejected** for the four reasons in ADR §*Why generators, not async/await* — don't re-litigate. If a future contributor asks "why not async/await?" the answer is in the ADR body, not a separate explanation.
- **`async def` + `await` is NOT byte-identical to `def` + `yield from` on CP.** Anyone arguing "the modern idiom is free" should be pointed at CP `py/compile.c:2790-2796` first.
- **`runner.add_coroutine` was the original name.** The workstream's `add_generator` is the new name (more honest — they really are generators, not coroutines in the post-PEP-492 sense). If during implementation a better name surfaces (`spawn`, `add_task`, `add_sequence`), it's reasonable to revisit — flag the rename in the commit message and update the ADR + workstream in lockstep.

## How to rebuild context fast

1. Read `plans/decisions/0087-generators-for-sequential-io.md` end-to-end — the ADR carries all the reasoning.
2. Read `plans/workstreams/runner-generator-tasks.md` — the directive, 6 phases.
3. Skim `demos/sockets_runner_connector/app.py` — the verbose demo this work collapses.
4. Read `libraries/runner/src/chumicro_runner/core.py` — the contract the wrapper has to satisfy.
5. Read `libraries/sockets/src/chumicro_sockets/_connector.py` — the connector the `connect()` helper wraps.

Related ADRs (skim only): 0014 (runner pattern), 0051 (runner-shaped policy), 0080 (runner reactor), 0081 (non-blocking connect).

Runtime evidence files (cited in the ADR; useful for sanity-checking before Phase 1):
- `.tools/micropython-v1.26.0/py/compile.c:2767-2780`
- `.tools/circuitpython-10.2.0/py/compile.c:2790-2796`
- `.tools/{mp,cp}/py/mpconfig.h` for `MICROPY_PY_ASYNC_AWAIT` / `MICROPY_PY_ASYNCIO`
- `.tools/{mp,cp}/py/objgenerator.c` for `.send()` / `.throw()` / `.close()` semantics

## Gotchas

- **Phase 2 wrapper `io_error` hook called from `Runner.wait`, not `tick`.** `core.py:420-444` shows `_dispatch_io_error` runs inside `wait()` after `tick()` has returned, so the `_ticking` re-entrancy guard does not protect `_GeneratorWrapper._advance_throw`. This is fine — `_advance_throw` mutates only the wrapper's own `_wait` field, and the next `tick()` will see the result via `check()` returning False (`_wait is None` after a StopIteration). But the implementer should verify the wrapper's state coherence under the case where `io_error` fires *between* a `check()` call returning True and the subsequent `handle()` call. Edge case worth a test.

- **`.idea/chumicro.iml` has PyCharm drift in working tree.** Not from this work. Either revert (`git checkout .idea/chumicro.iml`) or sync (`python scripts/run.py sync-ide`) before next commit so it doesn't ride into an unrelated change.

- **Workstream's "auto-remove from runner entries on `_done`" (Phase 2)** is a stronger contract than the existing `Runner._remove` provides. `core.py:537-543` shows `_remove` mutates `self._entries` directly. The wrapper would need to defer the self-removal to avoid mutating the list during `tick()`'s iteration. The workstream notes this; implementer should design the deferral mechanism (probably via `self._pending` or a new `_pending_removes` list) and add a test that verifies a finished generator's handle doesn't accumulate as a dead entry.

- **Workstream Phase 3 helpers must hoist wait-tokens out of inner loops.** This is the load-bearing implementation rule that makes the steady-state allocation budget achievable. Easy to forget when writing the first helper; if the helper says `while …: yield ReadReady(sock)`, the tracemalloc test in Phase 3 will fail. Pattern is `ready = ReadReady(sock); while …: yield ready`.

- **Naming the lint rule (Phase 4).** Need to pick the next available `CHU0NN` number. Check `workbench/checks/src/chumicro_checks/` for the highest existing code before assigning.
