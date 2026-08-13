"""A local stand-in for the Algolia search host and the GW image CDN.

Lets the real network code path — `query_catalog`, `detect_grid`,
`download_cardinals`, the caching, the whole `build()` — run under test without
touching warhammer.com.
"""

from __future__ import annotations

import io
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from whproxy.offline import render_frame

CATALOG_HITS = [
    {
        "objectID": "prod-norn-emissary",
        "name": "Norn Emissary",
        "slug": "tyranids-norn-emissary",
        "sku": "99120106064",
        "images": [
            "/app/resources/catalog/product/threeSixty/99120106064_TyrNornAssimilator2023OTT1360/01-12.jpg",
            "/app/resources/catalog/product/threeSixty/99120106064_TyrNornEmissary2023OTT1360/01-12.jpg",
        ],
    },
    {
        "objectID": "prod-hive-tyrant",
        "name": "Tyranids: Winged Hive Tyrant",
        "slug": "tyranids-winged-hive-tyrant",
        "sku": "99120106056",
        "images": [
            "/app/resources/catalog/product/threeSixty/99120106056_WingedHiveTyrant360/01-12.jpg"
        ],
    },
]

ROWS = 3
ANGLES = 12
SPIN_PREFIX = "/app/resources/catalog/product/threeSixty/"


class _Handler(BaseHTTPRequestHandler):
    frame_cache: dict[tuple[str, int], bytes] = {}
    request_log: list[tuple[str, str]] = []

    def log_message(self, *args):  # silence the default stderr spam
        pass

    # -- helpers ---------------------------------------------------------

    def _frame_bytes(self, folder: str, index: int) -> bytes:
        key = (folder, index)
        if key not in self.frame_cache:
            img = render_frame(folder, index, ANGLES, out_height=420)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=92)
            self.frame_cache[key] = buf.getvalue()
        return self.frame_cache[key]

    def _parse_frame_path(self, path: str):
        if not path.startswith(SPIN_PREFIX):
            return None
        rest = path[len(SPIN_PREFIX):]
        parts = rest.split("/")
        if len(parts) != 2 or not parts[1].endswith(".jpg"):
            return None
        folder, name = parts
        stem = name[:-4]
        try:
            row, col = (int(v) for v in stem.split("-"))
        except ValueError:
            return None
        if not (1 <= row <= ROWS and 1 <= col <= ANGLES):
            return None
        return folder, row, col

    def _send(self, code: int, body: bytes, content_type: str, head_only: bool):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _serve_image(self, head_only: bool):
        self.request_log.append(("HEAD" if head_only else "GET", self.path))
        parsed = self._parse_frame_path(self.path)
        if parsed is None:
            self._send(404, b"not found", "text/plain", head_only)
            return
        folder, _row, col = parsed
        self._send(200, self._frame_bytes(folder, col), "image/jpeg", head_only)

    # -- verbs -----------------------------------------------------------

    def do_HEAD(self):
        self._serve_image(head_only=True)

    def do_GET(self):
        self._serve_image(head_only=False)

    def do_POST(self):
        self.request_log.append(("POST", self.path))
        if "/1/indexes/" not in self.path or not self.path.endswith("/query"):
            self._send(404, b"not found", "text/plain", False)
            return

        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        query = (payload.get("query") or "").lower()

        hits = [
            h for h in CATALOG_HITS
            if not query or any(w in h["name"].lower() for w in query.split())
        ] or CATALOG_HITS

        body = json.dumps({"hits": hits, "nbHits": len(hits)}).encode()
        self._send(200, body, "application/json", False)


class MockGW:
    """Context manager yielding the base URL of a running mock host."""

    def __init__(self):
        self._server = HTTPServer(("127.0.0.1", 0), _Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def requests(self) -> list[tuple[str, str]]:
        return list(_Handler.request_log)

    def __enter__(self):
        _Handler.request_log.clear()
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
        return False
