"""Reproducible pre-Arrow benchmark for the interactive Scene pipeline.

The synthetic command is built before timing starts, so catalog access and
Matplotlib drawing cannot contaminate the renderer measurements. Each Python
repeat runs in a fresh bounded subprocess so its peak RSS is isolated from
other repeats and from browser measurement.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
try:
    import resource
except ImportError:
    resource = None
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager

import numpy as np


REQUIRED_RESULT_KEYS = {
    "browser",
    "environment",
    "payload_bytes",
    "peak_rss_mb",
    "point_count",
    "scene_compile",
}
REQUIRED_ARTIFACT_KEYS = REQUIRED_RESULT_KEYS | {
    "legacy_renderer_preparation",
    "legacy_renderer_total",
    "plotly_construction",
}
REQUIRED_ENVIRONMENT_KEYS = {
    "browser",
    "captured_at_utc",
    "cpu",
    "cpu_count",
    "host_fingerprint",
    "machine",
    "numpy",
    "os",
    "playwright",
    "plotly",
    "pyarrow",
    "python",
    "shapely",
    "starplot",
}

# These are release gates, not tuning targets.  A missing measurement fails the
# gate so a benchmark record cannot turn an unavailable dependency into a pass.
PERFORMANCE_GATES = {
    "scene_compile_ratio_max": 0.50,
    "peak_rss_ratio_max": 0.60,
    "arrow_payload_bytes_max": 30 * 1024 * 1024,
    "external_html_bytes_max": 1 * 1024 * 1024,
    # Transport overhead gate: Arrow load/validation/decoding must not add more
    # than 10% over the same-Scene direct Plotly fixture on the same host.
    "browser_complete_render_ratio_max": 1.10,
    # Product-facing absolute budget, kept separate from transport overhead.
    "browser_complete_render_p95_ms_max": 5000,
    "ordinary_chart_regression_ratio_max": 1.10,
    "viewport_warm_median_ms_max": 500,
    "viewport_warm_p95_ms_max": 1000,
}

_SEED = 20260716
_DEFAULT_REPEAT_TIMEOUT_SECONDS = 300.0
_BROWSER_TIMEOUT_MS = 300_000
_SCENE_COMPILE_SEMANTICS = "Native SceneCompiler.compile timing."
_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_PLOTLY_COMPLETION_INIT_SCRIPT = r"""
(() => {
  const state = window.__starplotBenchmark = {
    calls: 0,
    complete: false,
    completedAt: null,
    method: null,
    startedAt: null
  };

  const afterFinalPaint = (callback) => {
    requestAnimationFrame(() => requestAnimationFrame(callback));
  };

  const wrapPlotly = (plotly) => {
    if (!plotly || plotly.__starplotBenchmarkWrapped) return;
    Object.defineProperty(plotly, "__starplotBenchmarkWrapped", {
      value: true,
      configurable: true
    });
    for (const method of ["newPlot", "react"]) {
      const original = plotly[method];
      if (typeof original !== "function") continue;
      plotly[method] = function(...args) {
        const generation = ++state.calls;
        state.complete = false;
        state.method = method;
        state.startedAt = performance.now();
        const result = original.apply(this, args);
        return Promise.resolve(result).then((value) => new Promise((resolve) => {
          afterFinalPaint(() => {
            if (generation === state.calls) {
              state.completedAt = performance.now();
              state.complete = true;
            }
            resolve(value);
          });
        }));
      };
    }
  };

  let plotlyValue = window.Plotly;
  if (plotlyValue) wrapPlotly(plotlyValue);
  const descriptor = Object.getOwnPropertyDescriptor(window, "Plotly");
  if (!descriptor || descriptor.configurable) {
    Object.defineProperty(window, "Plotly", {
      configurable: true,
      enumerable: true,
      get: () => plotlyValue,
      set: (value) => {
        plotlyValue = value;
        wrapPlotly(value);
      }
    });
  }
})();
"""


def validate_result(result: dict) -> None:
    missing = REQUIRED_RESULT_KEYS - result.keys()
    if missing:
        raise ValueError(f"Missing benchmark keys: {sorted(missing)}")


def validate_benchmark_artifact(result: dict) -> None:
    """Validate the stricter schema required for a persisted baseline JSON."""
    validate_result(result)
    missing = REQUIRED_ARTIFACT_KEYS - result.keys()
    if missing:
        raise ValueError(f"Missing benchmark artifact keys: {sorted(missing)}")
    environment = result.get("environment")
    if not isinstance(environment, dict):
        raise ValueError("Benchmark environment must be a mapping")
    missing_environment = REQUIRED_ENVIRONMENT_KEYS - environment.keys()
    if missing_environment:
        raise ValueError(
            f"Missing benchmark environment keys: {sorted(missing_environment)}"
        )


def percentile(values: list[float], q: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=np.float64), q))


def summarize(values: list[float]) -> dict[str, float]:
    return {
        "median_seconds": percentile(values, 50),
        "p95_seconds": percentile(values, 95),
    }


def _metric(mapping: dict, path: str) -> float | None:
    value: object = mapping
    for key in path.split("."):
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def compare_results(before: dict, after: dict) -> list[str]:
    """Return one auditable failure for each missed final-performance gate."""
    failures: list[str] = []
    before_environment = before.get("environment", {})
    after_environment = after.get("environment", {})
    if before_environment.get("host_fingerprint") != after_environment.get("host_fingerprint"):
        failures.append(
            "environment.host_fingerprint differs; regenerate baseline and final "
            "measurements together on this machine"
        )

    def ratio_gate(label: str, before_path: str, after_path: str, maximum: float) -> None:
        baseline = _metric(before, before_path)
        current = _metric(after, after_path)
        if baseline is None:
            failures.append(f"{label} baseline is missing ({before_path})")
        elif current is None:
            failures.append(f"{label} result is missing ({after_path})")
        elif baseline == 0:
            if current > 0:
                failures.append(
                    f"{label} baseline is zero, current {current:.6g} exceeds {maximum:.6g}"
                )
        elif current / baseline > maximum:
            failures.append(
                f"{label} ratio {current / baseline:.3f} exceeds {maximum:.3f} "
                f"({current:.6g} / {baseline:.6g})"
            )

    def maximum_gate(label: str, path: str, maximum: float) -> None:
        current = _metric(after, path)
        if current is None:
            failures.append(f"{label} is missing ({path})")
        elif current > maximum:
            failures.append(f"{label} {current:.6g} exceeds {maximum:.6g}")

    ratio_gate("scene_compile", "scene_compile.median_seconds", "scene_compile.median_seconds",
               PERFORMANCE_GATES["scene_compile_ratio_max"])
    ratio_gate("peak_rss", "peak_rss_mb", "peak_rss_mb", PERFORMANCE_GATES["peak_rss_ratio_max"])
    maximum_gate("arrow_payload_bytes", "arrow_payload_bytes", PERFORMANCE_GATES["arrow_payload_bytes_max"])
    maximum_gate("external_html_bytes", "external_html_bytes", PERFORMANCE_GATES["external_html_bytes_max"])
    paired_browser = after.get("browser", {}).get("legacy_same_scene")
    if isinstance(paired_browser, dict):
        legacy = _metric(paired_browser, "complete_render_median_ms")
        current = _metric(after, "browser.complete_render_median_ms")
        if paired_browser.get("scene_hash") != after.get("browser", {}).get("scene_hash"):
            failures.append("browser_complete_render paired legacy fixture scene_hash differs")
        elif legacy is None:
            failures.append("browser_complete_render paired legacy result is missing")
        elif current is None:
            failures.append("browser_complete_render result is missing (browser.complete_render_median_ms)")
        elif legacy == 0:
            if current > 0:
                failures.append(
                    "browser_complete_render baseline is zero, current "
                    f"{current:.6g} exceeds "
                    f"{PERFORMANCE_GATES['browser_complete_render_ratio_max']:.6g}"
                )
        elif current / legacy > PERFORMANCE_GATES["browser_complete_render_ratio_max"]:
            failures.append(
                "browser_complete_render ratio "
                f"{current / legacy:.3f} exceeds "
                f"{PERFORMANCE_GATES['browser_complete_render_ratio_max']:.3f} "
                f"({current:.6g} / {legacy:.6g})"
            )
    else:
        ratio_gate("browser_complete_render", "browser.complete_render_median_ms",
                   "browser.complete_render_median_ms",
                   PERFORMANCE_GATES["browser_complete_render_ratio_max"])
    maximum_gate(
        "browser_complete_render_p95",
        "browser.complete_render_p95_ms",
        PERFORMANCE_GATES["browser_complete_render_p95_ms_max"],
    )
    ratio_gate("ordinary_chart", "ordinary_chart.median_seconds", "ordinary_chart.median_seconds",
               PERFORMANCE_GATES["ordinary_chart_regression_ratio_max"])
    maximum_gate("viewport_warm_median", "viewport_warm.median_ms",
                 PERFORMANCE_GATES["viewport_warm_median_ms_max"])
    maximum_gate("viewport_warm_p95", "viewport_warm.p95_ms",
                 PERFORMANCE_GATES["viewport_warm_p95_ms_max"])
    return failures


def _read_only_contiguous(values, dtype=None) -> np.ndarray:
    result = np.ascontiguousarray(values, dtype=dtype)
    result.setflags(write=False)
    return result


def _mollweide_clip_points(vertex_count: int = 360) -> tuple[tuple[float, float], ...]:
    """Return a stable ellipse approximating the map's Mollweide boundary."""
    angles = np.linspace(0.0, 2.0 * math.pi, vertex_count, endpoint=False)
    return tuple(
        (float(math.pi * np.cos(angle)), float(0.5 * math.pi * np.sin(angle)))
        for angle in angles
    )


