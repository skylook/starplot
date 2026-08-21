"""Small, safe static-file handlers for local visual-parity review tools.

These extend ``SimpleHTTPRequestHandler`` with path-traversal prevention and
without the default CORS wildcard, so they are suitable only for localhost use.
"""

from __future__ import annotations

import urllib.parse
from http.server import SimpleHTTPRequestHandler
from pathlib import Path


class SafeStaticHandler(SimpleHTTPRequestHandler):
    """Serve files from a single directory without escaping it.

    Unlike the base class, this handler:

    - rejects any request path that contains ``..`` or that normalizes outside
      the configured directory;
    - does not add an ``Access-Control-Allow-Origin: *`` header.
    """

    def _forbidden_path(self, directory: Path) -> str:
        """Return a non-directory sub-path so the request fails cleanly."""
        return str(directory / ".starplot-forbidden" / "denied")

    def translate_path(self, path: str) -> str:
        directory = Path(self.directory or Path.cwd()).resolve()

        # Strip query string and fragment, then percent-decode the path.
        path = path.split("?", 1)[0].split("#", 1)[0]
        path = urllib.parse.unquote(path)

        # Split into components, dropping empty segments and "./".
        parts = [part for part in path.split("/") if part and part != "."]
        if any(part == ".." for part in parts):
            return self._forbidden_path(directory)

        # Ensure the served file stays inside the intended directory.
        target = (directory / Path(*parts)).resolve()
        try:
            target.relative_to(directory)
        except ValueError:
            return self._forbidden_path(directory)

        return str(target)

    def list_directory(self, path: str) -> None:
        # Never expose directory listings from the review output directory.
        self.send_error(404, "Directory listing disabled")

    def end_headers(self) -> None:
        # Do not add CORS wildcard; local review tools are same-origin only.
        super().end_headers()
