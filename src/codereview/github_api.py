"""Build and send a pull-request review. The HTTP call is injectable in tests."""

from __future__ import annotations

import json
from urllib.request import Request, urlopen

from codereview.agent import summary


def review_payload(comments: list[dict]) -> dict:
    if not comments:
        return {"event": "COMMENT", "body": summary(comments)}
    return {
        "event": "COMMENT",
        "body": summary(comments),
        "comments": [
            {
                "path": item["path"],
                "line": item["line"],
                "side": "RIGHT",
                "body": item["body"],
            }
            for item in comments
        ],
    }


def post_review(repo: str, number: int, token: str, payload: dict, opener=urlopen) -> dict:
    request = Request(
        f"https://api.github.com/repos/{repo}/pulls/{number}/reviews",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "codereview",
        },
        method="POST",
    )
    with opener(request) as response:
        return json.loads(response.read().decode("utf-8"))
