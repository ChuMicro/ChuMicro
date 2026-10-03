"""Draft a documentation page from a reviewed brief in an isolated Claude session."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
VOICES = ROOT / ".github" / "skills" / "_shared" / "voices"
DEFAULT_VOICE = "plain"
EXCERPT_VOICE = "chumicro-docs"
CHECKS = {"accuracy", "coverage", "reader_sequence", "prose_independence"}
REQUIRED_FLAGS = (
    "--safe-mode", "--system-prompt", "--tools", "--disable-slash-commands",
    "--strict-mcp-config", "--mcp-config", "--no-session-persistence",
    "--output-format", "--verbose", "--model", "--permission-mode",
    "--setting-sources", "--settings",
)
# Built-in plugins remain available in safe mode on current Claude CLI releases.
SESSION_SETTINGS = {"enabledPlugins": {"agents-md@builtin": False, "telemetry@builtin": False}}
WRITER_PROMPT = (
    "Write the documentation page the brief describes, for the reader it names, the "
    "way you would explain it to that person at their desk. Use the brief's commands, "
    "code, output lines, warnings, and link targets exactly, and say everything else "
    "in your own sentences. Keep the page inside the brief's length range; items the "
    "brief marks Supporting are optional and belong only where a required sentence "
    "needs them. Return only the finished page in Markdown. If a fact the page needs "
    "is missing, return BRIEF_INCOMPLETE followed by what is missing."
)
REGISTER_PROMPT = (
    "Match the register of the passage below, which comes from a different page: its "
    "plain words, sentence length, and pace. Take none of its facts or wording."
)


def read_brief(path: Path) -> tuple[str, str]:
    """Read UTF-8 brief bytes and return their text and SHA-256 digest."""
    content = path.read_bytes()
    text = content.decode("utf-8")
    if not text.strip():
        raise ValueError("brief is empty; supply the researched writer brief")
    return text, hashlib.sha256(content).hexdigest()


def check_review(path: Path, digest: str) -> None:
    """Reject reviews that leave gaps or refer to different brief bytes."""
    review = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(review, dict):
        raise ValueError(f"{path}: review must be a JSON object")
    if review.get("brief_sha256") != digest:
        raise ValueError(
            f"{path}: review hash differs from brief; expected {digest!r}, "
            f"received {review.get('brief_sha256')!r}; review the changed brief"
        )
    if review.get("status") != "ready" or review.get("blocking_findings") != []:
        raise ValueError(f"{path}: review is blocked; resolve its findings before writing")
    if "checks" not in review:
        raise ValueError(f"{path}: missing checks object")
    checks = review["checks"]
    if not isinstance(checks, dict):
        raise ValueError(f"{path}: checks must be an object; received {type(checks).__name__}")
    failed_checks = [
        f"{name}={checks[name]!r}" if name in checks else f"{name}=<missing>"
        for name in sorted(CHECKS) if checks.get(name) is not True
    ]
    if failed_checks:
        raise ValueError(f"{path}: review checks must be true: {', '.join(failed_checks)}")
    if not isinstance(review.get("reviewer"), str) or not review["reviewer"].strip():
        raise ValueError(f"{path}: review must identify its actual reviewer")
    if not isinstance(review.get("notes"), str) or not review["notes"].strip():
        raise ValueError(f"{path}: review notes must identify the evidence inspected")


def excerpt(voice: str) -> str:
    """Return the prose under a voice's excerpt headings through the shared loader, or "" when it has none."""
    if str(VOICES) not in sys.path:
        sys.path.insert(0, str(VOICES))
    from voice_sample import load_voice_sample

    return load_voice_sample(voice)


def load_register_sample(voice: str) -> str:
    """Return the register excerpt for a registry voice; `plain` returns "" and a voice without one is an error."""
    if voice == "plain":
        return ""
    registry = json.loads((VOICES / "voices.json").read_text(encoding="utf-8"))
    if voice not in registry.get("voices", {}):
        raise ValueError(f"unknown voice {voice!r}; registry keys live in {VOICES / 'voices.json'}")
    sample = excerpt(voice)
    if not sample:
        raise ValueError(
            f"voice {voice!r} has no excerpt under {VOICES / 'voice_samples'}; add one or pass --voice plain"
        )
    return sample


def system_prompt(sample: str) -> str:
    """Return the writer instructions, followed by the register instruction and excerpt when one is given."""
    if not sample:
        return WRITER_PROMPT
    return f"{WRITER_PROMPT}\n\n{REGISTER_PROMPT}\n\n{sample}"


