"""Tests for faq_schema.py — FAQ markup derived from the FAQ's prose.

The gate that matters is the last test: the block committed in
``docs/faq.md`` has to match the questions on the page, so markup and
prose cannot drift apart.
"""

from __future__ import annotations

import json

import faq_schema
import pytest


@pytest.fixture
def page() -> str:
    """A two-question page in the shape of the real one."""
    return (
        "---\ntitle: \"Questions\"\n---\n\n"
        "# Questions people ask\n\n"
        "Short answers.\n\n"
        "## Why does my board freeze?\n\n"
        "Because most libraries wait with the whole program stopped.\n\n"
        "A second paragraph that also answers it.\n\n"
        "```python\ncode = 1\n```\n\n"
        "## How do I install one library?\n\n"
        "One command per runtime, with the library name in it.\n\n"
        "```bash\npip install chumicro-mqtt\n```\n"
    )


class TestParseQuestions:
    """What counts as a question, and what counts as its answer."""

    def test_every_heading_becomes_a_question(self, page):
        questions = faq_schema.parse_questions(page)
        assert [name for name, _ in questions] == [
            "Why does my board freeze?",
            "How do I install one library?",
        ]

    def test_answer_stops_at_the_first_code_block(self, page):
        _, answer = faq_schema.parse_questions(page)[0]
        assert "code = 1" not in answer
        assert answer.endswith("also answers it.")

    def test_inline_markdown_reads_as_speech(self):
        questions = faq_schema.parse_questions(
            "## Does it block?\n\nCall `handle()` on the "
            "[client](https://example.org), **once** per pass.\n",
        )
        assert questions[0][1] == "Call handle() on the client, once per pass."


class TestRender:
    """The block replaces itself rather than accumulating."""

    def test_generating_twice_changes_nothing(self, page):
        once = faq_schema.render(page)
        assert faq_schema.render(once) == once

    def test_block_parses_as_faq_markup(self, page):
        rendered = faq_schema.render(page)
        body = rendered.split('<script type="application/ld+json">')[1]
        data = json.loads(body.split("</script>")[0])
        assert data["@type"] == "FAQPage"
        assert len(data["mainEntity"]) == 2
        assert data["mainEntity"][0]["acceptedAnswer"]["@type"] == "Answer"


class TestCommittedPageIsCurrent:
    """The gate: markup on disk matches the prose on disk."""

    def test_faq_schema_is_not_stale(self):
        page = faq_schema.FAQ_SOURCE.read_text()
        assert faq_schema.render(page) == page, (
            "docs/faq.md carries stale markup; run "
            "`python scripts/faq_schema.py` and commit the result."
        )

    def test_every_heading_reached_the_markup(self):
        page = faq_schema.FAQ_SOURCE.read_text()
        headings = {name for name, _ in faq_schema.parse_questions(page)}
        body = page.split('<script type="application/ld+json">')[1]
        data = json.loads(body.split("</script>")[0])
        assert {item["name"] for item in data["mainEntity"]} == headings
