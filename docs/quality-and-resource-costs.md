# Quality and resource costs

ChuMicro's baseline is a board with 256 KB of MCU RAM and 2 MB of physical flash. Usable storage is smaller after firmware, and networking, TLS, and larger buffers compete for limited headroom. Correctness matters alongside whether an application can afford to run the library.

Tests, examples, and demos are expected from day one, where relevant, with physical and manual feedback sought early. The scaffold provides source, starter tests, documentation, an example, and an empty functional-test directory. A concrete demo and a real-board test must be authored separately.

## What a green preflight establishes

The development goal is coverage of at least 90%, but that is not a universally enforced gate. The configured default and normal CI threshold is 85%, while agent and release checks use 94%. Elevated preflight scopes coverage to changed packages when it detects a change set. Read a passing result against its configured threshold and scope, not as proof that every package meets the development goal.

From a prepared repository root with the virtual environment active, run:

```bash
python scripts/run.py preflight
```

The [Contributor guide](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md) covers environment setup and required runtime tools. This command reports phase results and a final pass or failure. It creates local check/build artifacts and may prepare missing runtime tools.

Default preflight covers lint, builds, documentation, CPython tests, test infrastructure, example and demo verification, dependency checks, size budgets, version/API checks, and MicroPython and CircuitPython unix-port tests. The unix ports run the device runtimes on your laptop. They provide runtime evidence, but this invocation does not run tests on a physical board.

Example verification checks syntax and resolvable imports. For hardware examples, import checking is limited to ChuMicro imports. Demo verification checks for nonempty Python files and valid syntax. Neither check executes the example or demo bodies, so passing verification does not establish real behavior.

Focused test selection and coverage-disabled runs are useful for quick iteration, but they bypass the coverage gate. Use a full gate result to support coverage claims.

Physical-board unit and functional tests have separate routes described in [Device testing](contributing/device-testing.md). They can be added to preflight, but are absent from default CI preflight. Project practice includes actual hardware testing and manual use of examples and demos. Your own board is optional for many contributions, but a green laptop run should not be presented as physical-board evidence.

## Choose evidence for the resource you changed

### Flash size

The size gate measures two package artifacts in bytes: stripped deployment `.py` source and MicroPython-compiled `.mpy` bytecode. Each library has committed ceilings in [Library size budgets](https://github.com/ChuMicro/ChuMicro/blob/main/size-budgets.toml), and exceeding a ceiling fails preflight. Test-support code is excluded.

These measurements describe the deployment package. They do not include firmware, measure total device storage use, or tell you how much RAM the library needs. A change can fit its flash budget while still needing separate allocation or timing evidence.

### Allocation churn and execution time

The optional command `python scripts/run.py bench` is not included in preflight. It requires MicroPython and CircuitPython unix ports and a committed benchmark baseline. It executes locally, may prepare missing runtime tools, and leaves the baseline unchanged.

Benchmarks run batches of selected operations, including Runner tick and WebSocket frame decode. Results include per-runtime allocation and timing measurements with baseline comparison verdicts. See [Benchmark cases and baselines](https://github.com/ChuMicro/ChuMicro/tree/main/scripts/benches) for the measured cases and references.

The heap benchmark divides the batch allocation delta by the operation count, with garbage collection disabled during the batch. Temporary objects therefore count toward allocation churn. This is not retained heap, peak RAM, or fragmentation. Those require separate measurements.

Timing is reported as median elapsed microseconds per operation across repeated batches, with minimum and maximum values also reported. Laptop results are useful for comparing regressions between revisions. They do not establish physical-board timing, which requires measurement on the board.

### Heap remaining after collection

The device-test reporter requires `gc.mem_free`. It collects garbage before taking pre-test and post-test samples and produces a module summary. This makes surviving allocations visible, rather than reporting all the temporary allocations counted by the churn benchmark.

The reporter has no automatic threshold or history comparison. Treat its output as evidence to examine, not as an enforced RAM budget or an automatic regression verdict.

## Compare revisions and sustained workloads

The project's measurement priority is repeatable comparisons across revisions and long-duration workloads, covering RAM, fragmentation, flash, and hot paths. Flash ceilings and selected benchmarks are implemented foundations. Board RAM and fragmentation tracking remain incomplete.

Choose evidence according to the change. Package-size results address flash, selected benchmarks address allocation churn and hot-path timing, and physical-board runs address behavior and timing on hardware. Long runs remain important when evaluating resource behavior over time.

Baseline comparisons require a measured case with an existing reference. Updating a baseline overwrites the committed reference, so investigate a regression before accepting a new baseline. A changed reference is not itself evidence that the regression is acceptable.

## Contribute without taking on publication infrastructure

Libraries, ideas, examples, and board reports are welcome. If you are unsure whether something fits, [Start a discussion](https://github.com/ChuMicro/ChuMicro/discussions) first. Follow [Adding a new library](contributing/new-library.md) for the library contribution workflow. Publication depends on project review and acceptance.

For an accepted library, the project owns the publication infrastructure: the published package, device bundle, source snapshot, and hosted documentation. Release assets include a versioned source archive. Authors do not need to operate separate release or hosting systems.

Experimental publication happens automatically after an accepted, versioned change passes the release gate. Stable promotion is a deliberate maintainer action. [Releases and promotion](contributing/releases.md) explains that workflow.

The project commits to keeping published versions available after the original author moves on. That commitment concerns the availability of released versions. It does not promise ongoing active maintenance, guaranteed fixes, or automatic acceptance of contributions.
