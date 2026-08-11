"""Minimal remote SceneProvider server using only the Python standard library.

This example builds a simplified Orion scene (same field as
``map_orion_interactive.py``) and serves it through a remote ``SceneProvider``:

- ``/`` or ``/orion-remote.html`` — the client HTML shell.
- ``/scenes/orion/manifest.json`` — the scene manifest.
- ``/scenes/orion/<layer-uri>.arrow`` — individual Arrow IPC Stream layers.
- ``/scenes/orion/detail/<object-id>`` — optional catalog detail for objects.

Run this script first:

    PYTHONPATH=src python examples/interactive/remote_provider_server.py

Then open the printed URL. The client HTML uses an inline copy of the Plotly
and Arrow libraries, so after the page is loaded it does not need a CDN.
"""

from __future__ import annotations

from collections.abc import Mapping
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qsl, unquote, urlparse

from starplot import Miller, _
from starplot.interactive import (
    InteractiveMapPlot,
    SceneProvider,
    ViewportRequest,
    parse_scene_manifest,
)
from starplot.styles import PlotStyle, extensions

HOST = "127.0.0.1"
PORT = 8765
SCENE_ID = "orion"
DATA_URL = f"http://{HOST}:{PORT}/scenes/{SCENE_ID}/manifest.json"


def _build_client_html_and_provider():
    """Build the Orion scene and export the remote client HTML."""
    style = PlotStyle().extend(extensions.BLUE_LIGHT, extensions.MAP)
    p = InteractiveMapPlot(
        projection=Miller(),
        ra_min=3.6 * 15,
        ra_max=7.8 * 15,
        dec_min=-15,
        dec_max=25,
        style=style,
        resolution=4096,
        autoscale=True,
    )
    p.gridlines()
    p.constellations()
    p.stars(where=[_.magnitude < 8], where_labels=[_.magnitude < 4])
    p.constellation_labels()

    # Remote client HTML with inline libraries so it works without a CDN.
    # The manifest and layers are still served by this server.
    export = p.export_html(
        "orion-remote.html",
        data_mode="remote",
        data_url=DATA_URL,
        library_mode="inline",
        allowed_data_origins=(),
    )

    manifest = parse_scene_manifest(export.manifest_bytes)
    provider = SceneProvider(
        manifest,
        export.manifest_bytes,
        export.layer_bytes,
        detail_provider=_CatalogDetailProvider(),
    )
    uri_to_id = {layer.data_source.uri: layer.id for layer in manifest.layers}
    return export.html_path, provider, uri_to_id


class _CatalogDetailProvider:
    """Placeholder detail provider that echoes object_id.

    A real implementation would look up the object in a catalog database.
    This is only used when layers declare ``InteractionPolicy.HOVER_AND_DETAIL``
    and the client requests an object detail.
    """

    def get_object(self, object_id: str) -> Mapping[str, object] | None:
        return {
            "object_id": object_id,
            "name": object_id,
            "detail": "Replace with a real catalog lookup.",
        }


def _viewport_request(query: Mapping[str, str]) -> ViewportRequest | None:
    """Convert the JavaScript loader's query string into a ViewportRequest."""

    def maybe(name: str, conv):
        value = query.get(name)
        return conv(value) if value is not None else None

    try:
        req = ViewportRequest(
            x_min=maybe("x_min", float),
            x_max=maybe("x_max", float),
            y_min=maybe("y_min", float),
            y_max=maybe("y_max", float),
            pixel_width=maybe("pixel_width", int),
            pixel_height=maybe("pixel_height", int),
            lod=maybe("lod", int),
            magnitude_max=maybe("magnitude_max", float),
            point_budget=maybe("point_budget", int),
        )
    except (ValueError, TypeError):
        return None

    return None if req.is_full else req


class _Handler(BaseHTTPRequestHandler):
    html_bytes: bytes = b""
    provider: SceneProvider | None = None
    uri_to_id: dict[str, str] = {}

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = dict(parse_qsl(parsed.query))

        if path in ("/", "/orion-remote.html"):
            self._send(200, "text/html; charset=utf-8", self.html_bytes)
            return

        parts = [part for part in path.split("/") if part]
        if (
            len(parts) < 3
            or parts[0] != "scenes"
            or parts[1] != SCENE_ID
        ):
            self._send(404, "text/plain", b"Not found")
            return

        if parts[2:] == ["manifest.json"]:
            resp = self.provider.manifest(self.headers.get("If-None-Match"))
        elif len(parts) == 4 and parts[2] == "detail":
            object_id = parts[3]
            resp = self.provider.object_detail(object_id)
        else:
            layer_uri = "/".join(parts[2:])
            layer_id = self.uri_to_id.get(layer_uri)
            if layer_id is None:
                self._send(404, "text/plain", b"Layer not found")
                return
            viewport = _viewport_request(query)
            resp = self.provider.layer(
                layer_id,
                viewport,
                self.headers.get("If-None-Match"),
            )

        self._send(resp.status, resp.headers.get("Content-Type"), resp.body_bytes())

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        """Keep server output concise."""
        print(f"{self.address_string()} {format % args}")


def main() -> None:
    html_path, provider, uri_to_id = _build_client_html_and_provider()
    _Handler.html_bytes = html_path.read_bytes()
    _Handler.provider = provider
    _Handler.uri_to_id = uri_to_id

    server = ThreadingHTTPServer((HOST, PORT), _Handler)
    print(f"Serving {html_path} and SceneProvider at http://{HOST}:{PORT}/")
    print(f"Manifest endpoint: {DATA_URL}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
