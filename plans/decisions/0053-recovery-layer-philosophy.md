# Decision 0053: Recovery-layer philosophy — host tools classify failures and coach the user

Status: `accepted`
Date: `2026-05-04`
Summary: Every workbench package that touches hardware ships `<package>.recovery`: closed-set failure-kind enum, classifier, per-kind recovery plans, CLI coaching loop wrapping entry points.
Related: Decision 0032 (workbench host tools), Decision 0033 (macOS CIRCUITPY hardening — concrete instance), Decision 0039 (firmware version floor — concrete instance).

## Context

`chumicro-deploy` ships an `InteractiveDeployer` with a `classify_deploy_failure()` function and a `DeployFailureKind` enum carrying ten distinct kinds (`PORT_UNAVAILABLE`, `CIRCUITPY_DRIVE_MISSING`, `MACOS_FSKIT_WEDGED`, `FLASH_COPY_FAILED`, `TRACEBACK_RETURNED`, …).  `chumicro-repl` wraps session start in a coached loop.  `chumicro-workspace`'s `doctor` and `status` commands surface classified problems with actionable next steps.  The pattern across all three: **don't just `raise`; classify the failure into a closed set of kinds and walk the user through a fix.**

This is a load-bearing UX commitment for the workbench surface — beginners running `python run.py deploy` for the first time get coached through "your CIRCUITPY drive isn't mounted, here's what to do" instead of a stack trace.  But the pattern lives only in code, established by precedent.  A future workbench package that defaults to plain `raise` would silently degrade the user experience.

## Decision

Every workbench package that touches hardware **must** ship a recovery layer with the following shape:

1. **A closed-set failure-kind enum** in `<package>.recovery` — every failure path the package can produce maps to one of N named kinds plus a fallback `UNKNOWN`.  No string-typed failure modes.  No untyped `Exception` propagation past the package boundary.
2. **A classifier function** — `classify_<thing>_failure(error: Exception) -> <Thing>FailureKind` that maps a raised exception (often from a child subprocess, pyserial, mpremote, or rsync) to a kind.  Pattern matches on exception type and message substrings; falls open on `UNKNOWN`.
3. **A recovery plan per kind** — for each kind, a `RecoveryPlan` containing user-facing diagnosis, the recommended fix, and the retry policy (one-shot, retryable, fatal).  Plans live alongside the classifier in `<package>.recovery`.
4. **The package's CLI wraps every entry point in a coaching loop** that catches failures, runs the classifier, prints the recovery plan, and offers the user a retry where the kind permits.  Uncaught exceptions reach the user only as a last resort.

When two workbench packages can produce the same failure (e.g., both `chumicro-deploy` and `chumicro-workspace` can hit `CIRCUITPY_DRIVE_MISSING` because both touch the FAT volume), they share the kind name and emit equivalent diagnostic prose — the user shouldn't see two different messages for the same underlying problem.

## Rejected

**Generic `try / except Exception: print(error); exit(1)`.**  Rejected: the user gets a `pyserial.SerialException` or a `subprocess.CalledProcessError` and has to figure out for themselves whether to plug the board in, switch the cable, or reinstall firmware.  This is the default Python behavior and the entire point of the workbench surface is to do better.

**One global recovery layer in a shared `chumicro_recovery` workbench package that every other workbench package imports.**  Rejected: violates Decision 0052's spirit (workbench packages don't import each other except for narrow shared protocols).  The recovery vocabulary is per-package because the failures are per-package; cross-package shared kinds are coincidence, not a basis for coupling.

**Skip the classifier and just print rich error messages with hints.**  Rejected: classification gives downstream agents (the `doctor` command, future automation) a structured signal to act on.  Strings are user-facing only; the kind enum is machine-readable.  A classifier also concentrates the "how do I tell these apart" knowledge in one place — the matcher patterns and the precedence ordering live next to each other where they can be tested.

## Consequences

- New workbench packages that touch hardware cannot ship without a `recovery` module + closed-set kind enum + per-kind plans.  Code review enforces this; preflight could enforce it via a lint that checks for the module's existence.
- Decision 0033's macOS hardening, Decision 0039's firmware-version-floor warning, and `chumicro-deploy`'s classifier ladder are concrete instances of the pattern, not exceptions to it.  When they evolve, the same shape continues — adding a kind, a classifier rule, a plan.
- The `chumicro-repl` `coached_session_start` and `chumicro-workspace doctor` / `status` commands are the user-facing artifacts of the pattern.  New workbench packages should follow the same naming where it fits.
- A future `chumicro-update` (OTA) workbench package will need its own recovery layer — bricked-firmware, partial-flash, signature-mismatch kinds.  This ADR is the precedent.
- The pattern is host-side only.  Library code on a device never tries to "coach the user" — the user isn't there; the application is.  Libraries `raise` typed exceptions and let the application decide.
