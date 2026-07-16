"""Reproducible pre-Arrow benchmark for the interactive Scene pipeline.

The synthetic command is built before timing starts, so catalog access and
Matplotlib drawing cannot contaminate the renderer measurements.
"""

from __future__ import annotations

import argparse
import gc
import importlib.metadata
import json
import math
import platform
import resource
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


REQUIRED_RESULT_KEYS = {
    "environment",
    "point_count",
    "scene_compile",
    "peak_rss_mb",
    "payload_bytes",
    "browser",
}

_SEED = 20260716
_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_MILLION_STAR_HTML_CANDIDATES = (
    Path("comparison_outputs/map_milky_way_stars/plotly.html"),
    Path("map_milky_way_stars.html"),
    Path("comparison_outputs/map_milky_way_stars.html"),
)


def validate_result(result: dict) -> None:
    missing = REQUIRED_RESULT_KEYS - result.keys()
    if missing:
        raise ValueError(f"Missing benchmark keys: {sorted(missing)}")


def percentile(values: list[float], q: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=np.float64), q))


def summarize(values: list[float]) -> dict[str, float]:
    return {
        "median_seconds": percentile(values, 50),
        "p95_seconds": percentile(values, 95),
    }


def _mollweide_clip_points(vertex_count: int = 360) -> tuple[tuple[float, float], ...]:
    """Return a stable ellipse approximating the map's Mollweide boundary."""
    angles = np.linspace(0.0, 2.0 * math.pi, vertex_count, endpoint=False)
    return tuple(
        (float(math.pi * np.cos(angle)), float(0.5 * math.pi * np.sin(angle)))
        for angle in angles
    )


def _palette() -> list[str]:
    """Build 50 stable, visually distinct colors without Matplotlib."""
    return [
        f"#{(37 * index + 47) % 256:02x}{(83 * index + 89) % 256:02x}"
        f"{(149 * index + 131) % 256:02x}"
        for index in range(50)
    ]


def _build_scatter_command(point_count: int):
    from starplot.interactive.commands import DrawingCommand

    rng = np.random.default_rng(_SEED)
    x = rng.uniform(-math.pi, math.pi, point_count)
    y = rng.uniform(-0.5 * math.pi, 0.5 * math.pi, point_count)
    sizes = rng.uniform(0.02, 1.5, point_count).tolist()

    palette = _palette()
    alpha_cycle = np.linspace(0.04, 1.0, 50, dtype=np.float64).tolist()
    colors = [palette[index % 50] for index in range(point_count)]
    alphas = [alpha_cycle[index % 50] for index in range(point_count)]

    return DrawingCommand(
        kind="scatter",
        data={
            "x": x,
            "y": y,
            "sizes": sizes,
            "colors": colors,
            "alphas": alphas,
        },
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


def _render_once(command, projection_info: dict, style_info: dict):
    from starplot.interactive.plotly_renderer import PlotlyRenderer

    started = time.perf_counter()
    figure = PlotlyRenderer(
        projection_info,
        style_info,
        width=1000,
        height=500,
    ).render([command])
    return time.perf_counter() - started, figure


def _peak_rss_mb() -> float:
    peak = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    divisor = 1024.0 * 1024.0 if sys.platform == "darwin" else 1024.0
    return peak / divisor


def _package_version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _environment() -> dict[str, str]:
    return {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "machine": platform.machine(),
        "numpy": np.__version__,
        "platform": platform.platform(),
        "plotly": _package_version("plotly"),
        "python": platform.python_version(),
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
                    page = browser.new_page(viewport={"width": 1000, "height": 500})
                    started = time.perf_counter()
                    page.goto(html_path.as_uri(), wait_until="load", timeout=300_000)
                    page.wait_for_function(
                        """() => {
                            const graph = document.querySelector('.plotly-graph-div');
                            return Boolean(graph && graph._fullLayout && graph._fullData);
                        }""",
                        timeout=300_000,
                    )
                    page.evaluate(
                        "() => new Promise(resolve => requestAnimationFrame(() => "
                        "requestAnimationFrame(resolve)))"
                    )
                    elapsed_ms = (time.perf_counter() - started) * 1000.0
                    page.close()
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

    milliseconds = {
        "complete_render_median_ms": percentile(measurements, 50),
        "complete_render_p95_ms": percentile(measurements, 95),
        "engine": "chromium",
        "engine_version": browser_version,
        "source_html": relative_source,
        "status": "measured",
    }
    return milliseconds


def run_python_benchmark(point_count: int, repeats: int) -> dict:
    if point_count <= 0:
        raise ValueError("point_count must be positive")
    if repeats <= 0:
        raise ValueError("repeats must be positive")

    command, projection_info, style_info = _renderer_inputs(point_count)

    # Warm-up. Command creation, RNG work, catalog access, and Matplotlib are
    # deliberately outside the timed renderer region.
    _, figure = _render_once(command, projection_info, style_info)
    del figure
    gc.collect()

    durations: list[float] = []
    final_figure = None
    for _ in range(repeats):
        duration, figure = _render_once(command, projection_info, style_info)
        durations.append(duration)
        if final_figure is not None:
            del final_figure
            gc.collect()
        final_figure = figure

    payload_bytes = len(final_figure.to_json().encode("utf-8"))
    result = {
        "browser": run_browser_benchmark(repeats),
        "environment": _environment(),
        "payload_bytes": payload_bytes,
        "peak_rss_mb": _peak_rss_mb(),
        "point_count": point_count,
        "scene_compile": summarize(durations),
    }
    validate_result(result)
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--points", type=int, default=974_153)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    result = run_python_benchmark(args.points, args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