def _palette() -> list[str]:
    """Build the fixed 50-color palette (never a per-point Python list)."""
    return [
        f"#{(37 * index + 47) % 256:02x}{(83 * index + 89) % 256:02x}"
        f"{(149 * index + 131) % 256:02x}"
        for index in range(50)
    ]


def _build_scatter_command(point_count: int):
    from starplot.interactive.commands import DrawingCommand

    rng = np.random.default_rng(_SEED)
    indices = np.arange(point_count, dtype=np.intp) % 50
    palette = np.asarray(_palette(), dtype="<U7")
    alpha_cycle = np.linspace(0.04, 1.0, 50, dtype=np.float64)

    columns = {
        "x": _read_only_contiguous(
            rng.uniform(-math.pi, math.pi, point_count), np.float64
        ),
        "y": _read_only_contiguous(
            rng.uniform(-0.5 * math.pi, 0.5 * math.pi, point_count), np.float64
        ),
        "sizes": _read_only_contiguous(
            rng.uniform(0.02, 1.5, point_count), np.float64
        ),
        "colors": _read_only_contiguous(palette[indices], "<U7"),
        "alphas": _read_only_contiguous(alpha_cycle[indices], np.float64),
    }
    return DrawingCommand(
        kind="scatter",
        data=columns,
        style={
            "symbol": "circle",
            "edge_color": "none",
            "edge_width": 0,
        },
        metadata=[],
        zorder=0,
        gid="stars",
        clip_id="plot",
    )


