"""SQLite persistence for release reviews.

The starter deliberately retains last-write-wins review behavior. The engineering
exercise is to replace it with an optimistic concurrency contract. All data is
fictional; this is not connected to a deployment service.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "releases.json"


class ReleaseNotFound(Exception):
    pass


class Store:
    def __init__(self, database):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.database, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self):
        with self.connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS releases (
                    id TEXT PRIMARY KEY,
                    service TEXT NOT NULL,
                    version TEXT NOT NULL,
                    environment TEXT NOT NULL,
                    risk TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    checks TEXT NOT NULL,
                    status TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    release_id TEXT NOT NULL REFERENCES releases(id),
                    reviewer TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    note TEXT NOT NULL,
                    submitted_revision INTEGER,
                    resulting_revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS audit_release_id
                    ON audit_events(release_id, id);
            """)
            connection.executemany(
                """INSERT OR IGNORE INTO releases
                   (id, service, version, environment, risk, summary, checks,
                    status, revision, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [self.fixture_values(release) for release in json.loads(FIXTURES.read_text())],
            )

    @staticmethod
    def fixture_values(release):
        return (
            release["id"], release["service"], release["version"], release["environment"],
            release["risk"], release["summary"], json.dumps(release["checks"]),
            release["status"], release["revision"], release["updated_at"],
        )

    @staticmethod
    def serialize(row):
        release = dict(row)
        release["checks"] = json.loads(release["checks"])
        return release

    def list_releases(self):
        with self.connection() as connection:
            rows = connection.execute("SELECT * FROM releases ORDER BY id").fetchall()
        return [self.serialize(row) for row in rows]

    def overview(self):
        """Summarize one read-only snapshot of the current release records."""
        releases = self.list_releases()
        by_status = {status: 0 for status in ("pending", "approved", "rejected")}
        by_environment = {}
        attention = []
        for release in releases:
            by_status[release["status"]] = by_status.get(release["status"], 0) + 1
            environment = release["environment"]
            by_environment[environment] = by_environment.get(environment, 0) + 1
            checks = [
                check["name"] for check in release["checks"]
                if check["result"] == "review"
            ]
            if release["status"] == "pending" and checks:
                attention.append({
                    "id": release["id"],
                    "service": release["service"],
                    "environment": environment,
                    "risk": release["risk"],
                    "checks_needing_review": checks,
                })
        return {
            "total": len(releases),
            "by_status": by_status,
            "by_environment": dict(sorted(by_environment.items())),
            "attention": attention,
        }    

    def get_release(self, release_id):
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM releases WHERE id = ?", (release_id,)).fetchone()
        if row is None:
            raise ReleaseNotFound(release_id)
        return self.serialize(row)

    def audit_events(self, release_id):
        self.get_release(release_id)
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM audit_events WHERE release_id = ? ORDER BY id DESC", (release_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def review(self, release_id, reviewer, decision, note, expected_revision=None):
        """Persist a review using the starter's documented last-write-wins policy.

        The browser supplies expected_revision, but this baseline does not enforce
        it. Two reviewers can therefore both succeed against the same snapshot.
        """
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.connection() as connection:
            if connection.execute(
                "SELECT 1 FROM releases WHERE id = ?", (release_id,)
            ).fetchone() is None:
                raise ReleaseNotFound(release_id)
            connection.execute(
                "UPDATE releases SET status = ?, revision = revision + 1, updated_at = ? WHERE id = ?",
                (decision, timestamp, release_id),
            )
            row = connection.execute("SELECT * FROM releases WHERE id = ?", (release_id,)).fetchone()
            connection.execute(
                """INSERT INTO audit_events
                   (release_id, reviewer, decision, note, submitted_revision,
                    resulting_revision, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (release_id, reviewer, decision, note, expected_revision, row["revision"], timestamp),
            )
            return self.serialize(row)

    def reset_demo(self):
        with self.connection() as connection:
            connection.execute("DELETE FROM audit_events")
            connection.execute("DELETE FROM releases")
            connection.executemany(
                """INSERT INTO releases
                   (id, service, version, environment, risk, summary, checks,
                    status, revision, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [self.fixture_values(release) for release in json.loads(FIXTURES.read_text())],
            )
