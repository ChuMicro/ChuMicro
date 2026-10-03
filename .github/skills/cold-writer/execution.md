# Isolated writer execution

## Requirements

Use Python 3.11 or newer and an authenticated `claude` executable on PATH.
From the repository root with its virtual environment active, run
`python .github/skills/cold-writer/scripts/write.py --help` for the arguments.
Use the same script path for drafting calls. `--check` validates a brief and
prints its SHA-256 without calling a model. Supply a review to validate readiness
as well. A normal run requires `--brief`, `--review`, and a new `--run-dir` beneath
the repository's `.scratch/` directory. Use `--model` only for an explicit model
choice. `--voice` names an entry in `_shared/voices/voices.json` whose
`voice_samples/<key>.md` excerpt goes into the system prompt as a register
sample; the default `plain` sends no excerpt, and `chumicro-docs` adds the README
excerpt for experiments. A named voice without an excerpt is a setup error. The
default timeout is ten minutes for one bounded drafting call.

The script invokes Claude with `--safe-mode`, a custom system prompt (the writer
instructions, followed by a register excerpt when a voice is requested), an empty
tool list, disabled skills, an empty MCP configuration, and no session persistence.
It excludes user, project, and local settings with an empty `--setting-sources`
value. Session-only `enabledPlugins` settings disable the built-in `agents-md`
and `telemetry` plugins. Global preferences remain unchanged. The response check
still requires an empty plugin list and rejects unexpected plugins.
It keeps the normal authentication path and permissions. It never resumes a
session or supplies the repository as an additional directory.

The [Claude CLI reference](https://code.claude.com/docs/en/cli-reference) documents
these controls. The launcher checks the installed CLI for its required flags and
fails if they are unavailable. Check the live documentation and the installed
help before changing the invocation. Managed policy remains in force.
When changing the invocation, retrieve the live Claude CLI reference and record
its URL and relevant observations in the research directory's `evidence.md`.
The [settings reference](https://code.claude.com/docs/en/settings-reference#enabledplugins)
describes per-plugin controls; `--settings` applies them to this invocation only.

## Inputs and output

The researcher supplies `brief.md`; the independent reviewer supplies
`brief-review.json`. The review hash must match the exact brief bytes. Changes to
the brief invalidate its review. The review record never enters the writer prompt.

Keep the brief, review, evidence ledger, and optional maintenance index in the
research directory. Set `--run-dir` to a new child such as `writer-1/`. The launcher
creates that child and owns its output files; research records stay in the parent.

Each successful run contains:

| File | Contents |
|---|---|
| `brief.md` | Exact reviewed input |
| `system-prompt.txt` | Writer instructions, plus the register excerpt when one was requested, exactly as sent |
| `response.jsonl` | Complete Claude response stream |
| `stderr.txt` | CLI diagnostics |
| `receipt.json` | Input hash, voice and excerpt hash, CLI version, requested and observed models, controls, result |
| `draft.md` | Successful nonempty model output |

After invocation begins, CLI errors, timeouts, and response-validation failures
preserve diagnostics and a failed receipt without producing `draft.md`. Setup
checks precede directory creation; those failures print an error and can leave
no run artifacts. Existing run directories are refused to prevent stale output
from being mistaken for a new draft. The launcher never installs the draft into docs.

The receipt checks the stream's initialization record for an empty tool list,
MCP servers, plugins, and skills. It rejects tool-use events and unsuccessful or
incomplete result records. Review the saved prompt and run the contamination
test when changing isolation controls. These checks establish the observed CLI
configuration; they are not an operating-system sandbox or proof of every
undisclosed model input.

## Failure handling

Exit 2 means invalid input, missing controls, or unavailable CLI. Fix the named
input or dependency and run again in a new directory. Exit 1 means the model run
failed, timed out, or violated the response contract. Inspect `stderr.txt`,
`response.jsonl`, and `receipt.json` before deciding what to retry.

If the configured model is unavailable, report it and use the user's model choice
or an already-authorized alternative. Record the actual response model. Never
describe a failed run as a draft or silently substitute the orchestrator's prose.

## Host portability

The research and review roles can run in Claude Code or Codex. The bundled writer
uses Claude's CLI so its isolation controls can be checked consistently. Another
writer backend needs equivalent input, tool, memory, completion, and provenance
checks plus the contamination test before this skill can claim isolation for it.

Claude discovers this repository's `.github/skills` through `.claude/skills`.
Codex can read the skill by its explicit repository path; use the repository's
existing `.agents/skills` convention when adding a discovery link.
