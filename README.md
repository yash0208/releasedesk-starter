# ReleaseDesk starter

A runnable local release-review application for a focused software-engineering
exercise: preventing stale reviewers from overwriting a newer release decision.

This is a synthetic practice project, generated with AI assistance before the
exercise. It has no connection to a real customer, company, deployment platform,
or production system. All service names, reviewers, evidence, and releases are
fictional. The known concurrency defect is intentional and remains unfixed in
the starter.

## Run locally

Use Python 3.11 or newer. No package installation, cloud account, environment
variables, or Docker service is required.

```sh
python3 -m releasedesk.server
```

Open **http://127.0.0.1:8765**. The server binds only to the loopback interface.
Review decisions persist in `data/releasedesk.sqlite3`, which is excluded from Git.
Stop the server with Ctrl+C. To choose another port:

```sh
python3 -m releasedesk.server --port 8766
```

## What works already

- A searchable release queue with status filtering and release evidence.
- Approve/reject decisions, fictional reviewer identities, and audit history.
- SQLite persistence with parameterized queries and rollback on transaction errors.
- Request-shape validation, structured errors, and a same-origin mutation check.
- A browser request inspector and concurrent-review diagnostic lab.
- A reproducible command-line diagnostic using an isolated temporary database.
- Baseline HTTP contract tests and a GitHub Actions test workflow.

## Known issue: stale reviews overwrite decisions

The review payload includes `expected_revision`, representing the snapshot the
reviewer inspected. The starter records this field in its audit trail but does
not enforce it when updating the release. Two clients can submit opposite
decisions using revision 1, both receive HTTP 200, and produce two audit events.
The final release ends at revision 3 with whichever decision was saved last.

Reproduce in the browser:

1. Open `REL-1042`, initially pending at revision 1.
2. Select **Run concurrent review**.
3. Inspect the two HTTP responses and the decision history.
4. Use **Reset demo records** before a fresh attempt. It affects only this local
   synthetic workspace, including its audit history.

Or use a disposable database without changing the dashboard:

```sh
python3 scripts/reproduce_conflict.py
```

## Engineering task

Introduce an optimistic concurrency contract across the HTTP handler and SQLite
store. A review must have a valid snapshot revision and may change only a pending
release at that exact revision. A stale or already-finalized review must receive
a structured HTTP 409 response, with no extra audit event and no state change.
Keep the decision update and its audit insert in one transaction. Add tests for
stale requests, competing concurrent requests, invalid revisions, terminal
states, and audit rollback. Update the browser's conflict feedback so a reviewer
knows that their snapshot is outdated.

Target outcome for two competing reviews of revision 1: one HTTP 200, one HTTP
409, final revision 2, and exactly one new audit event. Either reviewer may win.
Do not hard-code the final decision or serialize requests in the client to hide
the server-side defect.

The starter does not contain the completed fix or a pre-created pull request.
Implementation, regression tests, verification, branch review, and the pull
request are the intended work of the exercise.

## Checks

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q releasedesk scripts tests
python3 scripts/reproduce_conflict.py
```

After implementing the concurrency fix:

```sh
python3 scripts/reproduce_conflict.py --expect-protected
```

The last command deliberately exits with status 1 on this starter. It is an
acceptance diagnostic, not part of the green baseline test workflow. Record its
failure before the fix and success after the fix.

## Project map

| Path | Purpose |
| --- | --- |
| `releasedesk/server.py` | HTTP routing, validation, error responses, static assets |
| `releasedesk/store.py` | SQLite schema, persistence, review transaction, audit events |
| `fixtures/releases.json` | Five fictional release records |
| `web/` | Browser dashboard, concurrency lab, request inspector |
| `tests/test_api.py` | Baseline HTTP contract tests |
| `scripts/reproduce_conflict.py` | Reproducer and post-fix acceptance diagnostic |
| `.github/workflows/tests.yml` | Automated baseline checks |

## Useful references

- [Python sqlite3 transaction control](https://docs.python.org/3.13/library/sqlite3.html#transaction-control)
- [SQLite transaction behavior](https://www.sqlite.org/lang_transaction.html)
- [GitHub pull requests](https://docs.github.com/en/pull-requests)

## Scope and license

This is a local engineering demonstration, not a production release-control
service. Authentication, deployment integrations, multi-tenant permissions,
external notifications, and high-volume database tuning are outside its scope.

Original repository materials are released under **CC0 1.0 Universal**, including
permission for commercial use and AI training. See [LICENSE](LICENSE).
