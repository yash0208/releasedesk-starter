"""Baseline contract tests. Add concurrency regression tests during the exercise."""

from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import json
import unittest

from releasedesk.server import create_server


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.database = Path(self.directory.name) / "test.sqlite3"
        self.server = create_server(self.database)
        self.thread = Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.directory.cleanup()

    def request(self, path, payload=None, headers=None):
        data = None if payload is None else json.dumps(payload).encode()
        request = Request(self.url + path, data=data, headers=headers or {"Content-Type": "application/json"})
        try:
            response = urlopen(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.loads(response.read())

    @staticmethod
    def review_payload(**changes):
        return {"reviewer": "Reviewer A", "decision": "approved",
                "note": "Staging and rollback evidence checked.", "expected_revision": 1, **changes}

    def test_health_describes_local_demo(self):
        status, body = self.request("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["mode"], "local-synthetic-demo")

    def test_queue_has_five_synthetic_releases(self):
        status, body = self.request("/api/releases")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["releases"]), 5)
        self.assertEqual(body["releases"][0]["id"], "REL-1042")

    def test_release_contains_decision_snapshot_and_checks(self):
        status, body = self.request("/api/releases/REL-1042")
        self.assertEqual(status, 200)
        self.assertEqual(body["release"]["revision"], 1)
        self.assertEqual(body["release"]["status"], "pending")
        self.assertEqual(len(body["release"]["checks"]), 3)

    def test_new_release_has_empty_audit_history(self):
        status, body = self.request("/api/releases/REL-1042/audit")
        self.assertEqual((status, body["events"]), (200, []))

    def test_approval_is_persisted_and_increments_revision(self):
        status, body = self.request("/api/releases/REL-1042/review", self.review_payload())
        self.assertEqual(status, 200)
        self.assertEqual(body["release"]["status"], "approved")
        self.assertEqual(body["release"]["revision"], 2)
        self.assertEqual(self.request("/api/releases/REL-1042")[1]["release"]["status"], "approved")

    def test_rejection_is_persisted(self):
        status, body = self.request("/api/releases/REL-1042/review", self.review_payload(decision="rejected"))
        self.assertEqual(status, 200)
        self.assertEqual(body["release"]["status"], "rejected")

    def test_successful_review_adds_one_audit_event(self):
        self.request("/api/releases/REL-1042/review", self.review_payload())
        status, body = self.request("/api/releases/REL-1042/audit")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["events"]), 1)
        self.assertEqual(body["events"][0]["submitted_revision"], 1)
        self.assertEqual(body["events"][0]["resulting_revision"], 2)

    def test_invalid_decision_is_rejected_without_mutation(self):
        status, body = self.request("/api/releases/REL-1042/review", self.review_payload(decision="deploy"))
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "invalid_request")
        self.assertEqual(self.request("/api/releases/REL-1042")[1]["release"]["revision"], 1)
        self.assertEqual(self.request("/api/releases/REL-1042/audit")[1]["events"], [])

    def test_unknown_reviewer_is_rejected(self):
        status, _ = self.request("/api/releases/REL-1042/review", self.review_payload(reviewer="Unknown"))
        self.assertEqual(status, 400)

    def test_invalid_notes_are_rejected(self):
        for note in ["  ", "x" * 501, None, 42]:
            with self.subTest(note_type=type(note).__name__):
                status, _ = self.request("/api/releases/REL-1042/review", self.review_payload(note=note))
                self.assertEqual(status, 400)

    def test_missing_release_is_not_found(self):
        self.assertEqual(self.request("/api/releases/REL-9999")[0], 404)
        self.assertEqual(self.request("/api/releases/REL-9999/review", self.review_payload())[0], 404)

    def test_unknown_routes_are_not_found(self):
        self.assertEqual(self.request("/api/no-such-route")[0], 404)
        self.assertEqual(self.request("/api/no-such-route", {})[0], 404)

    def test_non_object_json_is_rejected(self):
        self.assertEqual(self.request("/api/releases/REL-1042/review", [1, 2])[0], 400)

    def test_malformed_json_is_rejected(self):
        request = Request(self.url + "/api/releases/REL-1042/review", data=b"{invalid",
                          headers={"Content-Type": "application/json"})
        with self.assertRaises(HTTPError) as raised:
            urlopen(request, timeout=5)
        self.assertEqual(raised.exception.code, 400)
        raised.exception.close()

    def test_cross_origin_mutation_is_rejected(self):
        status, body = self.request("/api/releases/REL-1042/review", self.review_payload(),
                                    {"Content-Type": "application/json", "Origin": "https://example.com"})
        self.assertEqual(status, 403)
        self.assertEqual(body["error"]["code"], "origin_rejected")

    def test_reset_requires_explicit_synthetic_confirmation(self):
        self.assertEqual(self.request("/api/demo/reset", {})[0], 400)

    def test_reset_restores_fixtures_and_clears_audit(self):
        self.request("/api/releases/REL-1042/review", self.review_payload())
        status, body = self.request("/api/demo/reset", {"confirm": "reset-synthetic-data"})
        self.assertEqual(status, 200)
        self.assertEqual(body["releases"][0]["revision"], 1)
        self.assertEqual(self.request("/api/releases/REL-1042/audit")[1]["events"], [])

    def test_dashboard_and_static_assets_are_served(self):
        for path, content_type in [("/", "text/html"), ("/app.js", "text/javascript"), ("/styles.css", "text/css")]:
            with self.subTest(path=path), urlopen(self.url + path, timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertTrue(response.headers["Content-Type"].startswith(content_type))
                self.assertGreater(len(response.read()), 100)

    def test_overview_counts_and_pending_attention(self):
        status, body = self.request("/api/overview")
        self.assertEqual(status, 200)
        self.assertEqual(body["total"], 5)
        self.assertEqual(body["by_status"], {"pending": 3, "approved": 1, "rejected": 1})
        self.assertEqual(body["by_environment"], {"Production": 3, "Staging": 2})
        self.assertEqual(body["attention"], [{
            "id": "REL-1044", "service": "Search Index", "environment": "Production",
            "risk": "High", "checks_needing_review": ["Memory budget check"],
        }])

    def test_overview_follows_review_and_reset(self):
        self.request("/api/releases/REL-1042/review", self.review_payload())
        after_review = self.request("/api/overview")[1]
        self.assertEqual(after_review["by_status"],
                         {"pending": 2, "approved": 2, "rejected": 1})
        self.assertEqual(after_review["total"], 5)
        self.assertEqual(after_review["by_environment"],
                         {"Production": 3, "Staging": 2})
        self.assertEqual([item["id"] for item in after_review["attention"]], ["REL-1044"])
        self.request("/api/demo/reset", {"confirm": "reset-synthetic-data"})
        after_reset = self.request("/api/overview")[1]
        self.assertEqual(after_reset["by_status"],
                         {"pending": 3, "approved": 1, "rejected": 1})
        self.assertEqual([item["id"] for item in after_reset["attention"]], ["REL-1044"])

    def test_overview_does_not_change_revisions_or_audit_history(self):
        before = self.request("/api/releases")[1]["releases"]
        self.request("/api/overview")
        self.request("/api/overview")
        after = self.request("/api/releases")[1]["releases"]
        self.assertEqual(after, before)
        self.assertEqual(self.request("/api/releases/REL-1042/audit")[1]["events"], [])            


if __name__ == "__main__":
    unittest.main()
