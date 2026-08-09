import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from benchmarks import interactive_scene_pipeline as benchmark
from benchmarks.interactive_scene_pipeline import validate_result


ENVIRONMENT = {
    "browser": "chromium 150",
    "captured_at_utc": "2026-07-16T00:00:00+00:00",
    "cpu": "test-cpu",
    "cpu_count": 8,
    "host_fingerprint": "0123456789abcdef",
    "machine": "x86_64",
    "numpy": "2.2.2",
    "os": "test-os",
    "playwright": "1.57.0",
    "plotly": "6.5.2",
    "pyarrow": "20.0.0",
    "python": "3.13.2",
    "shapely": "2.1.1",
    "starplot": "0.19.5",
}

TEST_SOURCE_PROVENANCE = {
    "fingerprint": f"sha256:{'c' * 64}",
    "fingerprint_scope": [
        "benchmarks/interactive_scene_pipeline.py",
        "pyproject.toml",
        "src/starplot/** (tracked files)",
    ],
    "git_revision": "d" * 40,
    "tracked_dirty": False,
}


@pytest.fixture(autouse=True)
def stable_current_source_provenance(monkeypatch):
    if hasattr(benchmark, "_current_source_provenance"):
        monkeypatch.setattr(
            benchmark,
            "_current_source_provenance",
            lambda: dict(TEST_SOURCE_PROVENANCE),
        )


def candidate_provenance(
    *, point_count=100, ordinary_point_count=10, repeats=2
):
    workload = {
        "ordinary_point_count": ordinary_point_count,
        "point_count": point_count,
        "repeats": repeats,
        "seed": benchmark._SEED,
    }
    encoded = json.dumps(workload, sort_keys=True, separators=(",", ":")).encode()
    return {
        "source": dict(TEST_SOURCE_PROVENANCE),
        "workload": {
            **workload,
            "fingerprint": f"sha256:{hashlib.sha256(encoded).hexdigest()}",
        },
    }


def legacy_provenance():
    revision = "23e3358214e15c444e0da0651a5f5cb3ab0268fd"
    return {
        "dense_workload": {
            "captured_at_utc": "2026-07-16T17:02:21.772099+00:00",
            "measurement_kind": "historical-pre-arrow-release-baseline",
            "revision": revision,
        },
        "ordinary_chart": {
            "captured_at_utc": "2026-08-09T12:58:52.581770+00:00",
            "measurement_kind": "isolated-control-backfill",
            "revision": revision,
        },
    }


def complete_plot_type_coverage():
    return {
        "semantics": "real recording coverage",
        "browser": {
            "semantics": "external Arrow browser diagnostics",
            "source_kind": "external-arrow-http",
            "status": "measured",
            "plot_types": {
                name: {
                    "arrow_payload_bytes": 100,
                    "complete_render_median_ms": 10.0,
                    "complete_render_p95_ms": 12.0,
                    "scene_hash": f"sha256:{name}",
                }
                for name in ("map", "horizon", "zenith", "optic")
            },
        },
        "plot_types": {
            name: {
                "plot_kind": name,
                "recorded_command_count": 1,
                "recorded_command_kinds": ["scatter"],
                "scene_layer_count": 1,
                "rendered_primitive_count": 1,
                "scene_compile_seconds": 0.01,
                "plotly_render_seconds": 0.02,
            }
            for name in ("map", "horizon", "zenith", "optic")
        },
    }


def complete_result():
    summary = {"median_seconds": 1.0, "p95_seconds": 1.2}
    scene_hash = f"sha256:{'a' * 64}"
    return {
        "arrow_payload_bytes": 100,
        "artifact_role": "candidate",
        "browser": {
            "arrow_payload_bytes": 100,
            "complete_render_median_ms": 100.0,
            "complete_render_p95_ms": 118.0,
            "completion_signal": "render promise plus final paint",
            "cold_start_ms": 4000.0,
            "engine": "chromium",
            "engine_version": "150.0",
            "legacy_same_scene": {
                "complete_render_median_ms": 90.0,
                "complete_render_p95_ms": 99.0,
                "cold_start_ms": 4500.0,
                "raw_warm_repeats_ms": [80.0, 100.0],
                "scene_hash": scene_hash,
                "source_kind": "direct-plotly-same-scene-http",
            },
            "raw_warm_repeats_ms": [80.0, 120.0],
            "scene_hash": scene_hash,
            "source_kind": "external-arrow-http",
            "status": "measured",
        },
        "environment": ENVIRONMENT,
        "external_html_bytes": 100,
        "legacy_renderer_preparation": summary,
        "legacy_renderer_total": summary,
        "ordinary_chart": {**summary, "point_count": 10},
        "payload_bytes": 1000,
        "peak_rss_mb": 10.0,
        "plot_type_coverage": complete_plot_type_coverage(),
        "plotly_construction": summary,
        "point_count": 100,
        "provenance": candidate_provenance(),
        "scene_compile": {
            **summary,
            "semantics": "compatibility alias for legacy_renderer_total",
        },
        "schema_version": benchmark.BENCHMARK_SCHEMA_VERSION,
        "viewport_warm": {"median_ms": 10.0, "p95_ms": 12.0},
    }


def complete_browser_result(*, repeats=2):
    browser = complete_result()["browser"]
    browser["raw_warm_repeats_ms"] = [100.0] * repeats
    browser["complete_render_median_ms"] = 100.0
    browser["complete_render_p95_ms"] = 100.0
    legacy = browser["legacy_same_scene"]
    legacy["raw_warm_repeats_ms"] = [90.0] * repeats
    legacy["complete_render_median_ms"] = 90.0
    legacy["complete_render_p95_ms"] = 90.0
    return browser


