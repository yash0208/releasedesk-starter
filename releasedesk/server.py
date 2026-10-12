"""Local-only HTTP server. Run with python3 -m releasedesk.server."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
import argparse
import json
import re
import sys

from .store import ReleaseNotFound, Store

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
REVIEWERS = {"Reviewer A", "Reviewer B", "Reviewer C"}
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
}


def make_handler(store):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ReleaseDesk/0.1"

        def respond(self, status, data):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path in STATIC_FILES:
                filename, content_type = STATIC_FILES[path]
                body = (WEB / filename).read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/health":
                self.respond(200, {"status": "ok", "mode": "local-synthetic-demo"})
                return
            if path == "/api/releases":
                self.respond(200, {"releases": store.list_releases()})
                return
            if path == "/api/overview":
                self.respond(200, store.overview())
                return
            match = re.fullmatch(r"/api/releases/([A-Z0-9-]+)(/audit)?", path)
            if match:
                release_id, audit = match.groups()
                try:
                    self.respond(200, {"events": store.audit_events(release_id)} if audit else
                                 {"release": store.get_release(release_id)})
                except ReleaseNotFound:
                    self.respond(404, {"error": {"code": "not_found", "message": "Release not found."}})
                return
            self.respond(404, {"error": {"code": "not_found", "message": "Route not found."}})

        def read_json(self):
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                raise ValueError("Use application/json.")
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as error:
                raise ValueError("Invalid Content-Length.") from error
            if length < 1 or length > 8192:
                raise ValueError("Provide a JSON body smaller than 8 KB.")
            try:
                value = json.loads(self.rfile.read(length))
            except (ValueError, UnicodeDecodeError) as error:
                raise ValueError("Malformed JSON body.") from error
            if not isinstance(value, dict):
                raise ValueError("The request body must be an object.")
            return value

        def do_POST(self):
            path = urlsplit(self.path).path
            origin = self.headers.get("Origin")
            # The synthetic reset/review endpoints are available only on loopback.
            # Prevent a different website from issuing browser requests to this app.
            expected_origins = {
                f"http://127.0.0.1:{self.server.server_port}",
                f"http://localhost:{self.server.server_port}",
            }
            if origin and origin not in expected_origins:
                self.respond(403, {"error": {"code": "origin_rejected", "message": "Use the local app."}})
                return
            try:
                payload = self.read_json()
                if path == "/api/demo/reset":
                    if payload.get("confirm") != "reset-synthetic-data":
                        raise ValueError("Explicit synthetic-data reset confirmation is required.")
                    store.reset_demo()
                    self.respond(200, {"releases": store.list_releases()})
                    return
                match = re.fullmatch(r"/api/releases/([A-Z0-9-]+)/review", path)
                if not match:
                    self.respond(404, {"error": {"code": "not_found", "message": "Route not found."}})
                    return
                if payload.get("reviewer") not in REVIEWERS:
                    raise ValueError("Select Reviewer A, Reviewer B, or Reviewer C.")
                if payload.get("decision") not in {"approved", "rejected"}:
                    raise ValueError("Decision must be approved or rejected.")
                note = payload.get("note")
                if not isinstance(note, str) or not 3 <= len(note.strip()) <= 500:
                    raise ValueError("Provide a review note between 3 and 500 characters.")
                # Enforcing the expected_revision contract is the planned engineering task.
                release = store.review(
                    match.group(1), payload["reviewer"], payload["decision"],
                    note.strip(), payload.get("expected_revision"),
                )
                self.respond(200, {"release": release})
            except ValueError as error:
                self.respond(400, {"error": {"code": "invalid_request", "message": str(error)}})
            except ReleaseNotFound:
                self.respond(404, {"error": {"code": "not_found", "message": "Release not found."}})
            except Exception as error:
                print(f"Request failed: {type(error).__name__}", file=sys.stderr)
                self.respond(500, {"error": {"code": "internal_error", "message": "Request could not be saved."}})

        def log_message(self, format, *args):
            print(f"{self.log_date_time_string()} {format % args}")

    return Handler


def create_server(database, port=0):
    store = Store(database)
    store.initialize()
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(store))


def main():
    parser = argparse.ArgumentParser(description="Run the local ReleaseDesk starter.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--database", type=Path, default=ROOT / "data" / "releasedesk.sqlite3")
    args = parser.parse_args()
    server = create_server(args.database, args.port)
    print(f"ReleaseDesk is ready at http://127.0.0.1:{server.server_port}")
    print("Synthetic data only. Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping ReleaseDesk.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
