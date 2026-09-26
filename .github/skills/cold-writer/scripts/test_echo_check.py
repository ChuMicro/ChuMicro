"""Exercise the echo gate's prose extraction, run detection, and exit codes without a model."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import echo_check

ROOT = Path(__file__).resolve().parents[4]

FRAGMENT_BRIEF = (
    "# Verified facts\n\n"
    "- F01 required. setup: installs deps into a venv; later run.py commands pick it up on their own.\n"
    "- F02 required. flash: erases user files; instruct backup first.\n\n"
    "E01, laptop, from the parent folder:\n\n```bash\npython3 run.py setup\n```\n"
)
PROSE_DRAFT = (
    "---\ntitle: Test\n---\n\n# Start\n\n"
    "The setup command installs dependencies into a virtual environment, and later "
    "commands select that environment automatically.\n\n"
    "```bash\npython3 run.py setup\n```\n\n"
    "> **Warning:** Installing firmware can erase files on the board, so back up anything valuable first.\n"
)


class EchoCheckTests(unittest.TestCase):
    """Check what counts as prose, when a shared run counts as an echo, and how the gate reports it."""

    @classmethod
    def setUpClass(cls):
        scratch = ROOT / ".scratch" / "cold-writer"
        scratch.mkdir(parents=True, exist_ok=True)
        cls.fixtures = Path(tempfile.mkdtemp(prefix="unit-echo-", dir=scratch))

    def setUp(self):
        self.case = self.fixtures / self.id().split(".")[-1]
        self.case.mkdir()

    def save(self, name: str, text: str) -> Path:
        path = self.case / name
        path.write_text(text, encoding="utf-8")
        return path

    def run_main(self, *arguments: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = echo_check.main(list(arguments))
        return code, out.getvalue(), err.getvalue()

    def test_prose_drops_markup_and_keeps_quoted_text(self):
        text = echo_check.prose(PROSE_DRAFT)
        self.assertNotIn("title:", text)
        self.assertNotIn("# Start", text)
        self.assertNotIn("python3 run.py setup", text)
        self.assertIn("Installing firmware can erase files", text)
        self.assertNotIn(">", text)
        linked = echo_check.prose("See [Board not found](troubleshooting/board-not-found.md) and `run.py` at <https://example.com/x>.")
        self.assertEqual(linked.split(), ["See", "Board", "not", "found", "and", "at", "."])

    def test_identical_prose_is_fully_echoed(self):
        report = echo_check.measure(PROSE_DRAFT, PROSE_DRAFT, 6)
        self.assertEqual(report["sentences"], 2)
        self.assertEqual(report["echoed"], 2)
        self.assertEqual(report["share"], 1.0)
        self.assertGreaterEqual(report["echoes"][0]["words"], report["echoes"][1]["words"])

    def test_fragment_brief_passes(self):
        report = echo_check.measure(FRAGMENT_BRIEF, PROSE_DRAFT, 6)
        self.assertEqual(report["echoed"], 0)
        self.assertEqual(report["share"], 0.0)

    def test_code_and_links_never_count(self):
        brief = "E01:\n\n```bash\ngit clone --depth 1 https://example.com/repo my-workspace\n```\n\nLinks: [Install libraries](install.md), [Add WiFi credentials](wifi.md).\n"
        draft = (
            "Clone it:\n\n```bash\ngit clone --depth 1 https://example.com/repo my-workspace\n```\n\n"
            "- [Install libraries](install.md)\n- [Add WiFi credentials](wifi.md)\n\n"
            "Run the clone command from the parent folder where the new directory should appear.\n"
        )
        report = echo_check.measure(brief, draft, 3)
        self.assertEqual(report["sentences"], 1)
        self.assertEqual(report["echoed"], 0)

    def test_run_length_sets_the_bar(self):
        brief = "- F01: selects a sole port automatically or offers a numbered choice\n"
        draft = "The bootstrap command picks a sole port automatically or asks you to choose from a numbered list.\n"
        self.assertEqual(echo_check.measure(brief, draft, 5)["echoed"], 1)
        self.assertEqual(echo_check.measure(brief, draft, 5)["echoes"][0]["words"], 5)
        self.assertEqual(echo_check.measure(brief, draft, 6)["echoed"], 0)

    def test_crlf_and_short_lines_tolerated(self):
        brief = FRAGMENT_BRIEF.replace("\n", "\r\n")
        draft = "Optional tasks:\r\n\r\n" + PROSE_DRAFT.replace("\n", "\r\n")
        report = echo_check.measure(brief, draft, 6)
        self.assertEqual(report["sentences"], 2)

    def test_main_exit_codes_and_report(self):
        brief = self.save("brief.md", PROSE_DRAFT)
        fragments = self.save("fragments.md", FRAGMENT_BRIEF)
        draft = self.save("draft.md", PROSE_DRAFT)
        code, out, _ = self.run_main("--brief", str(brief), "--draft", str(draft))
        self.assertEqual(code, 1)
        report = json.loads(out)
        self.assertFalse(report["passed"])
        self.assertEqual(report["max_share"], echo_check.DEFAULT_MAX_SHARE)
        self.assertIn("sentence", report["echoes"][0])
        code, out, _ = self.run_main("--brief", str(fragments), "--draft", str(draft))
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["passed"])
        code, out, _ = self.run_main("--brief", str(brief), "--draft", str(draft), "--max-share", "1")
        self.assertEqual(code, 0)

    def test_main_rejects_unusable_input(self):
        draft = self.save("draft.md", PROSE_DRAFT)
        empty = self.save("empty.md", "# Only a heading\n\n```bash\nls\n```\n")
        code, _, err = self.run_main("--brief", str(self.case / "missing.md"), "--draft", str(draft))
        self.assertEqual(code, 2)
        self.assertIn("missing.md", err)
        code, _, err = self.run_main("--brief", str(draft), "--draft", str(empty))
        self.assertEqual(code, 2)
        self.assertIn("no prose sentences", err)
        code, _, err = self.run_main("--brief", str(draft), "--draft", str(draft), "--run", "1")
        self.assertEqual(code, 2)
        self.assertIn("--run", err)
        code, _, err = self.run_main("--brief", str(draft), "--draft", str(draft), "--max-share", "2")
        self.assertEqual(code, 2)
        self.assertIn("--max-share", err)


if __name__ == "__main__":
    unittest.main(verbosity=2)
