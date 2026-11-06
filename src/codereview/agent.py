"""Tool loop in front of the static rules.

The model can read files and drop a finding. It cannot publish a comment the
rules did not produce. With no model, the confirming loop reads each finding
and keeps the ones still present in the workspace.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from codereview.diffparse import FileDiff, parse_diff
from codereview.rules import Finding, analyze


@dataclass(frozen=True)
class Action:
    name: str
    args: dict


class Workspace:
    def __init__(self, files: dict[str, str]) -> None:
        self.files = files

    def snippet(self, path: str, line: int, radius: int = 3) -> str:
        rows = self.files.get(path, "").splitlines()
        start = max(1, line - radius)
        end = min(len(rows), line + radius)
        return "\n".join(rows[start - 1 : end])

    def confirms(self, finding: Finding) -> bool:
        # A diff-only review has no file to contradict. A file that is present must
        # still contain the evidence, so a stale line is not commented twice.
        if finding.path not in self.files:
            return True
        rows = self.files[finding.path].splitlines()
        index = finding.line - 1
        if index < 0 or index >= len(rows):
            return False
        if finding.rule == "unchecked_go_error":
            window = "\n".join(rows[index : index + 8])
            return "if err" not in window
        return finding.evidence in rows[index]

    def search(self, pattern: str) -> list[dict]:
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return [{"error": str(exc)}]
        hits = []
        for path, text in self.files.items():
            for number, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    hits.append({"path": path, "line": number, "text": line})
        return hits


class ConfirmingModel:
    """Read every finding, then submit the static comments unchanged."""

    def __init__(self) -> None:
        self.findings: list[dict] | None = None
        self.index = 0
        self.calls: list[str] = []

    def step(self, observation: str) -> Action:
        data = json.loads(observation)
        if self.findings is None:
            self.findings = list(data.get("findings", []))
            if not self.findings:
                self.calls.append("submit")
                return Action("submit", {"comments": []})
            self.calls.append("read_file")
            current = self.findings[0]
            return Action("read_file", {"path": current["path"], "line": current["line"]})
        if self.index < len(self.findings) - 1:
            self.index += 1
            current = self.findings[self.index]
            self.calls.append("read_file")
            return Action("read_file", {"path": current["path"], "line": current["line"]})
        self.calls.append("submit")
        comments = [
            {
                "path": item["path"],
                "line": item["line"],
                "rule": item["rule"],
                "severity": item["severity"],
                "body": item["body"],
            }
            for item in self.findings
        ]
        return Action("submit", {"comments": comments})


def review_diff(diff: str, workspace: Workspace | None = None, model=None, max_steps: int = 24) -> list[dict]:
    files = parse_diff(diff)
    return review_files(files, workspace, model, max_steps)


def review_files(files: list[FileDiff], workspace: Workspace | None = None, model=None, max_steps: int = 24) -> list[dict]:
    findings = analyze(files)
    chooser = model or ConfirmingModel()
    submitted = _run(chooser, findings, workspace, max_steps)
    return [comment for comment in submitted if _supported(comment, findings, workspace)]


def _run(model, findings: list[Finding], workspace: Workspace | None, max_steps: int) -> list[dict]:
    observation = json.dumps({"findings": [item.to_dict() for item in findings]})
    for _ in range(max_steps):
        action = model.step(observation)
        if action.name == "submit":
            comments = action.args.get("comments", [])
            return comments if isinstance(comments, list) else []
        observation = json.dumps(_tool(action, findings, workspace))
    return [
        {
            "path": item.path,
            "line": item.line,
            "rule": item.rule,
            "severity": item.severity,
            "body": item.body,
        }
        for item in findings
    ]


def _tool(action: Action, findings: list[Finding], workspace: Workspace | None) -> dict:
    if action.name == "list_findings":
        return {"findings": [item.to_dict() for item in findings]}
    if action.name == "read_file":
        path = str(action.args.get("path", ""))
        line = int(action.args.get("line", 1))
        text = workspace.snippet(path, line) if workspace else ""
        return {"path": path, "line": line, "text": text}
    if action.name == "search":
        pattern = str(action.args.get("pattern", ""))
        return {"matches": workspace.search(pattern) if workspace else []}
    return {"error": f"unknown tool {action.name}"}


def _supported(comment: dict, findings: list[Finding], workspace: Workspace | None) -> bool:
    try:
        path = comment["path"]
        line = int(comment["line"])
        rule = comment["rule"]
        body = comment["body"]
    except (KeyError, TypeError, ValueError):
        return False
    if not isinstance(body, str) or not body.strip():
        return False
    for finding in findings:
        if finding.path == path and finding.line == line and finding.rule == rule:
            if workspace is not None and not workspace.confirms(finding):
                return False
            return True
    return False


def summary(comments: list[dict]) -> str:
    if not comments:
        return "No routine findings."
    rules = ", ".join(sorted({item["rule"] for item in comments}))
    return (
        f"Automated review found {len(comments)} routine comment"
        f"{'' if len(comments) == 1 else 's'} ({rules}). "
        "These are mechanical checks. Design and product behavior still need a person."
    )
