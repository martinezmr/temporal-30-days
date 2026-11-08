"""Keep lessons honest: every code snippet in a lesson must exist in that day's solution.

A fenced code block whose first line is `# file: <path>` is checked against
`solutions/day-NN/<path>`, where NN comes from the lesson folder (`day-NN-...`).
Every non-blank snippet line, except a bare `...`, must appear in that file in
the same order. Relative Markdown links must point at files that exist.

Usage: uv run python scripts/check_lessons.py [lesson.md ...]
"""

import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FENCE = re.compile(r"^\s*```")
HEADER = re.compile(r"^#\s*file:\s*(\S+)\s*$")
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
DAY = re.compile(r"day-(\d\d)")


@dataclass
class Snippet:
    file: str
    lines: list[str]
    line_no: int


def extract_snippets(markdown: str) -> list[Snippet]:
    snippets: list[Snippet] = []
    block: list[str] | None = None
    start = 0
    for no, line in enumerate(markdown.splitlines(), start=1):
        if FENCE.match(line):
            if block is None:
                block, start = [], no + 1
                continue
            if block and (m := HEADER.match(block[0].strip())):
                snippets.append(Snippet(m.group(1), block[1:], start))
            block = None
        elif block is not None:
            block.append(line)
    return snippets


def check_snippet(snippet: Snippet, solution_dir: Path) -> str | None:
    target = solution_dir / snippet.file
    where = f"snippet at line {snippet.line_no} ({snippet.file})"
    if not target.is_file():
        shown = target.relative_to(REPO) if target.is_relative_to(REPO) else target
        return f"{where}: {shown} does not exist"
    source = [line.rstrip() for line in target.read_text().splitlines()]
    pos = 0
    for line in snippet.lines:
        line = line.rstrip()
        if not line.strip() or line.strip() == "...":
            continue
        try:
            pos = source.index(line, pos) + 1
        except ValueError:
            return f"{where}: line not found in order in {snippet.file}: {line.strip()!r}"
    return None


def check_links(md_path: Path) -> list[str]:
    errors = []
    in_code = False
    for no, line in enumerate(md_path.read_text().splitlines(), start=1):
        if FENCE.match(line):
            in_code = not in_code
            continue
        if in_code:
            continue
        for target in LINK.findall(re.sub(r"`[^`]*`", "", line)):
            if re.match(r"^[a-z]+:", target) or target.startswith("#"):
                continue
            path = target.split("#", 1)[0]
            if not (md_path.parent / path).exists():
                errors.append(f"{md_path}:{no}: broken link {target}")
    return errors


def solution_dir_for(lesson: Path) -> Path:
    m = DAY.search(lesson.resolve().parent.name)
    if not m:
        raise ValueError(f"{lesson} is not inside a day-NN-* folder")
    return REPO / "solutions" / f"day-{m.group(1)}"


def main(argv: list[str]) -> int:
    lessons = [Path(a) for a in argv] or sorted((REPO / "days").glob("**/README.md"))
    errors: list[str] = []
    for lesson in lessons:
        errors += check_links(lesson)
        snippets = extract_snippets(lesson.read_text())
        if not snippets:
            continue
        solution = solution_dir_for(lesson)
        for snippet in snippets:
            if error := check_snippet(snippet, solution):
                errors.append(f"{lesson}: {error}")
    for error in errors:
        print(error)
    status = f"{len(errors)} problem(s)" if errors else "OK"
    print(f"checked {len(lessons)} lesson(s): {status}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
