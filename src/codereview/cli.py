"""Review a diff from a file or from `git diff base...HEAD`."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from codereview.agent import Workspace, review_diff, summary
from codereview.diffparse import parse_diff
from codereview.github_api import post_review, review_payload


def pull_request_number(event_path: str | None) -> int | None:
    if not event_path:
        return None
    path = Path(event_path)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    number = (data.get("pull_request") or {}).get("number")
    return int(number) if number else None


def git_diff(base: str, root: Path) -> str:
    proc = subprocess.run(
        ["git", "diff", "--unified=3", f"{base}...HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or "git diff failed")
    return proc.stdout


def workspace_for(diff: str, root: Path) -> Workspace:
    files: dict[str, str] = {}
    for item in parse_diff(diff):
        path = root / item.path
        if path.is_file():
            files[item.path] = path.read_text(encoding="utf-8")
    return Workspace(files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="codereview")
    sub = parser.add_subparsers(dest="cmd", required=True)
    review = sub.add_parser("review")
    review.add_argument("--diff", type=Path)
    review.add_argument("--base")
    review.add_argument("--root", type=Path, default=Path("."))
    review.add_argument("--post", action="store_true")
    args = parser.parse_args(argv)
    if args.cmd != "review":
        return 2
    if args.diff and args.base:
        raise SystemExit("pass --diff or --base, not both")
    if args.diff:
        diff = args.diff.read_text(encoding="utf-8")
        comments = review_diff(diff, workspace_for(diff, args.root))
    elif args.base:
        diff = git_diff(args.base, args.root)
        comments = review_diff(diff, workspace_for(diff, args.root))
    else:
        raise SystemExit("pass --diff or --base")
    payload = review_payload(comments)
    json.dump({"summary": summary(comments), "comments": comments}, sys.stdout, indent=2)
    sys.stdout.write("\n")
    if args.post:
        token = os.environ.get("GITHUB_TOKEN", "")
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        number = pull_request_number(os.environ.get("GITHUB_EVENT_PATH"))
        if token and repo and number:
            post_review(repo, number, token, payload)
        else:
            print("post skipped: not running on a pull request", file=sys.stderr)
    return 0
