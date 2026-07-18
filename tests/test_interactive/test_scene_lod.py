"""Viewport and LOD contracts for framework-neutral Scene delivery."""

from __future__ import annotations

import numpy as np
import pyarrow as pa
import pytest

from starplot.interactive import (
    ColumnarData,
    FullResolutionPolicy,
    MagnitudeLodPolicy,
    SceneKind,
    SceneLayer,
    ScenePackage,
    ViewportRequest,
    export_scene_html,
)
from starplot.interactive.commands import CoordinateSpace
from starplot.interactive.scene import CoordinateEncoding, CoordinateEncodingKind
from starplot.interactive.scene_manifest import SceneManifestModel
from starplot.interactive.scene_provider import SceneProvider


def _layer(layer_id: str, columns: dict[str, np.ndarray]) -> SceneLayer:
    return SceneLayer(
        id=layer_id,
        kind=SceneKind.SCATTER,
        zorder=1,
        load_priority=1,
        space=CoordinateSpace.DATA,
        clip_id=None,
        style={"marker": {"symbol": "circle"}},
        data=ColumnarData.from_mapping(columns),
        coordinate_encoding={
            "x": CoordinateEncoding(CoordinateEncodingKind.ABSOLUTE_F64),
            "y": CoordinateEncoding(CoordinateEncodingKind.ABSOLUTE_F64),
        },
    )


@pytest.fixture
def provider(tmp_path):
    stars = _layer(
        "stars",
        {
            "x": np.array([-2.0, -0.5, 0.0, 0.5, 2.0]),
            "y": np.array([0.0, -3.0, 0.0, 1.0, 0.0]),
            "size": np.ones(5, dtype=np.float32),
            "color_index": np.zeros(5, dtype=np.uint8),
            "opacity": np.ones(5, dtype=np.float32),
            "magnitude": np.array([5.0, 3.0, 1.0, 2.0, 0.0], dtype=np.float32),
        },
    )
    guides = _layer(
        "guides",
        {
            "x": np.array([-2.0, 0.0, 2.0]),
            "y": np.zeros(3),
            "size": np.ones(3, dtype=np.float32),
            "color_index": np.zeros(3, dtype=np.uint8),
            "opacity": np.ones(3, dtype=np.float32),
        },
    )
    scene = ScenePackage(
        layers=(stars, guides),
        projection_info={},
        style_info={},
        clips={},
        palettes={},
        viewport={"reference_width": 100, "reference_height": 100},
    )
    result = export_scene_html(scene, tmp_path / "chart.html")
    manifest = SceneManifestModel.model_validate_json(result.manifest_bytes)
    return SceneProvider(
        manifest,
        result.manifest_bytes,
        result.layer_bytes,
        lod_policies={"stars": MagnitudeLodPolicy()},
    )


def _decoded(provider, layer_id, request):
    response = provider.layer(layer_id, request)
    with pa.ipc.open_stream(response.body_bytes()) as reader:
        return reader.read_all()


def test_viewport_filter_uses_final_scene_coordinates(provider):
    request = ViewportRequest(
        x_min=-1,
        x_max=1,
        y_min=-2,
        y_max=2,
        pixel_width=800,
        pixel_height=600,
        lod=1,
    )
    layer = _decoded(provider, "stars", request)
    x, y = (layer.column(name).to_numpy() for name in ("x", "y"))
    assert np.all((-1 <= x) & (x <= 1))
    assert np.all((-2 <= y) & (y <= 2))


def test_full_resolution_request_is_exact_complete_layer(provider):
    assert (
        provider.layer("stars", ViewportRequest.full()).body_bytes()
        == provider.layer("stars").body_bytes()
    )


def test_magnitude_lod_keeps_brightest_visible_rows_before_fainter_rows(provider):
    request = ViewportRequest(x_min=-3, x_max=3, y_min=-4, y_max=2, point_budget=2)
    layer = _decoded(provider, "stars", request)
    assert sorted(layer.column("magnitude").to_pylist()) == [0.0, 1.0]


def test_unconfigured_layers_use_full_resolution_policy(provider):
    request = ViewportRequest(x_min=-1, x_max=1, y_min=-1, y_max=1)
    layer = _decoded(provider, "guides", request)
    assert layer.column("x").to_pylist() == [0.0]


def test_viewport_request_validates_bounds_and_has_generic_cache_parts():
    with pytest.raises(ValueError, match="x_min"):
        ViewportRequest(x_min=2, x_max=1)
    request = ViewportRequest(x_min=0, x_max=1, pixel_width=100, lod=2)
    assert request.cache_key_parts() == (0.0, 1.0, None, None, 100, None, 2, None, None)


def test_viewport_filter_decodes_relative_transport_coordinates_before_cropping():
    layer = _layer(
        "relative",
        {
            "x": np.array([0.0, 1.0], dtype=np.float32),
            "y": np.array([0.0, 0.0], dtype=np.float32),
            "size": np.ones(2, dtype=np.float32),
            "color_index": np.zeros(2, dtype=np.uint8),
            "opacity": np.ones(2, dtype=np.float32),
        },
    )
    layer = SceneLayer(
        **{
            **layer.__dict__,
            "coordinate_encoding": {
                "x": CoordinateEncoding(CoordinateEncodingKind.RELATIVE_F32, origin=100, scale=10),
                "y": CoordinateEncoding(CoordinateEncodingKind.RELATIVE_F32, origin=0, scale=1),
            },
        }
    )
    selected = FullResolutionPolicy().select(
        layer, ViewportRequest(x_min=109, x_max=111, y_min=-1, y_max=1)
    )
    assert selected.tolist() == [False, True]
