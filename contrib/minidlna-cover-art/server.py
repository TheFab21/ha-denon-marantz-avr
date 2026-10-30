#!/usr/bin/env python3
"""Optional MiniDLNA folder-art lookup service for HEOS media browsing."""

import json
import os
import re
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

DB_PATH = os.environ.get("MINIDLNA_DB_PATH", "/var/cache/minidlna/files.db")
BASE_URL = os.environ.get("MINIDLNA_BASE_URL", "http://127.0.0.1:8200").rstrip("/")
LISTEN_HOST = os.environ.get("COVER_LISTEN_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("COVER_LISTEN_PORT", "8765"))
VALID_CONTAINER_ID = re.compile(r"[A-Za-z0-9$_.-]{1,200}\Z")


class CoverHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/":
            self.send_error(404)
            return
        raw_id = parse_qs(parsed.query).get("container_id", [""])[0]
        if not VALID_CONTAINER_ID.fullmatch(raw_id):
            self.send_error(400, "Missing or invalid container_id")
            return

        try:
            # URI mode=ro prevents accidental writes to MiniDLNA's database.
            with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=3) as db:
                row = db.execute(
                    """
                    SELECT d.ID, d.ALBUM_ART
                    FROM OBJECTS AS o
                    JOIN DETAILS AS d ON d.ID = o.DETAIL_ID
                    WHERE o.OBJECT_ID = ?
                      AND o.CLASS = 'container.storageFolder'
                      AND d.ALBUM_ART > 0
                    LIMIT 1
                    """,
                    (raw_id,),
                ).fetchone()
        except sqlite3.Error:
            self.send_error(500, "Database lookup failed")
            return

        thumbnail = (
            f"{BASE_URL}/AlbumArt/{row[1]}-{row[0]}.jpg" if row else None
        )
        body = json.dumps({"thumbnail": thumbnail}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), CoverHandler).serve_forever()