def command(binary: str, model: str, prompt: str) -> list[str]:
    """Build a tool-free, customization-free print invocation carrying the composed system prompt."""
    return [
        binary, "--print", "--safe-mode", "--system-prompt", prompt,
        "--tools", "", "--disable-slash-commands", "--strict-mcp-config",
        "--mcp-config", '{"mcpServers":{}}', "--no-session-persistence",
        "--output-format", "stream-json", "--verbose", "--model", model,
        "--permission-mode", "dontAsk",
        "--setting-sources", "", "--settings", json.dumps(SESSION_SETTINGS),
    ]


def require_type(value: object, expected: type, location: str) -> None:
    """Name a malformed response field before its value is accessed."""
    if not isinstance(value, expected):
        raise ValueError(
            f"{location}: expected {expected.__name__}; received {type(value).__name__}"
        )


def parse_response(text: str) -> tuple[str, dict]:
    """Require empty capabilities, a completed response, and nonempty Markdown."""
    events = [json.loads(line) for line in text.splitlines() if line.strip()]
    if not events:
        raise ValueError("response stream is empty")
    for index, event in enumerate(events):
        require_type(event, dict, f"event[{index}]")
        require_type(event.get("type"), str, f"event[{index}].type")
    initializations = [
        event for event in events
        if event.get("type") == "system" and event.get("subtype") == "init"
    ]
    if len(initializations) != 1:
        raise ValueError("response must contain one initialization record")
    initialization = initializations[0]
    initialization_index = events.index(initialization)
    require_type(initialization.get("model"), str, f"event[{initialization_index}].model")
    for key in ("tools", "mcp_servers", "plugins", "skills"):
        if initialization.get(key) != []:
            raise ValueError(f"isolation check failed: initialization {key} is not empty")
    models = set()
    stop_reasons = []
    for index, event in enumerate(events):
        if event.get("type") != "assistant":
            continue
        location = f"event[{index}].message"
        message = event.get("message")
        require_type(message, dict, location)
        model = message.get("model")
        require_type(model, str, f"{location}.model")
        if not model.strip():
            raise ValueError(f"{location}.model: expected nonempty str; received empty str")
        models.add(model)
        reason = message.get("stop_reason")
        if reason is not None:
            require_type(reason, str, f"{location}.stop_reason")
            stop_reasons.append(reason)
        content = message.get("content")
        require_type(content, list, f"{location}.content")
        for block_index, block in enumerate(content):
            block_location = f"{location}.content[{block_index}]"
            require_type(block, dict, block_location)
            require_type(block.get("type"), str, f"{block_location}.type")
            if block.get("type") in {"tool_use", "server_tool_use"}:
                raise ValueError("writer attempted a tool call")
    results = [event for event in events if event.get("type") == "result"]
    if len(results) != 1 or events[-1] != results[0]:
        raise ValueError("response stream lacks one final result")
    result = results[0]
    if result.get("is_error") is not False or result.get("subtype") != "success":
        raise ValueError("Claude reported an unsuccessful result; inspect response.jsonl")
    if any(reason not in {"end_turn", "stop_sequence"} for reason in stop_reasons):
        raise ValueError("writer response stopped before normal completion")
    result_reason = result.get("stop_reason")
    if result_reason is not None:
        require_type(result_reason, str, f"event[{len(events) - 1}].stop_reason")
    if result_reason not in {None, "end_turn", "stop_sequence"}:
        raise ValueError("final result reports incomplete generation")
    draft = result.get("result")
    if not isinstance(draft, str) or not draft.strip():
        raise ValueError("writer returned empty output")
    if "BRIEF_INCOMPLETE" in draft:
        raise ValueError("writer found missing requirements; repair and re-review the brief")
    if not models:
        raise ValueError("response stream does not identify the actual model")
    return draft.strip() + "\n", {
        "initialization_model": initialization.get("model"),
        "response_models": sorted(models),
        "tools": [], "mcp_servers": [], "plugins": [], "skills": [],
        "result_subtype": result["subtype"],
        "result_stop_reason": result_reason,
        "stop_reasons": stop_reasons,
    }


def new_run_directory(path: Path) -> Path:
    """Create a fresh run directory inside repository scratch storage."""
    resolved = path.resolve()
    scratch = (ROOT / ".scratch").resolve()
    if not resolved.is_relative_to(scratch) or resolved == scratch:
        raise ValueError("--run-dir must be a new subdirectory of this repository's .scratch/")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.mkdir(exist_ok=False)
    return resolved