def _renderer_inputs(point_count: int) -> tuple[object, dict, dict]:
    from starplot.interactive.commands import ClipGeometry

    command = _build_scatter_command(point_count)
    projection_info = {
        "x_min": -math.pi,
        "x_max": math.pi,
        "y_min": -0.5 * math.pi,
        "y_max": 0.5 * math.pi,
        # Match the geometry contract recorded from a 2:1 Matplotlib map:
        # ten vertical pixels and twenty horizontal pixels surround a
        # 960-by-480 scale-anchored axes inside the 1000-by-500 fixture.
        "axes_bbox": (0.02, 0.02, 0.96, 0.96),
        "plot_kind": "map",
        "clip_geometries": {
            "plot": ClipGeometry(kind="polygon", points=_mollweide_clip_points()),
        },
    }
    style_info = {
        "background_color": "#000000",
        "figure_background_color": "#000000",
        "show_legend": False,
        "resolution": 4096,
        "dpi": 100.0,
        "source_axes_width": 4096.0,
    }
    return command, projection_info, style_info


def _peak_rss_mb() -> float:
    if resource is None:
        return 0.0
    peak = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    divisor = 1024.0 * 1024.0 if sys.platform == "darwin" else 1024.0
    return peak / divisor


def _run_python_worker(point_count: int) -> dict:
    """Run one isolated Scene compilation and Plotly construction sample."""
    from starplot.interactive.arrow_transport import encode_layer_stream
    from starplot.interactive.plotly_adapter import PlotlySceneAdapter
    from starplot.interactive.scene_compiler import SceneCompiler
    from starplot.interactive.scene import ViewportRequest
    from starplot.interactive.scene_manifest import parse_scene_manifest
    from starplot.interactive.scene_provider import SceneProvider
    from starplot.interactive.web_export import LibraryMode, export_scene_html

    command, projection_info, style_info = _renderer_inputs(point_count)

    preparation_started = time.perf_counter()
    scene = SceneCompiler().compile(
        [command],
        projection_info,
        style_info,
        1000,
        500,
        False,
    )
    preparation_seconds = time.perf_counter() - preparation_started

    construction_started = time.perf_counter()
    figure = PlotlySceneAdapter().render(scene)
    plotly_seconds = time.perf_counter() - construction_started
    peak_rss_mb = _peak_rss_mb()
    arrow_payload_bytes = sum(len(encode_layer_stream(layer)) for layer in scene.layers)
    with tempfile.TemporaryDirectory(prefix="starplot-scene-benchmark-") as directory:
        output = Path(directory) / "scene.html"
        exported = export_scene_html(
            scene, output, library_mode=LibraryMode.DIRECTORY
        )
        external_html_bytes = output.stat().st_size
        provider = SceneProvider(
            parse_scene_manifest(exported.manifest_bytes),
            exported.manifest_bytes,
            exported.layer_bytes,
        )
        request = ViewportRequest(
            x_min=-math.pi / 2,
            x_max=math.pi / 2,
            y_min=-math.pi / 4,
            y_max=math.pi / 4,
            pixel_width=1000,
            pixel_height=500,
            lod=1,
        )
        provider.layer(scene.layers[0].id, request)  # populate the dynamic cache
        viewport_warm_ms = []
        for _ in range(5):
            started = time.perf_counter()
            provider.layer(scene.layers[0].id, request).body_bytes()
            viewport_warm_ms.append((time.perf_counter() - started) * 1000.0)
    payload_bytes = len(figure.to_json().encode("utf-8"))
    return {
        # Task 13 will migrate the persisted artifact schema. Keep these old
        # aggregate key names until then so pre-Arrow result readers survive.
        "legacy_renderer_preparation_seconds": preparation_seconds,
        "legacy_renderer_total_seconds": preparation_seconds + plotly_seconds,
        "payload_bytes": payload_bytes,
        "arrow_payload_bytes": arrow_payload_bytes,
        "external_html_bytes": external_html_bytes,
        "peak_rss_mb": peak_rss_mb,
        "plotly_construction_seconds": plotly_seconds,
        "viewport_warm_ms": viewport_warm_ms,
    }


