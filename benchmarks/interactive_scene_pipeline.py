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
from contextlib import ExitStack, contextmanager

import numpy as np


REQUIRED_RESULT_KEYS = {
    "browser",
    "environment",
    "payload_bytes",
    "peak_rss_mb",
    "point_count",
    "scene_compile",
}
BENCHMARK_SCHEMA_VERSION = 1
REQUIRED_ARTIFACT_KEYS = REQUIRED_RESULT_KEYS | {
    "artifact_role",
    "legacy_renderer_preparation",
    "legacy_renderer_total",
    "plot_type_coverage",
    "plotly_construction",
    "schema_version",
}
REQUIRED_LEGACY_BASELINE_KEYS = {
    "artifact_role",
    "browser",
    "environment",
    "ordinary_chart",
    "peak_rss_mb",
    "point_count",
    "scene_compile",
    "schema_version",
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
_PLOT_TYPE_COVERAGE_SEMANTICS = (
    "One small, real recording/SceneCompiler/PlotlySceneAdapter sample for each "
    "supported interactive plot family, paired with external-Arrow browser "
    "diagnostics; this is coverage evidence, not a cross-family performance gate."
)
_PLOT_TYPE_BROWSER_SEMANTICS = (
    "One warm-up plus repeated external-Arrow HTTP renders for every supported "
    "interactive plot family; timings are diagnostic and have no cross-family gate."
)
_SUPPORTED_INTERACTIVE_PLOT_KINDS = frozenset({"map", "horizon", "zenith", "optic"})
_COMPARABLE_ENVIRONMENT_KEYS = (
    "host_fingerprint",
    "cpu",
    "cpu_count",
    "machine",
    "os",
    "python",
    "numpy",
    "plotly",
    "pyarrow",
    "shapely",
)
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


def _validate_environment(environment: object) -> None:
    if not isinstance(environment, dict):
        raise ValueError("Benchmark environment must be a mapping")
    missing_environment = REQUIRED_ENVIRONMENT_KEYS - environment.keys()
    if missing_environment:
        raise ValueError(
            f"Missing benchmark environment keys: {sorted(missing_environment)}"
        )


def _require_positive_integer(mapping: dict, key: str, label: str) -> int:
    value = mapping.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _require_nonempty_string(mapping: dict, key: str, label: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _require_scene_hash(mapping: dict, key: str, label: str) -> str:
    value = _require_nonempty_string(mapping, key, label)
    prefix = "sha256:"
    digest = value[len(prefix) :] if value.startswith(prefix) else ""
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ValueError(f"{label} must be a sha256 hash")
    return value


def _require_nonnegative_number(mapping: dict, key: str, label: str) -> float:
    value = mapping.get(key)
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{label} must be a finite non-negative number")
    return float(value)


def _validate_timing_summary(summary: object, label: str) -> None:
    if not isinstance(summary, dict):
        raise ValueError(f"{label} must be a mapping")
    median = _require_nonnegative_number(
        summary, "median_seconds", f"{label}.median_seconds"
    )
    p95 = _require_nonnegative_number(summary, "p95_seconds", f"{label}.p95_seconds")
    if p95 < median:
        raise ValueError(f"{label}.p95_seconds must be at least median_seconds")


def _validate_primary_browser(browser: object) -> None:
    if not isinstance(browser, dict):
        raise ValueError("browser must be a mapping")
    status = browser.get("status")
    if status not in {
        "measured",
        "measurement_failed",
        "playwright_not_installed",
    }:
        raise ValueError("browser has invalid or missing status")
    if browser.get("source_kind") != "external-arrow-http":
        raise ValueError("browser.source_kind must be external-arrow-http")
    if status != "measured":
        if status == "measurement_failed":
            _require_nonempty_string(browser, "error", "browser.error")
        return

    _require_nonempty_string(browser, "completion_signal", "browser.completion_signal")
    _require_nonempty_string(browser, "engine", "browser.engine")
    _require_nonempty_string(browser, "engine_version", "browser.engine_version")
    scene_hash = _require_scene_hash(browser, "scene_hash", "browser.scene_hash")
    _require_positive_integer(
        browser, "arrow_payload_bytes", "browser.arrow_payload_bytes"
    )
    median = _require_nonnegative_number(
        browser,
        "complete_render_median_ms",
        "browser.complete_render_median_ms",
    )
    p95 = _require_nonnegative_number(
        browser, "complete_render_p95_ms", "browser.complete_render_p95_ms"
    )
    if p95 < median:
        raise ValueError(
            "browser.complete_render_p95_ms must be at least complete_render_median_ms"
        )

    legacy = browser.get("legacy_same_scene")
    if not isinstance(legacy, dict):
        raise ValueError("browser.legacy_same_scene must be a mapping")
    if legacy.get("source_kind") != "direct-plotly-same-scene-http":
        raise ValueError(
            "browser.legacy_same_scene.source_kind must be "
            "direct-plotly-same-scene-http"
        )
    legacy_hash = _require_scene_hash(
        legacy, "scene_hash", "browser.legacy_same_scene.scene_hash"
    )
    if legacy_hash != scene_hash:
        raise ValueError(
            "browser.legacy_same_scene.scene_hash must match browser.scene_hash"
        )
    legacy_median = _require_nonnegative_number(
        legacy,
        "complete_render_median_ms",
        "browser.legacy_same_scene.complete_render_median_ms",
    )
    legacy_p95 = _require_nonnegative_number(
        legacy,
        "complete_render_p95_ms",
        "browser.legacy_same_scene.complete_render_p95_ms",
    )
    if legacy_p95 < legacy_median:
        raise ValueError(
            "browser.legacy_same_scene.complete_render_p95_ms must be at least "
            "complete_render_median_ms"
        )


def _validate_legacy_baseline(result: dict) -> None:
    missing = REQUIRED_LEGACY_BASELINE_KEYS - result.keys()
    if missing:
        raise ValueError(f"Missing legacy baseline keys: {sorted(missing)}")
    _validate_environment(result.get("environment"))
    _require_positive_integer(result, "point_count", "point_count")
    _require_nonnegative_number(result, "peak_rss_mb", "peak_rss_mb")
    ordinary = result.get("ordinary_chart")
    if not isinstance(ordinary, dict):
        raise ValueError("ordinary_chart must be a mapping")
    _validate_timing_summary(result.get("scene_compile"), "scene_compile")
    _validate_timing_summary(ordinary, "ordinary_chart")
    _require_positive_integer(ordinary, "point_count", "ordinary_chart.point_count")
    browser = result.get("browser")
    if not isinstance(browser, dict):
        raise ValueError("browser must be a mapping")
    if browser.get("status") != "not_applicable":
        raise ValueError("legacy baseline browser.status must be not_applicable")
    _require_nonempty_string(
        browser, "source_kind", "legacy baseline browser.source_kind"
    )
    _require_nonempty_string(browser, "reason", "legacy baseline browser.reason")


def validate_benchmark_artifact(result: dict) -> None:
    """Validate the stricter schema required for a persisted baseline JSON."""
    if result.get("schema_version") != BENCHMARK_SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {BENCHMARK_SCHEMA_VERSION}")
    artifact_role = result.get("artifact_role")
    if artifact_role == "legacy_baseline":
        _validate_legacy_baseline(result)
        return
    if artifact_role != "candidate":
        raise ValueError("artifact_role must be candidate or legacy_baseline")

    validate_result(result)
    missing = REQUIRED_ARTIFACT_KEYS - result.keys()
    if missing:
        raise ValueError(f"Missing benchmark artifact keys: {sorted(missing)}")
    _validate_environment(result.get("environment"))
    _require_positive_integer(result, "point_count", "point_count")
    _validate_primary_browser(result.get("browser"))
    coverage = result.get("plot_type_coverage")
    if not isinstance(coverage, dict) or not isinstance(coverage.get("semantics"), str):
        raise ValueError("plot_type_coverage must include string semantics")
    plot_types = coverage.get("plot_types")
    if not isinstance(plot_types, dict):
        raise ValueError("plot_type_coverage.plot_types must be a mapping")
    if set(plot_types) != _SUPPORTED_INTERACTIVE_PLOT_KINDS:
        raise ValueError(
            "plot_type_coverage.plot_types must cover exactly "
            f"{sorted(_SUPPORTED_INTERACTIVE_PLOT_KINDS)}"
        )
    for name, evidence in plot_types.items():
        if not isinstance(evidence, dict) or evidence.get("plot_kind") != name:
            raise ValueError(f"plot_type_coverage {name!r} has invalid plot_kind")
        for metric in (
            "recorded_command_count",
            "scene_layer_count",
            "rendered_primitive_count",
        ):
            value = evidence.get(metric)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(
                    f"plot_type_coverage {name!r} requires positive integer {metric}"
                )
        kinds = evidence.get("recorded_command_kinds")
        if not isinstance(kinds, list) or not kinds or not all(
            isinstance(kind, str) and kind for kind in kinds
        ):
            raise ValueError(
                f"plot_type_coverage {name!r} requires recorded_command_kinds"
            )
        for metric in ("scene_compile_seconds", "plotly_render_seconds"):
            value = evidence.get(metric)
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError(
                    f"plot_type_coverage {name!r} requires non-negative {metric}"
                )
    browser_coverage = coverage.get("browser")
    if not isinstance(browser_coverage, dict):
        raise ValueError("plot_type_coverage.browser must be a mapping")
    if not isinstance(browser_coverage.get("semantics"), str):
        raise ValueError("plot_type_coverage.browser must include string semantics")
    browser_status = browser_coverage.get("status")
    if browser_status not in {
        "measured",
        "measurement_failed",
        "playwright_not_installed",
    }:
        raise ValueError("plot_type_coverage.browser has invalid status")
    if browser_status == "measured":
        browser_plot_types = browser_coverage.get("plot_types")
        if not isinstance(browser_plot_types, dict):
            raise ValueError("plot_type_coverage.browser.plot_types must be a mapping")
        if set(browser_plot_types) != _SUPPORTED_INTERACTIVE_PLOT_KINDS:
            raise ValueError(
                "plot_type_coverage browser plot_types must cover exactly "
                f"{sorted(_SUPPORTED_INTERACTIVE_PLOT_KINDS)}"
            )
        for name, evidence in browser_plot_types.items():
            if not isinstance(evidence, dict):
                raise ValueError(
                    f"plot_type_coverage browser {name!r} evidence must be a mapping"
                )
            payload_bytes = evidence.get("arrow_payload_bytes")
            if (
                not isinstance(payload_bytes, int)
                or isinstance(payload_bytes, bool)
                or payload_bytes <= 0
            ):
                raise ValueError(
                    f"plot_type_coverage browser {name!r} requires Arrow payload bytes"
                )
            scene_hash = evidence.get("scene_hash")
            if not isinstance(scene_hash, str) or not scene_hash.startswith("sha256:"):
                raise ValueError(
                    f"plot_type_coverage browser {name!r} requires a scene hash"
                )
            for metric in (
                "complete_render_median_ms",
                "complete_render_p95_ms",
            ):
                value = evidence.get(metric)
                if (
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or not math.isfinite(value)
                    or value < 0
                ):
                    raise ValueError(
                        f"plot_type_coverage browser {name!r} requires non-negative "
                        f"{metric}"
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
    before_role = before.get("artifact_role")
    after_role = after.get("artifact_role")
    if (before_role, after_role) != ("legacy_baseline", "candidate"):
        return [
            "artifact roles are not comparable; expected legacy_baseline -> "
            f"candidate but got {before_role} -> {after_role}"
        ]
    if (
        before.get("schema_version") != BENCHMARK_SCHEMA_VERSION
        or after.get("schema_version") != BENCHMARK_SCHEMA_VERSION
    ):
        return [
            f"schema_version must be {BENCHMARK_SCHEMA_VERSION} for comparable "
            "artifacts"
        ]
    before_point_count = before.get("point_count")
    after_point_count = after.get("point_count")
    if before_point_count != after_point_count:
        return [
            "point_count differs; benchmark workloads are not comparable "
            f"({before_point_count} != {after_point_count})"
        ]
    if (
        not isinstance(before_point_count, int)
        or isinstance(before_point_count, bool)
        or before_point_count <= 0
    ):
        return ["point_count must be a positive integer for comparable workloads"]
    before_ordinary = before.get("ordinary_chart", {})
    after_ordinary = after.get("ordinary_chart", {})
    before_ordinary_points = (
        before_ordinary.get("point_count")
        if isinstance(before_ordinary, dict)
        else None
    )
    after_ordinary_points = (
        after_ordinary.get("point_count") if isinstance(after_ordinary, dict) else None
    )
    if before_ordinary_points != after_ordinary_points:
        return [
            "ordinary_chart.point_count differs; benchmark workloads are not "
            f"comparable ({before_ordinary_points} != {after_ordinary_points})"
        ]

    for label, artifact in (("baseline", before), ("candidate", after)):
        try:
            validate_benchmark_artifact(artifact)
        except ValueError as error:
            return [f"{label} artifact schema is invalid: {error}"]

    before_environment = before["environment"]
    after_environment = after["environment"]
    for key in _COMPARABLE_ENVIRONMENT_KEYS:
        before_value = before_environment[key]
        after_value = after_environment[key]
        if before_value != after_value:
            return [
                f"environment.{key} differs; benchmark workloads are not "
                f"comparable ({before_value!r} != {after_value!r})"
            ]

    failures: list[str] = []

    def ratio_gate(
        label: str, before_path: str, after_path: str, maximum: float
    ) -> None:
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

    ratio_gate(
        "scene_compile",
        "scene_compile.median_seconds",
        "scene_compile.median_seconds",
        PERFORMANCE_GATES["scene_compile_ratio_max"],
    )
    ratio_gate(
        "peak_rss",
        "peak_rss_mb",
        "peak_rss_mb",
        PERFORMANCE_GATES["peak_rss_ratio_max"],
    )
    maximum_gate(
        "arrow_payload_bytes",
        "arrow_payload_bytes",
        PERFORMANCE_GATES["arrow_payload_bytes_max"],
    )
    maximum_gate(
        "external_html_bytes",
        "external_html_bytes",
        PERFORMANCE_GATES["external_html_bytes_max"],
    )
    primary_browser = after.get("browser", {})
    paired_browser = primary_browser.get("legacy_same_scene")
    if primary_browser.get("status") != "measured":
        failures.append("browser primary measurement is not measured")
    elif isinstance(paired_browser, dict):
        legacy = _metric(paired_browser, "complete_render_median_ms")
        current = _metric(after, "browser.complete_render_median_ms")
        if paired_browser.get("scene_hash") != primary_browser.get("scene_hash"):
            failures.append(
                "browser_complete_render paired legacy fixture scene_hash differs"
            )
        elif legacy is None:
            failures.append("browser_complete_render paired legacy result is missing")
        elif current is None:
            failures.append(
                "browser_complete_render result is missing (browser.complete_render_median_ms)"
            )
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
        ratio_gate(
            "browser_complete_render",
            "browser.complete_render_median_ms",
            "browser.complete_render_median_ms",
            PERFORMANCE_GATES["browser_complete_render_ratio_max"],
        )
    maximum_gate(
        "browser_complete_render_p95",
        "browser.complete_render_p95_ms",
        PERFORMANCE_GATES["browser_complete_render_p95_ms_max"],
    )
    ratio_gate(
        "ordinary_chart",
        "ordinary_chart.median_seconds",
        "ordinary_chart.median_seconds",
        PERFORMANCE_GATES["ordinary_chart_regression_ratio_max"],
    )
    maximum_gate(
        "viewport_warm_median",
        "viewport_warm.median_ms",
        PERFORMANCE_GATES["viewport_warm_median_ms_max"],
    )
    maximum_gate(
        "viewport_warm_p95",
        "viewport_warm.p95_ms",
        PERFORMANCE_GATES["viewport_warm_p95_ms_max"],
    )
    plot_type_browser = after.get("plot_type_coverage", {}).get("browser", {})
    if plot_type_browser.get("status") != "measured":
        failures.append("plot_type_coverage browser diagnostics are not measured")
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


@contextmanager
def _representative_recorded_plot_cases():
    """Return small real recordings for every public interactive plot family.

    The high-volume benchmark below deliberately keeps its synthetic map
    command: it is the stable workload for payload and browser regression
    gates.  These cases prevent that one workload from silently becoming the
    only exercised plot path.  Each case uses the public Starplot plot API to
    record an actual Matplotlib primitive before Scene compilation.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from ibis import _ as ibis_col
    from starplot import Miller, Observer
    from starplot.interactive import (
        InteractiveHorizonPlot,
        InteractiveMapPlot,
        InteractiveOpticPlot,
        InteractiveZenithPlot,
    )
    from starplot.models import Refractor

    observer = Observer(
        dt=datetime(2023, 7, 13, 22, 0, tzinfo=ZoneInfo("America/Los_Angeles")),
        lat=33.363484,
        lon=-116.836394,
    )

    with ExitStack() as stack:
        def own(plot):
            stack.callback(plot.close_fig)
            return plot

        map_plot = own(
            InteractiveMapPlot(
                projection=Miller(),
                ra_min=60,
                ra_max=120,
                dec_min=-10,
                dec_max=30,
                resolution=512,
            )
        )
        map_plot.stars(where=[ibis_col.magnitude < 2])

        horizon_plot = own(
            InteractiveHorizonPlot(
                altitude=(0, 60),
                azimuth=(325, 440),
                observer=observer,
                resolution=512,
            )
        )
        horizon_plot.stars(where=[ibis_col.magnitude < 2])

        zenith_plot = own(InteractiveZenithPlot(observer=observer, resolution=512))
        zenith_plot.horizon(labels=[])

        optic_plot = own(
            InteractiveOpticPlot(
                ra=90.0,
                dec=10.0,
                observer=observer,
                optic=Refractor(
                    focal_length=430,
                    eyepiece_focal_length=11,
                    eyepiece_fov=82,
                ),
                resolution=512,
                raise_on_below_horizon=False,
            )
        )
        optic_plot.info()

        yield (
            ("map", map_plot),
            ("horizon", horizon_plot),
            ("zenith", zenith_plot),
            ("optic", optic_plot),
        )


def _rendered_primitive_count(figure) -> int:
    """Count Plotly traces plus layout primitives used by non-scatter plots."""
    layout = figure.layout
    return len(figure.data) + len(layout.shapes or ()) + len(layout.annotations or ())


def run_recorded_plot_type_coverage() -> dict[str, object]:
    """Exercise real recording, compilation, and rendering for all plot types."""
    from starplot.interactive.plotly_adapter import PlotlySceneAdapter

    cases: dict[str, dict[str, object]] = {}
    with _representative_recorded_plot_cases() as recorded_cases:
        for name, plot in recorded_cases:
            commands = plot._recorder.coalesced_scatter_commands()
            if not commands:
                raise RuntimeError(f"{name} coverage case recorded no drawing commands")

            compilation_started = time.perf_counter()
            scene = plot._compile_scene()
            compilation_seconds = time.perf_counter() - compilation_started
            if not scene.layers:
                raise RuntimeError(f"{name} coverage case compiled no Scene layers")

            rendering_started = time.perf_counter()
            figure = PlotlySceneAdapter().render(scene)
            rendering_seconds = time.perf_counter() - rendering_started
            rendered_primitives = _rendered_primitive_count(figure)
            if not rendered_primitives:
                raise RuntimeError(f"{name} coverage case rendered no Plotly primitives")

            cases[name] = {
                "plot_kind": scene.projection_info["plot_kind"],
                "recorded_command_count": len(commands),
                "recorded_command_kinds": sorted(
                    {command.kind.value for command in commands}
                ),
                "scene_layer_count": len(scene.layers),
                "rendered_primitive_count": rendered_primitives,
                "scene_compile_seconds": compilation_seconds,
                "plotly_render_seconds": rendering_seconds,
            }
    return {"semantics": _PLOT_TYPE_COVERAGE_SEMANTICS, "plot_types": cases}


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


def _export_recorded_plot_type_browser_fixtures(
    output_directory: Path,
) -> dict[str, dict[str, object]]:
    """Export one real external-Arrow fixture for every public plot family."""
    from starplot.interactive.web_export import (
        DataMode,
        LibraryMode,
        export_scene_html,
    )

    fixtures: dict[str, dict[str, object]] = {}
    with _representative_recorded_plot_cases() as recorded_cases:
        for name, plot in recorded_cases:
            scene = plot._compile_scene()
            exported = export_scene_html(
                scene,
                output_directory / f"{name}.html",
                data_mode=DataMode.EXTERNAL,
                library_mode=LibraryMode.DIRECTORY,
            )
            fixtures[name] = {
                "arrow_payload_bytes": sum(
                    len(payload) for payload in exported.layer_bytes.values()
                ),
                "scene_hash": exported.scene_hash,
            }
    return fixtures


@contextmanager
def _recorded_plot_type_browser_fixture():
    """Serve real external-Arrow pages for the four public plot families."""
    from starplot.cli import create_server

    with tempfile.TemporaryDirectory(prefix="starplot-plot-types-browser-") as directory:
        root = Path(directory)
        fixtures = _export_recorded_plot_type_browser_fixtures(root)
        server = create_server(root, host="127.0.0.1", port=0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        host, port = server.server_address[:2]
        try:
            yield {
                name: {
                    **metadata,
                    "source_url": f"http://{host}:{port}/{name}.html",
                }
                for name, metadata in fixtures.items()
            }
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)


def run_recorded_plot_type_browser_diagnostics(repeats: int) -> dict[str, object]:
    """Measure real browser rendering for every public interactive plot family."""
    if repeats <= 0:
        raise ValueError("repeats must be positive")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {
            "semantics": _PLOT_TYPE_BROWSER_SEMANTICS,
            "source_kind": "external-arrow-http",
            "status": "playwright_not_installed",
        }

    measurements = {
        name: [] for name in sorted(_SUPPORTED_INTERACTIVE_PLOT_KINDS)
    }
    try:
        with _recorded_plot_type_browser_fixture() as fixtures, sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            try:
                browser_version = browser.version
                context = browser.new_context(
                    viewport={"width": 1000, "height": 500}
                )
                try:
                    for iteration in range(repeats + 1):
                        label = (
                            "warm-up"
                            if iteration == 0
                            else f"repeat {iteration}/{repeats}"
                        )
                        for name, fixture in fixtures.items():
                            print(
                                f"Browser {name} diagnostic {label}: starting",
                                flush=True,
                            )
                            page = context.new_page()
                            try:
                                elapsed_ms = _measure_browser_page(
                                    page,
                                    str(fixture["source_url"]),
                                    _BROWSER_TIMEOUT_MS,
                                )
                            finally:
                                page.close()
                            print(
                                f"Browser {name} diagnostic {label}: complete "
                                f"({elapsed_ms:.3f} ms)",
                                flush=True,
                            )
                            if iteration:
                                measurements[name].append(elapsed_ms)
                finally:
                    context.close()
            finally:
                browser.close()
    except Exception as error:
        return {
            "error": f"{type(error).__name__}: {error}",
            "semantics": _PLOT_TYPE_BROWSER_SEMANTICS,
            "source_kind": "external-arrow-http",
            "status": "measurement_failed",
        }

    return {
        "engine": "chromium",
        "engine_version": browser_version,
        "plot_types": {
            name: {
                "arrow_payload_bytes": int(fixtures[name]["arrow_payload_bytes"]),
                "complete_render_median_ms": percentile(values, 50),
                "complete_render_p95_ms": percentile(values, 95),
                "scene_hash": fixtures[name]["scene_hash"],
            }
            for name, values in measurements.items()
        },
        "semantics": _PLOT_TYPE_BROWSER_SEMANTICS,
        "source_kind": "external-arrow-http",
        "status": "measured",
    }


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
                for name, url, values in (
                    ("external Arrow", fixture["source_url"], measurements),
                    ("legacy direct", fixture["legacy_source_url"], legacy_measurements),
                ):
                    # ``browser.new_page`` is a convenience API that creates a
                    # fresh context for every page, so its nominal warm-up does
                    # not warm HTTP/library caches for the measured repeats.
                    # Give each source an isolated persistent context and open
                    # fresh pages inside it: warm within a source, never across
                    # the external/direct comparison boundary.
                    context = browser.new_context(
                        viewport={"width": 1000, "height": 500}
                    )
                    try:
                        for iteration in range(repeats + 1):
                            label = (
                                "warm-up"
                                if iteration == 0
                                else f"repeat {iteration}/{repeats}"
                            )
                            print(f"Browser {name} {label}: starting", flush=True)
                            page = context.new_page()
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
                        context.close()
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

    # Browser timings are extremely sensitive to CPU thermal pressure.  Measure
    # both browser workloads before the repeated dense Python/RSS workload so a
    # single artifact does not heat the host before timing Chromium.
    browser = run_browser_benchmark(
        point_count,
        repeats,
        fixture_timeout_seconds=repeat_timeout_seconds,
    )
    plot_type_browser = run_recorded_plot_type_browser_diagnostics(repeats)

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

    ordinary_chart = None
    if ordinary_points is not None:
        if ordinary_points <= 0:
            raise ValueError("ordinary_points must be positive")
        ordinary = _run_python_samples(
            ordinary_points, repeats, repeat_timeout_seconds, label="Ordinary chart"
        )
        ordinary_chart = {
            **_summarize_worker_results(ordinary, "legacy_renderer_total_seconds"),
            "point_count": ordinary_points,
            "raw_repetitions": ordinary,
        }

    plot_type_coverage = run_recorded_plot_type_coverage()
    plot_type_coverage["browser"] = plot_type_browser
    result = {
        "arrow_payload_bytes": int(measured[0]["arrow_payload_bytes"]),
        "artifact_role": "candidate",
        "browser": browser,
        "environment": _environment(browser),
        "external_html_bytes": int(measured[0]["external_html_bytes"]),
        "legacy_renderer_preparation": preparation,
        "legacy_renderer_total": legacy_total,
        "payload_bytes": payload_sizes.pop(),
        "peak_rss_mb": max(float(item["peak_rss_mb"]) for item in measured),
        "plotly_construction": plotly_construction,
        "plot_type_coverage": plot_type_coverage,
        "point_count": point_count,
        "scene_compile": scene_compile,
        "schema_version": BENCHMARK_SCHEMA_VERSION,
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
    if ordinary_chart is not None:
        result["ordinary_chart"] = ordinary_chart
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
