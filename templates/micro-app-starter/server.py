#!/usr/bin/env python3
"""
Standard Library Python 3.12 Microservice Runtime
Features:
- Zero external dependencies (instant container build & tiny attack surface)
- Persistent SQLite database on Azure Files volume mount with WAL mode
- Automated health probes (/healthz) for Azure Container Apps liveness checks
- Microsoft Entra ID EasyAuth identity extraction from injection headers
- Clean REST API and static asset server
"""

import os
import sys
import json
import signal
import sqlite3
import mimetypes
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

PORT = int(os.environ.get("PORT", 8080))
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DB_PATH = DATA_DIR / "app.sqlite"
SRC_DIR = Path(__file__).resolve().parent / "src"


def init_db():
    """Initializes persistent SQLite database with WAL mode."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"[WARN] Could not create {DATA_DIR}: {e}", file=sys.stderr)

    conn = sqlite3.connect(DB_PATH)
    # Enable Write-Ahead Logging (WAL) for concurrent read access
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
    conn.close()
    print(f"[INFO] SQLite database initialized at {DB_PATH} with WAL mode.")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


class AppRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Clean formatted logging
        sys.stdout.write(f"[{self.log_date_time_string()}] {self.address_string()} - {format % args}\n")

    def send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def extract_identity(self):
        """Extracts caller identity injected by Azure Container Apps EasyAuth SSO."""
        user_name = self.headers.get("X-MS-CLIENT-PRINCIPAL-NAME") or "Anonymous Developer"
        user_id = self.headers.get("X-MS-CLIENT-PRINCIPAL-ID") or "local-dev-id"
        id_provider = self.headers.get("X-MS-CLIENT-PRINCIPAL-IDP") or "local"
        return {
            "name": user_name,
            "id": user_id,
            "provider": id_provider,
            "authenticated": self.headers.get("X-MS-CLIENT-PRINCIPAL-NAME") is not None
        }

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # 1. Health Probe for ACA Ingress & Probes
        if path == "/healthz" or path == "/api/health":
            self.send_json({
                "status": "healthy",
                "uptime": "ok",
                "database": "connected" if DB_PATH.exists() else "uninitialized"
            })
            return

        # 2. Auth Identity Info
        if path == "/api/user":
            self.send_json(self.extract_identity())
            return

        # 3. REST API: List records
        if path == "/api/records":
            try:
                conn = get_db()
                rows = conn.execute("SELECT id, title, category, created_by, created_at FROM records ORDER BY id DESC").fetchall()
                conn.close()
                records = [dict(r) for r in rows]
                self.send_json(records)
            except Exception as e:
                self.send_json({"error": str(e)}, status=500)
            return

        # 4. Static Files (SPA Serving)
        self.serve_static(path)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/records":
            length = int(self.headers.get("Content-Length", 0))
            if length == 0:
                self.send_json({"error": "Missing payload"}, status=400)
                return

            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                title = payload.get("title", "").strip()
                category = payload.get("category", "General").strip()

                if not title:
                    self.send_json({"error": "Field 'title' is required"}, status=400)
                    return

                user = self.extract_identity()
                created_by = user["name"]

                conn = get_db()
                with conn:
                    cur = conn.execute(
                        "INSERT INTO records (title, category, created_by) VALUES (?, ?, ?)",
                        (title, category, created_by)
                    )
                    record_id = cur.lastrowid
                conn.close()

                self.send_json({
                    "id": record_id,
                    "title": title,
                    "category": category,
                    "created_by": created_by
                }, status=201)
            except Exception as e:
                self.send_json({"error": str(e)}, status=500)
            return

        self.send_json({"error": "Not Found"}, status=404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/records/"):
            try:
                rec_id = int(path.split("/")[-1])
                conn = get_db()
                with conn:
                    conn.execute("DELETE FROM records WHERE id = ?", (rec_id,))
                conn.close()
                self.send_json({"success": True, "deleted_id": rec_id})
            except Exception as e:
                self.send_json({"error": str(e)}, status=500)
            return

        self.send_json({"error": "Not Found"}, status=404)

    def serve_static(self, path):
        if path == "/" or not path:
            file_path = SRC_DIR / "index.html"
        else:
            rel = path.lstrip("/")
            file_path = (SRC_DIR / rel).resolve()

        # Prevent directory traversal
        if not str(file_path).startswith(str(SRC_DIR)) or not file_path.exists() or file_path.is_dir():
            file_path = SRC_DIR / "index.html"

        mime, _ = mimetypes.guess_type(str(file_path))
        mime = mime or "application/octet-stream"

        try:
            content = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_json({"error": f"Error loading asset: {e}"}, status=500)


def run_server():
    init_db()
    server_address = ("", PORT)
    httpd = HTTPServer(server_address, AppRequestHandler)
    print(f"[INFO] Server listening on http://0.0.0.0:{PORT}")

    def shutdown_handler(signum, frame):
        print(f"\n[INFO] Signal {signum} received, shutting down gracefully...")
        httpd.server_close()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)

    httpd.serve_forever()


if __name__ == "__main__":
    run_server()
