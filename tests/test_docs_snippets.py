"""The guide's code includes still point at the code they describe.

`user_guide/*.qmd` include parts of `examples/` by line range
(`{{< include examples/petstore.py lines="61-81" >}}`), so the site shows the
real code. A range does not move when the file is edited, so each include is
preceded by `<!-- snippet: <first line> -->`, and this test checks that the
range still starts there and holds whole statements.
"""

from __future__ import annotations

import ast
import re
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
GUIDE = ROOT / "user_guide"
INCLUDE = re.compile(
    r"<!-- snippet: (?P<first>.+?) -->\n"
    r"\{\{< include (?P<path>\S+) lines=\"(?P<start>\d+)-(?P<end>\d+)\" >\}\}"
)


def _includes() -> list[tuple[str, str, str, int, int]]:
    found: list[tuple[str, str, str, int, int]] = []
    for page in sorted(GUIDE.glob("*.qmd")):
        text = page.read_text("utf-8")
        matches = list(INCLUDE.finditer(text))
        # Every ranged include carries its marker.
        assert len(matches) == text.count(" lines="), page.name
        for m in matches:
            found.append((page.name, m["path"], m["first"], int(m["start"]), int(m["end"])))
    return found


INCLUDES = _includes()


def test_the_guide_has_includes() -> None:
    assert INCLUDES


@pytest.mark.parametrize(("page", "path", "first", "start", "end"), INCLUDES)
def test_include_range_matches_its_marker(
    page: str, path: str, first: str, start: int, end: int
) -> None:
    lines = (ROOT / path).read_text("utf-8").splitlines()
    assert 1 <= start <= end <= len(lines), (page, path, start, end)
    snippet = lines[start - 1 : end]
    assert snippet[0].strip() == first, (page, path, start)
    # Whole statements: the range ends where the next line is blank or dedented,
    # and the dedented snippet parses.
    if end < len(lines):
        after = lines[end]
        indent = len(snippet[0]) - len(snippet[0].lstrip())
        assert not after.strip() or len(after) - len(after.lstrip()) <= indent, (page, end)
    ast.parse(textwrap.dedent("\n".join(snippet)))