def complete_legacy_baseline():
    summary = {"median_seconds": 1.0, "p95_seconds": 1.2}
    return {
        "artifact_role": "legacy_baseline",
        "browser": {
            "reason": "candidate uses a paired same-scene browser fixture",
            "source_kind": "legacy-renderer-revision",
            "status": "not_applicable",
        },
        "environment": ENVIRONMENT,
        "ordinary_chart": {**summary, "point_count": 10},
        "peak_rss_mb": 10.0,
        "point_count": 100,
        "provenance": legacy_provenance(),
        "scene_compile": summary,
        "schema_version": benchmark.BENCHMARK_SCHEMA_VERSION,
    }


def test_benchmark_result_schema_rejects_missing_metrics():
    with pytest.raises(ValueError, match="scene_compile"):
        validate_result({"environment": {}, "point_count": 100})


def test_public_benchmark_result_schema_is_the_brief_six_key_contract():
    assert benchmark.REQUIRED_RESULT_KEYS == {
        "environment",
        "point_count",
        "scene_compile",
        "peak_rss_mb",
        "payload_bytes",
        "browser",
    }
    validate_result(
        {
            "environment": {"python": "3.12", "platform": "test"},
            "point_count": 100,
            "scene_compile": {"median_seconds": 1.0, "p95_seconds": 1.2},
            "peak_rss_mb": 10.0,
            "payload_bytes": 1000,
            "browser": {"complete_render_median_ms": 100.0},
        }
    )


def test_strict_artifact_schema_accepts_complete_result():
    benchmark.validate_benchmark_artifact(complete_result())


@pytest.mark.parametrize("key", ["artifact_role", "schema_version"])
def test_strict_artifact_schema_requires_explicit_role_and_version(key):
    result = complete_result()
    del result[key]

    with pytest.raises(ValueError, match=key):
        benchmark.validate_benchmark_artifact(result)


def test_strict_artifact_schema_accepts_minimal_legacy_baseline_without_coverage():
    benchmark.validate_benchmark_artifact(complete_legacy_baseline())


def test_persisted_legacy_baseline_has_strict_real_provenance():
    path = (
        benchmark._REPOSITORY_ROOT
        / "benchmarks/baselines/interactive_scene_pre_arrow.json"
    )

    benchmark.validate_benchmark_artifact(json.loads(path.read_text()))


def test_candidate_schema_rejects_missing_provenance():
    result = complete_result()
    del result["provenance"]

    with pytest.raises(ValueError, match="provenance"):
        benchmark.validate_benchmark_artifact(result)


def test_candidate_schema_rejects_tampered_source_fingerprint(monkeypatch):
    result = complete_result()
    result["provenance"]["source"]["fingerprint"] = f"sha256:{'e' * 64}"

    with pytest.raises(ValueError, match="source.fingerprint"):
        benchmark.validate_benchmark_artifact(result)


def test_candidate_schema_requires_full_git_revision():
    result = complete_result()
    result["provenance"]["source"]["git_revision"] = "4ec7f7e"

    with pytest.raises(ValueError, match="git_revision"):
        benchmark.validate_benchmark_artifact(result)


def test_compare_results_rejects_dirty_candidate_source(monkeypatch):
    before = complete_legacy_baseline()
    after = complete_result()
    dirty_source = {**TEST_SOURCE_PROVENANCE, "tracked_dirty": True}
    after["provenance"]["source"] = dirty_source
    monkeypatch.setattr(benchmark, "_current_source_provenance", lambda: dirty_source)

    assert benchmark.compare_results(before, after) == [
        "candidate source provenance is tracked-dirty; regenerate from a clean commit"
    ]


def test_compare_results_rejects_stale_candidate_source(monkeypatch):
    before = complete_legacy_baseline()
    after = complete_result()
    current_source = {
        **TEST_SOURCE_PROVENANCE,
        "fingerprint": f"sha256:{'f' * 64}",
    }
    monkeypatch.setattr(
        benchmark, "_current_source_provenance", lambda: current_source
    )

    failures = benchmark.compare_results(before, after)

    assert failures == [
        "candidate artifact schema is invalid: provenance.source.fingerprint does "
        "not match the current workspace"
    ]


def test_candidate_source_revision_may_precede_an_artifact_only_commit(monkeypatch):
    result = complete_result()
    current_source = {
        **TEST_SOURCE_PROVENANCE,
        "git_revision": "e" * 40,
    }
    monkeypatch.setattr(
        benchmark, "_current_source_provenance", lambda: current_source
    )

    benchmark.validate_benchmark_artifact(result)


def test_candidate_schema_rejects_workload_fingerprint_mismatch():
    result = complete_result()
    result["provenance"]["workload"] = candidate_provenance(point_count=101)[
        "workload"
    ]

    with pytest.raises(ValueError, match="workload"):
        benchmark.validate_benchmark_artifact(result)


@pytest.mark.parametrize(
    ("segment", "field", "value", "match"),
    [
        ("dense_workload", "revision", "23e3358", "revision"),
        (
            "dense_workload",
            "captured_at_utc",
            "2026-07-16T17:02:21",
            "captured_at_utc",
        ),
        ("ordinary_chart", "measurement_kind", "unknown", "measurement_kind"),
    ],
)
def test_legacy_schema_rejects_invalid_provenance(segment, field, value, match):
    result = complete_legacy_baseline()
    result["provenance"][segment][field] = value

    with pytest.raises(ValueError, match=match):
        benchmark.validate_benchmark_artifact(result)


