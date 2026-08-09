#!/usr/bin/env python3
"""Render and verify one example through every Scene transport.

Usage::

    python tools/visual_parity/gen_comparison.py horizon_double_cluster --transports inline,external,provider

Each interactive example compiles exactly one ``ScenePackage``.  Inline,
external-Arrow and provider-backed pages are exported from that same object,
their canonical wire bytes are compared before a real browser renders them.
"""

from __future__ import annotations

import argparse
import base64
from collections.abc import Mapping
import hashlib
from html.parser import HTMLParser
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
from urllib.parse import unquote
from urllib.request import Request, urlopen

if __package__:
    from . import crops
    from .server import SafeStaticHandler
else:
    import crops
    from server import SafeStaticHandler
import numpy as np

from starplot.interactive.arrow_transport import decode_layer_stream
from starplot.interactive.scene_manifest import parse_scene_manifest
from starplot.interactive.scene_provider import SceneProvider


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "comparison_outputs"
DATA_CACHE = OUTPUT / ".data-cache"
ALL_TRANSPORTS = ("inline", "external", "provider")
_EXAMPLE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_VISUAL_RUNTIME_ASSETS = (
    Path("src/starplot/interactive/assets/starplot-scene-loader.js"),
    Path("src/starplot/interactive/assets/plotly-scene-adapter.js"),
)


def _validate_name(name: str) -> None:
    if not name or not _EXAMPLE_NAME_RE.fullmatch(name):
        raise ValueError(f"invalid example name: {name!r}")


