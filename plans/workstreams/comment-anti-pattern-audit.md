# Workstream: Code-comment anti-pattern audit

Status: **scoped, not started.**

## Purpose

AGENTS.md (commit `e13df11`) added a non-negotiable rule against historical / dated / removed-code framing in code comments — that content belongs in the commit message, ADR body, or workstream file, not in `.py` files that ship to flash on every deploy.  An initial scan during the workbench-deploy-reliability workstream surfaced a handful of pre-session violations that escaped the new-rule sweep; this workstream catalogs them and decides how aggressively to clean.

## Known live violations (initial scan, 2026-05-09)

`grep -rln "Surfaced 2026\|in the deploy-audit pass\|Earlier versions" workbench/ libraries/ scripts/ support/` returned two source files:

- `workbench/pytest-device/src/chumicro_pytest_device/plugin.py:752-753` — references "the deploy-audit pass" and "the ESP32-S2 USB-CDC double-reboot wedge (2026-05-03 Lolin S2 …)".
- `workbench/deploy/src/chumicro_deploy/circuitpython_transport.py:1728` — "Surfaced 2026-05-03 during the post-wedge cleanup bake".

Test fixtures with realistic boot_out.txt strings (`2026-04-16` etc.) are *data*, not narration — leave alone.  The same goes for ADR bodies and workstream files in `plans/`, which are journal-shaped by intent.

## Wider patterns to scan

The initial grep was narrow.  Worth a deeper sweep before deciding scope:

- `Surfaced YYYY-MM-DD` / `Discovered YYYY-MM-DD` — ad-hoc dated incidents.
- `Earlier versions` / `Previously this` / `We used to` — removed-code explanations.
- `in the X bake` / `in the X pass` / `in the X audit` — workstream-internal phase names that mean nothing to a cold reader.
- `workstream` / `Decision NNNN` / `plans/...md` references in publishable trees — already covered by `CHU006` for the latter, but the workstream-pointer shape may slip past the lint.
- Dated incidents inside docstring `Args:` / `Raises:` / `Returns:` blocks.

## Scope decisions to make before editing

- Do we extend `scripts/check_no_repo_refs.py` (CHU006) with a new lint code for dated-narration patterns, or stay with grep-and-edit?  A lint catches future regressions; a one-off pass leaves it to reviewer discipline.
- Is the rule strict everywhere, or do `# pragma: no cover`-style suppressions apply when the dated framing genuinely is the WHY (e.g. "fixed in firmware X.Y, drop this workaround when min-firmware bumps past it")?
- For docstrings: do we strip dated framing from `Args` / `Raises` / `Returns` blocks, or only from the prose preamble?  The latter is less invasive.

## Suggested first pass

1. Wider grep with the patterns above; build a punch-list per file.
2. Pick a representative file (probably `circuitpython_transport.py` since it has the most history) and rewrite as a sample to show the target shape.  Get user sign-off on the rewrite before doing the rest in bulk.
3. Decide CHU lint vs. one-off based on how many violations the wider grep found.
4. Apply.  Each file is a separate commit so the pre-existing pattern's removal is reviewable.
5. If a CHU lint lands, ratchet to `_everywhere` so the next addition can't slip in.

## Triggered by

- User feedback during workbench-deploy-reliability session, mid-2026-05-09: "many comments in this session are adding comments referring to changes and history. that is not what code comments are for."
- AGENTS.md commit `e13df11` formalised the rule but didn't sweep existing code.