def _run_python_repeat(point_count: int, timeout_seconds: float) -> dict:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--python-worker",
        "--points",
        str(point_count),
    ]
    env = os.environ.copy()
    src_path = str(_REPOSITORY_ROOT / "src")
    existing_pythonpath = env.get("PYTHONPATH", "")
    if existing_pythonpath:
        env["PYTHONPATH"] = f"{src_path}{os.pathsep}{existing_pythonpath}"
    else:
        env["PYTHONPATH"] = src_path
    try:
        completed = subprocess.run(
            command,
            cwd=_REPOSITORY_ROOT,
            capture_output=True,
            check=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            f"Python benchmark repeat timed out after {timeout_seconds} seconds"
        ) from error
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or "no worker output").strip()
        raise RuntimeError(f"Python benchmark repeat failed: {detail}") from error
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"Python benchmark worker returned invalid JSON: {completed.stdout!r}"
        ) from error


def _run_browser_fixture_worker(point_count: int, output_directory: Path) -> dict:
    """Export the paired browser fixtures in a disposable Python process."""
    from starplot.interactive.plotly_adapter import PlotlySceneAdapter
    from starplot.interactive.scene_compiler import SceneCompiler
    from starplot.interactive.web_export import (
        DataMode,
        LibraryMode,
        export_scene_html,
    )

    command, projection_info, style_info = _renderer_inputs(point_count)
    scene = SceneCompiler().compile(
        [command], projection_info, style_info, 1000, 500, False
    )
    exported = export_scene_html(
        scene,
        output_directory / "scene.html",
        data_mode=DataMode.EXTERNAL,
        library_mode=LibraryMode.DIRECTORY,
    )
    # This legacy page uses the exact same Scene and local Plotly library as
    # the Arrow page. It is only a like-for-like browser baseline, never a
    # public delivery mode.
    PlotlySceneAdapter().render(scene).write_html(
        output_directory / "legacy.html", include_plotlyjs="directory"
    )
    return {
        "arrow_payload_bytes": sum(
            len(value) for value in exported.layer_bytes.values()
        ),
        "scene_hash": exported.scene_hash,
    }


