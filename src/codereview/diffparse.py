"""Parse a unified diff into added lines and hunks.

Line numbers are the new file's lines, which is what the pull-request review
API wants in `side: RIGHT`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_HUNK = re.compile(r"\+(\d+)")


@dataclass(frozen=True)
class Line:
    kind: str
    new_line: int | None
    text: str


@dataclass(frozen=True)
class Hunk:
    lines: tuple[Line, ...]


@dataclass(frozen=True)
class FileDiff:
    path: str
    is_new: bool
    hunks: tuple[Hunk, ...]

    def added(self) -> list[tuple[int, str]]:
        rows = []
        for hunk in self.hunks:
            for line in hunk.lines:
                if line.kind == "add" and line.new_line is not None:
                    rows.append((line.new_line, line.text))
        return rows


def parse_diff(diff: str) -> list[FileDiff]:
    files: list[FileDiff] = []
    path: str | None = None
    is_new = False
    new_line: int | None = None
    hunk_lines: list[Line] = []
    hunks: list[Hunk] = []

    def close_hunk() -> None:
        nonlocal hunk_lines
        if hunk_lines:
            hunks.append(Hunk(tuple(hunk_lines)))
            hunk_lines = []

    def close_file() -> None:
        nonlocal path, is_new, hunks
        close_hunk()
        if path:
            files.append(FileDiff(path, is_new, tuple(hunks)))
        path = None
        is_new = False
        hunks = []

    for raw in diff.splitlines():
        if raw.startswith("diff --git "):
            close_file()
            continue
        if raw.startswith("new file mode"):
            is_new = True
            continue
        if raw.startswith("+++ "):
            name = raw[4:].strip().strip('"')
            path = None if name == "/dev/null" else name[2:] if name.startswith("b/") else name
            continue
        if raw.startswith("@@"):
            close_hunk()
            match = _HUNK.search(raw)
            new_line = int(match.group(1)) if match else None
            continue
        if path is None or new_line is None:
            continue
        if raw.startswith("\\"):
            continue
        if raw.startswith("+"):
            hunk_lines.append(Line("add", new_line, raw[1:]))
            new_line += 1
        elif raw.startswith("-"):
            hunk_lines.append(Line("del", None, raw[1:]))
        else:
            text = raw[1:] if raw.startswith(" ") else raw
            hunk_lines.append(Line("ctx", new_line, text))
            new_line += 1
    close_file()
    return files