def test_source_fingerprint_scope_covers_pipeline_sources_not_artifacts():
    paths = {
        path.relative_to(benchmark._REPOSITORY_ROOT).as_posix()
        for path in benchmark._source_fingerprint_paths()
    }

    assert "benchmarks/interactive_scene_pipeline.py" in paths
    assert "pyproject.toml" in paths
    assert "src/starplot/interactive/web_export.py" in paths
    assert "src/starplot/interactive/assets/starplot-scene-loader.js" in paths
    assert not any(path.startswith("benchmarks/baselines/") for path in paths)


def test_tracked_dirty_ignores_untracked_review_docs_and_baseline_artifacts(
    monkeypatch,
):
    monkeypatch.setattr(
        benchmark,
        "_git_output",
        lambda *args: "?? REVIEW.md\n M benchmarks/baselines/candidate.json\n",
    )

    assert not benchmark._tracked_worktree_dirty()


def test_tracked_dirty_rejects_untracked_runtime_source(monkeypatch):
    monkeypatch.setattr(
        benchmark,
        "_git_output",
        lambda *args: "?? src/starplot/interactive/untracked_runtime.py\n",
    )

    assert benchmark._tracked_worktree_dirty()


def test_tracked_dirty_detects_relevant_tracked_change(monkeypatch):
    monkeypatch.setattr(
        benchmark,
        "_git_output",
        lambda *args: " M src/starplot/interactive/web_export.py\n",
    )

    assert benchmark._tracked_worktree_dirty()


def test_benchmark_result_schema_rejects_missing_environment_versions():
    result = complete_result()
    result["environment"] = {"python": "3.13.2", "platform": "test"}

    with pytest.raises(ValueError, match="pyarrow"):
        benchmark.validate_benchmark_artifact(result)


def test_strict_artifact_schema_rejects_missing_stage_metrics():
    result = complete_result()
    del result["plotly_construction"]

    with pytest.raises(ValueError, match="plotly_construction"):
        benchmark.validate_benchmark_artifact(result)


def test_strict_artifact_schema_rejects_missing_plot_type_evidence():
    result = complete_result()
    del result["plot_type_coverage"]["plot_types"]["optic"]

    with pytest.raises(ValueError, match="cover exactly"):
        benchmark.validate_benchmark_artifact(result)


def test_strict_artifact_schema_rejects_missing_plot_type_browser_evidence():
    result = complete_result()
    del result["plot_type_coverage"]["browser"]["plot_types"]["zenith"]

    with pytest.raises(ValueError, match="browser.*cover exactly"):
        benchmark.validate_benchmark_artifact(result)


@pytest.mark.parametrize(
    ("path", "match"),
    [
        (("status",), "status"),
        (("source_kind",), "source_kind"),
        (("completion_signal",), "completion_signal"),
        (("engine",), "engine"),
        (("engine_version",), "engine_version"),
        (("scene_hash",), "scene_hash"),
        (("arrow_payload_bytes",), "arrow_payload_bytes"),
        (("complete_render_median_ms",), "complete_render_median_ms"),
        (("complete_render_p95_ms",), "complete_render_p95_ms"),
        (("cold_start_ms",), "cold_start_ms"),
        (("raw_warm_repeats_ms",), "raw_warm_repeats_ms"),
        (("legacy_same_scene",), "legacy_same_scene"),
        (
            ("legacy_same_scene", "source_kind"),
            "legacy_same_scene.source_kind",
        ),
        (("legacy_same_scene", "scene_hash"), "legacy_same_scene.scene_hash"),
        (
            ("legacy_same_scene", "complete_render_median_ms"),
            "legacy_same_scene.complete_render_median_ms",
        ),
        (
            ("legacy_same_scene", "complete_render_p95_ms"),
            "legacy_same_scene.complete_render_p95_ms",
        ),
        (("legacy_same_scene", "cold_start_ms"), "legacy_same_scene.cold_start_ms"),
        (
            ("legacy_same_scene", "raw_warm_repeats_ms"),
            "legacy_same_scene.raw_warm_repeats_ms",
        ),
    ],
)
def test_strict_artifact_schema_rejects_incomplete_measured_primary_browser(
    path, match
):
    result = complete_result()
    target = result["browser"]
    for key in path[:-1]:
        target = target[key]
    del target[path[-1]]

    with pytest.raises(ValueError, match=match):
        benchmark.validate_benchmark_artifact(result)


@pytest.mark.parametrize("status", ["playwright_not_installed", "measurement_failed"])
def test_strict_artifact_schema_accepts_structured_unmeasured_primary_browser(status):
    result = complete_result()
    result["browser"] = {
        "complete_render_median_ms": None,
        "complete_render_p95_ms": None,
        "source_kind": "external-arrow-http",
        "status": status,
    }
    if status == "measurement_failed":
        result["browser"]["error"] = "RuntimeError: browser unavailable"

    benchmark.validate_benchmark_artifact(result)


def test_strict_artifact_schema_rejects_nonpositive_primary_arrow_payload():
    result = complete_result()
    result["browser"]["arrow_payload_bytes"] = 0

    with pytest.raises(ValueError, match="arrow_payload_bytes"):
        benchmark.validate_benchmark_artifact(result)


def test_strict_artifact_schema_rejects_nonfinite_primary_browser_timing():
    result = complete_result()
    result["browser"]["complete_render_p95_ms"] = float("nan")

    with pytest.raises(ValueError, match="complete_render_p95_ms"):
        benchmark.validate_benchmark_artifact(result)