def _export_browser_fixture(
    point_count: int,
    output_directory: Path,
    timeout_seconds: float = _DEFAULT_REPEAT_TIMEOUT_SECONDS,
) -> dict:
    """Run fixture compilation/export to completion outside this process."""
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--browser-fixture-worker",
        "--browser-fixture-output",
        str(output_directory),
        "--points",
        str(point_count),
    ]
    env = os.environ.copy()
    src_path = str(_REPOSITORY_ROOT / "src")
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{src_path}{os.pathsep}{existing_pythonpath}"
        if existing_pythonpath
        else src_path
    )
    try:
        completed = subprocess.run(
            command,
            cwd=_REPOSITORY_ROOT,
            capture_output=True,
            check=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            "Browser fixture worker timed out after "
            f"{timeout_seconds} seconds"
        ) from error
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or "no worker output").strip()
        raise RuntimeError(f"Browser fixture worker failed: {detail}") from error
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            "Browser fixture worker returned invalid JSON: "
            f"{completed.stdout!r}"
        ) from error


def _package_version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _host_fingerprint() -> str:
    """Hash stable host traits without recording a private hostname."""
    traits = {
        "cpu": platform.processor() or platform.machine(),
        "cpu_count": os.cpu_count(),
        "machine": platform.machine(),
        "node": platform.node(),
        "os": platform.platform(),
    }
    encoded = json.dumps(traits, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:16]


def _environment(browser_result: dict) -> dict[str, object]:
    browser = " ".join(
        value
        for value in (
            str(browser_result.get("engine", "unavailable")),
            str(browser_result.get("engine_version", "unknown")),
        )
        if value
    )
    return {
        "browser": browser,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "cpu": platform.processor() or platform.machine(),
        "cpu_count": os.cpu_count(),
        "host_fingerprint": _host_fingerprint(),
        "machine": platform.machine(),
        "numpy": np.__version__,
        "os": platform.platform(),
        "playwright": _package_version("playwright"),
        "plotly": _package_version("plotly"),
        "pyarrow": _package_version("pyarrow"),
        "python": platform.python_version(),
        "shapely": _package_version("shapely"),
        "starplot": _package_version("starplot"),
    }


def _system_chrome_executable() -> Path | None:
    candidates = (
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
    )
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def _launch_browser(playwright):
    """Launch bundled Chromium, falling back to an already-installed browser."""
    try:
        return playwright.chromium.launch(headless=True)
    except Exception:
        executable = _system_chrome_executable()
        if executable is None:
            raise
        return playwright.chromium.launch(
            executable_path=str(executable),
            headless=True,
        )


def _measure_browser_page(page, uri: str, timeout_ms: int) -> float:
    """Measure navigation through Starplot's complete render and final paint."""
    page.add_init_script(_PLOTLY_COMPLETION_INIT_SCRIPT)
    started = time.perf_counter()
    page.goto(uri, wait_until="load", timeout=timeout_ms)
    page.wait_for_function(
        """async () => {
          if (window.__starplotRenderPromise) {
            await window.__starplotRenderPromise;
            await new Promise((resolve) => requestAnimationFrame(
              () => requestAnimationFrame(resolve)
            ));
            return true;
          }
          return window.__starplotBenchmark.complete === true;
        }""",
        timeout=timeout_ms,
    )
    return (time.perf_counter() - started) * 1000.0


