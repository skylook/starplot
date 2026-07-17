"""Small command-line helpers for Starplot setup and exported Scene bundles."""

from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import webbrowser

from starplot.config import settings
from starplot.data import db
from starplot.data.catalogs import download_all_catalogs
from starplot.styles import fonts


def setup(_options=()):
    print("Installing DuckDB spatial extension...")
    con = db.connect()
    con.load_extension("spatial")
    fonts.load()
    print(f"Downloading data catalogs to: {settings.data_path}")
    download_all_catalogs()


class _BundleHandler(SimpleHTTPRequestHandler):
    """Static handler confined to one resolved bundle root."""

    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".arrow": "application/vnd.apache.arrow.stream",
    }

    def __init__(self, *args, directory: str, **kwargs):
        self._root = Path(directory).resolve()
        super().__init__(*args, directory=str(self._root), **kwargs)

    def translate_path(self, path):
        candidate = Path(super().translate_path(path)).resolve()
        if candidate != self._root and self._root not in candidate.parents:
            return str(self._root / ".starplot-forbidden")
        return str(candidate)

    def end_headers(self):
        filename = Path(self.translate_path(self.path)).name
        if filename == "manifest.json":
            self.send_header("Cache-Control", "no-cache")
        elif filename.endswith(".arrow") and filename.startswith("layer-"):
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        super().end_headers()

    def log_message(self, _format, *_args):
        """Keep library/server tests quiet; the URL is printed by ``serve``."""


def create_server(directory: str | Path, host: str = "127.0.0.1", port: int = 8000):
    """Create, but do not start, a root-confined bundle HTTP server."""
    root = Path(directory).resolve()
    if not root.is_dir():
        raise ValueError(f"serve directory is not a directory: {root}")
    return ThreadingHTTPServer((host, port), partial(_BundleHandler, directory=str(root)))


def serve(directory: str | Path, host: str = "127.0.0.1", port: int = 8000,
          open_browser: bool = True) -> None:
    """Serve an exported bundle until interrupted by the user."""
    server = create_server(directory, host, port)
    address, actual_port = server.server_address[:2]
    url = f"http://{address}:{actual_port}/"
    print(f"Serving {Path(directory).resolve()} at {url}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="starplot")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("setup", help="install data and extensions")
    serve_parser = commands.add_parser("serve", help="serve exported Scene bundles locally")
    serve_parser.add_argument("directory")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.add_argument("--no-open", action="store_true")
    return parser


def main(argv=None):
    arguments = _parser().parse_args(argv)
    if arguments.command == "setup":
        setup()
    else:
        serve(arguments.directory, arguments.host, arguments.port, not arguments.no_open)


if __name__ == "__main__":
    main(sys.argv[1:])
