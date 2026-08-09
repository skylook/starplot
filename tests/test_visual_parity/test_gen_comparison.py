"""Unit tests for the visual parity comparison harness helpers."""

import hashlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip("starplot")
from starplot.interactive.scene import (
    ColumnarData,
    CoordinateEncoding,
    CoordinateEncodingKind,
    CoordinateSpace,
    InteractionPolicy,
    SceneKind,
    SceneLayer,
    ScenePackage,
)
from starplot.interactive.web_export import export_scene_html
import tools.visual_parity.gen_comparison as gen
import tools.visual_parity._example_runner as runner


def test_visual_evidence_provenance_binds_revision_dirty_state_and_assets(
    monkeypatch, tmp_path
):
    loader = tmp_path / "src/starplot/interactive/assets/starplot-scene-loader.js"
    adapter = tmp_path / "src/starplot/interactive/assets/plotly-scene-adapter.js"
    loader.parent.mkdir(parents=True)
    loader.write_bytes(b"loader")
    adapter.write_bytes(b"adapter")

    def fake_git_stdout(root, *args):
        assert root == tmp_path
        if args == ("rev-parse", "HEAD"):
            return "a" * 40 + "\n"
        if args == ("status", "--porcelain", "--untracked-files=no"):
            return " M src/starplot/example.py\n"
        raise AssertionError(args)

    monkeypatch.setattr(gen, "_git_stdout", fake_git_stdout)

    assert gen._visual_evidence_provenance(tmp_path) == {
        "git_revision": "a" * 40,
        "tracked_dirty": True,
        "assets": {
            "src/starplot/interactive/assets/starplot-scene-loader.js": hashlib.sha256(
                b"loader"
            ).hexdigest(),
            "src/starplot/interactive/assets/plotly-scene-adapter.js": hashlib.sha256(
                b"adapter"
            ).hexdigest(),
        },
    }


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


def test_read_inline_export_decodes_base64_canonical_manifest(tmp_path):
    layer = SceneLayer(
        id="x</script><script>globalThis.pwn=1</script><script>",
        kind=SceneKind.SCATTER,
        zorder=1,
        load_priority=1,
        space=CoordinateSpace.DATA,
        clip_id=None,
        style={"marker": {"symbol": "circle"}, "palette_id": "stars"},
        palette=("#ffffff",),
        interaction=InteractionPolicy.HOVER,
        hover_fields=(),
        coordinate_encoding={
            "x": CoordinateEncoding(CoordinateEncodingKind.ABSOLUTE_F64),
            "y": CoordinateEncoding(CoordinateEncodingKind.ABSOLUTE_F64),
        },
        data=ColumnarData.from_mapping(
            {
                "x": np.array([1.0]),
                "y": np.array([2.0]),
                "size": np.array([3.0], dtype=np.float32),
                "color_index": np.array([0], dtype=np.uint8),
                "opacity": np.array([1.0], dtype=np.float32),
            }
        ),
    )
    scene = ScenePackage(
        layers=(layer,),
        projection_info={},
        style_info={},
        viewport={"reference_width": 100, "reference_height": 100},
        clips={},
        palettes={"stars": ("#ffffff",)},
    )
    exported = export_scene_html(
        scene,
        tmp_path / "chart.html",
        data_mode="inline",
        library_mode="cdn",
    )

    manifest_bytes, layer_bytes = gen._read_inline_export(exported.html_path)

    assert manifest_bytes == exported.manifest_bytes
    assert layer_bytes == exported.layer_bytes


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