def test_strict_artifact_schema_rejects_malformed_primary_scene_hash():
    result = complete_result()
    result["browser"]["scene_hash"] = "sha256:short"
    result["browser"]["legacy_same_scene"]["scene_hash"] = "sha256:short"

    with pytest.raises(ValueError, match="scene_hash"):
        benchmark.validate_benchmark_artifact(result)


def test_strict_artifact_schema_rejects_different_paired_scene_hash():
    result = complete_result()
    result["browser"]["legacy_same_scene"]["scene_hash"] = f"sha256:{'b' * 64}"

    with pytest.raises(ValueError, match="legacy_same_scene.scene_hash"):
        benchmark.validate_benchmark_artifact(result)


def test_strict_artifact_schema_rejects_raw_browser_repeat_count_mismatch():
    result = complete_result()
    result["browser"]["raw_warm_repeats_ms"].pop()

    with pytest.raises(ValueError, match="raw_warm_repeats_ms"):
        benchmark.validate_benchmark_artifact(result)


def test_benchmark_summary_reports_median_and_p95():
    assert benchmark.summarize([1.0, 2.0, 3.0, 4.0]) == {
        "median_seconds": 2.5,
        "p95_seconds": pytest.approx(3.85),
    }


def test_compare_results_reports_every_missed_performance_gate():
    before = complete_legacy_baseline()
    after = complete_result()
    after["scene_compile"] = {"median_seconds": 0.75, "p95_seconds": 0.8}
    after["peak_rss_mb"] = 7.0
    after["arrow_payload_bytes"] = 31 * 1024 * 1024
    after["external_html_bytes"] = 2 * 1024 * 1024
    after["browser"]["raw_warm_repeats_ms"] = [120.0, 6000.0]
    after["browser"]["complete_render_median_ms"] = benchmark.percentile(
        after["browser"]["raw_warm_repeats_ms"], 50
    )
    after["browser"]["complete_render_p95_ms"] = benchmark.percentile(
        after["browser"]["raw_warm_repeats_ms"], 95
    )
    after["browser"]["cold_start_ms"] = 5001.0
    after["ordinary_chart"]["median_seconds"] = 1.2
    after["viewport_warm"] = {"median_ms": 501.0, "p95_ms": 1001.0}

    failures = benchmark.compare_results(before, after)

    assert len(failures) == 10
    assert any("scene_compile" in failure for failure in failures)
    assert any("peak_rss" in failure for failure in failures)
    assert any("arrow_payload" in failure for failure in failures)
    assert any("external_html" in failure for failure in failures)
    assert any("browser_complete" in failure for failure in failures)
    assert any("browser_complete_render_p95" in failure for failure in failures)
    assert any("browser_cold_start" in failure for failure in failures)
    assert any("ordinary_chart" in failure for failure in failures)
    assert any("viewport_warm_median" in failure for failure in failures)
    assert any("viewport_warm_p95" in failure for failure in failures)


def test_compare_results_rejects_point_count_mismatch_before_gate_evaluation():
    before = complete_legacy_baseline()
    after = complete_result()
    after["point_count"] = before["point_count"] + 1
    after["scene_compile"]["median_seconds"] = 100.0

    failures = benchmark.compare_results(before, after)

    assert failures == [
        "point_count differs; benchmark workloads are not comparable (100 != 101)"
    ]


def test_compare_results_rejects_ordinary_workload_mismatch_before_gates():
    before = complete_legacy_baseline()
    after = complete_result()
    after["ordinary_chart"]["point_count"] = 11

    assert benchmark.compare_results(before, after) == [
        "ordinary_chart.point_count differs; benchmark workloads are not "
        "comparable (10 != 11)"
    ]


def test_compare_results_rejects_wrong_artifact_roles_before_gate_evaluation():
    before = complete_result()
    after = complete_result()

    assert benchmark.compare_results(before, after) == [
        "artifact roles are not comparable; expected legacy_baseline -> candidate "
        "but got candidate -> candidate"
    ]


def test_compare_results_rejects_environment_mismatch_before_gate_evaluation():
    before = complete_legacy_baseline()
    after = complete_result()
    after["environment"] = {**ENVIRONMENT, "python": "3.14.0"}

    assert benchmark.compare_results(before, after) == [
        "environment.python differs; benchmark workloads are not comparable "
        "('3.13.2' != '3.14.0')"
    ]


def test_compare_results_rejects_starplot_version_mismatch():
    before = complete_legacy_baseline()
    after = complete_result()
    after["environment"] = {**ENVIRONMENT, "starplot": "forged-release"}

    assert benchmark.compare_results(before, after) == [
        "environment.starplot differs; benchmark workloads are not comparable "
        "('0.19.5' != 'forged-release')"
    ]


def test_browser_gates_separate_transport_overhead_from_absolute_product_budget():
    assert benchmark.PERFORMANCE_GATES["browser_complete_render_ratio_max"] == 1.10
    assert benchmark.PERFORMANCE_GATES["browser_complete_render_p95_ms_max"] == 5000
    assert benchmark.PERFORMANCE_GATES["browser_cold_start_ms_max"] == 5000


def test_compare_results_rejects_host_mismatch_before_gate_evaluation():
    before = complete_legacy_baseline()
    after = complete_result()
    after["environment"] = {**ENVIRONMENT, "host_fingerprint": "other-host"}

    assert benchmark.compare_results(before, after) == [
        "environment.host_fingerprint differs; benchmark workloads are not "
        "comparable ('0123456789abcdef' != 'other-host')"
    ]


