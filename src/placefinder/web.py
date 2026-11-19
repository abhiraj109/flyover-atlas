"""Serve the responsive interface on this computer."""

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from secrets import token_urlsafe
from tempfile import TemporaryDirectory
from threading import Lock, Thread
from urllib.parse import unquote
import webbrowser

from .gui import run_job

ASSETS = Path(__file__).with_name("workspace")
FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}
RESULTS = {
    "spec.png": "image/png",
    "winner.png": "image/png",
    "runner-up.png": "image/png",
    "results.geojson": "application/geo+json",
    "ranked-flights.csv": "text/csv",
    "summary.json": "application/json",
}
UPLOADS = {"media": 256 * 1024**2, "tracks": 32 * 1024**2}


class Workspace(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), Handler)
        self.token = token_urlsafe(24)
        self.lock = Lock()
        self.files = TemporaryDirectory(prefix="placefinder-")
        self.status = {"phase": "idle"}
        self.output = None

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server_port}"

    def run_search(self, settings):
        def notify(message):
            self.status = {"phase": "running", "message": message}

        try:
            self.output, message = run_job(settings, notify)
            self.status = {
                "phase": "done",
                "message": message,
                "files": [name for name in RESULTS if (self.output / name).is_file()],
            }
        except (ValueError, OSError) as error:
            self.status = {"phase": "error", "message": str(error)}
        except Exception:
            logging.exception("Search failed")
            self.status = {
                "phase": "error",
                "message": "The search stopped. Check that FFmpeg is installed and the recording and flight tracks can be opened.",
            }
        finally:
            for name in UPLOADS:
                (Path(self.files.name) / name).unlink(missing_ok=True)
            self.lock.release()


class Handler(BaseHTTPRequestHandler):
    def send_content(self, code, media_type, payload):
        self.send_response(code)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'"
        )
        self.end_headers()
        self.wfile.write(payload)

    def send_json(self, code, value):
        self.send_content(code, "application/json", json.dumps(value).encode())

    def local(self):
        if self.headers.get("Host") == self.server.url.removeprefix("http://"):
            return True
        self.send_error(403)
        return False

    def authorized(self):
        if not self.local():
            return False
        if (
            self.headers.get("X-Workspace-Key") == self.server.token
            and self.headers.get("Origin", self.server.url) == self.server.url
        ):
            return True
        self.send_error(403)
        return False

    def do_GET(self):
        if not self.local():
            return
        if self.path == "/favicon.ico":
            self.send_content(204, "image/x-icon", b"")
        elif self.path in FILES:
            name, content_type = FILES[self.path]
            data = (ASSETS / name).read_bytes()
            if name == "index.html":
                data = data.replace(b"WORKSPACE_KEY", self.server.token.encode())
            self.send_content(200, content_type, data)
        elif self.path == "/status" and self.authorized():
            self.send_json(200, self.server.status)
        elif self.path.startswith("/result/"):
            name = self.path.removeprefix("/result/")
            out = self.server.output
            if name in RESULTS and out and (out / name).is_file():
                self.send_content(200, RESULTS[name], (out / name).read_bytes())
            else:
                self.send_error(404)
        elif self.path != "/status":
            self.send_error(404)

    def read_search(self):
        fields = json.loads(unquote(self.headers.get("X-Search-Settings", "null")))
        length = int(self.headers.get("Content-Length", "0"))
        if fields is None and length == 0:
            return None
        if (
            not isinstance(fields, list)
            or len(fields) != 4
            or not all(isinstance(field, str) for field in fields)
        ):
            raise ValueError("The search settings could not be read.")
        media_size = int(self.headers.get("X-Recording-Bytes", "0"))
        sizes = (media_size, length - media_size)
        if any(not 0 < size <= limit for size, limit in zip(sizes, UPLOADS.values())):
            raise ValueError("Choose a recording up to 256 MB and a CSV up to 32 MB.")
        paths = []
        for (name, _), size in zip(UPLOADS.items(), sizes):
            path = Path(self.server.files.name) / name
            with path.open("wb") as file:
                while size:
                    block = self.rfile.read(min(size, 1024**2))
                    if not block:
                        raise OSError("The file transfer ended early.")
                    file.write(block)
                    size -= len(block)
            paths.append(str(path))
        return paths + fields

    def do_POST(self):
        if not self.authorized():
            return
        if self.path != "/search":
            self.send_error(404)
            return
        if not self.server.lock.acquire(blocking=False):
            self.send_json(409, {"message": "A search is already running."})
            return
        try:
            self.connection.settimeout(25)
            settings = self.read_search()
        except (ValueError, OSError) as error:
            for name in UPLOADS:
                (Path(self.server.files.name) / name).unlink(missing_ok=True)
            self.server.lock.release()
            self.send_json(400, {"message": str(error)})
            return
        self.server.output = None
        self.server.status = {"phase": "running", "message": "Starting the search…"}
        Thread(target=self.server.run_search, args=(settings,), daemon=True).start()
        self.send_json(202, self.server.status)


def main():
    with Workspace() as server:
        print(
            f"Flyover Atlas is running at {server.url}. Press Ctrl+C to close it.",
            flush=True,
        )
        webbrowser.open(server.url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.files.cleanup()


if __name__ == "__main__":
    main()
