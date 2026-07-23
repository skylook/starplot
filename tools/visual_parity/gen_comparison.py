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
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Mapping
from urllib.request import Request, urlopen

if __package__:
    from . import crops
else:
    import crops
import numpy as np

from starplot.interactive.arrow_transport import decode_layer_stream
from starplot.interactive.scene_manifest import parse_scene_manifest
from starplot.interactive.scene_provider import SceneProvider


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "comparison_outputs"
DATA_CACHE = OUTPUT / ".data-cache"
ALL_TRANSPORTS = ("inline", "external", "provider")


class _InlinePayloadParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._current_id: str | None = None
        self.scripts: dict[str, str] = {}

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            attributes = dict(attrs)
            self._current_id = attributes.get("id")

    def handle_data(self, data):
        if self._current_id is not None:
            self.scripts[self._current_id] = self.scripts.get(self._current_id, "") + data

    def handle_endtag(self, tag):
        if tag == "script":
            self._current_id = None


def _read_inline_export(path: Path) -> tuple[bytes, Mapping[str, bytes]]:
    parser = _InlinePayloadParser()
    parser.feed(path.read_text(encoding="utf-8"))
    manifest_text = parser.scripts["starplot-manifest"].replace("<\\/", "</")
    manifest_bytes = manifest_text.encode("utf-8")
    manifest = parse_scene_manifest(manifest_bytes)
    layers = {
        layer.id: base64.b64decode(parser.scripts[f"starplot-layer-{index}"].encode("ascii"))
        for index, layer in enumerate(manifest.layers)
    }
    return manifest_bytes, layers