def test_compare_results_rejects_unmeasured_metrics():
    before = complete_legacy_baseline()
    after = complete_result()
    del after["arrow_payload_bytes"]
    del after["external_html_bytes"]
    after["ordinary_chart"]["median_seconds"] = None
    del after["viewport_warm"]
    after["plot_type_coverage"]["browser"] = {
        "semantics": "external Arrow browser diagnostics",
        "source_kind": "external-arrow-http",
        "status": "measurement_failed",
    }

    failures = benchmark.compare_results(before, after)

    assert any("arrow_payload_bytes is missing" in failure for failure in failures)
    assert any("external_html_bytes is missing" in failure for failure in failures)
    assert any("ordinary_chart result is missing" in failure for failure in failures)
    assert any("viewport_warm_median is missing" in failure for failure in failures)
    assert any(
        "browser diagnostics are not measured" in failure for failure in failures
    )


def test_compare_results_fails_closed_for_unmeasured_primary_browser():
    before = complete_legacy_baseline()
    after = complete_result()
    after["scene_compile"]["median_seconds"] = 0.4
    after["peak_rss_mb"] = 5.0
    after["browser"] = {
        "complete_render_median_ms": None,
        "complete_render_p95_ms": None,
        "error": "RuntimeError: browser unavailable",
        "source_kind": "external-arrow-http",
        "status": "measurement_failed",
    }

    failures = benchmark.compare_results(before, after)

    assert "browser primary measurement is not measured" in failures


def test_cross_family_browser_timings_remain_diagnostic_only():
    before = complete_legacy_baseline()
    after = complete_result()
    after["scene_compile"]["median_seconds"] = 0.4
    after["peak_rss_mb"] = 5.0
    after["browser"]["raw_warm_repeats_ms"] = [90.0, 90.0]
    after["browser"]["complete_render_median_ms"] = 90.0
    after["browser"]["complete_render_p95_ms"] = 90.0
    for evidence in after["plot_type_coverage"]["browser"]["plot_types"].values():
        evidence["complete_render_median_ms"] = 1_000_000.0
        evidence["complete_render_p95_ms"] = 2_000_000.0

    assert benchmark.compare_results(before, after) == []


@pytest.mark.parametrize(
    ("column", "dtype"),
    [
        ("x", np.dtype(np.float64)),
        ("y", np.dtype(np.float64)),
        ("sizes", np.dtype(np.float64)),
        ("colors", np.dtype("<U7")),
        ("alphas", np.dtype(np.float64)),
    ],
)
def test_scatter_command_columns_are_contiguous_read_only_arrays(column, dtype):
    command = benchmark._build_scatter_command(100)
    values = command.data[column]

    assert isinstance(values, np.ndarray)
    assert values.dtype == dtype
    assert values.flags.c_contiguous
    assert not values.flags.writeable


def test_renderer_fixture_matches_recorded_projection_geometry_contract():
    from starplot.interactive.scene_compiler import SceneCompiler

    command, projection, style = benchmark._renderer_inputs(100)

    assert {
        key: projection[key] for key in ("x_min", "x_max", "y_min", "y_max")
    } == {
        "x_min": -np.pi,
        "x_max": np.pi,
        "y_min": -0.5 * np.pi,
        "y_max": 0.5 * np.pi,
    }
    scene = SceneCompiler().compile(
        [command], projection, style, width=1000, height=500, transparent=False
    )
    assert scene.viewport["data_bounds"] == pytest.approx(
        {
            "x_min": -np.pi,
            "x_max": np.pi,
            "y_min": -0.5 * np.pi,
            "y_max": 0.5 * np.pi,
        }
    )
    assert scene.viewport["target_axes_width"] == pytest.approx(960.0)
    assert dict(scene.viewport["margin"]) == {
        "l": pytest.approx(20.0),
        "r": pytest.approx(20.0),
        "t": pytest.approx(10.0),
        "b": pytest.approx(10.0),
        "autoexpand": False,
    }


def test_python_benchmark_aggregates_isolated_stage_results(monkeypatch):
    from contextlib import redirect_stdout
    from io import StringIO

    worker_result = {
        "arrow_payload_bytes": 900,
        "external_html_bytes": 100,
        "legacy_renderer_preparation_seconds": 0.25,
        "legacy_renderer_total_seconds": 1.5,
        "payload_bytes": 1000,
        "peak_rss_mb": 20.0,
        "plotly_construction_seconds": 1.25,
        "viewport_warm_ms": [1.0, 1.0],
    }
    calls = []

    def run_repeat(point_count, timeout_seconds):
        calls.append((point_count, timeout_seconds))
        return worker_result

    monkeypatch.setattr(benchmark, "_run_python_repeat", run_repeat)
    browser_calls = []

    def run_browser(point_count, repeats, fixture_timeout_seconds):
        browser_calls.append((point_count, repeats, fixture_timeout_seconds))
        browser_result = complete_browser_result(repeats=1)
        browser_result["arrow_payload_bytes"] = 900
        return browser_result

    monkeypatch.setattr(benchmark, "run_browser_benchmark", run_browser)
    plot_type_coverage = complete_plot_type_coverage()
    monkeypatch.setattr(
        benchmark,
        "run_recorded_plot_type_coverage",
        lambda: plot_type_coverage,
    )
    browser_diagnostics = plot_type_coverage["browser"]
    browser_diagnostic_calls = []

    def run_plot_type_browser_diagnostics(repeats):
        browser_diagnostic_calls.append(repeats)
        return browser_diagnostics

    monkeypatch.setattr(
        benchmark,
        "run_recorded_plot_type_browser_diagnostics",
        run_plot_type_browser_diagnostics,
    )

    stdout = StringIO()
    with redirect_stdout(stdout):
        result = benchmark.run_python_benchmark(
            point_count=10,
            repeats=1,
            repeat_timeout_seconds=2.0,
        )

    benchmark.validate_benchmark_artifact(result)
    assert calls == [(10, 2.0), (10, 2.0)]
    assert browser_calls == [(10, 1, 2.0)]
    assert browser_diagnostic_calls == [1]
    assert result["scene_compile"]["median_seconds"] == 0.25
    assert result["artifact_role"] == "candidate"
    assert result["schema_version"] == benchmark.BENCHMARK_SCHEMA_VERSION
    assert result["legacy_renderer_total"]["median_seconds"] == 1.5
    assert result["legacy_renderer_preparation"]["median_seconds"] == 0.25
    assert result["plotly_construction"]["median_seconds"] == 1.25
    assert result["peak_rss_mb"] == 20.0
    assert result["arrow_payload_bytes"] == 900
    assert result["external_html_bytes"] == 100
    assert result["viewport_warm"] == {"median_ms": 1.0, "p95_ms": 1.0}
    assert result["plot_type_coverage"] is plot_type_coverage
    output = stdout.getvalue()
    assert "Python warm-up: starting" in output
    assert "Python repeat 1/1: complete" in output


