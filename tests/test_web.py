from contextlib import contextmanager
import json
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import pytest

from placefinder import web


@contextmanager
def workspace():
    with web.Workspace() as server:
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            yield server
        finally:
            server.shutdown()
            worker.join()
            server.files.cleanup()


def test_workspace_accepts_only_local_authorized_searches(monkeypatch):
    def receive(settings, _notify):
        assert Path(settings[0]).read_bytes() == b"media"
        assert Path(settings[1]).read_bytes() == b"tracks"
        assert settings[2:] == [
            "35 80 92 171",
            "",
            "34.9 35.1 -100.1 -99.9",
            "1700000000",
        ]
        raise ValueError("Test recording")

    monkeypatch.setattr(web, "run_job", receive)
    with workspace() as server:
        with pytest.raises(HTTPError) as error:
            urlopen(Request(server.url + "/search", data=b"", method="POST"))
        assert error.value.code == 403

        fields = ["35 80 92 171", "", "34.9 35.1 -100.1 -99.9", "1700000000"]
        request = Request(
            server.url + "/search",
            data=b"mediatracks",
            headers={
                "X-Workspace-Key": server.token,
                "X-Search-Settings": quote(json.dumps(fields)),
                "X-Recording-Bytes": "5",
            },
        )
        with urlopen(request) as response:
            assert response.status == 202
        with server.lock:
            assert server.status == {"phase": "error", "message": "Test recording"}
            assert not list(Path(server.files.name).iterdir())
