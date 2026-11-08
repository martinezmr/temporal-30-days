"""Tests for scripts/check_lessons.py, which keeps lesson snippets in sync with solutions."""

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "check_lessons", REPO / "scripts" / "check_lessons.py"
)
check_lessons = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_lessons)


def _solution(tmp_path: Path) -> Path:
    solution = tmp_path / "solutions" / "day-02"
    solution.mkdir(parents=True)
    (solution / "x.py").write_text("A = 1\n\ndef b():\n    return 2\n\nC = 3\n")
    return solution


def _lesson(body: str) -> str:
    return "# Lesson\n\n```python\n" + body + "```\n"


def test_snippet_matching_in_order_passes(tmp_path):
    solution = _solution(tmp_path)
    [snippet] = check_lessons.extract_snippets(_lesson("# file: x.py\nA = 1\n...\nC = 3\n"))
    assert check_lessons.check_snippet(snippet, solution) is None


def test_snippet_keeps_indentation(tmp_path):
    solution = _solution(tmp_path)
    [snippet] = check_lessons.extract_snippets(_lesson("# file: x.py\ndef b():\n    return 2\n"))
    assert check_lessons.check_snippet(snippet, solution) is None


def test_snippet_line_missing_fails(tmp_path):
    solution = _solution(tmp_path)
    [snippet] = check_lessons.extract_snippets(_lesson("# file: x.py\nA = 1\nD = 4\n"))
    error = check_lessons.check_snippet(snippet, solution)
    assert error is not None
    assert "x.py" in error
    assert "D = 4" in error


def test_snippet_out_of_order_fails(tmp_path):
    solution = _solution(tmp_path)
    [snippet] = check_lessons.extract_snippets(_lesson("# file: x.py\nC = 3\nA = 1\n"))
    assert check_lessons.check_snippet(snippet, solution) is not None


def test_snippet_missing_file_fails(tmp_path):
    solution = _solution(tmp_path)
    [snippet] = check_lessons.extract_snippets(_lesson("# file: nope.py\nA = 1\n"))
    error = check_lessons.check_snippet(snippet, solution)
    assert error is not None and "nope.py" in error


def test_block_without_header_ignored():
    assert check_lessons.extract_snippets(_lesson("A = 1\n")) == []


def test_broken_relative_link_reported(tmp_path):
    (tmp_path / "real.md").write_text("# real\n")
    md = tmp_path / "lesson.md"
    md.write_text("[x](missing.md) [y](https://example.com) [z](real.md#a) [w](#local)\n")
    errors = check_lessons.check_links(md)
    assert len(errors) == 1
    assert "missing.md" in errors[0]


def test_links_inside_code_blocks_ignored(tmp_path):
    md = tmp_path / "lesson.md"
    md.write_text("```python\nx = d[a](b)\n```\n")
    assert check_lessons.check_links(md) == []


def test_solution_dir_from_lesson_path():
    lesson = REPO / "days" / "week-1" / "day-02-eapi-activity" / "README.md"
    assert check_lessons.solution_dir_for(lesson) == REPO / "solutions" / "day-02"
