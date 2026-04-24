# Working with AI Agents

This project is set up to work well with AI coding agents — the rules are documented, the patterns are explicit, and agents can be productive here quickly. You don't have to use one, but if you're curious, this page explains what that looks like in practice, what agents are good at here, and how to try it yourself.

## What agents do in this workspace

An AI coding agent is a tool that reads code, proposes changes, runs tests, and iterates — like a very fast pair programmer that doesn't get tired. In this project, agents handle a lot of the repetitive work:

- **Writing tests** to hit the coverage gate
- **Generating documentation** from code and docstrings
- **Scaffolding** new libraries, examples, and boilerplate
- **Fixing lint errors** and formatting issues
- **Exploring the codebase** to answer "how does X work?" questions

Agents follow the same rules as human contributors — they run preflight, their code goes through review, and their PRs must pass CI. The difference is that agents have a stricter rule set ([`AGENTS.md`](../../AGENTS.md)) because they need explicit instructions for things a human would intuit, like "don't reformat code you didn't change" or "check whether this was already decided." Two agent-specific rules worth knowing about as a human collaborator:

- **`task-checkpoint`** — agents run preflight and commit after each unit of work, so the tree stays clean as you collaborate.
- **94 % coverage threshold** — humans target the 85 % baseline configured in `pyproject.toml`; agents pass `--coverage-threshold 94` on every `test` and `preflight` invocation per [Decision 0025](../../plans/decisions/0025-dual-coverage-thresholds.md). If your agent's coverage failure shows `94.0%`, that's why.

## What agents don't replace

Agents are capable tools, but some things still need a human in the loop:

- **Design direction** — choosing the right abstraction matters more than generating code quickly
- **Code review** — agent-generated PRs get the same scrutiny as any other
- **Hardware testing** — agents can't plug in an ESP32
- **Judgment calls** — whether an API *feels* right to use, whether a tradeoff is worth it

## How to use an agent on this project

If you're using an AI coding tool (GitHub Copilot, Cursor, Claude, etc.), you can point it at this workspace and it will be productive immediately. Here's why:

1. **`AGENTS.md`** in the project root contains the full rule set. Most AI tools detect and follow it automatically.
2. **The `.github/skills/` directory** has step-by-step instructions for common tasks (committing, testing, creating libraries). Agents read these before acting.
3. **`plans/decisions/`** gives agents context about *why* things are the way they are, so they don't propose changes that were already considered and rejected.

### Quick start with an agent

```
You: "Add a test for ticks_add with a negative delta at the wraparound boundary"

Agent: reads the codebase, writes the test, runs it, checks coverage,
       commits with a proper message — done.
```

```
You: "Create a new library called 'settings' for persistent key-value storage"

Agent: runs the scaffold command, generates starter code following the
       project patterns, writes tests to pass the coverage gate, builds docs —
       ready for your review.
```

The agent does the mechanical work. You steer the design and review the result.

### Tips

- **Be specific about what you want.** "Add edge-case tests for heartbeat near wraparound" is better than "improve tests."
- **Let the agent read first.** If it reads `AGENTS.md` and the relevant library code before writing, the output quality goes up significantly.
- **Review what it produces.** Agents write plausible code quickly. That's not the same as *correct* code. Read the diff like you would any PR.
- **Use agents for the boring parts.** Coverage gaps, docstring formatting, example scripts, boilerplate — these are where agents save the most time with the least risk.

## Why this project invests in agent support

Embedded development has a lot of mechanical overhead: cross-runtime compatibility, memory-efficient patterns, coverage gates, documentation standards, release automation. These are exactly the tasks where agents excel — they're consistent, they don't forget steps, and they don't mind writing the fifteenth test for a wraparound edge case.

By investing in clear rules (`AGENTS.md`), structured skills (`.github/skills/`), and documented decisions (`plans/decisions/`), the project makes agents effective. But those same investments also make the project easier for *humans* — clear rules, good docs, and explained decisions help everyone.

The goal isn't "AI writes all the code." The goal is that contributors — human or agent-assisted — spend their time on the interesting problems (API design, new libraries, hardware integration) rather than the mechanical ones (coverage, formatting, boilerplate).

## If this is your first time

If you've never used an AI coding agent, this project is a good place to try. The `AGENTS.md` file and skills system mean the agent already knows the project's rules — you don't have to teach it. Start with something small:

- Ask it to explain how a library works
- Ask it to write a test for an uncovered code path
- Ask it to generate an example script

You might be surprised how much of the "getting started" friction disappears when you can just ask.
