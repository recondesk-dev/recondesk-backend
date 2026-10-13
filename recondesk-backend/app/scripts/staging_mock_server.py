"""Lightweight external service mock server for ReconDesk Staging.

Provides mock responses for:
1. Object Storage (Cloudflare R2 / AWS S3 compatibility): HEAD, GET, PUT, DELETE
2. GSTN Sandbox APIs: Authentication, GSP pass-through, filing stubs
3. Razorpay webhook verification stubs
"""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
import sys

_log = logging.getLogger("staging.mock.server")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class StagingMockHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Concise logging for mock requests
        _log.info("%s - %s", self.address_string(), format % args)

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("ETag", '"staging-mock-etag-12345"')
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        resp = {
            "status": "ok",
            "mock": True,
            "environment": "staging",
            "path": self.path,
        }
        self.wfile.write(json.dumps(resp).encode("utf-8"))

    def do_PUT(self):
        # S3 PutObject mock
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > 0:
            _ = self.rfile.read(content_length)
        self.send_response(200)
        self.send_header("ETag", '"staging-mock-etag-12345"')
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        payload = {}
        if content_length > 0:
            try:
                body = self.rfile.read(content_length)
                payload = json.loads(body.decode("utf-8"))
            except Exception:
                pass

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()

        # Handle Sandbox / GSTN auth or filing mock responses
        if "authenticate" in self.path or "token" in self.path:
            resp = {
                "access_token": "staging-mock-token-abc123xyz",
                "expires_in": 3600,
                "status_cd": "1",
                "message": "Authenticated (Mock Staging)",
            }
        else:
            resp = {
                "status_cd": "1",
                "status": "SUCCESS",
                "message": "Operation accepted by staging mock",
                "reference_id": "STG-REF-99999",
                "txn_id": "STG-TXN-12345",
                "mock": True,
            }
        self.wfile.write(json.dumps(resp).encode("utf-8"))

    def do_DELETE(self):
        self.send_response(204)
        self.end_headers()


def run_server(port: int = 9000):
    server_address = ("0.0.0.0", port)
    httpd = HTTPServer(server_address, StagingMockHandler)
    _log.info("Staging Mock Server listening on port %d...", port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        _log.info("Staging Mock Server shutting down.")
        httpd.server_close()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9000
    run_server(port)
