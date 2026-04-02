# Chumicro Development Ecosystem

## Project Overview

Chumicro is a family of open‑source Python libraries that target three different Python runtimes:

- **CircuitPython** and **MicroPython** for embedded boards (e.g., ESP32‑S2, ESP32‑S3).
- **CPython** for standard desktop Python.  CPython support allows easy unit testing and enables use of familiar tools such as PyTest.

 The goal is to provide robust, modern drivers and utility libraries that are efficient enough for constrained microcontrollers while still maintaining a familiar Python API.  Libraries must be compatible across all three environments.  If an existing third‑party library does not support CircuitPython/MicroPython, the code should be re‑implemented rather than imported.

Chumicro code is released under the **MIT License**, which grants broad permission to use, copy, modify, merge, publish, distribute, sublicense and/or sell copies of the software【824420635613462†L74-L83】.  The only condition is that the copyright notice and permission notice must appear in all copies or substantial portions of the software【824420635613462†L85-L86】.  The software is provided “as is”, without warranty【824420635613462†L88-L93】.

Never embed secrets; configuration such as Wi‑Fi credentials belongs in separate files on the device.

## Tech Stack & Platforms

- **Language:** Python 3 (subset compatible with CircuitPython & MicroPython).  Use PEP 8 naming conventions and docstrings.
- **Runtimes:** CircuitPython (Adafruit fork of MicroPython), MicroPython, and CPython.  CircuitPython and MicroPython constrain RAM and CPU; they support only a subset of the standard library.  Developers should use memory‑efficient patterns such as pre‑allocating buffers and using `memoryview` objects to avoid extra allocations【127994299864638†L237-L254】【5110752449986†L110-L149】.
- **Frameworks:**
  - **PyTest** for host‑based unit tests.  PyTest can be used with CPython and, where possible, MicroPython/CircuitPython via compatibility layers.
  - A **lightweight on‑device test runner** exists under `support/test_harness/` for executing small `device_tests/` modules directly on hardware or compatible runtimes.  It should stay tiny: discover test functions by the `test_` prefix, use minimal assertions, and report results without requiring extra memory.
  - **Mocks & stubs:** For host tests, create mock modules to simulate hardware APIs.  For CircuitPython, PyTest can run with mocks by using a `conftest.py` that replaces CircuitPython‑only modules.  The MicroPython stubber project similarly uses a `tests/mocks` folder to allow MicroPython code to run under CPython.

## Workspace Structure

Chumicro is organized as a **mono‑workspace**.  Each publishable library resides under `libraries/`, each with its own `src/`, `tests/`, `device_tests/`, and `doc/` subdirectories.  Shared internal packages live under `support/`.  Developer tasks are in `scripts/`, CI-specific helpers in `ci/`, and planning docs in `plans/`.

The live workspace structure is provided automatically at the start of each session.  For the canonical detailed layout, see `plans/prompts/workspace-rebuild.prompt.md`.

Conventions:

- Publishable libraries go in `libraries/<name>/` with a `pyproject.toml` and `VERSION` file.
- Support packages go in `support/<name>/` — they are workspace-internal and not published.
- `scripts/run.py` auto-discovers all packages by scanning for `pyproject.toml` under `libraries/` and `support/`.  No hard-coded lists exist.
- `python scripts/run.py new-library <name>` scaffolds a new library with the correct structure and regenerates IDE configs.

Key task runner commands (run from repo root):

- `python scripts/run.py setup` — install dependencies and regenerate IDE configs
- `python scripts/run.py preflight` — lint + all tests + build (run before committing)
- `python scripts/run.py test` — run tests for changed packages (or `--all` / `--libraries name`)
- `python scripts/run.py lint` — run ruff across the workspace
- `python scripts/run.py build` — build all publishable packages
- `python scripts/run.py sync-ide` — regenerate PyCharm and VS Code configs

This mono‑repo simplifies dependency management and allows libraries to share common infrastructure.  Publishing individual packages remains possible by using per‑library `pyproject.toml` files and packaging tools (e.g., Hatchling or Setuptools).  Use a `VERSION` file or similar per‑library version to coordinate releases.

## Development Guidelines

