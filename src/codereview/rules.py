"""High-precision checks over added lines.

A finding has to point at a line that was added. Comments, lockfiles, and
vendor trees are skipped except for key material, which is never fine to commit.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from codereview.diffparse import FileDiff

_AWS = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_SECRET = re.compile(
    r"""(?i)\b(?:api_key|apikey|secret|password|passwd|token)\b\s*[:=]\s*['\"]([^'\"]{8,})['\"]"""
)
_PRIVATE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_BARE = re.compile(r"^\s*except\s*:\s*(#.*)?$")
_EXCEPT = re.compile(r"^\s*except\b.+:\s*(#.*)?$")
_SQL = re.compile(r"(?i)\b(select|insert|update|delete)\b")
_SQL_BUILD = re.compile(r"""f['\"]|%\(|\+\s*[A-Za-z_]""")
_DEBUG = re.compile(r"\b(?:breakpoint\(\)|pdb\.set_trace\(\)|debugger;)|fmt\.Printf\(\s*\"DEBUG")
_ERR = re.compile(r"\berr\s*:=")
_SKIP_PREFIX = ("vendor/", "node_modules/", "dist/")
_PLACEHOLDERS = {"changeme", "password", "secret", "your-api-key", "redacted", "todo"}


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    severity: str
    body: str
    evidence: str

    def to_dict(self) -> dict:
        return asdict(self)


def _skipped(path: str) -> bool:
    lowered = path.replace("\\", "/").lower()
    return lowered.startswith(_SKIP_PREFIX) or lowered.endswith(".lock")


def _comment(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith(("#", "//", "/*", "*"))


def _is_test_path(path: str) -> bool:
    name = path.replace("\\", "/").lower()
    base = name.rsplit("/", 1)[-1]
    return (
        "/test" in f"/{name}"
        or base.startswith("test_")
        or base.endswith("_test.py")
        or base.endswith("_test.go")
        or base.endswith(".test.ts")
        or base.endswith(".spec.ts")
    )


def _one(path: str, line: int, rule: str, severity: str, body: str, evidence: str) -> Finding:
    return Finding(path, line, rule, severity, f"{rule}: {body}", evidence)


def analyze(files: list[FileDiff]) -> list[Finding]:
    findings: list[Finding] = []
    has_test = any(_is_test_path(item.path) for item in files)
    for item in files:
        skipped = _skipped(item.path)
        findings.extend(_line_rules(item, secrets_only=skipped))
        if skipped:
            continue
        findings.extend(_go_errors(item))
        if item.is_new and not has_test and not _is_test_path(item.path):
            added = item.added()
            defines = any(re.search(r"^\s*(def|func)\s+", text) for _, text in added)
            if defines and added:
                line, text = added[0]
                findings.append(
                    _one(
                        item.path,
                        line,
                        "missing_test",
                        "medium",
                        "This new file adds a function and the diff does not add a test.",
                        text.strip(),
                    )
                )
    return findings


def _line_rules(item: FileDiff, secrets_only: bool = False) -> list[Finding]:
    found: list[Finding] = []
    for hunk in item.hunks:
        added = [(line.new_line, line.text) for line in hunk.lines if line.kind == "add" and line.new_line]
        for index, (line_no, text) in enumerate(added):
            if line_no is None:
                continue
            evidence = text.strip()
            if _PRIVATE.search(text):
                found.append(
                    _one(
                        item.path,
                        line_no,
                        "private_key",
                        "high",
                        "A private key was added. Remove it and rotate the key.",
                        evidence,
                    )
                )
                continue
            if _AWS.search(text):
                found.append(
                    _one(
                        item.path,
                        line_no,
                        "aws_key",
                        "high",
                        "An AWS access key id was added. Remove it and rotate the key.",
                        evidence,
                    )
                )
                continue
            if not _comment(text):
                secret = _SECRET.search(text)
                if secret and secret.group(1).lower() not in _PLACEHOLDERS and not secret.group(1).lower().startswith("example"):
                    found.append(
                        _one(
                            item.path,
                            line_no,
                            "secret_literal",
                            "high",
                            "This assigns a secret literal. Read it from the environment instead.",
                            evidence,
                        )
                    )
            if secrets_only or _comment(text):
                continue
            if _BARE.search(text):
                found.append(
                    _one(
                        item.path,
                        line_no,
                        "bare_except",
                        "medium",
                        "A bare except hides the failure. Catch the exception you can handle.",
                        evidence,
                    )
                )
            elif _EXCEPT.search(text):
                nxt = added[index + 1][1] if index + 1 < len(added) else ""
                if nxt.strip() == "pass":
                    found.append(
                        _one(
                            item.path,
                            line_no,
                            "swallowed_exception",
                            "medium",
                            "This except swallows the error with pass. Log it or return it.",
                            evidence,
                        )
                    )
            if _SQL.search(text) and _SQL_BUILD.search(text):
                found.append(
                    _one(
                        item.path,
                        line_no,
                        "sql_interpolation",
                        "high",
                        "SQL is built with string interpolation. Use bound parameters.",
                        evidence,
                    )
                )
            if _DEBUG.search(text):
                found.append(
                    _one(
                        item.path,
                        line_no,
                        "debug_leftover",
                        "medium",
                        "A debugger or DEBUG print was added. Take it out before merge.",
                        evidence,
                    )
                )
    return found


def _go_errors(item: FileDiff) -> list[Finding]:
    found = []
    for hunk in item.hunks:
        lines = hunk.lines
        for index, line in enumerate(lines):
            if line.kind != "add" or line.new_line is None or _comment(line.text):
                continue
            if not _ERR.search(line.text) or "if err" in line.text:
                continue
            rest = "\n".join(later.text for later in lines[index + 1 : index + 8])
            if "if err" in rest:
                continue
            found.append(
                _one(
                    item.path,
                    line.new_line,
                    "unchecked_go_error",
                    "medium",
                    "err is assigned and not checked in this hunk. Handle it before using the result.",
                    line.text.strip(),
                )
            )
    return found
