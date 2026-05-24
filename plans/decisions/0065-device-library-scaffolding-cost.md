# Decision 0065: Device-library scaffolding cost — no `__slots__`, no pure-passthrough `@property`

Status: `accepted`
Date: `2026-05-12`
Summary: Device libraries (`libraries/*/src/`) forbid `__slots__` (MP/CP no-op, pure CPython-test payoff) and pure-passthrough `@property` (descriptor cost for no value); workbench out of scope.
Related: [Decision 0014](0014-runner-pattern.md) (runner pattern), [Decision 0042](0042-library-dependency-policy.md) (library dependency policy), [Decision 0051](0051-runner-shaped-as-project-policy.md) (runner-shape as project policy).

## Context

Boards in scope sit at 256 KB RAM and ~800 KB total flash for all chumicro libraries plus the user's code (Pi Pico W class).  Every line of source that ships to a device is parsed into bytecode and counts against that budget.  The CPython idioms for "make this class slightly safer / slightly more pythonic" — `__slots__` to lock the attribute set and shrink the per-instance dict, `@property` to turn a getter into a dot-access — both cost flash on the device while paying off only in environments other than the device itself.

Concretely:

* **`__slots__`:** MicroPython has no `__slots__` implementation ([discussion #13745](https://github.com/orgs/micropython/discussions/13745)); CircuitPython inherits the no-op behavior.  The runtimes parse the declaration but the attribute-locking + per-instance-dict-drop is a CPython-only effect.  So on every supported device, `__slots__` is dead source that pays off only inside CPython tests (catches `self.feild = ...` typos that would otherwise silently shadow `self.field`).
* **`@property`:** Works on MP/CP via the standard descriptor protocol, but each access invokes the getter function — multiple µs on MP/CP vs a direct attribute load.  Each `@property` also allocates a `property` object on the class (~100 B per-class).  For pure-passthrough getters (`def state(self): return self._state`), the same public-read contract is communicated by naming the attribute `state` directly with no underscore.  No descriptor, no per-access cost, no class overhead.

The accumulated cost across `libraries/` was real but quiet: a 2026-05-11 audit found 17 `__slots__` declarations across 9 library files, and a follow-up grep in 2026-05-12 found 89 `@property` decorators across 16 library files.  Most of the latter are pure passthroughs.

The audit-library skill already names "no code catering to tests in shipped `src/`" as an anti-pattern, but the specific shapes (`__slots__`, pure-passthrough `@property`) hadn't been called out.  This decision lands the rule explicitly and makes it enforceable by the audit lens going forward.

## Decision

### No `__slots__` in `libraries/*/src/`

Device-library source must not declare `__slots__` on any class, including testing-only fakes in `testing.py`.  The MP/CP no-op + CPython-test-only payoff combination is dead weight on every board.

CPython-side typo shielding for test fakes is not load-bearing: the same protection comes from running `python scripts/run.py preflight` (which includes a full test sweep on all three runtimes) before commit.  A typo in a test fake breaks the test, regardless of whether `__slots__` is set.

### No pure-passthrough `@property` in `libraries/*/src/`

For a getter that just returns an instance attribute, publish the attribute publicly instead of wrapping it in a `@property`:

```python
# ❌ Pure passthrough — descriptor cost for no semantic value
class RequestParser:
    def __init__(self):
        self._state = RequestParseState.REQUEST_LINE

    @property
    def state(self):
        return self._state

# ✅ Direct public attribute
class RequestParser:
    def __init__(self):
        self.state = RequestParseState.REQUEST_LINE
```

The underscored-internal-name + public-property pair communicates "this is read-only" by convention.  Naming the attribute publicly communicates "this is the public read API" without the descriptor scaffold.  Callers write `parser.state` either way.

### Where `@property` is still allowed

Properties that genuinely *compute* a value on each access stay legitimate.  Examples from the current codebase:

```python
@property
def is_done(self):
    """Connection has reached a terminal state."""
    return self._state in (_ConnState.DONE, _ConnState.ERROR)

@property
def body(self):
    """Snapshot the body bytes received so far."""
    return bytes(self._body_view[:self._body_write_offset])
```

If the computation is non-trivial enough that the dot-access syntax actively misleads the reader ("this looks like a field, but it's doing work"), prefer a regular method (`def body_bytes(self) -> bytes: ...`).  The cutoff is taste; the rule is that the property must be doing *something* beyond passthrough.

### Workbench is out of scope

`workbench/*/src/` runs on the laptop, not on a device.  The flash-cost argument does not apply.  Workbench packages may use `__slots__` (CPython load-bearing — drops the per-instance dict, locks the attribute set) and `@property` (CPython-optimized at the C level) at their author's discretion.  This decision narrows to device-library code (`libraries/*/src/`) specifically.

## Consequences

* The `/audit-library` skill's §7 ("chumicro project-policy compliance") names both rules as HIGH-confidence drops for any device-library finding.  Every new audit pass surfaces them mechanically.
* `plans/patterns.md` carries the "device-library scaffolding cost" section as the durable how-to with worked examples.
* Existing `@property` uses in `libraries/` are catalogued for follow-up — pure passthroughs become direct public attributes (mechanical rename, public API stays compatible because the attribute name doesn't change); computed properties stay; method-shape conversions are case-by-case.  The sweep is tracked in `plans/next-up.md` and runs library-by-library at the same cadence as other audits.  Each library's removal commit bumps `VERSION` per the audit-skill rules.
* The `chumicro_requests.client` (2026-05-12, commit `b125d7c2`) and `chumicro_http_server.server` (2026-05-12, commit `bbfc5e34`) `__slots__` removals are retroactive precedents for the `__slots__` half of this decision.  The `@property` half is forward-looking; no library has been swept yet.

### Alternatives considered

* **Keep `__slots__` where the class has many similarly-named fields.**  Rejected: the typo-shielding payoff applies only to CPython tests, and the test suite catches the same typos by running each test against a real workflow.  The flash cost is paid on every board regardless.
* **Keep pure-passthrough `@property` for "documentation value" (signals read-only).**  Rejected: the underscore convention on the backing field plus the public attribute name communicates the same intent.  A reader scanning `parser.state` sees the public attribute; a reader scanning `self._state =` inside the class sees the internal field.  No descriptor needed.
* **Convert pure-passthrough properties to read-only via `__setattr__`.**  Rejected: adds back the per-access cost (`__setattr__` fires on every write) and adds new flash to enforce a constraint nobody is violating.  Public attributes are mutable; user code that overwrites `parser.state = "BAD"` is already broken at the protocol level.
* **Apply the ban workspace-wide (including `workbench/`).**  Rejected: workbench packages run only on the laptop where both `__slots__` and `@property` have real CPython payoff.  Narrowing the rule to `libraries/` keeps the constraint where the flash cost lives.
