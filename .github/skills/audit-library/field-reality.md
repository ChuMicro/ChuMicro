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
- [Essay-bloat and the cold-maintainer test](#essay-bloat-and-the-cold-maintainer-test)
- [AI-tic and dateless-history in code comments](#ai-tic-and-dateless-history-in-code-comments)

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

**Pattern:** a comment like *"defined here rather than imported from X because <reason>"* is direct evidence that someone considered the cleaner alternative and rejected it.  Before "fixing" the structure, validate the comment's claim against the actual constraint it names — and run the test sweep that the constraint relates to, not just CPython unit tests.  If the file is imported by cross-runtime tests (any test file not marked `__chumicro_runtimes__ = ("cpython",)` or `__chumicro_host_only__ = True`), run `python scripts/run.py preflight` rather than `pytest libraries/<name>/tests/` before committing — the latter won't surface MicroPython / CircuitPython parse-time or import-time failures.

## Essay-bloat and the cold-maintainer test

A comment pass on `chumicro_deploy` + `chumicro_workspace` found a 4-line function (`cli/health.py::_cmd_doctor`) under a 25-line docstring whose second sentence — *"That path has no workspace dependency — wedge detection + the killall recovery don't touch workspace state"* — no reader could parse.  It was not greppable: no banned word, no date, no tic.  A pattern-grep pass had called the file "clean" one round earlier.  Only a per-function ratio sweep plus a top-down read surfaced it.

**Audit move.** AST-walk `src/`; for each function compute `(docstring_lines + inline_comment_lines) / code_lines` (code = body minus the docstring node).  Sort descending, read every function over ~1.5× with ≥10 prose lines.  A throwaway script does this in one pass:

```python
import ast, io, tokenize
from pathlib import Path
for path in sorted(Path("workbench/deploy/src").rglob("*.py")):
    src = path.read_text(); tree = ast.parse(src)
    cmt = {t.start[0] for t in tokenize.generate_tokens(io.StringIO(src).readline)
           if t.type == tokenize.COMMENT}
    for n in ast.walk(tree):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)): continue
        d = ast.get_docstring(n, clean=False)
        first = n.body[0]
        is_doc = isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
        code0 = first.end_lineno + 1 if is_doc else first.lineno
        code = max(1, n.end_lineno - code0 + 1)
        prose = (len(d.splitlines()) if d else 0) + sum(code0 <= c <= n.end_lineno for c in cmt) + (len(d.splitlines()) if d and not is_doc else 0)
        if prose >= 10 and prose / code >= 1.5:
            print(f"{prose/code:4.1f}x {prose:3d}/{code:<3d} {path}:{n.lineno} {n.name}")
```

**Then judge — the ratio is a trigger, not a verdict.** Roughly half the outliers in that pass were *legitimate* and must not be cut:

| Shape | Why it earns the length | Action |
|---|---|---|
| `typing.Protocol` method (`...` body) | The docstring *is* the interface contract | Leave (tighten wording only) |
| `@property` / `@abstractmethod` stub | One-line body by nature; doc carries the meaning | Leave |
| Destructive public API (`flash_firmware`) | `Args:` warns that a wrong flash-offset bricks the board — load-bearing | Leave |
| Many-param public function (`merge`, `flatten`) | Every `Args:`/`Returns:`/`Raises:` line documents real behavior, each sentence clear | Leave |
| Internal helper / `_cmd_*` narrating trivial code | Prose restates code, justifies the diff, or is incoherent | **Cut to the why** |

Gutting the first four is the same fault as the bloat, inverted — "don't golf" applies to prose.  The genuine target is the last row: internal helpers and CLI handlers where the prose narrates instead of explaining, often with a sentence no cold maintainer can parse.  Cut those to the why; delete the unparseable sentences rather than rewording them.

## AI-tic and dateless-history in code comments

The same pass: `circuitpython_transport.py` carried `the single chokepoint that evicts a board settings.toml` (the banned `the (one|single|sole) X` definition-tic — same family as "the canonical X"), a `.scratch/wipe_soak.py` pointer (`.scratch/` is gitignored, so it is a dead pointer for every consumer *and* every other contributor), and *"the legacy additive shape, retained only until the clean-slate default lands"* (history **and** stale — clean-slate had already defaulted).  `CHU012` did not fire: its removed-code pattern is verb-anchored (`Earlier versions|Previously,? th(is|e)|We used to`) and its incident patterns require a trailing ISO date, so dateless history sails through.

**Audit move.** Over `src/` comments + docstrings (not just markdown), run the `/audit-docs` standing AI-tic regex, plus:

- `the (one|single|sole) [a-z]+ (that|which|is|path|owner|mechanism|chokepoint)` — triage only.  Legitimate invariant prose (*"the single owner of the staging path"*, 0077's *"exactly one mechanism"*) is a keep — judge, don't auto-flag.
- `\.scratch/` in publishable `src/` — always a defect.  `.scratch/` is the agent scratch convention; shipped code must never name it as a pointer (`circuitpython_transport.py`'s `.scratch/wipe_soak.py`) *or* build it as a runtime path.  The one apparent exception — `example_source.py` defaulting a generated msgpack to `<secrets_toml>.parent/.scratch/…` — was itself the defect: it had deviated from the `_generated/` build-artifact convention its sibling `deploy_source.py` already established.  Fixed 2026-05-18 to `libraries/<lib>/examples/_generated/`.  A generated artifact belongs in gitignored `_generated/`, never `.scratch/`.
- dateless history: `now that|retained only until|before (this|the) .*landed|used to be`, removed-code explanations, bench-observation logs (`empirically the slowest .* we'?ve observed`, `bench-tested`), and "today / currently / for now" temporal hedges.

**The lint/agent split.** `CHU012` + `CHU006` catch the deterministic subset (dated incidents, `Decision NNNN`, `plans/…md`).  The dateless / judgment cases — *"X now that Y landed"*, incoherent incident framing, a stale "until Z lands" that is now false — are not safely regexable and belong to this audit pass.

With `example_source.py` fixed (the sole verified "legitimate runtime-path use" was a convention deviation, now gone), a bare `\.scratch/` pattern over publishable `src/` has no known legitimate hit — it is the clean mechanical `CHU006` add the parked workstream [`chu-prose-isolation-lint-gaps`](../../../plans/workstreams/chu-prose-isolation-lint-gaps.md) (tracked in [`next-up.md`](../../../plans/next-up.md)) originally expected, before it was revised for the `example_source` counter-evidence.  That revision is now itself reverted; the workstream remains the consistent source of truth and still routes the add through `new-decision` per Decision 0074, but no longer blocked by a legitimate-use exception.  The `the one/single X` matcher, by contrast, stays *not* mechanizable (Decision 0074 / the CHU020 entry) — it false-positives on legitimate invariant prose.  Don't re-derive these by hand each audit; reconcile against that workstream and don't let this skill drift from it.
