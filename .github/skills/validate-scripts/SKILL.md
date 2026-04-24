---
name: validate-scripts
description: How to write and run validation tests for scripts/ infrastructure code. Use this skill when creating, expanding, or running script tests.
---

# Script Validation

Validate `scripts/run.py` tasks by executing them directly with positive and negative inputs. Each section is a task — run the commands, check exit codes and output markers.

## How to use this skill

1. Run each command listed below.
2. Check the **exit code** (`echo $?` after each command, or check the command's return status).
3. Check for the **expected output** marker in stdout/stderr.
4. If a command fails unexpectedly, investigate before continuing.

**Pipe through `tail` or `grep`** for commands that produce large output — see the `large-output` skill.

**Skip destructive tasks** (like `new-library`) if the workspace has uncommitted changes — or clean up afterward.

## Notation

- ✅ = expected to succeed (exit code 0)
- ❌ = expected to fail (non-zero exit code) — this is the *correct* behavior
- 🔍 = check specific output text
- ⏭️ = skip if prerequisite not met (e.g., no runtime binary available)

---

## 1. No arguments / help

```bash
# ✅ No task → prints help, exits 1
python scripts/run.py
# 🔍 Output contains: "usage:" and "Available tasks" or subcommand list
# Exit code: 1

# ✅ Explicit help
python scripts/run.py -h
# 🔍 Output contains: "usage:"
# Exit code: 0
```

## 2. lint

```bash
# ✅ Lint the workspace
python scripts/run.py lint
# 🔍 Exit code 0 if clean; non-zero if violations exist
# 🔍 Output contains ruff check invocation lines starting with "+"
```

## 3. test

### Positive inputs

```bash
# ✅ Test all packages
python scripts/run.py test --all 2>&1 | tail -10
# 🔍 Output contains: "passed" (pytest summary)
# 🔍 Output contains: coverage report lines

# ✅ Test a specific library by name
python scripts/run.py test --libraries timing 2>&1 | tail -10
# 🔍 Output contains: "passed"

# ✅ Test multiple libraries
python scripts/run.py test --libraries timing,runner 2>&1 | tail -10
# 🔍 Output contains: "passed"

# ✅ Filter by library and test name
python scripts/run.py test -k timing/test_heartbeat 2>&1 | tail -10
# 🔍 Output contains: "passed" or "no tests ran"

# ✅ Filter by library, file, and test name
python scripts/run.py test -k timing/test_ticks/ticks_add 2>&1 | tail -10
# 🔍 Output contains: "passed" or "no tests ran"

# ✅ Multi-library filter
python scripts/run.py test -k timing/ticks_diff,runner/task_handle 2>&1 | tail -10
# 🔍 Output contains: "passed" or "no tests ran"

# ✅ No coverage mode
python scripts/run.py test --all --no-cov 2>&1 | tail -5
# 🔍 Output does NOT contain: "coverage" report
# 🔍 Output contains: "passed"

# ✅ Exit-first mode
python scripts/run.py test --all -x --no-cov 2>&1 | tail -5
# 🔍 Exit code 0 if all pass

# ✅ Verbose mode
python scripts/run.py test --all -v --no-cov 2>&1 | tail -20
# 🔍 Output contains individual test names (PASSED/FAILED per test)

# ✅ Default scope (changed packages or all)
python scripts/run.py test 2>&1 | tail -10
# 🔍 Output contains: "Changed packages detected:" or "Running for all packages"
```

### Negative inputs

```bash
# ❌ Unknown library name
python scripts/run.py test --libraries nonexistent 2>&1 | tail -5
# 🔍 Output contains: "Unknown package: nonexistent"
# Exit code: 1

# ❌ Malformed -k filter (no library prefix)
python scripts/run.py test -k just_a_test_name 2>&1 | tail -5
# 🔍 Output contains: "Invalid -k format"
# Exit code: 1

# ❌ -k filter with too many slashes
python scripts/run.py test -k a/b/c/d 2>&1 | tail -5
# 🔍 Output contains: "Invalid -k format"
# Exit code: 1

# ❌ -k filter references nonexistent library
python scripts/run.py test -k fakename/test_something 2>&1 | tail -5
# 🔍 Output contains: "Unknown library in -k: fakename"
# Exit code: 1

# ❌ -k filter references nonexistent test file
python scripts/run.py test -k timing/test_nonexistent_file/some_test 2>&1 | tail -5
# 🔍 Output contains: "Test file not found"
# Exit code: 1

# ❌ --all and --libraries are mutually exclusive
python scripts/run.py test --all --libraries timing 2>&1 | tail -5
# 🔍 Output contains: "not allowed with argument"
# Exit code: 2 (argparse error)
```

### CI-mirror sweep with optional functional phase

```bash
# ✅ Run the full CI mirror locally (no hardware needed)
python scripts/run.py preflight 2>&1 | tail -20
# 🔍 Output contains the step headers including:
#    "== test =="  "== test-scripts =="
#    "== test-micropython =="  "== test-circuitpython =="
# Exit code: 0
# ✅ Append the hardware-gated functional phases (requires connected boards)
python scripts/run.py preflight --with-functional 2>&1 | tail -20
# 🔍 Adds at the end:
#    "== test-libraries-functional =="
#    "== test-workbench-functional =="
```

## 4. build

```bash
# ✅ Build all publishable packages
python scripts/run.py build 2>&1 | tail -5
# 🔍 Output contains: "Built N package(s)"
# Exit code: 0
```

## 5. sync-ide

```bash
# ✅ Regenerate IDE configs
python scripts/run.py sync-ide
# 🔍 Output contains: "Updated .idea/runConfigurations/"
# 🔍 Output contains: "Updated .vscode/tasks.json"
# 🔍 Output contains: "Updated pyrightconfig.json"
# 🔍 Output contains: "Updated .idea/chumicro.iml" (or similar)
# Exit code: 0

# ✅ Idempotent — run again, same output
python scripts/run.py sync-ide
# Exit code: 0
```

## 6. docs

```bash
# ✅ Build docs for all libraries
python scripts/run.py docs --all 2>&1 | tail -10
# 🔍 Output contains: "== docs libraries/" for each library
# 🔍 Output contains: "Built:" lines
# Exit code: 0

# ✅ Build docs for a specific library
python scripts/run.py docs --libraries timing 2>&1 | tail -10
# 🔍 Output contains: "== docs libraries/timing"
# Exit code: 0

# ❌ Unknown library
python scripts/run.py docs --libraries nonexistent 2>&1 | tail -5
# 🔍 Output contains: "Unknown package"
# Exit code: 1
```

## 7. verify-examples

```bash
# ✅ Verify all examples
python scripts/run.py verify-examples --all 2>&1 | tail -10
# 🔍 Output contains: "OK:" lines and "All N example(s) verified"
# Exit code: 0

# ✅ Verify for a specific library
python scripts/run.py verify-examples --libraries timing
# 🔍 Output contains: "OK:" or "All N example(s) verified"
# Exit code: 0
```

## 8. new-library

**⚠️ This creates files. Clean up afterward: `rm -rf libraries/testvalidation && python scripts/run.py sync-ide`**

```bash
# ✅ Scaffold a new library
python scripts/run.py new-library testvalidation
# 🔍 Output contains: "Created libraries/testvalidation/"
# 🔍 Output contains IDE sync messages
# Exit code: 0
# 🔍 Verify files exist:
ls libraries/testvalidation/VERSION
ls libraries/testvalidation/pyproject.toml
ls libraries/testvalidation/src/chumicro_testvalidation/__init__.py
ls libraries/testvalidation/tests/conftest.py
ls libraries/testvalidation/mkdocs.yml
ls libraries/testvalidation/docs/index.md
ls libraries/testvalidation/examples/quickstart.py

# ❌ Scaffold same name again (already exists)
python scripts/run.py new-library testvalidation
# 🔍 Output contains: "Directory already exists"
# Exit code: 1

# Clean up
rm -rf libraries/testvalidation
python scripts/run.py sync-ide
```

## 9. check-version

```bash
# ✅ Check VERSION enforcement
python scripts/run.py check-version 2>&1 | tail -5
# 🔍 Output contains one of:
#    "OK:" (versions properly bumped)
#    "No release-relevant library changes detected"
#    "No changed files detected"
#    OR "FAIL:" if VERSION was not bumped (expected on some branches)
# Exit code: 0 if compliant, 1 if VERSION missing
```

## 10. check-api

```bash
# ✅ Check API breakages
python scripts/run.py check-api 2>&1 | tail -5
# 🔍 Output contains one of:
#    "OK:" or "SKIP:" (no previous tag or no changes)
#    "No release-relevant library changes detected"
#    OR "FAIL:" if breakages with insufficient bump
# Exit code: 0 if compliant, 1 if enforcement fails
```

## 11. test-libraries-functional

```bash
# ✅ Bare CLI run uses the default target device(s) from devices.yml
python scripts/run.py test-libraries-functional --library timing --function progress_on_runtime 2>&1 | tail -20
# 🔍 Output contains either:
#    "Device: <id>" lines for the defaults-selected board(s)
#    OR "Device config error" / "No matching devices found" if local board config is incomplete
# 🔍 `--runtime both` is an explicit alias for that same defaults-based dual-runtime selection
# 🔍 `--runtime micropython|circuitpython` overrides only the runtime set
# 🔍 `--micropython-device` / `--circuitpython-device` override the selected boards for those runtimes
# 🔍 CircuitPython RAM mode now probes live free heap and sends large inline payloads in multiple chunks; low-memory failures should mention the measured RAM budget and suggest flash mode
```

## 12. test-micropython

```bash
# ⏭️ Skip if MicroPython binary not available
# ✅ Run cross-runtime tests with auto-detection
python scripts/run.py test-micropython 2>&1 | tail -10
# 🔍 If binary found: runs tests, exit code 0 on pass
# 🔍 If binary not found: "MicroPython binary not found. Preparing unix-port runtime first."
#    Then either prepares and runs, or fails if build tools missing

# ❌ Explicit path to nonexistent binary
python scripts/run.py test-micropython --micropython-binary /nonexistent/path 2>&1 | tail -5
# 🔍 Output contains: "MicroPython binary not found: /nonexistent/path"
# Exit code: 1
```

## 13. test-circuitpython

```bash
# ⏭️ Skip if CircuitPython binary not available
# ✅ Run cross-runtime tests with auto-detection
python scripts/run.py test-circuitpython 2>&1 | tail -10
# 🔍 If binary found: runs tests, exit code 0 on pass
# 🔍 If binary not found: "CircuitPython binary not found. Preparing unix-port runtime first."

# ❌ Explicit path to nonexistent binary
python scripts/run.py test-circuitpython --circuitpython-binary /nonexistent/path 2>&1 | tail -5
# 🔍 Output contains: "CircuitPython binary not found: /nonexistent/path"
# Exit code: 1
```

## 14. test-all-runtimes

```bash
# ⏭️ Skip if runtime binaries not available
python scripts/run.py test-all-runtimes 2>&1 | tail -10
# 🔍 Output contains: "== test ==" followed by "== test-micropython ==" etc.
# Exit code: 0 if all pass
```

## 15. docs-deploy

```bash
# ❌ Missing required --channel
python scripts/run.py docs-deploy 2>&1 | tail -5
# 🔍 Output contains: "the following arguments are required: --channel"
# Exit code: 2

# ❌ Invalid channel value
python scripts/run.py docs-deploy --channel invalid 2>&1 | tail -5
# 🔍 Output contains: "invalid choice"
# Exit code: 2

# ✅ Valid channel (but may fail if gh-pages/mike not set up locally)
# python scripts/run.py docs-deploy --channel experimental 2>&1 | tail -10
# 🔍 Output starts with deploy messages

# ✅ With library filter
# python scripts/run.py docs-deploy --channel experimental --libraries timing 2>&1 | tail -10
```

## 16. preflight

```bash
# ✅ Full CI gate
python scripts/run.py preflight 2>&1 | tail -5
# 🔍 Success: "Preflight passed — required CI checks should pass."
# 🔍 Failure: "Preflight failed at: <step name>"
# This runs: lint, build, docs, test, verify-examples, check-version, check-api,
# test-micropython, test-circuitpython
```

## 17. setup

```bash
# ✅ Install dependencies (idempotent)
python scripts/run.py setup 2>&1 | tail -10
# 🔍 Output contains pip/uv install output
# 🔍 Output contains IDE sync messages
# Exit code: 0
```

## 18. prepare-micropython / prepare-circuitpython

```bash
# ⏭️ These clone and build runtime unix-ports — slow and require build tools
# Only run when validating the full prepare pipeline

# python scripts/run.py prepare-micropython
# 🔍 Output contains: clone/build progress
# 🔍 Creates .tools/micropython.path marker

# python scripts/run.py prepare-circuitpython
# 🔍 Output contains: clone/build progress
# 🔍 Creates .tools/circuitpython.path marker
```

## 19. Invalid/unknown task

```bash
# ❌ Unknown task name
python scripts/run.py nonexistent-task 2>&1 | tail -5
# 🔍 Output contains: "invalid choice" or "unrecognized arguments"
# Exit code: 2

# ❌ Typo in task name
python scripts/run.py tset 2>&1 | tail -5
# 🔍 Output contains: "invalid choice"
# Exit code: 2
```

## 20. validate-mip

```bash
# ⏭️ Requires MicroPython binary and network access to raw.githubusercontent.com
# ⏭️ Requires a public bundle repo to test against

# ❌ Missing required --bundle-repo
python scripts/run.py validate-mip 2>&1 | tail -5
# 🔍 Output contains: "the following arguments are required: --bundle-repo"
# Exit code: 2

# ✅ Validate specific libraries against a bundle repo
python scripts/run.py validate-mip --bundle-repo ChuMicro-Bundle-Experimental --libraries timing 2>&1 | tail -5
# 🔍 Output contains: "All 2 validations passed (2/2)."
# Exit code: 0

# ✅ Validate with dependency resolution
python scripts/run.py validate-mip --bundle-repo ChuMicro-Bundle-Experimental --libraries timing,runner 2>&1 | tail -5
# 🔍 Output contains: "All 4 validations passed (4/4)."
# Exit code: 0
```

---

## Validation checklist

Use this to track which tasks have been validated:

```
[ ] help / no args
[ ] lint
[ ] test --all
[ ] test --libraries <name>
[ ] test --libraries <name1>,<name2>
[ ] test -k <library>/<test>
[ ] test -k <library>/<file>/<test>
[ ] test -k <lib1>/<t1>,<lib2>/<t2>
[ ] test --no-cov
[ ] test -x
[ ] test -v
[ ] test (default scope)
[ ] test --libraries nonexistent        (negative)
[ ] test -k no_slash                    (negative)
[ ] test -k a/b/c/d                    (negative)
[ ] test -k fakename/test              (negative)
[ ] test -k lib/nonexistent_file/test  (negative)
[ ] test --all --libraries timing      (negative)
[ ] build
[ ] sync-ide
[ ] sync-ide (idempotent)
[ ] docs --all
[ ] docs --libraries <name>
[ ] docs --libraries nonexistent       (negative)
[ ] verify-examples --all
[ ] verify-examples --libraries <name>
[ ] new-library <name>                 (then clean up)
[ ] new-library <existing>             (negative)
[ ] check-version
[ ] check-api
[ ] test-libraries-functional
[ ] test-workbench-functional
[ ] test-functional
[ ] test-micropython
[ ] test-micropython --micropython-binary /bad  (negative)
[ ] test-circuitpython
[ ] test-circuitpython --circuitpython-binary /bad  (negative)
[ ] test-all-runtimes
[ ] docs-deploy (no --channel)         (negative)
[ ] docs-deploy --channel invalid      (negative)
[ ] preflight
[ ] preflight --with-functional        (slow — requires connected board)
[ ] setup
[ ] prepare-mpy-cross                  (slow — only when validating mpy build path)
[ ] validate-mip (no --bundle-repo)  (negative)
[ ] validate-mip --bundle-repo <repo> --libraries <name>
[ ] validate-mip --bundle-repo <repo> --libraries <dep-lib>  (deps)
[ ] validate-mip --staging-dir <dir> --libraries <name>      (pre-publish gate)
[ ] unknown task                       (negative)
```

## Running a full validation

To validate all non-destructive tasks in one pass:

```bash
# Fast tasks (< 30 seconds total)
python scripts/run.py 2>&1 | tail -3                           # help
python scripts/run.py lint 2>&1 | tail -3                      # lint
python scripts/run.py sync-ide                                  # sync-ide
python scripts/run.py build 2>&1 | tail -5                     # build
python scripts/run.py check-version 2>&1 | tail -5             # check-version
python scripts/run.py check-api 2>&1 | tail -5                 # check-api

# Note: test-libraries-functional is NOT fast when boards are connected — typical run is
# tens of seconds per board, longer in flash mode. Run it intentionally,
# not as part of an "all fast tasks" sweep.

# Medium tasks (< 2 minutes total)
python scripts/run.py test --all 2>&1 | tail -10                # test
python scripts/run.py verify-examples --all 2>&1 | tail -10    # verify-examples
python scripts/run.py docs --all 2>&1 | tail -10                # docs

# Negative cases (fast)
python scripts/run.py test --libraries nonexistent 2>&1 | tail -3
python scripts/run.py test -k bad_format 2>&1 | tail -3
python scripts/run.py test -k timing/test_nonexistent_file/x 2>&1 | tail -3
python scripts/run.py test --all --libraries timing 2>&1 | tail -3
python scripts/run.py docs-deploy 2>&1 | tail -3
python scripts/run.py docs-deploy --channel invalid 2>&1 | tail -3
python scripts/run.py validate-mip 2>&1 | tail -3
python scripts/run.py nonexistent-task 2>&1 | tail -3
python scripts/run.py test-micropython --micropython-binary /nonexistent 2>&1 | tail -3
python scripts/run.py test-circuitpython --circuitpython-binary /nonexistent 2>&1 | tail -3
```