def run_writer(brief: str, digest: str, directory: Path, model: str, timeout: int, voice: str) -> None:
    """Run Claude once with the brief and the voice's register excerpt, retain diagnostics, and save only a successful draft."""
    sample = load_register_sample(voice)
    prompt = system_prompt(sample)
    binary = shutil.which("claude")
    if binary is None:
        raise ValueError("claude is unavailable on PATH; install and authenticate the CLI")
    help_result = subprocess.run(
        [binary, "--help"], capture_output=True, text=True, timeout=30, check=False,
    )
    missing = [flag for flag in REQUIRED_FLAGS if flag not in help_result.stdout.split()]
    if help_result.returncode or missing:
        raise ValueError(f"Claude CLI lacks required controls: {missing}; inspect claude --help")
    version = subprocess.run(
        [binary, "--version"], capture_output=True, text=True, timeout=30, check=True,
    ).stdout.strip()
    run_path = new_run_directory(directory)
    (run_path / "brief.md").write_bytes(brief.encode("utf-8"))
    (run_path / "system-prompt.txt").write_text(prompt, encoding="utf-8")
    receipt = {
        "status": "running", "brief_sha256": digest, "cli_version": version,
        "requested_model": model, "safe_mode": True, "session_resumed": False,
        "setting_sources": [], "session_settings": SESSION_SETTINGS,
        "voice": voice,
        "sample_sha256": hashlib.sha256(sample.encode()).hexdigest() if sample else None,
        "system_prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
    }
    receipt_path = run_path / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    environment = os.environ.copy()
    # Headless calls are independent sessions even when invoked from Claude Code.
    environment.pop("CLAUDECODE", None)
    environment["CLAUDE_CODE_SAFE_MODE"] = "1"
    print(f"Writing with {model}, voice {voice}; one isolated call, up to {timeout}s. Artifacts: {run_path}",
          file=sys.stderr, flush=True)
    try:
        with (run_path / "response.jsonl").open("w", encoding="utf-8") as output:
            with (run_path / "stderr.txt").open("w", encoding="utf-8") as errors:
                completed = subprocess.run(
                    command(binary, model, prompt), input=brief, text=True,
                    cwd=run_path, env=environment, stdout=output, stderr=errors,
                    timeout=timeout, check=False,
                )
        receipt["exit_code"] = completed.returncode
        if completed.returncode:
            raise ValueError(f"Claude exited {completed.returncode}; inspect {run_path / 'stderr.txt'}")
        draft, observed = parse_response((run_path / "response.jsonl").read_text(encoding="utf-8"))
        receipt.update(observed)
        (run_path / "draft.md").write_text(draft, encoding="utf-8")
        receipt["status"] = "success"
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        receipt.update(status="failed", error=str(error))
        raise RuntimeError(f"writer failed: {error}; artifacts retained at {run_path}") from error
    finally:
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(run_path / "draft.md")


def main() -> int:
    """Validate arguments and return distinct input and generation failure codes."""
    parser = argparse.ArgumentParser(
        description="Write a page from a reviewed brief. Exit 2: input/setup. Exit 1: writer failure.",
        epilog="First use --brief PATH --check to obtain the digest for the independent reviewer.",
    )
    parser.add_argument("--brief", required=True, type=Path, help="UTF-8 writer brief")
    parser.add_argument("--review", type=Path, help="independent brief-review JSON")
    parser.add_argument("--run-dir", type=Path, help="new directory under repository .scratch/")
    parser.add_argument("--check", action="store_true", help="validate input and print its digest; no model call")
    parser.add_argument("--model", default="opus", help="Claude model, default opus")
    parser.add_argument("--voice", default=DEFAULT_VOICE,
                        help=f"registry voice whose excerpt is added to the prompt; the default {DEFAULT_VOICE} sends none, "
                             f"and {EXCERPT_VOICE} adds the README register excerpt for experiments")
    # Ten minutes bounds a single long draft without requiring repeated prompts.
    parser.add_argument("--timeout", type=int, default=600, help="model call deadline in seconds (default 600)")
    arguments = parser.parse_args()
    try:
        brief, digest = read_brief(arguments.brief)
        if arguments.review:
            check_review(arguments.review, digest)
        if arguments.check:
            sample = load_register_sample(arguments.voice)
            print(json.dumps({
                "brief_sha256": digest, "review_checked": bool(arguments.review), "voice": arguments.voice,
                "sample_sha256": hashlib.sha256(sample.encode()).hexdigest() if sample else None,
            }))
            return 0
        if not arguments.review or not arguments.run_dir:
            raise ValueError("writing requires --review and --run-dir")
        if arguments.timeout <= 0:
            raise ValueError("--timeout must be positive")
        run_writer(brief, digest, arguments.run_dir, arguments.model, arguments.timeout, arguments.voice)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"input/setup error: {error}", file=sys.stderr)
        return 2
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