### Memory & Performance

Microcontrollers have limited RAM and CPU.  To avoid heap fragmentation and excessive garbage collection, follow these practices:

1. **Pre‑allocate buffers:** When interacting with I/O streams (UART, SPI, I2C), allocate a bytearray once in the constructor and reuse it.  MicroPython’s documentation shows that reading into a pre‑allocated buffer (`readinto`) avoids creating new objects on each call【127994299864638†L237-L254】.  Similarly, the MicroPython speed guide notes that stream objects often provide `readinto()` for this purpose【5110752449986†L110-L120】.
2. **Use `memoryview` for slicing:** Passing a slice of a `bytearray` creates a copy.  A `memoryview` provides a view into the buffer without copying and uses a small, fixed‑size object【5110752449986†L110-L150】.
3. **Avoid dynamic string building in loops:** Concatenate constant strings at compile time or use `format()`/`f`‑strings outside performance‑critical sections.  Repeated string concatenation fragments memory【127994299864638†L214-L233】.

4. **Prefer f‑strings over `str.format`:**  On CPython, f‑strings are compiled at import time and avoid the overhead of parsing the `str.format` mini‑language; they are the most readable and efficient form of string interpolation【600036924127677†L109-L120】.  CircuitPython’s implementation of `str.format` is written in C and builds the result by incrementally growing a virtual string buffer: it initialises a `vstr` structure and then loops over the format string, appending literal characters or parsed replacement fields one by one【700593876761682†L1099-L1123】.  Additional loops handle nested braces and format specifiers【700593876761682†L1174-L1194】.  This dynamic parsing and buffer growth consumes heap memory and adds runtime overhead, whereas an f‑string is compiled into a series of constants and expressions, assembled without extra parsing.  Therefore, when f‑strings are available, use them exclusively; if f‑strings are disabled on a very small build, `%`‑style formatting is the next most efficient option.  When using the CPython `logging` module, remember that f‑strings cause eager evaluation, but this trade‑off is acceptable on embedded boards where logging APIs lack deferred formatting.

5. **Use `const()` for constants:** CircuitPython’s design guide recommends using `const()` imported from `micropython` for numeric constants【484622475298331†L733-L746】.  Prefix internal constants with an underscore to prevent them from occupying globals【127994299864638†L155-L162】.
6. **Cache frequently used attributes:** Store object references (e.g., `self.buffer`) in local variables within performance‑critical methods to avoid repeated attribute lookups【5110752449986†L199-L211】.
7. **Control garbage collection:** For long‑running tasks, explicitly call `gc.collect()` periodically.  This pre‑emptive collection can reduce latency and fragmentation【5110752449986†L214-L228】.

### Naming & Style

 Follow PEP 8 for code style and naming.  Use descriptive names (`service`, `test_device`) instead of abbreviations like `svc` or `dut`.  Keep functions short and avoid unnecessary layers of abstraction—only split a function when it improves readability or testability.  Document **all** functions and methods (including those marked as “private” with a leading underscore) with concise docstrings so that human contributors and future AI agents can understand their purpose and parameters.  When writing CircuitPython drivers, align with Adafruit’s design guide: initialize hardware in `__init__`, provide `deinit()` or context‑manager support, and avoid extraneous allocations in drivers【484622475298331†L710-L724】.

 Use **f‑strings exclusively** for string formatting.  Compared to older `%` formatting or `str.format`, f‑strings are compiled into a single expression and avoid intermediate allocations.  On microcontrollers, this can reduce memory footprint and fragmentation.  However, be mindful when logging (see “Logging & Instrumentation” below); some logging APIs may still require lazy formatting.

### API & Compatibility

*Libraries must be compatible with CPython, MicroPython and CircuitPython.*  When exposing CPython‑compatible functionality, follow CPython’s API names so that code is easily portable【484622475298331†L250-L270】.  Do not add non‑CPython APIs to the same module; instead, create separate modules for microcontroller‑specific functionality【484622475298331†L250-L270】.  Avoid the MicroPython convention of prefixing modules with `u*` to distinguish them; choose a distinct name instead【484622475298331†L261-L266】.

### Platform Abstraction & Shims