def test_python_benchmark_measures_browser_before_cpu_intensive_samples(monkeypatch):
    events = []
    worker_result = {
        "arrow_payload_bytes": 900,
        "external_html_bytes": 100,
        "legacy_renderer_preparation_seconds": 0.25,
        "legacy_renderer_total_seconds": 1.5,
        "payload_bytes": 1000,
        "peak_rss_mb": 20.0,
        "plotly_construction_seconds": 1.25,
        "viewport_warm_ms": [1.0, 1.0],
    }

    def run_samples(point_count, repeats, timeout_seconds, *, label):
        events.append(label)
        return [worker_result]

    def run_browser(*args, **kwargs):
        events.append("browser")
        result = complete_browser_result(repeats=1)
        result["arrow_payload_bytes"] = 900
        return result

    def run_coverage():
        events.append("coverage")
        return complete_plot_type_coverage()

    def run_browser_diagnostics(repeats):
        events.append("browser diagnostics")
        return complete_plot_type_coverage()["browser"]

    monkeypatch.setattr(benchmark, "_run_python_samples", run_samples)
    monkeypatch.setattr(benchmark, "run_browser_benchmark", run_browser)
    monkeypatch.setattr(benchmark, "run_recorded_plot_type_coverage", run_coverage)
    monkeypatch.setattr(
        benchmark,
        "run_recorded_plot_type_browser_diagnostics",
        run_browser_diagnostics,
    )

    benchmark.run_python_benchmark(
        point_count=10,
        repeats=1,
        repeat_timeout_seconds=2.0,
        ordinary_points=5,
    )

    assert events == [
        "browser",
        "browser diagnostics",
        "Python",
        "Ordinary chart",
        "coverage",
    ]


def test_recorded_plot_type_browser_diagnostics_measures_each_family(monkeypatch):
    from contextlib import contextmanager

    fixtures = {
        name: {
            "arrow_payload_bytes": 100 + index,
            "scene_hash": f"sha256:{name}",
            "source_url": f"http://127.0.0.1:4321/{name}.html",
        }
        for index, name in enumerate(("map", "horizon", "zenith", "optic"))
    }

    @contextmanager
    def fixture():
        yield fixtures

    class Page:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class BrowserContext:
        def __init__(self):
            self.pages = []
            self.closed = False

        def new_page(self):
            page = Page()
            self.pages.append(page)
            return page

        def close(self):
            self.closed = True

    class Browser:
        version = "test-browser"

        def __init__(self):
            self.context = None
            self.closed = False

        def new_context(self, viewport):
            assert viewport == {"width": 1000, "height": 500}
            self.context = BrowserContext()
            return self.context

        def close(self):
            self.closed = True

    browser = Browser()
    playwright = object()

    class PlaywrightContext:
        def __enter__(self):
            return playwright

        def __exit__(self, *args):
            return False

    fake_sync_api = SimpleNamespace(sync_playwright=lambda: PlaywrightContext())
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)
    monkeypatch.setattr(benchmark, "_recorded_plot_type_browser_fixture", fixture)
    monkeypatch.setattr(benchmark, "_launch_browser", lambda value: browser)
    calls = {name: 0 for name in fixtures}

    def measure(page, uri, timeout_ms):
        assert timeout_ms == benchmark._BROWSER_TIMEOUT_MS
        name = Path(uri).stem
        calls[name] += 1
        return float(10 * calls[name])

    monkeypatch.setattr(benchmark, "_measure_browser_page", measure)

    result = benchmark.run_recorded_plot_type_browser_diagnostics(repeats=2)

    assert result["status"] == "measured"
    assert result["engine_version"] == "test-browser"
    assert set(result["plot_types"]) == {"map", "horizon", "zenith", "optic"}
    assert calls == {"map": 3, "horizon": 3, "zenith": 3, "optic": 3}
    assert all(page.closed for page in browser.context.pages)
    assert browser.context.closed
    assert browser.closed
    for name, evidence in result["plot_types"].items():
        assert evidence["complete_render_median_ms"] == 25.0
        assert evidence["complete_render_p95_ms"] == pytest.approx(29.5)
        assert evidence["scene_hash"] == f"sha256:{name}"


