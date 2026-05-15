# Decision 0066: Agent-runnable CLIs need a non-interactive mode

Status: `accepted`
Date: `2026-05-14`
Related: [Decision 0054](0054-streaming-output-and-status-modes.md) (TTY auto-detection for output dispatcher selection — same detection signal, different decision), [Decision 0053](0053-recovery-layer-philosophy.md) (failure classification + recovery — distinct exit codes turn classified failures into machine-readable ones).

## Context

ChuMicro CLIs (`chumicro-workspace`, `chumicro-deploy`, `chumicro-repl`, `python scripts/run.py <task>`) serve two audiences: human contributors at a terminal, and agents / CI runners invoking them programmatically. The "human at a terminal" defaults — interactive wizards on missing configuration, long-running output tails on a deploy or REPL, stdin-blocking prompts on confirmation — break automation. An agent calling `chumicro-workspace bootstrap` and hitting a port-pick wizard has no path to recover except killing the process; a CI invocation of `python scripts/run.py deploy-example timing circuitpython_blink` followed by a `tail()` follow-mode never terminates.

The opposite default — strictly non-interactive — would harm the human contributor: a fresh-clone bootstrap with no `devices.yml` would error out instead of running the device-pick wizard, and `chumicro-repl` would exit before its `tail` follow-up could surface anything useful.

Both audiences are first-class. The same code paths need to serve both correctly without the caller having to remember which subcommand requires which flag.

## Decision

Any chumicro CLI subcommand or `scripts/run.py` task callable by both humans and agents must:

1. **Auto-detect interactivity via TTY presence.** Default `interactive = sys.stdin.isatty()`. Honored by all subcommands that conditionally prompt or tail.

2. **Expose `--non-interactive` as the explicit meta-flag override.** Forces non-interactive mode regardless of TTY. Per-feature flags (`--no-tail`, `--no-auto-register`, `--no-wizard`) compose underneath it; passing `--non-interactive` implies all of them.

3. **Never prompt in non-interactive mode.** Wizard fall-throughs (`bootstrap` port-pick, `init` template-pick, missing-`devices.yml` first-time setup) fire only when interactive. In non-interactive mode the subcommand either uses an explicit `--<arg>` value or fails with a distinct exit code.

4. **Never tail / drop into REPL by default in non-interactive mode.** Deploy commands that default to `tail()` follow-mode in interactive use exit after the deploy completes in non-interactive use. Long-running watches stay opt-out via `--no-tail` for interactive contexts and are off-by-default in non-interactive.

5. **Use distinct exit codes for distinct failure modes.** An agent must be able to branch on the exit code without parsing stderr. Categories: success (`0`), precheck failure (e.g. no device registered), runtime failure (e.g. deploy failed), user-cancelled wizard (interactive only), invalid usage. The specific code mapping per subcommand is documented in that subcommand's `--help`.

Inherently-interactive subcommands (no agent use case) — `chumicro-workspace bootstrap` in its default wizard form, standalone REPL drops — declare TTY requirement in their `--help` and exit cleanly with a clear error if invoked without one. They're not agent-callable; that's a design choice, not a defect.

This complements Decision 0054, which uses the same TTY signal to pick output dispatcher mode (status vs interleave vs quiet). The two decisions are orthogonal: an interactive context gets both the wizard *and* the status-mode dispatcher; a non-interactive context gets neither prompts nor the status-mode failure-only dump.

## Consequences

### Positive

- Agents and CI runners can call any subcommand without escape-key gymnastics around wizard prompts or hanging on tails.
- The same code path serves both audiences — no separate "agent CLI" surface to maintain.
- Distinct exit codes turn "subcommand failed" into "subcommand failed for *this specific reason*," which agent coaching loops (Decision 0053) can branch on without parsing stderr.
- `--non-interactive` composes — adding a new prompt or a new long-running mode to a subcommand doesn't require a new top-level flag; both gate on the same TTY-derived boolean.

### Negative / tradeoffs

- Every new subcommand has to consider its interactive/non-interactive shape during design, not retrofit it later. A subcommand that ships interactive-only and is later wanted from CI is more work than one designed for both up front.
- Inherently-interactive subcommands (wizard-only) need explicit `--help` documentation and a clean TTY-required error path; silently hanging on stdin in CI is a regression.

### Neutral

- TTY auto-detection is the right default *because* most invocations from agents come without a TTY. Tools that allocate a PTY (some pexpect / docker-compose contexts) will hit interactive paths even when the caller isn't a human — flagged separately as a `CHUMICRO_NON_INTERACTIVE=1` env-var override if it becomes a real problem; YAGNI today.

## Alternatives considered

- **Always interactive (status quo before this decision).** Forces every agent / CI invocation to either avoid the affected subcommands or kill them. Hidden cost: chumicro's own automation gradually accumulated workarounds (`yes ""` piping, explicit kill timeouts, output-parsing for prompts) — exactly the inversion this decision avoids.
- **Always non-interactive (every subcommand errors on missing config).** Loses the wizard onramp that makes first-time setup work. Fresh-clone contributors would face a wall of `--<arg>` flags instead of a guided port-pick. The cost lands on the human audience for a benefit the agent audience already gets via TTY detection.
- **Separate `--agent` CLI surface (e.g. `chumicro-workspace-agent bootstrap`).** Doubles the maintenance surface and creates drift opportunities. The TTY signal is a free disambiguator; no need to split the namespace.
- **Per-subcommand opt-in via individual flags only (no `--non-interactive` meta-flag).** Forces the caller to remember which flags exist per subcommand. The meta-flag composes — it's the right shape for a category-spanning rule.