Whenever possible, **prefer a single library implementation that works across all three runtimes**.  If a third‑party library has different implementations for CircuitPython, MicroPython and CPython, consider writing a thin **shim layer** that abstracts away the platform‑specific details.  The shim should:

1. **Detect the current runtime** using `sys.platform` or feature checks and import the appropriate underlying module.  For example, CPython uses the standard `socket` module, while CircuitPython wraps networking in `socketpool` and MicroPython exposes `usocket`.  Provide a unified API that delegates to the correct backend at import time.
2. **Maintain consistent function names and semantics** aligned with CPython’s standard library【484622475298331†L250-L270】.  If CircuitPython or MicroPython expose additional methods, do not surface them through the shim; instead, create separate modules for microcontroller‑specific functionality.
3. **Fallback to re‑implementation** when an equivalent library is not available.  If no existing library supports all three runtimes, implement the required functionality in Chumicro following the memory and performance guidelines outlined above.  Always respect upstream licenses and avoid copying code verbatim without preserving license notices.
4. **Minimise dependencies**.  Each additional external dependency increases flash usage and maintenance burden.  Only include third‑party packages when they provide significant functionality that cannot reasonably be re‑implemented.

By centralising platform differences into a shim layer, application code can remain agnostic to the underlying runtime, improving readability and reducing duplication.

### Secrets & Configuration

Never hard‑code secrets (Wi‑Fi SSIDs, passwords, tokens) in the library code.  Provide configuration hooks so users can store credentials in a separate file on the device.  A common pattern is to create a `config.py` that exports variables such as `wifi_ssid` and `wifi_password`; this file lives on the device’s filesystem and is not checked into version control.  Tutorials for Raspberry Pi Pico W show how to create a `config.py` with credentials and import it into the application【433245353756076†L29-L86】.  Libraries should look up credentials via a helper function or environment variables, allowing the user to override them.

### Logging & Instrumentation

Microcontrollers and embedded applications benefit from consistent logging to aid debugging and telemetry.  Chumicro libraries should:

1. Provide a **lightweight logging facility** that works across CPython, MicroPython and CircuitPython.  On CPython, this may wrap the standard `logging` module; on microcontrollers, implement a simple logger that writes to the console or a designated output buffer.  Support log levels (e.g., `ERROR`, `WARNING`, `INFO`, `DEBUG`) and a global mechanism to adjust the verbosity at runtime.
2. Use **f‑strings** for composing log messages.  While CPython’s logging API encourages `%`‑style formatting for deferred interpolation, on resource‑constrained devices it is acceptable to build the message eagerly with an f‑string since the overhead of the logging call dominates and there is no lazy evaluation facility.  If adopting the standard `logging` API for CPython, consider implementing a thin adapter that accepts f‑strings but defers formatting internally.
3. Keep log messages short and avoid logging inside tight loops unless necessary.  Where detailed diagnostics are needed, gate them behind a debug log level so they can be disabled on production builds.

Well‑instrumented libraries improve diagnosability without imposing undue memory or CPU costs.

### Networking & Non‑Blocking I/O

Embedded applications often communicate over Wi‑Fi, TCP or other sockets.  To keep the main loop responsive (e.g., to toggle an LED or service other tasks), **all network operations must be non‑blocking**.  Blocking on a `connect()`, `read()` or `write()` call will starve the tick‑based scheduler and defeat the purpose of this ecosystem.  The following guidelines apply:

1. **Enable non‑blocking mode** on sockets.  In MicroPython and CircuitPython, call `sock.setblocking(False)` (equivalent to `sock.settimeout(0)`) to ensure that operations return immediately rather than waiting【992409882259005†L354-L364】.  Avoid using `read()` or `write()` on a blocking socket.
2. **Use the `select` module to multiplex I/O**.  Instantiate a `select.Poll` object and register sockets for `POLLIN` and `POLLOUT` events.  Call `poll.poll(timeout)` to obtain a list of `(obj, event)` tuples, or use `poll.ipoll(timeout)` which returns an iterator that yields “callee‑owned” tuples and is an allocation‑free way to wait for events【287491311677333†L131-L136】.  The returned event mask combines flags such as `POLLIN` (readable), `POLLOUT` (writable), `POLLHUP` (hang‑up) and `POLLERR` (error)【287491311677333†L110-L123】.
3. **Handle error and hang‑up flags immediately**.  `POLLHUP` and `POLLERR` may be returned at any time—even if you did not request them—and must be acted on promptly; failing to close or unregister the socket will result in subsequent `poll()` calls returning instantly with these flags【287491311677333†L110-L123】.
4. **Read and write incrementally**.  When `POLLIN` is set, read incoming data using `sock.readinto()` or similar functions into a pre‑allocated buffer.  When `POLLOUT` is set, send queued data in small chunks.  Maintain transmit and receive queues so that the network stack never blocks.  After sending, if there is still data pending, update a timeout or state flag so the next tick will attempt to send again.  Avoid calling `sock.read()` or `sock.write()` without first checking readiness.
5. **Integrate with the tick scheduler**.  The network handler should run once per scheduler tick, poll sockets with a small timeout, and process any events.  If no events occur, return quickly so other tasks can run.  Do not spin inside network handlers; instead, rely on the scheduler to call the handler again on the next tick.

By following these patterns, Chumicro libraries can perform network communication without blocking other tasks or consuming excessive memory, enabling truly responsive applications on constrained devices.

### Long Operations & Storage

Certain operations—such as writing to the on‑device filesystem, erasing flash sectors or performing lengthy computations—can block the interpreter for tens or hundreds of milliseconds.  Flash memory must be erased before it can be written, and this erasure happens automatically prior to writing to a region【603081405923325†L140-L144】.  Because erasing and writing flash can take time and wear out the memory if repeated frequently【603081405923325†L140-L149】, design libraries to minimise file writes and avoid performing them inside tight loops.  Where persistent storage is needed:

1. **Batch writes and defer them to idle periods.**  Accumulate data in RAM and write it to the filesystem in a single operation when the application can tolerate a pause.  Do not call `open().write()` repeatedly in a high‑frequency loop.
2. **Use ring buffers or logs to amortise erases.**  If the library must store data continuously, allocate a fixed‑size log file and write new records in a circular fashion, erasing and rewriting sectors infrequently.
3. **Expose configuration for write intervals.**  Allow users to configure how often the library flushes data to storage, so they can balance durability with responsiveness.
4. **Warn about flash wear.**  Document that frequent writes can reduce flash lifetime and encourage users to offload large logs to an SD card or external storage when possible.

5. **Use an idle work queue.**  Implement the scheduler so that it supports an **idle queue** of deferred tasks.  Operations that are required but not time‑critical (such as flushing buffered data to disk) should enqueue a small callable into this queue.  The scheduler runs idle tasks only when no other tasks are runnable and no I/O events are pending, ensuring that they execute during otherwise unused time slices without blocking interactive logic.  This mechanism helps maintain responsiveness while still completing background work.

Similarly, avoid other long‑running operations—e.g., heavy computations or sensor reads that take milliseconds—in the main loop.  Break them into smaller steps, run them across multiple ticks, or offload them to dedicated hardware peripherals.  Following these practices preserves the responsiveness of the tick‑based scheduler and ensures your application can continue to service other tasks.

### Scheduling & Concurrency

To maximise predictability and minimise overhead, Chumicro **does not rely on Python’s `async`/`await` syntax** or the built‑in asynchronous schedulers (`asyncio`/`uasyncio`).  MicroPython’s and CircuitPython’s asynchronous engines are limited and not available on some small boards【204239382498704†L176-L186】.  Instead, a **tick‑based scheduler** will be provided in the support package.  This scheduler will run tasks sequentially on each tick or time slice, and tasks must return control quickly so that other tasks can run.  Developers should pre‑allocate task objects and buffers to avoid heap fragmentation, and the scheduler should expose a configurable tick rate while keeping per‑tick overhead minimal.

Chumicro **forbids the use of hardware interrupts (ISRs) anywhere in the codebase**.  Libraries must not attach callbacks to GPIO interrupts or rely on `micropython.schedule()` to run code outside the main loop.  Instead, use polling in the tick‑based scheduler or helper modules like `countio` and `keypad` to detect state changes.  Avoiding ISRs ensures deterministic timing, eliminates hidden heap usage and simplifies debugging across all supported runtimes.