def test_primary_browser_measures_each_source_as_an_isolated_series(monkeypatch):
    from contextlib import contextmanager

    @contextmanager
    def fixture(point_count, timeout_seconds):
        assert point_count == 10
        assert timeout_seconds == 12.0
        yield {
            "arrow_payload_bytes": 123,
            "legacy_source_kind": "direct-plotly-same-scene-http",
            "legacy_source_url": "http://127.0.0.1/legacy.html",
            "scene_hash": f"sha256:{'a' * 64}",
            "source_kind": "external-arrow-http",
            "source_url": "http://127.0.0.1/scene.html",
        }

    class Page:
        def close(self):
            pass

    contexts = []

    class BrowserContext:
        def __init__(self):
            self.page_count = 0

        def new_page(self):
            self.page_count += 1
            return Page()

        def close(self):
            pass

    class Browser:
        version = "test-browser"

        def new_context(self, viewport):
            assert viewport == {"width": 1000, "height": 500}
            context = BrowserContext()
            contexts.append(context)
            return context

        def close(self):
            pass

    class PlaywrightContext:
        def __enter__(self):
            return object()

        def __exit__(self, *args):
            return False

    fake_sync_api = SimpleNamespace(sync_playwright=lambda: PlaywrightContext())
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)
    monkeypatch.setattr(benchmark, "_external_browser_fixture", fixture)
    monkeypatch.setattr(benchmark, "_launch_browser", lambda playwright: Browser())
    measured_urls = []

    def measure(page, url, timeout_ms):
        measured_urls.append(url)
        return float(len(measured_urls))

    monkeypatch.setattr(benchmark, "_measure_browser_page", measure)

    result = benchmark.run_browser_benchmark(
        point_count=10,
        repeats=2,
        fixture_timeout_seconds=12.0,
    )

    assert measured_urls == [
        "http://127.0.0.1/scene.html",
        "http://127.0.0.1/legacy.html",
        "http://127.0.0.1/legacy.html",
        "http://127.0.0.1/scene.html",
        "http://127.0.0.1/scene.html",
        "http://127.0.0.1/legacy.html",
    ]
    assert [context.page_count for context in contexts] == [3, 3]
    assert result["status"] == "measured"
    assert result["cold_start_ms"] == 1.0
    assert result["raw_warm_repeats_ms"] == [4.0, 5.0]
    assert result["legacy_same_scene"]["cold_start_ms"] == 2.0
    assert result["legacy_same_scene"]["raw_warm_repeats_ms"] == [3.0, 6.0]


