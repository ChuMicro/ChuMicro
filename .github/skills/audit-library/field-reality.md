# Audit-library field reality

Incidents and worked examples that shaped the audit dimensions in [SKILL.md](SKILL.md).  Each section is referenced from a bullet there.  Consult an entry when the *how this came up* context behind a rule is useful; the rule itself stays in SKILL.md.

## Contents

- [Stale CLI / recovery-command / status claims](#stale-cli--recovery-command--status-claims)
- [Doc bugs cluster — audit numbers and symbols together](#doc-bugs-cluster--audit-numbers-and-symbols-together)
- [Tests that pass a parameter but don't exercise it](#tests-that-pass-a-parameter-but-dont-exercise-it)
- [I/O in the constructor violates the runner contract](#io-in-the-constructor-violates-the-runner-contract)
- [Speculative public-API class properties](#speculative-public-api-class-properties)
- [No slots in device-library code](#no-slots-in-device-library-code)
- [Spec-trivia in `__all__` — and the doc residue](#spec-trivia-in-all--and-the-doc-residue)
- [ABC + exceptions split across files](#abc--exceptions-split-across-files)
- [Inspect the staged diff before every audit commit](#inspect-the-staged-diff-before-every-audit-commit)
- [Don't dismiss inline comments without verifying the claim](#dont-dismiss-inline-comments-without-verifying-the-claim)

## Stale CLI / recovery-command / status claims

A doc grep pass found three drift sites in one library: a `--drive` flag the CLI no longer exposed, a `launchctl kickstart` recovery command the source had dropped (SIP-blocked), and a "uid is reserved, empty today" claim that pre-dated the probe that now populates it.  All three were HIGH-confidence single-line edits — and all three would have rotted further without the grep.

**Pattern:** docs name CLI flags, error-message text, recovery commands, environment variables, and feature-status assertions by name.  Audit move is to grep `docs/guide.md`, `README.md`, and `docs/*.md` for each and confirm the documented shape still exists.

## Doc bugs cluster — audit numbers and symbols together

The kvstore guide had three drifts in one file — a missing `from chumicro_timing import ticks_ms` in a "copy-pasteable" snippet, a SAMD21↔SAMD51 chip-family swap, and a "~4 KB practical" sizing claim that disagreed with both the code default and the ADR.  Doc-writers introduce errors in batches; auditors should find them in batches.

**Pattern:** when one quantitative or symbolic claim in a doc is wrong, the file's other numbers and symbols deserve a focused pass rather than a passing grep.

## Tests that pass a parameter but don't exercise it

A test setup like `MQTTClient(max_message_bytes=8192, rx_buffer_size=64, ...)` looked like it tested the `max_message_bytes` cap — but the test asserted an event fires on a 200-byte payload, which fires off `rx_buffer_size` (64), not `max_message_bytes`.  The test would pass identically if `max_message_bytes` were ignored entirely — and in one mqtt audit, it was: the parameter was assigned to `self` and never read, but four tests passing the value still went green because the behavior they asserted was triggered by a different parameter.

**Audit move:** for every test that passes a tunable kwarg, mentally change the kwarg's value and ask "would this test still pass?"  If yes, the test exercises "doesn't crash when set," not "does what it claims."  Either the test needs a value-sensitive assertion, the parameter is dead surface, or both.  Same family of finding as the "lying class name" honesty check — the gap is between what the test code looks like it's testing and what it actually tests.

## I/O in the constructor violates the runner contract

Any library that claims runner-shape (`check(now_ms)` / `handle(now_ms)` interface) promises errors land on `state` / `last_error`, observable via introspection — not as exceptions out of the constructor.  When `__init__` calls a factory that opens a socket, opens a file, dials a network host, or otherwise touches the world, an `OSError(ECONNREFUSED)` propagates out of `MyClient(...)` and bypasses the state-machine contract entirely.

`MQTTClient.__init__` called `socket = socket_factory()` at construction since the original self-heal commit.  Three audit passes (`/audit-embedded`, `/audit-integration`, the DI-Tier-1 sockets-factory audit) all walked past it; the bug surfaced only when a misconfigured factory raised `ECONNABORTED` out of the constructor and the user pointed out the shape was wrong.  The fix moved the factory invocation into `connect()` — same error now lands as `state == FAILED` + `last_error` set, which the existing self-heal path retries.

**Audit move:** grep `__init__` methods for `socket.connect`, `socket.bind`, `open(`, `.recv`, `.send`, `.read`, `.write`, `.dial(`, factory calls like `socket_factory()` / `connection_factory()` / `listener_factory()` invoked at construction time.  Each match is a finding unless the I/O is documented as part of the constructor contract (rare — usually a bug).

**Related:** `from_config` factories should NOT do I/O either — `from_config` builds a factory and threads it into the constructor; both stay side-effect free.

## Speculative public-API class properties

The chumicro_ntp audit flagged `NTPResult.ticks_started_ms` — a public read-only property with zero external callers across the mono-repo + workspace-template.  Only `NTPClient._check_timeout` read it for timeout math, and the same flow already touched `_unix_seconds` / `_done` / `_error` via `# noqa: SLF001`.  Treating the finding as MEDIUM and surfacing for sign-off was over-cautious; it should have been HIGH.

**Pattern:** Named-without-underscore properties / methods on public classes are the same shape of speculative surface as `__all__` exports.  When internal code uses the name, the rewrite is mechanical (access the underscored attribute with `# noqa: SLF001`, matching how the rest of the class is already touched).  Default action is HIGH-confidence drop — same evidence threshold as `__all__` exports.

## No slots in device-library code

`chumicro_requests.client` and `chumicro_http_server.server` each dropped three `__slots__` blocks with no behavior change.  MicroPython and CircuitPython have no `__slots__` implementation; the runtimes parse the declaration but the attribute-locking + per-instance-dict-drop is a CPython-only behavior.  On-device value is zero, the only payoff is typo-shielding inside CPython tests, and the cost is the parsed declaration on every board this library ships to.  Per-board flash sits around 800 KB total across ~15 libraries — every line of test-only scaffolding in `src/` is real flash spent for zero device value.

## Spec-trivia in `__all__` — and the doc residue

A mqtt audit dropped `InFlightTable` from `__all__` cleanly on the code side, but the Memory-notes paragraph in `guide.md` kept naming it for two audit passes before a follow-up doc-cluster re-pass caught the residue.  Different shape of staleness from the CLI-flag / error-text variety; same root cause (docs lag code).

**Audit move:** after dropping names from `__all__`, grep `README.md` + `docs/guide.md` + docstrings + examples for each removed name.  User-facing prose names internal classes more often than code-grep predicts.

## ABC + exceptions split across files

kvstore had every backend doing `from chumicro_kvstore.core import KVStoreFull` inside `save()`'s body purely because `Backend` was split into `_backends/base.py`.  Merging `Backend` into `core.py` deleted 4 lazy imports + 1 file in a single commit.

**Pattern:** an ABC lives in one file, the concrete subclasses in sibling files lazy-import the exception classes from `core.py` to satisfy their `raise KVStoreFull(...)` lines, because eager-importing would cycle through the ABC.  Fix is to merge the ABC into the module that already holds the exceptions — one fewer file, the per-method lazy imports disappear, the dependency graph linearises.

This is the reverse shape of the "leaf types module" pattern (where a new leaf file is the right answer).  Here the cycle is induced by a split that should never have existed; collapse, don't add a third leaf.

## Inspect the staged diff before every audit commit

An ntp embedded audit staged + committed `core.py` after a docstring-trim Edit; the commit ended up containing 8 extra lines (a `from chumicro_config import ...` + a validation block) added by a concurrent process between the Edit and the commit.  The commit message described only the docstring trim — the diff had a surprise that no review caught.

**Pattern:** audits run iteratively, and concurrent edits (linter hooks, parallel agent sessions, the user's own in-flight work) can land in the same files between your Edit and your `git add`; staging "the file" with `git add libraries/<name>/...` then picks up everything in the working tree.  Either stage with `git add -p` for surgical commits when foreign hunks are present, or always inspect `git --no-pager diff --cached` before `commit`.  Most expensive failure mode in iterative audit work; the cached-diff check costs ~2 seconds.

## Don't dismiss inline comments without verifying the claim

A timing audit "fix" deduped tick constants by importing from a sibling module, which broke MP+CP test runs because the constants the sibling module exposed were leading-underscore `const()` names (stripped from the module namespace on MP/CP).  An inline comment had named the constraint; the audit pass dismissed it.

**Pattern:** a comment like *"defined here rather than imported from X because <reason>"* is direct evidence that someone considered the cleaner alternative and rejected it.  Before "fixing" the structure, validate the comment's claim against the actual constraint it names — and run the test sweep that the constraint relates to, not just CPython unit tests.  If the file is imported by cross-runtime tests (anything other than `*_pytest.py`), run `python scripts/run.py preflight` rather than `pytest libraries/<name>/tests/` before committing — the latter won't surface MicroPython / CircuitPython parse-time or import-time failures.
