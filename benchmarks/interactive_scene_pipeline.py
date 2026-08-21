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
import re
try:
    import resource
except ImportError:
    resource = None
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterable
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
BENCHMARK_SCHEMA_VERSION = 2
REQUIRED_ARTIFACT_KEYS = REQUIRED_RESULT_KEYS | {
    "artifact_role",
    "legacy_renderer_preparation",
    "legacy_renderer_total",
    "plot_type_coverage",
    "plotly_construction",
    "provenance",
    "raw_repetitions",
    "schema_version",
}
REQUIRED_LEGACY_BASELINE_KEYS = {
    "artifact_role",
    "browser",
    "environment",
    "ordinary_chart",
    "peak_rss_mb",
    "point_count",
    "provenance",
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
    "browser_cold_start_ms_max": 5000,
    "ordinary_chart_regression_ratio_max": 1.10,
    "viewport_warm_median_ms_max": 500,
    "viewport_warm_p95_ms_max": 1000,
}

_SEED = 20260716
_DEFAULT_REPEAT_TIMEOUT_SECONDS = 300.0
_BROWSER_TIMEOUT_MS = 300_000
# Cold measurements must be taken from a fresh browser context.  A minimum of
# three cold samples gives a representative first-load distribution.
_BROWSER_COLD_SAMPLES = 3
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
# In-page completion signals the validator recognizes.  These are the only
# legitimate values for browser completion evidence.
_BROWSER_COMPLETION_SIGNALS = frozenset(
    {"starplot-product-promise", "plotly-fallback"}
)
_SUPPORTED_INTERACTIVE_PLOT_KINDS = frozenset({"map", "horizon", "zenith", "optic"})
_SOURCE_FINGERPRINT_SCOPE = [
    "benchmarks/interactive_scene_pipeline.py",
    "pyproject.toml",
    "src/starplot/** (tracked files)",
]
_LEGACY_MEASUREMENT_KINDS = {
    "dense_workload": "historical-pre-arrow-release-baseline",
    "ordinary_chart": "isolated-control-backfill",
}
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
    completionSignal: null,
    method: null,
    navigationTimings: null,
    startedAt: null,
    starplotCalls: 0,
    starplotCompletedAt: null
  };

  const afterFinalPaint = (callback) => {
    requestAnimationFrame(() => requestAnimationFrame(callback));
  };

  const recordNavigation = () => {
    state.navigationTimings = performance.getEntriesByType("navigation").map(
      (entry) => ({
        startTime: entry.startTime,
        duration: entry.duration,
        domComplete: entry.domComplete,
        loadEventEnd: entry.loadEventEnd,
        responseEnd: entry.responseEnd,
      })
    );
  };

  const markStarplotComplete = () => {
    if (state.starplotCompletedAt !== null) return;
    state.starplotCompletedAt = performance.now();
    state.completionSignal = "starplot-product-promise";
    recordNavigation();
  };

  const markPlotlyComplete = (generation) => {
    // The Plotly fallback is only legitimate when no Starplot product render
    // promise is present.  If starplotCalls is non-zero the product owns the
    // completion and any Plotly callback must be ignored.
    if (state.starplotCalls > 0) return;
    if (state.completedAt !== null) return;
    if (generation !== state.calls) return;
    state.completedAt = performance.now();
    state.complete = true;
    state.completionSignal = "plotly-fallback";
    recordNavigation();
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
        Promise.resolve(result).then(() => {
          afterFinalPaint(() => {
            markPlotlyComplete(generation);
          });
        }, () => {});
        // Instrumentation must not add paint frames to the product promise.
        return result;
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

  let renderPromiseValue = window.__starplotRenderPromise;
  const observeRenderPromise = (value) => {
    const generation = ++state.starplotCalls;
    state.starplotCompletedAt = null;
    Promise.resolve(value).then(() => {
      if (generation === state.starplotCalls) {
        // renderScene resolves only after its own final-paint contract.
        markStarplotComplete();
      }
    }, () => {});
  };
  if (renderPromiseValue) observeRenderPromise(renderPromiseValue);
  const renderDescriptor = Object.getOwnPropertyDescriptor(
    window, "__starplotRenderPromise"
  );
  if (!renderDescriptor || renderDescriptor.configurable) {
    Object.defineProperty(window, "__starplotRenderPromise", {
      configurable: true,
      enumerable: true,
      get: () => renderPromiseValue,
      set: (value) => {
        renderPromiseValue = value;
        observeRenderPromise(value);
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


def _git_output(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=_REPOSITORY_ROOT,
        capture_output=True,
        check=True,
        text=True,
    )
    return completed.stdout


def _git_bytes(*args: str) -> bytes:
    return subprocess.run(
        ["git", *args],
        cwd=_REPOSITORY_ROOT,
        capture_output=True,
        check=True,
    ).stdout


def _source_fingerprint_paths() -> list[Path]:
    tracked = _git_output(
        "ls-files",
        "--",
        "benchmarks/interactive_scene_pipeline.py",
        "pyproject.toml",
        "src/starplot",
    )
    return [
        _REPOSITORY_ROOT / relative_path
        for relative_path in sorted(filter(None, tracked.splitlines()))
    ]


def _fingerprint_source_entries(
    entries: Iterable[tuple[str, bytes]],
) -> str:
    digest = hashlib.sha256()
    for relative_path_text, content in entries:
        relative_path = relative_path_text.encode()
        digest.update(len(relative_path).to_bytes(8, "big"))
        digest.update(relative_path)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return f"sha256:{digest.hexdigest()}"


def _source_fingerprint() -> str:
    return _fingerprint_source_entries(
        (
            path.relative_to(_REPOSITORY_ROOT).as_posix(),
            path.read_bytes(),
        )
        for path in _source_fingerprint_paths()
    )


def _source_fingerprint_at_revision(revision: str) -> str:
    tracked = _git_output(
        "ls-tree",
        "-r",
        "--name-only",
        revision,
        "--",
        "benchmarks/interactive_scene_pipeline.py",
        "pyproject.toml",
        "src/starplot",
    )
    paths = sorted(filter(None, tracked.splitlines()))
    return _fingerprint_source_entries(
        (path, _git_bytes("show", f"{revision}:{path}")) for path in paths
    )


def _tracked_worktree_dirty() -> bool:
    status = _git_output("status", "--porcelain=v1", "--untracked-files=all")
    for line in status.splitlines():
        if not line:
            continue
        path = line[3:].split(" -> ")[-1]
        if line.startswith("?? "):
            if path.startswith("src/starplot/"):
                return True
            continue
        if path.startswith("benchmarks/baselines/") and path.endswith(".json"):
            continue
        return True
    return False


def _current_source_provenance() -> dict[str, object]:
    return {
        "fingerprint": _source_fingerprint(),
        "fingerprint_scope": list(_SOURCE_FINGERPRINT_SCOPE),
        "git_revision": _git_output("rev-parse", "HEAD").strip(),
        "tracked_dirty": _tracked_worktree_dirty(),
    }


def _workload_provenance(
    point_count: int,
    ordinary_point_count: int | None,
    repeats: int,
) -> dict[str, object]:
    workload: dict[str, object] = {
        "ordinary_point_count": ordinary_point_count,
        "point_count": point_count,
        "repeats": repeats,
        "seed": _SEED,
    }
    encoded = json.dumps(workload, sort_keys=True, separators=(",", ":")).encode()
    return {
        **workload,
        "fingerprint": f"sha256:{hashlib.sha256(encoded).hexdigest()}",
    }


def _is_full_git_revision(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(character in "0123456789abcdef" for character in value)
    )


def _validate_source_revision(revision: str, expected_fingerprint: str) -> None:
    try:
        object_type = _git_output("cat-file", "-t", revision).strip()
    except subprocess.CalledProcessError as error:
        raise ValueError(
            "provenance.source.git_revision does not identify an existing commit"
        ) from error
    if object_type != "commit":
        raise ValueError(
            "provenance.source.git_revision does not identify an existing commit"
        )
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", revision, "HEAD"],
        cwd=_REPOSITORY_ROOT,
        capture_output=True,
        check=False,
    )
    if ancestor.returncode != 0:
        raise ValueError(
            "provenance.source.git_revision is not an ancestor of the current HEAD"
        )
    if _source_fingerprint_at_revision(revision) != expected_fingerprint:
        raise ValueError(
            "provenance.source fingerprint does not match its git_revision"
        )


def _validate_candidate_provenance(result: dict) -> int:
    provenance = result.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("provenance must be a mapping")
    source = provenance.get("source")
    if not isinstance(source, dict):
        raise ValueError("provenance.source must be a mapping")
    _require_scene_hash(source, "fingerprint", "provenance.source.fingerprint")
    if source.get("fingerprint_scope") != _SOURCE_FINGERPRINT_SCOPE:
        raise ValueError("provenance.source.fingerprint_scope is invalid")
    revision = source.get("git_revision")
    if not _is_full_git_revision(revision):
        raise ValueError("provenance.source.git_revision must be a full git revision")
    if not isinstance(source.get("tracked_dirty"), bool):
        raise ValueError("provenance.source.tracked_dirty must be boolean")
    _validate_source_revision(revision, source["fingerprint"])

    current_source = _current_source_provenance()
    # An artifact-only follow-up commit legitimately changes HEAD without
    # changing any fingerprinted runtime source.  Keep the measured full SHA
    # as provenance, but bind validity to content and relevant dirty state.
    for key in ("fingerprint", "fingerprint_scope", "tracked_dirty"):
        if source.get(key) != current_source.get(key):
            raise ValueError(
                f"provenance.source.{key} does not match the current workspace"
            )

    workload = provenance.get("workload")
    if not isinstance(workload, dict):
        raise ValueError("provenance.workload must be a mapping")
    repeats = _require_positive_integer(workload, "repeats", "provenance.workload.repeats")
    ordinary = result.get("ordinary_chart")
    ordinary_point_count = (
        ordinary.get("point_count") if isinstance(ordinary, dict) else None
    )
    expected_workload = _workload_provenance(
        result.get("point_count"), ordinary_point_count, repeats
    )
    if workload != expected_workload:
        raise ValueError("provenance.workload does not match the benchmark workload")
    for key, label in (
        ("raw_repetitions", "raw_repetitions"),
        ("ordinary_chart", "ordinary_chart.raw_repetitions"),
    ):
        if key == "ordinary_chart":
            values = ordinary.get("raw_repetitions") if isinstance(ordinary, dict) else None
        else:
            values = result.get(key)
        if values is not None and (
            not isinstance(values, list) or len(values) != repeats
        ):
            raise ValueError(f"{label} must contain exactly {repeats} repeats")
    return repeats


def _require_worker_repetition(entry: object, index: int, label: str) -> dict:
    if not isinstance(entry, dict):
        raise ValueError(f"{label}[{index}] must be a mapping")
    for key in (
        "arrow_payload_bytes",
        "external_html_bytes",
        "legacy_renderer_preparation_seconds",
        "legacy_renderer_total_seconds",
        "payload_bytes",
        "peak_rss_mb",
        "plotly_construction_seconds",
        "viewport_warm_ms",
    ):
        if key not in entry:
            raise ValueError(f"{label}[{index}] must contain {key}")
    return entry


def _validated_worker_repetitions(
    repetitions: object, repeats: int, label: str
) -> list[dict]:
    if not isinstance(repetitions, list) or len(repetitions) != repeats:
        raise ValueError(f"{label} must contain exactly {repeats} repeats")
    for index, entry in enumerate(repetitions):
        _require_worker_repetition(entry, index, label)
    return repetitions


def _raw_floats(repetitions: list[dict], key: str, label: str) -> list[float]:
    return [
        _require_nonnegative_number(
            repetition, key, f"{label}[{index}].{key}"
        )
        for index, repetition in enumerate(repetitions)
    ]


def _raw_ints(repetitions: list[dict], key: str, label: str) -> set[int]:
    return {
        _require_positive_integer(
            repetition, key, f"{label}[{index}].{key}"
        )
        for index, repetition in enumerate(repetitions)
    }


def _validate_summary_against_raw(
    summary: object, raw_values: list[float], label: str
) -> None:
    if not isinstance(summary, dict):
        raise ValueError(f"{label} must be a mapping")
    expected = summarize(raw_values)
    for field in ("median_seconds", "p95_seconds"):
        observed = _require_nonnegative_number(
            summary, field, f"{label}.{field}"
        )
        if not math.isclose(
            observed, expected[field], rel_tol=1e-12, abs_tol=1e-12
        ):
            raise ValueError(f"{label}.{field} does not match raw repetitions")


def _validate_viewport_against_raw(
    viewport: object, repetitions: list[dict], label: str
) -> None:
    if not isinstance(viewport, dict):
        raise ValueError("viewport_warm must be a mapping")
    samples: list[float] = []
    for index, repetition in enumerate(repetitions):
        values = repetition.get("viewport_warm_ms")
        if not isinstance(values, list) or not values:
            raise ValueError(
                f"{label}[{index}].viewport_warm_ms must be a non-empty list"
            )
        for sample_index, value in enumerate(values):
            samples.append(
                _require_nonnegative_number(
                    {"value": value},
                    "value",
                    f"{label}[{index}].viewport_warm_ms[{sample_index}]",
                )
            )
    if not samples:
        raise ValueError(f"{label} viewport_warm_ms produced no samples")
    expected = {
        "median_ms": percentile(samples, 50),
        "p95_ms": percentile(samples, 95),
    }
    for field in ("median_ms", "p95_ms"):
        observed = _require_nonnegative_number(
            viewport, field, f"viewport_warm.{field}"
        )
        if not math.isclose(
            observed, expected[field], rel_tol=1e-12, abs_tol=1e-12
        ):
            raise ValueError(
                f"viewport_warm.{field} does not match raw repetitions"
            )


def _validate_candidate_aggregates(result: dict, repeats: int) -> None:
    """Recompute every persisted aggregate from raw worker repetitions."""
    raw = _validated_worker_repetitions(
        result.get("raw_repetitions"), repeats, "raw_repetitions"
    )

    expected_point_count = result.get("point_count")
    for index, repetition in enumerate(raw):
        if "point_count" in repetition:
            observed = _require_positive_integer(
                repetition,
                "point_count",
                f"raw_repetitions[{index}].point_count",
            )
            if observed != expected_point_count:
                raise ValueError(
                    f"raw_repetitions[{index}].point_count does not match workload"
                )

    for key in ("payload_bytes", "arrow_payload_bytes", "external_html_bytes"):
        if key not in result:
            raise ValueError(f"{key} is missing")
        raw_values = _raw_ints(raw, key, "raw_repetitions")
        if len(raw_values) != 1:
            raise ValueError(
                f"{key} values are not identical across raw repetitions"
            )
        top_value = _require_positive_integer(result, key, key)
        if top_value != raw_values.pop():
            raise ValueError(f"{key} does not match raw repetitions")

    peak_rss_values = _raw_floats(raw, "peak_rss_mb", "raw_repetitions")
    expected_peak_rss = max(peak_rss_values)
    observed_peak_rss = _require_nonnegative_number(
        result, "peak_rss_mb", "peak_rss_mb"
    )
    if not math.isclose(
        observed_peak_rss, expected_peak_rss, rel_tol=1e-12, abs_tol=1e-12
    ):
        raise ValueError("peak_rss_mb does not match raw repetitions")

    _validate_summary_against_raw(
        result.get("scene_compile"),
        _raw_floats(raw, "legacy_renderer_preparation_seconds", "raw_repetitions"),
        "scene_compile",
    )
    _validate_summary_against_raw(
        result.get("legacy_renderer_preparation"),
        _raw_floats(raw, "legacy_renderer_preparation_seconds", "raw_repetitions"),
        "legacy_renderer_preparation",
    )
    _validate_summary_against_raw(
        result.get("plotly_construction"),
        _raw_floats(raw, "plotly_construction_seconds", "raw_repetitions"),
        "plotly_construction",
    )
    _validate_summary_against_raw(
        result.get("legacy_renderer_total"),
        _raw_floats(raw, "legacy_renderer_total_seconds", "raw_repetitions"),
        "legacy_renderer_total",
    )

    browser = result.get("browser")
    if isinstance(browser, dict) and browser.get("status") == "measured":
        arrow_payload = result.get("arrow_payload_bytes")
        if arrow_payload is not None and browser.get(
            "arrow_payload_bytes"
        ) != arrow_payload:
            raise ValueError(
                "browser.arrow_payload_bytes does not match raw repetitions"
            )

    if "viewport_warm" in result:
        _validate_viewport_against_raw(
            result["viewport_warm"], raw, "raw_repetitions"
        )

    ordinary = result.get("ordinary_chart")
    if isinstance(ordinary, dict):
        expected_ordinary_points = (
            result.get("provenance", {}).get("workload", {}).get(
                "ordinary_point_count"
            )
        )
        if (
            expected_ordinary_points is not None
            and ordinary.get("point_count") != expected_ordinary_points
        ):
            raise ValueError(
                "ordinary_chart.point_count does not match workload"
            )
        ordinary_raw = _validated_worker_repetitions(
            ordinary.get("raw_repetitions"),
            repeats,
            "ordinary_chart.raw_repetitions",
        )
        for index, repetition in enumerate(ordinary_raw):
            if "point_count" in repetition:
                observed = _require_positive_integer(
                    repetition,
                    "point_count",
                    f"ordinary_chart.raw_repetitions[{index}].point_count",
                )
                if observed != expected_ordinary_points:
                    raise ValueError(
                        f"ordinary_chart.raw_repetitions[{index}].point_count "
                        "does not match workload"
                    )
        _validate_summary_against_raw(
            ordinary,
            _raw_floats(
                ordinary_raw,
                "legacy_renderer_total_seconds",
                "ordinary_chart.raw_repetitions",
            ),
            "ordinary_chart",
        )


def _validate_legacy_provenance(result: dict) -> None:
    provenance = result.get("provenance")
    if not isinstance(provenance, dict) or set(provenance) != set(
        _LEGACY_MEASUREMENT_KINDS
    ):
        raise ValueError(
            "provenance must contain dense_workload and ordinary_chart"
        )
    for segment, measurement_kind in _LEGACY_MEASUREMENT_KINDS.items():
        evidence = provenance.get(segment)
        if not isinstance(evidence, dict):
            raise ValueError(f"provenance.{segment} must be a mapping")
        if evidence.get("measurement_kind") != measurement_kind:
            raise ValueError(
                f"provenance.{segment}.measurement_kind is not recognized"
            )
        if not _is_full_git_revision(evidence.get("revision")):
            raise ValueError(
                f"provenance.{segment}.revision must be a full git revision"
            )
        captured_at = evidence.get("captured_at_utc")
        try:
            parsed = datetime.fromisoformat(captured_at)
        except (TypeError, ValueError):
            parsed = None
        if parsed is None or parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(
                f"provenance.{segment}.captured_at_utc must be timezone-aware ISO time"
            )


def _require_raw_repeats(
    mapping: dict,
    key: str,
    label: str,
    repeats: int,
) -> list[float]:
    values = mapping.get(key)
    if not isinstance(values, list) or len(values) != repeats:
        raise ValueError(f"{label} must contain exactly {repeats} repeats")
    return [
        _require_nonnegative_number({"value": value}, "value", label)
        for value in values
    ]


def _require_nonempty_browser_repeats(
    mapping: dict,
    key: str,
    label: str,
) -> list[float]:
    values = mapping.get(key)
    if not isinstance(values, list) or not values:
        raise ValueError(f"{label} must contain at least one repeat")
    return [
        _require_nonnegative_number({"value": value}, "value", label)
        for value in values
    ]


def _validate_browser_series(
    series: object,
    label: str,
    required_keys: tuple[str, ...],
    expected_completion_signal: str | None = None,
) -> list[float]:
    if not isinstance(series, dict):
        raise ValueError(f"{label} must be a mapping")
    missing = set(required_keys) - series.keys()
    if missing:
        formatted = ", ".join(sorted(f"{label}.{key}" for key in missing))
        raise ValueError(f"{label} missing keys: {formatted}")

    completion_signal = series.get("completion_signal")
    if completion_signal not in _BROWSER_COMPLETION_SIGNALS:
        raise ValueError(f"{label}.completion_signal is missing or unknown")
    if (
        expected_completion_signal is not None
        and completion_signal != expected_completion_signal
    ):
        raise ValueError(
            f"{label}.completion_signal must be {expected_completion_signal}"
        )

    raw_cold = _require_nonempty_browser_repeats(
        series, "raw_cold_repeats_ms", f"{label}.raw_cold_repeats_ms"
    )
    raw_warm = _require_nonempty_browser_repeats(
        series, "raw_warm_repeats_ms", f"{label}.raw_warm_repeats_ms"
    )

    cold_start = _require_nonnegative_number(
        series, "cold_start_ms", f"{label}.cold_start_ms"
    )
    if not math.isclose(cold_start, raw_cold[0]):
        raise ValueError(
            f"{label}.cold_start_ms must be the first raw cold measurement"
        )
    if cold_start in raw_warm:
        raise ValueError(
            f"{label}.cold_start_ms must not be present in raw_warm_repeats_ms"
        )

    cold_median = _require_nonnegative_number(
        series, "cold_start_median_ms", f"{label}.cold_start_median_ms"
    )
    cold_p95 = _require_nonnegative_number(
        series, "cold_start_p95_ms", f"{label}.cold_start_p95_ms"
    )
    if cold_p95 < cold_median:
        raise ValueError(
            f"{label}.cold_start_p95_ms must be at least cold_start_median_ms"
        )
    if not math.isclose(cold_median, percentile(raw_cold, 50)) or not math.isclose(
        cold_p95, percentile(raw_cold, 95)
    ):
        raise ValueError(f"{label} cold summary timings do not match raw_cold_repeats_ms")

    median = _require_nonnegative_number(
        series, "complete_render_median_ms", f"{label}.complete_render_median_ms"
    )
    p95 = _require_nonnegative_number(
        series, "complete_render_p95_ms", f"{label}.complete_render_p95_ms"
    )
    if p95 < median:
        raise ValueError(
            f"{label}.complete_render_p95_ms must be at least complete_render_median_ms"
        )
    if not math.isclose(median, percentile(raw_warm, 50)) or not math.isclose(
        p95, percentile(raw_warm, 95)
    ):
        raise ValueError(f"{label} summary timings do not match raw_warm_repeats_ms")

    all_navigation = series.get("all_navigation_timings")
    if isinstance(all_navigation, list):
        if not all_navigation:
            raise ValueError(f"{label}.all_navigation_timings must not be empty")
        for index, entry in enumerate(all_navigation):
            if not isinstance(entry, dict):
                raise ValueError(
                    f"{label}.all_navigation_timings[{index}] must be a mapping"
                )
            entry_signal = entry.get("completion_signal")
            if entry_signal not in _BROWSER_COMPLETION_SIGNALS:
                raise ValueError(
                    f"{label}.all_navigation_timings[{index}] has an unknown "
                    "completion signal"
                )
            if (
                expected_completion_signal is not None
                and entry_signal != expected_completion_signal
            ):
                raise ValueError(
                    f"{label}.all_navigation_timings[{index}] must use "
                    f"{expected_completion_signal}"
                )
            nav = entry.get("navigation_timings")
            if not isinstance(nav, list) or not nav:
                raise ValueError(
                    f"{label}.all_navigation_timings[{index}].navigation_timings "
                    "must be a non-empty list"
                )
            for nav_index, timing in enumerate(nav):
                if not isinstance(timing, dict) or not all(
                    math.isfinite(timing.get(field, float("nan")))
                    for field in ("startTime", "duration", "domComplete", "loadEventEnd", "responseEnd")
                ):
                    raise ValueError(
                        f"{label}.all_navigation_timings[{index}]"
                        f".navigation_timings[{nav_index}] is not finite"
                    )

    all_signals = series.get("all_completion_signals")
    if isinstance(all_signals, list):
        if not all_signals:
            raise ValueError(f"{label}.all_completion_signals must not be empty")
        for index, signal in enumerate(all_signals):
            if signal not in _BROWSER_COMPLETION_SIGNALS:
                raise ValueError(
                    f"{label}.all_completion_signals[{index}] is an unknown signal"
                )
            if (
                expected_completion_signal is not None
                and signal != expected_completion_signal
            ):
                raise ValueError(
                    f"{label}.all_completion_signals[{index}] must be "
                    f"{expected_completion_signal}"
                )
        if isinstance(all_navigation, list):
            navigation_signals = [
                entry["completion_signal"] for entry in all_navigation
            ]
            if all_signals != navigation_signals:
                raise ValueError(
                    f"{label}.all_completion_signals must match "
                    "all_navigation_timings"
                )

    return raw_warm


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

    _require_nonempty_string(browser, "engine", "browser.engine")
    _require_nonempty_string(browser, "engine_version", "browser.engine_version")
    scene_hash = _require_scene_hash(browser, "scene_hash", "browser.scene_hash")
    _require_positive_integer(
        browser, "arrow_payload_bytes", "browser.arrow_payload_bytes"
    )

    _validate_browser_series(
        browser,
        "browser",
        (
            "all_completion_signals",
            "all_navigation_timings",
            "cold_start_ms",
            "cold_start_median_ms",
            "cold_start_p95_ms",
            "completion_signal",
            "complete_render_median_ms",
            "complete_render_p95_ms",
            "raw_cold_repeats_ms",
            "raw_warm_repeats_ms",
            "scene_hash",
            "source_kind",
        ),
        expected_completion_signal="starplot-product-promise",
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
    _validate_browser_series(
        legacy,
        "browser.legacy_same_scene",
        (
            "all_completion_signals",
            "all_navigation_timings",
            "cold_start_ms",
            "cold_start_median_ms",
            "cold_start_p95_ms",
            "completion_signal",
            "complete_render_median_ms",
            "complete_render_p95_ms",
            "raw_cold_repeats_ms",
            "raw_warm_repeats_ms",
            "scene_hash",
            "source_kind",
        ),
        expected_completion_signal="plotly-fallback",
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
    _validate_legacy_provenance(result)


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
    repeats = _validate_candidate_provenance(result)
    _validate_primary_browser(result.get("browser"))
    _validate_candidate_aggregates(result, repeats)
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
            completion_signals = evidence.get("all_completion_signals")
            if (
                not isinstance(completion_signals, list)
                or len(completion_signals) != repeats
                or any(
                    signal != "starplot-product-promise"
                    for signal in completion_signals
                )
            ):
                raise ValueError(
                    f"plot_type_coverage browser {name!r} requires "
                    "starplot-product-promise for every repeat"
                )
            raw_repeats = _require_nonempty_browser_repeats(
                evidence,
                "raw_render_repeats_ms",
                f"plot_type_coverage browser {name!r}.raw_render_repeats_ms",
            )
            if len(raw_repeats) != repeats:
                raise ValueError(
                    f"plot_type_coverage browser {name!r} requires exactly "
                    f"{repeats} raw render repeats"
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
            if not math.isclose(
                evidence["complete_render_median_ms"], percentile(raw_repeats, 50)
            ) or not math.isclose(
                evidence["complete_render_p95_ms"], percentile(raw_repeats, 95)
            ):
                raise ValueError(
                    f"plot_type_coverage browser {name!r} summary timings do not "
                    "match raw render repeats"
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

    if after["provenance"]["source"]["tracked_dirty"]:
        return [
            "candidate source provenance is tracked-dirty; regenerate from a clean commit"
        ]

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
    maximum_gate(
        "browser_cold_start",
        "browser.cold_start_ms",
        PERFORMANCE_GATES["browser_cold_start_ms_max"],
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
        "point_count": point_count,
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
    scene_html = exported.html_path.read_text(encoding="utf-8")
    match = re.search(
        r'<script src="[^"]*plotly[^"]*"[^>]* integrity="[^"]+"[^>]*></script>',
        scene_html,
    )
    if match is None:
        raise RuntimeError("external fixture is missing its pinned Plotly library")
    figure_html = PlotlySceneAdapter().render(scene).to_html(
        include_plotlyjs=False,
        full_html=True,
    )
    if "</head>" not in figure_html:
        raise RuntimeError("legacy Plotly fixture has no HTML head")
    (output_directory / "legacy.html").write_text(
        figure_html.replace("</head>", f"{match.group(0)}</head>", 1),
        encoding="utf-8",
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
    from starplot import __version__ as source_starplot_version

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
        "starplot": source_starplot_version,
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


def _measure_browser_page(page, uri: str, timeout_ms: int) -> dict:
    """Measure in-page navigation through the product's final-paint contract.

    The returned value is a dict tied to the page's own clock and navigation
    timing: ``elapsed_ms`` is the product render-paint completion,
    ``completion_signal`` records whether the Starplot product promise or the
    Plotly fallback produced the sample, and ``navigation_timings`` holds the
    ``PerformanceNavigationTiming`` entries available at completion.
    """
    page.add_init_script(_PLOTLY_COMPLETION_INIT_SCRIPT)
    page.goto(uri, wait_until="load", timeout=timeout_ms)
    page.wait_for_function(
        """() => {
          const state = window.__starplotBenchmark;
          if (state === undefined || state === null) return false;
          if (state.starplotCalls > 0) {
            return state.starplotCompletedAt !== null;
          }
          return state.completionSignal === "plotly-fallback";
        }""",
        timeout=timeout_ms,
    )
    sample = page.evaluate(
        """() => {
          const state = window.__starplotBenchmark;
          return {
            completion_signal: state.completionSignal,
            elapsed_ms: state.starplotCompletedAt ?? state.completedAt,
            navigation_timings: state.navigationTimings || []
          };
        }"""
    )
    if not isinstance(sample, dict):
        raise RuntimeError("browser did not return a completion sample")
    completion_signal = sample.get("completion_signal")
    if completion_signal not in _BROWSER_COMPLETION_SIGNALS:
        raise RuntimeError(
            f"browser reported unknown completion signal: {completion_signal!r}"
        )
    elapsed_ms = sample.get("elapsed_ms")
    if (
        isinstance(elapsed_ms, bool)
        or not isinstance(elapsed_ms, int | float)
        or not math.isfinite(elapsed_ms)
        or elapsed_ms < 0
    ):
        raise RuntimeError("browser did not report a finite completion timestamp")
    navigation = sample.get("navigation_timings")
    if (
        not isinstance(navigation, list)
        or not navigation
        or not all(
            isinstance(entry, dict)
            and all(
                math.isfinite(entry.get(field, float("nan")))
                for field in ("startTime", "duration", "domComplete", "loadEventEnd", "responseEnd")
            )
            for entry in navigation
        )
    ):
        raise RuntimeError("browser did not report finite PerformanceNavigationTiming")
    first_navigation = navigation[0]
    if elapsed_ms < first_navigation.get("loadEventEnd", 0):
        raise RuntimeError(
            "product completion timestamp precedes the navigation load event"
        )
    sample["elapsed_ms"] = float(elapsed_ms)
    return sample


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
    completion_signals = {
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
                                sample = _measure_browser_page(
                                    page,
                                    str(fixture["source_url"]),
                                    _BROWSER_TIMEOUT_MS,
                                )
                            finally:
                                page.close()
                            elapsed_ms = sample["elapsed_ms"]
                            completion_signal = sample["completion_signal"]
                            if completion_signal != "starplot-product-promise":
                                raise RuntimeError(
                                    f"{name} diagnostic did not complete through the "
                                    "Starplot product promise"
                                )
                            print(
                                f"Browser {name} diagnostic {label}: complete "
                                f"({elapsed_ms:.3f} ms)",
                                flush=True,
                            )
                            if iteration:
                                measurements[name].append(elapsed_ms)
                                completion_signals[name].append(completion_signal)
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
                "all_completion_signals": completion_signals[name],
                "arrow_payload_bytes": int(fixtures[name]["arrow_payload_bytes"]),
                "complete_render_median_ms": percentile(values, 50),
                "complete_render_p95_ms": percentile(values, 95),
                "raw_render_repeats_ms": list(values),
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
    """Measure a real external Arrow bundle over the supported HTTP server.

    Cold measurements use a fresh browser context for every sample, and at
    least ``_BROWSER_COLD_SAMPLES`` are collected for each series, with the
    external/legacy first-load order alternating so that any browser-level
    startup asymmetry is averaged.  Warm repeats are measured separately in a
    persistent context and never include the cold measurement.
    """
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
    cold_measurements: list[float] = []
    legacy_cold_measurements: list[float] = []
    all_navigation_timings: list[dict] = []
    all_completion_signals: list[str] = []

    def _collect_sample(
        page,
        item: dict,
        kind: str,
    ) -> float:
        sample = _measure_browser_page(
            page, item["url"], _BROWSER_TIMEOUT_MS,
        )
        elapsed_ms = sample["elapsed_ms"]
        all_navigation_timings.append({
            "kind": kind,
            "series": item["key"],
            "completion_signal": sample["completion_signal"],
            "navigation_timings": sample["navigation_timings"],
        })
        all_completion_signals.append(sample["completion_signal"])
        print(
            f"Browser {item['name']} {kind}: complete ({elapsed_ms:.3f} ms)",
            flush=True,
        )
        return elapsed_ms

    try:
        with _external_browser_fixture(
            point_count, fixture_timeout_seconds
        ) as fixture, sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            try:
                browser_version = browser.version
                series = [
                    {
                        "key": "external",
                        "name": "external Arrow",
                        "url": fixture["source_url"],
                    },
                    {
                        "key": "legacy",
                        "name": "legacy direct",
                        "url": fixture["legacy_source_url"],
                    },
                ]
                for cold_index in range(_BROWSER_COLD_SAMPLES):
                    label = f"cold start {cold_index + 1}/{_BROWSER_COLD_SAMPLES}"
                    ordered_series = (
                        series
                        if cold_index % 2 == 0
                        else list(reversed(series))
                    )
                    for item in ordered_series:
                        print(f"Browser {item['name']} {label}: starting", flush=True)
                        context = browser.new_context(
                            viewport={"width": 1000, "height": 500}
                        )
                        try:
                            page = context.new_page()
                            try:
                                cold_ms = _collect_sample(page, item, label)
                            finally:
                                page.close()
                            if item["key"] == "external":
                                cold_measurements.append(cold_ms)
                            else:
                                legacy_cold_measurements.append(cold_ms)
                        finally:
                            context.close()

                contexts: list[object] = []
                try:
                    for item in series:
                        context = browser.new_context(
                            viewport={"width": 1000, "height": 500}
                        )
                        contexts.append(context)
                        item["context"] = context
                    for iteration in range(1, repeats + 1):
                        ordered_series = (
                            series
                            if iteration % 2 == 0
                            else list(reversed(series))
                        )
                        for item in ordered_series:
                            label = f"warm repeat {iteration}/{repeats}"
                            print(f"Browser {item['name']} {label}: starting", flush=True)
                            page = item["context"].new_page()
                            try:
                                warm_ms = _collect_sample(page, item, label)
                            finally:
                                page.close()
                            if item["key"] == "external":
                                measurements.append(warm_ms)
                            else:
                                legacy_measurements.append(warm_ms)
                finally:
                    for context in reversed(contexts):
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

    def _series_completion_signal(signals: list[str]) -> str:
        if not signals:
            return ""
        if all(signal == signals[0] for signal in signals):
            return signals[0]
        # Mixed signals are still auditable as long as every value is known.
        return ";".join(sorted(set(signals)))

    external_navigation = [
        entry for entry in all_navigation_timings if entry["series"] == "external"
    ]
    external_signals = [entry["completion_signal"] for entry in external_navigation]
    legacy_navigation = [
        entry for entry in all_navigation_timings if entry["series"] == "legacy"
    ]
    legacy_signals = [entry["completion_signal"] for entry in legacy_navigation]

    return {
        "all_completion_signals": external_signals,
        "all_navigation_timings": external_navigation,
        "complete_render_median_ms": percentile(measurements, 50),
        "complete_render_p95_ms": percentile(measurements, 95),
        "completion_signal": _series_completion_signal(external_signals),
        "cold_start_ms": cold_measurements[0],
        "cold_start_median_ms": percentile(cold_measurements, 50),
        "cold_start_p95_ms": percentile(cold_measurements, 95),
        "engine": "chromium",
        "engine_version": browser_version,
        "legacy_same_scene": {
            "all_completion_signals": legacy_signals,
            "all_navigation_timings": legacy_navigation,
            "cold_start_ms": legacy_cold_measurements[0],
            "cold_start_median_ms": percentile(legacy_cold_measurements, 50),
            "cold_start_p95_ms": percentile(legacy_cold_measurements, 95),
            "complete_render_median_ms": percentile(legacy_measurements, 50),
            "complete_render_p95_ms": percentile(legacy_measurements, 95),
            "completion_signal": _series_completion_signal(legacy_signals),
            "raw_cold_repeats_ms": list(legacy_cold_measurements),
            "raw_warm_repeats_ms": list(legacy_measurements),
            "scene_hash": fixture["scene_hash"],
            "source_kind": fixture["legacy_source_kind"],
        },
        "raw_cold_repeats_ms": list(cold_measurements),
        "raw_warm_repeats_ms": list(measurements),
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
        "provenance": {
            "source": _current_source_provenance(),
            "workload": _workload_provenance(point_count, ordinary_points, repeats),
        },
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
