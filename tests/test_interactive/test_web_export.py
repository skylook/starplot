"""Delivery-mode contracts for Scene HTML exports."""

from __future__ import annotations

import base64
import json

import numpy as np
import pytest
from plotly.offline import get_plotlyjs_version

from starplot.interactive import (
    ColumnarData,
    DataMode,
    InteractionPolicy,
    LibraryMode,
    SceneKind,
    SceneLayer,
    ScenePackage,
    export_scene_html,
)
from starplot.interactive.commands import CoordinateSpace
from starplot.interactive.scene import CoordinateEncoding, CoordinateEncodingKind


def _scene(layer_id="stars") -> ScenePackage:
    layer = SceneLayer(
        id=layer_id,
        kind=SceneKind.SCATTER,
        zorder=1,
        load_priority=1,
        space=CoordinateSpace.DATA,
        clip_id=None,
        style={"marker": {"symbol": "circle"}, "palette_id": "stars"},
        palette=("#ffffff",),
        interaction=InteractionPolicy.HOVER,
        hover_fields=("name",),
        coordinate_encoding={
            "x": CoordinateEncoding(CoordinateEncodingKind.ABSOLUTE_F64),
            "y": CoordinateEncoding(CoordinateEncodingKind.ABSOLUTE_F64),
        },
        data=ColumnarData.from_mapping({
            "x": np.array([1.0]), "y": np.array([2.0]),
            "size": np.array([3.0], dtype=np.float32),
            "color_index": np.array([0], dtype=np.uint8),
            "opacity": np.array([1.0], dtype=np.float32),
            "name": np.array(["Rigel"]),
        }),
    )
    return ScenePackage(
        layers=(layer,), projection_info={}, style_info={},
        viewport={"reference_width": 100, "reference_height": 100}, clips={},
        palettes={"stars": ("#ffffff",)},
    )


@pytest.mark.parametrize(
    ("data_mode", "library_mode"),
    [
        (DataMode.INLINE, LibraryMode.CDN),
        (DataMode.EXTERNAL, LibraryMode.CDN),
        (DataMode.REMOTE, LibraryMode.CDN),
    ],
)
def test_modes_preserve_identical_scene_hash(tmp_path, data_mode, library_mode):
    expected = export_scene_html(
        _scene(), tmp_path / "chart.html", data_mode=DataMode.INLINE,
        library_mode=LibraryMode.CDN,
    )
    result = export_scene_html(
        _scene(), tmp_path / "chart.html", data_mode=data_mode,
        library_mode=library_mode,
        data_url="https://example.test/api/scenes/rigel",
    )
    assert result.scene_hash == expected.scene_hash
    assert result.manifest_bytes == expected.manifest_bytes
    assert result.layer_bytes["stars"]


def test_external_default_writes_hashed_arrow_bundle(tmp_path):
    result = export_scene_html(_scene(), tmp_path / "chart.html")
    assert result.bundle_path == tmp_path / "chart.scene"
    manifest = json.loads((result.bundle_path / "manifest.json").read_bytes())
    arrow = result.bundle_path / manifest["layers"][0]["data_source"]["uri"]
    assert arrow.read_bytes() == result.layer_bytes["stars"]
    assert manifest["layers"][0]["data_source"]["uri"].endswith(".arrow")
    assert len(manifest["layers"][0]["data_source"]["uri"].split("-")[1].split(".")[0]) == 64
    assert (result.bundle_path / "palettes.json").is_file()


def test_inline_embeds_exact_arrow_payload(tmp_path):
    result = export_scene_html(_scene(), tmp_path / "chart.html", data_mode="inline", library_mode="cdn")
    html = result.html_path.read_text(encoding="utf-8")
    payload = base64.b64encode(result.layer_bytes["stars"]).decode("ascii")
    assert payload in html
    assert 'application/vnd.apache.arrow.stream' in html


def test_remote_requires_safe_absolute_url(tmp_path):
    with pytest.raises(ValueError, match="data_url"):
        export_scene_html(_scene(), tmp_path / "chart.html", data_mode="remote")
    with pytest.raises(ValueError, match="http"):
        export_scene_html(_scene(), tmp_path / "chart.html", data_mode="remote", data_url="file:///tmp/scene")
    with pytest.raises(ValueError, match=".html"):
        export_scene_html(_scene(), tmp_path / "..", data_mode="inline")


def test_remote_shell_uses_exact_manifest_url(tmp_path):
    result = export_scene_html(
        _scene(), tmp_path / "chart.html", data_mode="remote",
        data_url="https://example.test/api/scenes/rigel",
    )
    html = result.html_path.read_text(encoding="utf-8")
    assert "RemoteSceneSource" in html
    assert "https://example.test/api/scenes/rigel" in html
    assert '"https://example.test"' in html
    assert "application/vnd.apache.arrow.stream" not in html


def test_allowed_data_origins_reject_paths_and_normalize_duplicates(tmp_path):
    with pytest.raises(ValueError, match="allowed_data_origins"):
        export_scene_html(
            _scene(), tmp_path / "chart.html", data_mode="remote",
            data_url="https://example.test/manifest.json",
            allowed_data_origins=("https://example.test/path",),
        )
    result = export_scene_html(
        _scene(), tmp_path / "chart.html", data_mode="remote",
        data_url="https://example.test/manifest.json",
        allowed_data_origins=("https://cdn.test/", "https://cdn.test"),
    )
    assert result.html_path.read_text(encoding="utf-8").count('"https://cdn.test"') == 1


def test_directory_libraries_are_written_inside_the_owned_bundle(tmp_path):
    result = export_scene_html(
        _scene(), tmp_path / "chart.html", library_mode=LibraryMode.DIRECTORY
    )
    html = result.html_path.read_text(encoding="utf-8")
    assert f'src="chart.scene/assets/plotly-{get_plotlyjs_version()}.min.js"' in html
    assert (result.bundle_path / "assets" / "starplot-scene-loader.js").is_file()
    assert (result.bundle_path / "assets" / "apache-arrow-21.1.0.min.js").is_file()


def test_untrusted_layer_ids_never_control_paths_or_html_ids(tmp_path):
    layer_id = 'x/../../escaped"></script><script>globalThis.pwn=1</script><script id="z'
    external = export_scene_html(_scene(layer_id), tmp_path / "chart.html")
    arrow_names = [path.name for path in external.bundle_path.glob("*.arrow")]
    assert len(arrow_names) == 1
    assert arrow_names[0].startswith("layer-")
    assert "/" not in arrow_names[0]
    inline = export_scene_html(_scene(layer_id), tmp_path / "inline.html", data_mode="inline", library_mode="cdn")
    html = inline.html_path.read_text(encoding="utf-8")
    assert "starplot-layer-0" in html
    assert "<script>globalThis.pwn=1</script>" not in html
