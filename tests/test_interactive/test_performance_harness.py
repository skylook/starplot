import json
from pathlib import Path
import subprocess
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


def complete_result():
    summary = {"median_seconds": 1.0, "p95_seconds": 1.2}
    return {
        "browser": {"complete_render_median_ms": 100.0},
        "environment": ENVIRONMENT,
        "legacy_renderer_preparation": summary,
        "legacy_renderer_total": summary,
        "payload_bytes": 1000,
        "peak_rss_mb": 10.0,
        "plotly_construction": summary,
        "point_count": 100,
        "scene_compile": {
            **summary,
            "semantics": "compatibility alias for legacy_renderer_total",
        },
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


def test_benchmark_summary_reports_median_and_p95():
    assert benchmark.summarize([1.0, 2.0, 3.0, 4.0]) == {
        "median_seconds": 2.5,
        "p95_seconds": pytest.approx(3.85),
    }


def test_compare_results_reports_every_missed_performance_gate():
    before = complete_result()
    after = {
        **complete_result(),
        "environment": ENVIRONMENT,
        "scene_compile": {"median_seconds": 0.75, "p95_seconds": 0.8},
        "peak_rss_mb": 7.0,
        "arrow_payload_bytes": 31 * 1024 * 1024,
        "external_html_bytes": 2 * 1024 * 1024,
        "browser": {"complete_render_median_ms": 80.0},
        "ordinary_chart": {"median_seconds": 1.2},
        "viewport_warm": {"median_ms": 501.0, "p95_ms": 1001.0},
    }
    before["ordinary_chart"] = {"median_seconds": 1.0}

    failures = benchmark.compare_results(before, after)

    assert len(failures) == 8
    assert any("scene_compile" in failure for failure in failures)
    assert any("peak_rss" in failure for failure in failures)
    assert any("arrow_payload" in failure for failure in failures)
    assert any("external_html" in failure for failure in failures)
    assert any("browser_complete" in failure for failure in failures)
    assert any("ordinary_chart" in failure for failure in failures)
    assert any("viewport_warm_median" in failure for failure in failures)
    assert any("viewport_warm_p95" in failure for failure in failures)


def test_compare_results_rejects_unmeasured_metrics_and_host_mismatch():
    before = complete_result()
    after = complete_result()
    after["environment"] = {**ENVIRONMENT, "host_fingerprint": "other-host"}

    failures = benchmark.compare_results(before, after)

    assert any("host_fingerprint" in failure for failure in failures)
    assert any("arrow_payload_bytes is missing" in failure for failure in failures)
    assert any("external_html_bytes is missing" in failure for failure in failures)
    assert any("ordinary_chart baseline is missing" in failure for failure in failures)
    assert any("viewport_warm_median is missing" in failure for failure in failures)


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


def test_python_benchmark_aggregates_isolated_stage_results(monkeypatch, capsys):
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
    monkeypatch.setattr(
        benchmark,
        "run_browser_benchmark",
        lambda point_count, repeats: {
            "complete_render_median_ms": None,
            "engine": "chromium",
            "engine_version": "test",
            "status": "test",
        },
    )

    result = benchmark.run_python_benchmark(
        point_count=10,
        repeats=1,
        repeat_timeout_seconds=2.0,
    )

    benchmark.validate_benchmark_artifact(result)
    assert calls == [(10, 2.0), (10, 2.0)]
    assert result["scene_compile"]["median_seconds"] == 0.25
    assert result["legacy_renderer_total"]["median_seconds"] == 1.5
    assert result["legacy_renderer_preparation"]["median_seconds"] == 0.25
    assert result["plotly_construction"]["median_seconds"] == 1.25
    assert result["peak_rss_mb"] == 20.0
    assert result["arrow_payload_bytes"] == 900
    assert result["external_html_bytes"] == 100
    assert result["viewport_warm"] == {"median_ms": 1.0, "p95_ms": 1.0}
    output = capsys.readouterr().out
    assert "Python warm-up: starting" in output
    assert "Python repeat 1/1: complete" in output


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

    page = FakePage()
    elapsed = benchmark._measure_browser_page(page, "file:///plot.html", 1234)

    assert elapsed >= 0
    assert [event[0] for event in events] == ["init", "goto", "wait"]
    init_script = events[0][1]
    assert "newPlot" in init_script
    assert "react" in init_script
    assert "Promise.resolve" in init_script
    assert init_script.count("requestAnimationFrame") >= 2
    assert "__starplotBenchmark.complete === true" in events[2][1]


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


def test_benchmark_worker_uses_scene_compiler_and_adapter_source():
    import inspect

    source = inspect.getsource(benchmark._run_python_worker)

    assert "SceneCompiler" in source
    assert "PlotlySceneAdapter" in source
    assert "_clip_command" not in source


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