## Testing Strategy

### Host‑Based Unit Tests (PyTest)

PyTest is the primary framework for unit tests in the host environment.  It offers fixtures, assertions, and code‑coverage tools.  The CircuitPython community has demonstrated that PyTest can be used alongside a `conftest.py` to mock out CircuitPython‑specific modules【900637251395569†L175-L225】.  MicroPython projects such as `micropython‑stubber` also use a `tests/mocks` folder to allow MicroPython code to run under CPython【424519180869736†L53-L77】.  When writing tests:

1. Place CPython unit tests under `tests/` inside each library.  Use mocks to simulate hardware interactions.  For example, `pytest_runtest_setup` in `conftest.py` can dynamically replace `board`, `digitalio`, etc., with stub objects【900637251395569†L175-L246】.
2. Maintain 100 % code coverage where practical.  Use `pytest-cov` to measure coverage and ensure that new code includes tests.
3. Keep tests simple and avoid test‑only abstractions that bloat the library.  Instead, design classes and functions to accept injected dependencies (e.g., pass in a `ticks` module or I/O interface) so tests can replace them with mocks.

#### Library testability rules

Libraries must be designed for testability from the start (see [Decision 0010](plans/decisions/0010-library-testability.md)):

- Accept dependencies via constructor injection — classes that depend on time, I/O, or network must take those as constructor parameters.
- Provide fakes for things you own — libraries that expose injectable services must include a `testing` submodule (`src/chumicro_<name>/testing.py`) with ready-made fakes.
- Don't mock what you don't own — use the upstream library's provided fakes rather than creating ad-hoc mocks.

#### Test structure rules

The workspace uses per-library pytest runs to avoid test-directory name collisions (see [Decision 0009](plans/decisions/0009-per-library-test-runs.md)).  `scripts/run.py test` runs a separate pytest subprocess for each package, then combines coverage.  Each library must independently meet the 90% coverage threshold.

- The root `conftest.py` auto-discovers all `src/` directories and adds them to `sys.path`, so library packages are importable without pip install.
- Shared test fakes ship with their library as a `testing` submodule (e.g., `from chumicro_timing.testing import FakeTicks`).  Other libraries import them directly.
- **Do not use `pip install -e`** to resolve IDE import warnings.  IDE resolution is handled through generated source root configs (`.idea/chumicro.iml` for PyCharm, `pyrightconfig.json` for VS Code).
- Bare `pytest` from the repo root is not the supported path.  Use `python scripts/run.py test`.

### On‑Device Unit Tests

For tests that must run on real hardware or under the actual MicroPython/CircuitPython interpreter, a lightweight on‑device test runner exists in `support/test_harness/`.  It should discover functions prefixed with `test_`, run them one by one, and report results, while keeping memory usage minimal.  Its interface and helpers (e.g., assertions) may still evolve, but it should remain intentionally tiny.

Tests intended for on‑device execution should live under a `device_tests/` directory within each library and import any required mocks or helpers from the support package.  Avoid heavy imports or complex features that are unavailable on the board.

### Functional & Integration Testing

Where possible, run integration tests against actual hardware.  Since hardware access varies, the framework allows users to register their own devices via a configuration file (e.g., `devices.yml`).  Each entry defines the serial port or network address of a board, its family (e.g., ESP32‑S2), and any environment setup commands.  CI can read this file to run functional tests on connected devices.

### Continuous Integration

CI pipelines should enforce linting, unit tests and code coverage across all supported runtimes.  A typical flow:

1. **Linting:** Run `ruff` to ensure PEP 8 compliance.
2. **Static type checking:** Optionally run `mypy` against CPython code (use type hints where possible without breaking MicroPython/CircuitPython compatibility).
3. **Unit tests:** Execute PyTest on a CPython interpreter.  Optionally also run tests under MicroPython's Unix port using MicroPython's `run‑tests.py` script【593158073270695†L93-L104】.
4. **On‑device tests:** If configured, flash the library and test firmware to boards listed in `devices.yml` and run the on‑device test runner.  Collect results and include them in the CI report.
5. **Coverage:** Fail the build if coverage drops below a threshold (e.g., 90 %).

