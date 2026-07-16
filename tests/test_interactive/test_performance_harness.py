from pathlib import Path

import pytest

from benchmarks import interactive_scene_pipeline as benchmark
from benchmarks.interactive_scene_pipeline import validate_result


def test_benchmark_result_schema_rejects_missing_metrics():
    with pytest.raises(ValueError, match="scene_compile"):
        validate_result({"environment": {}, "point_count": 100})


def test_benchmark_result_schema_accepts_complete_result():
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


def test_benchmark_summary_reports_median_and_p95():
    assert benchmark.summarize([1.0, 2.0, 3.0, 4.0]) == {
        "median_seconds": 2.5,
        "p95_seconds": pytest.approx(3.85),
    }


def test_python_benchmark_produces_complete_result(monkeypatch):
    monkeypatch.setattr(
        benchmark,
        "run_browser_benchmark",
        lambda repeats: {"complete_render_median_ms": None, "status": "test"},
    )

    result = benchmark.run_python_benchmark(point_count=10, repeats=1)

    validate_result(result)
    assert result["point_count"] == 10
    assert result["scene_compile"]["median_seconds"] >= 0
    assert result["payload_bytes"] > 0


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
