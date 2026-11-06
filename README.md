# Code review agent

Reads a unified diff, runs a short list of mechanical checks, and publishes only those findings. A tool-using model can read the file or search it, and it can drop a finding. It cannot add a comment the checks did not produce. If the workspace copy of the file no longer contains the line, the comment is dropped.

On the fixture diff in `tests/test_review.py` the review returns nine comments and no others: a secret literal, an AWS key id, a private key, a bare `except`, an `except` that only `pass`es, SQL built with an f-string, `breakpoint()`, an unchecked Go `err`, and a new function with no test file in the diff. Placeholders (`changeme`, values that start with `example`) are not flagged. A checked `if err != nil` is not flagged. Adding a test file removes the missing-test comment. This repo does not measure review cycle time.

## Run

```bash
pip install -e ".[dev]"
pytest -q
python -m codereview review --diff change.diff
python -m codereview review --base origin/main
```

`--post` sends the review to the pull request when `GITHUB_TOKEN`, `GITHUB_REPOSITORY`, and a pull request event are all set. Otherwise it prints the JSON and skips the post, so a local run does not fail.

`.github/workflows/review.yml` fetches the base branch and runs that command on pull requests. Comments are on the new side of the diff (`side: RIGHT`), which is the line number in the file after the patch.

## Checks

| Rule | What it flags |
| --- | --- |
| `private_key` | `BEGIN … PRIVATE KEY` |
| `aws_key` | `AKIA` access key id |
| `secret_literal` | `password`, `token`, `api_key`, or `secret` assigned a literal |
| `bare_except` | `except:` |
| `swallowed_exception` | `except …:` whose next added line is `pass` |
| `sql_interpolation` | `SELECT` / `INSERT` / `UPDATE` / `DELETE` built with an f-string, `%()`, or `+` |
| `debug_leftover` | `breakpoint()`, `pdb.set_trace()`, `debugger;`, `fmt.Printf("DEBUG` |
| `unchecked_go_error` | `err :=` with no `if err` in the next few hunk lines |
| `missing_test` | a new file that adds `def` or `func`, and the diff touches no test |

`vendor/`, `node_modules/`, `dist/`, and lockfiles skip the style checks. A secret literal, a private key, or an AWS key id in those paths is still flagged.

## Limits

The Go check looks at the hunk, then at eight lines of the workspace. A check further down is missed. The SQL check is textual. The missing-test check is "a test file changed", not "the new function is covered". None of this replaces reading the change.

## License

MIT.
