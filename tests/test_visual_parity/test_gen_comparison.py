"""Unit tests for the visual parity comparison harness helpers."""

from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("starplot")
import tools.visual_parity.gen_comparison as gen
import tools.visual_parity._example_runner as runner


def test_snapshot_pngs_lists_only_png_files(tmp_path):
    (tmp_path / "a.png").write_text("")
    (tmp_path / "b.png").write_text("")
    (tmp_path / "c.txt").write_text("")
    assert gen._snapshot_pngs(tmp_path) == {
        tmp_path / "a.png",
        tmp_path / "b.png",
    }


def test_find_new_png_prefers_expected_name(tmp_path):
    before = gen._snapshot_pngs(tmp_path)
    (tmp_path / "expected.png").write_text("")
    (tmp_path / "other.png").write_text("")
    found = gen._find_new_png(tmp_path, before, preferred_name="expected.png")
    assert found == tmp_path / "expected.png"


def test_find_new_png_ignores_excluded_files(tmp_path):
    before = frozenset()
    (tmp_path / "plotly.png").write_text("")
    (tmp_path / "wanted.png").write_text("")
    found = gen._find_new_png(
        tmp_path, before, excluded={"plotly.png"}
    )
    assert found == tmp_path / "wanted.png"


def test_find_new_png_rejects_multiple_new_candidates(tmp_path):
    before = frozenset()
    (tmp_path / "a.png").write_text("")
    (tmp_path / "b.png").write_text("")
    with pytest.raises(RuntimeError, match="expected one new PNG"):
        gen._find_new_png(tmp_path, before)


def test_find_new_png_rejects_no_output(tmp_path):
    before = frozenset()
    with pytest.raises(RuntimeError, match="no PNG was produced"):
        gen._find_new_png(tmp_path, before)


def test_comparison_runner_passes_relative_output_paths_to_safe_export(monkeypatch, tmp_path):
    """The harness must not turn example filenames into unsafe absolute paths."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STARPLOT_COMPARISON_TRANSPORTS", "inline,external")
    monkeypatch.setattr(runner.importlib.util, "find_spec", lambda _name: None)
    received = []

    def fake_export(_plot, filename, **_kwargs):
        received.append(Path(filename))
        return runner.ExportResult(
            html_path=tmp_path / filename,
            bundle_path=tmp_path / "chart.scene",
            scene_hash="scene",
            manifest_bytes=b"manifest",
            layer_bytes={"layer": b"payload"},
        )

    monkeypatch.setattr(runner, "_ORIG_EXPORT_HTML", fake_export)
    runner._comparison_export(SimpleNamespace(), "chart.html")

    assert received == [Path("chart.html"), Path("chart_inline.html")]
    assert all(not path.is_absolute() for path in received)