@contextmanager
def _external_browser_fixture(
    point_count: int,
    timeout_seconds: float = _DEFAULT_REPEAT_TIMEOUT_SECONDS,
):
    """Serve one real external Arrow export outside measured browser repeats."""
    from starplot.cli import create_server

    with tempfile.TemporaryDirectory(prefix="starplot-arrow-browser-") as directory:
        root = Path(directory)
        metadata = _export_browser_fixture(point_count, root, timeout_seconds)
        server = create_server(root, host="127.0.0.1", port=0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        host, port = server.server_address[:2]
        try:
            yield {
                "arrow_payload_bytes": metadata["arrow_payload_bytes"],
                "scene_hash": metadata["scene_hash"],
                "source_kind": "external-arrow-http",
                "source_url": f"http://{host}:{port}/scene.html",
                "legacy_source_kind": "direct-plotly-same-scene-http",
                "legacy_source_url": f"http://{host}:{port}/legacy.html",
            }
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)


def run_browser_benchmark(
    point_count: int,
    repeats: int,
    fixture_timeout_seconds: float = _DEFAULT_REPEAT_TIMEOUT_SECONDS,
) -> dict:
    """Measure a real external Arrow bundle over the supported HTTP server."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {
            "complete_render_median_ms": None,
            "complete_render_p95_ms": None,
            "source_kind": "external-arrow-http",
            "status": "playwright_not_installed",
        }

    measurements: list[float] = []
    legacy_measurements: list[float] = []
    try:
        with _external_browser_fixture(
            point_count, fixture_timeout_seconds
        ) as fixture, sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            try:
                browser_version = browser.version
                for iteration in range(repeats + 1):
                    label = "warm-up" if iteration == 0 else f"repeat {iteration}/{repeats}"
                    for name, url, values in (
                        ("external Arrow", fixture["source_url"], measurements),
                        ("legacy direct", fixture["legacy_source_url"], legacy_measurements),
                    ):
                        print(f"Browser {name} {label}: starting", flush=True)
                        page = browser.new_page(viewport={"width": 1000, "height": 500})
                        try:
                            elapsed_ms = _measure_browser_page(
                                page, url, _BROWSER_TIMEOUT_MS,
                            )
                        finally:
                            page.close()
                        print(
                            f"Browser {name} {label}: complete ({elapsed_ms:.3f} ms)",
                            flush=True,
                        )
                        if iteration:
                            values.append(elapsed_ms)
            finally:
                browser.close()
    except Exception as error:
        return {
            "complete_render_median_ms": None,
            "complete_render_p95_ms": None,
            "error": f"{type(error).__name__}: {error}",
            "source_kind": "external-arrow-http",
            "status": "measurement_failed",
        }

    return {
        "complete_render_median_ms": percentile(measurements, 50),
        "complete_render_p95_ms": percentile(measurements, 95),
        "completion_signal": (
            "Starplot render promise including scale correction plus two animation "
            "frames; Plotly promise fallback for legacy fixture"
        ),
        "engine": "chromium",
        "engine_version": browser_version,
        "legacy_same_scene": {
            "complete_render_median_ms": percentile(legacy_measurements, 50),
            "complete_render_p95_ms": percentile(legacy_measurements, 95),
            "scene_hash": fixture["scene_hash"],
            "source_kind": fixture["legacy_source_kind"],
        },
        **fixture,
        "status": "measured",
    }


def _summarize_worker_results(results: list[dict], key: str) -> dict[str, float]:
    return summarize([float(result[key]) for result in results])


def _run_python_samples(
    point_count: int,
    repeats: int,
    repeat_timeout_seconds: float,
    *,
    label: str,
) -> list[dict]:
    print(f"{label} warm-up: starting", flush=True)
    warmup = _run_python_repeat(point_count, repeat_timeout_seconds)
    print(
        f"{label} warm-up: complete "
        f"({warmup['legacy_renderer_total_seconds']:.3f} s, "
        f"{warmup['peak_rss_mb']:.3f} MiB peak RSS)",
        flush=True,
    )
    measured: list[dict] = []
    for iteration in range(1, repeats + 1):
        print(f"{label} repeat {iteration}/{repeats}: starting", flush=True)
        result = _run_python_repeat(point_count, repeat_timeout_seconds)
        measured.append(result)
        print(
            f"{label} repeat {iteration}/{repeats}: complete "
            f"({result['legacy_renderer_total_seconds']:.3f} s, "
            f"{result['peak_rss_mb']:.3f} MiB peak RSS)",
            flush=True,
        )
    return measured


def run_python_benchmark(
    point_count: int,
    repeats: int,
    repeat_timeout_seconds: float = _DEFAULT_REPEAT_TIMEOUT_SECONDS,
    ordinary_points: int | None = None,
) -> dict:
    if point_count <= 0:
        raise ValueError("point_count must be positive")
    if repeats <= 0:
        raise ValueError("repeats must be positive")
    if repeat_timeout_seconds <= 0:
        raise ValueError("repeat_timeout_seconds must be positive")

    measured = _run_python_samples(
        point_count, repeats, repeat_timeout_seconds, label="Python"
    )

    payload_sizes = {int(result["payload_bytes"]) for result in measured}
    if len(payload_sizes) != 1:
        raise RuntimeError(f"Python repeat payload sizes differ: {sorted(payload_sizes)}")
    for metric in ("arrow_payload_bytes", "external_html_bytes"):
        values = {int(result[metric]) for result in measured}
        if len(values) != 1:
            raise RuntimeError(f"Python repeat {metric} values differ: {sorted(values)}")

    preparation = _summarize_worker_results(
        measured, "legacy_renderer_preparation_seconds"
    )
    plotly_construction = _summarize_worker_results(
        measured, "plotly_construction_seconds"
    )
    legacy_total = _summarize_worker_results(
        measured, "legacy_renderer_total_seconds"
    )
    scene_compile = {**preparation, "semantics": _SCENE_COMPILE_SEMANTICS}

    browser = run_browser_benchmark(
        point_count,
        repeats,
        fixture_timeout_seconds=repeat_timeout_seconds,
    )
    result = {
        "arrow_payload_bytes": int(measured[0]["arrow_payload_bytes"]),
        "browser": browser,
        "environment": _environment(browser),
        "external_html_bytes": int(measured[0]["external_html_bytes"]),
        "legacy_renderer_preparation": preparation,
        "legacy_renderer_total": legacy_total,
        "payload_bytes": payload_sizes.pop(),
        "peak_rss_mb": max(float(item["peak_rss_mb"]) for item in measured),
        "plotly_construction": plotly_construction,
        "point_count": point_count,
        "scene_compile": scene_compile,
        "raw_repetitions": measured,
        "viewport_warm": {
            "median_ms": percentile(
                [value for item in measured for value in item["viewport_warm_ms"]], 50
            ),
            "p95_ms": percentile(
                [value for item in measured for value in item["viewport_warm_ms"]], 95
            ),
        },
    }
    if ordinary_points is not None:
        if ordinary_points <= 0:
            raise ValueError("ordinary_points must be positive")
        ordinary = _run_python_samples(
            ordinary_points, repeats, repeat_timeout_seconds, label="Ordinary chart"
        )
        result["ordinary_chart"] = {
            **_summarize_worker_results(ordinary, "legacy_renderer_total_seconds"),
            "point_count": ordinary_points,
            "raw_repetitions": ordinary,
        }
    validate_benchmark_artifact(result)
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--points", type=int, default=974_153)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--ordinary-points", type=int)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--enforce", action="store_true")
    parser.add_argument("--repeat-timeout-seconds", type=float, default=300.0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--python-worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--browser-fixture-worker", action="store_true", help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--browser-fixture-output", type=Path, help=argparse.SUPPRESS
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.python_worker:
        print(json.dumps(_run_python_worker(args.points), sort_keys=True))
        return
    if args.browser_fixture_worker:
        if args.browser_fixture_output is None:
            raise SystemExit("--browser-fixture-output is required")
        print(
            json.dumps(
                _run_browser_fixture_worker(args.points, args.browser_fixture_output),
                sort_keys=True,
            )
        )
        return
    if args.output is None:
        raise SystemExit("--output is required")
    result = run_python_benchmark(
        args.points,
        args.repeats,
        repeat_timeout_seconds=args.repeat_timeout_seconds,
        ordinary_points=args.ordinary_points,
    )
    validate_benchmark_artifact(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if args.baseline is not None:
        before = json.loads(args.baseline.read_text(encoding="utf-8"))
        failures = compare_results(before, result)
        if failures:
            print("Performance gate failures:", file=sys.stderr)
            print("\n".join(f"- {failure}" for failure in failures), file=sys.stderr)
            if args.enforce:
                raise SystemExit(1)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