def _git_stdout(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout


def _visual_evidence_provenance(root: Path = ROOT) -> dict[str, object]:
    """Bind comparison artifacts to the revision and browser runtime assets."""
    return {
        "git_revision": _git_stdout(root, "rev-parse", "HEAD").strip(),
        "tracked_dirty": bool(
            _git_stdout(root, "status", "--porcelain", "--untracked-files=no").strip()
        ),
        "assets": {
            path.as_posix(): hashlib.sha256((root / path).read_bytes()).hexdigest()
            for path in _VISUAL_RUNTIME_ASSETS
        },
    }


class _InlinePayloadParser(HTMLParser):
    """Extract manifest and layer payloads from an inline HTML export."""

    def __init__(self):
        super().__init__()
        self._current_id: str | None = None
        self.scripts: dict[str, str] = {}
        self.script_types: dict[str, str] = {}

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            attributes = dict(attrs)
            self._current_id = attributes.get("id")
            if self._current_id is not None:
                self.script_types[self._current_id] = attributes.get("type", "")

    def handle_data(self, data):
        if self._current_id is not None:
            self.scripts[self._current_id] = self.scripts.get(self._current_id, "") + data

    def handle_endtag(self, tag):
        if tag == "script":
            self._current_id = None


def _read_inline_export(path: Path) -> tuple[bytes, Mapping[str, bytes]]:
    parser = _InlinePayloadParser()
    parser.feed(path.read_text(encoding="utf-8"))
    manifest_payload = parser.scripts["starplot-manifest"]
    if (
        parser.script_types.get("starplot-manifest")
        == "application/vnd.starplot.manifest+base64"
    ):
        manifest_bytes = base64.b64decode(manifest_payload.encode("ascii"), validate=True)
    else:
        manifest_bytes = manifest_payload.replace("<\\/", "</").encode("utf-8")
    manifest = parse_scene_manifest(manifest_bytes)
    layers = {
        layer.id: base64.b64decode(parser.scripts[f"starplot-layer-{index}"].encode("ascii"))
        for index, layer in enumerate(manifest.layers)
    }
    return manifest_bytes, layers


def _read_external_export(bundle: Path) -> tuple[bytes, Mapping[str, bytes]]:
    manifest_bytes = (bundle / "manifest.json").read_bytes()
    manifest = parse_scene_manifest(manifest_bytes)
    return manifest_bytes, {
        layer.id: (bundle / layer.data_source.uri).read_bytes()
        for layer in manifest.layers
    }


def _assert_same_array(left: np.ndarray, right: np.ndarray, description: str) -> None:
    if left.dtype != right.dtype or left.shape != right.shape:
        raise AssertionError(f"{description}: dtype/shape differs: {left.dtype}{left.shape} != {right.dtype}{right.shape}")
    if np.issubdtype(left.dtype, np.inexact):
        if not np.array_equal(left, right, equal_nan=True):
            raise AssertionError(f"{description}: values differ")
    elif not np.array_equal(left, right):
        raise AssertionError(f"{description}: values differ")


def _assert_decoded_columns_equal(manifest_bytes: bytes, expected: Mapping[str, bytes], actual: Mapping[str, bytes], label: str) -> None:
    manifest = parse_scene_manifest(manifest_bytes)
    for layer in manifest.layers:
        expected_layer = decode_layer_stream(expected[layer.id], manifest.resolve_layer(layer.id))
        actual_layer = decode_layer_stream(actual[layer.id], manifest.resolve_layer(layer.id))
        if expected_layer.data.columns.keys() != actual_layer.data.columns.keys():
            raise AssertionError(f"{label}/{layer.id}: column names differ")
        for name in expected_layer.data.columns:
            _assert_same_array(
                expected_layer.data[name], actual_layer.data[name], f"{label}/{layer.id}/{name}"
            )


class _ProviderHandler(SafeStaticHandler):
    """Serve provider transport requests over the test HTTP server."""

    def __init__(self, *args, state: dict, **kwargs):
        self._state = state
        super().__init__(*args, **kwargs)

    def log_message(self, _format, *_args):
        pass

    def _send_response(self, response):
        self.send_response(response.status)
        for name, value in response.headers.items():
            self.send_header(name, value)
        self.end_headers()
        for chunk in response.iter_body():
            self.wfile.write(chunk)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        provider = self._state.get("provider")
        manifest = self._state.get("manifest")
        if path == "/provider/manifest.json":
            if provider is None:
                self.send_error(500, "Provider not configured")
                return
            self._send_response(provider.manifest(self.headers.get("If-None-Match")))
            return
        if path.startswith("/provider/"):
            if provider is None or manifest is None:
                self.send_error(500, "Provider not configured")
                return
            name = unquote(path.removeprefix("/provider/"))
            if not name or "/" in name or name.startswith(".."):
                self.send_error(404)
                return
            layer = next(
                (item for item in manifest.layers if item.data_source.uri == name), None
            )
            if layer is None:
                self.send_error(404)
                return
            self._send_response(provider.layer(layer.id, if_none_match=self.headers.get("If-None-Match")))
            return
        super().do_GET()


class _ProviderServer:
    """A local HTTP server that can switch to provider mode on demand.

    Serves the example output folder so inline/external/provider HTML pages
    and the external ``.scene`` bundle can be loaded from a single origin.
    """

    def __init__(self, folder: Path):
        self._state = {"provider": None, "manifest": None}
        self._folder = folder

        def handler(*args, **kwargs):
            return _ProviderHandler(
                *args,
                state=self._state,
                directory=str(self._folder),
                **kwargs,
            )

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def origin(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self):
        self.thread.start()

    def configure(self, manifest_bytes: bytes, layers: Mapping[str, bytes]):
        manifest = parse_scene_manifest(manifest_bytes)
        self._state["provider"] = SceneProvider(manifest, manifest_bytes, layers)
        self._state["manifest"] = manifest

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self._state["provider"] = None
        self._state["manifest"] = None


def _request_bytes(url: str) -> tuple[bytes, Mapping[str, str]]:
    with urlopen(Request(url), timeout=60) as response:
        return response.read(), {k.lower(): v for k, v in response.headers.items()}


def _verify_transports(folder: Path, server: _ProviderServer, exports: dict, transports: tuple[str, ...]) -> dict:
    """Verify that every selected transport exposes the same canonical Scene bytes."""
    selected = set(transports)
    if not selected:
        raise ValueError("at least one transport must be selected")

    def load_transport(name: str) -> tuple[bytes, Mapping[str, bytes]]:
        if name == "inline":
            return _read_inline_export(folder / exports["inline_html"])
        if name == "external":
            return _read_external_export(folder / exports["external_bundle"])
        if name == "provider":
            manifest, headers = _request_bytes(f"{server.origin}/provider/manifest.json")
            cache_control = {
                d.strip().lower()
                for d in headers.get("cache-control", "").split(",")
            }
            if "no-cache" not in cache_control:
                raise AssertionError("provider manifest cache policy differs")
            parsed = parse_scene_manifest(manifest)
            layers: dict[str, bytes] = {}
            for layer in parsed.layers:
                url = f"{server.origin}/provider/{layer.data_source.uri}"
                payload, layer_headers = _request_bytes(url)
                content_type = layer_headers.get("content-type", "").split(";")[0].strip().lower()
                if content_type != "application/vnd.apache.arrow.stream":
                    raise AssertionError(f"provider/{layer.id}: Arrow media type differs")
                layers[layer.id] = payload
            return manifest, layers
        raise ValueError(f"unknown transport: {name}")

    # Use a local file-based transport as the reference so the server can be
    # configured before the provider transport is queried.
    reference_candidates = [t for t in ("external", "inline") if t in selected]
    if "provider" in selected and not reference_candidates:
        raise ValueError("provider transport requires inline or external as a reference")
    reference_name = reference_candidates[0]
    reference_manifest, reference_layers = load_transport(reference_name)
    server.configure(reference_manifest, reference_layers)

    by_transport: dict[str, tuple[bytes, Mapping[str, bytes]]] = {
        reference_name: (reference_manifest, reference_layers),
    }
    for name in selected:
        if name == reference_name:
            continue
        by_transport[name] = load_transport(name)

    for name, (manifest, layers) in by_transport.items():
        if name == reference_name:
            continue
        if manifest != reference_manifest:
            raise AssertionError(f"{name} canonical manifest bytes differ from {reference_name}")
        if layers != reference_layers:
            raise AssertionError(f"{name} Arrow bytes differ from {reference_name}")
        _assert_decoded_columns_equal(reference_manifest, reference_layers, layers, name)

    manifest = parse_scene_manifest(reference_manifest)
    return {
        "scene_hash": manifest.content_hash,
        "manifest_sha256": hashlib.sha256(reference_manifest).hexdigest(),
        "layers": [
            {
                "id": layer.id,
                "rows": layer.row_count,
                "bytes": layer.byte_length,
                "sha256": hashlib.sha256(reference_layers[layer.id]).hexdigest(),
            }
            for layer in manifest.layers
        ],
    }


def _launch_browser(playwright):
    try:
        return playwright.chromium.launch(headless=True)
    except Exception as error:
        candidates = [
            Path("/usr/bin/chromium"),
            Path("/usr/bin/chromium-browser"),
            Path("/usr/bin/google-chrome"),
            Path("/usr/bin/google-chrome-stable"),
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
        ]
        for candidate in candidates:
            if candidate.is_file():
                return playwright.chromium.launch(executable_path=str(candidate), headless=True)
        raise RuntimeError(
            "Could not launch a Chromium browser. Install Playwright browsers with "
            "'playwright install chromium' or put a Chrome/Chromium binary on PATH."
        ) from error


def _browser_screenshots(folder: Path, server: _ProviderServer, width: int, height: int, transports: tuple[str, ...], html_files: dict[str, str]) -> dict[str, dict]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise RuntimeError(
            "playwright is required for browser screenshots. "
            "Install it with: pip install playwright && playwright install chromium"
        ) from error

    reports: dict[str, dict] = {}
    with sync_playwright() as playwright:
        browser = _launch_browser(playwright)
        try:
            for name in transports:
                page_errors: list[str] = []
                page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
                try:
                    page.on("pageerror", lambda error: page_errors.append(str(error)))
                    html_file = html_files[name]
                    print(f"  browser {name}: loading {html_file}", flush=True)
                    page.goto(f"{server.origin}/{html_file}", wait_until="load", timeout=300_000)
                    page.wait_for_function(
                        "() => document.body.dataset.starplotRendered === 'true' || document.body.dataset.starplotError",
                        timeout=300_000,
                    )
                    error = page.locator("body").get_attribute("data-starplot-error")
                    if error:
                        raise RuntimeError(f"{name} browser export failed: {error}")
                    if page_errors:
                        raise RuntimeError(f"{name} browser page errors: {page_errors}")
                    if page.locator("#starplot-chart .plotly").count() != 1:
                        raise RuntimeError(f"{name} did not create a Plotly chart")
                    report = page.evaluate("""() => {
                        const graph = document.getElementById('starplot-chart');
                        const traces = Array.from(graph.data || []);
                        return {
                          trace_count: traces.length,
                          layer_ids: traces.map((trace) => trace.meta && trace.meta.starplot_layer_id),
                          trace_types: traces.reduce((counts, trace) => {
                            counts[trace.type] = (counts[trace.type] || 0) + 1;
                            return counts;
                          }, {}),
                          svg_trace_count: graph.querySelectorAll('.scatterlayer > .trace').length,
                          canvas_count: graph.querySelectorAll('canvas').length,
                        };
                    }""")
                    reports[name] = report
                    page.screenshot(path=str(folder / f"{name}.png"), full_page=False)
                    print(f"  browser {name}: captured", flush=True)
                finally:
                    page.close()
        finally:
            browser.close()
    return reports


def _write_diff(folder: Path, name: str, transports: tuple[str, ...], exports: dict) -> None:
    from contextlib import ExitStack
    from PIL import Image

    def compare(left, right):
        # Composite onto white to match the background used by crops.diff_stats.
        left_rgb = crops.composite_on_color(left, (255, 255, 255))
        right_rgb = crops.composite_on_color(right, (255, 255, 255))
        left_array = np.asarray(left_rgb, dtype=np.float32)
        right_array = np.asarray(right_rgb, dtype=np.float32)
        if left_array.shape != right_array.shape:
            return f"size mismatch {left.size} vs {right.size}"
        delta = np.abs(left_array - right_array)
        return f"mean={delta.mean():.2f}; nonzero={np.count_nonzero(delta) / delta.size * 100:.2f}%"

    # Prefer the Plotly static snapshot when kaleido produced one; otherwise fall
    # back to the matplotlib export from the Interactive*Plot class.
    plotly_path = exports.get("plotly_png")
    rows = []
    with ExitStack() as stack:
        original = stack.enter_context(Image.open(folder / "orig.png"))
        static_interactive = stack.enter_context(Image.open(folder / "interactive.png"))
        interactive = (
            stack.enter_context(Image.open(folder / plotly_path))
            if plotly_path
            else static_interactive
        )
        browser_images = {
            transport: stack.enter_context(Image.open(folder / f"{transport}.png"))
            for transport in transports
        }

        rows.append(("orig vs interactive", compare(original, interactive.resize(original.size, Image.Resampling.LANCZOS))))
        if plotly_path:
            rows.append(("orig vs interactive_matplotlib", compare(original, static_interactive.resize(original.size, Image.Resampling.LANCZOS))))
        for transport_name, image in browser_images.items():
            orig_for_browser = original.resize(image.size, Image.Resampling.LANCZOS)
            rows.append((f"orig vs {transport_name}", compare(orig_for_browser, image)))
        for transport_name, image in browser_images.items():
            rows.append((f"interactive vs {transport_name}", compare(interactive.resize(image.size, Image.Resampling.LANCZOS), image)))
        if plotly_path:
            rows.append(("interactive_matplotlib vs interactive", compare(static_interactive.resize(interactive.size, Image.Resampling.LANCZOS), interactive)))
        for index, left_name in enumerate(transports):
            for right_name in transports[index + 1:]:
                rows.append((f"{left_name} vs {right_name}", compare(browser_images[left_name], browser_images[right_name])))
    (folder / "diff.md").write_text(
        "\n".join([f"# {name} transport diff", "", "| pair | diagnostic |", "|---|---|"] + [f"| {label} | {result} |" for label, result in rows]) + "\n",
        encoding="utf-8",
    )

    # Local semantic crop comparisons.  Use a curated set that covers the
    # static-interactive comparison, original-to-each-transport,
    # interactive-to-each-transport, and transport-to-transport consistency.
    crops_dir = folder / "crops"
    crops_dir.mkdir(parents=True, exist_ok=True)
    pairs: list[tuple[str, Path, Path, str]] = [
        ("orig vs interactive", folder / "orig.png", folder / (plotly_path or "interactive.png"), "left"),
    ]
    if plotly_path:
        pairs.append(("orig vs interactive_matplotlib", folder / "orig.png", folder / "interactive.png", "left"))
    for transport_name in transports:
        pairs.append((f"orig vs {transport_name}", folder / "orig.png", folder / f"{transport_name}.png", "right"))
        pairs.append((f"interactive vs {transport_name}", folder / (plotly_path or "interactive.png"), folder / f"{transport_name}.png", "right"))
    if plotly_path:
        pairs.append(("interactive_matplotlib vs interactive", folder / "interactive.png", folder / plotly_path, "right"))
    for index, left_name in enumerate(transports):
        for right_name in transports[index + 1:]:
            pairs.append((f"{left_name} vs {right_name}", folder / f"{left_name}.png", folder / f"{right_name}.png", "left"))

    crop_sections = []
    for label, left_path, right_path, reference in pairs:
        review = crops.build_pair_review(
            left_path, right_path, crops_dir, label,
            root_dir=folder, semantic=True, reference=reference,
        )
        section_lines = [
            f"## {label}",
            "",
            f"Full: MAE={review['full_stats']['mae']} RMSE={review['full_stats']['rmse']} "
            f"nonzero={review['full_stats']['nonzero_gt5']}% max={review['full_stats']['max_diff']}",
            "",
            "| crop | combined | diff |",
            "|---|---|---|",
        ]
        for crop in review["crops"]:
            section_lines.append(
                f"| {crop['name']} ({crop['desc']}) "
                f"MAE={crop['stats']['mae']} RMSE={crop['stats']['rmse']} "
                f"nonzero={crop['stats']['nonzero_gt5']}% max={crop['stats']['max_diff']} | "
                f"![combined]({crop['combined']}) | ![diff]({crop['diff']}) |"
            )
        section_lines.append("")
        crop_sections.append("\n".join(section_lines))
    (folder / "crops.md").write_text(
        "\n".join([f"# {name} local crop comparisons", ""] + crop_sections),
        encoding="utf-8",
    )


def _snapshot_pngs(folder: Path) -> frozenset[Path]:
    """Return the set of PNG file paths currently in ``folder``."""
    return frozenset(p for p in folder.glob("*.png") if p.is_file())


def _find_new_png(
    folder: Path,
    before: frozenset[Path],
    preferred_name: str | None = None,
    excluded: set[str] | None = None,
) -> Path:
    """Return a PNG created after ``before``.

    If a ``preferred_name`` exists among the new files, it is used; otherwise
    exactly one new PNG (not in ``excluded``) is required.
    """
    after = _snapshot_pngs(folder)
    new = sorted(after - before)
    excluded = excluded or set()
    new = [p for p in new if p.name not in excluded]
    if preferred_name:
        preferred = folder / preferred_name
        if preferred in new:
            return preferred
    if not new:
        raise RuntimeError(f"no PNG was produced in {folder}")
    if len(new) > 1:
        raise RuntimeError(
            f"expected one new PNG in {folder}, found: {[p.name for p in new]}"
        )
    return new[0]


def _run_interactive(name: str, folder: Path, environment: Mapping[str, str]) -> None:
    """Run the interactive example through the comparison-export harness."""
    interactive = ROOT / "examples" / "interactive" / f"{name}_interactive.py"
    runner = ROOT / "tools" / "visual_parity" / "_example_runner.py"
    result = subprocess.run(
        [sys.executable, str(runner), str(interactive)],
        cwd=folder,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        timeout=900,
        env=dict(environment),
    )
    if result.returncode:
        raise RuntimeError(result.stderr)


def run_example(name: str, transports: tuple[str, ...]) -> Path:
    """Render and verify one example through the requested transports."""
    _validate_name(name)
    original = ROOT / "examples" / f"{name}.py"
    if not original.is_file() or not (ROOT / "examples" / "interactive" / f"{name}_interactive.py").is_file():
        raise ValueError(f"unknown example: {name}")
    folder = OUTPUT / name
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    DATA_CACHE.mkdir(parents=True, exist_ok=True)
    environment = {**os.environ, "STARPLOT_DATA_PATH": str(DATA_CACHE)}
    # The runner subprocess must be able to import starplot from src/.
    pythonpath_parts = [str(ROOT / "src")]
    existing_pythonpath = os.environ.get("PYTHONPATH")
    if existing_pythonpath:
        pythonpath_parts.append(existing_pythonpath)
    environment["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
    # Tell the runner which transports to export and verify.
    environment["STARPLOT_COMPARISON_TRANSPORTS"] = ",".join(transports)
    server = _ProviderServer(folder)
    server.start()
    if "provider" in transports:
        environment["STARPLOT_COMPARISON_PROVIDER_MANIFEST_URL"] = f"{server.origin}/provider/manifest.json"
    try:
        print(f"[1/4] Running original: {original.name}")
        pngs_before = _snapshot_pngs(folder)
        result = subprocess.run([sys.executable, str(original)], cwd=folder, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=900, env=environment)
        if result.returncode:
            raise RuntimeError(result.stderr)
        original_png = _find_new_png(folder, pngs_before, preferred_name=f"{name}.png")
        original_png.replace(folder / "orig.png")
        print(f"[2/4] Compiling one Scene and exporting: {name}_interactive.py")
        pngs_before = _snapshot_pngs(folder)
        _run_interactive(name, folder, environment)
        interactive_png = _find_new_png(
            folder,
            pngs_before,
            preferred_name=f"{name}.png",
            excluded={"plotly.png"},
        )
        interactive_png.replace(folder / "interactive.png")
        exports = json.loads((folder / "comparison-exports.json").read_text(encoding="utf-8"))
        exports["interactive_png"] = "interactive.png"
        exports["provenance"] = _visual_evidence_provenance()
        (folder / "comparison-exports.json").write_text(json.dumps(exports, indent=2) + "\n", encoding="utf-8")
        print("[3/4] Verifying canonical transport bytes and decoded columns")
        report = _verify_transports(folder, server, exports, transports)
        print("[4/4] Rendering browser screenshots")
        if exports.get("external_bundle"):
            manifest_bytes = (folder / exports["external_bundle"] / "manifest.json").read_bytes()
        elif exports.get("inline_html"):
            manifest_bytes, _ = _read_inline_export(folder / exports["inline_html"])
        else:
            raise RuntimeError("no exported manifest available for browser sizing")
        manifest = parse_scene_manifest(manifest_bytes)
        html_files = {
            transport: exports[f"{transport}_html"]
            for transport in transports
            if f"{transport}_html" in exports
        }
        browser_report = _browser_screenshots(folder, server, int(manifest.viewport.get("reference_width", 1200)), int(manifest.viewport.get("reference_height", 900)), transports, html_files)
        expected_layer_ids = [layer.id for layer in manifest.layers]
        for transport, browser_metrics in browser_report.items():
            layer_ids = browser_metrics["layer_ids"]
            # Dense finite-palette ScatterGL layers may be represented by a
            # bounded consecutive run of GPU traces.  Collapse such runs to
            # verify the Scene layer ordering while still detecting an
            # interleaved or missing layer.
            collapsed_ids = [
                layer_id for index, layer_id in enumerate(layer_ids)
                if index == 0 or layer_id != layer_ids[index - 1]
            ]
            if collapsed_ids != expected_layer_ids:
                raise AssertionError(f"{transport}: browser traces do not preserve the canonical layer order")
        (folder / "browser-render.json").write_text(json.dumps(browser_report, indent=2) + "\n", encoding="utf-8")
        _write_diff(folder, name, transports, exports)
        verified = ", ".join(transports)
        provider_note = (
            "- Provider HTTP manifest/layer bytes and headers: PASS\n"
            if "provider" in transports
            else ""
        )
        (folder / "transport.md").write_text(
            "# Transport verification\n\n"
            f"- Scene hash: `{report['scene_hash']}`\n"
            f"- Manifest SHA-256: `{report['manifest_sha256']}`\n"
            f"- Selected transports ({verified}) share canonical raw Arrow bytes and decoded columns: PASS\n"
            f"{provider_note}"
            "\n"
            "| layer | rows | Arrow bytes | SHA-256 |\n|---|---:|---:|---|\n"
            + "\n".join(f"| {item['id']} | {item['rows']} | {item['bytes']} | `{item['sha256']}` |" for item in report["layers"])
            + "\n", encoding="utf-8",
        )
    finally:
        server.close()
    print(f"Done: {folder}")
    return folder


def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("example")
    parser.add_argument("--transports", default=",".join(ALL_TRANSPORTS))
    args = parser.parse_args()
    transports = tuple(value.strip() for value in args.transports.split(",") if value.strip())
    if not transports or any(value not in ALL_TRANSPORTS for value in transports):
        parser.error(f"--transports must be a non-empty subset of {','.join(ALL_TRANSPORTS)}")
    run_example(args.example, transports)


if __name__ == "__main__":
    main()
