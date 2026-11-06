import json
from pathlib import Path

from codereview.agent import Action, Workspace, review_diff
from codereview.cli import main, pull_request_number
from codereview.github_api import post_review, review_payload

DIFF = """
diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,2 +1,5 @@
 def ok():
-    return 1
+    password = "supersecretvalue"
+    password = "example-token"
+    token = "changeme"
+    return 1
diff --git a/cloud.py b/cloud.py
--- a/cloud.py
+++ b/cloud.py
@@ -1 +1,2 @@
+aws = "AKIAIOSFODNN7EXAMPLE"
 name = "cloud"
diff --git a/key.pem b/key.pem
--- a/key.pem
+++ b/key.pem
@@ -0,0 +1,1 @@
+-----BEGIN RSA PRIVATE KEY-----
diff --git a/handle.py b/handle.py
--- a/handle.py
+++ b/handle.py
@@ -1 +1,5 @@
 def run():
+    try:
+        work()
+    except:
+        return None
diff --git a/swallow.py b/swallow.py
--- a/swallow.py
+++ b/swallow.py
@@ -1 +1,4 @@
 def run():
+    try:
+        work()
+    except Exception:
+        pass
diff --git a/db.py b/db.py
--- a/db.py
+++ b/db.py
@@ -1 +1,2 @@
 def lookup(name):
+    query = f"SELECT id FROM users WHERE name = '{name}'"
diff --git a/debug.py b/debug.py
--- a/debug.py
+++ b/debug.py
@@ -1 +1,2 @@
 def run():
+    breakpoint()
diff --git a/main.go b/main.go
--- a/main.go
+++ b/main.go
@@ -1 +1,5 @@
 package main
+func f() {
+    x, err := g()
+    fmt.Println(x)
+}
diff --git a/src/billing.py b/src/billing.py
new file mode 100644
--- /dev/null
+++ b/src/billing.py
@@ -0,0 +1,2 @@
+def charge():
+    return 1
"""

CHECKED = """
diff --git a/main.go b/main.go
--- a/main.go
+++ b/main.go
@@ -1 +1,6 @@
 package main
+func f() error {
+    x, err := g()
+    if err != nil {
+        return err
+    }
+    fmt.Println(x)
+    return nil
+}
"""

CLEAN = """
diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-name = "a"
+name = "b"
"""

EXPECTED = {
    "secret_literal",
    "aws_key",
    "private_key",
    "bare_except",
    "swallowed_exception",
    "sql_interpolation",
    "debug_leftover",
    "unchecked_go_error",
    "missing_test",
}


def test_fixture_diff_has_each_routine_finding_once():
    comments = review_diff(DIFF)
    assert {item["rule"] for item in comments} == EXPECTED
    assert len(comments) == len(EXPECTED)
    for item in comments:
        assert item["body"].startswith(item["rule"] + ":")
        assert item["line"] >= 1


def test_adding_a_test_file_removes_the_missing_test_comment():
    diff = DIFF + """
diff --git a/tests/test_billing.py b/tests/test_billing.py
new file mode 100644
--- /dev/null
+++ b/tests/test_billing.py
@@ -0,0 +1,2 @@
+def test_charge():
+    assert charge() == 1
"""
    assert "missing_test" not in {item["rule"] for item in review_diff(diff)}


def test_checked_go_error_and_clean_diff_are_quiet():
    assert review_diff(CHECKED) == []
    assert review_diff(CLEAN) == []


def test_workspace_drops_a_line_that_is_gone():
    comments = review_diff(DIFF, Workspace({"app.py": "def ok():\n    return 1\n"}))
    assert "secret_literal" not in {item["rule"] for item in comments}
    assert "aws_key" in {item["rule"] for item in comments}


def test_model_cannot_invent_a_comment():
    class Scripted:
        def __init__(self):
            self.actions = [
                Action("search", {"pattern": "password"}),
                Action(
                    "submit",
                    {
                        "comments": [
                            {
                                "path": "app.py",
                                "line": 1,
                                "rule": "secret_literal",
                                "severity": "high",
                                "body": "invented",
                            }
                        ]
                    },
                ),
            ]

        def step(self, observation: str) -> Action:
            return self.actions.pop(0)

    model = Scripted()
    assert review_diff(DIFF, model=model) == []
    assert model.actions == []


def test_review_payload_uses_the_new_file_side():
    comments = review_diff(CLEAN)
    assert review_payload(comments) == {"event": "COMMENT", "body": "No routine findings."}
    payload = review_payload(review_diff(DIFF))
    assert payload["comments"]
    assert {item["side"] for item in payload["comments"]} == {"RIGHT"}


def test_post_review_sends_the_payload():
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b'{"id": 7}'

    def opener(request):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode())
        return Response()

    body = review_payload([])
    result = post_review("bsashank2710/example", 12, "token", body, opener=opener)
    assert result == {"id": 7}
    assert captured["url"].endswith("/repos/bsashank2710/example/pulls/12/reviews")
    assert captured["headers"]["Authorization"] == "Bearer token"
    assert captured["body"]["event"] == "COMMENT"


def test_cli_prints_json(tmp_path: Path, capsys):
    diff = tmp_path / "change.diff"
    diff.write_text(CLEAN, encoding="utf-8")
    assert main(["review", "--diff", str(diff), "--root", str(tmp_path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["comments"] == []


def test_pull_request_number_reads_the_event(tmp_path: Path):
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"number": 4}}), encoding="utf-8")
    assert pull_request_number(str(event)) == 4
    assert pull_request_number(None) is None
