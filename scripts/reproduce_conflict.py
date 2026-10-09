"""Demonstrate the baseline defect without modifying the implementation.

By default, this script uses a disposable database and does not touch the running
dashboard. --expect-protected checks the intended result after the recorded fix.
"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from releasedesk.server import create_server


def request(url, payload=None):
    body = None if payload is None else json.dumps(payload).encode()
    req = Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        response = urlopen(req, timeout=10)
    except HTTPError as error:
        response = error
    with response:
        return response.status, json.loads(response.read())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expect-protected", action="store_true")
    args = parser.parse_args()
    with TemporaryDirectory() as directory:
        server = create_server(Path(directory) / "race.sqlite3")
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}/api/releases/REL-1042"
        try:
            revision = request(url)[1]["release"]["revision"]
            barrier = Barrier(2)

            def review(reviewer, decision):
                barrier.wait(timeout=5)
                return request(url + "/review", {
                    "reviewer": reviewer, "decision": decision,
                    "note": f"{reviewer} submits a decision from revision {revision}.",
                    "expected_revision": revision,
                })

            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(review, "Reviewer A", "approved")
                second = pool.submit(review, "Reviewer B", "rejected")
                results = [first.result(), second.result()]
            statuses = sorted(result[0] for result in results)
            final_release = request(url)[1]["release"]
            events = request(url + "/audit")[1]["events"]
            print(json.dumps({
                "submitted_revision": revision, "http_statuses": statuses,
                "final_status": final_release["status"], "final_revision": final_release["revision"],
                "audit_event_count": len(events), "review_responses": [result[1] for result in results],
            }, indent=2))
            protected = statuses == [200, 409] and final_release["revision"] == revision + 1 and len(events) == 1
            print("PROTECTED: one decision, one audit event." if protected else
                  "DEFECT REPRODUCED: stale reviews can overwrite a decision.")
            if args.expect_protected and not protected:
                return 1
            return 0
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