def _read_external_export(folder: Path) -> tuple[bytes, Mapping[str, bytes]]:
    manifest_bytes = (folder / "external.scene" / "manifest.json").read_bytes()
    manifest = parse_scene_manifest(manifest_bytes)
    return manifest_bytes, {
        layer.id: (folder / "external.scene" / layer.data_source.uri).read_bytes()
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


class _ProviderHandler(SimpleHTTPRequestHandler):
    provider: SceneProvider | None = None
    manifest = None

    def __init__(self, *args, directory: str, **kwargs):
        super().__init__(*args, directory=directory, **kwargs)

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
        if self.path.split("?", 1)[0] == "/provider/manifest.json":
            assert self.provider is not None
            self._send_response(self.provider.manifest(self.headers.get("If-None-Match")))
            return
        if self.path.startswith("/provider/"):
            assert self.provider is not None and self.manifest is not None
            name = self.path.split("?", 1)[0].removeprefix("/provider/")
            layer = next(
                (item for item in self.manifest.layers if item.data_source.uri == name), None
            )
            if layer is None:
                self.send_error(404)
                return
            self._send_response(self.provider.layer(layer.id, if_none_match=self.headers.get("If-None-Match")))
            return
        super().do_GET()


class _ProviderServer:
    def __init__(self, folder: Path):
        self.folder = folder

        def handler(*args, **kwargs):
            return _ProviderHandler(*args, directory=str(folder), **kwargs)

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
        _ProviderHandler.provider = SceneProvider(manifest, manifest_bytes, layers)
        _ProviderHandler.manifest = manifest

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        _ProviderHandler.provider = None
        _ProviderHandler.manifest = None


def _request_bytes(url: str) -> tuple[bytes, Mapping[str, str]]:
    with urlopen(Request(url), timeout=60) as response:
        return response.read(), dict(response.headers.items())


def _verify_transports(folder: Path, server: _ProviderServer) -> dict:
    inline_manifest, inline_layers = _read_inline_export(folder / "inline.html")
    external_manifest, external_layers = _read_external_export(folder)
    if inline_manifest != external_manifest:
        raise AssertionError("inline and external canonical manifest bytes differ")
    if inline_layers != external_layers:
        raise AssertionError("inline and external Arrow bytes differ")
    server.configure(external_manifest, external_layers)
    provider_manifest, manifest_headers = _request_bytes(f"{server.origin}/provider/manifest.json")
    if provider_manifest != external_manifest:
        raise AssertionError("provider HTTP manifest bytes differ")
    if manifest_headers.get("Cache-Control") != "no-cache":
        raise AssertionError("provider manifest cache policy differs")
    manifest = parse_scene_manifest(external_manifest)
    provider_layers: dict[str, bytes] = {}
    for layer in manifest.layers:
        url = f"{server.origin}/provider/{layer.data_source.uri}"
        payload, headers = _request_bytes(url)
        if headers.get("Content-Type") != "application/vnd.apache.arrow.stream":
            raise AssertionError(f"provider/{layer.id}: Arrow media type differs")
        if payload != external_layers[layer.id]:
            raise AssertionError(f"provider/{layer.id}: HTTP Arrow bytes differ")
        provider_layers[layer.id] = payload
    _assert_decoded_columns_equal(external_manifest, external_layers, inline_layers, "inline")
    _assert_decoded_columns_equal(external_manifest, external_layers, provider_layers, "provider")
    return {
        "scene_hash": manifest.content_hash,
        "manifest_sha256": hashlib.sha256(external_manifest).hexdigest(),
        "layers": [
            {
                "id": layer.id,
                "rows": layer.row_count,
                "bytes": layer.byte_length,
                "sha256": hashlib.sha256(external_layers[layer.id]).hexdigest(),
            }
            for layer in manifest.layers
        ],
    }


def _launch_browser(playwright):
    try:
        return playwright.chromium.launch(headless=True)
    except Exception:
        for candidate in (
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
        ):
            if candidate.is_file():
                return playwright.chromium.launch(executable_path=str(candidate), headless=True)
        raise


def _browser_screenshots(folder: Path, server: _ProviderServer, width: int, height: int, transports: tuple[str, ...]) -> dict[str, dict]:
    from playwright.sync_api import sync_playwright

    reports: dict[str, dict] = {}
    with sync_playwright() as playwright:
        browser = _launch_browser(playwright)
        try:
            for name in transports:
                page_errors: list[str] = []
                page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
                page.on("pageerror", lambda error: page_errors.append(str(error)))
                print(f"  browser {name}: loading", flush=True)
                page.goto(f"{server.origin}/{name}.html", wait_until="load", timeout=300_000)
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
                page.close()
                print(f"  browser {name}: captured", flush=True)
        finally:
            browser.close()
    return reports


def _write_diff(folder: Path, name: str, transports: tuple[str, ...]) -> None:
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

    original = Image.open(folder / "orig.png")
    interactive = Image.open(folder / "interactive.png")
    browser_images = {transport: Image.open(folder / f"{transport}.png") for transport in transports}
    interactive_for_orig = interactive.resize(original.size, Image.Resampling.LANCZOS)
    rows = [("orig vs interactive", compare(original, interactive_for_orig))]
    for transport_name, image in browser_images.items():
        resized = interactive.resize(image.size, Image.Resampling.LANCZOS)
        rows.append((f"interactive vs {transport_name}", compare(resized, image)))
    for index, left_name in enumerate(transports):
        for right_name in transports[index + 1:]:
            rows.append((f"{left_name} vs {right_name}", compare(browser_images[left_name], browser_images[right_name])))
    (folder / "diff.md").write_text(
        "\n".join([f"# {name} transport diff", "", "| pair | diagnostic |", "|---|---|"] + [f"| {label} | {result} |" for label, result in rows]) + "\n",
        encoding="utf-8",
    )

    # Local semantic crop comparisons for every pair, resizing to a common size.
    crops_dir = folder / "crops"
    crops_dir.mkdir(exist_ok=True)
    pairs = [("orig vs interactive", folder / "orig.png", folder / "interactive.png", "left")]
    for transport_name in transports:
        pairs.append((f"interactive vs {transport_name}", folder / "interactive.png", folder / f"{transport_name}.png", "right"))
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


def _run_interactive(name: str, folder: Path, environment: Mapping[str, str]) -> None:
    interactive = ROOT / "examples" / "interactive" / f"{name}_interactive.py"
    wrapper = f'''
import hashlib, json, os, pathlib, runpy
import starplot.interactive.plots as plots
from starplot.interactive.web_export import DataMode, LibraryMode, export_scene_html

def export_once(self, filename, width=None, height=None, transparent=False, **_kwargs):
    scene = self._compile_scene(width=width, height=height, transparent=transparent)
    base = pathlib.Path.cwd()
    inline = export_scene_html(scene, base / "inline.html", data_mode=DataMode.INLINE, library_mode=LibraryMode.INLINE)
    external = export_scene_html(scene, base / "external.html", data_mode=DataMode.EXTERNAL, library_mode=LibraryMode.DIRECTORY)
    remote = export_scene_html(scene, base / "provider.html", data_mode=DataMode.REMOTE, library_mode=LibraryMode.INLINE, data_url=os.environ["STARPLOT_COMPARISON_PROVIDER_MANIFEST_URL"])
    assert inline.scene_hash == external.scene_hash == remote.scene_hash
    assert inline.manifest_bytes == external.manifest_bytes == remote.manifest_bytes
    assert inline.layer_bytes == external.layer_bytes == remote.layer_bytes
    (base / "scene-export.json").write_text(json.dumps({{
        "scene_hash": inline.scene_hash,
        "manifest_sha256": hashlib.sha256(inline.manifest_bytes).hexdigest(),
        "layers": [{{"id": layer_id, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}} for layer_id, data in inline.layer_bytes.items()],
    }}, indent=2) + "\\n", encoding="utf-8")
    return external

plots._InteractiveMixin.export_html = export_once
runpy.run_path({str(interactive)!r}, run_name="__main__")
'''
    result = subprocess.run(
        [sys.executable, "-c", wrapper], cwd=folder, stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE, text=True, timeout=900, env=dict(environment),
    )
    if result.returncode:
        raise RuntimeError(result.stderr)


def run_example(name: str, transports: tuple[str, ...]) -> Path:
    original = ROOT / "examples" / f"{name}.py"
    if not original.is_file() or not (ROOT / "examples" / "interactive" / f"{name}_interactive.py").is_file():
        raise ValueError(f"unknown example: {name}")
    folder = OUTPUT / name
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    DATA_CACHE.mkdir(parents=True, exist_ok=True)
    environment = {**os.environ, "STARPLOT_DATA_PATH": str(DATA_CACHE)}
    server = _ProviderServer(folder)
    server.start()
    environment["STARPLOT_COMPARISON_PROVIDER_MANIFEST_URL"] = f"{server.origin}/provider/manifest.json"
    try:
        print(f"[1/4] Running original: {original.name}")
        result = subprocess.run([sys.executable, str(original)], cwd=folder, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=900, env=environment)
        if result.returncode:
            raise RuntimeError(result.stderr)
        (folder / f"{name}.png").replace(folder / "orig.png")
        print(f"[2/4] Compiling one Scene and exporting: {name}_interactive.py")
        _run_interactive(name, folder, environment)
        (folder / f"{name}.png").replace(folder / "interactive.png")
        print("[3/4] Verifying canonical transport bytes and decoded columns")
        report = _verify_transports(folder, server)
        print("[4/4] Rendering browser screenshots")
        manifest = parse_scene_manifest((folder / "external.scene" / "manifest.json").read_bytes())
        browser_report = _browser_screenshots(folder, server, int(manifest.viewport.get("reference_width", 1200)), int(manifest.viewport.get("reference_height", 900)), transports)
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
        _write_diff(folder, name, transports)
        (folder / "transport.md").write_text(
            "# Transport verification\n\n"
            f"- Scene hash: `{report['scene_hash']}`\n"
            f"- Manifest SHA-256: `{report['manifest_sha256']}`\n"
            "- Inline = external = provider raw Arrow bytes: PASS\n"
            "- Inline = external = provider decoded columns/dtypes: PASS\n"
            "- Provider HTTP manifest/layer bytes and headers: PASS\n\n"
            "| layer | rows | Arrow bytes | SHA-256 |\n|---|---:|---:|---|\n"
            + "\n".join(f"| {item['id']} | {item['rows']} | {item['bytes']} | `{item['sha256']}` |" for item in report["layers"])
            + "\n", encoding="utf-8",
        )
    finally:
        server.close()
    print(f"Done: {folder}")
    return folder


def main() -> None:
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