## Versioning & Releases

Chumicro libraries follow [Semantic Versioning](https://semver.org/).  The specification states that major versions increment for backward‑incompatible API changes, minor versions for backward‑compatible new features, and patch versions for bug fixes.  Each publishable library should own a checked-in `VERSION` file at the library root (for example, `libraries/timing/VERSION`), and agents should treat that file as the canonical published version for that library.

When an agent changes a library in a way that affects its released surface area, the same PR should update that library’s `VERSION` file with the smallest correct semantic-version bump:

- `major` – introducing breaking changes.
- `minor` – adding new functionality in a backward-compatible way.
- `patch` – fixing bugs without API changes.

Do not bump unrelated libraries.  PR checks should fail when a publishable library changes without the corresponding `VERSION` file being reviewed and updated when required.  Release automation should read the library version from that file, and any duplicated version metadata (for example in `pyproject.toml`) should be kept in sync or validated against it before publishing.  Releases are automatically published (e.g., to PyPI or a CircuitPython bundle) only after tests pass and a human/AI review is complete.

### Bytecode Compilation

During everyday development, keep library code in plain `.py` files to maximise readability and allow inspection by AI agents and human developers.  When creating a release, compile modules to `.mpy` bytecode using `mpy-cross` or an equivalent tool.  The `.mpy` format reduces code size and speeds import on boards but is harder to debug.  Release automation should handle this compilation step so developers do not need to commit `.mpy` files to the repository.

Chumicro plans to provide its own package index for installation via tools like `circup`, alongside publishing to PyPI.  Once the ecosystem is mature, developers will be able to install or update libraries from this repository directly on their boards.

## Device Registration & Test Bed Setup

To run functional tests, users must register their own devices.  Provide a template file (e.g., `devices.example.yml`) with keys such as `id`, `description`, `connection_type` (`serial`, `tcp`), `address`, and `board_type`.  Users copy this to `devices.yml`, fill in their devices, and the test harness reads the file to know which devices to target.  Default assumptions are ESP32‑S2/S3 boards with enough RAM and flash.

For CircuitPython boards, ensure they have the appropriate firmware version installed and a filesystem with enough space for the library and tests.  Tools like Adafruit’s `mpremote` or `adafruit-nrfutil` can automate flashing.  For MicroPython boards, use the `pyboard.py` or `mpremote` utilities.

## Dependencies & Licensing

Minimize external dependencies; prefer pure‑Python implementations that work on CircuitPython and MicroPython.  If a dependency is required, verify that it supports the target runtimes.  When re‑implementing functionality, respect the licenses of upstream code.  CircuitPython and MicroPython core libraries are licensed under MIT【204597493819549†L36-L50】, which permits copying, modifying, and distributing code provided the license notice is retained【204597493819549†L38-L50】.

## Board Considerations & Feature Detection

Chumicro primarily targets boards in the ESP32‑S2/S3 family or similar microcontrollers with sufficient RAM and flash.  Smaller boards (e.g., SAMD21) may lack features such as the `asyncio` library【204239382498704†L176-L186】 or have tighter memory constraints.  Developers should:

1. Document the minimum firmware version and memory requirements for each library.  If a library depends on a specific module (e.g., `socket`, `bluetooth`), note which ports provide it.
2. Use `sys.platform` or feature checks (`hasattr(module, "function")`) to detect whether optional features are available.  Provide graceful fallbacks or raise clear exceptions when features are missing.  For example, check `hasattr(wifi, 'radio')` before using `wifi.radio`.
3. Consider differences between CircuitPython and MicroPython—e.g., CircuitPython includes higher‑level networking APIs like `socketpool`, while MicroPython exposes lower‑level `usocket`.  Abstract platform differences behind a consistent API when possible.
4. Test libraries on the supported boards listed in `devices.yml` and update documentation when new boards are added.

## Reference Implementations

The upstream implementations of **CPython**, **MicroPython**, and **CircuitPython** are all open‑source and hosted on GitHub.  CircuitPython’s repository is publicly available and is maintained as a fork of MicroPython【828117899337916†L163-L169】.  MicroPython’s source code is similarly public under the `micropython/micropython` repository, and the standard Python implementation is hosted in `python/cpython`【804763416686691†L163-L171】.  Examining these repositories is encouraged when you need to understand how features are implemented or to optimise memory usage—e.g., CircuitPython’s implementation of `str.format` in `py/objstr.c` uses a dynamically growing buffer to build the formatted string【700593876761682†L1099-L1123】.  Referencing the source helps ensure Chumicro libraries align with the behaviour of the underlying interpreters while remaining efficient.

## Planning documents are part of the workspace contract

The planning documents under `plans/` are part of the repository's working state, not optional notes. Significant implementation or direction changes should be reflected in:

- `plans/next-up.md` for the active execution queue
- `plans/roadmap.md` for milestone status and major direction
- `plans/workstreams/` for durable bodies of work and higher-level scope; update them when the long-lived shape of the work changes
- `plans/decisions/` for durable decisions that affect future work
- `plans/prompts/` for durable prompt artifacts used to recover workspace context, restart sessions, or preserve workspace build-up history

**Before proposing a change to workspace structure, testing patterns, or dependency strategy, check `plans/decisions/` for existing decisions on the topic.**  Re-proposing something that was already decided and rejected wastes time.  If new information justifies revisiting a decision, say so explicitly and reference the original decision.

Keep planning docs aligned with the actual codebase, but avoid churn for tiny edits that do not change scope, status, priorities, or next steps.

## Security & Compliance

Building connected devices requires attention to security and data protection.  In addition to keeping secrets out of the codebase (see *Secrets & Configuration*), developers should:

1. **Use encrypted protocols:** When communicating over networks, prefer TLS/SSL.  CircuitPython provides `ssl`/`ussl` wrappers for sockets; ensure certificates are validated where possible.
2. **Avoid weak cryptography:** Use modern hashing (e.g., SHA‑256) and encryption algorithms supported by your runtime.  Do not implement your own cryptography.
3. **Maintain dependencies:** Keep third‑party libraries up to date and audit them for vulnerabilities.  When importing code from upstream projects, review their licenses and security posture.
4. **Protect personal data:** Do not collect or transmit personal or sensitive data unless absolutely necessary.  Provide configuration options to disable or anonymise telemetry.
5. **Harden devices:** Disable unused network services, validate inputs from untrusted sources, and restrict access to configuration interfaces.  Follow established IoT security best practices to minimise attack surfaces.

## Contributing & Code Review

1. Discuss design proposals with the maintainers or AI agent before starting large features.  Surface trade‑offs and uncertainties early.
2. Keep pull requests small and focused.  Each PR must include tests and documentation for the new functionality.
3. Code review checks include style, test coverage, memory usage (avoid extra allocations), and API consistency across runtimes.  When reviewing code, explicitly reference these guidelines.
4. Do not include build artifacts, compiled bytecode, or secret configuration files in commits.  Add appropriate `.gitignore` rules.
5. **Commit after completing a meaningful unit of work.**  Do not leave changes uncommitted between sessions.  Each working session should end with a clean tree.
6. **Write commit messages that aid context recovery.**  Planning docs under `plans/` can go stale between sessions.  When that happens, commit history is the primary fallback for reconstructing what changed and why.  Write commit messages accordingly:
   - **Subject line:** summarise *what* changed in imperative mood (e.g., "Add importlib test isolation for multi-library workspace").
   - **Body (when non-trivial):** explain *why* the change was made, what alternatives were considered or rejected, and which planning items or decisions it relates to.  Name affected libraries, decisions, or workstreams when relevant.
   - **Scope tags:** if the commit touches planning docs, infrastructure, or a specific library, make that clear early in the message so `git log --oneline` is scannable.
   - A future agent scanning `git log` should be able to infer the current project state, recent design choices, and the trajectory of work — even if `plans/` has not been updated yet.

By following these guidelines, Chumicro aims to build a sustainable ecosystem of high‑quality, cross‑platform libraries for modern microcontrollers and Python applications.
