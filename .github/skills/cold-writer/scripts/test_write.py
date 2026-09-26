"""Exercise the cold-writer launcher without calling a model or touching a board."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import write

PLAIN = "plain"


def events() -> list[dict]:
    """Return a minimal successful tool-free response stream."""
    return [
        {"type": "system", "subtype": "init", "model": "fixture-model",
         "tools": [], "mcp_servers": [], "plugins": [], "skills": []},
        {"type": "assistant", "message": {"model": "fixture-model",
         "stop_reason": "end_turn", "content": [{"type": "text", "text": "# Hello"}]}},
        {"type": "result", "subtype": "success", "is_error": False, "result": "# Hello"},
    ]


def stream(records: list[dict]) -> str:
    """Encode fixture events in the CLI's line-delimited format."""
    return "\n".join(json.dumps(record) for record in records)


class WriterTests(unittest.TestCase):
    """Check input approval, register-sample handling, observed isolation, and retained failure artifacts."""

    @classmethod
    def setUpClass(cls):
        scratch = write.ROOT / ".scratch" / "cold-writer"
        scratch.mkdir(parents=True, exist_ok=True)
        cls.fixtures = Path(tempfile.mkdtemp(prefix="unit-", dir=scratch))

    def setUp(self):
        self.case = self.fixtures / self.id().split(".")[-1]
        self.case.mkdir()
        self.brief = self.case / "brief.md"
        self.brief.write_bytes(b"A verified exercise.\r\n")
        self.digest = hashlib.sha256(self.brief.read_bytes()).hexdigest()
        self.review = {
            "brief_sha256": self.digest, "reviewer": "fixture reviewer",
            "status": "ready", "blocking_findings": [],
            "checks": dict.fromkeys(write.CHECKS, True),
            "notes": "Inspected the fixture source.",
        }

    def save_review(self, review: dict) -> Path:
        path = self.case / "review.json"
        path.write_text(json.dumps(review), encoding="utf-8")
        return path

    def test_exact_bytes_hash(self):
        text, digest = write.read_brief(self.brief)
        self.assertIn("\r\n", text)
        self.assertEqual(digest, self.digest)

    def test_empty_brief(self):
        self.brief.write_text(" \n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "empty"):
            write.read_brief(self.brief)

    def test_approved_review(self):
        write.check_review(self.save_review(self.review), self.digest)

    def test_review_rejections(self):
        changes = [
            ("brief_sha256", "stale"), ("status", "blocked"),
            ("blocking_findings", ["missing warning"]), ("checks", {}),
            ("reviewer", ""), ("notes", ""),
        ]
        for key, value in changes:
            with self.subTest(key=key):
                review = copy.deepcopy(self.review)
                review[key] = value
                with self.assertRaises(ValueError):
                    write.check_review(self.save_review(review), self.digest)
        review = copy.deepcopy(self.review)
        review["checks"]["accuracy"] = "true"
        with self.assertRaises(ValueError):
            write.check_review(self.save_review(review), self.digest)

    def test_review_hash_diagnostic(self):
        self.review["brief_sha256"] = "stale-hash"
        path = self.save_review(self.review)
        with self.assertRaises(ValueError) as error:
            write.check_review(path, self.digest)
        for detail in (str(path), self.digest, "stale-hash"):
            self.assertIn(detail, str(error.exception))

    def test_review_checks_diagnostic(self):
        self.review["checks"]["accuracy"] = False
        self.review["checks"]["coverage"] = "true"
        del self.review["checks"]["reader_sequence"]
        path = self.save_review(self.review)
        with self.assertRaises(ValueError) as error:
            write.check_review(path, self.digest)
        message = str(error.exception)
        for detail in (str(path), "accuracy=False", "coverage='true'", "reader_sequence=<missing>"):
            self.assertIn(detail, message)
        self.assertNotIn("prose_independence", message)

    def test_missing_or_invalid_checks_diagnostic(self):
        del self.review["checks"]
        with self.assertRaisesRegex(ValueError, "missing checks object"):
            write.check_review(self.save_review(self.review), self.digest)
        self.review["checks"] = None
        with self.assertRaisesRegex(ValueError, "checks must be an object; received NoneType"):
            write.check_review(self.save_review(self.review), self.digest)

    def test_register_sample_is_excerpt_prose_only(self):
        sample = write.load_register_sample(write.DEFAULT_VOICE)
        source = (write.VOICES / "voice_samples" / f"{write.DEFAULT_VOICE}.md").read_text(encoding="utf-8")
        self.assertTrue(sample)
        self.assertIn(sample.splitlines()[0], source)
        for header in ("- Person:", "- Source:", "- Rights:", "## Excerpt"):
            self.assertIn(header, source)
            self.assertNotIn(header, sample)

    def test_plain_voice_sends_no_sample(self):
        self.assertEqual(write.load_register_sample(PLAIN), "")
        self.assertEqual(write.system_prompt(""), write.WRITER_PROMPT)
        self.assertNotIn("passage", write.WRITER_PROMPT)

    def test_system_prompt_places_sample_after_instructions(self):
        prompt = write.system_prompt("An excerpt paragraph.")
        self.assertTrue(prompt.startswith(write.WRITER_PROMPT))
        self.assertIn(write.REGISTER_PROMPT, prompt)
        self.assertTrue(prompt.endswith("An excerpt paragraph."))

    def test_unknown_and_excerptless_voices_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown voice 'no-such-voice'"):
            write.load_register_sample("no-such-voice")
        registry = self.case / "voices"
        registry.mkdir()
        (registry / "voices.json").write_text(json.dumps({"voices": {"silent": "A voice."}}), encoding="utf-8")
        with patch.object(write, "VOICES", registry):
            with patch.object(write, "excerpt", return_value=""):
                with self.assertRaisesRegex(ValueError, "no excerpt"):
                    write.load_register_sample("silent")

    def test_command_isolation_flags(self):
        arguments = write.command("claude", "opus", "instructions")
        for flag in write.REQUIRED_FLAGS:
            self.assertIn(flag, arguments)
        self.assertEqual(arguments[arguments.index("--system-prompt") + 1], "instructions")
        self.assertEqual(arguments[arguments.index("--tools") + 1], "")
        self.assertEqual(arguments[arguments.index("--mcp-config") + 1], '{"mcpServers":{}}')
        for flag in ("--resume", "--continue", "--add-dir", "--dangerously-skip-permissions"):
            self.assertNotIn(flag, arguments)

    def test_successful_stream(self):
        records = events()
        records[-1]["stop_reason"] = "end_turn"
        draft, receipt = write.parse_response(stream(records))
        self.assertEqual(draft, "# Hello\n")
        self.assertEqual(receipt["response_models"], ["fixture-model"])
        self.assertEqual(receipt["result_stop_reason"], "end_turn")

    def test_flag_names_checked_exactly(self):
        brief, digest = write.read_brief(self.brief)
        help_text = " ".join(write.REQUIRED_FLAGS).replace("--model", "--fallback-model")
        help_result = subprocess.CompletedProcess([], 0, help_text, "")
        with patch.object(write.shutil, "which", return_value="claude"):
            with patch.object(write.subprocess, "run", return_value=help_result):
                with self.assertRaisesRegex(ValueError, "lacks required controls.*--model"):
                    write.run_writer(brief, digest, self.case / "run", "opus", 1, PLAIN)
        self.assertFalse((self.case / "run").exists())

    def test_session_settings_isolation(self):
        arguments = write.command("claude", "opus", "instructions")
        self.assertEqual(arguments[arguments.index("--setting-sources") + 1], "")
        settings = json.loads(arguments[arguments.index("--settings") + 1])
        self.assertEqual(settings, {"enabledPlugins": {
            "agents-md@builtin": False, "telemetry@builtin": False,
        }})

    def test_loaded_capabilities_rejected(self):
        for key in ("tools", "mcp_servers", "plugins", "skills"):
            for value in (["unexpected"], None):
                with self.subTest(key=key, value=value):
                    records = events()
                    records[0][key] = value
                    with self.assertRaisesRegex(ValueError, "isolation"):
                        write.parse_response(stream(records))

    def test_tool_call_rejected(self):
        records = events()
        records[1]["message"]["content"] = [{"type": "tool_use", "name": "Read"}]
        with self.assertRaisesRegex(ValueError, "tool call"):
            write.parse_response(stream(records))

    def test_incomplete_responses_rejected(self):
        for field, value in (("is_error", True), ("subtype", "error_max_turns"),
                             ("result", ""), ("result", "BRIEF_INCOMPLETE: board"),
                             ("stop_reason", "max_tokens")):
            with self.subTest(field=field, value=value):
                records = events()
                records[-1][field] = value
                with self.assertRaises(ValueError):
                    write.parse_response(stream(records))

    def test_malformed_streams_rejected(self):
        for text in ("", "not json", "[]", stream(events()[1:]),
                     stream(events()[:-1]), stream(events() + [events()[-1]])):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    write.parse_response(text)

    def test_model_and_stop_reason_checked(self):
        for field, value in (("model", None), ("stop_reason", "max_tokens")):
            with self.subTest(field=field):
                records = events()
                records[1]["message"][field] = value
                with self.assertRaises(ValueError):
                    write.parse_response(stream(records))

    def test_nested_response_types(self):
        cases = [
            (None, "event[1].message", "dict", "NoneType"),
            ({"model": []}, "event[1].message.model", "str", "list"),
            ({"model": "fixture", "stop_reason": []}, "event[1].message.stop_reason", "str", "list"),
            ({"model": "fixture", "content": None}, "event[1].message.content", "list", "NoneType"),
            ({"model": "fixture", "content": [None]}, "event[1].message.content[0]", "dict", "NoneType"),
            ({"model": "fixture", "content": [{"type": []}]}, "event[1].message.content[0].type", "str", "list"),
        ]
        for message, location, expected, received in cases:
            with self.subTest(location=location):
                records = events()
                records[1]["message"] = message
                with self.assertRaises(ValueError) as error:
                    write.parse_response(stream(records))
                self.assertEqual(str(error.exception), f"{location}: expected {expected}; received {received}")
        for index, field, value in ((0, "model", []), (2, "stop_reason", {})):
            with self.subTest(index=index, field=field):
                records = events()
                records[index][field] = value
                with self.assertRaises(ValueError) as error:
                    write.parse_response(stream(records))
                self.assertIn(f"event[{index}].{field}", str(error.exception))

    def test_new_directory_only(self):
        destination = self.case / "run"
        self.assertEqual(write.new_run_directory(destination), destination)
        with self.assertRaises(FileExistsError):
            write.new_run_directory(destination)

    def test_directory_scope(self):
        for destination in (write.ROOT, write.ROOT / ".scratch", write.ROOT / "outside-scratch"):
            with self.subTest(path=destination):
                with self.assertRaisesRegex(ValueError, "subdirectory"):
                    write.new_run_directory(destination)

    def test_symlink_escape(self):
        link = self.case / "escape"
        link.symlink_to(write.ROOT, target_is_directory=True)
        with self.assertRaises(ValueError):
            write.new_run_directory(link / "escape-run")

    def fake_cli(self, outcome: str, records: list[dict] | None = None):
        def run(arguments, **kwargs):
            if arguments[-1] == "--help":
                return subprocess.CompletedProcess(arguments, 0, " ".join(write.REQUIRED_FLAGS), "")
            if arguments[-1] == "--version":
                return subprocess.CompletedProcess(arguments, 0, "fixture CLI", "")
            kwargs["stdout"].write(stream(events() if records is None else records))
            if outcome == "timeout":
                raise subprocess.TimeoutExpired(arguments, 1)
            return subprocess.CompletedProcess(arguments, 1 if outcome == "failure" else 0)
        return run

    def test_run_artifacts_and_failures(self):
        brief, digest = write.read_brief(self.brief)
        sample = write.load_register_sample(write.DEFAULT_VOICE)
        for outcome in ("success", "failure", "timeout"):
            with self.subTest(outcome=outcome):
                directory = self.case / outcome
                with patch.object(write.shutil, "which", return_value="claude"):
                    with patch.object(write.subprocess, "run", side_effect=self.fake_cli(outcome)):
                        if outcome == "success":
                            write.run_writer(brief, digest, directory, "opus", 1, write.DEFAULT_VOICE)
                        else:
                            with self.assertRaises(RuntimeError):
                                write.run_writer(brief, digest, directory, "opus", 1, write.DEFAULT_VOICE)
                receipt = json.loads((directory / "receipt.json").read_text())
                self.assertEqual(receipt["status"], "success" if outcome == "success" else "failed")
                self.assertEqual(receipt["setting_sources"], [])
                self.assertEqual(receipt["session_settings"], write.SESSION_SETTINGS)
                self.assertEqual(receipt["voice"], write.DEFAULT_VOICE)
                self.assertEqual(receipt["sample_sha256"], hashlib.sha256(sample.encode()).hexdigest())
                prompt = (directory / "system-prompt.txt").read_text(encoding="utf-8")
                self.assertEqual(receipt["system_prompt_sha256"], hashlib.sha256(prompt.encode()).hexdigest())
                self.assertTrue(prompt.startswith(write.WRITER_PROMPT))
                self.assertTrue(prompt.endswith(sample))
                self.assertNotIn("- Rights:", prompt)
                self.assertEqual((directory / "brief.md").read_bytes(), self.brief.read_bytes())
                self.assertEqual((directory / "draft.md").exists(), outcome == "success")
                self.assertTrue((directory / "response.jsonl").exists())
                self.assertTrue((directory / "stderr.txt").exists())

    def test_plain_run_records_no_sample(self):
        brief, digest = write.read_brief(self.brief)
        directory = self.case / "run"
        with patch.object(write.shutil, "which", return_value="claude"):
            with patch.object(write.subprocess, "run", side_effect=self.fake_cli("success")):
                write.run_writer(brief, digest, directory, "opus", 1, PLAIN)
        receipt = json.loads((directory / "receipt.json").read_text())
        self.assertEqual(receipt["voice"], PLAIN)
        self.assertIsNone(receipt["sample_sha256"])
        self.assertEqual((directory / "system-prompt.txt").read_text(encoding="utf-8"), write.WRITER_PROMPT)

    def test_check_mode_reports_voice_and_sample(self):
        sample = write.load_register_sample(write.DEFAULT_VOICE)
        out = io.StringIO()
        with patch.object(write.sys, "argv", ["write.py", "--brief", str(self.brief), "--check"]):
            with redirect_stdout(out):
                self.assertEqual(write.main(), 0)
        report = json.loads(out.getvalue())
        self.assertEqual(report["brief_sha256"], self.digest)
        self.assertEqual(report["voice"], write.DEFAULT_VOICE)
        self.assertEqual(report["sample_sha256"], hashlib.sha256(sample.encode()).hexdigest())
        self.assertFalse(report["review_checked"])

    def test_malformed_response_records_failure(self):
        brief, digest = write.read_brief(self.brief)
        records = events()
        records[1]["message"] = None
        directory = self.case / "run"
        with patch.object(write.shutil, "which", return_value="claude"):
            with patch.object(write.subprocess, "run", side_effect=self.fake_cli("success", records)):
                with self.assertRaises(RuntimeError):
                    write.run_writer(brief, digest, directory, "opus", 1, PLAIN)
        receipt = json.loads((directory / "receipt.json").read_text())
        self.assertEqual(receipt["status"], "failed")
        self.assertIn("event[1].message: expected dict; received NoneType", receipt["error"])
        self.assertFalse((directory / "draft.md").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