def test_python_repeat_timeout_is_fatal(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"])

    monkeypatch.setattr(benchmark.subprocess, "run", timeout)

    with pytest.raises(RuntimeError, match="timed out after 0.01 seconds"):
        benchmark._run_python_repeat(point_count=10, timeout_seconds=0.01)


def test_browser_page_waits_for_instrumented_plotly_promise_and_final_paint():
    events = []

    class FakePage:
        def add_init_script(self, script):
            events.append(("init", script))

        def goto(self, uri, wait_until, timeout):
            events.append(("goto", uri, wait_until, timeout))

        def wait_for_function(self, predicate, timeout):
            events.append(("wait", predicate, timeout))

        def evaluate(self, expression):
            events.append(("evaluate", expression))
            return 987.6

    page = FakePage()
    elapsed = benchmark._measure_browser_page(page, "file:///plot.html", 1234)

    assert elapsed == 987.6
    assert [event[0] for event in events] == ["init", "goto", "wait", "evaluate"]
    init_script = events[0][1]
    assert "newPlot" in init_script
    assert "react" in init_script
    assert "Promise.resolve" in init_script
    assert init_script.count("requestAnimationFrame") >= 2
    completion_predicate = events[2][1]
    assert "starplotCompletedAt !== null" in completion_predicate
    assert "__starplotBenchmark.complete === true" in completion_predicate
    assert "requestAnimationFrame" not in completion_predicate
    assert "starplotCompletedAt" in events[3][1]
    assert "completedAt" in events[3][1]


def test_browser_launcher_falls_back_to_system_chrome(monkeypatch):
    launched_browser = object()

    class Chromium:
        def __init__(self):
            self.calls = []

        def launch(self, **kwargs):
            self.calls.append(kwargs)
            if "executable_path" not in kwargs:
                raise RuntimeError("bundled browser missing")
            return launched_browser

    chromium = Chromium()
    playwright = type("Playwright", (), {"chromium": chromium})()
    chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    monkeypatch.setattr(benchmark, "_system_chrome_executable", lambda: chrome)

    assert benchmark._launch_browser(playwright) is launched_browser
    assert chromium.calls == [
        {"headless": True},
        {"executable_path": str(chrome), "headless": True},
    ]


def test_python_repeat_parses_isolated_worker_result(monkeypatch):
    expected = {
        "legacy_renderer_preparation_seconds": 0.1,
        "legacy_renderer_total_seconds": 0.3,
        "payload_bytes": 123,
        "peak_rss_mb": 45.0,
        "plotly_construction_seconds": 0.2,
    }
    completed = SimpleNamespace(stdout=json.dumps(expected), stderr="")

    def run(command, **kwargs):
        assert "--python-worker" in command
        assert kwargs["timeout"] == 12.0
        return completed

    monkeypatch.setattr(benchmark.subprocess, "run", run)

    assert benchmark._run_python_repeat(10, 12.0) == expected


def test_browser_fixture_export_runs_in_isolated_worker(monkeypatch, tmp_path):
    expected = {
        "arrow_payload_bytes": 123,
        "scene_hash": "scene-hash",
    }
    completed = SimpleNamespace(stdout=json.dumps(expected), stderr="")

    def run(command, **kwargs):
        assert command[:2] == [sys.executable, str(Path(benchmark.__file__).resolve())]
        assert "--browser-fixture-worker" in command
        assert command[command.index("--browser-fixture-output") + 1] == str(tmp_path)
        assert command[command.index("--points") + 1] == "10"
        assert kwargs["cwd"] == benchmark._REPOSITORY_ROOT
        assert kwargs["capture_output"] is True
        assert kwargs["check"] is True
        assert kwargs["text"] is True
        assert kwargs["timeout"] == 12.0
        return completed

    monkeypatch.setattr(benchmark.subprocess, "run", run)

    assert benchmark._export_browser_fixture(10, tmp_path, 12.0) == expected


def test_browser_fixture_export_timeout_is_fatal(monkeypatch, tmp_path):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"])

    monkeypatch.setattr(benchmark.subprocess, "run", timeout)

    with pytest.raises(RuntimeError, match="timed out after 12.0 seconds"):
        benchmark._export_browser_fixture(10, tmp_path, 12.0)


def test_browser_fixture_worker_exports_arrow_and_same_scene_legacy():
    import inspect

    source = inspect.getsource(benchmark._run_browser_fixture_worker)

    assert "SceneCompiler" in source
    assert "DataMode.EXTERNAL" in source
    assert "PlotlySceneAdapter().render(scene)" in source
    assert "include_plotlyjs=False" in source
    assert "match.group(0)" in source


def test_browser_fixture_worker_shares_the_custom_plotly_asset(tmp_path):
    result = benchmark._run_browser_fixture_worker(10, tmp_path)

    assert result["arrow_payload_bytes"] > 0
    scene_html = (tmp_path / "scene.html").read_text(encoding="utf-8")
    legacy_html = (tmp_path / "legacy.html").read_text(encoding="utf-8")
    expected = "scene.scene/assets/plotly-starplot-3.3.1.min.js"
    assert scene_html.count(expected) == 1
    assert legacy_html.count(expected) == 1
    assert (
        tmp_path / "scene.scene" / "assets" / "plotly-starplot-3.3.1.min.js"
    ).is_file()


def test_browser_fixture_starts_server_only_after_isolated_export(
    monkeypatch, tmp_path
):
    events = []

    def export(point_count, output_directory, timeout_seconds):
        assert point_count == 10
        assert output_directory.is_dir()
        assert timeout_seconds == 12.0
        events.append("worker_exited")
        return {"arrow_payload_bytes": 123, "scene_hash": "scene-hash"}

    class Server:
        server_address = ("127.0.0.1", 4321)

        def serve_forever(self):
            events.append("server_served")

        def shutdown(self):
            events.append("server_shutdown")

        def server_close(self):
            events.append("server_closed")

    def create_server(root, host, port):
        assert events == ["worker_exited"]
        assert root.is_dir()
        assert host == "127.0.0.1"
        assert port == 0
        events.append("server_created")
        return Server()

    monkeypatch.setattr(benchmark, "_export_browser_fixture", export)
    monkeypatch.setattr("starplot.cli.create_server", create_server)
    with benchmark._external_browser_fixture(10, 12.0) as fixture:
        assert fixture["source_url"] == "http://127.0.0.1:4321/scene.html"
        assert fixture["legacy_source_url"] == "http://127.0.0.1:4321/legacy.html"
        assert fixture["arrow_payload_bytes"] == 123
        assert fixture["scene_hash"] == "scene-hash"

    assert events[0:2] == ["worker_exited", "server_created"]


def test_benchmark_worker_uses_scene_compiler_and_adapter_source():
    import inspect

    source = inspect.getsource(benchmark._run_python_worker)

    assert "SceneCompiler" in source
    assert "PlotlySceneAdapter" in source
    assert "_clip_command" not in source


def test_recorded_plot_type_coverage_exercises_every_public_plot_family():
    import matplotlib.pyplot as plt

    open_figures_before = set(plt.get_fignums())
    coverage = benchmark.run_recorded_plot_type_coverage()

    assert "real recording/SceneCompiler/PlotlySceneAdapter" in coverage["semantics"]
    assert set(coverage["plot_types"]) == {"map", "horizon", "zenith", "optic"}
    assert {
        name: result["plot_kind"]
        for name, result in coverage["plot_types"].items()
    } == {"map": "map", "horizon": "horizon", "zenith": "zenith", "optic": "optic"}
    for result in coverage["plot_types"].values():
        assert result["recorded_command_count"] > 0
        assert result["scene_layer_count"] > 0
        assert result["rendered_primitive_count"] > 0
        assert result["scene_compile_seconds"] >= 0
        assert result["plotly_render_seconds"] >= 0
    assert set(plt.get_fignums()) == open_figures_before


def test_host_fingerprint_distinguishes_nodes_without_exposing_node(monkeypatch):
    monkeypatch.setattr(benchmark.platform, "processor", lambda: "test-cpu")
    monkeypatch.setattr(benchmark.platform, "machine", lambda: "test-machine")
    monkeypatch.setattr(benchmark.platform, "platform", lambda: "test-os")
    monkeypatch.setattr(benchmark.os, "cpu_count", lambda: 8)

    private_node_one = "private-host-one.example"
    private_node_two = "private-host-two.example"
    monkeypatch.setattr(benchmark.platform, "node", lambda: private_node_one)
    fingerprint_one = benchmark._host_fingerprint()
    monkeypatch.setattr(benchmark.platform, "node", lambda: private_node_two)
    fingerprint_two = benchmark._host_fingerprint()

    assert fingerprint_one != fingerprint_two
    assert private_node_one not in fingerprint_one
    assert private_node_two not in fingerprint_two
    assert len(fingerprint_one) == 16
