"""Reproducible pre-Arrow benchmark for the interactive Scene pipeline.

The synthetic command is built before timing starts, so catalog access and
Matplotlib drawing cannot contaminate the renderer measurements. Each Python
repeat runs in a fresh bounded subprocess so its peak RSS is isolated from
other repeats and from browser measurement.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time

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

_SEED = 20260716
_DEFAULT_REPEAT_TIMEOUT_SECONDS = 300.0
_BROWSER_TIMEOUT_MS = 300_000
_SCENE_COMPILE_SEMANTICS = (
    "Compatibility alias for legacy_renderer_total: legacy pre-Scene command "
    "preparation plus Plotly Figure construction; not a native Scene compiler."
)
_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_MILLION_STAR_HTML_CANDIDATES = (
    Path("comparison_outputs/map_milky_way_stars/plotly.html"),
    Path("map_milky_way_stars.html"),
    Path("comparison_outputs/map_milky_way_stars.html"),
)

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


class _ArrayListView(list):
    """O(1) list-compatible view for legacy renderer ``isinstance`` checks.

    The benchmark's canonical columns remain contiguous read-only ndarrays.
    This adapter owns no list elements; any materialization observed during the
    benchmark is therefore performed by the current legacy renderer itself.
    """

    def __init__(self, values: np.ndarray):
        self._values = values

    def __bool__(self) -> bool:
        return bool(self._values.size)

    def __getitem__(self, index):
        return self._values[index]

    def __iter__(self):
        return iter(self._values)

    def __len__(self) -> int:
        return int(self._values.size)


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
        "ra_min": -math.pi,
        "ra_max": math.pi,
        "dec_min": -0.5 * math.pi,
        "dec_max": 0.5 * math.pi,
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


def _legacy_compatible_command(command):
    data = {
        key: _ArrayListView(values) if isinstance(values, np.ndarray) else values
        for key, values in command.data.items()
    }
    return replace(command, data=data)


def _peak_rss_mb() -> float:
    peak = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    divisor = 1024.0 * 1024.0 if sys.platform == "darwin" else 1024.0
    return peak / divisor


def _run_python_worker(point_count: int) -> dict:
    """Run one isolated legacy-preparation and Plotly-construction sample."""
    from starplot.interactive.plotly_renderer import PlotlyRenderer

    command, projection_info, style_info = _renderer_inputs(point_count)

    preparation_started = time.perf_counter()
    compatible_command = _legacy_compatible_command(command)
    adapter_seconds = time.perf_counter() - preparation_started

    initialization_started = time.perf_counter()
    renderer = PlotlyRenderer(
        projection_info,
        style_info,
        width=1000,
        height=500,
    )
    initialization_seconds = time.perf_counter() - initialization_started

    clipping_started = time.perf_counter()
    prepared_command = renderer._clip_command(compatible_command)
    clipping_seconds = time.perf_counter() - clipping_started
    if prepared_command is not None:
        prepared_command.clip_id = None

    construction_started = time.perf_counter()
    commands = [] if prepared_command is None else [prepared_command]
    figure = renderer.render(commands)
    construction_seconds = time.perf_counter() - construction_started

    preparation_seconds = adapter_seconds + clipping_seconds
    plotly_seconds = initialization_seconds + construction_seconds
    peak_rss_mb = _peak_rss_mb()
    payload_bytes = len(figure.to_json().encode("utf-8"))
    return {
        "legacy_renderer_preparation_seconds": preparation_seconds,
        "legacy_renderer_total_seconds": preparation_seconds + plotly_seconds,
        "payload_bytes": payload_bytes,
        "peak_rss_mb": peak_rss_mb,
        "plotly_construction_seconds": plotly_seconds,
    }


def _run_python_repeat(point_count: int, timeout_seconds: float) -> dict:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--python-worker",
        "--points",
        str(point_count),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=_REPOSITORY_ROOT,
            capture_output=True,
            check=True,
            text=True,
            timeout=timeout_seconds,
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


def _million_star_html() -> Path | None:
    for relative_path in _MILLION_STAR_HTML_CANDIDATES:
        candidate = _REPOSITORY_ROOT / relative_path
        if candidate.is_file():
            return candidate
    return None


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
    """Measure navigation through instrumented Plotly promise and final paint."""
    page.add_init_script(_PLOTLY_COMPLETION_INIT_SCRIPT)
    started = time.perf_counter()
    page.goto(uri, wait_until="load", timeout=timeout_ms)
    page.wait_for_function(
        "() => window.__starplotBenchmark.complete === true",
        timeout=timeout_ms,
    )
    return (time.perf_counter() - started) * 1000.0


def run_browser_benchmark(repeats: int) -> dict:
    """Measure complete rendering of the existing million-star HTML, if usable."""
    html_path = _million_star_html()
    if html_path is None:
        return {
            "complete_render_median_ms": None,
            "complete_render_p95_ms": None,
            "status": "not_available",
        }

    relative_source = str(html_path.relative_to(_REPOSITORY_ROOT))
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {
            "complete_render_median_ms": None,
            "complete_render_p95_ms": None,
            "source_html": relative_source,
            "status": "playwright_not_installed",
        }

    measurements: list[float] = []
    try:
        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            try:
                browser_version = browser.version
                for iteration in range(repeats + 1):
                    label = "warm-up" if iteration == 0 else f"repeat {iteration}/{repeats}"
                    print(f"Browser {label}: starting", flush=True)
                    page = browser.new_page(viewport={"width": 1000, "height": 500})
                    try:
                        elapsed_ms = _measure_browser_page(
                            page,
                            html_path.as_uri(),
                            _BROWSER_TIMEOUT_MS,
                        )
                    finally:
                        page.close()
                    print(
                        f"Browser {label}: complete ({elapsed_ms:.3f} ms)",
                        flush=True,
                    )
                    if iteration:
                        measurements.append(elapsed_ms)
            finally:
                browser.close()
    except Exception as error:
        return {
            "complete_render_median_ms": None,
            "complete_render_p95_ms": None,
            "error": f"{type(error).__name__}: {error}",
            "source_html": relative_source,
            "status": "measurement_failed",
        }

    return {
        "complete_render_median_ms": percentile(measurements, 50),
        "complete_render_p95_ms": percentile(measurements, 95),
        "completion_signal": "Plotly newPlot/react promise plus two animation frames",
        "engine": "chromium",
        "engine_version": browser_version,
        "source_html": relative_source,
        "status": "measured",
    }


def _summarize_worker_results(results: list[dict], key: str) -> dict[str, float]:
    return summarize([float(result[key]) for result in results])


def run_python_benchmark(
    point_count: int,
    repeats: int,
    repeat_timeout_seconds: float = _DEFAULT_REPEAT_TIMEOUT_SECONDS,
) -> dict:
    if point_count <= 0:
        raise ValueError("point_count must be positive")
    if repeats <= 0:
        raise ValueError("repeats must be positive")
    if repeat_timeout_seconds <= 0:
        raise ValueError("repeat_timeout_seconds must be positive")

    print("Python warm-up: starting", flush=True)
    warmup = _run_python_repeat(point_count, repeat_timeout_seconds)
    print(
        "Python warm-up: complete "
        f"({warmup['legacy_renderer_total_seconds']:.3f} s, "
        f"{warmup['peak_rss_mb']:.3f} MiB peak RSS)",
        flush=True,
    )

    measured: list[dict] = []
    for iteration in range(1, repeats + 1):
        print(f"Python repeat {iteration}/{repeats}: starting", flush=True)
        result = _run_python_repeat(point_count, repeat_timeout_seconds)
        measured.append(result)
        print(
            f"Python repeat {iteration}/{repeats}: complete "
            f"({result['legacy_renderer_total_seconds']:.3f} s, "
            f"{result['peak_rss_mb']:.3f} MiB peak RSS)",
            flush=True,
        )

    payload_sizes = {int(result["payload_bytes"]) for result in measured}
    if len(payload_sizes) != 1:
        raise RuntimeError(f"Python repeat payload sizes differ: {sorted(payload_sizes)}")

    preparation = _summarize_worker_results(
        measured, "legacy_renderer_preparation_seconds"
    )
    plotly_construction = _summarize_worker_results(
        measured, "plotly_construction_seconds"
    )
    legacy_total = _summarize_worker_results(
        measured, "legacy_renderer_total_seconds"
    )
    scene_compile = {**legacy_total, "semantics": _SCENE_COMPILE_SEMANTICS}

    browser = run_browser_benchmark(repeats)
    result = {
        "browser": browser,
        "environment": _environment(browser),
        "legacy_renderer_preparation": preparation,
        "legacy_renderer_total": legacy_total,
        "payload_bytes": payload_sizes.pop(),
        "peak_rss_mb": max(float(item["peak_rss_mb"]) for item in measured),
        "plotly_construction": plotly_construction,
        "point_count": point_count,
        "scene_compile": scene_compile,
    }
    validate_benchmark_artifact(result)
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--points", type=int, default=974_153)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--repeat-timeout-seconds", type=float, default=300.0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--python-worker", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.python_worker:
        print(json.dumps(_run_python_worker(args.points), sort_keys=True))
        return
    if args.output is None:
        raise SystemExit("--output is required")
    result = run_python_benchmark(
        args.points,
        args.repeats,
        repeat_timeout_seconds=args.repeat_timeout_seconds,
    )
    validate_benchmark_artifact(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
