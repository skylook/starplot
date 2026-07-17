"""CLI contracts for the local exported-bundle server."""

from __future__ import annotations

from threading import Thread
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from starplot.cli import create_server


@pytest.fixture
def bundle_server(tmp_path):
    (tmp_path / "chart.html").write_bytes(b"<html>chart</html>")
    (tmp_path / "manifest.json").write_bytes(b'{"scene_id":"chart"}')
    (tmp_path / f"layer-{'a' * 64}.arrow").write_bytes(b"arrow-bytes")
    server = create_server(tmp_path, port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    yield f"http://{host}:{port}"
    server.shutdown()
    thread.join()
    server.server_close()


def test_bundle_server_preserves_bytes_mime_cache_and_root_boundary(bundle_server):
    with urlopen(f"{bundle_server}/chart.html") as response:
        assert response.read() == b"<html>chart</html>"
    with urlopen(f"{bundle_server}/manifest.json") as response:
        assert response.read() == b'{"scene_id":"chart"}'
        assert response.headers["Cache-Control"] == "no-cache"
    with urlopen(f"{bundle_server}/layer-{'a' * 64}.arrow") as response:
        assert response.read() == b"arrow-bytes"
        assert response.headers.get_content_type() == "application/vnd.apache.arrow.stream"
        assert "immutable" in response.headers["Cache-Control"]
    with pytest.raises(HTTPError) as error:
        urlopen(f"{bundle_server}/%2e%2e/pyproject.toml")
    assert error.value.code == 404


def test_bundle_server_rejects_missing_root(tmp_path):
    with pytest.raises(ValueError, match="not a directory"):
        create_server(tmp_path / "missing")
